"""The file→hash index that makes re-indexing cheap."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.documents.catalog import DocumentCatalog, file_sha256


@pytest.fixture
async def catalog(tmp_path: Path) -> AsyncIterator[DocumentCatalog]:
    # build_engine(path), not get_engine(): the latter is a process-wide
    # memoized singleton, so every test would share one database and leak rows
    # into the next. This mirrors how tests/unit/test_db.py isolates.
    engine = build_engine(tmp_path / "test.db")
    await ensure_schema(engine)
    try:
        yield DocumentCatalog(build_sessionmaker(engine))
    finally:
        await engine.dispose()


def test_file_sha256_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    first.write_text("contenu", encoding="utf-8")
    second = tmp_path / "b.txt"
    second.write_text("contenu", encoding="utf-8")
    third = tmp_path / "c.txt"
    third.write_text("autre", encoding="utf-8")
    assert file_sha256(first) == file_sha256(second)
    assert file_sha256(first) != file_sha256(third)


def test_file_sha256_handles_a_large_file_without_loading_it_whole(tmp_path: Path) -> None:
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (5 * 1024 * 1024))
    assert len(file_sha256(big)) == 64


async def test_an_unknown_file_needs_indexing(catalog: DocumentCatalog) -> None:
    assert await catalog.needs_index("contrat.pdf", "abc123") is True


async def test_a_recorded_file_with_the_same_hash_is_skipped(catalog: DocumentCatalog) -> None:
    await catalog.record(
        relative_path="contrat.pdf",
        sha256="abc123",
        size_bytes=100,
        mtime=datetime.now(timezone.utc),
        doc_type="pdf",
        chunk_count=4,
    )
    assert await catalog.needs_index("contrat.pdf", "abc123") is False


async def test_a_changed_hash_needs_reindexing(catalog: DocumentCatalog) -> None:
    await catalog.record(
        relative_path="contrat.pdf",
        sha256="old",
        size_bytes=100,
        mtime=datetime.now(timezone.utc),
        doc_type="pdf",
        chunk_count=4,
    )
    assert await catalog.needs_index("contrat.pdf", "new") is True


async def test_recording_the_same_path_twice_updates_rather_than_duplicates(
    catalog: DocumentCatalog,
) -> None:
    for sha in ("one", "two"):
        await catalog.record(
            relative_path="c.pdf",
            sha256=sha,
            size_bytes=1,
            mtime=datetime.now(timezone.utc),
            doc_type="pdf",
            chunk_count=1,
        )
    assert await catalog.known_paths() == ["c.pdf"]
    assert await catalog.needs_index("c.pdf", "two") is False


async def test_forget_removes_the_entry(catalog: DocumentCatalog) -> None:
    await catalog.record(
        relative_path="c.pdf",
        sha256="x",
        size_bytes=1,
        mtime=datetime.now(timezone.utc),
        doc_type="pdf",
        chunk_count=1,
    )
    await catalog.forget("c.pdf")
    assert await catalog.known_paths() == []
    assert await catalog.needs_index("c.pdf", "x") is True


async def test_known_paths_is_sorted(catalog: DocumentCatalog) -> None:
    for name in ("z.pdf", "a.pdf", "m.pdf"):
        await catalog.record(
            relative_path=name,
            sha256="x",
            size_bytes=1,
            mtime=datetime.now(timezone.utc),
            doc_type="pdf",
            chunk_count=1,
        )
    assert await catalog.known_paths() == ["a.pdf", "m.pdf", "z.pdf"]


# --- Failure markers (DCL-128): visible, cleared by recovery ---------------


async def test_record_failure_upserts_the_marker(catalog: DocumentCatalog) -> None:
    await catalog.record_failure(relative_path="bad.pdf", error="parse error", attempts=3)
    await catalog.record_failure(relative_path="bad.pdf", error="second error", attempts=4)
    assert await catalog.failures() == [("bad.pdf", "second error", 4)]


async def test_clear_failure_removes_the_marker(catalog: DocumentCatalog) -> None:
    await catalog.record_failure(relative_path="bad.pdf", error="parse error", attempts=3)
    await catalog.clear_failure("bad.pdf")
    await catalog.clear_failure("never-had-one.pdf")  # clearing the absent is a no-op
    assert await catalog.failures() == []


async def test_a_successful_record_clears_the_failure_marker(catalog: DocumentCatalog) -> None:
    # The recovery flow a user actually runs: a failed path that indexes fine
    # on the next run must not stay marked as failed in the catalog.
    await catalog.record_failure(relative_path="bad.pdf", error="parse error", attempts=3)
    await catalog.record(
        relative_path="bad.pdf",
        sha256="new",
        size_bytes=10,
        mtime=datetime.now(timezone.utc),
        doc_type="pdf",
        chunk_count=2,
    )
    assert await catalog.failures() == []


async def test_forget_clears_the_failure_marker(catalog: DocumentCatalog) -> None:
    # A deleted file takes its failure marker with it.
    await catalog.record_failure(relative_path="bad.pdf", error="parse error", attempts=3)
    await catalog.forget("bad.pdf")
    assert await catalog.failures() == []
