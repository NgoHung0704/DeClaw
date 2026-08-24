"""Shapes the parsers produce and the chunker consumes.

Plain dataclasses, not pydantic models: these never cross the wire. The
capability's *arguments* are pydantic (the SDK requires it); its result is
built into a plain dict in main.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Block:
    """One contiguous piece of text a parser recovered, with its origin."""

    text: str
    page: int | None = None
    sheet: str | None = None
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Everything a parser recovered from one file."""

    doc_type: str
    page_count: int
    blocks: list[Block] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One retrievable unit, carrying enough metadata to cite it."""

    text: str
    ordinal: int
    page: int | None = None
    page_end: int | None = None
    sheet: str | None = None
    heading: str | None = None
