"""Gateway pure-ASGI middleware (DCL-122, spec section 3).

Fail-closed Host/Origin policy defending the loopback gateway against
CSRF and DNS-rebinding attacks (CVE-2026-25253 class). Runs before
routing on every request; nothing downstream sees a request that failed
either check.

- Host: the ``Host`` header must exactly match the bound authority
  (``127.0.0.1:<port>``). Foreign domains, other ports and a missing
  host are 403 — a browser that resolved an attacker's domain to
  127.0.0.1 sends that domain in ``Host`` and dies here.
- Origin: required on every non-GET/HEAD request and on every WebSocket
  handshake. It must equal ``http://127.0.0.1:<port>``. Missing or
  ``null`` Origin on a state-changing request is 403 (fail closed).
  GET/HEAD are exempt: they are read-only, and ``SameSite=Strict``
  already prevents cross-site credentialed reads.
- WebSocket: both checks run on the handshake; failures close with code
  4403 (forbidden origin/host) before any application message flows.

The allowlist is derived from the actual bind authority passed in —
never from a hard-coded port.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

_WS_FORBIDDEN_CLOSE_CODE = 4403  # forbidden Origin/Host (spec section 3)
_WS_FORBIDDEN_CLOSE_REASON = "Forbidden Host or Origin"


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
