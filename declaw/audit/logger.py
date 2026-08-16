"""Audit loggers (DCL-061).

The :class:`AuditLogger` protocol is the seam every emitter depends on: the
tool wrappers, the quarantine bridge, and (later) the egress monitor all call
``await audit.emit(event)`` and nothing else. Two implementations ship:

* :class:`DbAuditLogger` — the production logger; one short-lived session per
  event, committed immediately so the trail survives a crash mid-task.
* :class:`InMemoryAuditLogger` — deterministic capture for tests and for
  compositions that have no DB yet.

Emitting an audit event must never take the agent down: ``DbAuditLogger``
catches storage errors and reports them to the operational logger instead of
raising. The inverse trade-off (fail the action when it cannot be audited) is
a Phase 12 hardening decision; for now observability must not reduce
availability.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.audit.events import AnyAuditEvent, to_db_row
from declaw.log import logger


class AuditLogger(Protocol):
    """Anything that can durably record an audit event."""

    async def emit(self, event: AnyAuditEvent) -> None: ...


class InMemoryAuditLogger:
    """Collects events in a list. For tests and DB-less compositions."""

    def __init__(self) -> None:
        self.events: list[AnyAuditEvent] = []

    async def emit(self, event: AnyAuditEvent) -> None:
        self.events.append(event)


class DbAuditLogger:
    """Persists every event into the ``audit_events`` table (Principle #7)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def emit(self, event: AnyAuditEvent) -> None:
        try:
            async with self._sessionmaker() as session:
                session.add(to_db_row(event))
                await session.commit()
        except Exception:
            # Auditing must not take the agent down; surface loudly instead.
            logger.bind(event_type=event.event_type, event_id=event.id).exception(
                "Failed to persist audit event"
            )
