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

A raising tool is normal operation here, not a crash: DeClaw's tools refuse
things constantly ("file already exists", "path outside the workspace"), and
the model must be able to see that refusal and adapt. ``ToolNode`` is therefore
given an explicit ``handle_tool_errors`` handler — langgraph's own default only
converts ``ToolInvocationError`` (bad arguments) and re-raises everything else,
which would tear down the whole session on a refused write.
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
from declaw.log import logger

# Async "think" step: given the running message list, return the model's next
# message. The model must already be aware of the available tools (e.g. via
# ``ChatOllama.bind_tools(tools)``); tests inject a scripted fake.
ModelCallable = Callable[[Sequence[BaseMessage]], Awaitable[BaseMessage]]

# Failures that are part of a tool's contract. Their messages are written for
# this purpose: they name a workspace-relative path and often the way out
# ("set overwrite=true"), so handing them to the model verbatim is what lets it
# recover. Everything else is a bug in DeClaw, whose message may carry
# absolute paths or library internals that are noise to the model and to the
# user reading its answer.
_EXPECTED_TOOL_ERRORS = (
    ValueError,  # incl. WorkspacePathError and pydantic ValidationError
    OSError,  # incl. FileNotFoundError, IsADirectoryError, PermissionError
)

TOOL_ERROR_PREFIX = "Tool error:"


def tool_error_message(exc: Exception) -> str:
    """Render a tool failure as an observation the model can act on.

    The ``exc: Exception`` annotation is load-bearing: langgraph infers which
    exception types this handler covers from it, so widening or narrowing the
    annotation changes which failures still escape the graph.
    """
    if isinstance(exc, _EXPECTED_TOOL_ERRORS):
        return f"{TOOL_ERROR_PREFIX} {exc}"
    logger.bind(error_type=type(exc).__name__).exception("Unexpected tool failure")
    return (
        f"{TOOL_ERROR_PREFIX} the tool failed unexpectedly "
        f"({type(exc).__name__}). This is a DeClaw bug, not something the user "
        "did wrong; do not retry the same call."
    )


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
    builder.add_node("tools", ToolNode(list(tools), handle_tool_errors=tool_error_message))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    return builder.compile()
