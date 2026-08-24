"""Wire the document stack once, so every entry point gets the same one.

``declaw index`` and ``declaw chat`` both need a Chroma collection, an embedder,
the Fernet key, a store and a catalog. Assembling that in two places is two
chances to differ — most dangerously, to forget the Fernet key in one path and
write plaintext chunks to disk without anyone noticing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from declaw.config import Settings
from declaw.db.engine import get_sessionmaker
from declaw.documents.catalog import DocumentCatalog
from declaw.documents.indexer import DocumentIndexer
from declaw.documents.search import ChunkSanitizer
from declaw.documents.store import DocumentStore
from declaw.memory.chroma import build_chroma_client, get_collection
from declaw.memory.crypto import get_or_create_fernet
from declaw.memory.embeddings import build_ollama_embedder
from declaw.plugin_host.host import PluginHost
from declaw.sanitizer.sanitizer import Sanitizer

DOC_INTEL_PLUGIN = "doc-intel"
COLLECTION_PURPOSE = "documents"


@dataclass(slots=True)
class DocumentStack:
    """Everything the document layer needs, assembled once."""

    store: DocumentStore
    catalog: DocumentCatalog
    indexer: DocumentIndexer
    chunk_sanitizer: ChunkSanitizer


def build_document_stack(
    settings: Settings,
    host: PluginHost,
    *,
    sanitizer: Sanitizer | None,
) -> DocumentStack:
    """Assemble the store, catalog, indexer and chunk sanitizer."""
    client = build_chroma_client(Path(settings.data_dir) / "chroma")
    collection = get_collection(client, COLLECTION_PURPOSE)
    store = DocumentStore(
        collection,
        build_ollama_embedder(),
        # Chunk text is encrypted at rest with the same vaulted key the rest of
        # memory uses. Vectors are not — Chroma must compare them.
        fernet=get_or_create_fernet(),
    )
    # get_sessionmaker() takes no arguments: it is a process-wide singleton
    # built over get_engine(). Passing an engine would be a TypeError.
    catalog = DocumentCatalog(get_sessionmaker())

    async def parse(path: str) -> dict[str, Any]:
        result = await host.call(DOC_INTEL_PLUGIN, "parse", {"path": path})
        return dict(result)

    indexer = DocumentIndexer(
        parse=parse,
        store=store,
        catalog=catalog,
        workspace=Path(settings.workspace_dir),
    )
    return DocumentStack(
        store=store,
        catalog=catalog,
        indexer=indexer,
        chunk_sanitizer=ChunkSanitizer(sanitizer),
    )
