"""Local embedding seam for vector memory (DCL-050, formalized in DCL-106).

``Embedder`` is the async seam the memory layer depends on: texts in, vectors
out. The production implementation calls the local Ollama daemon
(``nomic-embed-text``); tests inject a deterministic fake. Keeping the seam a
plain callable means ChromaDB's own embedding-function machinery (which
downloads models from the internet) is never engaged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from declaw.brain.ollama_client import OllamaClient
from declaw.config import get_settings

# texts -> one embedding vector per text, same order.
Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def build_ollama_embedder(
    *,
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 60.0,
) -> Embedder:
    """Build an :data:`Embedder` backed by the local Ollama daemon.

    ``model`` defaults to ``settings.embedding_model``. The generous timeout
    covers cold model loads on modest hardware.
    """
    client = OllamaClient(base_url, timeout=timeout)
    resolved_model = model if model is not None else get_settings().embedding_model

    async def embed(texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await client.embed(resolved_model, texts)

    return embed
