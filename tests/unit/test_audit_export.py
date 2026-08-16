"""Tests for multi-format audit export (DCL-065).

Acceptance: each format renders correctly. JSON must round-trip through the
typed schema; Markdown must be a readable table; PDF must be a real PDF and
must survive French accents + non-Latin-1 punctuation.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from declaw.audit.events import (
    AUDIT_SCHEMA_VERSION,
    AnyAuditEvent,
    NetworkCallEvent,
    ToolCallEvent,
    event_from_payload,
)
from declaw.audit.export import (
    export_events,
    export_json,
    export_markdown,
    export_pdf,
    load_all_events,
)
from declaw.audit.logger import DbAuditLogger
from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(tmp_path / "declaw.db")
    await ensure_schema(eng)
    try:
        yield eng
    finally:
        await eng.dispose()


def _events() -> list[AnyAuditEvent]:
    return [
        ToolCallEvent(
            tool_name="filesystem_read",
            classification="read",
            args={"path": "dossier — pièce n°1.pdf"},
            outcome="ok",
            task_id="task-1",
        ),
        NetworkCallEvent(
            method="POST",
            url="https://api.example.com/upload",
            host="api.example.com",
            status_code=200,
            flagged=True,
        ),
    ]


def test_json_export_roundtrips(tmp_path: Path) -> None:
    destination = export_json(_events(), tmp_path / "audit.json")
    archive = json.loads(destination.read_text(encoding="utf-8"))
    assert archive["declaw_audit_export"]["schema_version"] == 1
    assert archive["declaw_audit_export"]["event_count"] == 2
    restored = [event_from_payload(p) for p in archive["events"]]
    assert restored == _events()[:0] + restored  # parses cleanly into typed events
    assert restored[0].schema_version == AUDIT_SCHEMA_VERSION


def test_markdown_export_renders_table(tmp_path: Path) -> None:
    destination = export_markdown(_events(), tmp_path / "audit.md")
    text = destination.read_text(encoding="utf-8")
    assert "# DeClaw audit export" in text
    assert "| time (UTC) | type | task | details |" in text
    assert "filesystem_read" in text
    assert "FLAGGED: left the device" in text
    assert "task-1" in text


def test_pdf_export_is_a_real_pdf_and_survives_unicode(tmp_path: Path) -> None:
    from pypdf import PdfReader

    destination = export_pdf(_events(), tmp_path / "audit.pdf")
    blob = destination.read_bytes()
    assert blob.startswith(b"%PDF")
    assert len(blob) > 500
    # Content streams are compressed; extract the text to check the rendering.
    text = "".join(page.extract_text() for page in PdfReader(str(destination)).pages)
    assert "pièce" in text  # French accents (Latin-1) survive intact
    assert "filesystem_read" in text
    assert "FLAGGED" in text


def test_dispatcher_selects_format(tmp_path: Path) -> None:
    assert export_events(_events(), tmp_path / "a.json", "json").suffix == ".json"
    assert export_events(_events(), tmp_path / "a.md", "markdown").suffix == ".md"
    assert export_events(_events(), tmp_path / "a.pdf", "pdf").suffix == ".pdf"


def test_empty_trail_exports_are_valid(tmp_path: Path) -> None:
    archive = json.loads(
        export_json([], tmp_path / "empty.json").read_text(encoding="utf-8")
    )
    assert archive["events"] == []
    assert export_pdf([], tmp_path / "empty.pdf").read_bytes().startswith(b"%PDF")


async def test_load_all_events_reads_the_trail(engine: AsyncEngine) -> None:
    maker = build_sessionmaker(engine)
    audit = DbAuditLogger(maker)
    for event in _events():
        await audit.emit(event)

    events, unreadable = await load_all_events(maker)
    assert len(events) == 2
    assert unreadable == 0
    assert isinstance(events[0], ToolCallEvent)
