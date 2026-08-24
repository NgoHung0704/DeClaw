"""doc-intel: turn a document into citable text chunks, and nothing else.

This plugin is deliberately thin. It parses adversarial binary files from
strangers — which is exactly what the subprocess boundary is worth having for —
and hands back plain text. Embedding, encryption, the vector store, search and
citations all stay in the core, so no Fernet key ever crosses this boundary and
only one process writes the Chroma store.
"""

from __future__ import annotations

from pathlib import Path

from chunker import chunk_blocks
from models import ParsedDocument
from parsers.docx import parse_docx
from parsers.pdf import parse_pdf
from parsers.text import parse_text
from parsers.xlsx import parse_xlsx
from pydantic import BaseModel, Field

from declaw_plugin_sdk.declaration import BasePlugin, capability

# Leaves headroom under the host's 32 MiB frame cap for JSON overhead.
MAX_RESULT_CHARS = 24 * 1024 * 1024

_PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".xlsx": parse_xlsx,
    ".txt": parse_text,
    ".md": parse_text,
    ".markdown": parse_text,
}


class ParseArgs(BaseModel):
    """Arguments for ``parse``.

    ``path`` is absolute and has already been checked against the workspace
    boundary by the core before this plugin is ever called.
    """

    path: str = Field(description="Absolute path to the document to parse.")


class DocIntelPlugin(BasePlugin):
    name = "doc-intel"
    version = "0.1.0"

    @capability(
        name="parse",
        description_en="Parse a document into text chunks with source metadata.",
        description_fr="Analyse un document en fragments de texte avec metadonnees.",
        requires=["filesystem.read"],
        # Infrastructure for the core indexer. The model must never see this.
        exposed_to_model=False,
        produces_external_content=True,
        classification="read",
        timeout_s=300,
    )
    async def parse(self, args: ParseArgs) -> dict[str, object]:
        path = Path(args.path)
        if not path.is_file():
            raise FileNotFoundError(f"No such document: {path.name}")
        parser = _PARSERS.get(path.suffix.lower())
        if parser is None:
            supported = ", ".join(sorted(_PARSERS))
            raise ValueError(
                f"Unsupported file type {path.suffix!r}; doc-intel reads {supported}."
            )

        parsed: ParsedDocument = parser(path)
        chunks = chunk_blocks(parsed.blocks)

        # Truncate rather than blow the frame cap: a partly indexed document
        # the user is warned about beats a failed call they cannot act on.
        kept: list[dict[str, object]] = []
        total = 0
        truncated = False
        for chunk in chunks:
            total += len(chunk.text)
            if total > MAX_RESULT_CHARS:
                truncated = True
                break
            kept.append(
                {
                    "text": chunk.text,
                    "ordinal": chunk.ordinal,
                    "page": chunk.page,
                    "page_end": chunk.page_end,
                    "sheet": chunk.sheet,
                    "heading": chunk.heading,
                }
            )

        return {
            "doc_type": parsed.doc_type,
            "page_count": parsed.page_count,
            "truncated": truncated,
            "chunks": kept,
        }
