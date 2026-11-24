"""Checkpoint-backed chat isolation and recovery without live services."""

from collections.abc import Sequence

import httpx
import pytest
from ollama import ResponseError
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from declaw.brain.context import ContextWindowExceededError, with_context_window
from declaw.brain.loop import build_agent_graph
from declaw.brain.repl import run_chat


async def test_numbered_switching_and_invalid_commands() -> None:
    received = []

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        received.append(list(messages))
        return AIMessage(content="ok")

    graph = build_agent_graph(model=model, tools=[], checkpointer=InMemorySaver())
    lines = iter(
        [
            "Alice",
            "/new",
            "Bob",
            "/switch abc",
            "/switch 99",
            "/switch 1 extra",
            "/unknown",
            "/switch 1",
            "again",
            "/threads",
            "/exit",
        ]
    )
    output = []
    await run_chat(graph, read=lambda: next(lines, None), write=output.append)
    assert len(received) == 3
    assert [m.content for m in received[2]] == ["Alice", "ok", "again"]
    assert any("* 1: ready" in line for line in output)
    assert any("2: ready" in line for line in output)


@pytest.mark.parametrize(
    ("follow_up", "reply"),
    [
        ("Finish the explanation.", "I created report.txt with the summary."),
        ("Skip the explanation. Which file did you create?", "I created report.txt."),
    ],
    ids=["finish", "redirect"],
)
async def test_follow_up_preserves_saved_tool_progress(follow_up: str, reply: str) -> None:
    request = "Create report.txt and explain its contents."
    actions = []
    received = []

    @tool
    def create_report() -> str:
        """Simulate creating a report and record one execution."""
        actions.append(1)
        return "Created report.txt with the summary."

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        received.append(list(messages))
        if len(received) == 1:
            return AIMessage(
                content="", tool_calls=[{"name": "create_report", "args": {}, "id": "c1"}]
            )
        if len(received) == 2:
            raise ConnectionError("offline")
        if messages[-1].content == "Hello from another chat.":
            return AIMessage(content="Hello from chat 2.")
        assert messages[-1].content == follow_up
        return AIMessage(content=reply)

    graph = build_agent_graph(
        model=with_context_window(model), tools=[create_report], checkpointer=InMemorySaver()
    )
    lines = iter(
        [
            request,
            "/new",
            "Hello from another chat.",
            "/switch 1",
            "/threads",
            follow_up,
            "/threads",
            "/exit",
        ]
    )
    output = []
    await run_chat(graph, read=lambda: next(lines, None), write=output.append, debug=True)
    assert actions == [1]
    assert len(received) == 4
    assert [m.content for m in received[2]] == ["Hello from another chat."]
    assert [m.content for m in received[-1] if isinstance(m, HumanMessage)] == [request, follow_up]
    tool_results = [m for m in received[-1] if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.content) for m in tool_results] == [
        ("c1", "Created report.txt with the summary.")
    ]
    assert sum(isinstance(m, AIMessage) and bool(m.tool_calls) for m in received[-1]) == 1
    assert any("1: interrupted" in line for line in output)
    assert "Send a message to continue or change direction." in output
    assert reply in output
    assert "* 1: ready" in output


@pytest.mark.parametrize("error", [ConnectionError("offline"), ValueError("bug")])
async def test_failure_guards_and_system_seeding(error: Exception) -> None:
    received = []

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        received.append(list(messages))
        if len(received) == 1:
            raise error
        return AIMessage(content="ok")

    graph = build_agent_graph(model=model, tools=[], checkpointer=InMemorySaver())
    lines = iter(["hello", "Try again.", "/threads", "/exit"])
    output = []
    await run_chat(
        graph,
        read=lambda: next(lines, None),
        write=output.append,
        system=SystemMessage(content="rules"),
    )
    if isinstance(error, ConnectionError):
        assert len(received) == 2
        assert [m.content for m in received[-1]] == ["rules", "hello", "Try again."]
        assert any("1: ready" in line for line in output)
    else:
        assert len(received) == 1
        assert any("1: blocked" in line for line in output)


@pytest.mark.parametrize("text", ["/switch " + "9" * 5000, "/switch", "/new extra", "/retry"])
async def test_malformed_commands_do_not_invoke_graph(text: str) -> None:
    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        pytest.fail("commands must not invoke the model")

    graph = build_agent_graph(model=model, tools=[], checkpointer=InMemorySaver())
    lines = iter([text, "/exit"])
    await run_chat(graph, read=lambda: next(lines, None), write=lambda text: None)


