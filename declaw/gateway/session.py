"""Gateway chat sessions: the per-connection actor (DCL-125, spec section 6).

Session = one authenticated ``/ws/chat`` connection. Each :class:`GatewaySession`
owns its message history, **one active turn at a time** (a second message during
a turn gets a typed ``busy`` error frame, not a queue), exactly **one bounded
outbound queue** (``asyncio.Queue``, 256) and **exactly one writer**. Every
frame — approval requests, terminal frames, errors — is published on that one
queue, so ordering and backpressure have a single owner. Two browser tabs are
two sessions with isolated histories; they share only stateless services.

Turn = one user message. Each turn creates a ``Task`` row whose ``id`` is the
turn id (so a client ``cancel {turn_id}`` cancels exactly its own turn), moves
it PENDING → RUNNING → COMPLETED (``result`` = final answer) / FAILED
(``error="cancelled by user"`` on cancellation and disconnect), and on
completion writes an ``Episode`` row linked by ``task_id`` with the final
answer truncated to 500 characters and empty tags — population plumbing, no
extra LLM call.

Task ID propagation: the turn coroutine sets ``current_task_id`` for its whole
body; direct and copied-context async work therefore audits with the turn's
task id through :class:`~declaw.audit.correlation.TaskCorrelatingAuditLogger`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect

from declaw.audit.correlation import current_task_id
from declaw.brain.repl import turn_failure_message
from declaw.config import Language
from declaw.db.models import Episode, Task, TaskStatus
from declaw.gateway.approval import ApprovalBroker
from declaw.gateway.middleware import RateLimiter
from declaw.log import logger

if TYPE_CHECKING:
    from declaw.brain.repl import AgentGraph
    from declaw.settings_service import EffectiveSettings

# Exactly one bounded outbound queue per session (spec section 6); producers
# await when it is full, so there is no unbounded buffering.
OUTBOUND_QUEUE_MAXSIZE = 256
# Episode summaries are the final answer truncated, never LLM-written.
EPISODE_SUMMARY_MAX_CHARS = 500

# Client frames (spec section 6/7).
MESSAGE_TYPE = "message"
CANCEL_TYPE = "cancel"
APPROVAL_RESPONSE_TYPE = "approval.response"

# Server frames.
TURN_STARTED_TYPE = "turn.started"
CHAT_FINAL_TYPE = "chat.final"
TURN_CANCELLED_TYPE = "turn.cancelled"
ERROR_TYPE = "error"

# Typed error codes carried by ``{"type": "error", "code": ...}`` frames.
ERROR_BUSY = "busy"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_BAD_FRAME = "bad_frame"
ERROR_TURN_FAILED = "turn_failed"

CANCELLED_BY_USER = "cancelled by user"
_FAIL_QUIET_TIMEOUT_SECONDS = 10.0


def _error(code: str, message: str, *, turn_id: str | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": ERROR_TYPE, "code": code, "message": message}
    if turn_id is not None:
        frame["turn_id"] = turn_id
    return frame


def _turn_error_summary(exc: Exception) -> str:
    """Short, user-reportable failure reason stored on the Task row."""
    first_line = str(exc).splitlines()[0] if str(exc).strip() else ""
    return f"{type(exc).__name__}: {first_line}"[:200].rstrip(": ")


def _reply_text(messages: list[BaseMessage]) -> str:
    """The most recent assistant message that carries visible text."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            content = message.content if isinstance(message.content, str) else str(message.content)
            if content.strip():
                return content
    return ""


async def _await_on_loop[T](
    loop: asyncio.AbstractEventLoop | None,
    factory: Callable[[], Coroutine[Any, Any, T]],
) -> T:
    """Await ``factory()`` on the session's own loop, from any loop.

    Production (uvicorn) runs sessions and shutdown on one loop, so this is a
    direct await. Callers on a foreign loop (a shutdown exercised from a test
    thread, a second dev-transport loop) use the thread-safe bridge: tasks
    must be cancelled and broker futures resolved on the loop that owns them.
    """
    if loop is None:
        return await factory()
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    if current is loop:
        return await factory()
    future = asyncio.run_coroutine_threadsafe(factory(), loop)
    return await asyncio.to_thread(future.result, 30)


