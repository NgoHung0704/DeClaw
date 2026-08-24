"""Citations come from retrieval metadata, never from the model."""

from __future__ import annotations

from typing import Any

from declaw.documents.citations import format_source, render_outcome
from declaw.documents.models import SearchHit
from declaw.documents.search import SearchOutcome


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
