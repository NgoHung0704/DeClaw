"""At-rest encryption for vector memory (DCL-051).

Chroma persists its data as SQLite + binary segment files under
``data_dir/chroma``. DeClaw encrypts the *document text* (and any sensitive
metadata the caller passes through ``encrypt_text``) with Fernet **before** it
reaches Chroma, so those files never contain client plaintext. The key lives
in the OS credential vault via :class:`CredentialStore` (DCL-070) — never on
disk (Principle #1).

Honest scope note: the embedding vectors themselves are NOT encrypted —
Chroma must compare them to search. Embedding-inversion attacks can
approximately reconstruct text from vectors, so the at-rest guarantee is
"documents unreadable without the key", not "zero information in the files".
Recorded as a Phase 12 hardening consideration.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from declaw.credentials.store import CredentialStore

FERNET_KEY_NAME = "memory-fernet-key"


def get_or_create_fernet(store: CredentialStore | None = None) -> Fernet:
    """Return the memory Fernet, creating + vaulting the key on first use."""
    store = store if store is not None else CredentialStore()
    key = store.get(FERNET_KEY_NAME)
    if key is None:
        key = Fernet.generate_key().decode("ascii")
        store.set(FERNET_KEY_NAME, key)
    return Fernet(key.encode("ascii"))


def encrypt_text(fernet: Fernet, text: str) -> str:
    """Encrypt ``text`` to an ASCII Fernet token (safe to store anywhere)."""
    return fernet.encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_text(fernet: Fernet, token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_text`.

    Raises ``cryptography.fernet.InvalidToken`` on a wrong key or tampered
    ciphertext — corruption must be loud.
    """
    return fernet.decrypt(token.encode("ascii")).decode("utf-8")
