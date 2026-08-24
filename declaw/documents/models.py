"""Shapes the document layer stores and returns."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """One retrievable piece of a document, with enough metadata to cite it."""

    text: str
    ordinal: int
    page: int | None = None
    page_end: int | None = None
    sheet: str | None = None
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One retrieval result, text already decrypted."""

    chunk_id: str
    doc_id: str
    path: str
    text: str
    ordinal: int
    distance: float
    page: int | None = None
    page_end: int | None = None
    sheet: str | None = None
    heading: str | None = None


def document_id(relative_path: str) -> str:
    """Stable id for a document, derived from its workspace-relative path.

    Hashed rather than used raw so the id is safe in any store or URL whatever
    the filename contains — accents, spaces, separators.
    """
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def chunk_id(doc_id: str, ordinal: int) -> str:
    """Stable id for one chunk within a document."""
    return f"{doc_id}:{ordinal}"
