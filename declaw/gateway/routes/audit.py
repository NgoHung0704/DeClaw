"""``GET /api/audit`` and ``GET /api/audit/export`` (DCL-129, spec sections 9/15).

The viewer's data plane. ``GET /api/audit`` filters by date range, event
type and task id and pages with a keyset cursor on ``(created_at, id)`` —
newest first, with the id tie-break so rows sharing a timestamp can never
be skipped or repeated across pages.

The export route reuses the existing surfaces verbatim: the Markdown
export is ``declaw.audit.report.daily_report`` (the day's plain-language
rollup), the JSON export is ``declaw.audit.export.export_json`` over
``events_for_day`` (the typed, self-describing archive), round-tripped
through a temporary file so the shipped exporters stay the single writers
of those formats.

Corrupt rows — written by a future/older schema — are counted, not fatal,
exactly like the report/export paths; the response carries the count so a
stubbornly empty page can be told apart from a page the reader skipped.
"""

from __future__ import annotations

import base64
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, or_
from sqlmodel import col, select
from starlette.responses import Response

from declaw.audit.events import event_from_row
from declaw.audit.export import export_json
from declaw.audit.report import daily_report, events_for_day
from declaw.db.models import AuditEvent as AuditEventRow
from declaw.gateway.routes.auth import require_session
from declaw.gateway.routes.errors import ApiError, application_from
from declaw.gateway.routes.settings import effective_language
from declaw.log import logger

router = APIRouter(
    prefix="/api/audit",
    dependencies=[Depends(require_session)],
)

_PAGE_LIMITS = Query(50, ge=1, le=200)
_INVALID_CURSOR_CODE = "invalid_cursor"


@dataclass(frozen=True, slots=True)
class _Cursor:
    """The keyset position: strictly below (created_at, id) on the page."""

    created_at: datetime
    event_id: str


def _encode_cursor(cursor: _Cursor) -> str:
    raw = f"{cursor.created_at.isoformat()}|{cursor.event_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(raw: str) -> _Cursor:
    """Decode and validate; garbage answers 400, never a wrong page."""
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
        created_str, _, event_id = decoded.partition("|")
        if not created_str or not event_id:
            raise ValueError("missing cursor fields")
        return _Cursor(created_at=datetime.fromisoformat(created_str), event_id=event_id)
    except (ValueError, UnicodeError) as exc:
        raise ApiError(400, _INVALID_CURSOR_CODE, f"Malformed cursor: {exc}") from exc


def _filters(
    date_from: date | None, date_to: date | None, event_type: str | None, task_id: str | None
) -> list[Any]:
    """Inclusive UTC-dated range filters plus the equality filters."""
    clauses: list[Any] = []
    if date_from is not None:
        start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        clauses.append(col(AuditEventRow.created_at) >= start)
    if date_to is not None:
        end = datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        clauses.append(col(AuditEventRow.created_at) <= end)
    if event_type is not None:
        clauses.append(col(AuditEventRow.event_type) == event_type)
    if task_id is not None:
        clauses.append(col(AuditEventRow.task_id) == task_id)
    return clauses


@router.get("")
async def list_audit(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    event_type: str | None = None,
    task_id: str | None = None,
    limit: int = _PAGE_LIMITS,
    cursor: str | None = None,
) -> dict[str, Any]:
    application = application_from(request)
    clauses = _filters(date_from, date_to, event_type, task_id)
    if cursor is not None:
        position = _decode_cursor(cursor)
        clauses.append(
            or_(
                col(AuditEventRow.created_at) < position.created_at,
                and_(
                    col(AuditEventRow.created_at) == position.created_at,
                    col(AuditEventRow.id) < position.event_id,
                ),
            )
        )
    statement = (
        select(AuditEventRow)
        .where(*clauses)
        .order_by(col(AuditEventRow.created_at).desc(), col(AuditEventRow.id).desc())
        .limit(limit + 1)  # one-row lookahead: next_cursor iff a next page exists
    )
    async with application.sessionmaker() as session:
        rows = (await session.exec(statement)).all()
    more = len(rows) > limit
    rows = rows[:limit]

    events: list[dict[str, Any]] = []
    unreadable = 0
    for row in rows:
        try:
            events.append(event_from_row(row).model_dump(mode="json"))
        except PydanticValidationError:
            # A row the current schema cannot read: counted, never fatal —
            # same policy as the daily report and archive exports.
            unreadable += 1
    next_cursor = (
        _encode_cursor(_Cursor(rows[-1].created_at, rows[-1].id)) if rows and more else None
    )
    return {"events": events, "next_cursor": next_cursor, "unreadable": unreadable}


@router.get("/export")
async def export_audit(
    request: Request,
    day: Annotated[date, Query()],
    format: Annotated[Literal["md", "json"], Query()],
) -> Response:
    application = application_from(request)
    headers = {
        "Content-Disposition": f'attachment; filename="declaw-audit-{day.isoformat()}.{format}"'
    }
    if format == "md":
        report = await daily_report(
            application.sessionmaker, day, effective_language(application)
        )
        return Response(content=report, media_type="text/markdown", headers=headers)

    events, _unreadable = await events_for_day(application.sessionmaker, day)
    # The shipped exporter stays the single writer of the archive format;
    # the HTTP response re-reads its output from a temporary file.
    with tempfile.TemporaryDirectory(prefix="declaw-audit-export-") as directory:
        destination = Path(directory) / f"declaw-audit-{day.isoformat()}.json"
        export_json(events, destination)
        content = destination.read_text(encoding="utf-8")
    logger.debug("Served audit export for day {}", day.isoformat())
    return Response(content=content, media_type="application/json", headers=headers)
