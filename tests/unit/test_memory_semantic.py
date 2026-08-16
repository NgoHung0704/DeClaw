"""Tests for long-term semantic memory (DCL-053).

A deterministic fake embedder maps texts onto fixed unit vectors, so
"top-k retrieves expected docs" (the acceptance) is exact, not statistical.
No Ollama, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from declaw.memory.chroma import build_chroma_client, get_collection
from declaw.memory.semantic import SemanticMemory

# Deterministic "topic space": each known keyword owns an axis.
_AXES = {"contract": 0, "invoice": 1, "diagnosis": 2}


async def fake_embedder(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.01, 0.01, 0.01]  # small noise so unknown text is valid
        for keyword, axis in _AXES.items():
            if keyword in text.lower():
                vector[axis] = 1.0
        vectors.append(vector)
    return vectors


@pytest.fixture
def memory(tmp_path: Path) -> SemanticMemory:
    client = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(client, "semantic")
    return SemanticMemory(collection, fake_embedder, fernet=Fernet(Fernet.generate_key()))


async def test_top_k_retrieves_expected_docs(memory: SemanticMemory) -> None:
    await memory.add("The contract with Acme was signed in March.")
    await memory.add("Invoice 2026-042 is overdue by two weeks.")
    await memory.add("The diagnosis was confirmed by the specialist.")

    hits = await memory.search("what did the contract say?", k=1)
    assert len(hits) == 1
    assert "contract with Acme" in hits[0].text

    hits = await memory.search("any unpaid invoice?", k=2)
    assert "Invoice 2026-042" in hits[0].text  # nearest first


async def test_search_returns_at_most_k_and_at_most_count(memory: SemanticMemory) -> None:
    await memory.add("contract A")
    await memory.add("contract B")
    hits = await memory.search("contract", k=10)
    assert len(hits) == 2


async def test_search_on_empty_memory_is_empty(memory: SemanticMemory) -> None:
    assert await memory.search("anything") == []


async def test_metadata_roundtrip(memory: SemanticMemory) -> None:
    await memory.add(
        "The contract expires 2027-01-01.",
        metadata={"source": "contract.pdf", "page": 3},
    )
    [hit] = await memory.search("contract", k=1)
    assert hit.metadata == {"source": "contract.pdf", "page": 3}


async def test_stored_documents_are_encrypted_but_hits_are_plaintext(
    tmp_path: Path,
) -> None:
    client = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(client, "semantic")
    memory = SemanticMemory(collection, fake_embedder, fernet=Fernet(Fernet.generate_key()))

    text = "The contract contains SECRET-MARKER-99."
    memory_id = await memory.add(text)

    raw = collection.get(ids=[memory_id])
    assert raw["documents"] is not None
    assert "SECRET-MARKER-99" not in raw["documents"][0]  # ciphertext at rest

    [hit] = await memory.search("contract", k=1)
    assert hit.text == text  # decrypted on the way out


async def test_plaintext_mode_without_fernet(tmp_path: Path) -> None:
    client = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(client, "semantic")
    memory = SemanticMemory(collection, fake_embedder)  # no fernet
    memory_id = await memory.add("contract text")
    raw = collection.get(ids=[memory_id])
    assert raw["documents"] is not None
    assert raw["documents"][0] == "contract text"


async def test_export_all_decrypts_everything(memory: SemanticMemory) -> None:
    await memory.add("contract one", metadata={"n": 1})
    await memory.add("invoice two", metadata={"n": 2})
    records = memory.export_all()
    assert {r.text for r in records} == {"contract one", "invoice two"}
    assert all(isinstance(r.metadata, dict) for r in records)


async def test_wipe_empties_memory(memory: SemanticMemory) -> None:
    await memory.add("contract one")
    await memory.add("invoice two")
    removed = memory.wipe()
    assert removed == 2
    assert memory.count() == 0
    assert await memory.search("contract") == []


async def test_empty_text_rejected(memory: SemanticMemory) -> None:
    with pytest.raises(ValueError):
        await memory.add("   ")
