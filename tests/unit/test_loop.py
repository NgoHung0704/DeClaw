"""Unit tests for the basic agentic loop (DCL-010).

The model is faked with a scripted async callable, so the whole think ->
tool-call -> observe loop runs end-to-end with no Ollama daemon present.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from declaw.brain.loop import build_agent_graph
from declaw.brain.stub_tools import echo


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
