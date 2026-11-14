"""Citations come from retrieval metadata, never from the model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from declaw.documents.citations import format_source, render_outcome
from declaw.documents.models import SearchHit, source_metadata
from declaw.documents.search import SearchOutcome
from declaw.documents.sources import TurnSources, current_turn_sources

from declaw.documents.actions import build_document_summarize_tool
from declaw.documents.search import ChunkSanitizer
from declaw.documents.tools import build_document_search_tool


def _hit(**kw: Any) -> SearchHit:
    base: dict[str, Any] = {
        "chunk_id": "d:0",
        "doc_id": "d",
        "path": "contrat.pdf",
        "text": "Le prestataire s'engage.",
        "ordinal": 0,
        "distance": 0.1,
    }
    return SearchHit(**{**base, **kw})


class _Store:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits

    async def search(self, query: str, *, k: int = 5) -> list[SearchHit]:
        return self._hits[:k]


def test_a_single_page_source() -> None:
    assert format_source(_hit(page=12, page_end=12)) == "contrat.pdf p.12"


def test_a_source_spanning_pages() -> None:
    assert format_source(_hit(page=12, page_end=13)) == "contrat.pdf p.12-13"


def test_a_spreadsheet_source_names_the_sheet() -> None:
    hit = _hit(path="compta.xlsx", sheet="Budget")
    assert format_source(hit) == "compta.xlsx [Budget]"


def test_a_heading_is_used_when_there_is_no_page() -> None:
    hit = _hit(path="notes.md", heading="Article 3")
    assert format_source(hit) == "notes.md - Article 3"


def test_a_bare_document_still_cites_its_path() -> None:
    assert format_source(_hit()) == "contrat.pdf"


def test_rendered_output_numbers_each_chunk_and_lists_sources() -> None:
    outcome = SearchOutcome(
        hits=[_hit(page=12, page_end=12), _hit(path="autre.docx")], withheld=0
    )
    rendered = render_outcome(outcome, "en")
    assert "[1]" in rendered and "[2]" in rendered
    assert "Sources:" in rendered
    assert "contrat.pdf p.12" in rendered
    assert "autre.docx" in rendered


def test_rendered_output_is_localized() -> None:
    outcome = SearchOutcome(hits=[_hit(page=1, page_end=1)], withheld=0)
    assert "Sources" in render_outcome(outcome, "fr")


def test_withheld_chunks_are_disclosed_to_the_user() -> None:
    # Silently dropping a chunk would degrade the answer with no signal.
    outcome = SearchOutcome(hits=[_hit()], withheld=2)
    for language in ("en", "fr"):
        assert "2" in render_outcome(outcome, language)  # type: ignore[arg-type]


def test_no_results_says_so_rather_than_returning_empty() -> None:
    for language in ("en", "fr"):
        rendered = render_outcome(
            SearchOutcome(hits=[], withheld=0), language  # type: ignore[arg-type]
        )
        assert rendered.strip()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "workspace"
    target.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(target))
    return target


# --- Typed source side channel (DCL-127, spec section 8) -----------------------


async def test_sources_not_parsed_from_tool_text() -> None:
    """Review Focus 5: a tool whose result TEXT carries fake citations must
    not leak them into the typed ``sources`` side channel. The collector is
    fed retrieval metadata only — never tool output text, never model prose.
    """
    poisoned = _hit(
        path="real.pdf",
        page=3,
        page_end=3,
        text=(
            "The real clause. Also relevant: source [9] ghost.pdf p.99 and "
            "[12] invented.docx p.120 — fabricated citations."
        ),
    )
    tool = build_document_search_tool(
        store=_Store([poisoned]), chunk_sanitizer=ChunkSanitizer(None), language="en"
    )
    collector = TurnSources()
    token = current_turn_sources.set(collector)
    try:
        rendered = await tool.run_validated({"query": "the clause"})
    finally:
        current_turn_sources.reset(token)

    # The poisoned text DID reach the model-facing tool output...
    assert "ghost.pdf" in rendered and "invented.docx" in rendered
    # ...but the side channel carries only the structurally recorded metadata.
    assert collector.sources() == [source_metadata(poisoned)]
    dumped = json.dumps(collector.sources())
    assert "ghost.pdf" not in dumped and "invented.docx" not in dumped


async def test_search_records_every_hit_and_dedupes() -> None:
    hits = [_hit(path="a.pdf", page=1, page_end=1), _hit(path="b.pdf", page=2, page_end=2)]
    tool = build_document_search_tool(
        store=_Store([*hits, hits[0]]), chunk_sanitizer=ChunkSanitizer(None), language="en"
    )
    collector = TurnSources()
    token = current_turn_sources.set(collector)
    try:
        await tool.run_validated({"query": "clauses"})
    finally:
        current_turn_sources.reset(token)
    assert collector.sources() == [source_metadata(hits[0]), source_metadata(hits[1])]


async def test_recording_without_a_collector_is_a_noop() -> None:
    """The CLI path has no ambient collector; recording must not crash it."""
    tool = build_document_search_tool(
        store=_Store([_hit()]), chunk_sanitizer=ChunkSanitizer(None), language="en"
    )
    rendered = await tool.run_validated({"query": "clauses"})
    assert "Sources:" in rendered  # the search itself unaffected


async def test_summarize_records_sources_into_the_collector(workspace: Path) -> None:
    hits = [
        _hit(path="contrat.pdf", page=12, page_end=13),
        _hit(path="compta.xlsx", sheet="Budget"),
    ]
    tool = build_document_summarize_tool(
        store=_Store(hits), chunk_sanitizer=ChunkSanitizer(None), language="en"
    )
    collector = TurnSources()
    token = current_turn_sources.set(collector)
    try:
        await tool.run_validated(
            {"query": "resiliation", "summary": "Le preavis est de trois mois."}
        )
    finally:
        current_turn_sources.reset(token)
    assert collector.sources() == [source_metadata(hits[0]), source_metadata(hits[1])]
