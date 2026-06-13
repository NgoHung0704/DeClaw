"""Interactive chat REPL on the brain (DCL-016).

``build_brain`` assembles the model stack — the real Ollama model (DCL-012)
wrapped for context-window trimming (DCL-014) — and compiles the agentic loop
(DCL-010/011) around it. ``run_chat`` drives a multi-turn REPL over that graph;
its input/output are injected so the loop is testable without a real terminal
or daemon. ``declaw chat`` wires it to the console.

Both ``with_tool_call_repair`` (DCL-013) and ``with_compaction`` (DCL-015) are
composable and can be layered in by a caller, but they are *not* in the
default ``build_brain`` stack:

* Repair: the probe (`scripts/probe_mistral.py`) showed it lowered tool-call
  accuracy on Mistral 7B (raw 10/15, with repair 9/15) by turning "wrong tool"
  into "no tool". Two of three detection branches (``invalid_tool_calls`` and
  unknown tool name) never fired against real Ollama output. Until the strategy
  is redesigned (soft nudge, or a different failure mode like *missed* tool),
  repair stays out of the default.
* Compaction: needs a summariser model and re-summarises every turn, which
  costs an extra LLM call (~14 s p50). Out until persistence lands.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from declaw.brain.chat_model import build_ollama_model
from declaw.brain.context import with_context_window
from declaw.brain.loop import build_agent_graph
from declaw.brain.state import AgentState
from declaw.brain.stub_tools import echo

AgentGraph = CompiledStateGraph[AgentState, Any, Any, Any]


def build_brain(tools: Sequence[BaseTool] | None = None) -> AgentGraph:
    """Assemble the agentic loop on a real Ollama model.

    The default stack is ``build_ollama_model`` + ``with_context_window``. See
    the module docstring for why ``with_tool_call_repair`` and
    ``with_compaction`` are not in the default — callers can layer them in.
    """
    selected = list(tools) if tools is not None else [echo]
    model = build_ollama_model(selected)
    model = with_context_window(model)
    return build_agent_graph(model=model, tools=selected)


def _reply_text(messages: Sequence[BaseMessage]) -> str:
    """Return the most recent assistant message that carries visible text."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            content = (
                message.content if isinstance(message.content, str) else str(message.content)
            )
            if content.strip():
                return content
    return ""


def _render_debug(messages: Sequence[BaseMessage], write: Callable[[str], None]) -> None:
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                write(f"[tool call] {call['name']}({call['args']})")
        elif isinstance(message, ToolMessage):
            write(f"[tool result] {message.content}")


async def run_chat(
    graph: AgentGraph,
    *,
    read: Callable[[], str | None],
    write: Callable[[str], None],
    debug: bool = False,
    system: SystemMessage | None = None,
) -> None:
    """Drive a multi-turn REPL over ``graph``.

    ``read`` returns the next user line (or ``None`` to stop); ``write`` emits a
    line of output. The whole conversation is threaded back into the graph each
    turn, so the model keeps multi-turn memory. When ``system`` is given it is
    seeded as the leading message (the localized system prompt, DCL-017).
    """
    history: list[BaseMessage] = [] if system is None else [system]
    while True:
        line = read()
        if line is None:
            break
        text = line.strip()
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            break

        history.append(HumanMessage(content=text))
        before = len(history)
        result = await graph.ainvoke({"messages": history})
        history = list(result["messages"])

        if debug:
            _render_debug(history[before:], write)
        write(_reply_text(history))
