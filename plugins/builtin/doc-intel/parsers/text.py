"""TXT and Markdown.

Markdown headings are not emitted as content blocks; they become the ``heading``
of the blocks that follow, which is what makes a citation read
"contrat.md - Article 3".

YAML frontmatter is skipped rather than indexed: it is metadata about the
document, and indexing it produces retrieval hits on the author's name.
"""

from __future__ import annotations

import re
from pathlib import Path

from models import Block, ParsedDocument

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_MARKDOWN_SUFFIXES = {".md", ".markdown"}


def _read(path: Path) -> str:
    # errors="replace" so one bad byte never costs the whole document.
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + len("\n---") :].lstrip("\n")


def parse_text(path: Path) -> ParsedDocument:
    """Parse a .txt/.md file into blocks, carrying Markdown headings."""
    is_markdown = path.suffix.lower() in _MARKDOWN_SUFFIXES
    raw = _read(path)
    if is_markdown:
        raw = _strip_frontmatter(raw)

    blocks: list[Block] = []
    heading: str | None = None
    for paragraph in re.split(r"\n\s*\n", raw):
        lines: list[str] = []
        for line in paragraph.splitlines():
            match = _HEADING_RE.match(line) if is_markdown else None
            if match is not None:
                if lines:
                    blocks.append(Block(text="\n".join(lines).strip(), heading=heading))
                    lines = []
                heading = match.group(2)
                continue
            lines.append(line)
        body = "\n".join(lines).strip()
        if body:
            blocks.append(Block(text=body, heading=heading))

    return ParsedDocument(
        doc_type="markdown" if is_markdown else "text",
        page_count=1,
        blocks=blocks,
    )
