"""Confirmation gate for non-READ tools (DCL-022).

DeClaw targets regulated professionals. With the Phase 1 probe baseline at
~63% tool-call accuracy, letting Mistral autonomously WRITE or DESTROY user
files would mean roughly 1 in 3 modifications happens against the user's
intent. ``ToolClass`` labels (DCL-020) + this gate are the architectural
answer: every non-READ call awaits a ``ConfirmationProvider`` before the
tool's ``_arun`` ever runs.

Providers in production ask the human (REPL prompt today, gateway approval
broker in Phase 9); tests inject ``always_approve`` / ``always_deny`` for
deterministic coverage. On deny the wrapper returns a localized denial string
instead of executing — LangGraph's ``ToolNode`` surfaces that as a
``ToolMessage`` the model (and the audit trail) can see.

Validate-before-prompt (DCL-125, spec section 7, ratified decision 20.10):
arguments are validated against the tool's ``args_schema`` BEFORE the provider
is consulted. Invalid arguments return a validation-error observation to the
model without ever prompting, the prompt displays the canonical validated
dump, and the same validated object executes on approval — the user always
approves exactly what will run. CLI and gateway share this wrapper, so they
cannot diverge. A ``ConfirmationProvider`` is therefore always given an
already-validated ``args`` payload.

The wrapped tool keeps the *exact* same name, description (locale-correct),
and ``args_schema`` as the underlying ``DeclawTool``, so ``bind_tools`` still
sees a coherent function from the model's point of view — the gate is
invisible to the prompt.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from declaw.config import Language
from declaw.log import logger
from declaw.tools.base import DeclawTool

if TYPE_CHECKING:  # runtime import stays local to keep the tool layer light
    from declaw.audit.logger import AuditLogger

# Async predicate: should this non-READ tool call be allowed to run?
# Any ``async def f(tool, args) -> bool`` is a valid provider. ``args`` is the
# canonical validated dump of the call (validate-before-prompt, spec §7): a
# provider is never consulted for invalid arguments and what it shows the
# human is exactly what executes on approval.
ConfirmationProvider = Callable[[DeclawTool[Any], dict[str, Any]], Awaitable[bool]]


async def always_approve(tool: DeclawTool[Any], args: dict[str, Any]) -> bool:
    """Approve every call. For tests and trusted batch jobs."""
    return True


async def always_deny(tool: DeclawTool[Any], args: dict[str, Any]) -> bool:
    """Deny every call. Useful as a kill switch or in safety-mode tests."""
    return False


_DENIAL_EN = "User denied the call to {name}."
_DENIAL_FR = "L'utilisateur a refusé l'appel à {name}."

_VALIDATION_EN = (
    "Invalid arguments for {name}: {errors} The call was not executed and "
    "the user was not asked; fix the arguments and try again."
)
_VALIDATION_FR = (
    "Arguments invalides pour {name} : {errors} L'appel n'a pas été "
    "exécuté et l'utilisateur n'a pas été consulté ; corrigez les "
    "arguments et réessayez."
)


def denial_message(tool_name: str, language: Language) -> str:
    """The exact localized string returned on a denied call.

    Public because the audit wrapper (DCL-061) matches tool results against it
    to record the outcome as ``denied`` — the string is DeClaw-generated and
    deterministic, so the comparison is exact.
    """
    template = _DENIAL_FR if language == "fr" else _DENIAL_EN
    return template.format(name=tool_name)


def validation_failure_message(
    tool_name: str, exc: ValidationError, language: Language
) -> str:
    """The exact localized observation returned for invalid arguments.

    The error summary names the offending fields and reasons (never the
    rejected input values), so the model can fix the call it just made. This
    is what the model sees instead of a prompt (validate-before-prompt)."""
    errors = "; ".join(
        "{}: {}".format(".".join(str(loc) for loc in error["loc"]), error["msg"])
        for error in exc.errors()
    )
    template = _VALIDATION_FR if language == "fr" else _VALIDATION_EN
    return template.format(name=tool_name, errors=errors)


class RawArgsStructuredTool(StructuredTool):
    """A ``StructuredTool`` whose coroutine receives the raw, unvalidated kwargs.

    langchain-core validates against ``args_schema`` inside ``_parse_input``
    and *raises* ``ValidationError`` before the coroutine can run, which
    would move validation ahead of this module's gate and turn a fixable
    model mistake into a raised exception instead of an observation. Tools
    that own validation themselves (the confirmation gate, the audit
    wrapper around it) use this class so the coroutine decides what bad input
    means. ``args_schema`` is kept unchanged, so ``bind_tools`` still sees the
    exact same advertised schema.
    """

    def _parse_input(
        self, tool_input: str | dict[str, Any], tool_call_id: str | None
    ) -> str | dict[str, Any]:
        return tool_input


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

    Ordering (spec section 7.1): validate before prompt. Raw arguments are
    validated against ``tool.args_schema`` first; invalid arguments become a
    validation-error observation returned to the model, and the provider is
    never consulted. The provider is then given the canonical validated dump
    (``validated.model_dump()``) — the prompt shows exactly what will run —
    and on approval the very same validated object executes, without a second
    parse.
    """

    async def gated_coroutine(**kwargs: Any) -> str:
        # 1. Validate FIRST: there is nothing meaningful to approve about a
        #    call whose arguments do not even match the schema.
        try:
            validated = tool.args_schema.model_validate(kwargs)
        except ValidationError as exc:
            logger.bind(tool=tool.name).debug("Tool call rejected by args schema before prompting")
            return validation_failure_message(tool.name, exc, language)

        # 2. Prompt with the canonical validated dump — schema defaults
        #    included, undeclared keys stripped — so the human approves
        #    exactly what will run.
        canonical = validated.model_dump()
        approved = await approve(tool, canonical)

        if audit is not None:
            from declaw.audit.events import PermissionPromptEvent, clip_args

            await audit.emit(
                PermissionPromptEvent(
                    tool_name=tool.name,
                    args=clip_args(canonical),
                    decision="approved" if approved else "denied",
                )
            )
        if not approved:
            return denial_message(tool.name, language)

        # 3. Execute THE validated object from step 1 (identity, no
        #    re-parsing): what was approved is what runs.
        return await tool._arun(validated)

    return RawArgsStructuredTool(
        coroutine=gated_coroutine,
        name=tool.name,
        description=tool.description_for(language),
        args_schema=tool.args_schema,
    )
