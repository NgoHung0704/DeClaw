"""Tests for the ChromaDB persistent client + embedder seam (DCL-050).

Acceptance: restart preserves vectors; collection-per-purpose. All embeddings
in these tests are explicit vectors — nothing here (or in production code)
ever invokes Chroma's default embedding function, which would download a
model from the internet.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from declaw.brain.ollama_client import OllamaClient
from declaw.memory.chroma import (
    _chroma_settings,
    build_chroma_client,
    get_collection,
)
from declaw.memory.embeddings import build_ollama_embedder

VEC_A = [1.0, 0.0, 0.0]
VEC_B = [0.0, 1.0, 0.0]


# --- Persistent client ----------------------------------------------------------


def test_restart_preserves_vectors(tmp_path: Path) -> None:
    client = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(client, "semantic")
    collection.add(ids=["doc-1"], embeddings=[VEC_A], documents=["hello world"])
    del collection, client

    reopened = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(reopened, "semantic")
    assert collection.count() == 1
    got = collection.get(ids=["doc-1"])
    assert got["documents"] == ["hello world"]


def test_query_returns_nearest_vector(tmp_path: Path) -> None:
    client = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(client, "semantic")
    collection.add(
        ids=["a", "b"],
        embeddings=[VEC_A, VEC_B],
        documents=["doc a", "doc b"],
    )
    result = collection.query(query_embeddings=[[0.9, 0.1, 0.0]], n_results=1)
    assert result["documents"] is not None
    assert result["documents"][0] == ["doc a"]


def test_collection_per_purpose(tmp_path: Path) -> None:
    client = build_chroma_client(tmp_path / "chroma")
    semantic = get_collection(client, "semantic")
    prefs = get_collection(client, "preferences")
    assert semantic.name == "declaw_semantic"
    assert prefs.name == "declaw_preferences"
    semantic.add(ids=["s1"], embeddings=[VEC_A], documents=["s"])
    assert prefs.count() == 0  # purposes are isolated


def test_invalid_purpose_rejected(tmp_path: Path) -> None:
    client = build_chroma_client(tmp_path / "chroma")
    for bad in ("Semantic", "has space", "", "1leading", "a/b"):
        with pytest.raises(ValueError):
            get_collection(client, bad)


def test_telemetry_is_disabled() -> None:
    # Principle #7: a privacy-first app must not phone home. Chroma's default
    # is telemetry ON; our settings factory must pin it OFF.
    assert _chroma_settings().anonymized_telemetry is False


# --- Ollama embedder seam --------------------------------------------------------


def _embed_transport(vectors: list[list[float]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        body = json.loads(request.content)
        assert isinstance(body["input"], list)
        return httpx.Response(200, json={"embeddings": vectors})

    return httpx.MockTransport(handler)


async def test_embedder_returns_one_vector_per_text() -> None:
    transport = _embed_transport([[0.1, 0.2], [0.3, 0.4]])
    client = OllamaClient("http://testserver", transport=transport)
    vectors = await client.embed("nomic-embed-text", ["first", "second"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


async def test_build_ollama_embedder_uses_settings_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_models.append(body["model"])
        return httpx.Response(200, json={"embeddings": [[1.0]]})

    monkeypatch.setenv("DECLAW_EMBEDDING_MODEL", "my-embedder")
    from declaw.config import get_settings

    get_settings.cache_clear()

    monkeypatch.setattr(
        "declaw.memory.embeddings.OllamaClient",
        lambda base_url, timeout: OllamaClient(
            "http://testserver", timeout=timeout, transport=httpx.MockTransport(handler)
        ),
    )
    embedder = build_ollama_embedder()
    result = await embedder(["text"])
    assert result == [[1.0]]
    assert seen_models == ["my-embedder"]


async def test_embedder_empty_input_short_circuits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP call expected for empty input")

    embedder = build_ollama_embedder(base_url="http://testserver")
    assert await embedder([]) == []


async def test_embed_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = OllamaClient("http://testserver", transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await client.embed("nomic-embed-text", ["text"])
