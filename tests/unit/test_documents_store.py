"""The document vector store: batching, encryption at rest, top-k."""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

from declaw.documents.models import DocumentChunk, chunk_id, document_id
from declaw.documents.store import DocumentStore
from declaw.memory.chroma import build_chroma_client, get_collection

Embedder = Callable[[list[str]], Coroutine[Any, Any, list[list[float]]]]


def _deterministic_embedder(calls: list[list[str]]) -> Embedder:
    """Embed by character histogram — deterministic, so top-k is exact."""

    async def embed(texts: list[str]) -> list[list[float]]:
        calls.append(list(texts))
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vectors.append([float(lowered.count(c)) for c in "abcdefghijklmnopqrstuvwxyz"])
        return vectors

    return embed


@pytest.fixture
def store(tmp_path: Path) -> tuple[DocumentStore, list[list[str]]]:
    client = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(client, "documents")
    calls: list[list[str]] = []
    return DocumentStore(collection, _deterministic_embedder(calls), batch_size=2), calls


def _chunks(*texts: str) -> list[DocumentChunk]:
    return [DocumentChunk(text=t, ordinal=i, page=i + 1) for i, t in enumerate(texts)]


async def test_add_returns_the_number_stored(
    store: tuple[DocumentStore, list[list[str]]],
) -> None:
    document, _ = store
    added = await document.add_document(document_id("a.pdf"), "a.pdf", _chunks("alpha", "beta"))
    assert added == 2
    assert document.count() == 2


async def test_embedding_is_batched(store: tuple[DocumentStore, list[list[str]]]) -> None:
    # DCL-106: one call per batch, not one per chunk.
    document, calls = store
    await document.add_document(document_id("a.pdf"), "a.pdf", _chunks("a", "b", "c", "d", "e"))
    assert [len(batch) for batch in calls] == [2, 2, 1]


async def test_search_returns_the_closest_chunk_first(
    store: tuple[DocumentStore, list[list[str]]],
) -> None:
    document, _ = store
    await document.add_document(
        document_id("a.pdf"), "a.pdf", _chunks("zzz zzz zzz", "banana banana", "qqq")
    )
    hits = await document.search("banana", k=2)
    assert hits[0].text == "banana banana"
    assert len(hits) == 2


async def test_hits_carry_citation_metadata(
    store: tuple[DocumentStore, list[list[str]]],
) -> None:
    document, _ = store
    chunks = [DocumentChunk(text="clause", ordinal=0, page=3, page_end=4, heading="Article 3")]
    await document.add_document(document_id("c.pdf"), "c.pdf", chunks)
    (hit,) = await document.search("clause", k=1)
    assert hit.path == "c.pdf"
    assert hit.page == 3 and hit.page_end == 4
    assert hit.heading == "Article 3"
    assert hit.sheet is None
    assert hit.ordinal == 0


async def test_optional_metadata_is_omitted_not_none(
    store: tuple[DocumentStore, list[list[str]]],
) -> None:
    # Chroma rejects None metadata values outright; this must not raise.
    document, _ = store
    chunks = [DocumentChunk(text="plain", ordinal=0)]
    await document.add_document(document_id("n.txt"), "n.txt", chunks)
    (hit,) = await document.search("plain", k=1)
    assert hit.page is None and hit.sheet is None and hit.heading is None


async def test_text_is_encrypted_on_disk(tmp_path: Path) -> None:
    client = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(client, "documents")
    calls: list[list[str]] = []
    document = DocumentStore(
        collection, _deterministic_embedder(calls), fernet=Fernet(Fernet.generate_key())
    )
    secret = "IBAN FR76 3000 4000 0512 3456 7890 143"
    await document.add_document(
        document_id("s.txt"), "s.txt", [DocumentChunk(text=secret, ordinal=0)]
    )

    # Byte-scan every persisted file: the plaintext must appear nowhere.
    for path in (tmp_path / "chroma").rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), path

    (hit,) = await document.search(secret, k=1)
    assert hit.text == secret  # decrypted on the way out


async def test_delete_removes_only_that_document(
    store: tuple[DocumentStore, list[list[str]]],
) -> None:
    document, _ = store
    await document.add_document(document_id("a.txt"), "a.txt", _chunks("alpha"))
    await document.add_document(document_id("b.txt"), "b.txt", _chunks("beta"))
    document.delete_document(document_id("a.txt"))
    assert document.count() == 1
    assert (await document.search("beta", k=1))[0].path == "b.txt"


async def test_reindexing_replaces_rather_than_duplicates(
    store: tuple[DocumentStore, list[list[str]]],
) -> None:
    document, _ = store
    doc = document_id("a.txt")
    await document.add_document(doc, "a.txt", _chunks("first version"))
    document.delete_document(doc)
    await document.add_document(doc, "a.txt", _chunks("second version"))
    assert document.count() == 1


async def test_searching_an_empty_store_returns_nothing(
    store: tuple[DocumentStore, list[list[str]]],
) -> None:
    document, _ = store
    assert await document.search("anything", k=5) == []


async def test_adding_no_chunks_is_a_no_op(
    store: tuple[DocumentStore, list[list[str]]],
) -> None:
    document, calls = store
    assert await document.add_document(document_id("e.txt"), "e.txt", []) == 0
    assert calls == []


def test_ids_are_stable_and_scoped() -> None:
    assert document_id("a/b.pdf") == document_id("a/b.pdf")
    assert document_id("a/b.pdf") != document_id("a/c.pdf")
    assert chunk_id("abc", 3) == "abc:3"
    # The id must be filesystem- and JSON-safe whatever the path contains.
    assert json.dumps(document_id("dossier/contrat été.pdf"))
