"""Tests for the keyring wrapper (DCL-070).

A fake in-memory keyring backend is installed for every test, so no test ever
touches the real OS vault (and CI needs no credential manager).
"""

from __future__ import annotations

from collections.abc import Iterator

import keyring
import keyring.backend
import keyring.errors
import pytest

from declaw.credentials.store import KNOWN_SECRET_NAMES, CredentialStore


class InMemoryKeyring(keyring.backend.KeyringBackend):
    """Volatile keyring backend for tests."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.data:
            raise keyring.errors.PasswordDeleteError(username)
        del self.data[(service, username)]


@pytest.fixture
def fake_keyring() -> Iterator[InMemoryKeyring]:
    previous = keyring.get_keyring()
    fake = InMemoryKeyring()
    keyring.set_keyring(fake)
    try:
        yield fake
    finally:
        keyring.set_keyring(previous)


def test_set_get_roundtrip(fake_keyring: InMemoryKeyring) -> None:
    store = CredentialStore()
    store.set("api-token", "s3cret")
    assert store.get("api-token") == "s3cret"


def test_get_missing_returns_none(fake_keyring: InMemoryKeyring) -> None:
    assert CredentialStore().get("never-stored") is None


def test_secrets_are_namespaced_under_declaw_service(fake_keyring: InMemoryKeyring) -> None:
    CredentialStore().set("token", "value")
    assert ("declaw", "token") in fake_keyring.data


def test_delete_is_idempotent(fake_keyring: InMemoryKeyring) -> None:
    store = CredentialStore()
    store.set("token", "value")
    assert store.delete("token") is True
    assert store.delete("token") is False  # second delete: no error, reports absent
    assert store.get("token") is None


def test_purge_removes_known_secrets(fake_keyring: InMemoryKeyring) -> None:
    store = CredentialStore()
    for name in KNOWN_SECRET_NAMES:
        store.set(name, "x")
    removed = store.purge()
    assert removed == len(KNOWN_SECRET_NAMES)
    assert all(store.get(name) is None for name in KNOWN_SECRET_NAMES)


def test_empty_secret_value_rejected(fake_keyring: InMemoryKeyring) -> None:
    with pytest.raises(ValueError):
        CredentialStore().set("token", "")


def test_bad_names_rejected(fake_keyring: InMemoryKeyring) -> None:
    store = CredentialStore()
    for bad in ("", " padded "):
        with pytest.raises(ValueError):
            store.get(bad)


def test_distinct_services_are_isolated(fake_keyring: InMemoryKeyring) -> None:
    CredentialStore("declaw").set("token", "a")
    other = CredentialStore("declaw-test")
    assert other.get("token") is None
