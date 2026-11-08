"""Rate limits and body caps tests (DCL-123, DCL-124, spec section 4).

In-process token buckets per route class, and request-body caps enforced at
the ASGI receive level BEFORE any buffering: a chunked request with no
``Content-Length`` is measured while its bytes flow, not after a parser has
buffered them. WebSocket messages are capped too: a single message over
32 KiB closes the connection with code 1009.

Security-critical tests: written (and watched fail) before the
implementation, per spec section 17. Security tests first.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.types import Message
from starlette.websockets import WebSocketDisconnect

from declaw.config import Settings
from declaw.gateway.app import create_app
from declaw.gateway.auth import SESSION_COOKIE_NAME
from declaw.gateway.middleware import (
    DEFAULT_JSON_BODY_CAP_BYTES,
    SETTINGS_PUT_BODY_CAP_BYTES,
    WS_MESSAGE_CAP_BYTES,
    BodyCapMiddleware,
    RateLimiter,
    WebSocketMessageCapMiddleware,
)

TEST_PORT = 9000  # never the default 7842 (same convention as test_host_origin.py)
BIND_AUTHORITY = f"127.0.0.1:{TEST_PORT}"
ALLOWED_ORIGIN = f"http://{BIND_AUTHORITY}"


class FakeClock:
    """Injectable ``() -> float`` clock so buckets refill without sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _settings(port: int = TEST_PORT) -> Settings:
    return Settings(_env_file=None, port=port)  # type: ignore[call-arg]


def _client() -> TestClient:
    # base_url pins the Host header to the bound authority (Task 3
    # middleware 403s the TestClient default "testserver"); POST/PUT still
    # need the explicit Origin header.
    return TestClient(create_app(_settings()), base_url=f"http://{BIND_AUTHORITY}")


def _assert_error_shape(payload: Any) -> None:
    # Binding constraint: {"error": {"code": str, "message": str}} everywhere.
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message"}
    assert isinstance(payload["error"]["code"], str)
    assert isinstance(payload["error"]["message"], str)


# --- login rate limit: 5/minute, global -------------------------------------


def test_login_rate_limited_after_five_attempts_in_a_minute() -> None:
    client = _client()

    for _ in range(5):
        response = client.post(
            "/api/auth/login", json={"token": "wrong"}, headers={"Origin": ALLOWED_ORIGIN}
        )
        # The login route exists (Task 6): a bad token is a plain 401;
        # anything but 429 proves the request passed the limiter.
        assert response.status_code == 401

    sixth = client.post(
        "/api/auth/login", json={"token": "wrong"}, headers={"Origin": ALLOWED_ORIGIN}
    )

    assert sixth.status_code == 429
    _assert_error_shape(sixth.json())
    retry_after = int(sixth.headers["Retry-After"])
    assert 1 <= retry_after <= 60


def test_login_rate_limit_is_global_not_per_session() -> None:
    # Slows token brute force from ANY local process (spec section 4):
    # ten attempts split across two session cookies still hit one bucket.
    client = _client()
    cookie_one = {"Origin": ALLOWED_ORIGIN, "Cookie": f"{SESSION_COOKIE_NAME}=s1"}
    cookie_two = {"Origin": ALLOWED_ORIGIN, "Cookie": f"{SESSION_COOKIE_NAME}=s2"}

    for _ in range(3):
        assert client.post(
            "/api/auth/login", json={"token": "wrong"}, headers=cookie_one
        ).status_code == 401
    for _ in range(2):
        assert client.post(
            "/api/auth/login", json={"token": "wrong"}, headers=cookie_two
        ).status_code == 401

    assert client.post(
        "/api/auth/login", json={"token": "wrong"}, headers=cookie_two
    ).status_code == 429


def test_login_bucket_refills_over_time() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(5):
        assert limiter.allow_login()
    assert not limiter.allow_login()
    assert 1 <= limiter.login_retry_after() <= 60

    clock.advance(12)  # 5/minute refills one token every 12 s
    assert limiter.allow_login()


# --- authenticated REST reads: 120/minute per session -------------------------


def test_rest_reads_limited_to_120_per_minute_per_session() -> None:
    client = _client()
    cookie = {"Cookie": f"{SESSION_COOKIE_NAME}=s1"}

    # The bucket refills 2 tokens/second while the loop runs, so the
    # denial point can shift a little past 120; what must hold is that
    # it arrives (bounded by 200 attempts) and that everything before it
    # reached the router.
    statuses = []
    blocked_payload: object = None
    for _ in range(200):
        response = client.get("/api/tasks", headers=cookie)
        statuses.append(response.status_code)
        if response.status_code == 429:
            blocked_payload = response.json()
            break
        assert statuses[-1] == 404

    assert statuses[-1] == 429
    assert len(statuses) > 120  # a full bucket was consumed first
    _assert_error_shape(blocked_payload)


def test_rest_read_limit_is_keyed_by_session() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(120):
        assert limiter.allow_rest_read("session-a")
    assert not limiter.allow_rest_read("session-a")
    # An independent session has its own bucket.
    assert limiter.allow_rest_read("session-b")


# --- bucket helpers for later WS wiring (Task 9) ----------------------------


def test_chat_turn_bucket_allows_ten_per_minute_per_session() -> None:
    # Exposed now; Task 9 turns a denied turn into a WS error frame.
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(10):
        assert limiter.allow_chat_turn("session-a")
    assert not limiter.allow_chat_turn("session-a")
    assert limiter.allow_chat_turn("session-b")

    clock.advance(6)  # 10/minute refills one token every 6 s
    assert limiter.allow_chat_turn("session-a")


