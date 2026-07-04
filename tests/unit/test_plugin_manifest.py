"""Tests for the plugin.yaml schema + validator (DCL-080).

Acceptance: invalid manifests rejected with helpful error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from declaw.plugin_host.manifest import (
    ManifestError,
    PluginManifest,
    PluginPermission,
    load_manifest,
    parse_manifest,
)


def _valid() -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "name": "doc-intel",
        "version": "0.1.0",
        "description_en": "Document intelligence for your workspace.",
        "description_fr": "Intelligence documentaire pour votre espace de travail.",
        "entrypoint": "main.py",
        "permissions": {"requested": ["filesystem.read"], "denied": ["network"]},
        "author": "DeClaw Core Team",
    }


def test_valid_manifest_parses() -> None:
    manifest = parse_manifest(_valid())
    assert manifest.name == "doc-intel"
    assert manifest.permissions.requested == (PluginPermission.FILESYSTEM_READ,)
    assert manifest.permissions.denied == (PluginPermission.NETWORK,)


def test_requested_and_denied_overlap_rejected() -> None:
    raw = _valid()
    raw["permissions"] = {"requested": ["network"], "denied": ["network"]}
    with pytest.raises(ManifestError, match="both requested and denied: network"):
        parse_manifest(raw)


@pytest.mark.parametrize(
    "field,value,fragment",
    [
        ("name", "Doc Intel", "lowercase slug"),
        ("name", "-bad", "lowercase slug"),
        ("version", "1.0", "semver"),
        ("version", "v1.0.0", "semver"),
        ("description_en", "  ", "non-empty"),
        ("description_fr", "", "non-empty"),
        ("entrypoint", "../evil.py", "traverse"),
        ("entrypoint", "/abs/path.py", "relative"),
        ("entrypoint", "C:/abs/path.py", "relative"),
        ("entrypoint", "main.sh", ".py"),
        ("manifest_version", 99, "unsupported"),
    ],
)
def test_invalid_fields_rejected_with_helpful_error(
    field: str, value: Any, fragment: str
) -> None:
    raw = _valid()
    raw[field] = value
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(raw)
    assert fragment in str(excinfo.value)


def test_unknown_permission_rejected() -> None:
    raw = _valid()
    raw["permissions"] = {"requested": ["root-access"]}
    with pytest.raises(ManifestError, match="permissions"):
        parse_manifest(raw)


def test_unknown_top_level_key_rejected() -> None:
    raw = _valid()
    raw["shell_access"] = True
    with pytest.raises(ManifestError, match="shell_access"):
        parse_manifest(raw)


def test_missing_required_field_rejected() -> None:
    raw = _valid()
    del raw["description_fr"]
    with pytest.raises(ManifestError, match="description_fr"):
        parse_manifest(raw)


def test_manifest_is_frozen() -> None:
    manifest = parse_manifest(_valid())
    with pytest.raises(Exception):
        manifest.name = "other"  # type: ignore[misc]


# --- load_manifest (file layer) ---------------------------------------------------


def test_load_manifest_from_directory(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "doc-intel"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
manifest_version: 1
name: doc-intel
version: 0.1.0
description_en: Docs.
description_fr: Documents.
entrypoint: main.py
permissions:
  requested: [filesystem.read]
""",
        encoding="utf-8",
    )
    manifest = load_manifest(plugin_dir)
    assert isinstance(manifest, PluginManifest)
    assert manifest.permissions.requested == (PluginPermission.FILESYSTEM_READ,)


def test_load_manifest_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="No plugin.yaml"):
        load_manifest(tmp_path)


def test_load_manifest_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "plugin.yaml").write_text("{{not yaml", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(tmp_path)


def test_load_manifest_non_mapping(tmp_path: Path) -> None:
    (tmp_path / "plugin.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="must be a mapping"):
        load_manifest(tmp_path)
