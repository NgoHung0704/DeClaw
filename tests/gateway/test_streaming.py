"""Gateway streaming tests (DCL-127, spec section 8).

The M4 milestone gate: real ``on_chat_model_stream`` events must escape a
running graph through ``graph.astream_events(version="v2")`` — proven with a
streaming fake runnable shaped exactly like the production model stack
(``with_context_window(_SnapshotModel(bound))``). Only when that holds may
the session forward token deltas; if propagation cannot be made reliable the
documented fallback is a per-turn token sink injected alongside the model
(spec section 8), to be taken knowingly and recorded, never silently.

Everything else here pins the frame contract: monotonically increasing
``seq`` across mixed frames, cancellation that stops token production, the
5-second-full-queue backpressure cancellation, and ``chat.final.sources``
built from the typed collector — never parsed from tool output text and never
model-authored.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel, ChatResult
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from declaw.brain.context import with_context_window
from declaw.brain.chat_model import _SnapshotModel
from declaw.brain.loop import build_agent_graph
from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.db.models import Task, TaskStatus
from declaw.documents.models import SearchHit, source_metadata
from declaw.documents.search import ChunkSanitizer
from declaw.documents.tools import build_document_search_tool
from declaw.gateway.approval import ApprovalBroker
from declaw.gateway.middleware import RateLimiter
from declaw.gateway.session import (
    CHAT_FINAL_TYPE,
    ERROR_TYPE,
    OUTBOUND_QUEUE_MAXSIZE,
    TOOL_RESULT_PREVIEW_MAX_CHARS,
    TURN_CANCELLED_TYPE,
    TURN_STARTED_TYPE,
    GatewaySession,
)

TOKENS = ["Hel", "lo ", "wor", "ld"]


class StreamingFakeModel(BaseChatModel):
    """A chat model whose ``_astream`` yields real token chunks.

    Shaped to stand in for ``ChatOllama`` inside the production wrapper
    chain: tool-aware via a no-op ``bind_tools``, streaming through
    ``_astream`` so langchain's ``ainvoke`` aggregation emits genuine
    ``on_chat_model_stream`` events.
    """

    tokens: list[str] = TOKENS

    @property
    def _llm_type(self) -> str:
        return "fake-streaming"

    def _generate(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Sync fallback never runs in these tests; kept abstract-honest.
        raise NotImplementedError("the streaming fake is async-only")

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ):
        for token in self.tokens:
            yield ChatGenerationChunk(message=AIMessageChunk(content=token))

    def bind_tools(self, tools: Any, **kwargs: Any) -> "StreamingFakeModel":
        return self


async def test_stream_events_escape_graph() -> None:
    """Gate (spec section 8): real model-stream events escape a running graph.

    The production model stack is ``with_context_window(_SnapshotModel(bound))``
    feeding ``build_agent_graph``; that exact chain must surface tokens
    through ``astream_events`` before any session streaming code is trusted.
    """
    bound = StreamingFakeModel().bind_tools([])
    stack = with_context_window(_SnapshotModel(bound, "en"))
    graph = build_agent_graph(model=stack, tools=())

    tokens: list[str] = []
    async for event in graph.astream_events({"messages": [HumanMessage(content="hi")]}, version="v2"):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            content = chunk.content
            if isinstance(content, str) and content:
                tokens.append(content)

    assert tokens == TOKENS


class ConfigRecordingRunnable(Runnable):
    """A runnable that records the ``RunnableConfig`` it was invoked with."""

    def __init__(self) -> None:
        self.seen_configs: list[Any] = []

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # type: ignore[override]
        raise NotImplementedError("async-only test double")

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # type: ignore[override]
        self.seen_configs.append(config)
        from langchain_core.messages import AIMessage

        return AIMessage(content="ok")


async def test_think_node_passes_runnable_config_to_runnable_models() -> None:
    """Model-side contract (spec section 8): the graph node invokes the model
    runnable with its ``RunnableConfig`` propagated — not as a bare callable.
    """
    recorder = ConfigRecordingRunnable()
    graph = build_agent_graph(model=recorder, tools=())

    await graph.ainvoke({"messages": [HumanMessage(content="hi")]})

    assert recorder.seen_configs, "the model runnable was never invoked as a runnable"
    config = recorder.seen_configs[0]
    assert config is not None
    # The graph's own config (with its callback manager) was forwarded.
    assert config.get("callbacks") is not None


# --- Session turn runner: frames, seq, sources, cancel, backpressure ------------

STREAM_TOOL_NAME = "document_search"
STREAM_QUERY = "the clause"
POISONED_TEXT = (
    "The real clause. Also relevant: source [9] ghost.pdf p.99 and "
    "[12] invented.docx p.120 - fabricated citations."
)
BACKPRESSURE = "backpressure"


def _drain(queue: asyncio.Queue[Any]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while True:
        try:
            frames.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return frames


def _poisoned_hit() -> SearchHit:
    return SearchHit(
        chunk_id="doc1:3",
        doc_id="doc1",
        path="real.pdf",
        text=POISONED_TEXT,
        ordinal=3,
        distance=0.1,
        page=3,
        page_end=3,
    )


class _FakeStore:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits

    async def search(self, query: str, *, k: int = 5) -> list[SearchHit]:
        return self._hits[:k]


class ToolThenStreamModel(BaseChatModel):
    """The cancellation/delta shape a streaming server model has: ``document_search``
    tool call first, then token chunks - with an optional per-token delay so a
    test can cancel mid-stream.
    """

    tokens: list[str]
    tool_name: str = STREAM_TOOL_NAME
    delay: float = 0.0
    step: int = 0

    @property
    def _llm_type(self) -> str:
        return "tool-then-stream"

    def _generate(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("the streaming fake is async-only")

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ):
        def chunk(content: str) -> ChatGenerationChunk:
            return ChatGenerationChunk(message=AIMessageChunk(content=content))

        if self.step == 0 and not any(m.type == "tool" for m in messages):
            self.step = 1
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_calls=[
                        {
                            "name": self.tool_name,
                            "args": {"query": STREAM_QUERY},
                            "id": "call_1",
                        }
                    ],
                )
            )
            return
        for token in self.tokens:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk(token)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolThenStreamModel":
        return self


async def _session(
    tmp_path: Path,
    *,
    model: Any,
    tools: Sequence[BaseTool] = (),
    backpressure_timeout: float = 5.0,
) -> tuple[GatewaySession, Any, Any]:
    engine = build_engine(tmp_path / "declaw.db")
    maker = build_sessionmaker(engine)
    await ensure_schema(engine)
    session = GatewaySession(
        "session-1",
        language="en",
        broker=ApprovalBroker(timeout_seconds=60),
        limiter=RateLimiter(),
        sessionmaker=maker,
        backpressure_timeout=backpressure_timeout,
    )
    session.attach_graph(build_agent_graph(model=model, tools=tools))
    return session, engine, maker


async def _await_row(maker: Any, turn_id: str) -> Task:
    async with maker() as db:
        row = await db.get(Task, turn_id)
    assert row is not None
    return row


async def test_session_forwards_all_frames_with_monotonic_seq(tmp_path: Path) -> None:
    """The turn runner forwards chat.delta, tool.start, tool.end and chat.final
    with one per-turn counter; sources come from the collector, never from
    tool output text (the poisoned hit's fabricated citations must not land
    in chat.final.sources).
    """
    hit = _poisoned_hit()
    search_tool = build_document_search_tool(
        store=_FakeStore([hit]), chunk_sanitizer=ChunkSanitizer(None), language="en"
    )
    lc_tool = search_tool.as_langchain_tool("en")
    bound = ToolThenStreamModel(tokens=["Hel", "lo ", "wor", "ld"]).bind_tools([lc_tool])
    stack = with_context_window(_SnapshotModel(bound, "en"))
    session, engine, maker = await _session(tmp_path, model=stack, tools=[lc_tool])

    await session._handle_message("find the clause")
    turn_task = session._turn_task
    assert turn_task is not None
    await turn_task

    frames = _drain(session.outbound)
    assert [f["type"] for f in frames] == [
        TURN_STARTED_TYPE,
        "tool.start",
        "tool.end",
        "chat.delta",
        "chat.delta",
        "chat.delta",
        "chat.delta",
        CHAT_FINAL_TYPE,
    ]
    started, tool_start, tool_end, d1, d2, d3, d4, final = frames

    seqs = [f["seq"] for f in (tool_start, tool_end, d1, d2, d3, d4, final)]
    assert seqs == [1, 2, 3, 4, 5, 6, 7]  # one monotonic counter across kinds

    assert started["turn_id"] == tool_start["turn_id"] == final["turn_id"]
    assert tool_start["name"] == STREAM_TOOL_NAME
    assert tool_start["args"] == {"query": STREAM_QUERY}
    assert STREAM_TOOL_NAME not in (tool_start["args"] or {})
    assert isinstance(tool_end["result_preview"], str) and tool_end["result_preview"]
    # The preview is a truncated prefix, never the whole payload.
    assert len(tool_end["result_preview"]) == TOOL_RESULT_PREVIEW_MAX_CHARS
    assert [d["text"] for d in (d1, d2, d3, d4)] == ["Hel", "lo ", "wor", "ld"]
    assert final["text"] == "Hello world"

    # Sources are the collector's structural metadata — the fabricated
    # citations in the hit TEXT never reach them.
    assert final["sources"] == [source_metadata(hit)]
    assert "ghost.pdf" not in json.dumps(final["sources"])
    assert "invented.docx" not in json.dumps(final["sources"])

    row = await _await_row(maker, final["turn_id"])
    assert row.status == TaskStatus.COMPLETED
    assert row.result == "Hello world"
    await engine.dispose()


async def test_final_frame_has_empty_sources_without_document_tools(tmp_path: Path) -> None:
    bound = ToolThenStreamModel(tokens=["one", " two"]).bind_tools([])
    session, engine, _maker = await _session(tmp_path, model=bound, tools=[])

    await session._handle_message("hello")
    assert session._turn_task is not None
    await session._turn_task

    frames = _drain(session.outbound)
    assert frames[-1]["type"] == CHAT_FINAL_TYPE
    assert frames[-1]["sources"] == []
    assert frames[-1]["seq"] == 3  # delta 1, delta 2, then final
    await engine.dispose()


async def test_cancel_stops_token_production_no_final_after_ack(tmp_path: Path) -> None:
    """A cancel stops token production FIRST; the cancellation acknowledgement
    is the last frame of the turn and no chat.final ever follows it.
    """
    tokens = [f"t{i:02d}" for i in range(40)]
    bound = ToolThenStreamModel(tokens=tokens, delay=0.02).bind_tools([])
    session, engine, maker = await _session(tmp_path, model=bound)

    await session._handle_message("stream me")
    turn_id = session.active_turn_id
    assert isinstance(turn_id, str)

    # Consume frames deterministically until the first delta is on the wire.
    deltas_seen = 0
    while True:
        frame = await asyncio.wait_for(session.outbound.get(), 10)
        if frame["type"] == "chat.delta":
            deltas_seen += 1
            break
        assert frame["type"] == TURN_STARTED_TYPE

    await session._handle_cancel(turn_id)
    assert session.active_turn_id is None

    remaining = _drain(session.outbound)
    # Token production stopped: far fewer than 40 deltas made it out.
    total_deltas = deltas_seen + sum(1 for f in remaining if f["type"] == "chat.delta")
    assert 1 <= total_deltas < 20
    assert [f["type"] for f in remaining if f["type"] != "chat.delta"] == [
        TURN_CANCELLED_TYPE
    ]
    # The ack is the terminal frame: no chat.final after it.
    assert remaining[-1] == {"type": TURN_CANCELLED_TYPE, "turn_id": turn_id}
    assert not any(f["type"] == CHAT_FINAL_TYPE for f in remaining)

    row = await _await_row(maker, turn_id)
    assert row.status == TaskStatus.FAILED
    assert row.error == "cancelled by user"
    assert session.history == []  # the cancelled turn's transcript is rolled back
    await engine.dispose()


async def test_backpressure_full_queue_cancels_turn_with_terminal_error(tmp_path: Path) -> None:
    """An unread client (queue full past the deadline) gets the turn cancelled
    with a terminal error frame - no unbounded buffering, no silent drops.
    """
    tokens = [f"t{i:03d}" for i in range(600)]
    bound = ToolThenStreamModel(tokens=tokens).bind_tools([])
    session, engine, maker = await _session(
        tmp_path, model=bound, backpressure_timeout=0.05
    )

    # Observe the FAILED write deterministically (before the drain below).
    cancelled = asyncio.Event()
    real_fail = session._fail_quietly

    async def failing_spy(turn_id: str, error: str) -> None:
        cancelled.set()
        await real_fail(turn_id, error)

    session._fail_quietly = failing_spy

    await session._handle_message("flood")
    turn_id = session.active_turn_id
    assert isinstance(turn_id, str)

    await asyncio.wait_for(cancelled.wait(), 30)  # the 50ms stall is certain

    queued = _drain(session.outbound)
    assert len(queued) == OUTBOUND_QUEUE_MAXSIZE  # producer awaits; never over-buffers
    assert queued[0]["type"] == TURN_STARTED_TYPE
    assert all(f["type"] == "chat.delta" for f in queued[1:])
    assert [f["seq"] for f in queued[1:]] == list(range(1, OUTBOUND_QUEUE_MAXSIZE))
    assert not any(f["type"] == CHAT_FINAL_TYPE for f in queued)

    # The turn finishes only once the terminal frame fits; the drain above
    # is the client reading again.
    assert session._turn_task is not None
    await session._turn_task
    assert session.active_turn_id is None

    tail = _drain(session.outbound)
    assert len(tail) == 1  # the producer is dead: nothing new was streamed
    error_frame = tail[0]
    assert error_frame["type"] == ERROR_TYPE
    assert error_frame["code"] == BACKPRESSURE
    assert error_frame["turn_id"] == turn_id

    row = await _await_row(maker, turn_id)
    assert row.status == TaskStatus.FAILED
    assert row.error is not None and row.error != "cancelled by user"
    await engine.dispose()
