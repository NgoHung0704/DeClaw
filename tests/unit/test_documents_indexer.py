"""Walk, hash, parse, embed, store — and skip what has not changed."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.documents.catalog import DocumentCatalog
from declaw.documents.indexer import DocumentIndexer, IndexProgress
from declaw.documents.store import DocumentStore
from declaw.memory.chroma import build_chroma_client, get_collection


async def _embed(texts: list[str]) -> list[list[float]]:
    return [[float(len(t)), 1.0] for t in texts]


class FakeParser:
    """Stands in for the doc-intel subprocess."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: set[str] = set()
        self.scanned: set[str] = set()

    async def __call__(self, path: str) -> dict[str, Any]:
        self.calls.append(path)
        name = Path(path).name
        if name in self.failures:
            raise RuntimeError("parser exploded")
        if name in self.scanned:
            return {"doc_type": "pdf-scanned", "page_count": 3, "truncated": False, "chunks": []}
        return {
            "doc_type": "text",
            "page_count": 1,
            "truncated": False,
            "chunks": [
                {
                    "text": f"content of {name}",
                    "ordinal": 0,
                    "page": 1,
                    "page_end": 1,
                    "sheet": None,
                    "heading": None,
                }
            ],
        }


@pytest.fixture
async def indexer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[DocumentIndexer, FakeParser, Path]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # resolve_in_workspace reads the workspace from settings, so the setting
    # must point at this test's temporary workspace.
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(workspace))
    from declaw.config import get_settings

    get_settings.cache_clear()

    # build_engine(path), not get_engine(): the latter is a memoized singleton
    # and every test would share one database.
    engine = build_engine(tmp_path / "test.db")
    await ensure_schema(engine)
    collection = get_collection(build_chroma_client(tmp_path / "chroma"), "documents")
    parser = FakeParser()
    try:
        yield (
            DocumentIndexer(
                parse=parser,
                store=DocumentStore(collection, _embed),
                catalog=DocumentCatalog(build_sessionmaker(engine)),
                workspace=workspace,
            ),
            parser,
            workspace,
        )
    finally:
        await engine.dispose()
        get_settings.cache_clear()


def _write(workspace: Path, name: str, body: str = "hello") -> Path:
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


async def test_indexes_every_supported_file(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, parser, workspace = indexer
    _write(workspace, "a.txt")
    _write(workspace, "b.md")
    report = await index.index()
    assert report.indexed == 2
    assert len(parser.calls) == 2


async def test_unsupported_extensions_are_ignored(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, parser, workspace = indexer
    _write(workspace, "a.txt")
    _write(workspace, "photo.png")
    report = await index.index()
    assert report.indexed == 1
    assert not any("photo" in c for c in parser.calls)


async def test_nested_folders_are_walked(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, _parser, workspace = indexer
    _write(workspace, "dossier/2024/contrat.txt")
    assert (await index.index()).indexed == 1


async def test_an_unchanged_file_is_skipped_on_the_second_pass(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    # DCL-108: proven by call count, not by timing.
    index, parser, workspace = indexer
    _write(workspace, "a.txt")
    await index.index()
    second = await index.index()
    assert second.indexed == 0
    assert second.skipped == 1
    assert len(parser.calls) == 1


async def test_a_changed_file_is_reindexed(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, parser, workspace = indexer
    _write(workspace, "a.txt", "first")
    await index.index()
    _write(workspace, "a.txt", "second, different content")
    report = await index.index()
    assert report.indexed == 1
    assert len(parser.calls) == 2


async def test_reindexing_replaces_chunks_rather_than_duplicating(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, _parser, workspace = indexer
    _write(workspace, "a.txt", "first")
    await index.index()
    _write(workspace, "a.txt", "second")
    await index.index()
    assert index.store.count() == 1


async def test_one_failing_document_does_not_abort_the_run(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, parser, workspace = indexer
    parser.failures.add("bad.txt")
    _write(workspace, "bad.txt")
    _write(workspace, "good.txt")
    report = await index.index()
    assert report.indexed == 1
    assert report.failed == 1
    assert any("bad.txt" in w for w in report.warnings)


async def test_a_failed_document_is_retried_next_run(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    # The catalog must not be updated for a document that never got stored.
    index, parser, workspace = indexer
    parser.failures.add("bad.txt")
    _write(workspace, "bad.txt")
    await index.index()
    parser.failures.clear()
    assert (await index.index()).indexed == 1


async def test_a_scanned_pdf_is_warned_about_not_silently_indexed(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, parser, workspace = indexer
    parser.scanned.add("scan.txt")
    _write(workspace, "scan.txt")
    report = await index.index()
    assert report.indexed == 0
    assert any("scan.txt" in w and "scanned" in w.lower() for w in report.warnings)


async def test_progress_is_reported_for_every_file(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, _parser, workspace = indexer
    for name in ("a.txt", "b.txt", "c.txt"):
        _write(workspace, name)
    seen: list[IndexProgress] = []
    await index.index(on_progress=seen.append)
    assert [p.done for p in seen] == [1, 2, 3]
    assert all(p.total == 3 for p in seen)


async def test_a_truncated_document_is_warned_about(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, parser, workspace = indexer

    async def truncating(path: str) -> dict[str, Any]:
        parser.calls.append(path)
        return {
            "doc_type": "pdf",
            "page_count": 900,
            "truncated": True,
            "chunks": [
                {
                    "text": "part",
                    "ordinal": 0,
                    "page": 1,
                    "page_end": 1,
                    "sheet": None,
                    "heading": None,
                }
            ],
        }

    index.parse = truncating
    _write(workspace, "huge.txt")
    report = await index.index()
    assert report.indexed == 1
    assert any("huge.txt" in w and "truncat" in w.lower() for w in report.warnings)


async def test_indexing_an_empty_workspace_reports_nothing(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, _parser, _workspace = indexer
    report = await index.index()
    assert (report.indexed, report.skipped, report.failed) == (0, 0, 0)
