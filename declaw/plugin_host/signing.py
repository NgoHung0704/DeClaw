"""ed25519 plugin signature verification (DCL-083).

Third-party plugins must be signed. What is signed is the raw bytes of
``plugin.yaml`` — the manifest IS the security contract (name, entrypoint,
permissions), so a tampered manifest invalidates the signature, and a
signature from an untrusted key proves nothing.

Model:

* A signer (plugin author with a DeClaw-registered key, or the DeClaw team)
  holds an ed25519 **signing key** and publishes the 32-byte **verify key**
  (hex). ``sign_manifest`` exists for that tooling and for tests.
* DeClaw ships/configures a set of **trusted verify keys**.
  ``verify_manifest_bytes`` accepts iff at least one trusted key validates
  the signature over the exact manifest bytes.
* ``verify_plugin_dir`` reads ``plugin.yaml`` + ``plugin.sig`` (hex, detached)
  from a plugin directory. A missing signature is a distinct, actionable
  error — "unsigned" and "forged" are different user conversations. The
  loader (DCL-090, Phase 7) will call this before anything in the plugin dir
  is even parsed; per settings, ``plugin_signature_required=True`` means
  unsigned third-party plugins are rejected by default.
"""

from __future__ import annotations

from pathlib import Path

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from declaw.plugin_host.manifest import MANIFEST_FILENAME

SIGNATURE_FILENAME = "plugin.sig"


class SignatureError(ValueError):
    """Signature missing, malformed, untrusted, or invalid."""


class UnsignedPluginError(SignatureError):
    """The plugin carries no signature at all."""


def generate_keypair() -> tuple[str, str]:
    """Return ``(signing_key_hex, verify_key_hex)`` — author-side tooling."""
    signing_key = SigningKey.generate()
    return (
        signing_key.encode().hex(),
        signing_key.verify_key.encode().hex(),
    )


def sign_manifest(manifest_bytes: bytes, signing_key_hex: str) -> str:
    """Sign the exact manifest bytes; returns the detached signature as hex."""
    signing_key = SigningKey(bytes.fromhex(signing_key_hex))
    return signing_key.sign(manifest_bytes).signature.hex()


def verify_manifest_bytes(
    manifest_bytes: bytes,
    signature_hex: str,
    trusted_verify_keys_hex: frozenset[str] | set[str],
) -> str:
    """Verify ``signature_hex`` over ``manifest_bytes`` against trusted keys.

    Returns the hex of the key that validated. Raises :class:`SignatureError`
    if no trusted key validates (or the signature/keys are malformed).
    """
    if not trusted_verify_keys_hex:
        raise SignatureError("No trusted plugin signing keys are configured.")
    try:
        signature = bytes.fromhex(signature_hex.strip())
    except ValueError as exc:
        raise SignatureError(f"Malformed plugin signature (not hex): {exc}") from exc

    for key_hex in sorted(trusted_verify_keys_hex):
        try:
            VerifyKey(bytes.fromhex(key_hex)).verify(manifest_bytes, signature)
        except (BadSignatureError, ValueError):
            continue
        return key_hex
    raise SignatureError(
        "Plugin signature is invalid: no trusted key validates this manifest "
        "(the manifest may have been tampered with, or the signer is not trusted)."
    )


def verify_plugin_dir(
    plugin_dir: Path,
    trusted_verify_keys_hex: frozenset[str] | set[str],
) -> str:
    """Verify the detached signature of the plugin at ``plugin_dir``.

    Returns the validating key's hex. Raises :class:`UnsignedPluginError` when
    ``plugin.sig`` is absent, :class:`SignatureError` on any other failure.
    """
    manifest_path = plugin_dir / MANIFEST_FILENAME
    signature_path = plugin_dir / SIGNATURE_FILENAME
    if not manifest_path.is_file():
        raise SignatureError(f"No {MANIFEST_FILENAME} in {plugin_dir}.")
    if not signature_path.is_file():
        raise UnsignedPluginError(
            f"Plugin at {plugin_dir} is unsigned ({SIGNATURE_FILENAME} missing). "
            "Third-party plugins must be signed."
        )
    return verify_manifest_bytes(
        manifest_path.read_bytes(),
        signature_path.read_text(encoding="ascii"),
        trusted_verify_keys_hex,
    )
