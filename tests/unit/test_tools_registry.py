"""Unit tests for the tool registry (DCL-025).

Covers the acceptance criteria — registration via decorator, no eval/exec
(only concrete classes are accepted), unknown tool ID rejected, JSON schema
exposed — plus the READ/non-READ wiring in ``langchain_tools``.
"""

from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from declaw.tools.base import DeclawTool, ToolClass
from declaw.tools.confirmation import always_approve, always_deny
from declaw.tools.registry import (
    ToolRegistry,
    UnknownToolError,
    default_registry,
)


# --- Throwaway tools for registry tests -------------------------------------


class _ReadArgs(BaseModel):
    value: str


class _ReadTool(DeclawTool[_ReadArgs]):
    name: str = "demo_read"
    description_en: str = "read EN"
    description_fr: str = "read FR"
    classification: ToolClass = ToolClass.READ
    args_schema: type[_ReadArgs] = _ReadArgs

    async def _arun(self, args: _ReadArgs) -> str:
        return f"read {args.value}"


class _WriteTool(DeclawTool[_ReadArgs]):
    name: str = "demo_write"
    description_en: str = "write EN"
    description_fr: str = "write FR"
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[_ReadArgs] = _ReadArgs

    async def _arun(self, args: _ReadArgs) -> str:
        return f"wrote {args.value}"


# --- Registration: decorator + direct call ---------------------------------


def test_register_as_decorator_returns_class_and_registers() -> None:
    registry = ToolRegistry()

    @registry.register
    class _Decorated(DeclawTool[_ReadArgs]):
        name: str = "decorated"
        description_en: str = "en"
        description_fr: str = "fr"
        classification: ToolClass = ToolClass.READ
        args_schema: type[_ReadArgs] = _ReadArgs

        async def _arun(self, args: _ReadArgs) -> str:
            return "ok"

    # Decorator returns the class unchanged, and the tool is registered.
    assert _Decorated.__name__ == "_Decorated"
    assert registry.names() == ["decorated"]
    assert registry.get("decorated").classification is ToolClass.READ


def test_register_as_direct_call() -> None:
    registry = ToolRegistry()
    registry.register(_ReadTool)
    assert registry.names() == ["demo_read"]


def test_register_rejects_duplicate_name() -> None:
    registry = ToolRegistry()
    registry.register(_ReadTool)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_ReadTool)


# --- Lookup: unknown tool rejected -----------------------------------------


def test_get_unknown_tool_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(UnknownToolError):
        registry.get("does_not_exist")


def test_get_returns_registered_instance() -> None:
    registry = ToolRegistry()
    registry.register(_ReadTool)
    tool = registry.get("demo_read")
    assert isinstance(tool, _ReadTool)


# --- JSON schema export -----------------------------------------------------


def test_json_schemas_exposes_arg_schema_per_tool() -> None:
    registry = ToolRegistry()
    registry.register(_ReadTool)
    registry.register(_WriteTool)
    schemas = registry.json_schemas()
    assert set(schemas) == {"demo_read", "demo_write"}
    # Each schema is the pydantic JSON schema of the tool's args.
    assert "value" in schemas["demo_read"]["properties"]


# --- langchain_tools wiring: READ auto, non-READ gated ----------------------


async def test_langchain_tools_read_passes_through() -> None:
    registry = ToolRegistry()
    registry.register(_ReadTool)
    [lc_read] = registry.langchain_tools("en", always_deny)
    assert isinstance(lc_read, StructuredTool)
    # READ runs even when the provider would deny — it is never gated.
    assert await lc_read.ainvoke({"value": "x"}) == "read x"


async def test_langchain_tools_write_is_gated_by_confirmation() -> None:
    registry = ToolRegistry()
    registry.register(_WriteTool)

    [denied] = registry.langchain_tools("en", always_deny)
    assert await denied.ainvoke({"value": "x"}) == "User denied the call to demo_write."

    [approved] = registry.langchain_tools("en", always_approve)
    assert await approved.ainvoke({"value": "x"}) == "wrote x"


def test_langchain_tools_uses_locale_description() -> None:
    registry = ToolRegistry()
    registry.register(_ReadTool)
    [fr] = registry.langchain_tools("fr", always_approve)
    assert fr.description == "read FR"


# --- default_registry ------------------------------------------------------


def test_default_registry_has_all_builtin_filesystem_tools() -> None:
    registry = default_registry()
    assert registry.names() == [
        "filesystem_list",
        "filesystem_move",
        "filesystem_read",
        "filesystem_write",
    ]


def test_default_registry_classifications() -> None:
    registry = default_registry()
    assert registry.get("filesystem_read").classification is ToolClass.READ
    assert registry.get("filesystem_list").classification is ToolClass.READ
    assert registry.get("filesystem_write").classification is ToolClass.WRITE
    assert registry.get("filesystem_move").classification is ToolClass.WRITE
