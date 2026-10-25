"""CRUD smoke tests for the DeClaw database layer (DCL-005).

Each test gets a fresh SQLite file under ``tmp_path``. We create the schema
via ``SQLModel.metadata.create_all`` rather than invoking Alembic — that
keeps these tests fast and isolated. A separate integration test (added in
DCL-007 / preflight) will exercise the real ``alembic upgrade head`` path.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
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


# --- Process-wide factory initialization -------------------------------------


def _run_factory_probe(script: str, tmp_path: Path) -> None:
    # A subprocess bounds a deadlock without leaving locked singleton state or
    # blocked threads in pytest. The explicit engine path avoids user settings.
    subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )


def test_sessionmaker_can_initialize_before_engine(tmp_path: Path) -> None:
    _run_factory_probe(
        """
        import sys
        from pathlib import Path
        from unittest.mock import patch
        from declaw.db import engine as db

        engine = db.build_engine(Path(sys.argv[1]) / "cold.db")
        with patch.object(db, "build_engine", return_value=engine) as build:
            factory = db.get_sessionmaker()
            assert factory is db.get_sessionmaker()
            assert factory.kw["bind"] is db.get_engine() is engine
            assert build.call_count == 1
        """,
        tmp_path,
    )


def test_concurrent_cold_factory_calls_share_one_engine_and_sessionmaker(tmp_path: Path) -> None:
    _run_factory_probe(
        """
        import sys
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from threading import Barrier
        from unittest.mock import patch
        from declaw.db import engine as db

        engine = db.build_engine(Path(sys.argv[1]) / "concurrent.db")
        barrier = Barrier(8)

        def get_pair(index):
            barrier.wait(timeout=5)
            if index % 2:
                factory = db.get_sessionmaker()
                return db.get_engine(), factory
            current_engine = db.get_engine()
            return current_engine, db.get_sessionmaker()

        with patch.object(db, "build_engine", return_value=engine) as build:
            with patch.object(db, "build_sessionmaker", wraps=db.build_sessionmaker) as make:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    pairs = list(pool.map(get_pair, range(8)))
                assert all(e is engine for e, _ in pairs)
                assert all(m is pairs[0][1] for _, m in pairs)
                assert pairs[0][1].kw["bind"] is engine
                assert build.call_count == 1
                assert make.call_count == 1
        """,
        tmp_path,
    )
