"""Unit tests for the confirmation gate (DCL-022).

A tiny ``_RecordingTool`` (DeclawTool subclass) appends to a module-level list
whenever its ``_arun`` runs. That lets us prove deny prevents ``_arun`` from
running at all - not merely from returning its result.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError

from declaw.tools.base import DeclawTool, ToolClass
from declaw.tools.confirmation import (
    always_approve,
    always_deny,
    wrap_tool_with_confirmation,
)


# --- Test scaffolding: a recording DeclawTool subclass ----------------------


_invocations: list[str] = []


class _RecordedArgs(BaseModel):
    value: str


class _RecordingTool(DeclawTool[_RecordedArgs]):
    name: str = "recorder"
    description_en: str = "Record a value (EN)."
    description_fr: str = "Enregistre une valeur (FR)."
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[_RecordedArgs] = _RecordedArgs

    async def _arun(self, args: _RecordedArgs) -> str:
        _invocations.append(args.value)
        return f"recorded: {args.value}"


@pytest.fixture(autouse=True)
def _isolate_invocations() -> Iterator[None]:
    _invocations.clear()
    yield
    _invocations.clear()


@pytest.fixture
def tool() -> _RecordingTool:
    return _RecordingTool()


# --- Approval path ----------------------------------------------------------


async def test_approve_runs_the_tool_and_returns_the_result(
    tool: _RecordingTool,
) -> None:
    wrapped = wrap_tool_with_confirmation(tool, "en", always_approve)
    result = await wrapped.ainvoke({"value": "hello"})
    assert result == "recorded: hello"
    assert _invocations == ["hello"]


# --- Denial path: localized + actually blocks _arun -------------------------


async def test_deny_returns_localized_denial_in_english(
    tool: _RecordingTool,
) -> None:
    wrapped = wrap_tool_with_confirmation(tool, "en", always_deny)
    result = await wrapped.ainvoke({"value": "hello"})
    assert result == "User denied the call to recorder."
    assert _invocations == []  # _arun must not run on deny


async def test_deny_returns_localized_denial_in_french(
    tool: _RecordingTool,
) -> None:
    wrapped = wrap_tool_with_confirmation(tool, "fr", always_deny)
    result = await wrapped.ainvoke({"value": "salut"})
    assert result == "L'utilisateur a refusé l'appel à recorder."
    assert _invocations == []


# --- Provider receives the right context -----------------------------------


async def test_provider_receives_the_tool_and_args(tool: _RecordingTool) -> None:
    captured: dict[str, Any] = {}

    async def spy(t: DeclawTool[Any], args: dict[str, Any]) -> bool:
        captured["tool"] = t
        captured["args"] = args
        return True

    wrapped = wrap_tool_with_confirmation(tool, "en", spy)
    await wrapped.ainvoke({"value": "x"})

    assert captured["tool"] is tool
    assert captured["args"] == {"value": "x"}


# --- Wrapped tool keeps the model-facing metadata --------------------------


def test_wrapped_tool_keeps_name_description_schema(
    tool: _RecordingTool,
) -> None:
    """The gate must be invisible to ``bind_tools`` - same name, locale
    description, and args_schema as the underlying DeclawTool."""
    wrapped_en = wrap_tool_with_confirmation(tool, "en", always_approve)
    wrapped_fr = wrap_tool_with_confirmation(tool, "fr", always_approve)
    assert isinstance(wrapped_en, StructuredTool)
    assert wrapped_en.name == "recorder"
    assert wrapped_en.description == "Record a value (EN)."
    assert wrapped_fr.description == "Enregistre une valeur (FR)."
    assert wrapped_en.args_schema is _RecordedArgs


# --- Schema validation: still gates bad args, doesn't ask the provider -----


async def test_invalid_args_raise_validation_error_without_calling_provider(
    tool: _RecordingTool,
) -> None:
    """StructuredTool validates kwargs against args_schema before our gated
    coroutine runs, so bad args raise ValidationError - and the provider must
    not be consulted, because there is nothing meaningful to approve."""

    async def must_not_be_called(
        t: DeclawTool[Any], args: dict[str, Any]
    ) -> bool:
        raise AssertionError("provider should not be called when args are invalid")

    wrapped = wrap_tool_with_confirmation(tool, "en", must_not_be_called)
    with pytest.raises(ValidationError):
        await wrapped.ainvoke({})  # missing required 'value'
    assert _invocations == []
