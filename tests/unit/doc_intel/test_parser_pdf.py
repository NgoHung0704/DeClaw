"""PDF parsing, measured against text we generated ourselves.

Generating the fixture means recall is computed exactly rather than eyeballed
(DCL-101 asks for >95%).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fpdf import FPDF

from parsers.pdf import parse_pdf

PAGE_ONE = [
    "ARTICLE 3 - OBLIGATIONS DU PRESTATAIRE",
    "Le prestataire s'engage a fournir les services decrits en annexe.",
    "La resiliation peut intervenir moyennant un preavis de trois mois.",
]
PAGE_TWO = ["ARTICLE 4 - REMUNERATION", "Le montant total s'eleve a 12 000 euros HT."]


def _make_pdf(path: Path, pages: list[list[str]]) -> Path:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("helvetica", size=12)
    for lines in pages:
        pdf.add_page()
        for line in lines:
            # w=0 raises FPDFException; an explicit width is required.
            pdf.multi_cell(w=180, h=8, text=line)
    path.write_bytes(bytes(pdf.output()))
    return path


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def test_text_recall_exceeds_95_percent(tmp_path: Path) -> None:
    path = _make_pdf(tmp_path / "contrat.pdf", [PAGE_ONE, PAGE_TWO])
    parsed = parse_pdf(path)
    expected = _words(" ".join(PAGE_ONE + PAGE_TWO))
    got = _words(" ".join(b.text for b in parsed.blocks))
    recall = len(expected & got) / len(expected)
    assert recall > 0.95, f"recall {recall:.1%}, missing {sorted(expected - got)}"


def test_page_numbers_are_recorded_one_based(tmp_path: Path) -> None:
    path = _make_pdf(tmp_path / "c.pdf", [PAGE_ONE, PAGE_TWO])
    parsed = parse_pdf(path)
    assert parsed.page_count == 2
    pages = {b.page for b in parsed.blocks}
    assert pages == {1, 2}
    remuneration = next(b for b in parsed.blocks if "REMUNERATION" in b.text)
    assert remuneration.page == 2


def test_doc_type_is_pdf(tmp_path: Path) -> None:
    assert parse_pdf(_make_pdf(tmp_path / "c.pdf", [PAGE_ONE])).doc_type == "pdf"


def test_french_accents_survive_the_roundtrip(tmp_path: Path) -> None:
    # Assert on the string, never on console output: on Windows the terminal
    # codepage mangles accents in printed diagnostics even when data is fine.
    accented = "Résiliation à effet immédiat, société française"
    path = _make_pdf(tmp_path / "fr.pdf", [[accented]])
    parsed = parse_pdf(path)
    joined = " ".join(b.text for b in parsed.blocks)
    assert "�" not in joined
    assert "Résiliation" in joined


def test_a_pdf_with_no_extractable_text_is_reported_as_scanned(tmp_path: Path) -> None:
    # The important failure mode: silently indexing nothing would produce
    # confidently wrong answers about a document DeClaw never read.
    pdf = FPDF()
    pdf.add_page()  # a page with no text at all
    path = tmp_path / "scan.pdf"
    path.write_bytes(bytes(pdf.output()))
    parsed = parse_pdf(path)
    assert parsed.doc_type == "pdf-scanned"
    assert parsed.blocks == []
    assert parsed.page_count == 1


def test_a_corrupt_pdf_raises_a_readable_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is definitely not a pdf")
    with pytest.raises(ValueError) as excinfo:
        parse_pdf(path)
    assert "broken.pdf" in str(excinfo.value)
