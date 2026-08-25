"""Discovery, and the gate every capability must pass before it can run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from declaw.plugin_host.errors import PluginLoadError
from declaw.plugin_host.loader import discover, validate_described
from declaw.plugin_host.manifest import PluginPermission, parse_manifest
from declaw.plugin_host.schema import PluginSchemaError
from declaw_plugin_sdk.protocol import CapabilityDescriptor, DescribeResult

_MANIFEST = {
    "manifest_version": 1,
    "name": "echo-plugin",
    "version": "1.0.0",
    "description_en": "Echo.",
    "description_fr": "Echo.",
    "entrypoint": "main.py",
    "permissions": {"requested": ["filesystem.read"], "denied": ["network"]},
}

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
}


def _cap(**overrides: Any) -> CapabilityDescriptor:
    base: dict[str, Any] = {
        "name": "echo",
        "description_en": "Echo.",
        "description_fr": "Echo.",
        "args_schema": _SCHEMA,
    }
    return CapabilityDescriptor(**{**base, **overrides})


def _described(*capabilities: CapabilityDescriptor, **overrides: Any) -> DescribeResult:
    base: dict[str, Any] = {"name": "echo-plugin", "version": "1.0.0"}
    return DescribeResult(**{**base, **overrides}, capabilities=capabilities)


def _write_manifest(directory: Path, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.yaml").write_text(
        f"manifest_version: 1\nname: {name}\nversion: 1.0.0\n"
        f"description_en: A plugin.\ndescription_fr: Une extension.\nentrypoint: main.py\n",
        encoding="utf-8",
    )


def test_a_clean_capability_validates() -> None:
    manifest = parse_manifest(_MANIFEST)
    (validated,) = validate_described(manifest, _described(_cap()))
    assert validated.descriptor.name == "echo"
    assert validated.args_model.model_validate({"message": "hi"})


def test_requested_permission_is_converted_to_the_enum() -> None:
    manifest = parse_manifest(_MANIFEST)
    (validated,) = validate_described(manifest, _described(_cap(requires=["filesystem.read"])))
    assert validated.permissions == (PluginPermission.FILESYSTEM_READ,)


def test_a_capability_requiring_an_unrequested_permission_refuses_the_whole_plugin() -> None:
    # This is where DCL-097's "permission violation" actually lives: load time.
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(manifest, _described(_cap(requires=["network"])))
    assert "network" in str(excinfo.value)


def test_an_unknown_permission_string_is_refused() -> None:
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError):
        validate_described(manifest, _described(_cap(requires=["filesystem.obliterate"])))


def test_a_capability_name_that_is_not_a_slug_is_refused() -> None:
    # The name becomes a tool name sent to the model; Ollama restricts these.
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(manifest, _described(_cap(name="Echo It!")))
    assert "Echo It!" in str(excinfo.value)


def test_duplicate_capability_names_are_refused() -> None:
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError):
        validate_described(manifest, _described(_cap(), _cap()))


def test_a_name_mismatch_between_manifest_and_describe_is_refused() -> None:
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(manifest, _described(_cap(), name="something-else"))
    assert "something-else" in str(excinfo.value)


def test_a_future_sdk_version_is_refused_with_a_readable_message() -> None:
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(manifest, _described(_cap(), sdk_version=99))
    assert "99" in str(excinfo.value)


def test_an_unsupported_args_schema_is_refused() -> None:
    manifest = parse_manifest(_MANIFEST)
    bad = {"type": "object", "properties": {"nested": {"type": "object"}}}
    with pytest.raises(PluginSchemaError):
        validate_described(manifest, _described(_cap(args_schema=bad)))


def test_model_facing_write_capability_with_external_content_is_refused() -> None:
    # The registry sanitizes READ external-content tools and confirms non-READ
    # ones, but never composes both — so this shape would reach the model
    # unsanitized. Refuse it rather than leave the hole open.
    manifest = parse_manifest(_MANIFEST)
    with pytest.raises(PluginLoadError) as excinfo:
        validate_described(
            manifest,
            _described(
                _cap(
                    exposed_to_model=True,
                    classification="write",
                    produces_external_content=True,
                )
            ),
        )
    assert "sanitiz" in str(excinfo.value).lower()


def test_the_same_shape_is_fine_when_it_is_not_exposed_to_the_model() -> None:
    manifest = parse_manifest(_MANIFEST)
    validated = validate_described(
        manifest,
        _described(_cap(classification="write", produces_external_content=True)),
    )
    assert len(validated) == 1


def test_a_read_capability_with_external_content_is_fine() -> None:
    manifest = parse_manifest(_MANIFEST)
    validated = validate_described(
        manifest,
        _described(
            _cap(exposed_to_model=True, classification="read", produces_external_content=True)
        ),
    )
    assert len(validated) == 1


def test_discover_finds_a_plugin_directory(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "echo-plugin", "echo-plugin")
    found, failures = discover(tmp_path)
    assert [p.manifest.name for p in found] == ["echo-plugin"]
    assert failures == []


def test_one_broken_manifest_does_not_stop_the_others(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "good", "good")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "plugin.yaml").write_text("name: 'MISSING EVERYTHING'\n", encoding="utf-8")

    found, failures = discover(tmp_path)
    assert [p.manifest.name for p in found] == ["good"]
    assert len(failures) == 1 and failures[0].directory == bad


def test_a_directory_without_a_manifest_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "not-a-plugin").mkdir()
    found, failures = discover(tmp_path)
    assert found == [] and failures == []


def test_a_missing_directory_is_empty_not_fatal(tmp_path: Path) -> None:
    found, failures = discover(tmp_path / "does-not-exist")
    assert found == [] and failures == []
