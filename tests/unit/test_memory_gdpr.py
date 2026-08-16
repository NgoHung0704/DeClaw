"""Tests for GDPR memory export + wipe (DCL-056 / DCL-057).

Acceptances: export writes a complete archive; after wipe retrieval is empty
and the audit trail keeps an anonymized (counts-only) record.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

from declaw.audit.events import MemoryExportEvent, MemoryWipeEvent
from declaw.audit.logger import InMemoryAuditLogger
from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.memory.chroma import build_chroma_client, get_collection
from declaw.memory.episodic import EpisodicMemory
from declaw.memory.gdpr import (
    MEMORY_EXPORT_SCHEMA_VERSION,
    export_memory,
    wipe_memory,
)
from declaw.memory.semantic import SemanticMemory
from tests.unit.test_memory_semantic import fake_embedder


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(tmp_path / "declaw.db")
    await ensure_schema(eng)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def semantic(tmp_path: Path) -> SemanticMemory:
    collection = get_collection(build_chroma_client(tmp_path / "chroma"), "semantic")
    return SemanticMemory(collection, fake_embedder, fernet=Fernet(Fernet.generate_key()))


@pytest.fixture
def episodic(engine: AsyncEngine) -> EpisodicMemory:
    return EpisodicMemory(build_sessionmaker(engine))


async def test_export_writes_complete_readable_archive(
    tmp_path: Path, semantic: SemanticMemory, episodic: EpisodicMemory
) -> None:
    await semantic.add("The contract expires in 2027.", metadata={"source": "contract.pdf"})
    await episodic.record(summary="Summarized contract.pdf", tags=["contracts"])

    destination = tmp_path / "exports" / "archive.json"
    audit = InMemoryAuditLogger()
    written = await export_memory(
        destination, semantic=semantic, episodic=episodic, audit=audit
    )

    archive = json.loads(written.read_text(encoding="utf-8"))
    assert archive["declaw_memory_export"]["schema_version"] == MEMORY_EXPORT_SCHEMA_VERSION
    assert archive["declaw_memory_export"]["exported_at"]

    # Portability means readable: the semantic text is DECRYPTED in the archive.
    assert archive["semantic"][0]["text"] == "The contract expires in 2027."
    assert archive["semantic"][0]["metadata"] == {"source": "contract.pdf"}
    assert archive["episodes"][0]["summary"] == "Summarized contract.pdf"
    assert archive["episodes"][0]["tags"] == ["contracts"]

    [event] = audit.events
    assert isinstance(event, MemoryExportEvent)
    assert event.semantic_count == 1
    assert event.episode_count == 1
    assert event.destination == str(destination)


async def test_export_of_empty_memory_is_valid(
    tmp_path: Path, semantic: SemanticMemory, episodic: EpisodicMemory
) -> None:
    written = await export_memory(
        tmp_path / "empty.json", semantic=semantic, episodic=episodic
    )
    archive = json.loads(written.read_text(encoding="utf-8"))
    assert archive["semantic"] == []
    assert archive["episodes"] == []


async def test_wipe_empties_both_stores_and_leaves_anonymized_audit(
    semantic: SemanticMemory, episodic: EpisodicMemory
) -> None:
    await semantic.add("secret contract fact")
    await semantic.add("secret invoice fact")
    await episodic.record(summary="did things")

    audit = InMemoryAuditLogger()
    report = await wipe_memory(semantic=semantic, episodic=episodic, audit=audit)

    assert report.semantic_removed == 2
    assert report.episodes_removed == 1

    # The acceptance: after wipe, retrieval is empty.
    assert await semantic.search("contract") == []
    assert await episodic.export_all() == []

    # Audit keeps counts only — the event type has no content-bearing fields.
    [event] = audit.events
    assert isinstance(event, MemoryWipeEvent)
    assert event.semantic_removed == 2
    assert event.episodes_removed == 1
    field_names = set(type(event).model_fields)
    assert field_names.isdisjoint({"content", "text", "summary", "ids"})


async def test_wipe_of_empty_memory_reports_zero(
    semantic: SemanticMemory, episodic: EpisodicMemory
) -> None:
    report = await wipe_memory(semantic=semantic, episodic=episodic)
    assert report.semantic_removed == 0
    assert report.episodes_removed == 0
