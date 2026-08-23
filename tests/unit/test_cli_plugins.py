"""The plugins CLI group. Reads state and manifests; starts no subprocess."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from declaw.config import get_settings
from declaw.main import cli
from declaw.plugin_host.grants_helper import load_grants
from declaw.plugin_host.manifest import PluginPermission
from declaw.plugin_host.state import PluginStateStore

ECHO_SOURCE = Path(__file__).parent.parent / "fixtures" / "plugins" / "echo-plugin"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    shutil.copytree(ECHO_SOURCE, tmp_path / "plugins" / "echo-plugin")
    monkeypatch.setenv("DECLAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DECLAW_BUILTIN_PLUGINS_DIR", str(tmp_path / "plugins"))
    get_settings.cache_clear()
    yield
    # Never leave a tmp_path-bound Settings in the process-wide cache.
    get_settings.cache_clear()


def test_list_shows_the_plugin_its_version_and_its_permissions() -> None:
    result = runner.invoke(cli, ["plugins", "list"])
    assert result.exit_code == 0
    assert "echo-plugin" in result.stdout
    assert "1.0.0" in result.stdout
    assert "filesystem.read" in result.stdout


def test_disable_then_list_reports_it_disabled(tmp_path: Path) -> None:
    assert runner.invoke(cli, ["plugins", "disable", "echo-plugin"]).exit_code == 0
    assert PluginStateStore(tmp_path / "plugin_state.json").record("echo-plugin").enabled is False
    assert "disabled" in runner.invoke(cli, ["plugins", "list"]).stdout.lower()


def test_enable_clears_a_quarantine(tmp_path: Path) -> None:
    PluginStateStore(tmp_path / "plugin_state.json").quarantine("echo-plugin", "crashed")
    assert runner.invoke(cli, ["plugins", "enable", "echo-plugin"]).exit_code == 0
    record = PluginStateStore(tmp_path / "plugin_state.json").record("echo-plugin")
    assert record.quarantined is False and record.enabled is True


def test_revoke_removes_an_existing_grant(tmp_path: Path) -> None:
    # Grant first, so the test proves removal rather than an empty store.
    grants = load_grants(tmp_path)
    asyncio.run(grants.grant("echo-plugin", PluginPermission.FILESYSTEM_READ))
    assert PluginPermission.FILESYSTEM_READ in load_grants(tmp_path).granted("echo-plugin")

    result = runner.invoke(cli, ["plugins", "revoke", "echo-plugin", "filesystem.read"])
    assert result.exit_code == 0
    assert load_grants(tmp_path).granted("echo-plugin") == frozenset()


def test_revoking_an_unknown_permission_fails_with_a_readable_message() -> None:
    result = runner.invoke(cli, ["plugins", "revoke", "echo-plugin", "filesystem.obliterate"])
    assert result.exit_code != 0
    assert "filesystem.obliterate" in result.stdout


def test_an_unknown_plugin_name_is_rejected() -> None:
    result = runner.invoke(cli, ["plugins", "disable", "no-such-plugin"])
    assert result.exit_code != 0
    assert "no-such-plugin" in result.stdout
