"""CRUD smoke tests for the DeClaw database layer (DCL-005).

Each test gets a fresh SQLite file under ``tmp_path``. We create the schema
via ``SQLModel.metadata.create_all`` rather than invoking Alembic — that
keeps these tests fast and isolated. A separate integration test (added in
DCL-007 / preflight) will exercise the real ``alembic upgrade head`` path.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.db.engine import build_engine, build_sessionmaker
from declaw.db.models import AuditEvent, Task, TaskStatus


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


# --- Task CRUD --------------------------------------------------------------


async def test_insert_and_read_task(session: AsyncSession) -> None:
    task = Task(prompt="Summarize this contract.")
    session.add(task)
    await session.commit()
    await session.refresh(task)

    assert task.id  # uuid was assigned
    assert task.status is TaskStatus.PENDING
    assert task.created_at is not None

    result = await session.exec(select(Task).where(Task.id == task.id))
    fetched = result.one()
    assert fetched.prompt == "Summarize this contract."


async def test_update_task_status(session: AsyncSession) -> None:
    task = Task(prompt="run shell")
    session.add(task)
    await session.commit()
    await session.refresh(task)

    task.status = TaskStatus.COMPLETED
    task.result = "done"
    session.add(task)
    await session.commit()
    await session.refresh(task)

    assert task.status is TaskStatus.COMPLETED
    assert task.result == "done"


# --- AuditEvent CRUD --------------------------------------------------------


async def test_audit_event_with_json_payload(session: AsyncSession) -> None:
    event = AuditEvent(
        event_type="network.egress",
        payload={"host": "api.example.com", "bytes": 1024, "allowed": False},
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)

    fetched = (await session.exec(select(AuditEvent).where(AuditEvent.id == event.id))).one()
    assert fetched.payload == {"host": "api.example.com", "bytes": 1024, "allowed": False}
    assert fetched.task_id is None


async def test_audit_event_links_to_task(session: AsyncSession) -> None:
    task = Task(prompt="read /etc/passwd")
    session.add(task)
    await session.commit()
    await session.refresh(task)

    event = AuditEvent(
        event_type="tool.shell.blocked",
        task_id=task.id,
        payload={"reason": "outside sandbox"},
    )
    session.add(event)
    await session.commit()

    events = (
        await session.exec(select(AuditEvent).where(AuditEvent.task_id == task.id))
    ).all()
    assert len(events) == 1
    assert events[0].event_type == "tool.shell.blocked"


# --- updated_at auto-update -------------------------------------------------


async def test_updated_at_advances_on_update(session: AsyncSession) -> None:
    task = Task(prompt="check updated_at")
    session.add(task)
    await session.commit()
    await session.refresh(task)
    original = task.updated_at

    # Small sleep so the timestamps differ even at sub-second resolution.
    await asyncio.sleep(0.01)

    task.status = TaskStatus.RUNNING
    session.add(task)
    await session.commit()
    await session.refresh(task)

    assert task.updated_at > original


# --- Timezone round-trip ----------------------------------------------------


async def test_datetimes_are_timezone_aware_after_roundtrip(session: AsyncSession) -> None:
    task = Task(prompt="tz check")
    session.add(task)
    await session.commit()
    await session.refresh(task)

    fetched = (await session.exec(select(Task).where(Task.id == task.id))).one()
    assert fetched.created_at.tzinfo is not None
    assert fetched.created_at.tzinfo == timezone.utc
    assert fetched.updated_at.tzinfo is not None


# --- Schema sanity ----------------------------------------------------------


async def test_schema_creates_both_tables(engine: AsyncEngine) -> None:
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "tasks" in names
    assert "audit_events" in names


async def test_composite_index_exists_on_audit_events(engine: AsyncEngine) -> None:
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        indexes = await conn.run_sync(
            lambda c: inspect(c).get_indexes("audit_events")
        )
    index_names = {idx["name"] for idx in indexes}
    assert "ix_audit_events_task_created" in index_names
