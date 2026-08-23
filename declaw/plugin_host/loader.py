"""Find plugins, and decide whether each one is allowed to run.

Discovery is deliberately narrow in v0.1: only ``plugins/builtin`` is scanned.
Scanning a user directory would be a third-party install path by file copy,
with no signature check — exactly what the phase decision excluded.

``validate_described`` is the gate. A plugin that fails ANY check does not
start at all, rather than starting and failing later in a way the user has to
interpret. Every message names the offending capability.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

import declaw
from declaw.config import Settings
from declaw.plugin_host.errors import PluginLoadError
from declaw.plugin_host.manifest import (
    MANIFEST_FILENAME,
    ManifestError,
    PluginManifest,
    PluginPermission,
    load_manifest,
)
from declaw.plugin_host.schema import model_from_json_schema
from declaw_plugin_sdk.protocol import SDK_VERSION, CapabilityDescriptor, DescribeResult

# A capability name becomes a tool name the model sees, and Ollama's
# function-calling schema restricts what may appear there.
CAPABILITY_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,50}$")


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    """A directory holding a valid manifest. Not yet started."""

    directory: Path
    manifest: PluginManifest


@dataclass(frozen=True, slots=True)
class DiscoveryFailure:
    """A directory that looked like a plugin but could not be read."""

    directory: Path
    reason: str


@dataclass(frozen=True, slots=True)
class ValidatedCapability:
    """One capability that passed every load-time check."""

    descriptor: CapabilityDescriptor
    permissions: tuple[PluginPermission, ...]
    args_model: type[BaseModel]


def builtin_plugins_dir(settings: Settings) -> Path:
    """Resolve where the shipped plugins live, checkout or packaged."""
    if settings.builtin_plugins_dir is not None:
        return settings.builtin_plugins_dir
    candidates = [
        # Development checkout: plugins/ is a sibling of the declaw package.
        Path(declaw.__file__).resolve().parent.parent / "plugins" / "builtin",
        # Packaged app: shipped beside the executable.
        Path(sys.executable).resolve().parent / "plugins" / "builtin",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def discover(search_dir: Path) -> tuple[list[DiscoveredPlugin], list[DiscoveryFailure]]:
    """Scan ``search_dir`` for plugin directories. A broken one is skipped, not fatal."""
    if not search_dir.is_dir():
        return [], []
    found: list[DiscoveredPlugin] = []
    failures: list[DiscoveryFailure] = []
    for entry in sorted(search_dir.iterdir()):
        if not entry.is_dir() or not (entry / MANIFEST_FILENAME).is_file():
            continue
        try:
            found.append(DiscoveredPlugin(directory=entry, manifest=load_manifest(entry)))
        except ManifestError as exc:
            failures.append(DiscoveryFailure(directory=entry, reason=str(exc)))
    return found, failures


def validate_described(
    manifest: PluginManifest, described: DescribeResult
) -> tuple[ValidatedCapability, ...]:
    """Check a plugin's announced capabilities against its signed manifest."""
    if described.sdk_version != SDK_VERSION:
        raise PluginLoadError(
            f"Plugin {manifest.name!r} speaks SDK version {described.sdk_version}; "
            f"this DeClaw understands {SDK_VERSION}."
        )
    if described.name != manifest.name:
        raise PluginLoadError(
            f"Plugin in {manifest.name!r}'s directory identifies itself as "
            f"{described.name!r}; the manifest and the code disagree."
        )

    requested = set(manifest.permissions.requested)
    validated: list[ValidatedCapability] = []
    seen: set[str] = set()

    for descriptor in described.capabilities:
        name = descriptor.name
        if not CAPABILITY_NAME_RE.match(name):
            raise PluginLoadError(
                f"Plugin {manifest.name!r}: capability name {name!r} must be a lowercase slug."
            )
        if name in seen:
            raise PluginLoadError(
                f"Plugin {manifest.name!r} declares capability {name!r} more than once."
            )
        seen.add(name)

        permissions: list[PluginPermission] = []
        for raw in descriptor.requires:
            try:
                permission = PluginPermission(raw)
            except ValueError as exc:
                raise PluginLoadError(
                    f"Plugin {manifest.name!r}, capability {name!r}: "
                    f"{raw!r} is not a permission DeClaw knows."
                ) from exc
            if permission not in requested:
                raise PluginLoadError(
                    f"Plugin {manifest.name!r}, capability {name!r} requires "
                    f"{permission.value!r}, which its manifest never requested."
                )
            permissions.append(permission)

        if (
            descriptor.exposed_to_model
            and descriptor.produces_external_content
            and descriptor.classification != "read"
        ):
            raise PluginLoadError(
                f"Plugin {manifest.name!r}, capability {name!r}: a model-facing capability "
                "that returns external content must be classified 'read', otherwise the "
                "registry would confirm it without sanitizing it."
            )

        validated.append(
            ValidatedCapability(
                descriptor=descriptor,
                permissions=tuple(permissions),
                args_model=model_from_json_schema(
                    f"{manifest.name}_{name}_Args", descriptor.args_schema
                ),
            )
        )
    return tuple(validated)
