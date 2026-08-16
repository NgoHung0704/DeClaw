"""Daily audit report: "What did DeClaw do today?" (DCL-063).

Pulls one UTC day of audit events from the DB, groups them by task, and
renders each group through the deterministic NL summarizer (DCL-062). The
CLI surface is ``declaw report [--date] [--lang]``; the Phase 9 UI reads the
same function.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.audit.events import AnyAuditEvent, event_from_row
from declaw.audit.summary import summarize_events
from declaw.config import Language
from declaw.db.models import AuditEvent as AuditEventRow

_L = {
    "en": {
        "title": "DeClaw daily report — {day}",
        "empty": "No activity recorded on {day}.",
        "task": "Task {task}",
        "no_task": "Outside any task",
        "unreadable": "({count} unreadable audit record(s) skipped)",
    },
    "fr": {
        "title": "Rapport quotidien DeClaw — {day}",
        "empty": "Aucune activité enregistrée le {day}.",
        "task": "Tâche {task}",
        "no_task": "Hors de toute tâche",
        "unreadable": "({count} enregistrement(s) d'audit illisible(s) ignoré(s))",
    },
}


async def events_for_day(
    sessionmaker: async_sessionmaker[AsyncSession], day: date
) -> tuple[list[AnyAuditEvent], int]:
    """Load the day's events (UTC bounds), oldest first.

    Returns ``(events, unreadable_count)`` — rows whose payload no longer
    parses (e.g. written by a future/older schema) are counted, not fatal.
    """
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(day, time.max, tzinfo=timezone.utc)
    statement = (
        select(AuditEventRow)
        .where(col(AuditEventRow.created_at) >= start, col(AuditEventRow.created_at) <= end)
        .order_by(col(AuditEventRow.created_at))
    )
    async with sessionmaker() as session:
        rows = (await session.exec(statement)).all()

    events: list[AnyAuditEvent] = []
    unreadable = 0
    for row in rows:
        try:
            events.append(event_from_row(row))
        except ValidationError:
            unreadable += 1
    return events, unreadable


async def daily_report(
    sessionmaker: async_sessionmaker[AsyncSession],
    day: date,
    language: Language = "en",
) -> str:
    """Render the day's plain-language rollup, grouped by task."""
    strings = _L[language]
    events, unreadable = await events_for_day(sessionmaker, day)

    lines = [strings["title"].format(day=day.isoformat()), ""]
    if not events:
        lines.append(strings["empty"].format(day=day.isoformat()))
    else:
        # Group by task, preserving first-seen order.
        groups: dict[str | None, list[AnyAuditEvent]] = {}
        for event in events:
            groups.setdefault(event.task_id, []).append(event)
        for task_id, group in groups.items():
            header = (
                strings["task"].format(task=task_id)
                if task_id is not None
                else strings["no_task"]
            )
            lines.append(f"## {header}")
            lines.append(summarize_events(group, language))
            lines.append("")
    if unreadable:
        lines.append(strings["unreadable"].format(count=unreadable))
    return "\n".join(lines).rstrip() + "\n"
