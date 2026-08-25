"""Turning a plugin capability into a tool the brain can call."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from declaw.plugin_host.loader import ValidatedCapability
from declaw.plugin_host.tools import build_plugin_tool, plugin_tool_name
from declaw.tools.base import ToolClass
from declaw.tools.builtin.filesystem import FilesystemReadTool
from declaw.tools.registry import ToolRegistry
from declaw_plugin_sdk.protocol import CapabilityDescriptor


class Args(BaseModel):
    message: str
    times: int = 1


Invoke = Callable[[str, str, dict[str, Any]], Awaitable[Any]]


def _capability(**overrides: Any) -> ValidatedCapability:
    base: dict[str, Any] = {
        "name": "echo",
        "description_en": "Repeat a message.",
        "description_fr": "Repete un message.",
        "args_schema": Args.model_json_schema(),
        "classification": "read",
    }
    return ValidatedCapability(
        descriptor=CapabilityDescriptor(**{**base, **overrides}),
        permissions=(),
        args_model=Args,
    )


def _recording_invoke() -> tuple[list[tuple[str, str, dict[str, Any]]], Invoke]:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke(plugin: str, capability: str, args: dict[str, Any]) -> Any:
        calls.append((plugin, capability, args))
        return "bonjour"

    return calls, invoke


def test_tool_name_is_namespaced_with_dashes_converted() -> None:
    assert plugin_tool_name("doc-intel", "search") == "doc_intel_search"


def test_a_plugin_cannot_shadow_a_builtin_tool() -> None:
    # Namespacing is what makes this structurally impossible.
    assert plugin_tool_name("evil", "filesystem_read") != "filesystem_read"


def test_the_tool_forwards_validated_args_to_the_plugin() -> None:
    calls, invoke = _recording_invoke()
    tool = build_plugin_tool(plugin_name="echo-plugin", capability=_capability(), invoke=invoke)
    assert asyncio.run(tool.run_validated({"message": "salut", "times": 2})) == "bonjour"
    assert calls == [("echo-plugin", "echo", {"message": "salut", "times": 2})]


def test_invalid_args_are_rejected_before_the_plugin_is_contacted() -> None:
    calls, invoke = _recording_invoke()
    tool = build_plugin_tool(plugin_name="echo-plugin", capability=_capability(), invoke=invoke)
    with pytest.raises(ValidationError):
        asyncio.run(tool.run_validated({"times": 2}))
    assert calls == []  # nothing reached the subprocess


def test_a_structured_result_is_rendered_as_json_for_the_model() -> None:
    async def invoke(plugin: str, capability: str, args: dict[str, Any]) -> Any:
        return {"count": 3, "nom": "société"}

    tool = build_plugin_tool(plugin_name="p", capability=_capability(), invoke=invoke)
    rendered = asyncio.run(tool.run_validated({"message": "x"}))
    assert json.loads(rendered)["count"] == 3
    assert "société" in rendered  # accents survive; ensure_ascii is off


def test_classification_and_descriptions_come_from_the_capability() -> None:
    _, invoke = _recording_invoke()
    tool = build_plugin_tool(plugin_name="p", capability=_capability(), invoke=invoke)
    assert tool.classification is ToolClass.READ
    assert tool.description_for("fr") == "Repete un message."


def test_external_content_flag_is_carried_so_the_sanitizer_applies() -> None:
    _, invoke = _recording_invoke()
    capability = _capability(produces_external_content=True)
    tool = build_plugin_tool(plugin_name="p", capability=capability, invoke=invoke)
    assert tool.produces_external_content is True


def test_register_instance_adds_a_prebuilt_tool() -> None:
    _, invoke = _recording_invoke()
    registry = ToolRegistry()
    registry.register_instance(
        build_plugin_tool(plugin_name="echo-plugin", capability=_capability(), invoke=invoke)
    )
    assert registry.names() == ["echo_plugin_echo"]


def test_register_instance_still_refuses_a_duplicate_name() -> None:
    _, invoke = _recording_invoke()
    registry = ToolRegistry()
    registry.register(FilesystemReadTool)
    clashing = build_plugin_tool(
        plugin_name="filesystem", capability=_capability(name="read"), invoke=invoke
    )
    with pytest.raises(ValueError):
        registry.register_instance(clashing)


def test_a_registered_plugin_tool_reaches_bind_tools_intact() -> None:
    # The point of the proxy: everything downstream treats it as an ordinary
    # tool, with no idea a subprocess is involved.
    _, invoke = _recording_invoke()
    registry = ToolRegistry()
    registry.register_instance(
        build_plugin_tool(plugin_name="echo-plugin", capability=_capability(), invoke=invoke)
    )

    async def approve(tool: Any, args: dict[str, Any]) -> bool:
        return True

    (lc_tool,) = registry.langchain_tools("fr", approve)
    assert lc_tool.name == "echo_plugin_echo"
    assert lc_tool.description == "Repete un message."
