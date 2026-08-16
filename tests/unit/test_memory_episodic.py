"""Tests for episodic memory (DCL-054).

Acceptance: query by date/tag works. Fresh SQLite file per test via
create_all (mirrors test_db.py); the real Alembic migration is exercised by
the existing preflight/integration path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.db.models import Task
from declaw.memory.episodic import EpisodicMemory


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


@pytest.fixture
def memory(sessionmaker: async_sessionmaker[AsyncSession]) -> EpisodicMemory:
    return EpisodicMemory(sessionmaker)


def _at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


async def test_record_assigns_id_and_defaults(memory: EpisodicMemory) -> None:
    episode = await memory.record(summary="Summarized contract.pdf", tags=["contracts"])
    assert episode.id
    assert episode.started_at.tzinfo is not None
    assert episode.tags == ["contracts"]


async def test_query_by_date(memory: EpisodicMemory) -> None:
    day1 = date(2026, 7, 1)
    day2 = date(2026, 7, 2)
    await memory.record(summary="ep1", started_at=_at(day1, 9))
    await memory.record(summary="ep2", started_at=_at(day1, 17))
    await memory.record(summary="ep3", started_at=_at(day2, 10))

    on_day1 = await memory.query(on=day1)
    assert [e.summary for e in on_day1] == ["ep1", "ep2"]  # oldest first
    on_day2 = await memory.query(on=day2)
    assert [e.summary for e in on_day2] == ["ep3"]


async def test_query_by_tag(memory: EpisodicMemory) -> None:
    await memory.record(summary="a", tags=["contracts", "acme"])
    await memory.record(summary="b", tags=["invoices"])
    await memory.record(summary="c", tags=["contracts"])

    contracts = await memory.query(tag="contracts")
    assert [e.summary for e in contracts] == ["a", "c"]
    assert await memory.query(tag="nonexistent") == []


async def test_query_by_date_and_tag_combined(memory: EpisodicMemory) -> None:
    day = date(2026, 7, 3)
    await memory.record(summary="match", tags=["x"], started_at=_at(day, 8))
    await memory.record(summary="wrong-tag", tags=["y"], started_at=_at(day, 9))
    await memory.record(summary="wrong-day", tags=["x"], started_at=_at(date(2026, 7, 4), 8))

    hits = await memory.query(on=day, tag="x")
    assert [e.summary for e in hits] == ["match"]


async def test_episode_links_to_task(
    memory: EpisodicMemory, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with sessionmaker() as session:
        task = Task(prompt="summarize the contract")
        session.add(task)
        await session.commit()
        await session.refresh(task)

    episode = await memory.record(summary="done", task_id=task.id, outcome="completed")
    assert episode.task_id == task.id


async def test_wipe_removes_everything(memory: EpisodicMemory) -> None:
    await memory.record(summary="a")
    await memory.record(summary="b")
    assert await memory.wipe() == 2
    assert await memory.export_all() == []


async def test_empty_summary_rejected(memory: EpisodicMemory) -> None:
    with pytest.raises(ValueError):
        await memory.record(summary="  ")
