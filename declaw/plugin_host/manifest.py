"""``plugin.yaml`` schema + validator (DCL-080).

Every plugin ships a ``plugin.yaml`` manifest describing what it is and —
critically — what it is allowed to touch. The manifest is the unit that gets
ed25519-signed (DCL-083) and the source of truth the permission middleware
enforces (DCL-081): a plugin can never use a permission its manifest did not
request and the user did not grant.

Validation is strict on purpose: a manifest that fails ANY check is rejected
with a helpful, human-readable error (the acceptance). Notable semantic
checks:

* a permission cannot be both ``requested`` and ``denied`` (``denied`` is the
  plugin author's own promise-list — "this plugin will never ask for X" — a
  trust signal shown at install time and enforced forever after);
* the entrypoint must be a relative ``.py`` path inside the plugin directory
  (no traversal, no absolute paths — same boundary philosophy as the
  filesystem tools);
* names are slugs and versions are semver, so registry paths and UI strings
  are always safe to build from them.
"""

from __future__ import annotations

import enum
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MANIFEST_FILENAME = "plugin.yaml"
MANIFEST_VERSION = 1

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,50}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class PluginPermission(str, enum.Enum):
    """The closed vocabulary of things a plugin may be granted."""

    FILESYSTEM_READ = "filesystem.read"  # read files inside the workspace
    FILESYSTEM_WRITE = "filesystem.write"  # write/move files inside the workspace
    NETWORK = "network"  # outbound network (always egress-audited)
    CREDENTIALS = "credentials"  # secrets via the core credential API (DCL-071)
    OS_AUDIO = "os.audio"  # os-bridge audio APIs
    OS_DISPLAY = "os.display"  # os-bridge display APIs
    OS_LAUNCH = "os.launch"  # os-bridge open/launch APIs
    NOTIFICATIONS = "notifications"  # native toasts


class ManifestError(ValueError):
    """A plugin manifest failed validation. Message is user-facing."""


class PluginPermissions(BaseModel):
    """Requested vs author-denied permissions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested: tuple[PluginPermission, ...] = ()
    # Author's promise-list: permissions this plugin declares it will NEVER
    # request. Overlap with `requested` is a contradiction and is rejected.
    denied: tuple[PluginPermission, ...] = ()

    @model_validator(mode="after")
    def _no_overlap(self) -> PluginPermissions:
        overlap = set(self.requested) & set(self.denied)
        if overlap:
            names = ", ".join(sorted(p.value for p in overlap))
            raise ValueError(
                f"permissions listed as both requested and denied: {names}"
            )
        return self


class PluginManifest(BaseModel):
    """Validated content of one ``plugin.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: int = Field(default=MANIFEST_VERSION)
    name: str
    version: str
    description_en: str
    description_fr: str
    entrypoint: str
    permissions: PluginPermissions = Field(default_factory=PluginPermissions)
    author: str = ""
    homepage: str = ""

    @field_validator("manifest_version")
    @classmethod
    def _known_version(cls, value: int) -> int:
        if value != MANIFEST_VERSION:
            raise ValueError(
                f"unsupported manifest_version {value} (this DeClaw understands {MANIFEST_VERSION})"
            )
        return value

    @field_validator("name")
    @classmethod
    def _slug_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(
                f"name {value!r} must be a lowercase slug (letters, digits, '-', 2-51 chars)"
            )
        return value

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not _SEMVER_RE.match(value):
            raise ValueError(f"version {value!r} must be semver MAJOR.MINOR.PATCH")
        return value

    @field_validator("description_en", "description_fr")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("descriptions must be non-empty (EN and FR are both mandatory)")
        return value

    @field_validator("entrypoint")
    @classmethod
    def _contained_entrypoint(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or (len(path.parts) > 0 and re.match(r"^[A-Za-z]:", path.parts[0])):
            raise ValueError(f"entrypoint {value!r} must be a relative path")
        if ".." in path.parts:
            raise ValueError(f"entrypoint {value!r} must not traverse outside the plugin dir")
        if path.suffix != ".py":
            raise ValueError(f"entrypoint {value!r} must be a .py file")
        return value


def parse_manifest(raw: dict[str, Any]) -> PluginManifest:
    """Validate an already-decoded mapping into a :class:`PluginManifest`.

    Raises :class:`ManifestError` with a readable message on any failure.
    """
    try:
        return PluginManifest.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc']) or 'manifest'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ManifestError(f"Invalid plugin manifest: {problems}") from exc


def load_manifest(path: Path) -> PluginManifest:
    """Load + validate ``plugin.yaml`` at ``path`` (file or plugin directory)."""
    manifest_path = path / MANIFEST_FILENAME if path.is_dir() else path
    if not manifest_path.is_file():
        raise ManifestError(f"No {MANIFEST_FILENAME} found at {manifest_path}.")
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"Invalid plugin manifest: not valid YAML ({exc}).") from exc
    if not isinstance(raw, dict):
        raise ManifestError("Invalid plugin manifest: top level must be a mapping.")
    return parse_manifest(raw)
