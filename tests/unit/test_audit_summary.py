"""Tests for the NL audit summary + daily report (DCL-062 / DCL-063).

Acceptances: summary mentions actions + "data left device: yes/no";
daily report available (CLI reads the same daily_report function).
Everything is deterministic templates — no LLM, no network.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.audit.events import (
    NetworkCallEvent,
    QuarantineEvent,
    ToolCallEvent,
)
from declaw.audit.logger import DbAuditLogger
from declaw.audit.report import daily_report
from declaw.audit.summary import summarize_events
from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.db.models import AuditEvent as AuditEventRow


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(tmp_path / "declaw.db")
    await ensure_schema(eng)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return build_sessionmaker(engine)


def _read(path: str, outcome: str = "ok") -> ToolCallEvent:
    return ToolCallEvent(
        tool_name="filesystem_read",
        classification="read",
        args={"path": path},
        outcome=outcome,  # type: ignore[arg-type]
    )


# --- summarize_events (DCL-062) --------------------------------------------------


def test_summary_mentions_actions_and_egress_no() -> None:
    events = [
        _read("contract.pdf"),
        ToolCallEvent(
            tool_name="filesystem_move",
            classification="write",
            args={"source": "a.txt", "destination": "b.txt"},
            outcome="ok",
        ),
    ]
    text = summarize_events(events, "en")
    assert "Read file contract.pdf" in text
    assert "Moved a.txt to b.txt" in text
    assert text.endswith("Data left this device: no")


def test_summary_denied_and_error_outcomes() -> None:
    events = [
        ToolCallEvent(
            tool_name="filesystem_write",
            classification="write",
            args={"path": "x.txt", "content": "..."},
            outcome="denied",
        ),
        _read("missing.txt", outcome="error"),
    ]
    text = summarize_events(events, "en")
    assert "Wrote file x.txt (denied by you)" in text
    assert "Read file missing.txt (failed)" in text


def test_summary_flags_egress_yes_with_hosts() -> None:
    events: list[NetworkCallEvent] = [
        NetworkCallEvent(method="GET", url="http://localhost:11434/x", host="localhost"),
        NetworkCallEvent(
            method="POST", url="https://api.example.com/up", host="api.example.com", flagged=True
        ),
    ]
    text = summarize_events(list(events), "en")
    assert "Data left this device: YES (api.example.com)" in text


def test_summary_quarantine_line() -> None:
    event = QuarantineEvent(
        quarantine_id="q1", source="tool:filesystem_read", content_sha256="0" * 64, reason="r"
    )
    text = summarize_events([event], "en")
    assert "quarantined" in text.lower()


def test_summary_french() -> None:
    events = [_read("contrat.pdf")]
    text = summarize_events(events, "fr")
    assert "Lecture du fichier contrat.pdf" in text
    assert "Des données ont quitté cet appareil : non" in text


def test_summary_unknown_tool_falls_back_to_generic() -> None:
    event = ToolCallEvent(tool_name="future_tool", classification="read", outcome="ok")
    assert "Called tool future_tool" in summarize_events([event], "en")


def test_summary_empty() -> None:
    assert summarize_events([], "en") == "No recorded activity."
    assert summarize_events([], "fr") == "Aucune activité enregistrée."


# --- daily_report (DCL-063) -------------------------------------------------------


def _on_day(event: ToolCallEvent, day: date, hour: int) -> ToolCallEvent:
    stamp = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
    return event.model_copy(update={"created_at": stamp})


async def test_daily_report_groups_by_task(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    audit = DbAuditLogger(sessionmaker)
    day = date(2026, 7, 4)
    await audit.emit(
        _on_day(_read("a.pdf").model_copy(update={"task_id": "task-1"}), day, 9)
    )
    await audit.emit(_on_day(_read("b.pdf"), day, 10))
    await audit.emit(_on_day(_read("other-day.pdf"), date(2026, 7, 5), 9))

    text = await daily_report(sessionmaker, day, "en")
    assert "DeClaw daily report — 2026-07-04" in text
    assert "## Task task-1" in text
    assert "Read file a.pdf" in text
    assert "## Outside any task" in text
    assert "Read file b.pdf" in text
    assert "other-day.pdf" not in text  # date filter works


async def test_daily_report_empty_day(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    text = await daily_report(sessionmaker, date(2026, 1, 1), "en")
    assert "No activity recorded on 2026-01-01." in text
    fr = await daily_report(sessionmaker, date(2026, 1, 1), "fr")
    assert "Aucune activité enregistrée le 2026-01-01." in fr


async def test_daily_report_counts_unreadable_rows(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    day = date(2026, 7, 4)
    stamp = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
    async with sessionmaker() as session:
        session.add(
            AuditEventRow(
                event_type="future.event",
                payload={"event_type": "future.event", "schema_version": 99},
                created_at=stamp,
            )
        )
        await session.commit()

    text = await daily_report(sessionmaker, day, "en")
    assert "1 unreadable audit record(s) skipped" in text


def test_quarantined_plugin_appears_in_the_english_summary() -> None:
    from declaw.audit.events import PluginLifecycleEvent

    text = summarize_events(
        [PluginLifecycleEvent(plugin="echo-plugin", action="quarantined", detail="3 crashes")],
        "en",
    )
    assert "echo-plugin" in text
    assert "quarantin" in text.lower()


def test_disabled_plugin_appears_in_the_french_summary() -> None:
    from declaw.audit.events import PluginLifecycleEvent

    text = summarize_events([PluginLifecycleEvent(plugin="echo-plugin", action="disabled")], "fr")
    assert "echo-plugin" in text
    assert "désactivée" in text
