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

import asyncio
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
from declaw.config import Language
from declaw.log import logger
from declaw.tools.base import DeclawTool
from declaw.tools.confirmation import ConfirmationProvider

_APPROVALS = {"y", "yes", "o", "oui"}

# Shown when a whole turn fails. Tool refusals never reach here (the graph turns
# those into observations, see declaw/brain/loop.py); this covers the rest —
# Ollama disappearing mid-conversation, a recursion limit, a bug in DeClaw. The
# reason is kept short but names the exception type so a user can report it.
_TURN_FAILED_EN = (
    "That request could not be completed ({reason}). "
    "The conversation is still open - you can try again or rephrase."
)
_TURN_FAILED_FR = (
    "Cette demande n'a pas pu être traitée ({reason}). "
    "La conversation reste ouverte - vous pouvez réessayer ou reformuler."
)
_MAX_REASON_CHARS = 200

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


def make_console_confirmation_provider(
    prompt: Callable[[str], str], language: Language
) -> ConfirmationProvider:
    """Build a ``ConfirmationProvider`` that asks the human via a blocking prompt.

    ``prompt`` is a blocking input function (e.g. ``console.input``). It is run
    through ``asyncio.to_thread`` so waiting for the user never stalls the
    agent's event loop. Only an explicit yes (y/yes/o/oui) approves; anything
    else — including EOF or Ctrl-C — denies, so the safe default when the user
    cannot answer is "no".

    The question shows the tool name and arguments (e.g. the target path)
    because the user needs to know what they are approving. This text is shown
    to the user and audited; it is never fed back to the model.
    """

    def question(tool: DeclawTool[Any], args: dict[str, Any]) -> str:
        rendered = ", ".join(f"{key}={value!r}" for key, value in args.items())
        if language == "fr":
            return f"DeClaw veut appeler {tool.name}({rendered}). Autoriser ? [y/N] "
        return f"DeClaw wants to call {tool.name}({rendered}). Allow? [y/N] "

    async def approve(tool: DeclawTool[Any], args: dict[str, Any]) -> bool:
        try:
            answer = await asyncio.to_thread(prompt, question(tool, args))
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() in _APPROVALS

    return approve


def turn_failure_message(exc: Exception, language: Language) -> str:
    """Localized, single-line account of a failed turn for the user."""
    first_line = str(exc).splitlines()[0] if str(exc).strip() else ""
    reason = f"{type(exc).__name__}: {first_line}"[:_MAX_REASON_CHARS].rstrip(": ")
    template = _TURN_FAILED_FR if language == "fr" else _TURN_FAILED_EN
    return template.format(reason=reason)


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
    language: Language = "en",
) -> None:
    """Drive a multi-turn REPL over ``graph``.

    ``read`` returns the next user line (or ``None`` to stop); ``write`` emits a
    line of output. The whole conversation is threaded back into the graph each
    turn, so the model keeps multi-turn memory. When ``system`` is given it is
    seeded as the leading message (the localized system prompt, DCL-017).

    One failed turn never ends the session: the error is reported to the user
    (in ``language``), logged with its traceback for us, and the loop moves on.
    A user in the middle of a long conversation must not lose it to a transient
    failure.
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

        # Snapshot so a failed turn can be rolled back: history then only ever
        # holds completed turns, and a prompt that blew up cannot silently
        # re-trigger on the next invocation.
        completed = list(history)
        history.append(HumanMessage(content=text))
        before = len(history)
        try:
            result = await graph.ainvoke({"messages": history})
        except Exception as exc:
            logger.exception("Chat turn failed")
            history = completed
            write(turn_failure_message(exc, language))
            continue
        history = list(result["messages"])

        if debug:
            _render_debug(history[before:], write)
        write(_reply_text(history))