def test_ws_message_bucket_allows_thirty_per_second_per_connection() -> None:
    # Exposed now; Task 9 turns a denied message into a WS error frame.
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)

    for _ in range(30):
        assert limiter.allow_ws_message("connection-1")
    assert not limiter.allow_ws_message("connection-1")
    assert limiter.allow_ws_message("connection-2")

    clock.advance(1.0)  # 30/second: a full second restores the bucket
    assert limiter.allow_ws_message("connection-1")


# --- body caps: 64 KiB default, 16 KiB for PUT /api/settings -----------------


def test_body_over_default_cap_is_413() -> None:
    client = _client()

    response = client.post(
        "/api/documents",
        content=b"x" * (DEFAULT_JSON_BODY_CAP_BYTES + 1),
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 413
    _assert_error_shape(response.json())


def test_body_at_default_cap_reaches_the_router() -> None:
    client = _client()

    response = client.post(
        "/api/documents",
        content=b"x" * DEFAULT_JSON_BODY_CAP_BYTES,
        headers={"Origin": ALLOWED_ORIGIN},
    )

    # Exactly at the cap passes; 404 because the route does not exist yet.
    assert response.status_code == 404


def test_settings_put_body_capped_at_16_kib() -> None:
    client = _client()

    over = client.put(
        "/api/settings",
        content=b"x" * (SETTINGS_PUT_BODY_CAP_BYTES + 1),
        headers={"Origin": ALLOWED_ORIGIN},
    )
    at_cap = client.put(
        "/api/settings",
        content=b"x" * SETTINGS_PUT_BODY_CAP_BYTES,
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert over.status_code == 413
    _assert_error_shape(over.json())
    assert at_cap.status_code == 404


def test_settings_tight_cap_applies_only_to_put_settings() -> None:
    client = _client()

    # POST to any path keeps the 64 KiB default: a body just above 16 KiB
    # passes the cap and dies at the (absent) route instead of 413.
    response = client.post(
        "/api/settings",
        content=b"x" * (SETTINGS_PUT_BODY_CAP_BYTES + 1),
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 404


# --- body caps: chunked requests with no Content-Length ---------------------


def test_body_cap_chunked_no_content_length() -> None:
    # Review Focus / M1: a chunked request with no Content-Length must hit
    # the cap while its bytes flow through receive — a route that parses
    # first and measures later has already lost (spec section 4).
    sent: list[Message] = []
    state = {"completed": False, "seen_bytes": 0}
    chunk_one = {"type": "http.request", "body": b"x" * 60_000, "more_body": True}
    chunk_two = {"type": "http.request", "body": b"x" * 10_000, "more_body": True}
    chunk_end = {"type": "http.request", "body": b"", "more_body": False}
    receive_messages = [chunk_one, chunk_two, chunk_end]

    async def receive() -> Message:
        return receive_messages.pop(0)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/documents",
        "query_string": b"",
        # Deliberately NO content-length: bytes are only measurable at
        # receive level.
        "headers": [(b"content-type", b"application/json")],
    }

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = BodyCapMiddleware(_full_body_reader_app(state))


    asyncio.run(middleware(scope, receive, send))  # type: ignore[arg-type]

    # 413 goes out while the body is still flowing; the app never finished.
    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == 413
    _assert_error_shape(json.loads(sent[1]["body"]))
    assert state["completed"] is False


def test_body_cap_chunked_within_limit_passes() -> None:
    sent: list[Message] = []
    state = {"completed": False, "seen_bytes": 0}
    chunk_one = {"type": "http.request", "body": b"x" * 30_000, "more_body": True}
    chunk_end = {"type": "http.request", "body": b"x" * 30_000, "more_body": False}
    receive_messages = [chunk_one, chunk_end]

    async def receive() -> Message:
        return receive_messages.pop(0)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/documents",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = BodyCapMiddleware(_full_body_reader_app(state))


    asyncio.run(middleware(scope, receive, send))  # type: ignore[arg-type]

    assert state["completed"] is True
    assert state["seen_bytes"] == 60_000
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 200


# --- WebSocket: single messages capped at 32 KiB -----------------------------


def test_ws_message_over_cap_closes_1009() -> None:
    # M1: a single oversized WS message is closed with 1009 (message too
    # big); rate limits alone do not bound one oversized frame.
    client = TestClient(WebSocketMessageCapMiddleware(_ws_echo_app()))

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/chat") as session:
            session.send_text("x" * (WS_MESSAGE_CAP_BYTES + 1))
            session.receive_text()

    assert exc_info.value.code == 1009


def test_ws_message_at_cap_passes() -> None:
    client = TestClient(WebSocketMessageCapMiddleware(_ws_echo_app()))

    with client.websocket_connect("/ws/chat") as session:
        session.send_text("x" * WS_MESSAGE_CAP_BYTES)
        assert session.receive_text() == "x" * WS_MESSAGE_CAP_BYTES


# --- Helpers -----------------------------------------------------------------


def _full_body_reader_app(state: dict[str, Any]) -> Any:
    # Mimics what a JSON parser does downstream: buffers the whole body
    # via receive() before responding. The 413 must pre-empt that buffer.
    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            seen += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        state["completed"] = True
        state["seen_bytes"] = seen
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


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
