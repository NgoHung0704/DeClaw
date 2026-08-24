"""``document_search``: the only document capability the model can call.

Note the flag: ``produces_external_content = False``. That is NOT a shortcut
past the sanitizer. Retrieved chunks are classified inside ``search()``, one at
a time, cached by SHA-256 and run concurrently. Marking the tool as producing
external content would make the registry wrapper sanitize the concatenated
top-k a SECOND time — one large call per query, with nothing cacheable about
it. The real guarantee is held by tests: every chunk is classified, each
distinct chunk exactly once (tests/unit/test_documents_search.py), and nothing
unclassified reaches the model (tests/security/test_documents_isolation.py).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from declaw.config import Language
from declaw.documents.citations import render_outcome
from declaw.documents.prompts import chunk_preamble
from declaw.documents.search import (
    DEFAULT_K,
    ChunkSanitizer,
    SearchableStore,
    search_documents,
)
from declaw.tools.base import DeclawTool, ToolClass

SearchCallable = Callable[[str], Awaitable[str]]

_DESCRIPTION_EN = (
    "Search the user's indexed documents (PDF, Word, Excel, text) and return the "
    "most relevant passages together with the file and page they came from. Use "
    "this whenever the user asks about the content of their documents."
)
_DESCRIPTION_FR = (
    "Recherche dans les documents indexés de l'utilisateur (PDF, Word, Excel, "
    "texte) et renvoie les passages les plus pertinents avec le fichier et la "
    "page d'origine. À utiliser dès que l'utilisateur interroge ses documents."
)


class DocumentSearchArgs(BaseModel):
    """Arguments for ``document_search``.

    One field on purpose: the Phase 1 probes showed a 3B model calls flat,
    single-argument tools far more reliably, and ``k`` is a tuning knob rather
    than something the user is expressing.
    """

    query: str = Field(description="What to look for, in the user's own words.")


class DocumentSearchTool(DeclawTool[DocumentSearchArgs]):
    """Semantic search over the indexed document collection."""

    name: str = "document_search"
    description_en: str = _DESCRIPTION_EN
    description_fr: str = _DESCRIPTION_FR
    classification: ToolClass = ToolClass.READ
    args_schema: type[DocumentSearchArgs] = DocumentSearchArgs
    # See the module docstring: sanitizing happens inside search(), per chunk.
    produces_external_content: bool = False

    run_search: SearchCallable

    async def _arun(self, args: DocumentSearchArgs) -> str:
        return await self.run_search(args.query)


def build_document_search_tool(
    *,
    store: SearchableStore,
    chunk_sanitizer: ChunkSanitizer,
    language: Language,
    k: int = DEFAULT_K,
) -> DocumentSearchTool:
    """Wire a store and a chunk sanitizer into a registry-ready tool."""

    async def run_search(query: str) -> str:
        outcome = await search_documents(store, chunk_sanitizer, query, k=k)
        rendered = render_outcome(outcome, language)
        if not outcome.hits:
            return rendered
        return f"{chunk_preamble(language)}\n\n{rendered}"

    return DocumentSearchTool(run_search=run_search)
