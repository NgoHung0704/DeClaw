"""A plugin capability, dressed as an ordinary tool.

Everything downstream — ``bind_tools``, ``ToolNode``, the confirmation gate,
the sanitizer wrapper, the audit wrapper — treats this exactly like a built-in
tool, because it IS one: a ``DeclawTool`` whose ``_arun`` happens to travel
over a pipe. Nothing in the registry or the brain needs to know a subprocess
is involved.

Names are namespaced with the plugin slug, so a plugin cannot shadow
``filesystem_read`` no matter what it calls its capability.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from declaw.plugin_host.loader import ValidatedCapability
from declaw.tools.base import DeclawTool, ToolClass

InvokeCallable = Callable[[str, str, dict[str, Any]], Awaitable[Any]]


def plugin_tool_name(plugin: str, capability: str) -> str:
    """Build the model-visible tool name for one capability."""
    return f"{plugin.replace('-', '_')}_{capability.replace('-', '_')}"


class PluginTool(DeclawTool[BaseModel]):
    """A ``DeclawTool`` that forwards to a plugin process."""

    plugin: str
    capability: str
    invoke: InvokeCallable

    async def _arun(self, args: BaseModel) -> str:
        result = await self.invoke(self.plugin, self.capability, args.model_dump(mode="json"))
        if isinstance(result, str):
            return result
        # ensure_ascii=False so French accents reach the model intact.
        return json.dumps(result, ensure_ascii=False, indent=2)


def build_plugin_tool(
    *, plugin_name: str, capability: ValidatedCapability, invoke: InvokeCallable
) -> PluginTool:
    """Wrap one validated capability as a registry-ready tool."""
    descriptor = capability.descriptor
    return PluginTool(
        name=plugin_tool_name(plugin_name, descriptor.name),
        description_en=descriptor.description_en,
        description_fr=descriptor.description_fr,
        classification=ToolClass(descriptor.classification),
        args_schema=capability.args_model,
        produces_external_content=descriptor.produces_external_content,
        plugin=plugin_name,
        capability=descriptor.name,
        invoke=invoke,
    )
