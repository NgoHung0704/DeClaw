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
