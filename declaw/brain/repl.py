"""Interactive chat REPL on the brain (DCL-016).

``build_brain`` assembles the full model stack — the real Ollama model
(DCL-012), wrapped for tool-call repair (DCL-013) and context-window trimming
(DCL-014) — and compiles the agentic loop (DCL-010/011) around it. ``run_chat``
drives a multi-turn REPL over that graph; its input/output are injected so the
loop is testable without a real terminal or daemon. ``declaw chat`` wires it to
the console.

Compaction (DCL-015) composes here too but is left off by default: it needs a
summariser model and only triggers on very long sessions.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from declaw.brain.chat_model import build_ollama_model
from declaw.brain.context import with_context_window
from declaw.brain.loop import build_agent_graph
from declaw.brain.repair import with_tool_call_repair
from declaw.brain.state import AgentState
from declaw.brain.stub_tools import echo

AgentGraph = CompiledStateGraph[AgentState, Any, Any, Any]


def build_brain(tools: Sequence[BaseTool] | None = None) -> AgentGraph:
    """Assemble the agentic loop on a real Ollama model with the standard wrappers."""
    selected = list(tools) if tools is not None else [echo]
    model = build_ollama_model(selected)
    model = with_tool_call_repair(model, selected)
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
) -> None:
    """Drive a multi-turn REPL over ``graph``.

    ``read`` returns the next user line (or ``None`` to stop); ``write`` emits a
    line of output. The whole conversation is threaded back into the graph each
    turn, so the model keeps multi-turn memory.
    """
    history: list[BaseMessage] = []
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
