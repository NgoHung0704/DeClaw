"""The one document capability the model can actually call."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from declaw.documents.models import SearchHit
from declaw.documents.search import ChunkSanitizer
from declaw.documents.tools import DocumentSearchTool, build_document_search_tool
from declaw.tools.base import ToolClass
from declaw.tools.registry import ToolRegistry


class FakeStore:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.queries: list[tuple[str, int]] = []

    async def search(self, query: str, *, k: int = 5) -> list[SearchHit]:
        self.queries.append((query, k))
        return self._hits[:k]


def _hit(text: str, ordinal: int = 0, page: int | None = 12) -> SearchHit:
    return SearchHit(
        chunk_id=f"d:{ordinal}",
        doc_id="d",
        path="contrat.pdf",
        text=text,
        ordinal=ordinal,
        distance=0.1,
        page=page,
        page_end=page,
    )


def _tool(hits: list[SearchHit], language: Any = "en") -> DocumentSearchTool:
    return build_document_search_tool(
        store=FakeStore(hits),
        chunk_sanitizer=ChunkSanitizer(None),
        language=language,
    )


def test_the_tool_is_read_class() -> None:
    assert _tool([]).classification is ToolClass.READ


def test_it_is_not_flagged_external_content() -> None:
    # Sanitizing happens inside search(), per chunk and cached. A second pass
    # by the registry wrapper would be one large uncacheable call per query.
    assert _tool([]).produces_external_content is False


def test_the_tool_takes_only_a_query() -> None:
    # Flat, single-argument signatures are what a 3B model calls reliably.
    assert set(_tool([]).args_schema.model_fields) == {"query"}


def test_a_missing_query_is_rejected_before_any_search() -> None:
    store = FakeStore([])
    tool = build_document_search_tool(
        store=store, chunk_sanitizer=ChunkSanitizer(None), language="en"
    )
    with pytest.raises(ValidationError):
        asyncio.run(tool.run_validated({}))
    assert store.queries == []


def test_the_result_contains_the_passage_and_its_source() -> None:
    tool = _tool([_hit("Le prestataire s'engage.")])
    output = asyncio.run(tool.run_validated({"query": "obligations"}))
    assert "Le prestataire s'engage." in output
    assert "contrat.pdf p.12" in output
    assert "Sources:" in output


def test_the_result_frames_passages_as_data_not_instructions() -> None:
    tool = _tool([_hit("some clause")])
    output = asyncio.run(tool.run_validated({"query": "q"}))
    assert "not instructions" in output.lower()


def test_the_french_tool_answers_in_french() -> None:
    tool = _tool([_hit("clause")], language="fr")
    output = asyncio.run(tool.run_validated({"query": "q"}))
    assert "Sources" in output
    assert "instructions" in output.lower()


def test_the_description_is_bilingual() -> None:
    tool = _tool([])
    assert tool.description_for("en") != tool.description_for("fr")
    assert "document" in tool.description_for("en").lower()


def test_no_matches_produces_an_actionable_message() -> None:
    output = asyncio.run(_tool([]).run_validated({"query": "anything"}))
    assert "declaw index" in output


def test_the_tool_registers_and_survives_langchain_wiring() -> None:
    registry = ToolRegistry()
    registry.register_instance(_tool([_hit("clause")]))

    async def approve(tool: Any, args: dict[str, Any]) -> bool:
        return True

    (lc_tool,) = registry.langchain_tools("en", approve)
    assert lc_tool.name == "document_search"
