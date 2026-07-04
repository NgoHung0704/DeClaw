"""Tests for the encrypted-file secrets fallback (DCL-074).

Acceptance: fallback path documented (see module docstring) + covered by
tests. The identity seam makes key derivation deterministic per test.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import keyring
import keyring.backends.fail
import pytest

from declaw.credentials.fallback import (
    CorruptSecretsError,
    EncryptedFileCredentialStore,
)
from declaw.credentials.store import (
    CredentialStore,
    default_credential_store,
)
from tests.unit.test_credentials_store import InMemoryKeyring

IDENTITY = "avocat@cabinet-pc"


@pytest.fixture
def store(tmp_path: Path) -> EncryptedFileCredentialStore:
    return EncryptedFileCredentialStore(tmp_path / "secrets.enc.json", identity=IDENTITY)


def test_set_get_roundtrip(store: EncryptedFileCredentialStore) -> None:
    store.set("memory-fernet-key", "super-secret-key-material")
    assert store.get("memory-fernet-key") == "super-secret-key-material"


def test_get_missing_returns_none(store: EncryptedFileCredentialStore) -> None:
    assert store.get("never-stored") is None


def test_file_never_contains_plaintext(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc.json"
    store = EncryptedFileCredentialStore(path, identity=IDENTITY)
    store.set("token", "PLAINTEXT-MARKER-1234")
    blob = path.read_bytes()
    assert b"PLAINTEXT-MARKER-1234" not in blob  # Principle #1


def test_persists_across_instances_same_identity(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc.json"
    EncryptedFileCredentialStore(path, identity=IDENTITY).set("token", "value")
    reopened = EncryptedFileCredentialStore(path, identity=IDENTITY)
    assert reopened.get("token") == "value"


def test_wrong_identity_cannot_decrypt(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc.json"
    EncryptedFileCredentialStore(path, identity=IDENTITY).set("token", "value")
    intruder = EncryptedFileCredentialStore(path, identity="other@machine")
    with pytest.raises(CorruptSecretsError):
        intruder.get("token")


def test_tampered_ciphertext_is_loud(tmp_path: Path) -> None:
    path = tmp_path / "secrets.enc.json"
    store = EncryptedFileCredentialStore(path, identity=IDENTITY)
    store.set("token", "value")
    tampered = path.read_text(encoding="utf-8").replace(
        '"ciphertext": "', '"ciphertext": "00'
    )
    path.write_text(tampered, encoding="utf-8")
    reopened = EncryptedFileCredentialStore(path, identity=IDENTITY)
    with pytest.raises(CorruptSecretsError):
        reopened.get("token")


def test_delete_and_purge(store: EncryptedFileCredentialStore) -> None:
    store.set("memory-fernet-key", "x")
    assert store.delete("memory-fernet-key") is True
    assert store.delete("memory-fernet-key") is False
    store.set("memory-fernet-key", "y")
    assert store.purge() == 1
    assert store.get("memory-fernet-key") is None


def test_empty_value_rejected(store: EncryptedFileCredentialStore) -> None:
    with pytest.raises(ValueError):
        store.set("token", "")


# --- default_credential_store routing ----------------------------------------------


@pytest.fixture
def restore_keyring() -> Iterator[None]:
    previous = keyring.get_keyring()
    try:
        yield
    finally:
        keyring.set_keyring(previous)


def test_factory_uses_vault_when_available(restore_keyring: None) -> None:
    keyring.set_keyring(InMemoryKeyring())
    assert isinstance(default_credential_store(), CredentialStore)


def test_factory_falls_back_when_keyring_missing(
    restore_keyring: None, tmp_path: Path
) -> None:
    keyring.set_keyring(keyring.backends.fail.Keyring())
    store = default_credential_store(tmp_path / "secrets.enc.json")
    assert isinstance(store, EncryptedFileCredentialStore)
    store.set("token", "works-without-a-vault")
    assert store.get("token") == "works-without-a-vault"
