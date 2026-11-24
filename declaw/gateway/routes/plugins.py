"""``/api/plugins`` routes: inventory, honest enable/disable, permissions (DCL-130).

Single source of truth for the plugin page and the status page: built-ins
are enumerated from the manifest directories exactly as ``PluginHost``
discovers them, joined with the persisted ``PluginStateStore`` flags and the
live host state.

Enable/disable semantics are the honest ones (spec section 11):
``PluginHost.disable`` stops a running plugin immediately, while
``PluginHost.enable`` only flips persisted state and clears quarantine — the
plugin loads at the *next* gateway start, and the responses say exactly
that. Permission changes flow through the single ``GrantStore`` the host's
``PermissionEnforcer`` reads, so a grant made from the browser is visible to
the next capability call without any reload, and every grant/revoke lands
in the audit trail as a ``plugin.permission`` event.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request

from declaw.config import Language
from declaw.gateway.events import plugin_state_change_frame
from declaw.gateway.routes.auth import require_session
from declaw.gateway.routes.errors import ApiError, application_from
from declaw.gateway.routes.settings import effective_language
from declaw.plugin_host.loader import builtin_plugins_dir, discover
from declaw.plugin_host.manifest import PluginManifest, PluginPermission

if TYPE_CHECKING:
    from declaw.app import Application

router = APIRouter(prefix="/api/plugins", dependencies=[Depends(require_session)])

_STATE_QUARANTINED = "quarantined"
_STATE_ENABLED = "enabled"
_STATE_DISABLED = "disabled"

_TAKES_EFFECT_NEXT_START = "next_gateway_start"
_TAKES_EFFECT_IMMEDIATE = "immediate"


def _state_of(record: Any) -> str:
    """enabled/disabled/quarantined — quarantine outranks the enabled flag."""
    if record.quarantined:
        return _STATE_QUARANTINED
    return _STATE_ENABLED if record.enabled else _STATE_DISABLED


def _manifests(application: Application) -> list[PluginManifest]:
    """Every built-in manifest on disk, in discovery order."""
    found, _failures = discover(builtin_plugins_dir(application.settings))
    return [candidate.manifest for candidate in found]


def _known_manifest(application: Application, name: str) -> PluginManifest:
    for manifest in _manifests(application):
        if manifest.name == name:
            return manifest
    raise ApiError(404, "not_found", f"Unknown built-in plugin {name!r}.")


def plugin_inventory(application: Application, language: Language) -> list[dict[str, Any]]:
    """One entry per built-in plugin: identity, localized description, state.

    Also the status projection's source: ``GET /api/status`` renders the
    slim name/version/state slice of this exact inventory.
    """
    found, discovery_failures = discover(builtin_plugins_dir(application.settings))
    failures_by_name: dict[str, list[str]] = defaultdict(list)
    for failure in discovery_failures:
        failures_by_name[failure.directory.name].append(failure.reason)
    host = application.host
    host_failures = host.failures() if host is not None else []
    loaded_names = {p.manifest.name for p in host.loaded()} if host is not None else set()
    for entry in host_failures:
        name, separator, detail = entry.partition(": ")
        failures_by_name[name].append(detail if separator else entry)

    entries: list[dict[str, Any]] = []
    for candidate in found:
        manifest = candidate.manifest
        record = application.plugin_state.record(manifest.name)
        entries.append(
            {
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description_for_language(language),
                "state": _state_of(record),
                "loaded": manifest.name in loaded_names,
                "failures": sorted(failures_by_name.get(manifest.name, [])),
            }
        )
    return entries


@router.get("")
async def list_plugins(request: Request) -> dict[str, list[dict[str, Any]]]:
    application = application_from(request)
    return {
        "plugins": plugin_inventory(application, effective_language(application))
    }


def _require_host(application: Application) -> Any:
    """The started PluginHost; enable/disable act through it so they audit."""
    if application.host is None:
        raise ApiError(
            503,
            "service_unavailable",
            "Plugins are not running until the gateway application starts.",
        )
    return application.host


@router.post("/{name}/enable")
async def enable_plugin(name: str, request: Request) -> dict[str, str]:
    application = application_from(request)
    _known_manifest(application, name)
    await _require_host(application).enable(name)
    await _broadcast_state_change(request, name, "enabled")
    return {
        "name": name,
        "state": _state_of(application.plugin_state.record(name)),
        "takes_effect": _TAKES_EFFECT_NEXT_START,
    }


@router.post("/{name}/disable")
async def disable_plugin(name: str, request: Request) -> dict[str, str]:
    application = application_from(request)
    _known_manifest(application, name)
    await _require_host(application).disable(name)
    await _broadcast_state_change(request, name, "disabled")
    return {
        "name": name,
        "state": _state_of(application.plugin_state.record(name)),
        "takes_effect": _TAKES_EFFECT_IMMEDIATE,
    }


async def _broadcast_state_change(request: Request, name: str, action: str) -> None:
    """Fan the plugin state change out to /ws/events subscribers (Task 13).

    The broadcaster is the same EventBroadcaster the reindex seam uses; it
    is optional only in the sense that a bare test app may omit state.
    """
    broadcaster = getattr(request.app.state, "event_broadcaster", None)
    if broadcaster is None:
        return
    await broadcaster.broadcast(plugin_state_change_frame(name=name, action=action))


@router.get("/{name}/permissions")
async def plugin_permissions(name: str, request: Request) -> dict[str, Any]:
    application = application_from(request)
    manifest = _known_manifest(application, name)
    return {
        "name": name,
        "requested": sorted(p.value for p in manifest.permissions.requested),
        "denied": sorted(p.value for p in manifest.permissions.denied),
        "granted": _granted_values(application, name),
    }


def _granted_values(application: Application, name: str) -> list[str]:
    return sorted(p.value for p in application.plugin_grants.granted(name))


def _grants_payload(application: Application, name: str) -> dict[str, Any]:
    return {"name": name, "granted": _granted_values(application, name)}


@router.post("/{name}/permissions/{permission}/grant")
async def grant_permission(
    name: str, permission: PluginPermission, request: Request
) -> dict[str, Any]:
    application = application_from(request)
    _known_manifest(application, name)
    await application.plugin_grants.grant(name, permission, audit=request.app.state.audit)
    return _grants_payload(application, name)


@router.post("/{name}/permissions/{permission}/revoke")
async def revoke_permission(
    name: str, permission: PluginPermission, request: Request
) -> dict[str, Any]:
    application = application_from(request)
    _known_manifest(application, name)
    await application.plugin_grants.revoke(name, permission, audit=request.app.state.audit)
    return _grants_payload(application, name)