class GatewaySession:
    """One connection's actor: history, one turn, one queue, one writer."""

    def __init__(
        self,
        session_id: str,
        *,
        language: Language,
        broker: ApprovalBroker,
        limiter: RateLimiter,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self.id = session_id
        self.language = language
        self.history: list[BaseMessage] = []
        self.outbound: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=OUTBOUND_QUEUE_MAXSIZE
        )
        self.loop: asyncio.AbstractEventLoop | None = None
        self._broker = broker
        self._limiter = limiter
        self._sessionmaker = sessionmaker
        self._graph: AgentGraph | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self.active_turn_id: str | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._closed = False
        self._writer_stopped = False

    # --- single-owner outbound transport ------------------------------------

    def enqueue(self, frame: dict[str, Any]) -> None:
        """Publish one frame on the bounded queue (the one writer drains it).

        The broker publishes approval requests through this same seam: it
        never touches a transport. After close the writer is gone, so frames
        are dropped with a log line rather than piling up.
        """
        if self._writer_stopped:
            logger.bind(session_id=self.id, frame_type=frame.get("type")).debug(
                "Frame dropped after session close"
            )
            return
        try:
            self.outbound.put_nowait(frame)
        except asyncio.QueueFull:
            # Bounded by design; M4 owns queue-full turn cancellation.
            logger.bind(session_id=self.id, frame_type=frame.get("type")).warning(
                "Outbound queue full - frame dropped"
            )

    def attach_graph(self, graph: AgentGraph) -> None:
        """Bind this session's graph (built with per-session tools/provider)."""
        self._graph = graph

    async def serve(self, websocket: WebSocket) -> None:
        """The connection main loop: writer + reader until disconnect."""
        self.loop = asyncio.get_running_loop()
        self._writer_task = asyncio.create_task(self._writer(websocket))
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    frame = json.loads(raw)
                except ValueError:
                    self.enqueue(_error(ERROR_BAD_FRAME, "frame is not valid JSON"))
                    continue
                await self._handle_frame(frame)
        except WebSocketDisconnect:
            pass
        finally:
            # The endpoint's shielded close() owns teardown; make sure the
            # writer drains and stops even if close() is called elsewhere.
            await self._stop_writer()

    async def _writer(self, websocket: WebSocket) -> None:
        while True:
            frame = await self.outbound.get()
            if frame is None:
                return
            try:
                await websocket.send_json(frame)
            except Exception as exc:  # the client is gone; nothing left to send
                logger.bind(session_id=self.id).debug(
                    "Outbound write failed ({}) - writer stopped", type(exc).__name__
                )
                return

    async def _stop_writer(self) -> None:
        if self._writer_task is None:
            return
        self._writer_stopped = True
        await self.outbound.put(None)
        with suppress(Exception):
            await asyncio.wait_for(asyncio.shield(self._writer_task), _FAIL_QUIET_TIMEOUT_SECONDS)
        self._writer_task = None

    # --- frame dispatch ------------------------------------------------------

    async def _handle_frame(self, frame: Any) -> None:
        if not isinstance(frame, dict):
            self.enqueue(_error(ERROR_BAD_FRAME, "frame must be a JSON object"))
            return
        kind = frame.get("type")
        if kind == MESSAGE_TYPE:
            text = frame.get("text")
            if not isinstance(text, str) or not text.strip():
                self.enqueue(_error(ERROR_BAD_FRAME, 'a "message" frame needs a non-empty "text"'))
                return
            await self._handle_message(text)
            return
        # Every other frame (cancel, approval replies, unknown types, junk)
        # shares the 30/second per-connection "other WS messages" bucket.
        if self._rate_limited():
            return
        if kind == CANCEL_TYPE:
            await self._handle_cancel(frame.get("turn_id"))
        elif kind == APPROVAL_RESPONSE_TYPE:
            # The broker accepts the reply only for this session's pending,
            # unexpired, unanswered requests (spec section 7.3).
            self._broker.handle_response(self.id, frame)
        else:
            self.enqueue(_error(ERROR_BAD_FRAME, f"unknown frame type {kind!r}"))

    def _rate_limited(self) -> bool:
        """Other WS messages: 30/second per connection (Task 4 bucket helper)."""
        if self._limiter.allow_ws_message(self.id):
            return False
        self.enqueue(_error(ERROR_RATE_LIMITED, "rate limit exceeded on this connection"))
        return True

    async def _handle_message(self, text: str) -> None:
        if self._turn_task is not None:
            self.enqueue(
                _error(
                    ERROR_BUSY,
                    "a turn is already in progress; wait for it to finish or cancel it",
                    turn_id=self.active_turn_id,
                )
            )
            return
        if not self._limiter.allow_chat_turn(self.id):
            self.enqueue(
                _error(ERROR_RATE_LIMITED, "chat turn limit exceeded; wait a moment")
            )
            return
        # The turn id IS the Task row id: cancel and audit correlate by it.
        turn_id = str(uuid.uuid4())
        self.active_turn_id = turn_id
        self._turn_task = asyncio.create_task(self._run_turn(turn_id, text))

    async def _handle_cancel(self, turn_id: Any) -> None:
        if not isinstance(turn_id, str) or turn_id != self.active_turn_id:
            logger.bind(session_id=self.id, turn_id=turn_id).warning(
                "Cancel for a non-active turn ignored"
            )
            return
        await self.abort_active()
        self.enqueue({"type": TURN_CANCELLED_TYPE, "turn_id": turn_id})

    # --- turn lifecycle ------------------------------------------------------

    async def _run_turn(self, turn_id: str, text: str) -> None:
        """One turn: Task row lifecycle + graph invocation (spec section 6)."""
        graph = self._graph
        if graph is None:  # pragma: no cover - the endpoint refuses such sessions
            raise RuntimeError("session graph was never bound")
        token = current_task_id.set(turn_id)
        completed = list(self.history)
        try:
            await self._insert_task_row(turn_id, text)
            await self._update_task(turn_id, status=TaskStatus.RUNNING)
            self.history.append(_human_message(text))
            self.enqueue({"type": TURN_STARTED_TYPE, "turn_id": turn_id})
            try:
                result = await graph.ainvoke({"messages": self.history})
            except asyncio.CancelledError:
                # The turn unwinds; the canceller (cancel/disconnect/shutdown)
                # writes the FAILED row itself: awaits can be re-cancelled here.
                self.history = completed
                raise
            reply = list(result["messages"])
            self.history = reply
            answer = _reply_text(reply)
            await self._update_task(turn_id, status=TaskStatus.COMPLETED, result=answer)
            await self._insert_episode(turn_id, answer)
            # Clear the busy marker before the terminal frame so the next
            # message after chat.final is never spuriously "busy".
            self._clear_turn(turn_id)
            self.enqueue({"type": CHAT_FINAL_TYPE, "turn_id": turn_id, "text": answer})
        except asyncio.CancelledError:
            self.history = completed
            raise
        except Exception as exc:
            self.history = completed
            logger.bind(session_id=self.id, turn_id=turn_id).exception("Chat turn failed")
            await self._fail_quietly(turn_id, _turn_error_summary(exc))
            self._clear_turn(turn_id)
            self.enqueue(
                {
                    "type": ERROR_TYPE,
                    "code": ERROR_TURN_FAILED,
                    "turn_id": turn_id,
                    "message": turn_failure_message(exc, self.language),
                }
            )
        finally:
            current_task_id.reset(token)

    async def abort_active(self) -> None:
        """Cancel the in-flight turn, mark it FAILED and deny its approvals.

        Called on client cancel, on disconnect, and (bridged) on gateway
        shutdown. Always runs on the session's own loop; Default deny (spec
        sections 6-7): nobody can answer a cancelled turn's approval.
        """
        task = self._turn_task
        turn_id = self.active_turn_id
        if task is None or task.done() or turn_id is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await self._fail_quietly(turn_id, CANCELLED_BY_USER)
        self._broker.deny_all(self.id, "turn cancelled")
        self._clear_turn(turn_id)

    async def abort_from_any_loop(self) -> None:
        """Shutdown-step bridge: abort even when called from another loop."""
        await _await_on_loop(self.loop, self.abort_active)

    async def deny_pending_from_any_loop(self) -> None:
        """Shutdown deny step: resolve this session's pending approvals."""

        async def deny() -> None:
            self._broker.deny_all(self.id, "gateway shutdown")

        await _await_on_loop(self.loop, deny)

    async def close(self) -> None:
        """Teardown on disconnect: cancel the turn, deny approvals, stop writer."""
        if self._closed:
            return
        self._closed = True
        await self.abort_active()
        self._broker.deny_all(self.id, "session closed")
        await self._stop_writer()

    def _clear_turn(self, turn_id: str) -> None:
        if self.active_turn_id == turn_id:
            self.active_turn_id = None
            self._turn_task = None

    # --- Task/Episode persistence -------------------------------------------

    async def _insert_task_row(self, turn_id: str, text: str) -> None:
        async with self._sessionmaker() as session:
            session.add(Task(id=turn_id, prompt=text, status=TaskStatus.PENDING))
            await session.commit()

    async def _update_task(self, turn_id: str, **values: Any) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(Task, turn_id)
            if row is None:  # pragma: no cover - insert happens first in-turn
                return
            for key, value in values.items():
                setattr(row, key, value)
            session.add(row)
            await session.commit()

    async def _insert_episode(self, turn_id: str, answer: str) -> None:
        async with self._sessionmaker() as session:
            session.add(
                Episode(
                    task_id=turn_id,
                    summary=answer[:EPISODE_SUMMARY_MAX_CHARS],
                    tags=[],
                )
            )
            await session.commit()

    async def _fail_quietly(self, turn_id: str, error: str) -> None:
        """Best-effort FAILED write; auditing must not take the agent down."""
        try:
            await self._update_task(turn_id, status=TaskStatus.FAILED, error=error)
        except Exception:
            logger.bind(session_id=self.id, turn_id=turn_id).exception(
                "Failed to persist FAILED task row"
            )


