"""Encrypted-file secrets fallback (DCL-074).

Used ONLY when the machine has no OS credential vault (headless Linux without
SecretService, stripped-down environments). Secrets are stored in one JSON
file of AES-256-GCM ciphertexts; the key is derived (scrypt) from the OS user
identity (username@hostname) plus a random per-file salt.

Honest security note (the "documented" half of the acceptance): deriving the
key from the user identity means anyone who can run code AS THIS USER can
re-derive it — this protects against casual file reading, backup leakage and
other-user access, NOT against a compromise of the user's own account. The
OS vault (DCL-070) is strictly stronger, which is why this store is a
fallback and never the default. ``default_credential_store`` picks the vault
whenever one exists.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from declaw.credentials.store import KNOWN_SECRET_NAMES

SECRETS_FILENAME = "secrets.enc.json"
_FORMAT_VERSION = 1
_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12


class CorruptSecretsError(ValueError):
    """The secrets file cannot be decrypted (wrong identity or tampering)."""


def _default_identity() -> str:
    return f"{getpass.getuser()}@{platform.node()}"


def _derive_key(identity: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=_KEY_BYTES, n=2**14, r=8, p=1).derive(
        identity.encode("utf-8")
    )


class EncryptedFileCredentialStore:
    """Same CRUD surface as ``CredentialStore``, backed by an encrypted file."""

    def __init__(self, path: Path, *, identity: str | None = None) -> None:
        self._path = path
        self._identity = identity if identity is not None else _default_identity()
        self._salt: bytes
        self._entries: dict[str, dict[str, str]]  # name -> {nonce, ciphertext} (hex)
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("format_version") != _FORMAT_VERSION:
                raise CorruptSecretsError(
                    f"Unsupported secrets file version {raw.get('format_version')!r}."
                )
            self._salt = bytes.fromhex(raw["salt"])
            self._entries = dict(raw["entries"])
        else:
            self._salt = os.urandom(16)
            self._entries = {}
        self._key = _derive_key(self._identity, self._salt)

    def get(self, name: str) -> str | None:
        self._validate(name)
        entry = self._entries.get(name)
        if entry is None:
            return None
        try:
            plaintext = AESGCM(self._key).decrypt(
                bytes.fromhex(entry["nonce"]),
                bytes.fromhex(entry["ciphertext"]),
                name.encode("utf-8"),
            )
        except InvalidTag as exc:
            raise CorruptSecretsError(
                f"Cannot decrypt secret {name!r}: wrong user identity or tampered file."
            ) from exc
        return plaintext.decode("utf-8")

    def set(self, name: str, value: str) -> None:
        self._validate(name)
        if not value:
            raise ValueError("Refusing to store an empty secret.")
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(
            nonce, value.encode("utf-8"), name.encode("utf-8")
        )
        self._entries[name] = {"nonce": nonce.hex(), "ciphertext": ciphertext.hex()}
        self._save()

    def delete(self, name: str) -> bool:
        self._validate(name)
        existed = name in self._entries
        self._entries.pop(name, None)
        if existed:
            self._save()
        return existed

    def purge(self, names: tuple[str, ...] = KNOWN_SECRET_NAMES) -> int:
        return sum(1 for name in names if self.delete(name))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": _FORMAT_VERSION,
            "salt": self._salt.hex(),
            "entries": self._entries,
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _validate(name: str) -> None:
        if not name or name != name.strip():
            raise ValueError(f"Invalid secret name {name!r}.")
