"""Typed tool registry (DCL-025).

A ``ToolRegistry`` maps tool names to ``DeclawTool`` instances. Registration is
explicit and type-checked — there is no ``eval``/``exec`` and no string-driven
construction (Principle #6): you register a concrete ``DeclawTool`` subclass,
the registry instantiates it once (tools are stateless + frozen), and stores
the instance under its ``name``.

``register`` works both as a class decorator and as a direct call::

    registry = ToolRegistry()

    @registry.register
    class MyTool(DeclawTool[MyArgs]):
        ...

    registry.register(FilesystemReadTool)  # same thing, direct call

``langchain_tools(language, approve)`` is the single source of truth for wiring
tools into the brain: READ tools pass through ``as_langchain_tool`` (safe to
auto-run), every other classification is wrapped by the confirmation gate
(DCL-022) so the user is asked before a WRITE/DESTRUCTIVE call executes. The
same list is what goes into both ``bind_tools`` (model) and ``ToolNode``
(executor).

``default_registry()`` registers the built-in filesystem tools explicitly in
one place, so "every built-in tool DeClaw ships" is auditable at a glance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool

from declaw.config import Language
from declaw.sanitizer.pipeline import wrap_tool_with_sanitizer
from declaw.sanitizer.sanitizer import Sanitizer
from declaw.tools.base import DeclawTool, ToolClass

if TYPE_CHECKING:
    from declaw.audit.logger import AuditLogger
from declaw.tools.builtin.filesystem import (
    FilesystemListTool,
    FilesystemMoveTool,
    FilesystemReadTool,
    FilesystemWriteTool,
)
from declaw.tools.confirmation import ConfirmationProvider, wrap_tool_with_confirmation


class UnknownToolError(KeyError):
    """Raised when a tool name is not present in the registry."""


class ToolRegistry:
    """A name -> ``DeclawTool`` instance map with typed registration."""

    def __init__(self) -> None:
        self._tools: dict[str, DeclawTool[Any]] = {}

    def register_instance(self, tool: DeclawTool[Any]) -> DeclawTool[Any]:
        """Register an already-constructed tool.

        Plugin proxy tools (DCL-090) are bound to a specific plugin and
        capability, so they cannot be built by the class-and-instantiate path
        ``register`` uses. Both routes share this one insertion point, so the
        duplicate check cannot be bypassed by picking the other one.
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool
        return tool

    def register(self, tool_cls: type[DeclawTool[Any]]) -> type[DeclawTool[Any]]:
        """Instantiate and register ``tool_cls``. Usable as a class decorator.

        Returns the class unchanged so it stays usable after decoration. Raises
        ``ValueError`` if a tool with the same name is already registered.
        """
        # Concrete DeclawTool subclasses default every field (DCL-020), so they
        # instantiate with no args; the base type ``type[DeclawTool[Any]]``
        # can't express that, hence the targeted ignore.
        self.register_instance(tool_cls())  # type: ignore[call-arg]
        return tool_cls

    def get(self, name: str) -> DeclawTool[Any]:
        """Return the registered tool named ``name`` or raise ``UnknownToolError``."""
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(name) from None

    def names(self) -> list[str]:
        """Return the registered tool names, sorted."""
        return sorted(self._tools)

    def json_schemas(self) -> dict[str, dict[str, Any]]:
        """Return ``{tool_name: JSON schema of its args}`` for every tool."""
        return {
            name: tool.args_schema.model_json_schema()
            for name, tool in self._tools.items()
        }

    def langchain_tools(
        self,
        language: Language,
        approve: ConfirmationProvider,
        *,
        sanitizer: Sanitizer | None = None,
        audit: AuditLogger | None = None,
    ) -> list[StructuredTool]:
        """Build the brain-ready tool list with READ/non-READ + sanitizer wiring.

        READ tools pass through ``as_langchain_tool`` (safe to auto-run); every
        other classification is gated behind ``approve`` via the confirmation
        wrapper. When a ``sanitizer`` is supplied, any tool whose
        ``produces_external_content`` flag is set has its output routed through
        the sanitizer first (Principle #4) — UNSAFE output is quarantined and
        replaced before the model sees it. When an ``audit`` logger is supplied
        (DCL-061), every tool is additionally wrapped so each invocation emits a
        ``ToolCallEvent`` and every confirmation decision a
        ``PermissionPromptEvent`` — the audit wrapper is outermost, so it records
        the call exactly as the model experienced it. Feed the result to both
        ``bind_tools`` and ``ToolNode``.

        (The built-in external-content tool, ``filesystem_read``, is READ. A
        hypothetical non-READ external-content tool would need confirmation *and*
        sanitizing composed; none ships today, so that path is not wired.)
        """
        tools: list[StructuredTool] = []
        for name in self.names():
            tool = self._tools[name]
            if tool.classification is ToolClass.READ:
                if sanitizer is not None and tool.produces_external_content:
                    lc_tool = wrap_tool_with_sanitizer(tool, language, sanitizer)
                else:
                    lc_tool = tool.as_langchain_tool(language)
            else:
                lc_tool = wrap_tool_with_confirmation(tool, language, approve, audit=audit)
            if audit is not None:
                from declaw.audit.tooling import wrap_tool_with_audit

                lc_tool = wrap_tool_with_audit(
                    lc_tool, tool=tool, language=language, audit=audit
                )
            tools.append(lc_tool)
        return tools


_BUILTIN_TOOLS: tuple[type[DeclawTool[Any]], ...] = (
    FilesystemReadTool,
    FilesystemWriteTool,
    FilesystemMoveTool,
    FilesystemListTool,
)


def default_registry() -> ToolRegistry:
    """Return a fresh registry with every built-in tool registered.

    The explicit ``_BUILTIN_TOOLS`` tuple is the single auditable list of
    everything DeClaw ships out of the box.
    """
    registry = ToolRegistry()
    for tool_cls in _BUILTIN_TOOLS:
        registry.register(tool_cls)
    return registry
