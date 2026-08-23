"""The security claims of the plugin boundary, proven against real processes.

These assert what the boundary DOES provide. What it does not provide is
documented in docs/phase-7-review.md — a malicious plugin runs with the user's
privileges and can remove the import hook. These tests do not pretend
otherwise.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from declaw.audit.events import PluginPermissionEvent
from declaw.audit.logger import InMemoryAuditLogger
from declaw.plugin_host.errors import PluginLoadError
from declaw.plugin_host.host import PluginHost
from declaw.plugin_host.loader import validate_described
from declaw.plugin_host.manifest import PluginPermission, load_manifest
from declaw.plugin_host.permissions import GrantStore, PermissionDeniedError
from declaw.plugin_host.process import PluginProcess
from declaw.plugin_host.state import PluginStateStore
from declaw_plugin_sdk.protocol import DescribeResult

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"


async def _probe() -> PluginProcess:
    directory = FIXTURES / "probe-plugin"
    process = PluginProcess(name="probe-plugin", plugin_dir=directory, entrypoint="main.py")
    await process.start()
    return process


async def test_a_plugin_cannot_import_declaw() -> None:
    process = await _probe()
    try:
        result = await process.request(
            "invoke", {"capability": "try_import", "args": {}}, timeout=30
        )
        assert result.startswith("blocked:")
        assert "may not import" in result
    finally:
        await process.shutdown()


async def test_a_plugin_can_still_import_its_own_sdk() -> None:
    # 'declaw_plugin_sdk' shares a prefix with 'declaw'; blocking it would
    # break every plugin.
    process = await _probe()
    try:
        result = await process.request(
            "invoke", {"capability": "import_sdk", "args": {}}, timeout=30
        )
        assert result.startswith("ok ")
    finally:
        await process.shutdown()


async def test_no_declaw_or_ollama_setting_is_visible_to_the_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECLAW_SANITIZER_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    process = await _probe()
    try:
        names = await process.request(
            "invoke", {"capability": "dump_env", "args": {}}, timeout=30
        )
        leaked = [n for n in names if n.startswith(("DECLAW_", "OLLAMA"))]
        assert leaked == ["DECLAW_PLUGIN_NAME"]
    finally:
        await process.shutdown()


async def test_a_capability_demanding_more_than_its_manifest_refuses_to_load() -> None:
    # DCL-097 at load time: the plugin never gets to serve a single call.
    directory = FIXTURES / "overreach-plugin"
    manifest = load_manifest(directory)
    process = PluginProcess(name="overreach-plugin", plugin_dir=directory, entrypoint="main.py")
    await process.start()
    try:
        described = DescribeResult.model_validate(await process.request("describe", timeout=30))
        with pytest.raises(PluginLoadError) as excinfo:
            validate_described(manifest, described)
        assert "filesystem.read" in str(excinfo.value)
        assert "never requested" in str(excinfo.value)
    finally:
        await process.shutdown()


async def test_the_overreaching_plugin_is_skipped_by_the_host(tmp_path: Path) -> None:
    # End to end: the host loads nothing and records why.
    plugins_dir = tmp_path / "plugins"
    shutil.copytree(FIXTURES / "overreach-plugin", plugins_dir / "overreach-plugin")
    host = PluginHost(
        search_dir=plugins_dir,
        state=PluginStateStore(tmp_path / "plugin_state.json"),
        grants=GrantStore(tmp_path / "plugin_grants.json"),
    )
    await host.start()
    try:
        assert host.loaded() == []
        assert any("never requested" in failure for failure in host.failures())
    finally:
        await host.stop()


async def test_an_ungranted_permission_is_denied_and_audited(tmp_path: Path) -> None:
    # echo-plugin's 'count' requires filesystem.read. Revoke it, and the call
    # must be refused with a PluginPermissionEvent recording the denial.
    plugins_dir = tmp_path / "plugins"
    shutil.copytree(FIXTURES / "echo-plugin", plugins_dir / "echo-plugin")
    audit = InMemoryAuditLogger()
    state = PluginStateStore(tmp_path / "plugin_state.json")
    # Pretend the permission was already offered once, so auto-grant skips it.
    state.note_auto_grant("echo-plugin", PluginPermission.FILESYSTEM_READ.value)

    host = PluginHost(
        search_dir=plugins_dir,
        state=state,
        grants=GrantStore(tmp_path / "plugin_grants.json"),
        audit=audit,
    )
    await host.start()
    try:
        with pytest.raises(PermissionDeniedError):
            await host.call("echo-plugin", "count", {"values": ["a"]})
        denials = [
            e for e in audit.events
            if isinstance(e, PluginPermissionEvent) and e.action == "denied_call"
        ]
        assert denials and denials[0].permission == "filesystem.read"
    finally:
        await host.stop()


async def test_a_capability_hidden_from_the_model_stays_hidden(tmp_path: Path) -> None:
    # exposed_to_model=False must mean the brain never sees the tool, however
    # the plugin is loaded.
    plugins_dir = tmp_path / "plugins"
    shutil.copytree(FIXTURES / "echo-plugin", plugins_dir / "echo-plugin")
    host = PluginHost(
        search_dir=plugins_dir,
        state=PluginStateStore(tmp_path / "plugin_state.json"),
        grants=GrantStore(tmp_path / "plugin_grants.json"),
    )
    await host.start()
    try:
        assert "echo_plugin_count" not in {tool.name for tool in host.model_tools()}
    finally:
        await host.stop()
