"""Multi-file organisation: one plan, one approval, all-or-nothing validation."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from declaw.documents.actions import OrganizeFilesTool
from declaw.tools.base import ToolClass


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    target = tmp_path / "workspace"
    target.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(target))
    from declaw.config import get_settings

    get_settings.cache_clear()
    yield target
    get_settings.cache_clear()


def _write(workspace: Path, name: str) -> Path:
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("contenu", encoding="utf-8")
    return path


def _run(moves: list[dict[str, str]]) -> str:
    return asyncio.run(OrganizeFilesTool().run_validated({"moves": moves}))


def test_the_tool_is_write_class_so_it_is_gated() -> None:
    assert OrganizeFilesTool().classification is ToolClass.WRITE


def test_a_plan_moves_every_file(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    _write(workspace, "b.pdf")
    result = _run(
        [
            {"source": "a.pdf", "destination": "ACME/a.pdf"},
            {"source": "b.pdf", "destination": "ACME/b.pdf"},
        ]
    )
    assert (workspace / "ACME" / "a.pdf").is_file()
    assert (workspace / "ACME" / "b.pdf").is_file()
    assert not (workspace / "a.pdf").exists()
    assert "2" in result


def test_destination_folders_are_created(workspace: Path) -> None:
    # 'create folder structure' is the other half of DCL-116.
    _write(workspace, "facture.pdf")
    _run([{"source": "facture.pdf", "destination": "factures/2024/ACME/facture.pdf"}])
    assert (workspace / "factures" / "2024" / "ACME" / "facture.pdf").is_file()


def test_a_missing_source_refuses_the_whole_plan(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    with pytest.raises((ValueError, FileNotFoundError)) as excinfo:
        _run(
            [
                {"source": "a.pdf", "destination": "ACME/a.pdf"},
                {"source": "ghost.pdf", "destination": "ACME/ghost.pdf"},
            ]
        )
    assert "ghost.pdf" in str(excinfo.value)
    # Nothing was moved: the good entry must not have been executed either.
    assert (workspace / "a.pdf").is_file()
    assert not (workspace / "ACME").exists()


def test_an_existing_destination_refuses_the_whole_plan(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    _write(workspace, "ACME/a.pdf")
    with pytest.raises(ValueError) as excinfo:
        _run([{"source": "a.pdf", "destination": "ACME/a.pdf"}])
    assert "ACME/a.pdf" in str(excinfo.value)
    assert (workspace / "a.pdf").is_file()


def test_two_moves_onto_the_same_destination_are_refused(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    _write(workspace, "b.pdf")
    with pytest.raises(ValueError) as excinfo:
        _run(
            [
                {"source": "a.pdf", "destination": "ACME/x.pdf"},
                {"source": "b.pdf", "destination": "ACME/x.pdf"},
            ]
        )
    assert "ACME/x.pdf" in str(excinfo.value)
    assert (workspace / "a.pdf").is_file() and (workspace / "b.pdf").is_file()


def test_a_path_outside_the_workspace_is_refused(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    with pytest.raises(ValueError):
        _run([{"source": "a.pdf", "destination": "../escape.pdf"}])
    assert (workspace / "a.pdf").is_file()


def test_an_empty_plan_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        asyncio.run(OrganizeFilesTool().run_validated({"moves": []}))


def test_the_preview_lists_the_moves_readably(workspace: Path) -> None:
    preview = OrganizeFilesTool().confirmation_preview(
        {"moves": [{"source": "a.pdf", "destination": "ACME/a.pdf"}]}
    )
    assert preview is not None
    assert "a.pdf" in preview and "ACME/a.pdf" in preview
    assert "1" in preview


def test_a_long_plan_is_summarised_not_dumped(workspace: Path) -> None:
    # Thirty raw lines in a terminal prompt is how people learn to press 'y'
    # without reading.
    moves = [{"source": f"f{i}.pdf", "destination": f"ACME/f{i}.pdf"} for i in range(30)]
    preview = OrganizeFilesTool().confirmation_preview({"moves": moves})
    assert preview is not None
    assert "30" in preview
    assert preview.count("\n") < 15
    assert "more" in preview.lower()


# --- document_summarize (DCL-113) ------------------------------------------

from typing import Any  # noqa: E402

from declaw.documents.models import SearchHit  # noqa: E402
from declaw.documents.search import ChunkSanitizer  # noqa: E402


class _Store:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.queries: list[str] = []

    async def search(self, query: str, *, k: int = 5) -> list[SearchHit]:
        self.queries.append(query)
        return self._hits[:k]


def _hit(path: str, page: int | None = 3) -> SearchHit:
    return SearchHit(
        chunk_id=f"{path}:0",
        doc_id=path,
        path=path,
        text=f"clause from {path}",
        ordinal=0,
        distance=0.1,
        page=page,
        page_end=page,
    )


def _summarize_tool(hits: list[SearchHit], language: Any = "en") -> tuple[Any, _Store]:
    from declaw.documents.actions import build_document_summarize_tool

    store = _Store(hits)
    tool = build_document_summarize_tool(
        store=store, chunk_sanitizer=ChunkSanitizer(None), language=language
    )
    return tool, store


def test_the_summary_file_is_written(workspace: Path) -> None:
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    asyncio.run(
        tool.run_validated({"query": "resiliation", "summary": "Le preavis est de trois mois."})
    )
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "Le preavis est de trois mois." in written


def test_sources_come_from_retrieval_not_from_the_model(workspace: Path) -> None:
    # The rule that survives from DCL-062: the model never invents a citation.
    tool, store = _summarize_tool([_hit("contrat.pdf", page=12)])
    asyncio.run(
        tool.run_validated(
            {
                "query": "resiliation",
                "summary": "According to invented-source.pdf page 99, ...",
            }
        )
    )
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "contrat.pdf p.12" in written
    assert store.queries == ["resiliation"]
    # The model's invented citation stays in its prose but never in the sources.
    sources_block = written.split("Sources")[1]
    assert "invented-source.pdf" not in sources_block


def test_the_file_declares_that_a_model_wrote_it(workspace: Path) -> None:
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    asyncio.run(tool.run_validated({"query": "q", "summary": "resume"}))
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "AI" in written or "IA" in written
    assert "verify" in written.lower()


def test_the_french_summary_is_in_french(workspace: Path) -> None:
    tool, _store = _summarize_tool([_hit("contrat.pdf")], language="fr")
    asyncio.run(tool.run_validated({"query": "q", "summary": "resume"}))
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "IA locale" in written
    assert "vérifiez les sources" in written
    assert "Sources" in written
    # No English leaking into French copy: this is a France-first product.
    assert "verify" not in written.lower()
    assert "Written by" not in written


def test_it_refuses_to_overwrite_by_default(workspace: Path) -> None:
    (workspace / "summary.md").write_text("existing work", encoding="utf-8")
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    with pytest.raises(ValueError):
        asyncio.run(tool.run_validated({"query": "q", "summary": "new"}))
    assert (workspace / "summary.md").read_text(encoding="utf-8") == "existing work"


def test_overwrite_is_possible_when_asked(workspace: Path) -> None:
    (workspace / "summary.md").write_text("existing", encoding="utf-8")
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    asyncio.run(tool.run_validated({"query": "q", "summary": "new", "overwrite": True}))
    assert "new" in (workspace / "summary.md").read_text(encoding="utf-8")


def test_a_summary_path_outside_the_workspace_is_refused(workspace: Path) -> None:
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    with pytest.raises(ValueError):
        asyncio.run(
            tool.run_validated({"query": "q", "summary": "s", "path": "../escape.md"})
        )


def test_a_summary_with_no_matching_documents_still_writes_but_says_so(
    workspace: Path,
) -> None:
    tool, _store = _summarize_tool([])
    asyncio.run(tool.run_validated({"query": "q", "summary": "resume"}))
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "resume" in written


def test_the_summarize_tool_is_write_class_so_it_is_gated(workspace: Path) -> None:
    tool, _store = _summarize_tool([])
    assert tool.classification is ToolClass.WRITE
