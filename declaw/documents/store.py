"""The document vector store: batch add, top-k search, Fernet at rest.

A sibling of ``memory/semantic.py``, not a wrapper around it: that class embeds
one text per call, and DCL-106 needs a thousand chunks indexed in under two
minutes. The ``Embedder`` seam already takes a list, so batching is free here.

Chunk text is encrypted before it reaches Chroma. Metadata is NOT — Chroma
filters on it, and it holds labels (path, page, heading), never payloads. The
embedding vectors are also unencrypted, because Chroma has to compare them;
that residual exposure is recorded in the spec's limitations, and it is larger
here than it was for agent memories because these are the client's documents.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from chromadb.api.models.Collection import Collection
from cryptography.fernet import Fernet

from declaw.documents.models import DocumentChunk, SearchHit, chunk_id
from declaw.memory.crypto import decrypt_text, encrypt_text
from declaw.memory.embeddings import Embedder

DEFAULT_BATCH_SIZE = 32
DEFAULT_K = 5


def _metadata(doc_id: str, path: str, chunk: DocumentChunk) -> dict[str, Any]:
    """Build Chroma metadata, OMITTING absent optional fields.

    Chroma accepts only str/int/float/bool values; passing None raises. Every
    optional field is therefore left out rather than nulled.
    """
    data: dict[str, Any] = {"doc_id": doc_id, "path": path, "ordinal": chunk.ordinal}
    if chunk.page is not None:
        data["page"] = chunk.page
    if chunk.page_end is not None:
        data["page_end"] = chunk.page_end
    if chunk.sheet is not None:
        data["sheet"] = chunk.sheet
    if chunk.heading is not None:
        data["heading"] = chunk.heading
    return data


def _as_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _as_str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


class DocumentStore:
    """Chunks of indexed documents, searchable by meaning."""

    def __init__(
        self,
        collection: Collection,
        embedder: Embedder,
        *,
        fernet: Fernet | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._collection = collection
        self._embed = embedder
        self._fernet = fernet
        self._batch_size = batch_size

    async def add_document(
        self, doc_id: str, path: str, chunks: Sequence[DocumentChunk]
    ) -> int:
        """Embed and store every chunk of one document. Returns the count."""
        if not chunks:
            return 0
        for start in range(0, len(chunks), self._batch_size):
            batch = list(chunks[start : start + self._batch_size])
            vectors = await self._embed([c.text for c in batch])
            embeddings: Any = list(vectors)
            self._collection.add(
                ids=[chunk_id(doc_id, c.ordinal) for c in batch],
                embeddings=embeddings,
                documents=[self._encode(c.text) for c in batch],
                metadatas=[_metadata(doc_id, path, c) for c in batch],
            )
        return len(chunks)

    async def search(self, query: str, *, k: int = DEFAULT_K) -> list[SearchHit]:
        """Return the ``k`` closest chunks, text decrypted."""
        stored = self.count()
        if stored == 0:
            return []
        [vector] = await self._embed([query])
        embeddings: Any = [vector]
        result = self._collection.query(
            query_embeddings=embeddings,
            n_results=min(k, stored),
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids") or [[]]
        documents = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        distances = result.get("distances") or [[]]

        hits: list[SearchHit] = []
        for index, raw_id in enumerate(ids[0]):
            metadata: dict[str, Any] = dict(metadatas[0][index] or {})
            hits.append(
                SearchHit(
                    chunk_id=str(raw_id),
                    doc_id=str(metadata.get("doc_id", "")),
                    path=str(metadata.get("path", "")),
                    text=self._decode(str(documents[0][index])),
                    ordinal=int(metadata.get("ordinal", 0)),
                    distance=float(distances[0][index]),
                    page=_as_int(metadata.get("page")),
                    page_end=_as_int(metadata.get("page_end")),
                    sheet=_as_str(metadata.get("sheet")),
                    heading=_as_str(metadata.get("heading")),
                )
            )
        return hits

    def delete_document(self, doc_id: str) -> None:
        """Remove every chunk of one document, so re-indexing replaces it."""
        self._collection.delete(where={"doc_id": doc_id})

    def count(self) -> int:
        return int(self._collection.count())

    def _encode(self, text: str) -> str:
        return encrypt_text(self._fernet, text) if self._fernet is not None else text

    def _decode(self, stored: str) -> str:
        return decrypt_text(self._fernet, stored) if self._fernet is not None else stored
