"""The host end to end: discover, spawn, validate, grant, call, stop.

Each test copies the echo fixture into its own tmp_path, so discovery never
sees crash-plugin or hang-plugin, and nothing is written into the source tree.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from declaw.audit.events import PluginLifecycleEvent, PluginPermissionEvent
from declaw.audit.logger import InMemoryAuditLogger
from declaw.plugin_host.errors import PluginUnavailableError
from declaw.plugin_host.host import PluginHost
from declaw.plugin_host.manifest import PluginPermission
from declaw.plugin_host.permissions import GrantStore, PermissionDeniedError
from declaw.plugin_host.state import PluginStateStore

ECHO_SOURCE = Path(__file__).parent.parent / "fixtures" / "plugins" / "echo-plugin"


@pytest.fixture
def plugins_dir(tmp_path: Path) -> Path:
    """A search directory holding only the echo fixture."""
    target = tmp_path / "plugins" / "echo-plugin"
    shutil.copytree(ECHO_SOURCE, target)
    return target.parent


def _host(
    tmp_path: Path, plugins_dir: Path, audit: InMemoryAuditLogger | None = None
) -> PluginHost:
    return PluginHost(
        search_dir=plugins_dir,
        state=PluginStateStore(tmp_path / "plugin_state.json"),
        grants=GrantStore(tmp_path / "plugin_grants.json"),
        audit=audit,
    )


async def test_start_loads_the_plugin_and_publishes_its_model_tools(
    tmp_path: Path, plugins_dir: Path
) -> None:
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        assert [p.manifest.name for p in host.loaded()] == ["echo-plugin"]
        names = {tool.name for tool in host.model_tools()}
        # 'count' is not exposed_to_model, so the brain must never see it.
        assert names == {"echo_plugin_echo", "echo_plugin_noisy"}
    finally:
        await host.stop()


async def test_a_call_reaches_the_plugin(tmp_path: Path, plugins_dir: Path) -> None:
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        result = await host.call("echo-plugin", "echo", {"message": "salut", "times": 2})
        assert result == "salut salut"
    finally:
        await host.stop()


async def test_manifest_permissions_are_auto_granted_and_audited(
    tmp_path: Path, plugins_dir: Path
) -> None:
    audit = InMemoryAuditLogger()
    host = _host(tmp_path, plugins_dir, audit)
    await host.start()
    try:
        grants = GrantStore(tmp_path / "plugin_grants.json")
        assert PluginPermission.FILESYSTEM_READ in grants.granted("echo-plugin")
        granted = [
            e for e in audit.events
            if isinstance(e, PluginPermissionEvent) and e.action == "granted"
        ]
        assert granted and granted[0].plugin == "echo-plugin"
    finally:
        await host.stop()


async def test_a_revoked_permission_is_not_auto_granted_again(
    tmp_path: Path, plugins_dir: Path
) -> None:
    # The whole point of tracking auto_granted in plugin_state.json.
    host = _host(tmp_path, plugins_dir)
    await host.start()
    await host.stop()

    grants = GrantStore(tmp_path / "plugin_grants.json")
    await grants.revoke("echo-plugin", PluginPermission.FILESYSTEM_READ)

    host2 = _host(tmp_path, plugins_dir)
    await host2.start()
    try:
        reloaded = GrantStore(tmp_path / "plugin_grants.json")
        assert PluginPermission.FILESYSTEM_READ not in reloaded.granted("echo-plugin")
        with pytest.raises(PermissionDeniedError):
            await host2.call("echo-plugin", "count", {"values": ["a"]})
    finally:
        await host2.stop()


async def test_a_granted_capability_can_be_called(tmp_path: Path, plugins_dir: Path) -> None:
    # The positive half of the permission check: 'count' requires
    # filesystem.read, which auto-grant provides.
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        assert await host.call("echo-plugin", "count", {"values": ["a", "b"]}) == {"count": 2}
    finally:
        await host.stop()


async def test_a_disabled_plugin_is_not_started(tmp_path: Path, plugins_dir: Path) -> None:
    PluginStateStore(tmp_path / "plugin_state.json").set_enabled("echo-plugin", False)
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        assert host.loaded() == []
        assert host.model_tools() == []
    finally:
        await host.stop()


async def test_a_quarantined_plugin_is_not_started(tmp_path: Path, plugins_dir: Path) -> None:
    PluginStateStore(tmp_path / "plugin_state.json").quarantine("echo-plugin", "crashed")
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        assert host.loaded() == []
    finally:
        await host.stop()


async def test_calling_an_unloaded_plugin_raises_unavailable(
    tmp_path: Path, plugins_dir: Path
) -> None:
    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        with pytest.raises(PluginUnavailableError):
            await host.call("not-here", "echo", {})
        with pytest.raises(PluginUnavailableError):
            await host.call("echo-plugin", "no-such-capability", {})
    finally:
        await host.stop()


async def test_lifecycle_events_are_audited(tmp_path: Path, plugins_dir: Path) -> None:
    audit = InMemoryAuditLogger()
    host = _host(tmp_path, plugins_dir, audit)
    await host.start()
    await host.stop()
    actions = {e.action for e in audit.events if isinstance(e, PluginLifecycleEvent)}
    assert "started" in actions and "stopped" in actions


async def test_one_broken_plugin_does_not_stop_the_others(
    tmp_path: Path, plugins_dir: Path
) -> None:
    # A plugin whose code raises on import must not abort startup for the rest.
    broken = plugins_dir / "broken-plugin"
    broken.mkdir()
    (broken / "plugin.yaml").write_text(
        "manifest_version: 1\nname: broken-plugin\nversion: 1.0.0\n"
        "description_en: Broken.\ndescription_fr: Cassee.\nentrypoint: main.py\n",
        encoding="utf-8",
    )
    (broken / "main.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    host = _host(tmp_path, plugins_dir)
    await host.start()
    try:
        assert [p.manifest.name for p in host.loaded()] == ["echo-plugin"]
        assert any("broken-plugin" in failure for failure in host.failures())
    finally:
        await host.stop()
