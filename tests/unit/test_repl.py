"""Unit tests for the chat REPL (DCL-016).

The graph is driven by a scripted fake model and the REPL's input/output are
injected, so multi-turn behaviour is exercised with no terminal or Ollama.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage

from declaw.brain.loop import build_agent_graph
from declaw.brain.repl import build_brain, run_chat
from declaw.brain.stub_tools import echo


class _ScriptedModel:
    def __init__(self, replies: list[BaseMessage]) -> None:
        self._replies = list(replies)
        self.received: list[list[BaseMessage]] = []

    async def __call__(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        self.received.append(list(messages))
        return self._replies.pop(0)


class _Reader:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def __call__(self) -> str | None:
        return self._lines.pop(0) if self._lines else None


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


def test_build_brain_builds_a_runnable_graph() -> None:
    graph = build_brain([echo])  # ChatOllama is lazy, so no daemon is needed here
    assert hasattr(graph, "ainvoke")


async def test_run_chat_threads_history_across_turns() -> None:
    model = _ScriptedModel([AIMessage(content="first"), AIMessage(content="second")])
    graph = build_agent_graph(model=model, tools=[echo])
    writer = _Writer()

    await run_chat(graph, read=_Reader(["hello", "again", "/exit"]), write=writer)

    assert "first" in writer.lines
    assert "second" in writer.lines
    assert len(model.received) == 2
    # turn 2 sees turn-1's reply -> multi-turn memory
    assert any(isinstance(m, AIMessage) and m.content == "first" for m in model.received[1])


async def test_run_chat_exits_without_calling_model() -> None:
    model = _ScriptedModel([AIMessage(content="never")])
    graph = build_agent_graph(model=model, tools=[echo])
    writer = _Writer()

    await run_chat(graph, read=_Reader(["/exit"]), write=writer)

    assert model.received == []
    assert writer.lines == []


async def test_run_chat_skips_blank_input() -> None:
    model = _ScriptedModel([AIMessage(content="reply")])
    graph = build_agent_graph(model=model, tools=[echo])
    writer = _Writer()

    await run_chat(graph, read=_Reader(["", "   ", "hi", "/exit"]), write=writer)

    assert len(model.received) == 1  # only the non-blank line ran a turn
    assert "reply" in writer.lines


async def test_run_chat_debug_shows_tool_call_and_result() -> None:
    tool_call = AIMessage(
        content="", tool_calls=[{"name": "echo", "args": {"message": "hi"}, "id": "c1"}]
    )
    model = _ScriptedModel([tool_call, AIMessage(content="done")])
    graph = build_agent_graph(model=model, tools=[echo])
    writer = _Writer()

    await run_chat(graph, read=_Reader(["please echo", "/exit"]), write=writer, debug=True)

    joined = "\n".join(writer.lines)
    assert "[tool call] echo" in joined
    assert "[tool result] echo: hi" in joined
    assert "done" in joined
