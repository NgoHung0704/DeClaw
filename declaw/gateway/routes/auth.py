"""Gateway auth routes: login, logout, status (DCL-121, spec section 2).

Paste-once login: the browser posts the gateway token once and receives an
opaque session cookie. The token is never persisted client-side, never
written to logs or audit payloads, and never echoed in responses, so a
wrong login reveals only "401" — nothing about the expected value.

``AuthEvent`` ("gateway.auth") records login success/failure and logout
with no bearer material at all: no gateway token, and no session id (a
session id could be replayed as the cookie value). Correlation goes
through ``task_id`` only, once turns exist.

``require_session`` is the reusable cookie-check dependency every protected
API route (Task 11) will take; its failure renders the canonical
``{"error": {"code", "message"}}`` 401 shape.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from declaw.audit.events import AuthEvent
from declaw.audit.logger import AuditLogger
from declaw.credentials.store import SecretStore
from declaw.gateway.auth import (
    SESSION_COOKIE_NAME,
    SessionRegistry,
    clear_session_cookie,
    mint_gateway_token,
    session_cookie,
)

auth_router = APIRouter(prefix="/api/auth")

_UNAUTHORIZED_CODE = "unauthorized"


class LoginRequest(BaseModel):
    """Login body: the paste-once gateway token printed by ``declaw start``."""

    token: str


class AuthError(Exception):
    """An authentication failure to render as the canonical 401 body."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def register_auth_error_handlers(app: FastAPI) -> None:
    """Render ``AuthError`` as the gateway's canonical 401 JSON."""

    @app.exception_handler(AuthError)
    async def _auth_error(_request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": exc.code, "message": exc.message}},
        )


def _registry(request: Request) -> SessionRegistry:
    registry: SessionRegistry = request.app.state.session_registry
    return registry


def _audit(request: Request) -> AuditLogger:
    audit: AuditLogger = request.app.state.audit
    return audit


async def require_session(request: Request) -> str:
    """Reusable cookie check for protected routes (spec section 2.3).

    Returns the validated session id, or raises the canonical 401. Never
    creates a session — a probe must not mint authority.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None or not _registry(request).validate(session_id):
        raise AuthError(_UNAUTHORIZED_CODE, "Authentication required")
    return session_id


@auth_router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, str]:
    """Exchange the gateway token for an opaque session cookie (spec 2.2).

    Constant-time comparison over encoded bytes: the attacker-controlled
    value may be arbitrary unicode, which as ``str`` would make
    ``hmac.compare_digest`` raise instead of deny. Failed logins were
    already rate-limited by the middleware (Task 4) before this ran.
    """
    store: SecretStore = request.app.state.secret_store
    expected = mint_gateway_token(store)  # create-or-get, idempotent
    provided = payload.token.encode("utf-8")
    if not hmac.compare_digest(provided, expected.encode("utf-8")):
        await _audit(request).emit(AuthEvent(action="login_failure"))
        raise AuthError(_UNAUTHORIZED_CODE, "Invalid gateway token")

    session_id = _registry(request).create()
    response.headers["set-cookie"] = session_cookie(session_id)
    await _audit(request).emit(AuthEvent(action="login_success"))
    return {"status": "authenticated"}


@auth_router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    """Drop the registry entry and clear the cookie; idempotent (spec 2.3).

    No valid-session requirement: a client holding a stale cookie must be
    able to end up fully logged out, so the entry is dropped if present
    and the cookie is cleared either way.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is not None:
        _registry(request).drop(session_id)
    response.headers["set-cookie"] = clear_session_cookie()
    await _audit(request).emit(AuthEvent(action="logout"))
    return {"status": "ok"}


@auth_router.get("/status")
async def status(request: Request) -> dict[str, bool]:
    """Report authenticated/not authenticated; never creates a session."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    authenticated = session_id is not None and _registry(request).validate(session_id)
    return {"authenticated": authenticated}
