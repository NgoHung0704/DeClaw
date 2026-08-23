"""The single surface the rest of DeClaw uses to talk to plugins.

Startup is a pipeline, and every stage can refuse: discover a directory, read
its manifest, spawn the process, ask it to describe itself, validate what it
claims against what its manifest requested, grant what a builtin plugin needs,
and only then publish its tools. A plugin that fails any stage is skipped with
an audited reason; the others load normally.

Auto-granting is narrow and deliberate. A builtin plugin ships inside the
application, so a user who does not trust it cannot trust DeClaw either — there
is no separate trust decision to prompt for, and prompting would only train
people to click through. What makes it acceptable is that it is visible
(audited, listed by ``declaw plugins list``) and reversible (a revoked
permission is recorded and never auto-granted again). None of that reasoning
survives contact with third-party plugins, which is why installation is out of
scope until there is a dialog to gate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from declaw.audit.events import PluginLifecycleEvent
from declaw.audit.logger import AuditLogger
from declaw.config import Settings, get_settings
from declaw.log import logger
from declaw.plugin_host.errors import PluginHostError, PluginUnavailableError
from declaw.plugin_host.loader import (
    ValidatedCapability,
    builtin_plugins_dir,
    discover,
    validate_described,
)
from declaw.plugin_host.manifest import PluginManifest
from declaw.plugin_host.permissions import GrantStore, PermissionEnforcer
from declaw.plugin_host.process import PluginProcess
from declaw.plugin_host.state import PluginStateStore
from declaw.plugin_host.supervisor import PluginSupervisor
from declaw.plugin_host.tools import PluginTool, build_plugin_tool
from declaw_plugin_sdk.protocol import DescribeResult

# No capability may hold a process hostage longer than this, whatever it declares.
MAX_TIMEOUT_S = 600.0
DESCRIBE_TIMEOUT_S = 30.0

LifecycleAction = Any  # narrowed by PluginLifecycleEvent's own Literal


@dataclass(slots=True)
class LoadedPlugin:
    """One plugin that started, validated, and is serving calls."""

    manifest: PluginManifest
    directory: Path
    capabilities: dict[str, ValidatedCapability]
    supervisor: PluginSupervisor
    enforcer: PermissionEnforcer


class PluginHost:
    """Discover, run, and route calls to plugins."""

    def __init__(
        self,
        *,
        state: PluginStateStore,
        grants: GrantStore,
        settings: Settings | None = None,
        search_dir: Path | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._search_dir = search_dir or builtin_plugins_dir(self._settings)
        self._state = state
        self._grants = grants
        self._audit = audit
        self._plugins: dict[str, LoadedPlugin] = {}
        self._failures: list[str] = []

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Load every enabled, non-quarantined plugin found on disk."""
        found, discovery_failures = discover(self._search_dir)
        for failure in discovery_failures:
            self._failures.append(f"{failure.directory.name}: {failure.reason}")
            await self._emit(failure.directory.name, "load_failed", detail=failure.reason)

        for candidate in found:
            record = self._state.record(candidate.manifest.name)
            if not record.enabled or record.quarantined:
                continue
            try:
                await self._load(candidate.directory, candidate.manifest)
            # PluginHostError covers PluginLoadError AND the runtime failures a
            # describe handshake can hit (crash, timeout, error frame). Catching
            # only PluginLoadError would let one sick plugin abort startup for
            # every other plugin.
            except (PluginHostError, ValidationError, OSError) as exc:
                self._failures.append(f"{candidate.manifest.name}: {exc}")
                logger.error(f"Plugin {candidate.manifest.name!r} failed to load: {exc}")
                await self._emit(candidate.manifest.name, "load_failed", detail=str(exc))

    async def _load(self, directory: Path, manifest: PluginManifest) -> None:
        supervisor = PluginSupervisor(
            name=manifest.name,
            factory=lambda: PluginProcess(
                name=manifest.name, plugin_dir=directory, entrypoint=manifest.entrypoint
            ),
            on_quarantine=lambda reason: self._state.quarantine(manifest.name, reason),
        )
        await supervisor.start()
        try:
            raw = await supervisor.call("describe", timeout=DESCRIBE_TIMEOUT_S)
            described = DescribeResult.model_validate(raw)
            validated = validate_described(manifest, described)
        except BaseException:
            await supervisor.stop()
            raise

        await self._auto_grant(manifest)
        self._plugins[manifest.name] = LoadedPlugin(
            manifest=manifest,
            directory=directory,
            capabilities={c.descriptor.name: c for c in validated},
            supervisor=supervisor,
            enforcer=PermissionEnforcer(manifest, self._grants, audit=self._audit),
        )
        self._state.note_version(manifest.name, manifest.version)
        await self._emit(manifest.name, "started", version=manifest.version)

    async def _auto_grant(self, manifest: PluginManifest) -> None:
        """Grant what a builtin manifest requests, once, and remember doing it."""
        for permission in manifest.permissions.requested:
            if self._state.has_auto_granted(manifest.name, permission.value):
                continue  # already offered once; a later revoke must stick
            if permission in self._grants.granted(manifest.name):
                continue
            await self._grants.grant(manifest.name, permission, audit=self._audit)
            self._state.note_auto_grant(manifest.name, permission.value)

    async def stop(self) -> None:
        for name, plugin in list(self._plugins.items()):
            await plugin.supervisor.stop()
            await self._emit(name, "stopped", version=plugin.manifest.version)
        self._plugins.clear()

    # ------------------------------------------------------------------- calls

    async def call(self, plugin: str, capability: str, args: dict[str, Any]) -> Any:
        """Invoke a capability after checking every permission it declared."""
        loaded = self._plugins.get(plugin)
        if loaded is None:
            raise PluginUnavailableError(f"Plugin {plugin!r} is not loaded.")
        validated = loaded.capabilities.get(capability)
        if validated is None:
            raise PluginUnavailableError(f"Plugin {plugin!r} has no capability {capability!r}.")
        for permission in validated.permissions:
            await loaded.enforcer.require(permission)
        timeout = min(float(validated.descriptor.timeout_s), MAX_TIMEOUT_S)
        return await loaded.supervisor.call(
            "invoke", {"capability": capability, "args": args}, timeout=timeout
        )

    # ------------------------------------------------------------ introspection

    def loaded(self) -> list[LoadedPlugin]:
        return list(self._plugins.values())

    def failures(self) -> list[str]:
        return list(self._failures)

    def model_tools(self) -> list[PluginTool]:
        """Proxy tools for every capability a plugin published to the model."""
        tools: list[PluginTool] = []
        for plugin in self._plugins.values():
            for validated in plugin.capabilities.values():
                if not validated.descriptor.exposed_to_model:
                    continue
                tools.append(
                    build_plugin_tool(
                        plugin_name=plugin.manifest.name,
                        capability=validated,
                        invoke=self.call,
                    )
                )
        return tools

    # ---------------------------------------------------------------- user acts

    async def enable(self, name: str) -> None:
        self._state.set_enabled(name, True)
        self._state.clear_quarantine(name)
        await self._emit(name, "enabled")

    async def disable(self, name: str) -> None:
        loaded = self._plugins.pop(name, None)
        if loaded is not None:
            await loaded.supervisor.stop()
        self._state.set_enabled(name, False)
        await self._emit(name, "disabled")

    async def _emit(
        self, plugin: str, action: LifecycleAction, *, version: str = "", detail: str = ""
    ) -> None:
        if self._audit is None:
            return
        await self._audit.emit(
            PluginLifecycleEvent(plugin=plugin, version=version, action=action, detail=detail)
        )
