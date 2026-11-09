"""Gateway auth route flow tests (DCL-121, DCL-129, spec sections 2 and 6).

End-to-end over the real ``create_app`` stack: Host/Origin and rate-limit
middleware run for every request here, so the rate-limit test proves the
Task 4 login bucket actually applies to the mounted route, not just to a
synthetic scope. The audit logger is an injected ``InMemoryAuditLogger``; the
token store is a fake so no test ever touches the real OS vault.

The no-leak test routes loguru output into ``caplog`` (the Task 2 review
handoff): the gateway token value must never appear in logs, audit payloads
or HTTP responses — only on the console printout of ``declaw start``.

Red first: this module is written before ``declaw/gateway/routes/auth.py``,
``declaw/audit/correlation.py`` and ``AuthEvent`` exist.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from loguru import logger as loguru_logger
from starlette.testclient import TestClient

from declaw.audit.events import AuthEvent
from declaw.audit.logger import InMemoryAuditLogger
from declaw.config import Settings
from declaw.credentials.store import KNOWN_SECRET_NAMES
from declaw.gateway.app import create_app
from declaw.gateway.auth import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    mint_gateway_token,
)

TEST_PORT = 9000  # never the default 7842 (same convention as test_host_origin)
BIND_AUTHORITY = f"127.0.0.1:{TEST_PORT}"
ALLOWED_ORIGIN = f"http://{BIND_AUTHORITY}"


class FakeSecretStore:
    """In-memory ``SecretStore``; no test touches the OS vault."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.data.get(name)

    def set(self, name: str, value: str) -> None:
        self.data[name] = value

    def delete(self, name: str) -> bool:
        return self.data.pop(name, None) is not None

    def purge(self, names: tuple[str, ...] = KNOWN_SECRET_NAMES) -> int:
        return sum(1 for name in names if self.delete(name))


@pytest.fixture
def store() -> FakeSecretStore:
    return FakeSecretStore()


@pytest.fixture
def audit() -> InMemoryAuditLogger:
    return InMemoryAuditLogger()


