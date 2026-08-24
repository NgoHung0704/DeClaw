"""TXT and Markdown parsing: headings preserved, frontmatter stripped."""

from __future__ import annotations

from pathlib import Path

from parsers.text import parse_text


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_plain_text_becomes_blocks(tmp_path: Path) -> None:
    path = _write(tmp_path, "notes.txt", "First paragraph.\n\nSecond paragraph.")
    parsed = parse_text(path)
    assert parsed.doc_type == "text"
    assert [b.text for b in parsed.blocks] == ["First paragraph.", "Second paragraph."]


def test_markdown_headings_are_attached_to_following_blocks(tmp_path: Path) -> None:
    body = "# Contrat\n\nPreambule.\n\n## Article 3\n\nObligations du prestataire.\n"
    path = _write(tmp_path, "contrat.md", body)
    parsed = parse_text(path)
    assert parsed.doc_type == "markdown"
    by_text = {b.text: b.heading for b in parsed.blocks}
    assert by_text["Preambule."] == "Contrat"
    assert by_text["Obligations du prestataire."] == "Article 3"


def test_yaml_frontmatter_is_not_treated_as_content(tmp_path: Path) -> None:
    body = "---\ntitle: Contrat\nauthor: Dupont\n---\n\nLe corps du document.\n"
    path = _write(tmp_path, "doc.md", body)
    parsed = parse_text(path)
    texts = [b.text for b in parsed.blocks]
    assert texts == ["Le corps du document."]
    assert not any("author" in t for t in texts)


def test_french_accents_survive(tmp_path: Path) -> None:
    path = _write(tmp_path, "fr.txt", "Résiliation à effet immédiat.")
    (block,) = parse_text(path).blocks
    assert block.text == "Résiliation à effet immédiat."


def test_an_empty_file_yields_no_blocks(tmp_path: Path) -> None:
    parsed = parse_text(_write(tmp_path, "empty.txt", "   \n\n  "))
    assert parsed.blocks == []


def test_text_documents_report_one_page(tmp_path: Path) -> None:
    # Plain text has no pagination; page_count 1 keeps the field meaningful.
    parsed = parse_text(_write(tmp_path, "a.txt", "body"))
    assert parsed.page_count == 1
    assert parsed.blocks[0].page is None


def test_undecodable_bytes_do_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "latin.txt"
    path.write_bytes(b"Caf\xe9 non-UTF8")
    parsed = parse_text(path)
    assert parsed.blocks  # replaced characters, but content recovered
