"""Unit tests for the DeclawTool base (DCL-020).

Acceptance: a typed subclass passes mypy strict (this whole file is type-checked
under strict, so its mere existence is part of the proof), and runtime rejects
invalid args via the schema. Extra coverage: locale switch, langchain adapter
round-trip, frozen guarantee, default-on-optional.
"""

from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError

from declaw.tools.base import DeclawTool, ToolClass


# --- A concrete subclass shared across tests -----------------------------------


class EchoArgs(BaseModel):
    message: str
    times: int = 1


_EN = "Echo MESSAGE back, repeated TIMES times."
_FR = "Renvoie MESSAGE répété TIMES fois."


class EchoTool(DeclawTool[EchoArgs]):
    name: str = "echo"
    description_en: str = _EN
    description_fr: str = _FR
    classification: ToolClass = ToolClass.READ
    args_schema: type[EchoArgs] = EchoArgs

    async def _arun(self, args: EchoArgs) -> str:
        return " ".join([args.message] * args.times)


# --- Acceptance: subclass exists, runtime validation, schema --------------------


def test_subclass_instantiates_with_defaults() -> None:
    tool = EchoTool()
    assert tool.name == "echo"
    assert tool.classification is ToolClass.READ
    assert tool.args_schema is EchoArgs


async def test_run_validated_with_valid_args_returns_arun_result() -> None:
    tool = EchoTool()
    assert await tool.run_validated({"message": "hi", "times": 3}) == "hi hi hi"


async def test_run_validated_uses_default_for_optional_field() -> None:
    tool = EchoTool()
    # ``times`` has a default of 1; omitting it is fine.
    assert await tool.run_validated({"message": "hello"}) == "hello"


async def test_run_validated_rejects_missing_required_field() -> None:
    tool = EchoTool()
    with pytest.raises(ValidationError):
        await tool.run_validated({})  # 'message' is required


async def test_run_validated_rejects_wrong_arg_type() -> None:
    tool = EchoTool()
    with pytest.raises(ValidationError):
        await tool.run_validated({"message": "hi", "times": "not a number"})


# --- Abstract enforcement -----------------------------------------------------


async def test_base_arun_raises_when_not_overridden() -> None:
    """The base class is structurally instantiable; calling _arun must fail loudly."""

    class _NoArgs(BaseModel):
        pass

    class _Raw(DeclawTool[_NoArgs]):
        pass

    raw = _Raw(
        name="raw",
        description_en="x",
        description_fr="x",
        classification=ToolClass.READ,
        args_schema=_NoArgs,
    )
    with pytest.raises(NotImplementedError, match="_Raw"):
        await raw._arun(_NoArgs())


# --- Locale switch -------------------------------------------------------------


def test_description_for_returns_locale_specific_text() -> None:
    tool = EchoTool()
    assert tool.description_for("en") == _EN
    assert tool.description_for("fr") == _FR
    assert tool.description_for("en") != tool.description_for("fr")


# --- langchain adapter round-trip ----------------------------------------------


def test_as_langchain_tool_carries_locale_description_and_schema() -> None:
    tool = EchoTool()
    en = tool.as_langchain_tool("en")
    fr = tool.as_langchain_tool("fr")
    assert isinstance(en, StructuredTool)
    assert en.name == "echo"
    assert en.description == _EN
    assert fr.description == _FR
    assert en.args_schema is EchoArgs


async def test_as_langchain_tool_executes_end_to_end() -> None:
    """Proves the langchain adapter actually runs the tool — what ToolNode will do."""
    lc_tool = EchoTool().as_langchain_tool("en")
    assert await lc_tool.ainvoke({"message": "ping", "times": 2}) == "ping ping"


async def test_as_langchain_tool_validates_args_via_schema() -> None:
    """An invalid tool call through langchain must surface as a ValidationError."""
    lc_tool = EchoTool().as_langchain_tool("en")
    with pytest.raises(ValidationError):
        await lc_tool.ainvoke({"message": "hi", "times": "nope"})


# --- Immutability --------------------------------------------------------------


def test_tool_is_frozen() -> None:
    tool = EchoTool()
    with pytest.raises(ValidationError):
        tool.name = "renamed"
