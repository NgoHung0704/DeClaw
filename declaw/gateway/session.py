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

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect

from declaw.audit.correlation import current_task_id
from declaw.brain.repl import turn_failure_message
from declaw.config import Language
from declaw.db.models import Episode, Task, TaskStatus
from declaw.gateway.approval import ApprovalBroker
from declaw.gateway.middleware import RateLimiter
from declaw.gateway.sources import TurnSources, current_turn_sources
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
# Streaming frames (spec section 8): per-turn, one monotonically increasing
# ``seq`` spanning every frame kind that carries it.
CHAT_DELTA_TYPE = "chat.delta"
TOOL_START_TYPE = "tool.start"
TOOL_END_TYPE = "tool.end"

# Typed error codes carried by ``{"type": "error", "code": ...}`` frames.
ERROR_BUSY = "busy"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_BAD_FRAME = "bad_frame"
ERROR_TURN_FAILED = "turn_failed"
# Spec section 8 backpressure: the queue stayed full for the deadline, so the
# turn is cancelled. A dedicated code (an extension of the M3 set) so a
# client can tell "the model failed" from "you were not reading" apart.
ERROR_BACKPRESSURE = "backpressure"

CANCELLED_BY_USER = "cancelled by user"
_FAIL_QUIET_TIMEOUT_SECONDS = 10.0
# The streaming producer awaits the bounded queue for this long; a full queue
# for the whole deadline means the client is not reading (spec section 8).
BACKPRESSURE_TIMEOUT_SECONDS = 5.0
BACKPRESSURE_ROW_ERROR = "client not reading; turn cancelled"
# Tool result previews travel as truncated strings, never whole payloads.
TOOL_RESULT_PREVIEW_MAX_CHARS = 200


class OutboundBackpressure(Exception):
    """The outbound queue stayed full past the backpressure deadline."""


