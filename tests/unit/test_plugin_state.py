"""Plugin enable/disable/quarantine, persisted as readable JSON."""

from __future__ import annotations

import json
from pathlib import Path

from declaw.plugin_host.state import PluginStateStore


def test_an_unknown_plugin_defaults_to_enabled(tmp_path: Path) -> None:
    store = PluginStateStore(tmp_path / "plugin_state.json")
    record = store.record("echo-plugin")
    assert record.enabled is True
    assert record.quarantined is False


def test_disable_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "plugin_state.json"
    PluginStateStore(path).set_enabled("echo-plugin", False)
    assert PluginStateStore(path).record("echo-plugin").enabled is False


def test_quarantine_records_its_reason_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "plugin_state.json"
    PluginStateStore(path).quarantine("echo-plugin", "crashed 3 times in 5 minutes")
    reloaded = PluginStateStore(path).record("echo-plugin")
    assert reloaded.quarantined is True
    assert "3 times" in reloaded.quarantine_reason


def test_clearing_quarantine_also_clears_the_reason(tmp_path: Path) -> None:
    store = PluginStateStore(tmp_path / "s.json")
    store.quarantine("p", "boom")
    store.clear_quarantine("p")
    assert store.record("p").quarantined is False
    assert store.record("p").quarantine_reason == ""


def test_auto_grant_is_remembered_so_a_revoke_sticks(tmp_path: Path) -> None:
    # The whole point of tracking auto_granted: a permission offered once is
    # never offered again, which is what makes revoking it permanent.
    path = tmp_path / "s.json"
    store = PluginStateStore(path)
    assert store.has_auto_granted("p", "filesystem.read") is False
    store.note_auto_grant("p", "filesystem.read")
    assert PluginStateStore(path).has_auto_granted("p", "filesystem.read") is True


def test_the_file_is_readable_json_a_human_can_diff(tmp_path: Path) -> None:
    # Transparency is the reason this is not SQLite.
    path = tmp_path / "s.json"
    store = PluginStateStore(path)
    store.set_enabled("echo-plugin", False)
    store.note_version("echo-plugin", "1.0.0")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["echo-plugin"]["enabled"] is False
    assert raw["echo-plugin"]["last_version"] == "1.0.0"


def test_all_returns_every_known_plugin(tmp_path: Path) -> None:
    store = PluginStateStore(tmp_path / "s.json")
    store.set_enabled("a", False)
    store.quarantine("b", "x")
    assert set(store.all()) == {"a", "b"}


def test_a_corrupt_state_file_does_not_break_startup(tmp_path: Path) -> None:
    # Losing enable/disable preferences is annoying; refusing to start is worse.
    path = tmp_path / "s.json"
    path.write_text("{ not json", encoding="utf-8")
    assert PluginStateStore(path).record("p").enabled is True


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    # Writes go through a temp file and a replace; the temp must not survive.
    path = tmp_path / "s.json"
    PluginStateStore(path).set_enabled("p", False)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["s.json"]
