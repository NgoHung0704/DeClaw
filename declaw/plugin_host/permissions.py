"""Plugin permission enforcement + audited grant store (DCL-081 / DCL-084).

The rule a plugin call must satisfy before touching a capability:

    exercisable = requested in manifest  AND  granted by the user

Anything else is refused with a *structured* error (the IPC layer turns it
into an error frame the plugin can parse) and lands in the audit trail:

* requested but not granted   -> ``denied_call``   (normal, user said no/not yet)
* not even in the manifest    -> ``violation``     (plugin is misbehaving —
  DCL-097 escalates this to process termination in Phase 7)

Grants live in ``data_dir/plugin_grants.json`` — plain JSON on purpose: the
grant list is not a secret (it is the user's own policy) and being able to
read/diff it is a transparency feature. Every grant/revoke/denial emits a
:class:`PluginPermissionEvent` (DCL-084: grants, denies, revocations
recorded). The Phase 9 permission dialog (DCL-082) is just a UI over
``GrantStore.grant``/``revoke``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from declaw.audit.events import PluginPermissionEvent
from declaw.audit.logger import AuditLogger
from declaw.plugin_host.manifest import PluginManifest, PluginPermission

GRANTS_FILENAME = "plugin_grants.json"

DenialReason = Literal["not_requested", "not_granted"]


class PermissionDeniedError(Exception):
    """A plugin exercised a permission it may not use. Structured for IPC."""

    def __init__(self, plugin: str, permission: PluginPermission, reason: DenialReason) -> None:
        self.plugin = plugin
        self.permission = permission
        self.reason = reason
        detail = (
            "its manifest never requested it"
            if reason == "not_requested"
            else "the user has not granted it"
        )
        super().__init__(
            f"Plugin {plugin!r} may not use permission {permission.value!r}: {detail}."
        )


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Non-raising check result."""

    allowed: bool
    reason: DenialReason | None = None


class GrantStore:
    """User permission grants, persisted as plain JSON, every change audited."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._grants: dict[str, set[PluginPermission]] = {}
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._grants = {
                plugin: {PluginPermission(p) for p in permissions}
                for plugin, permissions in raw.items()
            }

    def granted(self, plugin: str) -> frozenset[PluginPermission]:
        return frozenset(self._grants.get(plugin, set()))

    async def grant(
        self,
        plugin: str,
        permission: PluginPermission,
        *,
        audit: AuditLogger | None = None,
    ) -> None:
        self._grants.setdefault(plugin, set()).add(permission)
        self._save()
        if audit is not None:
            await audit.emit(
                PluginPermissionEvent(
                    plugin=plugin, permission=permission.value, action="granted"
                )
            )

    async def revoke(
        self,
        plugin: str,
        permission: PluginPermission,
        *,
        audit: AuditLogger | None = None,
    ) -> None:
        self._grants.get(plugin, set()).discard(permission)
        self._save()
        if audit is not None:
            await audit.emit(
                PluginPermissionEvent(
                    plugin=plugin, permission=permission.value, action="revoked"
                )
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            plugin: sorted(p.value for p in permissions)
            for plugin, permissions in self._grants.items()
            if permissions
        }
        self._path.write_text(
            json.dumps(serializable, indent=2, sort_keys=True), encoding="utf-8"
        )


class PermissionEnforcer:
    """The middleware every plugin-facing capability call goes through."""

    def __init__(
        self,
        manifest: PluginManifest,
        grants: GrantStore,
        *,
        audit: AuditLogger | None = None,
    ) -> None:
        self._manifest = manifest
        self._grants = grants
        self._audit = audit

    def check(self, permission: PluginPermission) -> PermissionDecision:
        """Non-raising decision (no audit side effect)."""
        if permission not in self._manifest.permissions.requested:
            return PermissionDecision(allowed=False, reason="not_requested")
        if permission not in self._grants.granted(self._manifest.name):
            return PermissionDecision(allowed=False, reason="not_granted")
        return PermissionDecision(allowed=True)

    async def require(self, permission: PluginPermission) -> None:
        """Raise :class:`PermissionDeniedError` (and audit) unless exercisable."""
        decision = self.check(permission)
        if decision.allowed:
            return
        assert decision.reason is not None
        if self._audit is not None:
            await self._audit.emit(
                PluginPermissionEvent(
                    plugin=self._manifest.name,
                    permission=permission.value,
                    action="violation" if decision.reason == "not_requested" else "denied_call",
                )
            )
        raise PermissionDeniedError(self._manifest.name, permission, decision.reason)
