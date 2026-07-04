"""Tests for permission enforcement + audited grants (DCL-081 / DCL-084).

Acceptances: denied call returns structured error + audit event; all
grant/deny/revoke transitions are recorded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from declaw.audit.events import PluginPermissionEvent
from declaw.audit.logger import InMemoryAuditLogger
from declaw.plugin_host.manifest import PluginPermission, parse_manifest
from declaw.plugin_host.permissions import (
    GrantStore,
    PermissionDeniedError,
    PermissionEnforcer,
)


def _manifest() -> object:
    return parse_manifest(
        {
            "name": "doc-intel",
            "version": "0.1.0",
            "description_en": "Docs.",
            "description_fr": "Documents.",
            "entrypoint": "main.py",
            "permissions": {"requested": ["filesystem.read", "network"]},
        }
    )


@pytest.fixture
def grants(tmp_path: Path) -> GrantStore:
    return GrantStore(tmp_path / "plugin_grants.json")


async def test_granted_permission_passes(grants: GrantStore) -> None:
    await grants.grant("doc-intel", PluginPermission.FILESYSTEM_READ)
    enforcer = PermissionEnforcer(_manifest(), grants)  # type: ignore[arg-type]
    await enforcer.require(PluginPermission.FILESYSTEM_READ)  # no raise = pass


async def test_requested_but_ungranted_is_denied_call(grants: GrantStore) -> None:
    audit = InMemoryAuditLogger()
    enforcer = PermissionEnforcer(_manifest(), grants, audit=audit)  # type: ignore[arg-type]

    with pytest.raises(PermissionDeniedError) as excinfo:
        await enforcer.require(PluginPermission.NETWORK)

    error = excinfo.value
    assert error.plugin == "doc-intel"
    assert error.permission is PluginPermission.NETWORK
    assert error.reason == "not_granted"

    [event] = audit.events
    assert isinstance(event, PluginPermissionEvent)
    assert event.action == "denied_call"
    assert event.permission == "network"


async def test_unrequested_permission_is_violation(grants: GrantStore) -> None:
    audit = InMemoryAuditLogger()
    # Even a USER grant cannot open a permission the manifest never requested.
    await grants.grant("doc-intel", PluginPermission.CREDENTIALS)
    enforcer = PermissionEnforcer(_manifest(), grants, audit=audit)  # type: ignore[arg-type]

    with pytest.raises(PermissionDeniedError) as excinfo:
        await enforcer.require(PluginPermission.CREDENTIALS)
    assert excinfo.value.reason == "not_requested"

    violation = [e for e in audit.events if isinstance(e, PluginPermissionEvent)][-1]
    assert violation.action == "violation"


async def test_revoked_permission_is_then_denied(grants: GrantStore) -> None:
    await grants.grant("doc-intel", PluginPermission.NETWORK)
    await grants.revoke("doc-intel", PluginPermission.NETWORK)
    enforcer = PermissionEnforcer(_manifest(), grants)  # type: ignore[arg-type]
    with pytest.raises(PermissionDeniedError):
        await enforcer.require(PluginPermission.NETWORK)


async def test_grants_persist_across_store_instances(tmp_path: Path) -> None:
    path = tmp_path / "plugin_grants.json"
    store = GrantStore(path)
    await store.grant("doc-intel", PluginPermission.FILESYSTEM_READ)

    reopened = GrantStore(path)
    assert reopened.granted("doc-intel") == frozenset({PluginPermission.FILESYSTEM_READ})


async def test_all_transitions_audited(grants: GrantStore) -> None:
    """DCL-084: grants, denies, revocations recorded."""
    audit = InMemoryAuditLogger()
    await grants.grant("doc-intel", PluginPermission.NETWORK, audit=audit)
    await grants.revoke("doc-intel", PluginPermission.NETWORK, audit=audit)
    enforcer = PermissionEnforcer(_manifest(), grants, audit=audit)  # type: ignore[arg-type]
    with pytest.raises(PermissionDeniedError):
        await enforcer.require(PluginPermission.NETWORK)

    actions = [e.action for e in audit.events if isinstance(e, PluginPermissionEvent)]
    assert actions == ["granted", "revoked", "denied_call"]


async def test_missing_grants_file_means_no_grants(tmp_path: Path) -> None:
    store = GrantStore(tmp_path / "does-not-exist.json")
    assert store.granted("doc-intel") == frozenset()


async def test_revoke_never_granted_is_noop(grants: GrantStore) -> None:
    await grants.revoke("doc-intel", PluginPermission.NETWORK)  # no raise
    assert grants.granted("doc-intel") == frozenset()
