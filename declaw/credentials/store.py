"""python-keyring wrapper (DCL-070).

Inviolable Principle #1: credentials are NEVER stored in plaintext. Every
secret DeClaw holds goes through this wrapper into the OS credential vault
(Windows Credential Manager on the primary target; Keychain / SecretService
elsewhere — python-keyring picks the platform backend).

Design notes:

* Secrets live under the ``declaw`` service namespace so they are clearly
  attributable in the OS vault and can be purged on uninstall.
* Keyring backends cannot enumerate stored entries, so the uninstaller story
  (DCL-235) needs a known-names list: ``KNOWN_SECRET_NAMES`` is the single
  auditable registry of every secret DeClaw may have created. Add to it when
  a ticket introduces a new secret.
* ``delete`` is idempotent — purging a machine that never stored a given
  secret must not fail halfway.
* The encrypted-file fallback for keyring-less systems is DCL-074 (later).
"""

from __future__ import annotations

import keyring
import keyring.errors

SERVICE_NAME = "declaw"

# Every secret name DeClaw may create, in one place, so `purge()` (and the
# Phase 14 uninstaller) can remove all of them without backend enumeration.
KNOWN_SECRET_NAMES: tuple[str, ...] = (
    "memory-fernet-key",  # DCL-051: at-rest encryption of vector memory
)


class CredentialStore:
    """Namespaced CRUD over the OS credential vault."""

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self._service = service

    @property
    def service(self) -> str:
        return self._service

    def get(self, name: str) -> str | None:
        """Return the secret named ``name`` or None if absent."""
        self._validate(name)
        return keyring.get_password(self._service, name)

    def set(self, name: str, value: str) -> None:
        """Store ``value`` under ``name`` (overwrites)."""
        self._validate(name)
        if not value:
            raise ValueError("Refusing to store an empty secret.")
        keyring.set_password(self._service, name, value)

    def delete(self, name: str) -> bool:
        """Delete ``name`` if present. Returns True if something was removed."""
        self._validate(name)
        try:
            keyring.delete_password(self._service, name)
        except keyring.errors.PasswordDeleteError:
            return False
        return True

    def purge(self, names: tuple[str, ...] = KNOWN_SECRET_NAMES) -> int:
        """Delete every secret in ``names``; returns how many existed.

        This is the uninstaller hook (DCL-235: "uninstaller removes secrets").
        """
        return sum(1 for name in names if self.delete(name))

    @staticmethod
    def _validate(name: str) -> None:
        if not name or name != name.strip():
            raise ValueError(f"Invalid secret name {name!r}.")
