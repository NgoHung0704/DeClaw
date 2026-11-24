"""Gateway authentication primitives (DCL-121, spec section 2).

Paste-once login bootstrap: a long-lived gateway token stored in the OS
vault (never in the browser, logs, audit events or HTTP responses) is
exchanged at login for a short-lived opaque session cookie.

These are the pure primitives; the login/logout/status routes (later
ticket) consume them. Kept free of I/O besides the ``SecretStore`` calls so
the security-sensitive parts stay unit-testable.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable

from declaw.credentials.store import SecretStore

GATEWAY_TOKEN_NAME = "gateway-token"

SESSION_COOKIE_NAME = "declaw_session"
SESSION_TTL_SECONDS = 12 * 60 * 60  # absolute, not sliding (spec section 2)


def mint_gateway_token(store: SecretStore) -> str:
    """Return the gateway token, creating it on first call (create-or-get).

    The second and later calls return the stored value untouched: the
    launcher prints the same token on every ``declaw start``. The token is
    ``secrets.token_urlsafe(32)`` — 43 urlsafe characters.
    """
    existing = store.get(GATEWAY_TOKEN_NAME)
    if existing is not None:
        return existing
    token = secrets.token_urlsafe(32)
    store.set(GATEWAY_TOKEN_NAME, token)
    return token


def rotate_gateway_token(store: SecretStore) -> str:
    """Replace the stored gateway token (``declaw start --rotate-token``).

    Callers invalidate live sessions themselves; the registry is process
    state and rotation here only concerns the vault entry.
    """
    token = secrets.token_urlsafe(32)
    store.set(GATEWAY_TOKEN_NAME, token)
    return token


class SessionRegistry:
    """In-memory session id -> absolute-expiry map.

    ``clock`` is a ``() -> float`` seconds callable, injectable so tests
    cross the 12 h boundary without sleeping. Expiry is ABSOLUTE from
    creation; validating a session never extends its lifetime.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.time
        self._expiry: dict[str, float] = {}

    def create(self) -> str:
        """Mint an opaque session id and register it for 12 h."""
        session_id = secrets.token_urlsafe(32)
        self._expiry[session_id] = self._clock() + SESSION_TTL_SECONDS
        return session_id

    def validate(self, session_id: str) -> bool:
        """True iff the id is registered and its absolute expiry not passed.

        Expired entries are dropped on sight so they cannot accumulate.
        Unknown ids are simply rejected — constant behavior both sides,
        and no information about live ids leaks through timing.
        """
        expiry = self._expiry.get(session_id)
        if expiry is None:
            return False
        if self._clock() >= expiry:
            del self._expiry[session_id]
            return False
        return True

    def drop(self, session_id: str) -> None:
        """Invalidate a session (logout). Idempotent for unknown ids."""
        self._expiry.pop(session_id, None)


def session_cookie(session_id: str) -> str:
    """``Set-Cookie`` value for a logged-in session.

    Deliberately no ``Secure`` flag: the gateway is plain HTTP on loopback
    (spec section 2.4). ``SameSite=Strict`` carries the CSRF burden together
    with the Origin/Host middleware.
    """
    return f"{SESSION_COOKIE_NAME}={session_id}; HttpOnly; SameSite=Strict; Path=/"


def clear_session_cookie() -> str:
    """``Set-Cookie`` value that blanks and expires the session cookie."""
    return f"{SESSION_COOKIE_NAME}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
