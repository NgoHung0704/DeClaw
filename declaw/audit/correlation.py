"""Task-correlated audit logging (DCL-129, spec section 6).

Setting a contextvar is not enough on its own: emitters construct events
without a ``task_id`` and the inner logger persists the frozen event
verbatim. The mechanism is therefore applied at ``emit`` time:
``TaskCorrelatingAuditLogger`` wraps the real logger and stamps the
ambient task id onto any event whose ``task_id`` is unset; an explicit id
passes through untouched.

The CLI keeps the undecorated logger — no contextvar is ever set there,
so nothing changes for it (spec section 6). Async work scheduled from
within a turn runs in a copied context, so ``asyncio.create_task``
preserves the id into spawned emitters (quarantine sinks, egress bridge).
"""

from __future__ import annotations

from contextvars import ContextVar

from declaw.audit.events import AnyAuditEvent
from declaw.audit.logger import AuditLogger

current_task_id: ContextVar[str | None] = ContextVar("current_task_id", default=None)
"""The task the current execution context belongs to; None outside a turn."""


class TaskCorrelatingAuditLogger:
    """Emit-time decorator stamping the ambient task id on unset events."""

    def __init__(self, inner: AuditLogger) -> None:
        self._inner = inner

    async def emit(self, event: AnyAuditEvent) -> None:
        if event.task_id is None:
            task_id = current_task_id.get()
            if task_id is not None:
                event = event.model_copy(update={"task_id": task_id})
        await self._inner.emit(event)