@pytest.mark.parametrize(
    "error, expected",
    [
        (ConnectionError("offline"), "interrupted"),
        (httpx.ReadTimeout("slow"), "interrupted"),
        (ResponseError("busy", 503), "interrupted"),
        (ResponseError("limited", 429), "interrupted"),
        (ResponseError("missing", 404), "blocked"),
        (ResponseError("unknown"), "blocked"),
        (ValueError("bad input"), "blocked"),
        (ContextWindowExceededError("too large"), "blocked"),
        (TypeError("bug"), "blocked"),
    ],
)
def test_classification_requires_failed_agent(error: Exception, expected: str) -> None:
    from langgraph.types import StateSnapshot, PregelTask
    from declaw.brain.repl import classify_failure

    snapshot = StateSnapshot(
        values={},
        next=("agent",),
        config={},
        metadata=None,
        created_at=None,
        parent_config=None,
        tasks=(PregelTask("id", "agent", (), error=error),),
        interrupts=(),
    )
    assert classify_failure(error, snapshot) == expected
    assert classify_failure(error, snapshot._replace(next=("tools",))) == "blocked"
    assert classify_failure(error, snapshot._replace(tasks=())) == "blocked"


async def test_failed_follow_up_becomes_blocked() -> None:
    calls = []

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        calls.append(list(messages))
        if len(calls) == 1:
            raise ConnectionError("offline")
        raise TypeError("bug")

    graph = build_agent_graph(model=model, tools=[], checkpointer=InMemorySaver())
    lines = iter(["hello", "Try again.", "ignored", "/threads", "/exit"])
    output = []
    await run_chat(graph, read=lambda: next(lines, None), write=output.append)
    assert len(calls) == 2
    assert [m.content for m in calls[-1]] == ["hello", "Try again."]
    assert any("1: blocked" in line for line in output)


async def test_snapshot_failure_blocks_without_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        pytest.fail("snapshot failure must prevent invocation")

    graph = build_agent_graph(model=model, tools=[], checkpointer=InMemorySaver())
    monkeypatch.setattr(graph, "aget_state", AsyncMock(side_effect=ConnectionError("storage")))
    lines = iter(["hello", "Try again.", "/threads", "/exit"])
    output = []
    await run_chat(graph, read=lambda: next(lines, None), write=output.append)
    assert any("1: blocked" in line for line in output)


async def test_empty_chats_and_localized_commands() -> None:
    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        pytest.fail("commands must not invoke the model")

    graph = build_agent_graph(model=model, tools=[], checkpointer=InMemorySaver())
    lines = iter(["/new", "/threads", "/switch nope", "/retry", "/exit"])
    output = []
    await run_chat(graph, read=lambda: next(lines, None), write=output.append, language="fr")
    assert any("1: prête" in line for line in output)
    assert any("* 2: prête" in line for line in output)
    assert "Utilisation : /switch <numéro>" in output


async def test_system_is_seeded_once_in_each_chat_and_debug_is_not_repeated() -> None:
    received = []

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        received.append(list(messages))
        return AIMessage(content="ok")

    graph = build_agent_graph(model=model, tools=[], checkpointer=InMemorySaver())
    lines = iter(["first", "second", "/new", "third", "/exit"])
    output = []
    await run_chat(
        graph,
        read=lambda: next(lines, None),
        write=output.append,
        system=SystemMessage(content="rules"),
        debug=True,
    )
    assert [sum(isinstance(m, SystemMessage) for m in turn) for turn in received] == [1, 1, 1]
    assert [m.content for m in received[-1]] == ["rules", "third"]
    assert output.count("ok") == 3


async def test_run_chat_rejects_graph_without_checkpointing() -> None:
    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        return AIMessage(content="unused")

    graph = build_agent_graph(model=model, tools=[])
    with pytest.raises(ValueError, match="checkpointer"):
        await run_chat(graph, read=lambda: None, write=lambda text: None)


async def test_stale_interrupted_state_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        calls.append(1)
        raise ConnectionError("offline")

    graph = build_agent_graph(model=model, tools=[], checkpointer=InMemorySaver())
    original = graph.aget_state
    inspections = 0

    async def inspect(config):
        nonlocal inspections
        inspections += 1
        snapshot = await original(config)
        return snapshot._replace(next=("tools",)) if inspections == 3 else snapshot

    monkeypatch.setattr(graph, "aget_state", inspect)
    lines = iter(["hello", "Try again.", "/threads", "/exit"])
    output = []
    await run_chat(graph, read=lambda: next(lines, None), write=output.append)
    assert calls == [1]
    assert any("1: blocked" in line for line in output)


async def test_debug_does_not_repeat_old_tool_events() -> None:
    from declaw.brain.stub_tools import echo

    replies = iter(
        [
            AIMessage(
                content="", tool_calls=[{"name": "echo", "args": {"message": "hi"}, "id": "c1"}]
            ),
            AIMessage(content="done"),
            AIMessage(content="next answer"),
        ]
    )

    async def model(messages: Sequence[BaseMessage]) -> BaseMessage:
        return next(replies)

    graph = build_agent_graph(model=model, tools=[echo], checkpointer=InMemorySaver())
    lines = iter(["echo", "again", "/exit"])
    output = []
    await run_chat(graph, read=lambda: next(lines, None), write=output.append, debug=True)
    assert sum(line.startswith("[tool call]") for line in output) == 1
    assert sum(line.startswith("[tool result]") for line in output) == 1
    assert output[-1] == "next answer"
