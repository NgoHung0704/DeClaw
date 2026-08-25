"""DCL-114 / DCL-115: move and rename go through the gate, and the index follows.

No new tool is built here. ``FilesystemMoveTool`` (DCL-023) already moves AND
renames, is WRITE-class so the registry already gates it, and is already wired
into chat — both tickets name DCL-023 as their dependency. What was missing was
proof that the *index* follows the file, which is what these tests add.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.documents.catalog import DocumentCatalog
from declaw.documents.indexer import DocumentIndexer
from declaw.documents.store import DocumentStore
from declaw.memory.chroma import build_chroma_client, get_collection
from declaw.tools.base import DeclawTool


async def _embed(texts: list[str]) -> list[list[float]]:
    return [[float(len(t)), 1.0] for t in texts]


async def _parse(path: str) -> dict[str, Any]:
    return {
        "doc_type": "text",
        "page_count": 1,
        "truncated": False,
        "chunks": [
            {
                "text": f"content of {Path(path).name}",
                "ordinal": 0,
                "page": 1,
                "page_end": 1,
                "sheet": None,
                "heading": None,
            }
        ],
    }


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    target = tmp_path / "workspace"
    target.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(target))
    from declaw.config import get_settings

    get_settings.cache_clear()
    yield target
    get_settings.cache_clear()


async def _indexer(tmp_path: Path, workspace: Path) -> DocumentIndexer:
    # build_engine(path), not get_engine(): the latter is a memoized singleton.
    engine = build_engine(tmp_path / "t.db")
    await ensure_schema(engine)
    collection = get_collection(build_chroma_client(tmp_path / "chroma"), "documents")
    return DocumentIndexer(
        parse=_parse,
        store=DocumentStore(collection, _embed),
        catalog=DocumentCatalog(build_sessionmaker(engine)),
        workspace=workspace,
    )


def _move_tool(decisions: list[bool], asked: list[str]) -> Any:
    """The real filesystem_move tool behind a scripted confirmation gate."""
    from declaw.tools.registry import default_registry

    async def approve(tool: DeclawTool[Any], args: dict[str, Any]) -> bool:
        asked.append(tool.name)
        return decisions.pop(0)

    tools = default_registry().langchain_tools("en", approve)
    return next(t for t in tools if t.name == "filesystem_move")


async def test_a_rename_requires_confirmation_and_happens(workspace: Path) -> None:
    # DCL-115: a rename is a move within the same folder.
    (workspace / "brouillon.txt").write_text("x", encoding="utf-8")
    asked: list[str] = []
    tool = _move_tool([True], asked)

    await tool.ainvoke({"source": "brouillon.txt", "destination": "contrat-final.txt"})

    assert asked == ["filesystem_move"]
    assert (workspace / "contrat-final.txt").is_file()
    assert not (workspace / "brouillon.txt").exists()


async def test_a_denied_move_changes_nothing(workspace: Path) -> None:
    # DCL-114's acceptance: no move without explicit confirmation.
    (workspace / "a.txt").write_text("x", encoding="utf-8")
    asked: list[str] = []
    tool = _move_tool([False], asked)

    result = await tool.ainvoke({"source": "a.txt", "destination": "dossier/a.txt"})

    assert asked == ["filesystem_move"]
    assert "denied" in result.lower()
    assert (workspace / "a.txt").is_file()
    assert not (workspace / "dossier").exists()


async def test_the_index_follows_a_rename(tmp_path: Path, workspace: Path) -> None:
    # The whole reason these tickets matter: the citation must track the file.
    (workspace / "contrat.txt").write_text("x", encoding="utf-8")
    index = await _indexer(tmp_path, workspace)
    await index.index()
    assert [h.path for h in await index.store.search("content", k=5)] == ["contrat.txt"]

    (workspace / "contrat.txt").rename(workspace / "contrat-2024.txt")
    await index.index()

    assert [h.path for h in await index.store.search("content", k=5)] == ["contrat-2024.txt"]


async def test_organize_then_reindex_leaves_one_entry_per_file(
    tmp_path: Path, workspace: Path
) -> None:
    from declaw.documents.actions import OrganizeFilesTool

    for name in ("f1.txt", "f2.txt"):
        (workspace / name).write_text("x", encoding="utf-8")
    index = await _indexer(tmp_path, workspace)
    await index.index()
    assert index.store.count() == 2

    await OrganizeFilesTool().run_validated(
        {
            "moves": [
                {"source": "f1.txt", "destination": "ACME/f1.txt"},
                {"source": "f2.txt", "destination": "ACME/f2.txt"},
            ]
        }
    )
    report = await index.index()

    assert report.removed == 2
    assert index.store.count() == 2
    assert sorted(await index.catalog.known_paths()) == ["ACME/f1.txt", "ACME/f2.txt"]
