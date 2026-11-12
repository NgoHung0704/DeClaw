"""FastAPI gateway application factory and hardened launcher (DCL-120, spec section 1).

The launch contract lives here, not only in config parsing: the gateway must
bind exactly ``127.0.0.1``, and the launcher refuses anything else even if a
Settings instance carrying another host reaches it (defense in depth).

``run_gateway`` runs foreground uvicorn with hardened flags and no reload.
``create_app`` binds the shared ``Application`` lifespan, routes and security
middleware while preserving the strict launcher contract.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from declaw.app import Application
from declaw.audit.correlation import TaskCorrelatingAuditLogger
from declaw.audit.logger import AuditLogger, InMemoryAuditLogger
from declaw.brain.ollama_client import OllamaHealth
from declaw.config import Settings
from declaw.credentials.store import CredentialStore, SecretStore
from declaw.gateway.approval import ApprovalBroker
from declaw.gateway.auth import SessionRegistry
from declaw.gateway.events import EventBroadcaster, router as events_router
from declaw.gateway.middleware import (
    DEFAULT_JSON_BODY_CAP_BYTES,
    SETTINGS_PUT_BODY_CAP_BYTES,
    WS_MESSAGE_CAP_BYTES,
    BodyCapMiddleware,
    HostOriginMiddleware,
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    WebSocketMessageCapMiddleware,
)
from declaw.gateway.routes import (
    audit_router,
    auth_router,
    documents_router,
    plugins_router,
    settings_router,
    status_router,
    tasks_router,
)
from declaw.gateway.routes.auth import register_auth_error_handlers
from declaw.gateway.routes.errors import register_rest_error_handlers
from declaw.gateway.routes.status import (
    LatchedOllamaHealth,
    default_health_check,
)
from declaw.gateway.session import SessionManager
from declaw.gateway.ws import ModelFactory, router as ws_router, session_graph_factory
from declaw.log import logger

# The local web UI (spec section 13): static vanilla-JS assets served at
# "/", CSP-locked to same-origin. Path is resolved relative to the source
# tree — packaging (wheel) is the recorded Phase 14 gate, not handled here.
UI_DIR = Path(__file__).resolve().parents[2] / "ui"


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
    approval_broker: ApprovalBroker | None = None,
    model_factory: ModelFactory | None = None,
    rate_limiter: RateLimiter | None = None,
    status_health_check: Callable[[], Awaitable[OllamaHealth]] | None = None,
) -> FastAPI:
    """Build the FastAPI application for the gateway.

    The Host/Origin policy (DCL-122) is installed outermost so it wraps every
    route, then rate limits, then WS message caps, then body caps (innermost,
    so byte counting wraps the router's receive). The limiter is shared with
    the WS chat endpoint so the bucket helpers (chat-turn 10/min per session,
    other WS messages 30/s per connection) are enforced from one state.

    With an ``application`` (spec section 5 — the production path), the app
    owns the full chat wiring: the Application is started by the lifespan,
    its session shutdown hooks get the real handlers, and every chat session
    runs ``/ws/chat`` with per-session tools. Without one, the app serves the
    auth surface and middleware only (chats close 1011): the old bare
    ``DbAuditLogger(get_sessionmaker())`` fallback is gone — an eager engine
    on an unconfigured data_dir is not something a "bare" app should create.
    Tests keep using injected fakes or the in-memory capture logger.

    ``model_factory`` is the deterministic-fake seam for the chat flow tests;
    production leaves it None and the session graph builds the Ollama stack
    from the effective-settings snapshot.
    """
    limiter = rate_limiter if rate_limiter is not None else RateLimiter()
    broker = approval_broker if approval_broker is not None else ApprovalBroker()
    audit = TaskCorrelatingAuditLogger(_resolve_audit_logger(audit_logger, application))
    graph_factory = (
        session_graph_factory(
            application=application, audit=audit, broker=broker, model_factory=model_factory
        )
        if application is not None
        else None
    )
    manager = SessionManager(
        broker=broker,
        limiter=limiter,
        sessionmaker=application.sessionmaker if application is not None else None,
        graph_factory=graph_factory,
    )

    if application is not None:
        # Task 9 wiring (spec sections 5/6): the constructor-injected hooks
        # from Task 7 get their real handlers — the manager and broker above.
        application.wire_gateway_shutdown(manager)

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            # The gateway starts the Application on startup and stops it
            # deterministically on shutdown — it must serve the rest of the
            # API even when Ollama is down; chat turns then fail typed.
            await application.start()
            try:
                yield
            finally:
                await application.shutdown()

        app = FastAPI(title="DeClaw gateway", lifespan=lifespan)
    else:
        app = FastAPI(title="DeClaw gateway")

    app.state.rate_limiter = limiter
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
    # Strict CSP + nosniff OUTERMOST (added last): even a 403 from the
    # Host/Origin policy carries the security headers (spec section 13).
    app.add_middleware(
        SecurityHeadersMiddleware,
        bind_authority=f"{settings.host}:{settings.port}",
    )

    # Auth surface (spec sections 2 and 6): one token source, one session
    # registry and one correlating audit logger, shared by every route.
    app.state.secret_store = secret_store if secret_store is not None else CredentialStore()
    app.state.session_registry = (
        session_registry if session_registry is not None else SessionRegistry()
    )
    app.state.audit = audit
    app.state.approval_broker = broker
    app.state.session_manager = manager
    # /ws/events (DCL-133): ONE broadcaster serves the event stream, the
    # reindex progress seam (Task 11/12) and the plugin confirmations. It is
    # also the Application's document-event sink, so worker/watcher frames
    # reach subscribers without a second owner.
    broadcaster = EventBroadcaster()
    app.state.event_broadcaster = broadcaster
    if application is not None:
        application.set_document_event_broadcaster(broadcaster)
    # /api/status (spec section 9): latched Ollama health so the route never
    # waits on the daemon; tests inject the deterministic health check.
    app.state.ollama_status = LatchedOllamaHealth(
        status_health_check
        if status_health_check is not None
        else default_health_check(settings.ollama_base_url)
    )
    if application is not None:
        app.state.application = application
    register_auth_error_handlers(app)
    register_rest_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(ws_router)
    app.include_router(events_router)
    app.include_router(status_router)
    app.include_router(tasks_router)
    app.include_router(audit_router)
    app.include_router(plugins_router)
    app.include_router(settings_router)
    app.include_router(documents_router)

    # The JSON liveness probe moves off the root: / serves the UI (spec
    # section 13). It must register BEFORE the "/" static mount — Starlette
    # matches in registration order.
    @app.get("/healthz")
    def health_root() -> dict[str, str]:
        """JSON liveness probe (the site root serves the UI)."""
        return {"status": "ok"}

    # Spec section 13: the UI is served as static files by FastAPI at "/"
    # (registered after the /api routers, so API routes win the match).
    if UI_DIR.is_dir():
        app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")

    return app


def _resolve_audit_logger(
    audit_logger: AuditLogger | None, application: Application | None
) -> AuditLogger:
    """Injected fake wins; the Application owns the real DbAuditLogger."""
    if audit_logger is not None:
        return audit_logger
    if application is not None:
        return application.audit
    # Bare apps (auth/middleware surface only) capture in memory: the
    # deleted Task 7 fallback eagerly built a real engine on the default
    # data_dir, which a test or boot-time app must never do.
    return InMemoryAuditLogger()


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
    is no proxy, ever. The Application (spec section 5) is constructed here
    and started by the app lifespan; the gateway therefore starts and serves
    even when Ollama is down — chat turns fail with a typed error instead
    of taking the process down.
    """
    assert_launch_contract(settings)
    _route_access_log_into_loguru()
    application = Application(settings, mode="gateway")
    config = uvicorn.Config(
        app=create_app(settings, application=application),
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
