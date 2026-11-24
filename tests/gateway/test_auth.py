"""Gateway authentication primitives tests (DCL-121, spec section 2).

Token minting/rotation goes through a fake ``SecretStore`` so no test ever
touches the real OS vault; the registry clock is injected so the 12 h absolute
expiry is exercised without sleeping. The no-leak test routes loguru output
into ``caplog`` so the "token never logged" assertion sees every record the
product emits, loguru or stdlib.

Red first: this module is written before ``declaw/gateway/auth.py`` exists.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator

import pytest
from loguru import logger as loguru_logger

from declaw.credentials.store import KNOWN_SECRET_NAMES
from declaw.gateway.auth import (
    GATEWAY_TOKEN_NAME,
    SessionRegistry,
    clear_session_cookie,
    mint_gateway_token,
    rotate_gateway_token,
    session_cookie,
)

# secrets.token_urlsafe(32) -> 43 chars from the urlsafe alphabet.
URLSAFE_43 = re.compile(r"^[A-Za-z0-9_-]{43}$")

TWELVE_HOURS = 12 * 60 * 60


class FakeSecretStore:
    """In-memory ``SecretStore``; records every ``set`` write per name."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.set_calls: list[str] = []

    def get(self, name: str) -> str | None:
        return self.data.get(name)

    def set(self, name: str, value: str) -> None:
        self.set_calls.append(name)
        self.data[name] = value

    def delete(self, name: str) -> bool:
        return self.data.pop(name, None) is not None

    def purge(self, names: tuple[str, ...] = KNOWN_SECRET_NAMES) -> int:
        return sum(1 for name in names if self.delete(name))


@pytest.fixture
def store() -> FakeSecretStore:
    return FakeSecretStore()


@pytest.fixture
def captured_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture loguru records into caplog (caplog only sees stdlib logging)."""
    caplog.set_level(logging.DEBUG)
    sink_logger = logging.getLogger("declaw.gateway.test_sink")

    def sink(message: object) -> None:
        sink_logger.debug(str(message))

    handler_id = loguru_logger.add(sink, level="DEBUG")
    try:
        yield caplog
    finally:
        loguru_logger.remove(handler_id)


class ManualClock:
    """Callable clock the registry accepts; ``advance`` moves time forward."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# Token minting and rotation
# ---------------------------------------------------------------------------


def test_token_name_is_gateway_token() -> None:
    assert GATEWAY_TOKEN_NAME == "gateway-token"


def test_mint_stores_and_returns_43_char_urlsafe_token(store: FakeSecretStore) -> None:
    token = mint_gateway_token(store)
    assert store.get(GATEWAY_TOKEN_NAME) == token
    assert URLSAFE_43.fullmatch(token)


def test_second_mint_returns_stored_value_without_rewrite(store: FakeSecretStore) -> None:
    first = mint_gateway_token(store)
    assert store.set_calls == [GATEWAY_TOKEN_NAME]
    second = mint_gateway_token(store)
    assert second == first
    assert store.set_calls == [GATEWAY_TOKEN_NAME]  # no second write


def test_mints_are_unique_across_stores() -> None:
    assert mint_gateway_token(FakeSecretStore()) != mint_gateway_token(FakeSecretStore())


def test_rotate_replaces_stored_token(store: FakeSecretStore) -> None:
    old = mint_gateway_token(store)
    new = rotate_gateway_token(store)
    assert new != old
    assert URLSAFE_43.fullmatch(new)
    assert store.get(GATEWAY_TOKEN_NAME) == new


def test_token_and_session_material_never_logged(
    store: FakeSecretStore, captured_logs: pytest.LogCaptureFixture
) -> None:
    token = mint_gateway_token(store)
    rotated = rotate_gateway_token(store)
    registry = SessionRegistry()
    session_id = registry.create()
    assert registry.validate(session_id) is True
    registry.drop(session_id)
    clear_session_cookie()
    log_text = captured_logs.text
    assert token not in log_text
    assert rotated not in log_text
    assert session_id not in log_text


# ---------------------------------------------------------------------------
# SessionRegistry
# ---------------------------------------------------------------------------


def test_registry_create_returns_opaque_urlsafe_id() -> None:
    session_id = SessionRegistry().create()
    assert URLSAFE_43.fullmatch(session_id)


def test_registry_validates_fresh_session() -> None:
    registry = SessionRegistry()
    session_id = registry.create()
    assert registry.validate(session_id) is True


def test_registry_rejects_unknown_session_id() -> None:
    assert SessionRegistry().validate("attacker-guess") is False


def test_registry_expiry_is_absolute_12_hours() -> None:
    clock = ManualClock()
    registry = SessionRegistry(clock=clock)
    session_id = registry.create()
    clock.advance(TWELVE_HOURS - 1)
    assert registry.validate(session_id) is True
    clock.advance(2)  # now past the 12 h mark
    assert registry.validate(session_id) is False


def test_registry_expiry_is_not_sliding() -> None:
    clock = ManualClock()
    registry = SessionRegistry(clock=clock)
    session_id = registry.create()
    clock.advance(TWELVE_HOURS - 60)
    assert registry.validate(session_id) is True  # activity close to the limit
    clock.advance(120)  # must still die at the original 12 h mark
    assert registry.validate(session_id) is False


def test_registry_drop_invalidates_session() -> None:
    registry = SessionRegistry()
    session_id = registry.create()
    registry.drop(session_id)
    assert registry.validate(session_id) is False


def test_registry_drop_unknown_is_silent_noop() -> None:
    registry = SessionRegistry()
    registry.drop("never-existed")  # must not raise


def test_registry_ids_are_unique_per_create() -> None:
    registry = SessionRegistry()
    ids = {registry.create() for _ in range(8)}
    assert len(ids) == 8


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def test_session_cookie_exact_format() -> None:
    assert session_cookie("abc123") == "declaw_session=abc123; HttpOnly; SameSite=Strict; Path=/"


def test_clear_cookie_blanks_value_and_expires_it() -> None:
    cookie = clear_session_cookie()
    assert cookie.startswith("declaw_session=")
    assert "Max-Age=0" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie  # plain HTTP loopback (spec section 2.4)


def test_session_cookie_has_no_secure_flag() -> None:
    assert "Secure" not in session_cookie("xyz")
