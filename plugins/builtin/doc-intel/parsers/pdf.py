"""PDF text extraction with pypdf.

No OCR. A scanned PDF yields no extractable text, and the one thing we must not
do is index it as nothing — the user would later get confident answers about a
document DeClaw never read. Such a file is reported as
``doc_type="pdf-scanned"`` with zero blocks so the indexer can say so out loud.

``unstructured`` was dropped from the dependencies with this decision: OCR is a
subproject (model weights, language packs, a runtime download that would
contradict the offline promise), not a fallback branch.
"""

from __future__ import annotations

from pathlib import Path

from models import Block, ParsedDocument
from pypdf import PdfReader
from pypdf.errors import PyPdfError


def parse_pdf(path: Path) -> ParsedDocument:
    """Extract text per page. Raises ``ValueError`` if the file is unreadable."""
    try:
        reader = PdfReader(str(path))
        pages = list(reader.pages)
    except (PyPdfError, OSError, ValueError) as exc:
        raise ValueError(f"Cannot read PDF {path.name}: {exc}") from exc

    blocks: list[Block] = []
    for number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except (PyPdfError, ValueError):
            # One unreadable page must not cost the whole document.
            continue
        for paragraph in text.split("\n\n"):
            body = paragraph.strip()
            if body:
                blocks.append(Block(text=body, page=number))

    doc_type = "pdf" if blocks else "pdf-scanned"
    return ParsedDocument(doc_type=doc_type, page_count=len(pages), blocks=blocks)
