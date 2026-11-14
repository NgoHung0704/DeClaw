"""Canonical error handling for the REST surface (DCL-126, spec section 9).

Every response an added route produces — including the 404/422/409/503/400
paths — renders the one gateway error shape:

    {"error": {"code": str, "message": str}}

``ApiError`` is the typed exception routes raise for those situations;
``register_rest_error_handlers`` installs the renderer plus the 422 for
FastAPI/pydantic request validation (path params, query params, bodies),
which otherwise defaults to Starlette's ``{"detail": [...]}`` and would be
the only non-canonical error left on the surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from declaw.app import Application

_INVALID_REQUEST_CODE = "invalid_request"
_SERVICE_UNAVAILABLE_CODE = "service_unavailable"


def application_from(request: Request) -> Application:
    """The Application every ``/api`` service route reads.

    ``create_app`` may build a bare app (auth surface and middleware only);
    service routes answer 503 — the canonical shape — so the surface stays
    uniform: cookie auth is checked first (401), then service availability.
    """
    application: Application | None = getattr(request.app.state, "application", None)
    if application is None:
        raise ApiError(
            503,
            _SERVICE_UNAVAILABLE_CODE,
            "This gateway exposes the authentication surface only; "
            "start it with an application to use this route.",
        )
    return application


class ApiError(Exception):
    """A typed route failure rendered as the canonical gateway error JSON."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def canonical_error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """The one error shape the gateway serves (spec section 9)."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _summarize_validation_error(exc: RequestValidationError) -> str:
    """One readable line per problem, naming the offending field."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "request"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def register_rest_error_handlers(app: FastAPI) -> None:
    """Render ``ApiError`` and request-validation failures canonically."""

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return canonical_error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return canonical_error_response(
            422, _INVALID_REQUEST_CODE, _summarize_validation_error(exc)
        )
