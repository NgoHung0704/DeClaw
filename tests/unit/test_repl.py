"""Unit tests for the chat REPL (DCL-016).

The graph is driven by a scripted fake model and the REPL's input/output are
injected, so multi-turn behaviour is exercised with no terminal or Ollama.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from declaw.brain.loop import build_agent_graph
from declaw.brain.repl import (
    build_brain,
    make_console_confirmation_provider,
    run_chat,
)
from declaw.brain.stub_tools import echo
from declaw.tools.builtin.filesystem import FilesystemWriteTool
from declaw.tools.confirmation import always_approve, always_deny
from declaw.tools.registry import default_registry


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


async def test_run_chat_seeds_system_message() -> None:
    system = SystemMessage(content="rules of the game")
    model = _ScriptedModel([AIMessage(content="ok")])
    graph = build_agent_graph(model=model, tools=[echo])

    await run_chat(graph, read=_Reader(["hi", "/exit"]), write=_Writer(), system=system)

    first_turn = model.received[0]
    assert first_turn[0] is system  # the system prompt leads the conversation
    assert isinstance(first_turn[1], HumanMessage)


# ============================================================================
# Console confirmation provider (wiring follow-up)
# ============================================================================


class _FakePrompt:
    """Records the questions it is asked and returns a canned answer."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.questions: list[str] = []

    def __call__(self, question: str) -> str:
        self.questions.append(question)
        return self.answer


async def test_confirmation_approves_on_explicit_yes() -> None:
    prompt = _FakePrompt("y")
    approve = make_console_confirmation_provider(prompt, "en")
    assert await approve(FilesystemWriteTool(), {"path": "x.txt"}) is True


@pytest.mark.parametrize("answer", ["yes", "Y", "  oui ", "o", "OUI"])
async def test_confirmation_accepts_yes_variants(answer: str) -> None:
    approve = make_console_confirmation_provider(_FakePrompt(answer), "en")
    assert await approve(FilesystemWriteTool(), {"path": "x"}) is True


@pytest.mark.parametrize("answer", ["n", "no", "", "maybe", "yeah", "non"])
async def test_confirmation_denies_on_anything_else(answer: str) -> None:
    approve = make_console_confirmation_provider(_FakePrompt(answer), "en")
    assert await approve(FilesystemWriteTool(), {"path": "x"}) is False


async def test_confirmation_default_denies_on_eof() -> None:
    def raising(_: str) -> str:
        raise EOFError

    approve = make_console_confirmation_provider(raising, "en")
    assert await approve(FilesystemWriteTool(), {"path": "x"}) is False


async def test_confirmation_question_shows_tool_and_args() -> None:
    prompt = _FakePrompt("n")
    approve = make_console_confirmation_provider(prompt, "en")
    await approve(FilesystemWriteTool(), {"path": "secret.txt"})
    question = prompt.questions[0]
    assert "filesystem_write" in question
    assert "secret.txt" in question
    assert "Allow?" in question


async def test_confirmation_question_localized_french() -> None:
    prompt = _FakePrompt("n")
    approve = make_console_confirmation_provider(prompt, "fr")
    await approve(FilesystemWriteTool(), {"path": "x"})
    assert "Autoriser" in prompt.questions[0]


# ============================================================================
# End-to-end wiring: registry tools execute through the graph
# ============================================================================


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(ws))
    return ws


async def test_registry_read_tool_runs_through_graph(workspace: Path) -> None:
    """A READ tool call routes through ToolNode to the real workspace."""
    (workspace / "report.txt").write_text("hi", encoding="utf-8")
    tools = default_registry().langchain_tools("en", always_approve)
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "filesystem_list", "args": {}, "id": "c1"}],
            ),
            AIMessage(content="here are the files"),
        ]
    )
    graph = build_agent_graph(model=model, tools=tools)

    result = await graph.ainvoke({"messages": [HumanMessage(content="list files")]})

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs
    assert any("report.txt" in str(m.content) for m in tool_msgs)


async def test_registry_write_tool_is_gated_through_graph(workspace: Path) -> None:
    """A WRITE tool call denied by the provider neither writes nor errors out."""
    tools = default_registry().langchain_tools("en", always_deny)
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "filesystem_write",
                        "args": {"path": "new.txt", "content": "x"},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="ok"),
        ]
    )
    graph = build_agent_graph(model=model, tools=tools)

    result = await graph.ainvoke({"messages": [HumanMessage(content="write a file")]})

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("denied" in str(m.content).lower() for m in tool_msgs)
    assert not (workspace / "new.txt").exists()  # the gate prevented the write
