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
from typing import Any, Literal
from dataclasses import dataclass
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
import httpx
from ollama import ResponseError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import StateSnapshot
from langgraph.graph.state import CompiledStateGraph
from itertools import count
from declaw.brain.chat_model import build_ollama_model
from declaw.brain.context import with_context_window
from declaw.brain.loop import build_agent_graph
from declaw.brain.state import AgentState
from declaw.brain.stub_tools import echo
from declaw.config import Language
from declaw.log import logger
from declaw.tools.base import DeclawTool
from declaw.tools.confirmation import ConfirmationProvider

from uuid import uuid4

_APPROVALS = {"y", "yes", "o", "oui"}

# Shown when a whole turn fails. Tool refusals never reach here (the graph turns
# those into observations, see declaw/brain/loop.py); this covers the rest —
# Ollama disappearing mid-conversation, a recursion limit, a bug in DeClaw. The
# reason is kept short but names the exception type so a user can report it.
_TURN_FAILED_EN = (
    "That request could not be completed ({reason}). Saved progress has been preserved."
)
_TURN_FAILED_FR = (
    "Cette demande n'a pas pu être traitée ({reason}). La progression enregistrée a été conservée."
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
    return build_agent_graph(model=model, tools=selected, checkpointer=InMemorySaver())


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
        # A tool whose arguments are a plan renders its own summary: thirty
        # raw key=value pairs in a prompt is how people learn to press 'y'
        # without reading.
        preview = tool.confirmation_preview(args)
        if preview is not None:
            if language == "fr":
                return f"{preview}\nAutoriser ? [y/N] "
            return f"{preview}\nAllow? [y/N] "
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
            content = message.content if isinstance(message.content, str) else str(message.content)
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


ConversationStatus = Literal["ready", "interrupted", "blocked"]


@dataclass
class Conversation:
    """Process-local metadata; graph state belongs to the checkpointer."""

    thread_id: str
    status: ConversationStatus = "ready"
    last_error: str | None = None


def _failed_agent(snapshot: StateSnapshot) -> bool:
    return (
        snapshot.next == ("agent",)
        and not snapshot.interrupts
        and any(task.name == "agent" and task.error is not None for task in snapshot.tasks)
    )


def classify_failure(exc: Exception, snapshot: StateSnapshot) -> Literal["interrupted", "blocked"]:
    """Allow follow-ups after temporary failures of a saved agent task."""
    if not _failed_agent(snapshot):
        return "blocked"
    if isinstance(exc, (ConnectionError, httpx.TimeoutException, httpx.NetworkError)):
        return "interrupted"
    if isinstance(exc, ResponseError) and exc.status_code in {429, 502, 503, 504}:
        return "interrupted"
    return "blocked"


def _chat_text(language: Language, en: str, fr: str) -> str:
    return fr if language == "fr" else en


async def run_chat(
    graph: AgentGraph,
    *,
    read: Callable[[], str | None],
    write: Callable[[str], None],
    debug: bool = False,
    system: SystemMessage | None = None,
    language: Language = "en",
) -> None:
    """Run numbered, checkpoint-backed chats with message-driven recovery.

    Commands never enter model context. Failed progress remains checkpointed.
    A recognized temporary agent failure permits a follow-up message.
    """
    if graph.checkpointer is None or isinstance(graph.checkpointer, bool):
        raise ValueError("run_chat requires a graph with a checkpointer")

    conversations: dict[int, Conversation] = {}
    conversation_ids = count(start=1)

    def new_conversation() -> int:
        number = next(conversation_ids)
        conversations[number] = Conversation(str(uuid4()))
        return number

    def say(en: str, fr: str) -> None:
        write(_chat_text(language, en, fr))

    def recovery_notice(conversation: Conversation) -> None:
        if conversation.status == "interrupted":
            say(
                "Send a message to continue or change direction.",
                "Envoyez un message pour reprendre ou changer de direction.",
            )
        else:
            say(
                "Conversation blocked; investigation is required. Use /switch or /new.",
                "Conversation bloquée ; une vérification est nécessaire. Utilisez /switch ou /new.",
            )

    active_conversation = new_conversation()
    while True:
        line = read()
        if line is None:
            break
        text = line.strip()
        if not text:
            continue
        parts = text.split()
        command = parts[0]
        if text in {"/exit", "/quit"}:
            break
        if text == "/new":
            active_conversation = new_conversation()
            say(
                f"Created conversation {active_conversation}.",
                f"Conversation {active_conversation} créée.",
            )
            continue
        if text == "/threads":
            for number, conversation in conversations.items():
                marker = "*" if number == active_conversation else " "
                status: str = conversation.status
                if language == "fr":
                    status = {
                        "ready": "prête",
                        "interrupted": "interrompue",
                        "blocked": "bloquée",
                    }[status]
                write(f"{marker} {number}: {status}")
                if conversation.last_error:
                    write(f"  {conversation.last_error}")
            continue
        if command == "/switch":
            try:
                target = int(parts[1]) if len(parts) == 2 else None
            except ValueError:
                target = None
            if target is None:
                say("Usage: /switch <number>", "Utilisation : /switch <numéro>")
            elif target not in conversations:
                say("Conversation not found.", "Conversation introuvable.")
            else:
                active_conversation = target
                say(f"Switched to conversation {target}.", f"Conversation {target} sélectionnée.")
            continue
        if text.startswith("/"):
            say(
                "Commands: /new, /threads, /switch <number>, /exit, /quit",
                "Commandes : /new, /threads, /switch <numéro>, /exit, /quit",
            )
            continue

        conversation = conversations[active_conversation]
        if conversation.status == "blocked":
            recovery_notice(conversation)
            continue

        config: RunnableConfig = {"configurable": {"thread_id": conversation.thread_id}}
        may_classify = False
        try:
            before = await graph.aget_state(config)
            if conversation.status == "interrupted" and not _failed_agent(before):
                conversation.status = "blocked"
                recovery_notice(conversation)
                continue
            messages = before.values.get("messages", [])
            new_messages: list[BaseMessage] = []
            if system is not None and not messages:
                new_messages.append(system)
            new_messages.append(HumanMessage(content=text))
            debug_start = len(messages) + len(new_messages)
            may_classify = True
            result = await graph.ainvoke({"messages": new_messages}, config)
            may_classify = False
            after = await graph.aget_state(config)
            if after.next or after.interrupts:
                conversation.status = "blocked"
                recovery_notice(conversation)
                continue
        except Exception as exc:
            logger.exception("Chat turn failed")
            conversation.status = "blocked"
            try:
                snapshot = await graph.aget_state(config)
                if may_classify:
                    conversation.status = classify_failure(exc, snapshot)
            except Exception:
                logger.exception("Could not inspect failed conversation")
            conversation.last_error = turn_failure_message(exc, language)
            write(conversation.last_error)
            recovery_notice(conversation)
            continue

        conversation.status = "ready"
        conversation.last_error = None
        if debug:
            _render_debug(result["messages"][debug_start:], write)
        write(_reply_text(result["messages"]))
