"""Multi-format audit export: JSON, Markdown, PDF (DCL-065).

JSON is the machine-readable archive (full typed payloads, self-describing
envelope). Markdown and PDF are the human/regulator-facing renderings — one
line per event with the facts that matter (what ran, on what, outcome,
egress flags).

PDF notes: built with fpdf2 core fonts, which cover Latin-1 — enough for the
EN/FR target market. Characters outside Latin-1 are transliterated (em-dash,
curly quotes) or replaced, never fatal; bundling a full-Unicode TTF is a
Phase 9/10 polish item if ever needed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fpdf import FPDF
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.audit.events import (
    AnyAuditEvent,
    MemoryExportEvent,
    MemoryWipeEvent,
    NetworkCallEvent,
    PermissionPromptEvent,
    QuarantineEvent,
    ToolCallEvent,
    event_from_row,
)
from declaw.db.models import AuditEvent as AuditEventRow

AUDIT_EXPORT_SCHEMA_VERSION = 1

ExportFormat = Literal["json", "markdown", "pdf"]

_TITLE = "DeClaw audit export"

# Common non-Latin-1 punctuation, transliterated so core PDF fonts keep working.
_LATIN1_MAP = str.maketrans(
    {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"',
     "”": '"', "…": "..."}
)


def _latin1(text: str) -> str:
    return text.translate(_LATIN1_MAP).encode("latin-1", "replace").decode("latin-1")


def _details(event: AnyAuditEvent) -> str:
    """One-line factual rendering of an event (format-agnostic)."""
    if isinstance(event, ToolCallEvent):
        args = ", ".join(f"{k}={v!r}" for k, v in event.args.items())
        return f"{event.tool_name}({args}) -> {event.outcome}"
    if isinstance(event, NetworkCallEvent):
        flag = " [FLAGGED: left the device]" if event.flagged else ""
        status = event.status_code if event.status_code is not None else event.error
        return f"{event.method} {event.url} -> {status}{flag}"
    if isinstance(event, QuarantineEvent):
        return f"quarantined content from {event.source} (sha256 {event.content_sha256[:16]})"
    if isinstance(event, PermissionPromptEvent):
        return f"user {event.decision} {event.tool_name}"
    if isinstance(event, MemoryExportEvent):
        return (
            f"memory exported to {event.destination} "
            f"({event.semantic_count} memories, {event.episode_count} episodes)"
        )
    if isinstance(event, MemoryWipeEvent):
        return (
            f"memory wiped ({event.semantic_removed} memories, "
            f"{event.episodes_removed} episodes)"
        )
    return event.event_type  # future-proof fallback


def export_json(events: list[AnyAuditEvent], destination: Path) -> Path:
    archive = {
        "declaw_audit_export": {
            "schema_version": AUDIT_EXPORT_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
        },
        "events": [event.model_dump(mode="json") for event in events],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def export_markdown(events: list[AnyAuditEvent], destination: Path) -> Path:
    lines = [
        f"# {_TITLE}",
        "",
        f"Exported: {datetime.now(timezone.utc).isoformat()}  ",
        f"Events: {len(events)}",
        "",
        "| time (UTC) | type | task | details |",
        "| --- | --- | --- | --- |",
    ]
    for event in events:
        stamp = event.created_at.strftime("%Y-%m-%d %H:%M:%S")
        details = _details(event).replace("|", "\\|")
        task = event.task_id if event.task_id is not None else "-"
        lines.append(f"| {stamp} | {event.event_type} | {task} | {details} |")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def export_pdf(events: list[AnyAuditEvent], destination: Path) -> Path:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("helvetica", style="B", size=16)
    pdf.cell(0, 10, _TITLE, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    pdf.cell(
        0,
        6,
        _latin1(
            f"Exported {datetime.now(timezone.utc).isoformat()} - {len(events)} event(s)"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)
    for event in events:
        stamp = event.created_at.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp}  [{event.event_type}]  {_details(event)}"
        pdf.multi_cell(0, 5, _latin1(line), new_x="LMARGIN", new_y="NEXT")
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(destination))
    return destination


def export_events(
    events: list[AnyAuditEvent], destination: Path, format: ExportFormat
) -> Path:
    """Dispatch to the requested format's exporter."""
    if format == "json":
        return export_json(events, destination)
    if format == "markdown":
        return export_markdown(events, destination)
    if format == "pdf":
        return export_pdf(events, destination)
    raise ValueError(f"Unknown export format {format!r}.")


async def load_all_events(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[list[AnyAuditEvent], int]:
    """Load the entire audit trail, oldest first.

    Returns ``(events, unreadable_count)`` — like the daily report, corrupt
    rows are counted, not fatal.
    """
    from pydantic import ValidationError

    statement = select(AuditEventRow).order_by(col(AuditEventRow.created_at))
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
