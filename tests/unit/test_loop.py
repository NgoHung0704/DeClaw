"""Unit tests for the basic agentic loop (DCL-010).

The model is faked with a scripted async callable, so the whole think ->
tool-call -> observe loop runs end-to-end with no Ollama daemon present.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from declaw.brain.loop import build_agent_graph
from declaw.brain.stub_tools import echo
from declaw.tools.builtin.filesystem import WorkspacePathError


class _ScriptedModel:
    """Returns pre-baked replies in order; records the messages it was given."""

    def __init__(self, replies: list[BaseMessage]) -> None:
        self._replies = list(replies)
        self.calls: list[list[BaseMessage]] = []

    async def __call__(self, messages: Sequence[BaseMessage]) -> BaseMessage:
        self.calls.append(list(messages))
        return self._replies.pop(0)


async def test_loop_runs_tool_then_answers() -> None:
    # Turn 1: model asks to call ``echo``. Turn 2: model answers directly.
    ask_for_tool = AIMessage(
        content="",
        tool_calls=[{"name": "echo", "args": {"message": "hello"}, "id": "call_1"}],
    )
    model = _ScriptedModel([ask_for_tool, AIMessage(content="Done: echo: hello")])
    graph = build_agent_graph(model=model, tools=[echo])

    result = await graph.ainvoke({"messages": [HumanMessage(content="say hello")]})
    messages = result["messages"]

    # Full trace: Human -> AI(tool_call) -> Tool(result) -> AI(final answer).
    assert isinstance(messages[0], HumanMessage)

    first_ai = messages[1]
    assert isinstance(first_ai, AIMessage)
    assert first_ai.tool_calls  # the model requested the tool (THINK)

    tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1  # the tool actually ran (OBSERVE)
    assert tool_msgs[0].content == "echo: hello"

    final = messages[-1]
    assert isinstance(final, AIMessage)
    assert final.content == "Done: echo: hello"

    # The model "thought" twice: to call the tool, then after observing it.
    assert len(model.calls) == 2


async def test_loop_ends_without_tool_call() -> None:
    # Model answers immediately -> no tool node, loop ends after one think.
    model = _ScriptedModel([AIMessage(content="Bonjour")])
    graph = build_agent_graph(model=model, tools=[echo])

    result = await graph.ainvoke({"messages": [HumanMessage(content="hi")]})
    messages = result["messages"]

    assert not any(isinstance(m, ToolMessage) for m in messages)
    final = messages[-1]
    assert isinstance(final, AIMessage)
    assert final.content == "Bonjour"
    assert len(model.calls) == 1


# ============================================================================
# Tool failures must not escape the graph
#
# A raising tool is normal operation, not a crash: "file already exists",
# "path outside the workspace", "not a directory" are all things the user asks
# for every day. The loop has to turn them into an observation the model can
# react to, otherwise one refused write kills the whole session.
# ============================================================================


class _NoArgs(BaseModel):
    pass


def _raising_tool(exc: Exception, name: str = "boom") -> StructuredTool:
    async def raise_it() -> str:
        """A tool that always fails."""
        raise exc

    return StructuredTool.from_function(coroutine=raise_it, name=name, args_schema=_NoArgs)


@pytest.mark.parametrize(
    "exc",
    [
        WorkspacePathError("File already exists: 'test.txt' (set overwrite=true to replace)."),
        FileNotFoundError("File not found: 'missing.txt'"),
    ],
)
async def test_expected_tool_error_becomes_an_observation(exc: Exception) -> None:
    """The tool's own message reaches the model verbatim, and the loop continues."""
    tool = _raising_tool(exc)
    model = _ScriptedModel(
        [
            AIMessage(content="", tool_calls=[{"name": "boom", "args": {}, "id": "c1"}]),
            AIMessage(content="That file is already there - overwrite it?"),
        ]
    )
    graph = build_agent_graph(model=model, tools=[tool])

    result = await graph.ainvoke({"messages": [HumanMessage(content="write it")]})

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].status == "error"
    assert str(exc) in str(tool_msgs[0].content)

    # The model got a second turn and answered: the session survives.
    assert len(model.calls) == 2
    assert result["messages"][-1].content == "That file is already there - overwrite it?"


async def test_unexpected_tool_error_is_reported_without_internals() -> None:
    """A bug inside a tool is logged for us, not narrated to the model."""
    tool = _raising_tool(RuntimeError("psycopg pool exhausted at C:\\Users\\ADMIN\\secret"))
    model = _ScriptedModel(
        [
            AIMessage(content="", tool_calls=[{"name": "boom", "args": {}, "id": "c1"}]),
            AIMessage(content="Sorry, that did not work."),
        ]
    )
    graph = build_agent_graph(model=model, tools=[tool])

    result = await graph.ainvoke({"messages": [HumanMessage(content="go")]})

    [tool_msg] = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    content = str(tool_msg.content)
    assert tool_msg.status == "error"
    assert "secret" not in content  # internals stay in the operational log
    assert "RuntimeError" in content  # but the model knows the call failed
    assert len(model.calls) == 2
