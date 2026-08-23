"""Tests for the typed audit event schema (DCL-060).

Covers: construction defaults, frozen-ness, discriminated round-trip through
the JSON payload, persistence into the real audit_events table, arg clipping,
and rejection of unknown event types.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.audit.events import (
    AUDIT_SCHEMA_VERSION,
    MAX_ARG_CHARS,
    NetworkCallEvent,
    PermissionPromptEvent,
    QuarantineEvent,
    ToolCallEvent,
    clip_args,
    event_from_payload,
    event_from_row,
    to_db_row,
)
from declaw.db.engine import build_engine, build_sessionmaker
from declaw.db.models import AuditEvent as AuditEventRow


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(tmp_path / "declaw.db")
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = build_sessionmaker(engine)
    async with maker() as s:
        yield s


# --- Construction + envelope --------------------------------------------------


def test_tool_call_event_defaults() -> None:
    event = ToolCallEvent(tool_name="filesystem_read", classification="read", outcome="ok")
    assert event.event_type == "tool.call"
    assert event.schema_version == AUDIT_SCHEMA_VERSION
    assert event.id  # uuid assigned
    assert event.task_id is None
    assert event.created_at.tzinfo is not None


def test_events_are_frozen() -> None:
    event = NetworkCallEvent(method="GET", url="http://localhost:11434/api/tags", host="localhost")
    with pytest.raises(ValidationError):
        event.flagged = True  # type: ignore[misc]


def test_each_event_type_has_distinct_discriminator() -> None:
    events = [
        ToolCallEvent(tool_name="t", classification="read", outcome="ok"),
        NetworkCallEvent(method="GET", url="http://x", host="x"),
        QuarantineEvent(quarantine_id="q1", source="tool:filesystem_read", content_sha256="0" * 64, reason="r"),
        PermissionPromptEvent(tool_name="filesystem_write", decision="denied"),
    ]
    types = {e.event_type for e in events}
    assert types == {"tool.call", "network.call", "sanitizer.quarantine", "permission.prompt"}


# --- Round-trip through the payload -------------------------------------------


def test_payload_roundtrip_preserves_event() -> None:
    event = ToolCallEvent(
        tool_name="filesystem_write",
        classification="write",
        args={"path": "notes.txt", "overwrite": False},
        outcome="denied",
        task_id="task-1",
    )
    row = to_db_row(event)
    assert row.event_type == "tool.call"
    assert row.task_id == "task-1"
    assert row.payload["schema_version"] == AUDIT_SCHEMA_VERSION

    restored = event_from_payload(row.payload)
    assert restored == event


def test_unknown_event_type_rejected() -> None:
    with pytest.raises(ValidationError):
        event_from_payload({"event_type": "made.up", "schema_version": 1})


# --- Persistence into the real table -------------------------------------------


async def test_event_persists_and_rehydrates(session: AsyncSession) -> None:
    event = QuarantineEvent(
        quarantine_id="q-42",
        source="tool:filesystem_read",
        content_sha256=hashlib.sha256(b"payload").hexdigest(),
        reason="prompt injection",
    )
    session.add(to_db_row(event))
    await session.commit()

    fetched = (
        await session.exec(select(AuditEventRow).where(AuditEventRow.id == event.id))
    ).one()
    restored = event_from_row(fetched)
    assert isinstance(restored, QuarantineEvent)
    assert restored == event


# --- clip_args ------------------------------------------------------------------


def test_clip_args_leaves_short_values_untouched() -> None:
    args = {"path": "notes.txt", "overwrite": True, "max_bytes": 100}
    assert clip_args(args) == args


def test_clip_args_truncates_and_fingerprints_long_strings() -> None:
    body = "x" * 5000
    clipped = clip_args({"content": body})["content"]
    digest = hashlib.sha256(body.encode()).hexdigest()
    assert clipped.startswith("x" * MAX_ARG_CHARS)
    assert f"sha256={digest[:16]}" in clipped
    assert len(clipped) < 400  # the whole point: no full document in the audit DB


def test_clip_args_does_not_touch_non_strings() -> None:
    args = {"numbers": list(range(1000))}
    assert clip_args(args) == args


def test_plugin_lifecycle_event_round_trips_through_a_db_row() -> None:
    from declaw.audit.events import PluginLifecycleEvent, event_from_row, to_db_row

    event = PluginLifecycleEvent(
        plugin="echo-plugin", version="1.0.0", action="quarantined", detail="3 crashes in 5 min"
    )
    restored = event_from_row(to_db_row(event))
    assert restored == event


def test_plugin_lifecycle_action_vocabulary_is_closed() -> None:
    from declaw.audit.events import PluginLifecycleEvent

    with pytest.raises(ValidationError):
        PluginLifecycleEvent(plugin="p", action="exploded")  # type: ignore[arg-type]
