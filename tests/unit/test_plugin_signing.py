"""Tests for ed25519 plugin signature verification (DCL-083).

Acceptance: tampered plugin rejected. Also: unsigned rejected distinctly,
untrusted signer rejected, happy path returns the validating key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from declaw.plugin_host.signing import (
    SIGNATURE_FILENAME,
    SignatureError,
    UnsignedPluginError,
    generate_keypair,
    sign_manifest,
    verify_manifest_bytes,
    verify_plugin_dir,
)

_MANIFEST = b"""manifest_version: 1
name: doc-intel
version: 0.1.0
description_en: Docs.
description_fr: Documents.
entrypoint: main.py
permissions:
  requested: [filesystem.read]
"""


def _signed_plugin(tmp_path: Path) -> tuple[Path, str]:
    signing_hex, verify_hex = generate_keypair()
    plugin_dir = tmp_path / "doc-intel"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_bytes(_MANIFEST)
    (plugin_dir / SIGNATURE_FILENAME).write_text(
        sign_manifest(_MANIFEST, signing_hex), encoding="ascii"
    )
    return plugin_dir, verify_hex


def test_valid_signature_verifies(tmp_path: Path) -> None:
    plugin_dir, verify_hex = _signed_plugin(tmp_path)
    assert verify_plugin_dir(plugin_dir, {verify_hex}) == verify_hex


def test_tampered_manifest_rejected(tmp_path: Path) -> None:
    """The acceptance: any post-signature edit invalidates the plugin."""
    plugin_dir, verify_hex = _signed_plugin(tmp_path)
    manifest = plugin_dir / "plugin.yaml"
    # Attacker escalates permissions after signing.
    manifest.write_bytes(
        _MANIFEST.replace(b"[filesystem.read]", b"[filesystem.read, network, credentials]")
    )
    with pytest.raises(SignatureError, match="tampered|not trusted"):
        verify_plugin_dir(plugin_dir, {verify_hex})


def test_unsigned_plugin_rejected_distinctly(tmp_path: Path) -> None:
    plugin_dir, verify_hex = _signed_plugin(tmp_path)
    (plugin_dir / SIGNATURE_FILENAME).unlink()
    with pytest.raises(UnsignedPluginError, match="unsigned"):
        verify_plugin_dir(plugin_dir, {verify_hex})


def test_untrusted_signer_rejected(tmp_path: Path) -> None:
    plugin_dir, _ = _signed_plugin(tmp_path)
    _, other_verify = generate_keypair()  # trusted set contains a DIFFERENT key
    with pytest.raises(SignatureError):
        verify_plugin_dir(plugin_dir, {other_verify})


def test_multiple_trusted_keys_any_validates() -> None:
    signing_hex, verify_hex = generate_keypair()
    _, unrelated_verify = generate_keypair()
    signature = sign_manifest(_MANIFEST, signing_hex)
    validated = verify_manifest_bytes(_MANIFEST, signature, {unrelated_verify, verify_hex})
    assert validated == verify_hex


def test_empty_trust_store_rejected() -> None:
    signing_hex, _ = generate_keypair()
    signature = sign_manifest(_MANIFEST, signing_hex)
    with pytest.raises(SignatureError, match="No trusted"):
        verify_manifest_bytes(_MANIFEST, signature, set())


def test_malformed_signature_rejected() -> None:
    _, verify_hex = generate_keypair()
    with pytest.raises(SignatureError, match="not hex"):
        verify_manifest_bytes(_MANIFEST, "zz-not-hex", {verify_hex})


def test_signature_over_different_bytes_rejected() -> None:
    signing_hex, verify_hex = generate_keypair()
    signature = sign_manifest(b"other bytes entirely", signing_hex)
    with pytest.raises(SignatureError):
        verify_manifest_bytes(_MANIFEST, signature, {verify_hex})
