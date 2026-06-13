"""The basic agentic loop: think -> tool-call -> observe (DCL-010).

A two-node LangGraph state machine:

* ``agent`` - the *think* step. Calls the injected model, which returns an
  ``AIMessage`` that may carry ``tool_calls``.
* ``tools`` - the *observe* step. ``ToolNode`` runs any requested tools and
  appends their ``ToolMessage`` results.

A conditional edge (``tools_condition``) loops back to ``agent`` while the
model keeps requesting tools, and routes to ``END`` once it answers directly.

State is :class:`~declaw.brain.state.AgentState` (DCL-011). The model is
*injected* as an async callable, so the loop is testable without a live Ollama
daemon. Wiring the real Mistral model (via langchain-ollama ``bind_tools``) is
DCL-012.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from declaw.brain.state import AgentState

# Async "think" step: given the running message list, return the model's next
# message. The model must already be aware of the available tools (e.g. via
# ``ChatOllama.bind_tools(tools)``); tests inject a scripted fake.
ModelCallable = Callable[[Sequence[BaseMessage]], Awaitable[BaseMessage]]


def build_agent_graph(
    *,
    model: ModelCallable,
    tools: Sequence[BaseTool],
) -> CompiledStateGraph[AgentState, Any, Any, Any]:
    """Compile the think -> tool-call -> observe loop.

    ``model`` is the think step (async, injected). ``tools`` are executed by
    the observe step and must match the tools the model was made aware of.
    """

    async def think(state: AgentState) -> dict[str, list[BaseMessage]]:
        reply = await model(state.messages)
        return {"messages": [reply]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", think)
    builder.add_node("tools", ToolNode(list(tools)))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    return builder.compile()
