"""Retrieval, and the sanitizing that guards the model's context.

Roadmap decision 4: chunks are classified at RETRIEVAL time, top-k only, not at
index time. Indexing every chunk through qwen2.5:7b at its measured 4.19s p50
would cost 10-20 minutes for one 100-page PDF and days for a real workspace.
The boundary that matters is content entering the model's context.

Two properties this module must keep, both covered by tests:

* every chunk returned has been classified;
* each distinct chunk is classified once — the verdict caches by SHA-256, so
  ten questions about one contract do not pay ten times.

The model stays qwen2.5:7b rather than the faster 3b. The false-positive
asymmetry is sharper here than for file reads: a wrongly blocked file read is
visible and announced, but a wrongly withheld CHUNK silently degrades an
answer. 7.5-9% FP would drop roughly one relevant chunk in eleven, invisibly.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from declaw.documents.models import SearchHit
from declaw.sanitizer.sanitizer import Sanitizer

DEFAULT_K = 5


class SearchableStore(Protocol):
    """The slice of :class:`DocumentStore` search depends on."""

    async def search(self, query: str, *, k: int = DEFAULT_K) -> list[SearchHit]: ...


@dataclass(slots=True)
class SearchOutcome:
    """What a query produced, including how much was withheld."""

    hits: list[SearchHit] = field(default_factory=list)
    withheld: int = 0


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChunkSanitizer:
    """Classifies retrieved chunks, once each, concurrently.

    Constructed once per session and injected, so tests can count exactly how
    many classifications happened. The cache holds verdicts keyed by chunk
    SHA-256 — never the text itself.
    """

    def __init__(self, sanitizer: Sanitizer | None) -> None:
        self._sanitizer = sanitizer
        self._verdicts: dict[str, str | None] = {}

    async def filter(self, hits: Sequence[SearchHit]) -> tuple[list[SearchHit], list[str]]:
        """Return (safe hits in order, quarantine ids of what was withheld)."""
        if self._sanitizer is None or not hits:
            return list(hits), []

        # Classify each distinct text once, even when it appears twice in the
        # same result set, and never re-classify what the cache already knows.
        distinct: dict[str, SearchHit] = {}
        for hit in hits:
            digest = _digest(hit.text)
            if digest not in self._verdicts:
                distinct.setdefault(digest, hit)

        if distinct:
            results = await asyncio.gather(
                *(
                    self._sanitizer.check(hit.text, source=f"document:{hit.path}")
                    for hit in distinct.values()
                )
            )
            for digest, result in zip(distinct, results, strict=True):
                self._verdicts[digest] = None if result.is_safe else result.quarantine_id

        safe: list[SearchHit] = []
        withheld: list[str] = []
        for hit in hits:
            quarantine_id = self._verdicts.get(_digest(hit.text))
            if quarantine_id is None:
                safe.append(hit)
            else:
                withheld.append(quarantine_id)
        return safe, withheld


async def search_documents(
    store: SearchableStore,
    chunk_sanitizer: ChunkSanitizer,
    query: str,
    *,
    k: int = DEFAULT_K,
) -> SearchOutcome:
    """Retrieve the top ``k`` chunks and return only those cleared to be read."""
    hits = await store.search(query, k=k)
    safe, withheld = await chunk_sanitizer.filter(hits)
    return SearchOutcome(hits=safe, withheld=len(withheld))
