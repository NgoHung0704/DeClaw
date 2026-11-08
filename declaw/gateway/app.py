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

from declaw.config import Settings
from declaw.gateway.middleware import HostOriginMiddleware
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


def create_app(settings: Settings) -> FastAPI:
    """Build the (currently minimal) FastAPI application for the gateway.

    Empty besides a liveness root; further routes, auth and the Application
    lifespan arrive in later tickets. The Host/Origin policy (DCL-122) is
    installed first so it wraps every future route: it derives its
    allowlist from the actual bound authority (``settings.host:port``),
    never a hard-coded port.
    """
    app = FastAPI(title="DeClaw gateway")
    app.add_middleware(
        HostOriginMiddleware,
        bind_authority=f"{settings.host}:{settings.port}",
    )

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
    )
    uvicorn.Server(config).run()