def _result_preview(output: Any) -> str:
    """A short textual preview of a tool result for ``tool.end`` frames."""
    content: Any
    if isinstance(output, ToolMessage):
        content = output.content
    elif isinstance(output, str):
        content = output
    else:
        content = str(output)
    text = content if isinstance(content, str) else str(content)
    return text[:TOOL_RESULT_PREVIEW_MAX_CHARS]


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
        backpressure_timeout: float = BACKPRESSURE_TIMEOUT_SECONDS,
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
        self._backpressure_timeout = backpressure_timeout
        self._graph: AgentGraph | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self.active_turn_id: str | None = None
        # The turn's terminal state, decided exactly once (see
        # ``_decide_terminal``): ``None`` while the turn is still in
        # flight, COMPLETED/FAILED once the single decision was made.
        self._terminal_state: TaskStatus | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._closed = False
        self._writer_stopped = False

    # --- single-owner outbound transport ------------------------------------

    def enqueue(self, frame: dict[str, Any]) -> None:
        """Publish one control frame on the bounded queue (one writer drains it).

        The broker's ``approval.request`` and the reader-side error/ack frames
        are singular control frames emitted outside the turn's event stream;
        they fire-and-forget here. After close the writer is gone, so frames
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
            # Bounded by design; control frames from a stalled connection are
            # dropped with a warning (fail-closed: an unread approval.request
            # times out and denies). Streaming frames never travel this seam -
            # the turn runner awaits (:meth:`_publish`) so a stalling client
            # cancels the turn instead (spec section 8).
            logger.bind(session_id=self.id, frame_type=frame.get("type")).warning(
                "Outbound queue full - control frame dropped"
            )

    async def _publish(self, frame: dict[str, Any]) -> None:
        """The turn runner's enqueue: the producer awaits (spec section 8).

        Streaming frames (turn.started, chat.delta, tool.start, tool.end,
        chat.final) travel through this seam only. A queue that stays full
        for the whole backpressure deadline means the client is not reading:
        no unbounded buffering, no silent drops - the turn is cancelled.
        """
        try:
            await asyncio.wait_for(self.outbound.put(frame), self._backpressure_timeout)
        except TimeoutError:
            raise OutboundBackpressure(str(frame.get("type"))) from None

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

    def _decide_terminal(self, state: TaskStatus) -> bool:
        """Decide the turn's terminal state exactly once (loop-atomic).

        Both decision points — the turn deciding COMPLETED/FAILED on
        itself, and ``abort_active`` deciding FAILED on a cancel,
        disconnect or shutdown — run on the session's own loop with no
        await between the check and the set, so exactly one of them wins.
        The winner is the only writer of the Task row's terminal state;
        every loser must leave the row alone.
        """
        if self._terminal_state is not None:
            return False
        self._terminal_state = state
        return True

    async def _run_turn(self, turn_id: str, text: str) -> None:
        """One turn: Task row lifecycle + streamed graph run (spec sections 6, 8)."""
        graph = self._graph
        if graph is None:  # pragma: no cover - the endpoint refuses such sessions
            raise RuntimeError("session graph was never bound")
        token = current_task_id.set(turn_id)
        # The typed citation side channel rides the SAME context mechanism as
        # the task id: document tools running inside this turn record their
        # retrieval metadata through ``record_source``; ``chat.final.sources``
        # is built from this collector, never parsed from tool output text and
        # never model-authored (spec section 8).
        sources = TurnSources()
        sources_token = current_turn_sources.set(sources)
        completed = list(self.history)
        try:
            await self._insert_task_row(turn_id, text)
            await self._update_task(turn_id, status=TaskStatus.RUNNING)
            self.history.append(_human_message(text))
            try:
                await self._publish({"type": TURN_STARTED_TYPE, "turn_id": turn_id})
                reply, seq = await self._stream_turn(graph, turn_id)
            except OutboundBackpressure:
                # The client is not reading: the turn is cancelled with a
                # terminal error frame (spec section 8).
                self.history = completed
                await self._backpressure_failure(turn_id)
                return
            except asyncio.CancelledError:
                # The turn unwinds; the canceller (cancel/disconnect/shutdown)
                # writes the FAILED row itself: awaits can be re-cancelled here.
                self.history = completed
                raise
            reply = list(reply)
            self.history = reply
            answer = _reply_text(reply)
            # The model finished: the turn's terminal state is decided right
            # here — synchronously, since no await happened between the
            # stream end and this line — so a cancel landing in the
            # commit window below can no longer flip the finished turn.
            self._decide_terminal(TaskStatus.COMPLETED)
            await self._update_task(turn_id, status=TaskStatus.COMPLETED, result=answer)
            await self._insert_episode(turn_id, answer)
            # Clear the busy marker before the terminal frame so the next
            # message after chat.final is never spuriously "busy".
            self._clear_turn(turn_id)
            try:
                seq += 1  # chat.final carries the stream's last, highest seq
                await self._publish(
                    {
                        "type": CHAT_FINAL_TYPE,
                        "turn_id": turn_id,
                        "seq": seq,
                        "text": answer,
                        "sources": sources.sources(),
                    }
                )
            except OutboundBackpressure:
                # The turn genuinely completed (rows and history stand), but
                # the client never drained the final frame: report that.
                await self._backpressure_failure(turn_id)
                return
        except asyncio.CancelledError:
            self.history = completed
            raise
        except Exception as exc:
            self.history = completed
            logger.bind(session_id=self.id, turn_id=turn_id).exception("Chat turn failed")
            self._decide_terminal(TaskStatus.FAILED)
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
            current_turn_sources.reset(sources_token)
            current_task_id.reset(token)

    async def _stream_turn(
        self, graph: AgentGraph, turn_id: str
    ) -> tuple[list[BaseMessage], int]:
        """Run the turn through ``astream_events`` and forward its frames.

        Returns the final message list and the last used ``seq``. Token
        deltas, tool progress and the final state all surface through the
        event stream (spec section 8); every forwarded frame carries the
        turn's single monotonically increasing ``seq``.
        """
        seq = 0
        final: list[BaseMessage] | None = None
        async for event in graph.astream_events({"messages": self.history}, version="v2"):
            kind = event.get("event")
            data = event.get("data") or {}
            if kind == "on_chat_model_stream":
                # Empty chunks (tool-call announcements, stream-final markers)
                # carry no delta for the client.
                content = getattr(data.get("chunk"), "content", "")
                if isinstance(content, str) and content:
                    seq += 1
                    await self._publish(
                        {
                            "type": CHAT_DELTA_TYPE,
                            "turn_id": turn_id,
                            "seq": seq,
                            "text": content,
                        }
                    )
            elif kind == "on_tool_start":
                seq += 1
                await self._publish(
                    {
                        "type": TOOL_START_TYPE,
                        "turn_id": turn_id,
                        "seq": seq,
                        "name": event.get("name"),
                        "args": data.get("input") or {},
                    }
                )
            elif kind == "on_tool_end":
                seq += 1
                await self._publish(
                    {
                        "type": TOOL_END_TYPE,
                        "turn_id": turn_id,
                        "seq": seq,
                        "name": event.get("name"),
                        "result_preview": _result_preview(data.get("output")),
                    }
                )
            elif kind == "on_chain_end" and not event.get("parent_ids"):
                # The graph's own completion event: its output is the final
                # state (probe-pinned for this langgraph version).
                output = data.get("output")
                if isinstance(output, dict) and "messages" in output:
                    final = list(output["messages"])
        if final is None:  # pragma: no cover - a completed graph always ends the chain
            raise RuntimeError("graph completed without a final messages state")
        return final, seq

    async def _backpressure_failure(self, turn_id: str) -> None:
        """Cancel the turn after a backpressure deadline (spec section 8).

        A turn that had already decided COMPLETED keeps its task/episode
        rows and history; one still in flight is persisted FAILED and its
        approvals are default-denied. The terminal error frame is the turn's
        last produced frame and also awaits the bounded queue — once; if
        even that cannot be delivered the client is gone and liveness wins
        over a logged, dropped frame.
        """
        logger.bind(session_id=self.id, turn_id=turn_id).warning(
            "Outbound queue stayed full for {}s - cancelling turn",
            self._backpressure_timeout,
        )
        if self._decide_terminal(TaskStatus.FAILED):
            await self._fail_quietly(turn_id, BACKPRESSURE_ROW_ERROR)
        self._broker.deny_all(self.id, "turn stalled: client not reading")
        self._clear_turn(turn_id)
        frame = _error(
            ERROR_BACKPRESSURE,
            "the connection stopped reading; the turn was cancelled",
            turn_id=turn_id,
        )
        try:
            await asyncio.wait_for(self.outbound.put(frame), self._backpressure_timeout)
        except TimeoutError:
            logger.bind(session_id=self.id, turn_id=turn_id).error(
                "Terminal backpressure frame dropped - client is not reading"
            )

    async def abort_active(self) -> None:
        """Cancel the in-flight turn, mark it FAILED and deny its approvals.

        Called on client cancel, on disconnect, and (bridged) on gateway
        shutdown. Always runs on the session's own loop; default deny (spec
        sections 6-7): nobody can answer a cancelled turn's approval.

        A turn that already decided its terminal state (COMPLETED or
        FAILED) is not aborted: its task row keeps the decided state. A
        late cancel/disconnect is a no-op on the row — only the cancel-ack
        frame and the default-deny of pending approvals still happen.
        """
        task = self._turn_task
        turn_id = self.active_turn_id
        if task is None or task.done() or turn_id is None:
            return
        if self._terminal_state is not None:
            # The turn decided its own terminal state (the model finished or
            # the turn failed): let the decided task/episode writes land and
            # do not overwrite them with "cancelled by user".
            with suppress(asyncio.CancelledError, Exception):
                await task
            self._broker.deny_all(self.id, "turn cancelled")
            self._clear_turn(turn_id)
            return
        # No terminal state yet: the abort owns the FAILED decision.
        self._decide_terminal(TaskStatus.FAILED)
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
            self._terminal_state = None

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
        """Best-effort FAILED write; auditing must not take the agent down.

        The write observes the single terminal decision: a turn that
        already decided a different terminal state is never overwritten
        here (the FAILED decision owner reaches this only with the row
        still in flight, abort-active above enforces it).
        """
        if self._terminal_state not in (None, TaskStatus.FAILED):
            return
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
