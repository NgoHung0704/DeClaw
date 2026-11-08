"""FastAPI gateway application factory and hardened launcher (DCL-120, spec section 1).

The launch contract lives here, not only in config parsing: the gateway must
bind exactly ``127.0.0.1``, and the launcher refuses anything else even if a
Settings instance carrying another host reaches it (defense in depth).

``run_gateway`` is deliberately minimal for now: programmatic uvicorn with
hardened flags, no reload, in the foreground. Later tickets bind the
``Application`` lifespan, routes and middleware without touching this
contract.
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from declaw.app import Application
from declaw.audit.correlation import TaskCorrelatingAuditLogger
from declaw.audit.logger import AuditLogger, DbAuditLogger
from declaw.config import Settings
from declaw.credentials.store import CredentialStore, SecretStore
from declaw.db.engine import get_sessionmaker
from declaw.gateway.auth import SessionRegistry
from declaw.gateway.middleware import (
    DEFAULT_JSON_BODY_CAP_BYTES,
    SETTINGS_PUT_BODY_CAP_BYTES,
    WS_MESSAGE_CAP_BYTES,
    BodyCapMiddleware,
    HostOriginMiddleware,
    RateLimiter,
    RateLimitMiddleware,
    WebSocketMessageCapMiddleware,
)
from declaw.gateway.routes import auth_router
from declaw.gateway.routes.auth import register_auth_error_handlers
from declaw.log import logger


class GatewayLaunchError(RuntimeError):
    """Settings do not satisfy the strict 127.0.0.1 gateway launch contract."""


def assert_launch_contract(settings: Settings) -> None:
    """Refuse to launch unless the gateway binds exactly ``127.0.0.1``.

    Independent of ``Settings._enforce_loopback`` (defense in depth): a
    forged or future Settings object must never make the launcher bind a
    non-loopback host. ``localhost`` and ``::1`` remain valid settings for
    other uses but are not launchable gateway configurations in v0.1.
    """
    if settings.host != "127.0.0.1":
        raise GatewayLaunchError(
            f"Gateway launch refused: DECLAW_HOST must be 127.0.0.1 "
            f"(got {settings.host!r}). The gateway never binds outside loopback."
        )


def create_app(
    settings: Settings,
    *,
    secret_store: SecretStore | None = None,
    session_registry: SessionRegistry | None = None,
    audit_logger: AuditLogger | None = None,
    application: Application | None = None,
) -> FastAPI:
    """Build the FastAPI application for the gateway.

    Empty besides a liveness root and the auth surface (spec section 2);
    further routes, chat and the ``Application`` lifespan arrive in later
    tickets. The Host/Origin policy (DCL-122) is installed first so it
    wraps every future route: it derives its allowlist from the actual
    bound authority (``settings.host:port``), never a hard-coded port.

    Dependencies are injectable for tests (fake vault, in-memory audit
    logger); production passes the OS-keyring store, a fresh session
    registry and the ``Application`` (spec section 5), which owns the
    engine and ``DbAuditLogger`` wiring. The logger is wrapped in the
    task-correlating decorator (spec section 6): out of a turn the
    contextvar is unset, so events pass through unchanged — every
    gateway emitter shares this one decorated logger.
    """
    app = FastAPI(title="DeClaw gateway")
    # Task 9 (chat wiring) consumes the same limiter for the WS error
    # frames; the buckets live on the app so the whole stack shares them.
    limiter = RateLimiter()
    app.state.rate_limiter = limiter
    # Last-added runs outermost: Host/Origin rejects before anything else,
    # then rate limits, then WS message caps, then body caps (innermost,
    # so byte counting wraps the router's receive).
    app.add_middleware(
        BodyCapMiddleware,
        default_cap=DEFAULT_JSON_BODY_CAP_BYTES,
        overrides={"PUT /api/settings": SETTINGS_PUT_BODY_CAP_BYTES},
    )
    app.add_middleware(WebSocketMessageCapMiddleware)
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    app.add_middleware(
        HostOriginMiddleware,
        bind_authority=f"{settings.host}:{settings.port}",
    )

    # Auth surface (spec sections 2 and 6): one token source, one session
    # registry and one correlating audit logger, shared by every route.
    app.state.secret_store = secret_store if secret_store is not None else CredentialStore()
    app.state.session_registry = (
        session_registry if session_registry is not None else SessionRegistry()
    )
    # Engine/logger wiring has a single owner: the Application (spec section
    # 5). An injected audit_logger still wins so tests keep using fakes.
    if audit_logger is not None:
        inner_logger: AuditLogger = audit_logger
    elif application is not None:
        inner_logger = application.audit
    else:
        inner_logger = DbAuditLogger(get_sessionmaker())
    app.state.audit = TaskCorrelatingAuditLogger(inner_logger)
    if application is not None:
        # Later tickets hang the lifespan and the WS chat wiring off this.
        app.state.application = application
    register_auth_error_handlers(app)
    app.include_router(auth_router)

    @app.get("/")
    def health_root() -> dict[str, str]:
        """Liveness probe served at the site root."""
        return {"status": "ok"}

    return app


class _LoguruAccessLogHandler(logging.Handler):
    """Forward uvicorn access lines into the loguru sink at DEBUG.

    Uvicorn emits access lines through stdlib ``logging``; the gateway owns
    that channel so query strings (which the access log can carry) land in
    the structured JSON log at DEBUG instead of plain console output.
    """

    def emit(self, record: logging.LogRecord) -> None:
        logger.log("DEBUG", record.getMessage())


def _route_access_log_into_loguru() -> None:
    """Own the stdlib ``uvicorn.access`` logger for this process.

    Idempotent: the DEBUG level and the forwarding handler are installed once
    and never duplicated; ``propagate`` stays off so access lines cannot leak
    through stdlib root handlers.
    """
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(h, _LoguruAccessLogHandler) for h in access_logger.handlers):
        access_logger.addHandler(_LoguruAccessLogHandler())
    access_logger.setLevel(logging.DEBUG)
    access_logger.propagate = False


def run_gateway(settings: Settings) -> None:
    """Run the gateway in the foreground with a hardened uvicorn config.

    Blocking on purpose: Ctrl-C is the stop mechanism until DCL-234. No
    reload, ``proxy_headers`` off, ``forwarded_allow_ips`` never set — there
    is no proxy, ever.
    """
    assert_launch_contract(settings)
    _route_access_log_into_loguru()
    config = uvicorn.Config(
        app=create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,  # keep uvicorn away from stdlib logging setup
        proxy_headers=False,
        # Server-side frame limit (spec section 4): the protocol layer
        # refuses a single oversized WS message before it reaches ASGI,
        # complementing the in-app WebSocketMessageCapMiddleware.
        ws_max_size=WS_MESSAGE_CAP_BYTES,
    )
    uvicorn.Server(config).run()
