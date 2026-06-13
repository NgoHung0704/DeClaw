"""DeclawTool: typed, locale-aware base for every tool the brain may call (DCL-020).

The Phase 1 probe (``scripts/probe_mistral.py`` against ``BENCHMARK_CORPUS_V0``)
found that Mistral 7B never invokes a tool from natural French phrasing unless
the tool's description is in French (FR implicit accuracy was 0/5 with
English-only descriptions). It also confirmed across three runs that schema
validation is the only repair branch that ever fires on real Ollama, and that
when confused the model picks the closest *existing* tool. Three rules follow:

1. Every tool carries a typed Pydantic ``args_schema``; raw shell strings are
   forbidden (Principle #6). Invalid args are rejected at the wrapper and
   never reach the implementation.
2. Every tool carries both an English AND a French description. The brain
   picks the correct one at bind-time via ``as_langchain_tool(language)``.
3. Every tool declares a ``ToolClass`` (read / write / destructive). The
   confirmation queue (later ticket) uses this to gate non-read calls behind
   explicit user approval.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Generic, TypeVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict

from declaw.config import Language


class ToolClass(StrEnum):
    """How safe is this tool to call without explicit user confirmation?"""

    READ = "read"  # Pure read; safe to autonomously execute.
    WRITE = "write"  # Modifies state but is reversible (write, rename). Needs confirm.
    DESTRUCTIVE = "destructive"  # Cannot be safely undone (delete). Confirm + warn.


ArgsT = TypeVar("ArgsT", bound=BaseModel)


class DeclawTool(BaseModel, Generic[ArgsT]):
    """Abstract base for every tool the brain may call.

    Subclasses MUST override ``_arun`` and parameterise the generic with their
    concrete ``args_schema`` model (``class EchoTool(DeclawTool[EchoArgs])``).
    The base class is technically instantiable (every field has a default in
    a subclass or is supplied at construction) but its ``_arun`` raises
    ``NotImplementedError``, so treat the base as abstract.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description_en: str
    description_fr: str
    classification: ToolClass
    args_schema: type[ArgsT]

    async def _arun(self, args: ArgsT) -> str:
        """Run the tool with already-validated args. Subclasses MUST override."""
        raise NotImplementedError(
            f"DeclawTool subclasses must implement _arun; {type(self).__name__} did not."
        )

    def description_for(self, language: Language) -> str:
        """Return the description in the requested language."""
        return self.description_fr if language == "fr" else self.description_en

    async def run_validated(self, raw_args: dict[str, Any]) -> str:
        """Validate ``raw_args`` against ``args_schema`` then call ``_arun``.

        Raises ``pydantic.ValidationError`` if the args do not match the schema.
        """
        validated = self.args_schema.model_validate(raw_args)
        return await self._arun(validated)

    def as_langchain_tool(self, language: Language) -> StructuredTool:
        """Build a ``langchain_core.tools.StructuredTool`` ready for ``bind_tools``.

        The description is selected by ``language`` so Mistral sees the prompt
        in the user's locale (probe data: FR implicit reliability depends on it).
        """
        tool = self

        async def coroutine(**kwargs: Any) -> str:
            return await tool.run_validated(kwargs)

        return StructuredTool.from_function(
            coroutine=coroutine,
            name=self.name,
            description=self.description_for(language),
            args_schema=self.args_schema,
        )