def _human_message(text: str) -> HumanMessage:
    return HumanMessage(content=text)


class SessionManager:
    """The live-connection registry and the session shutdown steps.

    The first three deterministic shutdown steps of spec section 5 live here
    as real handlers for the Application's constructor-injected hooks
    (Task 7's seam): stop accepting sessions, cancel in-flight turns, deny
    pending approvals. The CLI never builds a manager; its hooks stay unset.
    """

    def __init__(
        self,
        *,
        broker: ApprovalBroker,
        limiter: RateLimiter,
        sessionmaker: async_sessionmaker[AsyncSession] | None,
        graph_factory: Callable[[GatewaySession, EffectiveSettings], AgentGraph] | None = None,
    ) -> None:
        self._broker = broker
        self._limiter = limiter
        self._sessionmaker = sessionmaker
        self._graph_factory = graph_factory
        self._sessions: dict[str, GatewaySession] = {}
        self._accepting = True

    @property
    def accepting(self) -> bool:
        """False once shutdown began: new handshakes must be refused."""
        return self._accepting

    def create(self, snapshot: EffectiveSettings) -> GatewaySession:
        """Create one isolated session (its own history, queue and turn slot)."""
        if self._sessionmaker is None:  # pragma: no cover - guarded by endpoint
            raise RuntimeError("SessionManager has no sessionmaker")
        session = GatewaySession(
            str(uuid.uuid4()),
            language=snapshot.language,
            broker=self._broker,
            limiter=self._limiter,
            sessionmaker=self._sessionmaker,
        )
        if self._graph_factory is not None:
            session.attach_graph(self._graph_factory(session, snapshot))
        self._sessions[session.id] = session
        return session

    def drop(self, session: GatewaySession) -> None:
        """Unregister a dropped connection and evict its rate buckets."""
        self._sessions.pop(session.id, None)
        self._limiter.drop_connection(session.id)

    def get(self, session_id: str) -> GatewaySession | None:
        return self._sessions.get(session_id)

    async def stop_accepting_sessions(self) -> None:
        """Shutdown step 1: refuse new handshakes (existing ones continue)."""
        self._accepting = False

    async def cancel_in_flight_turns(self) -> None:
        """Shutdown step 2: cancel every live session's turn on its own loop."""
        for session in list(self._sessions.values()):
            await session.abort_from_any_loop()

    async def deny_pending_approvals(self) -> None:
        """Shutdown step 3: default deny for every pending approval."""
        for session in list(self._sessions.values()):
            await session.deny_pending_from_any_loop()
