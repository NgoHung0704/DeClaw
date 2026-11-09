"""The ``/ws/events`` stream and its broadcaster (DCL-133, spec section 13).

ONE :class:`EventBroadcaster` fan-outs server-side event frames to every
connected ``/ws/events`` client: indexing progress from the single worker
(spec section 10), plugin enable/disable confirmations (spec section 11) and
watcher operational warnings.

Design rules carried over from the chat transport:

- Handshake: cookie authentication BEFORE accept (close 4401 without a valid
  session cookie; the foreign-Origin 4403 lives in the Host/Origin
  middleware and covers this endpoint like every other WebSocket).
- One bounded queue per subscriber. A subscriber that stops reading never
  stalls the server: the queue is drop-oldest with a warning — spectator
  slow-downs must not throttle the indexer or a healthy subscriber.
- Subscribers only receive; any inbound frame is an error frame away
  (rate-limited at the Task 4 per-connection bucket, closed 1009 above the
  32 KiB single-message cap by the middleware).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from declaw.gateway.auth import SESSION_COOKIE_NAME
from declaw.log import logger

# Per-subscriber bound: one spectator's unread backlog is capped; there is
# no legitimate event stream that needs more in flight than this.
SUBSCRIBER_QUEUE_MAXSIZE = 64

WS_UNAUTHENTICATED_CLOSE_CODE = 4401

ERROR_TYPE = "error"

INDEX_PROGRESS_TYPE = "index.progress"

PLUGIN_ENABLED_TYPE = "plugin.enabled"
PLUGIN_DISABLED_TYPE = "plugin.disabled"


class EventBroadcaster:
    """Bounded fan-out of server-side event frames (loop-owned).

    ``broadcast`` never blocks: each subscriber queue is bounded and
    drop-oldest, so a stalled client loses its oldest queued frames with an
    operational warning instead of stalling every producer.
    """

    def __init__(self, *, maxsize: int = SUBSCRIBER_QUEUE_MAXSIZE) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._maxsize = maxsize

    def subscribe(self, *, maxsize: int | None = None) -> asyncio.Queue[dict[str, Any]]:
        """Register a subscriber and return its bounded queue.

        ``maxsize`` overrides the broadcaster default per subscriber (a
        spectator that is known to read slowly can be given a smaller
        backlog); the bound is never removed: no queue is unbounded.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._maxsize if maxsize is None else maxsize
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Drop a subscriber; a stale queue never keeps receiving frames."""
        self._subscribers.discard(queue)

    def subscriber_count(self) -> int:
        """Number of live subscribers (status/wiring pin)."""
        return len(self._subscribers)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Fan one frame out to every current subscriber, bounded."""
        for queue in list(self._subscribers):
            self._put_bounded(queue, event)

    def _put_bounded(self, queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop the OLDEST queued frame: the subscriber sees the newest
            # state, and a stalled client can never stall the broadcaster.
            try:
                dropped = queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - contradicts QueueFull
                return
            logger.bind(
                event_type=str(dropped.get("type")),
                subscriber_backlog=self._maxsize,
            ).warning("gateway.events.subscriber_backlog_dropped")
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - space just freed
                pass


def plugin_state_change_frame(*, name: str, action: str) -> dict[str, Any]:
    """Build a plugin state-change confirmation frame (spec section 11)."""
    if action == "enabled":
        return {"type": PLUGIN_ENABLED_TYPE, "name": name}
    return {"type": PLUGIN_DISABLED_TYPE, "name": name}


router = APIRouter()


@router.websocket("/ws/events")
async def events_endpoint(websocket: WebSocket) -> None:
    """Serve the event stream to one authenticated connection."""
    state = websocket.scope["app"].state
    registry = state.session_registry
    cookie = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not isinstance(cookie, str) or not registry.validate(cookie):
        await websocket.close(code=WS_UNAUTHENTICATED_CLOSE_CODE, reason="authentication required")
        return

    broadcaster: EventBroadcaster = state.event_broadcaster
    limiter = state.rate_limiter
    # The connection key is the server-minted session id (validated above) —
    # the same convention as the Chat transport: never an attacker-supplied
    # string. Bucket state is evicted on disconnect.
    connection_key = f"events:{cookie}"

    await websocket.accept()
    queue = broadcaster.subscribe()

    async def sender() -> None:
        while True:
            frame = await queue.get()
            await websocket.send_json(frame)

    sender_task = asyncio.ensure_future(sender())
    try:
        # Broadcast frames flow out via the sender; any inbound frame is
        # illegitimate traffic and answers with a typed error frame
        # (rate-limited at the Task 4 per-connection bucket).
        while True:
            await websocket.receive_text()
            if not limiter.allow_ws_message(connection_key):
                await websocket.send_json({"type": ERROR_TYPE, "code": "rate_limited"})
            else:
                await websocket.send_json({"type": ERROR_TYPE, "code": "bad_frame"})
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        broadcaster.unsubscribe(queue)
        limiter.drop_connection(connection_key)
