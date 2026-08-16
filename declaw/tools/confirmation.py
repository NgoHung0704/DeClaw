"""Confirmation gate for non-READ tools (DCL-022).

DeClaw targets regulated professionals. With the Phase 1 probe baseline at
~63% tool-call accuracy, letting Mistral autonomously WRITE or DESTROY user
files would mean roughly 1 in 3 modifications happens against the user's
intent. ``ToolClass`` labels (DCL-020) + this gate are the architectural
answer: every non-READ call awaits a ``ConfirmationProvider`` before the
tool's ``_arun`` ever runs.

Providers in production ask the human (REPL prompt today, native dialog
later); tests inject ``always_approve`` / ``always_deny`` for deterministic
coverage. On deny the wrapper returns a localized denial string instead of
executing — LangGraph's ``ToolNode`` surfaces that as a ``ToolMessage`` the
model (and the audit trail) can see.

The wrapped tool keeps the *exact* same name, description (locale-correct),
and ``args_schema`` as the underlying ``DeclawTool``, so ``bind_tools`` still
sees a coherent function from the model's point of view — the gate is
invisible to the prompt.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool

from declaw.config import Language
from declaw.tools.base import DeclawTool

if TYPE_CHECKING:  # runtime import stays local to keep the tool layer light
    from declaw.audit.logger import AuditLogger

# Async predicate: should this non-READ tool call be allowed to run?
# Any ``async def f(tool, args) -> bool`` is a valid provider.
ConfirmationProvider = Callable[[DeclawTool[Any], dict[str, Any]], Awaitable[bool]]


async def always_approve(tool: DeclawTool[Any], args: dict[str, Any]) -> bool:
    """Approve every call. For tests and trusted batch jobs."""
    return True


async def always_deny(tool: DeclawTool[Any], args: dict[str, Any]) -> bool:
    """Deny every call. Useful as a kill switch or in safety-mode tests."""
    return False


_DENIAL_EN = "User denied the call to {name}."
_DENIAL_FR = "L'utilisateur a refusé l'appel à {name}."


def denial_message(tool_name: str, language: Language) -> str:
    """The exact localized string returned on a denied call.

    Public because the audit wrapper (DCL-061) matches tool results against it
    to record the outcome as ``denied`` — the string is DeClaw-generated and
    deterministic, so the comparison is exact.
    """
    template = _DENIAL_FR if language == "fr" else _DENIAL_EN
    return template.format(name=tool_name)


def wrap_tool_with_confirmation(
    tool: DeclawTool[Any],
    language: Language,
    approve: ConfirmationProvider,
    *,
    audit: AuditLogger | None = None,
) -> StructuredTool:
    """Return a ``StructuredTool`` that gates ``tool`` behind ``approve``.

    Use this for any non-READ tool. READ tools should pass through
    ``DeclawTool.as_langchain_tool`` directly (no need to gate a pure read).
    When ``audit`` is supplied, every human decision is recorded as a
    ``PermissionPromptEvent`` (DCL-061) — approvals and denials both.
    """

    async def gated_coroutine(**kwargs: Any) -> str:
        approved = await approve(tool, kwargs)
        if audit is not None:
            from declaw.audit.events import PermissionPromptEvent, clip_args

            await audit.emit(
                PermissionPromptEvent(
                    tool_name=tool.name,
                    args=clip_args(kwargs),
                    decision="approved" if approved else "denied",
                )
            )
        if not approved:
            return denial_message(tool.name, language)
        return await tool.run_validated(kwargs)

    return StructuredTool.from_function(
        coroutine=gated_coroutine,
        name=tool.name,
        description=tool.description_for(language),
        args_schema=tool.args_schema,
    )
