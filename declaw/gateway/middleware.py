"""Gateway pure-ASGI middleware (DCL-122/123/124, spec sections 3-4).

Three fail-closed defenses run before routing, wrapping every future
route:

- Host/Origin policy (DCL-122, spec section 3): fail-closed defense
  against CSRF and DNS rebinding (CVE-2026-25253 class). See the
  ``HostOriginMiddleware`` docstring for the exact rules.
- Rate limits (DCL-123, spec section 4): in-process token buckets, per
  route class, keyed by session (and globally for unauthenticated
  endpoints).
- Body caps (DCL-124, spec section 4): request bodies capped at
  64 KiB (16 KiB for ``PUT /api/settings``), counted at ASGI receive
  level BEFORE any buffering — including chunked requests with no
  ``Content-Length``. A route that parses first and measures later has
  already lost. WebSocket messages are capped too: a single message
  over 32 KiB closes the connection with code 1009.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from declaw.gateway.auth import SESSION_COOKIE_NAME

_WS_FORBIDDEN_CLOSE_CODE = 4403  # forbidden Origin/Host (spec section 3)
_WS_FORBIDDEN_CLOSE_REASON = "Forbidden Host or Origin"

# Rate limits and body caps (DCL-123, DCL-124, spec section 4).
#
# All constants live here, in one place, mirroring the spec section 4
# table (the WS message cap is folded in from the same section):
#
# | Scope                           | Limit                  | Response on exceed       |
# | ------------------------------- | ---------------------- | ------------------------ |
# | POST /api/auth/login            | 5/minute (global)     | 429 + Retry-After        |
# | Chat turn start (/ws/chat)     | 10/minute per session  | WS error frame (Task 9)  |
# | Other WS messages               | 30/second per conn.    | WS error frame (Task 9)  |
# | Authenticated REST reads       | 120/minute per session | 429                      |
# | Default JSON body               | 64 KiB                 | 413                      |
# | PUT /api/settings               | 16 KiB                 | 413                      |
# | Single WS message               | 32 KiB                 | close 1009               |
#
# There are no large legitimate bodies in this API: documents are
# indexed from disk, never uploaded (spec section 4 non-goal). A future
# route needing a bigger cap gets an explicit per-route override here.
LOGIN_BUCKET_CAPACITY = 5  # POST /api/auth/login, global (slows brute force)
LOGIN_REFILLS_PER_SECOND = 5.0 / 60.0
CHAT_TURN_BUCKET_CAPACITY = 10  # chat turn starts, per session
CHAT_TURN_REFILLS_PER_SECOND = 10.0 / 60.0
WS_MESSAGE_BUCKET_CAPACITY = 30  # other WS messages, per connection
WS_MESSAGE_REFILLS_PER_SECOND = 30.0
REST_READ_BUCKET_CAPACITY = 120  # authenticated REST reads, per session
REST_READ_REFILLS_PER_SECOND = 120.0 / 60.0

DEFAULT_JSON_BODY_CAP_BYTES = 64 * 1024
SETTINGS_PUT_BODY_CAP_BYTES = 16 * 1024
WS_MESSAGE_CAP_BYTES = 32 * 1024

_WS_MESSAGE_TOO_BIG_CLOSE_CODE = 1009  # message too big (spec section 4)
_WS_MESSAGE_TOO_BIG_CLOSE_REASON = "Message too big"

_RATE_LIMIT_ERROR_CODE = "rate_limited"
_BODY_TOO_LARGE_ERROR_CODE = "payload_too_large"


class SecurityHeadersMiddleware:
    """Strict content-security policy + nosniff on EVERY response (spec 13).

    Installed OUTERMOST so even a 403 from the Host/Origin policy carries
    the headers. The CSP's ``connect-src`` WebSocket authority is derived
    from the actual bind authority (the port is configurable — never a
    hard-coded 7842): same-source scripts and styles only, no inline
    executable or styling surface anywhere in the markup.
    """

    def __init__(self, app: ASGIApp, bind_authority: str) -> None:
        self.app = app
        self._csp = (
            "default-src 'self'; "
            f"connect-src 'self' ws://{bind_authority}; "
            "img-src 'self' data:; "
            "style-src 'self'; "
            "script-src 'self'; "
            "frame-ancestors 'none'"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["content-security-policy"] = self._csp
                headers["x-content-type-options"] = "nosniff"
            await send(message)

        await self.app(scope, receive, send_with_headers)



def _header(scope: Scope, name: bytes) -> str | None:
    """Return the (latin-1 decoded) value of a header, or None if absent.

    ASGI header names arrive lowercased; decoding is latin-1 so
    arbitrary bytes can never raise and turn a rejection into a 500.
    """
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for key, value in headers:
        if key == name:
            return value.decode("latin-1")
    return None


class HostOriginMiddleware:
    """Pure-ASGI Host/Origin gate; installed before routing in create_app."""

    def __init__(self, app: ASGIApp, bind_authority: str) -> None:
        self.app = app
        # Exact strings only: no normalization, no wildcard, fail closed.
        self._host_authority = bind_authority
        self._allowed_origin = f"http://{bind_authority}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type == "http":
            await self._handle_http(scope, receive, send)
        elif scope_type == "websocket":
            await self._handle_websocket(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    async def _handle_http(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if not self._host_allowed(scope):
            await self._forbid_http(send, "Host header does not match the bound authority")
            return
        if scope["method"] not in ("GET", "HEAD") and not self._origin_allowed(scope):
            await self._forbid_http(send, "Missing or forbidden Origin header")
            return
        await self.app(scope, receive, send)

    async def _handle_websocket(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        # Both checks run on the handshake, whatever the subprotocol.
        if self._host_allowed(scope) and self._origin_allowed(scope):
            await self.app(scope, receive, send)
            return
        # Reject before accept so the client sees the close code and the
        # wrapped application never observes the handshake.
        await send(
            {
                "type": "websocket.close",
                "code": _WS_FORBIDDEN_CLOSE_CODE,
                "reason": _WS_FORBIDDEN_CLOSE_REASON,
            }
        )

    def _host_allowed(self, scope: Scope) -> bool:
        host = _header(scope, b"host")
        # Missing Host (possible on HTTP/1.1 with raw clients) fails closed.
        return host is not None and host == self._host_authority

    def _origin_allowed(self, scope: Scope) -> bool:
        origin = _header(scope, b"origin")
        # Missing or "null" Origin both differ from the allowed value, so a
        # single exact comparison rejects them (fail closed).
        return origin is not None and origin == self._allowed_origin

    async def _forbid_http(self, send: Send, detail: str) -> None:
        body = f'{{"detail": "{detail}"}}'.encode("ascii")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# --- Error responses (spec section 9: {"error": {"code", "message"}}) -------


async def _http_error_response(
    send: Send,
    status: int,
    code: str,
    message: str,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """Emit the canonical gateway error JSON with the given status."""
    body = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send(
        {"type": "http.response.start", "status": status, "headers": headers}
    )
    await send({"type": "http.response.body", "body": body})


# --- Token buckets (DCL-123, spec section 4) --------------------------------


class TokenBucket:
    """Classic in-process token bucket.

    ``capacity`` tokens max; ``refill_per_second`` tokens flow back per
    second. ``clock`` is a ``() -> float`` seconds callable, injectable
    so tests cross window boundaries without sleeping. Monotonic by
    default: a wall-clock jump must never refill a brute-force bucket.
    """

    def __init__(
        self,
        capacity: float,
        refill_per_second: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._capacity = capacity
        self._refill_per_second = refill_per_second
        self._clock = clock if clock is not None else time.monotonic
        self._tokens = float(capacity)
        self._last_refill = self._clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(
                self._capacity, self._tokens + elapsed * self._refill_per_second
            )
            self._last_refill = now

    def try_consume(self, tokens: float = 1.0) -> bool:
        """Consume ``tokens`` if available; False when over the limit."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def retry_after_seconds(self, tokens: float = 1.0) -> int:
        """Whole seconds until ``tokens`` are available again (>= 1)."""
        self._refill()
        if self._tokens >= tokens:
            return 0
        missing = tokens - self._tokens
        return max(1, math.ceil(missing / self._refill_per_second))


