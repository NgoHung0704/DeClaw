"""Long-term semantic memory over ChromaDB (DCL-053).

Vector search by topic: texts are embedded locally (Ollama, DCL-050 seam) and
stored in the ``declaw_semantic`` collection; queries embed the same way and
return the top-k nearest memories.

Encryption boundary (DCL-051): when a ``Fernet`` is supplied (the production
path), the document *text* is encrypted before it reaches Chroma and decrypted
on the way out — persisted files never hold client plaintext. Metadata stays
plaintext by design so Chroma ``where`` filters keep working; callers must not
put document content into metadata (keys like ``source`` or ``topic`` are
labels, not payloads). The embedding vector is inherently unencrypted (Chroma
must compare it) — see the caveat in ``declaw/memory/crypto.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from chromadb.api.models.Collection import Collection
from cryptography.fernet import Fernet

from declaw.memory.crypto import decrypt_text, encrypt_text
from declaw.memory.embeddings import Embedder

# Chroma accepts these metadata value types.
MetadataValue = str | int | float | bool
Metadata = dict[str, MetadataValue]


@dataclass(frozen=True, slots=True)
class MemoryHit:
    """One search result, text already decrypted."""

    id: str
    text: str
    metadata: Metadata
    distance: float


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One stored memory, text already decrypted (export surface)."""

    id: str
    text: str
    metadata: Metadata


class SemanticMemory:
    """Topic-searchable long-term memory with at-rest encryption."""

    def __init__(
        self,
        collection: Collection,
        embedder: Embedder,
        *,
        fernet: Fernet | None = None,
    ) -> None:
        self._collection = collection
        self._embed = embedder
        self._fernet = fernet

    async def add(self, text: str, *, metadata: Metadata | None = None, id: str | None = None) -> str:
        """Embed + store one memory; returns its id."""
        if not text.strip():
            raise ValueError("Refusing to store an empty memory.")
        memory_id = id if id is not None else str(uuid.uuid4())
        [vector] = await self._embed([text])
        stored = encrypt_text(self._fernet, text) if self._fernet is not None else text
        # list is invariant, so re-type the single vector for chroma's signature.
        embeddings: list[Sequence[float] | Sequence[int]] = [vector]
        self._collection.add(
            ids=[memory_id],
            embeddings=embeddings,
            documents=[stored],
            metadatas=[metadata] if metadata else None,
        )
        return memory_id

    async def search(self, query: str, *, k: int = 5) -> list[MemoryHit]:
        """Return the ``k`` nearest memories to ``query`` (may be fewer)."""
        if self.count() == 0:
            return []
        [vector] = await self._embed([query])
        query_embeddings: list[Sequence[float] | Sequence[int]] = [vector]
        result = self._collection.query(
            query_embeddings=query_embeddings,
            n_results=min(k, self.count()),
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: list[MemoryHit] = []
        for i, memory_id in enumerate(ids):
            hits.append(
                MemoryHit(
                    id=memory_id,
                    text=self._reveal(documents[i]),
                    metadata=_narrow_metadata(metadatas[i]) if metadatas[i] else {},
                    distance=float(distances[i]),
                )
            )
        return hits

    def export_all(self) -> list[MemoryRecord]:
        """Every stored memory, decrypted — the GDPR-export surface (DCL-056)."""
        result = self._collection.get(include=["documents", "metadatas"])
        records: list[MemoryRecord] = []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        for i, memory_id in enumerate(result["ids"]):
            records.append(
                MemoryRecord(
                    id=memory_id,
                    text=self._reveal(documents[i]),
                    metadata=(
                        _narrow_metadata(metadatas[i])
                        if i < len(metadatas) and metadatas[i]
                        else {}
                    ),
                )
            )
        return records

    def wipe(self) -> int:
        """Delete every stored memory; returns how many were removed (DCL-057)."""
        ids = self._collection.get(include=[])["ids"]
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def count(self) -> int:
        return self._collection.count()

    def _reveal(self, stored: str) -> str:
        return decrypt_text(self._fernet, stored) if self._fernet is not None else stored


def _narrow_metadata(raw: Mapping[str, Any]) -> Metadata:
    """Keep only the scalar metadata values DeClaw writes (drop chroma extras)."""
    return {k: v for k, v in raw.items() if isinstance(v, str | int | float | bool)}
