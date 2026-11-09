"""Host/Origin policy middleware tests (DCL-122, spec section 3).

Fail-closed defense against CSRF and DNS rebinding: the Host header must
exactly match the bound authority, and every non-GET/HEAD request plus
every WebSocket handshake must carry ``Origin: http://127.0.0.1:<port>``.
Rejected WebSocket handshakes close with code 4403 before the wrapped
application sees anything.

Security-critical tests were written (and watched fail) before the
implementation, per spec section 17.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.types import Message
from starlette.websockets import WebSocketDisconnect

from declaw.config import Settings
from declaw.gateway.app import create_app
from declaw.gateway.middleware import HostOriginMiddleware

TEST_PORT = 9000  # never the default 7842: proves the allowlist is derived
BIND_AUTHORITY = f"127.0.0.1:{TEST_PORT}"
ALLOWED_ORIGIN = f"http://{BIND_AUTHORITY}"


def _settings(port: int = TEST_PORT) -> Settings:
    # ``_env_file=None`` skips ``.env`` lookup so tests do not depend on the
    # developer's CWD (same pattern as tests/gateway/test_launch.py).
    return Settings(_env_file=None, port=port)  # type: ignore[call-arg]


def _client(port: int = TEST_PORT) -> TestClient:
    return TestClient(create_app(_settings(port)))


# --- Host: exact match of the bound authority --------------------------------


def test_foreign_host_is_forbidden() -> None:
    response = _client().get("/", headers={"Host": "evil.example"})

    assert response.status_code == 403


def test_bound_host_passes_get() -> None:
    response = _client().get("/healthz", headers={"Host": BIND_AUTHORITY})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_host_allowlist_follows_actual_port() -> None:
    # Review Focus item: the allowlist derives from the actual bind
    # authority, never a hard-coded 7842.
    client = _client(port=TEST_PORT)

    actual_host = client.get("/", headers={"Host": f"127.0.0.1:{TEST_PORT}"})
    default_port_host = client.get("/", headers={"Host": "127.0.0.1:7842"})

    assert actual_host.status_code == 200
    assert default_port_host.status_code == 403


def test_missing_host_header_on_http11_is_forbidden() -> None:
    # Raw ASGI call: the TestClient transport always sends a Host header,
    # but HTTP/1.1 clients without one must be rejected too.
    sent: list[Message] = []
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],  # no Host at all
    }
    middleware = HostOriginMiddleware(_must_not_be_reached(), BIND_AUTHORITY)

    asyncio.run(
        middleware(
            scope,  # type: ignore[arg-type]
            _receive_nothing,
            _recording_send(sent),
        )
    )

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 403


# --- Origin: required on non-GET/HEAD, fail closed ---------------------------


def test_post_without_origin_is_forbidden() -> None:
    response = _client().post("/api/nothing", headers={"Host": BIND_AUTHORITY})

    assert response.status_code == 403


def test_post_with_foreign_origin_is_forbidden() -> None:
    response = _client().post(
        "/api/nothing",
        headers={"Host": BIND_AUTHORITY, "Origin": "http://evil.example"},
    )

    assert response.status_code == 403


def test_post_with_null_origin_is_forbidden() -> None:
    response = _client().post(
        "/api/nothing",
        headers={"Host": BIND_AUTHORITY, "Origin": "null"},
    )

    assert response.status_code == 403


def test_post_with_bound_origin_passes_policy() -> None:
    # No POST route matches; with the static UI mount at "/") unmatched
    # paths reach it and answer 405 Method Not Allowed. Anything but 403
    # proves the request got past the policy.
    response = _client().post(
        "/api/nothing",
        headers={"Host": BIND_AUTHORITY, "Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 405


def test_get_origin_exempt() -> None:
    # GET carries no Origin header in the first place; read-only requests
    # stay exempt (SameSite=Strict covers credentialed reads).
    response = _client().get("/", headers={"Host": BIND_AUTHORITY})

    assert response.status_code == 200


def test_head_origin_exempt() -> None:
    response = _client().head("/", headers={"Host": BIND_AUTHORITY})

    # 200 because the static UI mount answers HEAD at the root; the point
    # is that the policy did not reject the Origin-less HEAD request.
    assert response.status_code == 200


# --- WebSocket: handshake checks close with 4403 ----------------------------


def test_ws_handshake_foreign_origin_closes_4403() -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with _client().websocket_connect(
            "/ws/chat",
            headers={"Host": BIND_AUTHORITY, "Origin": "http://evil.example"},
        ) as session:
            session.receive_text()

    assert exc_info.value.code == 4403


def test_ws_handshake_missing_origin_closes_4403() -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with _client().websocket_connect(
            "/ws/chat", headers={"Host": BIND_AUTHORITY}
        ) as session:
            session.receive_text()

    assert exc_info.value.code == 4403


def test_ws_handshake_wrong_host_closes_4403() -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with _client().websocket_connect(
            "/ws/chat",
            headers={"Host": "127.0.0.1:7842", "Origin": ALLOWED_ORIGIN},
        ) as session:
            session.receive_text()

    assert exc_info.value.code == 4403


def test_ws_rejection_closes_before_any_application_message() -> None:
    # Raw ASGI: the wrapped application must never be reached, and the only
    # outbound message is the close frame with code 4403 (no accept).
    sent: list[Message] = []
    scope: dict[str, Any] = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": "/ws/chat",
        "query_string": b"",
        "headers": [(b"host", BIND_AUTHORITY.encode()), (b"origin", b"http://evil.example")],
    }
    middleware = HostOriginMiddleware(_must_not_be_reached(), BIND_AUTHORITY)

    asyncio.run(
        middleware(
            scope,  # type: ignore[arg-type]
            _receive_nothing,
            _recording_send(sent),
        )
    )

    assert sent == [
        {"type": "websocket.close", "code": 4403, "reason": "Forbidden Host or Origin"}
    ]


def test_ws_valid_handshake_reaches_application() -> None:
    # A tiny pure-ASGI echo app wrapped directly: a valid Host+Origin pair
    # must reach it (create_app has no WS route yet).
    client = TestClient(HostOriginMiddleware(_ws_echo_app(), BIND_AUTHORITY))

    with client.websocket_connect(
        "/ws/chat", headers={"Host": BIND_AUTHORITY, "Origin": ALLOWED_ORIGIN}
    ) as session:
        session.send_text("hello")
        assert session.receive_text() == "hello"


# --- Helpers ----------------------------------------------------------------


def _must_not_be_reached() -> Any:
    async def unreachable_app(scope: Any, receive: Any, send: Any) -> None:
        raise AssertionError("request must be rejected before reaching the app")

    return unreachable_app


async def _receive_nothing() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def _recording_send(sent: list[Message]) -> Any:
    async def send(message: Message) -> None:
        sent.append(message)

    return send


def _ws_echo_app() -> Any:
    async def echo(scope: Any, receive: Any, send: Any) -> None:
        await receive()  # consume the "websocket.connect" handshake event
        await send({"type": "websocket.accept"})
        while True:
            message = await receive()
            if message["type"] == "websocket.disconnect":
                break
            await send({"type": "websocket.send", "text": message.get("text", "")})

    return echo