class RateLimiter:
    """The spec section 4 table as executable state.

    One global bucket for the login route, and lazily created per-key
    buckets (session id / connection key) for the scoped limits. Buckets
    live for the process lifetime; a later ticket ties their eviction to
    session drop when sessions are wired end to end.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.monotonic
        self._login_bucket = TokenBucket(
            LOGIN_BUCKET_CAPACITY, LOGIN_REFILLS_PER_SECOND, clock=self._clock
        )
        self._rest_read_buckets: dict[str, TokenBucket] = {}
        self._chat_turn_buckets: dict[str, TokenBucket] = {}
        self._ws_message_buckets: dict[str, TokenBucket] = {}

    def _scoped_bucket(
        self,
        store: dict[str, TokenBucket],
        key: str,
        capacity: float,
        refill_per_second: float,
    ) -> TokenBucket:
        bucket = store.get(key)
        if bucket is None:
            bucket = TokenBucket(capacity, refill_per_second, clock=self._clock)
            store[key] = bucket
        return bucket

    def allow_login(self) -> bool:
        """Global POST /api/auth/login bucket (5/minute)."""
        return self._login_bucket.try_consume()

    def login_retry_after(self) -> int:
        """Seconds until the next login attempt may proceed."""
        return self._login_bucket.retry_after_seconds()

    def allow_rest_read(self, session_id: str) -> bool:
        """Authenticated REST reads: 120/minute per session."""
        return (
            self._scoped_bucket(
                self._rest_read_buckets,
                session_id,
                REST_READ_BUCKET_CAPACITY,
                REST_READ_REFILLS_PER_SECOND,
            ).try_consume()
        )

    def allow_chat_turn(self, session_id: str) -> bool:
        """Chat turn starts: 10/minute per session.

        Exposed now per the milestone; Task 9 turns a denied turn into
        the WS error frame (rate limits themselves do not need the
        frame wiring to be correct here).
        """
        return (
            self._scoped_bucket(
                self._chat_turn_buckets,
                session_id,
                CHAT_TURN_BUCKET_CAPACITY,
                CHAT_TURN_REFILLS_PER_SECOND,
            ).try_consume()
        )

    def allow_ws_message(self, connection_key: str) -> bool:
        """Other WS messages: 30/second per connection.

        Exposed now per the milestone; Task 9 turns a denied message
        into the WS error frame.
        """
        return (
            self._scoped_bucket(
                self._ws_message_buckets,
                connection_key,
                WS_MESSAGE_BUCKET_CAPACITY,
                WS_MESSAGE_REFILLS_PER_SECOND,
            ).try_consume()
        )

    def drop_connection(self, key: str) -> None:
        """Evict one connection's scoped buckets (Task 9 session wiring).

        Scoped buckets otherwise live for the process lifetime; with
        per-connection chat keys that is unbounded growth across connections.
        With session wiring the keys are server-minted and evicted exactly
        when the session drops (close of the Task 4 review finding: buckets
        keyed by untrusted cookie values no longer exist — the WS rate keys
        are only created after cookie validation).
        """
        self._chat_turn_buckets.pop(key, None)
        self._ws_message_buckets.pop(key, None)


def _cookie_value(scope: Scope, name: str) -> str | None:
    """Return the value of cookie ``name`` from the ``Cookie`` header."""
    raw = _header(scope, b"cookie")
    if raw is None:
        return None
    for part in raw.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == name:
            return value
    return None


class RateLimitMiddleware:
    """Pure-ASGI rate limiting; installed inside the Host/Origin policy.

    HTTP enforcement only for now: the WS error frames arrive with the
    chat wiring (Task 9), which calls the ``RateLimiter`` bucket helpers
    for chat turns and other messages.
    """

    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        self.app = app
        self._limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method: str = scope["method"]
        path: str = scope["path"]
        if method == "POST" and path == "/api/auth/login":
            if self._limiter.allow_login():
                await self.app(scope, receive, send)
            else:
                retry_after = self._limiter.login_retry_after()
                await _http_error_response(
                    send,
                    429,
                    _RATE_LIMIT_ERROR_CODE,
                    "Too many login attempts; retry later",
                    extra_headers=[(b"retry-after", str(retry_after).encode("ascii"))],
                )
            return
        if method in ("GET", "HEAD") and path.startswith("/api/"):
            session_id = _cookie_value(scope, SESSION_COOKIE_NAME)
            if session_id is not None and not self._limiter.allow_rest_read(session_id):
                await _http_error_response(
                    send,
                    429,
                    _RATE_LIMIT_ERROR_CODE,
                    "Rate limit exceeded; retry later",
                )
                return
        await self.app(scope, receive, send)


# --- Body caps (DCL-124, spec section 4) --------------------------------------


class _BodyTooLarge(Exception):
    """Internal: raised at ASGI receive level when the cap is exceeded."""


class BodyCapMiddleware:
    """Cap request bodies at ASGI receive level, before any buffering.

    ``Content-Length`` over the cap is rejected without reading a byte.
    Without a ``Content-Length`` (chunked transfers) the bytes are
    counted as they flow through the wrapped ``receive``; an over-cap
    chunk aborts the downstream application mid-read and the 413 goes
    out before any parser could have buffered the payload. A route that
    parses first and measures later has already lost (spec section 4).

    ``overrides`` maps ``"METHOD path"`` (e.g. ``"PUT /api/settings"``)
    to a per-route cap; every other body gets ``default_cap``.
    """

    def __init__(
        self,
        app: ASGIApp,
        default_cap: int = DEFAULT_JSON_BODY_CAP_BYTES,
        overrides: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self._default_cap = default_cap
        self._overrides = dict(overrides) if overrides is not None else {}

    def _cap_for(self, method: str, path: str) -> int:
        return self._overrides.get(f"{method} {path}", self._default_cap)

    def _content_length(self, scope: Scope) -> int | None:
        raw = _header(scope, b"content-length")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            # Malformed length: fall through to receive-level counting,
            # which needs no header and fails closed on real bytes.
            return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cap = self._cap_for(scope["method"], scope["path"])
        content_length = self._content_length(scope)
        if content_length is not None and content_length > cap:
            await _too_large_response(send)
            return

        state: dict[str, int] = {"seen_bytes": 0}

        async def capped_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"") or b""
                state["seen_bytes"] += len(body)
                if state["seen_bytes"] > cap:
                    raise _BodyTooLarge
            return message

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, capped_receive, tracked_send)
        except _BodyTooLarge:
            if not response_started:
                await _too_large_response(send)
            # Otherwise the application already committed a response; the
            # connection is dropped without further frames.


async def _too_large_response(send: Send) -> None:
    await _http_error_response(
        send,
        413,
        _BODY_TOO_LARGE_ERROR_CODE,
        "Request body exceeds the allowed size",
    )


class _WsMessageTooLarge(Exception):
    """Internal: a single WS message exceeded the 32 KiB cap."""


class WebSocketMessageCapMiddleware:
    """Reject any single WS message over 32 KiB; close with code 1009.

    Rate limits do not bound one oversized frame (spec section 4), so
    inbound ``websocket.receive`` messages are measured as they flow
    and an over-cap message unwinds the application and closes the
    connection with code 1009 (message too big). The same limit is set
    on the server WS stack (uvicorn ``ws_max_size``) so the protocol
    layer refuses oversized frames before they even reach ASGI.
    """

    def __init__(
        self, app: ASGIApp, cap: int = WS_MESSAGE_CAP_BYTES
    ) -> None:
        self.app = app
        self._cap = cap

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return

        async def capped_receive() -> Message:
            message = await receive()
            if message["type"] == "websocket.receive":
                data = message.get("bytes") or b""
                text = message.get("text")
                if text is not None:
                    size = max(len(data), len(text.encode("utf-8")))
                else:
                    size = len(data)
                if size > self._cap:
                    raise _WsMessageTooLarge
            return message

        try:
            await self.app(scope, capped_receive, send)
        except _WsMessageTooLarge:
            await send(
                {
                    "type": "websocket.close",
                    "code": _WS_MESSAGE_TOO_BIG_CLOSE_CODE,
                    "reason": _WS_MESSAGE_TOO_BIG_CLOSE_REASON,
                }
            )