@pytest.fixture
def captured_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture loguru records into caplog (caplog only sees stdlib logging)."""
    caplog.set_level(logging.DEBUG)
    sink_logger = logging.getLogger("declaw.gateway.test_auth_flow_sink")

    def sink(message: object) -> None:
        sink_logger.debug(str(message))

    handler_id = loguru_logger.add(sink, level="DEBUG")
    try:
        yield caplog
    finally:
        loguru_logger.remove(handler_id)


def _app(store: FakeSecretStore, audit: InMemoryAuditLogger) -> Any:
    # create_app gains keyword-only injection for this task; the Settings
    # pattern is copied from tests/gateway/test_host_origin.py.
    settings = Settings(_env_file=None, port=TEST_PORT)  # type: ignore[call-arg]
    return create_app(settings, secret_store=store, audit_logger=audit)


def _client(app: Any) -> TestClient:
    # base_url sets the Host header to the bound authority so the
    # Host/Origin middleware lets the request through (spec section 3).
    return TestClient(app, base_url=f"http://{BIND_AUTHORITY}")


def _login(client: TestClient, token: str) -> Any:
    return client.post("/api/auth/login", json={"token": token}, headers={"Origin": ALLOWED_ORIGIN})


def _logout(client: TestClient) -> Any:
    return client.post("/api/auth/logout", headers={"Origin": ALLOWED_ORIGIN})


def auth_events(audit: InMemoryAuditLogger) -> list[AuthEvent]:
    return [event for event in audit.events if isinstance(event, AuthEvent)]


def _session_id_from_set_cookie(response: Any) -> str:
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    return cookie.split("=", 1)[1].split(";", 1)[0]


# --- POST /api/auth/login ------------------------------------------------------


def test_login_success_sets_session_cookie_and_audits_success(
    store: FakeSecretStore, audit: InMemoryAuditLogger
) -> None:
    app = _app(store, audit)
    token = mint_gateway_token(store)
    client = _client(app)

    response = _login(client, token)

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    session_id = _session_id_from_set_cookie(response)
    assert cookie == f"{SESSION_COOKIE_NAME}={session_id}; HttpOnly; SameSite=Strict; Path=/"
    assert app.state.session_registry.validate(session_id) is True

    [event] = auth_events(audit)
    assert event.event_type == "gateway.auth"
    assert event.action == "login_success"


def test_login_wrong_token_is_401_canonical_and_audits_failure(
    store: FakeSecretStore, audit: InMemoryAuditLogger
) -> None:
    app = _app(store, audit)
    mint_gateway_token(store)  # a real token exists; the client sends junk
    client = _client(app)

    response = _login(client, "attacker-guess")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert "message" in body["error"]
    assert "set-cookie" not in response.headers

    [event] = auth_events(audit)
    assert event.event_type == "gateway.auth"
    assert event.action == "login_failure"


def test_login_route_is_rate_limited_by_the_login_bucket(
    store: FakeSecretStore, audit: InMemoryAuditLogger
) -> None:
    # Verify the Task 4 wiring applies to the real mounted route: the
    # global bucket (5/min) sits in RateLimitMiddleware, before routing.
    app = _app(store, audit)
    mint_gateway_token(store)
    client = _client(app)

    for _ in range(5):
        assert _login(client, "wrong").status_code == 401

    sixth = _login(client, "wrong")
    assert sixth.status_code == 429
    assert int(sixth.headers["retry-after"]) >= 1
    assert sixth.json()["error"]["code"] == "rate_limited"

    # Only the five allowed attempts reached the route; the middleware
    # refused the sixth before it was audited.
    assert len(auth_events(audit)) == 5


# --- No token material anywhere (Task 2 review handoff) ------------------------


def test_login_never_leaks_token_or_session_material(
    store: FakeSecretStore, audit: InMemoryAuditLogger, captured_logs: pytest.LogCaptureFixture
) -> None:
    app = _app(store, audit)
    token = mint_gateway_token(store)
    client = _client(app)

    good = _login(client, token)
    bad = _login(client, "definitely-not-the-token")
    session_id = _session_id_from_set_cookie(good)

    assert token not in captured_logs.text
    assert token not in good.text
    assert token not in bad.text
    assert session_id not in captured_logs.text
    assert session_id not in good.json().get("status", "")

    for event in audit.events:
        dumped = str(event.model_dump(mode="json"))
        assert token not in dumped
        assert session_id not in dumped


# --- POST /api/auth/logout ------------------------------------------------------


def test_logout_drops_session_clears_cookie_and_audits(
    store: FakeSecretStore, audit: InMemoryAuditLogger
) -> None:
    app = _app(store, audit)
    token = mint_gateway_token(store)
    client = _client(app)
    logged_in = _login(client, token)
    session_id = _session_id_from_set_cookie(logged_in)

    response = _logout(client)

    assert response.status_code == 200
    assert response.headers["set-cookie"] == clear_session_cookie()
    assert app.state.session_registry.validate(session_id) is False

    [event] = [e for e in auth_events(audit) if e.action == "logout"]
    assert event.event_type == "gateway.auth"


def test_logout_without_a_session_still_clears_cookie_and_audits(
    store: FakeSecretStore, audit: InMemoryAuditLogger
) -> None:
    app = _app(store, audit)
    client = _client(app)

    response = _logout(client)

    assert response.status_code == 200
    assert response.headers["set-cookie"] == clear_session_cookie()
    assert {e.action for e in auth_events(audit)} == {"logout"}


# --- GET /api/auth/status --------------------------------------------------------


def test_status_reports_unauthenticated_without_creating_a_session(
    store: FakeSecretStore, audit: InMemoryAuditLogger
) -> None:
    app = _app(store, audit)
    client = _client(app)

    response = client.get("/api/auth/status")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    assert "set-cookie" not in response.headers


def test_status_reports_authenticated_with_a_valid_session(
    store: FakeSecretStore, audit: InMemoryAuditLogger
) -> None:
    app = _app(store, audit)
    token = mint_gateway_token(store)
    client = _client(app)
    _login(client, token)  # TestClient keeps the session cookie

    response = client.get("/api/auth/status")

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}


# --- Protected API routes reuse the session dependency (Task 11 will) ----------


def test_unauthenticated_api_access_gets_401_canonical_error(
    store: FakeSecretStore, audit: InMemoryAuditLogger
) -> None:
    app = _app(store, audit)
    token = mint_gateway_token(store)
    client = _client(app)

    # /api/settings is a real protected route (DCL-126/131): the static UI
    # mount at "/" (Task 14) answers unmatched paths, so the canonical-401
    # pin rides an actual API route instead of a post-factory probe.
    response = client.get("/api/settings")

    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthorized", "message": "Authentication required"}}

    _login(client, token)
    allowed = client.get("/api/auth/status")
    assert allowed.status_code == 200
    assert allowed.json() == {"authenticated": True}
