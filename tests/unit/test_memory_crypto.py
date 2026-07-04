"""Tests for memory at-rest encryption (DCL-051).

Acceptance: raw files unreadable without key. The headline test writes an
encrypted document through the real Chroma persistent client and scans every
byte Chroma wrote for the plaintext marker.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from cryptography.fernet import Fernet, InvalidToken

from declaw.credentials.store import CredentialStore
from declaw.memory.chroma import build_chroma_client, get_collection
from declaw.memory.crypto import (
    FERNET_KEY_NAME,
    decrypt_text,
    encrypt_text,
    get_or_create_fernet,
)
from tests.unit.test_credentials_store import InMemoryKeyring


@pytest.fixture
def fake_keyring() -> Iterator[InMemoryKeyring]:
    previous = keyring.get_keyring()
    fake = InMemoryKeyring()
    keyring.set_keyring(fake)
    try:
        yield fake
    finally:
        keyring.set_keyring(previous)


def test_roundtrip() -> None:
    fernet = Fernet(Fernet.generate_key())
    token = encrypt_text(fernet, "Dossier Dupont — clause de non-concurrence")
    assert decrypt_text(fernet, token) == "Dossier Dupont — clause de non-concurrence"


def test_ciphertext_does_not_contain_plaintext() -> None:
    fernet = Fernet(Fernet.generate_key())
    token = encrypt_text(fernet, "TOP-SECRET-MARKER")
    assert "TOP-SECRET-MARKER" not in token


def test_key_created_once_and_reused(fake_keyring: InMemoryKeyring) -> None:
    store = CredentialStore()
    first = get_or_create_fernet(store)
    stored_key = store.get(FERNET_KEY_NAME)
    assert stored_key is not None

    second = get_or_create_fernet(store)
    token = encrypt_text(first, "hello")
    assert decrypt_text(second, token) == "hello"  # same key both times
    assert store.get(FERNET_KEY_NAME) == stored_key


def test_wrong_key_raises_invalid_token() -> None:
    token = encrypt_text(Fernet(Fernet.generate_key()), "hello")
    other = Fernet(Fernet.generate_key())
    with pytest.raises(InvalidToken):
        decrypt_text(other, token)


def test_chroma_files_unreadable_without_key(tmp_path: Path) -> None:
    """The DCL-051 acceptance: no plaintext in anything Chroma persists."""
    marker = "CONFIDENTIAL-CLIENT-FACT-8842"
    fernet = Fernet(Fernet.generate_key())

    persist_dir = tmp_path / "chroma"
    client = build_chroma_client(persist_dir)
    collection = get_collection(client, "semantic")
    collection.add(
        ids=["doc-1"],
        embeddings=[[0.5, 0.5]],
        documents=[encrypt_text(fernet, f"The fact is {marker}.")],
    )
    del collection, client

    marker_bytes = marker.encode("utf-8")
    files = [p for p in persist_dir.rglob("*") if p.is_file()]
    assert files, "chroma persisted nothing?"
    for file in files:
        assert marker_bytes not in file.read_bytes(), f"plaintext leaked into {file}"

    # And with the key, the document is recoverable.
    reopened = get_collection(build_chroma_client(persist_dir), "semantic")
    got = reopened.get(ids=["doc-1"])
    assert got["documents"] is not None
    assert marker in decrypt_text(fernet, got["documents"][0])
