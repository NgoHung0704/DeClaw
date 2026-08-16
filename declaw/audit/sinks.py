"""Bridges from in-process event sources to the durable audit trail (DCL-061).

The sanitizer's :class:`QuarantineStore` (DCL-044/045) emits its events through
a *sync* ``AuditSink`` seam — it predates the DB-backed trail and must never
block a tool coroutine on storage. ``quarantine_db_sink`` adapts that seam to
an async :class:`AuditLogger`:

* called from inside a running event loop (the normal case — quarantine happens
  inside an async tool wrapper), the emit is scheduled as a background task;
* called with no loop (sync scripts, tests), it runs the emit to completion.

``composite_sink`` fans one quarantine event out to several sinks so the
existing loguru sink and the DB sink can both stay wired.
"""

from __future__ import annotations

import asyncio

from declaw.audit.events import QuarantineEvent
from declaw.audit.logger import AuditLogger
from declaw.sanitizer.quarantine import AuditSink
from declaw.sanitizer.quarantine import QuarantineEvent as SanitizerQuarantineEvent

# Strong references to fire-and-forget emit tasks. asyncio keeps only weak
# refs to tasks; without this set a pending audit write could be GC'd.
_pending_tasks: set[asyncio.Task[None]] = set()


def quarantine_db_sink(audit: AuditLogger) -> AuditSink:
    """Adapt ``audit`` into a sync ``AuditSink`` for the ``QuarantineStore``."""

    def sink(event: SanitizerQuarantineEvent) -> None:
        audit_event = QuarantineEvent(
            quarantine_id=event.id,
            source=event.source,
            content_sha256=event.content_sha256,
            reason=event.reason,
            created_at=event.created_at,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(audit.emit(audit_event))
        else:
            task = loop.create_task(audit.emit(audit_event))
            _pending_tasks.add(task)
            task.add_done_callback(_pending_tasks.discard)

    return sink


def composite_sink(*sinks: AuditSink) -> AuditSink:
    """Return a sink that forwards each event to every sink in ``sinks``."""

    def fan_out(event: SanitizerQuarantineEvent) -> None:
        for sink in sinks:
            sink(event)

    return fan_out
