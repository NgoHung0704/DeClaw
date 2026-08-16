"""ChromaDB persistent client + collection-per-purpose (DCL-050).

One local, persistent Chroma instance under ``settings.data_dir / "chroma"``.
Each memory purpose (semantic documents, user preferences later, ...) gets its
own collection, namespaced ``declaw_<purpose>``, so wipe/export can target one
kind of memory without touching the others.

Two deliberate choices:

* **Telemetry is OFF.** ChromaDB ships with anonymized product telemetry
  enabled by default — an outbound network call from a privacy-first app that
  promises "nothing leaves the device" (Principle #7). ``_chroma_settings``
  pins ``anonymized_telemetry=False`` and every client goes through it.
* **No embedding function is ever exercised.** Chroma's default embedding
  function downloads an ONNX model from the internet on first use. DeClaw
  always supplies embeddings explicitly (computed locally via Ollama's
  ``nomic-embed-text`` — see ``declaw/memory/embeddings.py``), so the default
  EF is never invoked and nothing is fetched.
"""

from __future__ import annotations

import re
from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from declaw.config import get_settings

CHROMA_DIR_NAME = "chroma"
COLLECTION_PREFIX = "declaw_"

# Purposes are code-defined identifiers, not user input; the pattern is a
# guardrail against accidents (spaces, path chars), not an attack surface.
_PURPOSE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,50}$")


def _chroma_settings() -> ChromaSettings:
    """Chroma client settings with telemetry pinned OFF (Principle #7)."""
    return ChromaSettings(anonymized_telemetry=False)


def build_chroma_client(persist_dir: Path | None = None) -> ClientAPI:
    """Return a persistent local Chroma client.

    Defaults to ``settings.data_dir / "chroma"``; tests pass an explicit
    ``persist_dir``. Data written through this client survives process
    restarts (the DCL-050 acceptance).
    """
    if persist_dir is None:
        persist_dir = get_settings().data_dir / CHROMA_DIR_NAME
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir), settings=_chroma_settings())


def get_collection(client: ClientAPI, purpose: str) -> Collection:
    """Get or create the collection backing ``purpose``.

    ``purpose`` must be a short lowercase identifier (e.g. ``"semantic"``,
    ``"preferences"``); the stored collection name is ``declaw_<purpose>``.
    """
    if not _PURPOSE_RE.match(purpose):
        raise ValueError(
            f"Invalid memory purpose {purpose!r}: must match {_PURPOSE_RE.pattern}."
        )
    return client.get_or_create_collection(
        name=f"{COLLECTION_PREFIX}{purpose}",
        metadata={"purpose": purpose},
    )
