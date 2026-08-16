"""Audit wrapper for brain-facing tools (DCL-061).

``wrap_tool_with_audit`` is the outermost layer of the tool onion the registry
builds (audit around confirmation around sanitizer around the tool), so the
emitted :class:`ToolCallEvent` describes the call exactly as the model
experienced it: what was asked, whether it ran, was denied, or blew up, and
how long it took.

Like the confirmation and sanitizer wrappers, the wrapped tool keeps the same
name / description / args_schema — invisible to ``bind_tools``.

Outcome detection: a denial is recognized by comparing the inner result to the
localized denial string DeClaw itself generates (``denial_message``); that
string is ours, deterministic, and never produced by a real tool, so the check
is exact, not heuristic.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.tools import StructuredTool

from declaw.audit.events import ToolCallEvent, clip_args
from declaw.audit.logger import AuditLogger
from declaw.config import Language
from declaw.tools.base import DeclawTool
from declaw.tools.confirmation import denial_message


def wrap_tool_with_audit(
    inner: StructuredTool,
    *,
    tool: DeclawTool[Any],
    language: Language,
    audit: AuditLogger,
) -> StructuredTool:
    """Return ``inner`` wrapped so every invocation emits a ``ToolCallEvent``.

    Errors are logged with outcome ``"error"`` and re-raised — auditing
    observes, it never swallows.
    """
    inner_coroutine = inner.coroutine
    if inner_coroutine is None:  # pragma: no cover - all DeClaw tools are async
        raise ValueError(f"Tool {inner.name!r} has no async coroutine to wrap.")
    denied_marker = denial_message(tool.name, language)

    async def audited_coroutine(**kwargs: Any) -> str:
        start = time.perf_counter()
        try:
            result = await inner_coroutine(**kwargs)
        except Exception as exc:
            await audit.emit(
                ToolCallEvent(
                    tool_name=tool.name,
                    classification=tool.classification.value,
                    args=clip_args(kwargs),
                    outcome="error",
                    error=str(exc)[:500],
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
            )
            raise
        await audit.emit(
            ToolCallEvent(
                tool_name=tool.name,
                classification=tool.classification.value,
                args=clip_args(kwargs),
                outcome="denied" if result == denied_marker else "ok",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        )
        return str(result)

    return StructuredTool.from_function(
        coroutine=audited_coroutine,
        name=inner.name,
        description=inner.description,
        args_schema=tool.args_schema,
    )
