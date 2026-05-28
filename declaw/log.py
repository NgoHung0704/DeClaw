"""Structured JSON logger for DeClaw, built on loguru.

Every log record is emitted as a single JSON line containing at least:
``timestamp`` (ISO 8601, UTC), ``level``, ``message``, ``request_id``.

Request ID propagation uses ``contextvars.ContextVar`` so it follows
``asyncio.Task`` boundaries automatically — each FastAPI request sets its
own ID at the gateway entry point, and every log call inside that request
(no matter how deeply nested or how many ``await`` hops it crosses) picks
the same ID up without explicit threading.

This module is the *operational* logger (debug/troubleshooting). The
*audit* trail required by Principle #7 is a separate, DB-backed channel
(``declaw.db.models.AuditEvent``).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, TextIO

from loguru import logger

from declaw.config import get_settings

if TYPE_CHECKING:
    from loguru import Record

_request_id: ContextVar[str | None] = ContextVar("declaw_request_id", default=None)

_configured = False


def set_request_id(value: str | None) -> None:
    """Set the current task's request ID (or clear it with ``None``)."""
    _request_id.set(value)


def get_request_id() -> str | None:
    """Return the current task's request ID, or ``None`` if none is set."""
    return _request_id.get()


@contextmanager
def use_request_id(value: str) -> Iterator[None]:
    """Bind a request ID for the duration of a ``with`` block."""
    token = _request_id.set(value)
    try:
        yield
    finally:
        _request_id.reset(token)


def _patcher(record: Record) -> None:
    # loguru calls this for every record before sinks see it. We attach the
    # current contextvar value so JSON sinks can serialize it.
    record["extra"]["request_id"] = _request_id.get()


def _serialize(record: dict[str, Any]) -> str:
    payload: dict[str, Any] = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "request_id": record["extra"].get("request_id"),
        "logger": record["name"],
    }
    # Bound extras (logger.bind(foo=...)) live alongside request_id in extra.
    extras = {k: v for k, v in record["extra"].items() if k != "request_id"}
    if extras:
        payload["extra"] = extras
    if record["exception"] is not None:
        payload["exception"] = str(record["exception"])
    return json.dumps(payload, default=str, ensure_ascii=False)


def _sink_factory(stream: TextIO):  # type: ignore[no-untyped-def]
    def sink(message) -> None:  # type: ignore[no-untyped-def]
        # ``message.record`` is the structured dict; ``str(message)`` would be
        # the already-formatted text line, which we don't want.
        stream.write(_serialize(message.record) + "\n")
        stream.flush()

    return sink


def configure(
    *,
    level: str | None = None,
    stream: TextIO | None = None,
    force: bool = False,
) -> None:
    """Install the JSON sink on the global loguru logger.

    Idempotent unless ``force=True``. Tests pass ``force=True`` plus their
    own stream to capture output.
    """
    global _configured
    if _configured and not force:
        return

    resolved_level = level or get_settings().log_level
    target = stream if stream is not None else sys.stderr

    logger.remove()
    logger.configure(patcher=_patcher)
    logger.add(_sink_factory(target), level=resolved_level, format="{message}")
    _configured = True


__all__ = [
    "configure",
    "get_request_id",
    "logger",
    "set_request_id",
    "use_request_id",
]
