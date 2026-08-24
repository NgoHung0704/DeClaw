"""The index command: reports, warns, and refuses cleanly when it cannot run."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from declaw.config import get_settings
from declaw.main import cli
from declaw.preflight import CheckResult

PLUGIN_SOURCE = Path(__file__).parent.parent.parent / "plugins" / "builtin" / "doc-intel"
runner = CliRunner()


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    target = tmp_path / "workspace"
    target.mkdir()
    shutil.copytree(PLUGIN_SOURCE, tmp_path / "plugins" / "doc-intel")
    monkeypatch.setenv("DECLAW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(target))
    monkeypatch.setenv("DECLAW_BUILTIN_PLUGINS_DIR", str(tmp_path / "plugins"))
    monkeypatch.setenv("DECLAW_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'declaw.db'}")

    # `declaw index` preflights the embedding model against a live Ollama.
    # Tests must never need one, so report it present and let the command
    # proceed to the logic actually under test.
    async def _embedding_present(settings: object) -> CheckResult:
        return CheckResult(
            name="ollama.embedding_model", passed=True, message="stubbed as pulled"
        )

    monkeypatch.setattr(
        "declaw.preflight.check_embedding_model_pulled", _embedding_present
    )

    get_settings.cache_clear()
    yield target
    get_settings.cache_clear()


def test_the_embedding_model_check_refuses_with_a_remedy(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    # The failure that actually happened on dev hardware: Ollama answers 404
    # for an unknown model, so without this the user saw a bare HTTP error.
    async def _missing(settings: object) -> CheckResult:
        return CheckResult(
            name="ollama.embedding_model",
            passed=False,
            message="Embedding model 'nomic-embed-text' not pulled.",
            remedy="Run `ollama pull nomic-embed-text`.",
        )

    monkeypatch.setattr("declaw.preflight.check_embedding_model_pulled", _missing)
    result = runner.invoke(cli, ["index"])
    assert result.exit_code != 0
    # Rich wraps at 80 columns under CliRunner, so collapse whitespace
    # rather than assert on a phrase that may be split mid-command.
    assert "ollama pull nomic-embed-text" in " ".join(result.stdout.split())


def test_indexing_an_empty_workspace_says_so(workspace: Path) -> None:
    result = runner.invoke(cli, ["index"])
    assert result.exit_code == 0
    assert "0" in result.stdout


def test_a_disabled_plugin_produces_an_actionable_refusal(
    tmp_path: Path, workspace: Path
) -> None:
    from declaw.plugin_host.state import PluginStateStore

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    PluginStateStore(tmp_path / "data" / "plugin_state.json").set_enabled("doc-intel", False)
    result = runner.invoke(cli, ["index"])
    assert result.exit_code != 0
    assert "doc-intel" in result.stdout
    assert "enable" in result.stdout.lower()


def test_a_folder_outside_the_workspace_is_refused(tmp_path: Path, workspace: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    result = runner.invoke(cli, ["index", str(outside)])
    assert result.exit_code != 0
    assert "workspace" in result.stdout.lower()
