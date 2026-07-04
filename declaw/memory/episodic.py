"""Episodic memory: task history (DCL-054).

Timestamped records of what the agent did, stored in SQLite next to tasks and
audit events (they share the DB so an episode, its task, and its audit trail
join on ``task_id``). This is the layer the daily report (DCL-063) and the
GDPR export (DCL-056) read.

Query semantics: the date filter runs in SQL against the indexed
``started_at`` column; tag matching happens in Python over the JSON array.
For a single-user local DB (hundreds of episodes, not millions) that is
simpler and safer than a normalized tag table — revisit if scale ever proves
otherwise.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.db.models import Episode


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _day_bounds(on: date) -> tuple[datetime, datetime]:
    start = datetime.combine(on, time.min, tzinfo=timezone.utc)
    end = datetime.combine(on, time.max, tzinfo=timezone.utc)
    return start, end


class EpisodicMemory:
    """Record + query per-task episodes."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(
        self,
        *,
        summary: str,
        tags: list[str] | None = None,
        task_id: str | None = None,
        outcome: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> Episode:
        """Persist one episode and return it (id assigned)."""
        if not summary.strip():
            raise ValueError("Refusing to record an episode with an empty summary.")
        episode = Episode(
            summary=summary,
            tags=list(tags) if tags else [],
            task_id=task_id,
            outcome=outcome,
            started_at=started_at if started_at is not None else _utcnow(),
            finished_at=finished_at,
        )
        async with self._sessionmaker() as session:
            session.add(episode)
            await session.commit()
            await session.refresh(episode)
        return episode

    async def query(
        self,
        *,
        on: date | None = None,
        tag: str | None = None,
    ) -> list[Episode]:
        """Episodes filtered by day (UTC) and/or tag, oldest first."""
        statement = select(Episode).order_by(col(Episode.started_at))
        if on is not None:
            start, end = _day_bounds(on)
            statement = statement.where(
                col(Episode.started_at) >= start, col(Episode.started_at) <= end
            )
        async with self._sessionmaker() as session:
            episodes = list((await session.exec(statement)).all())
        if tag is not None:
            episodes = [e for e in episodes if tag in e.tags]
        return episodes

    async def export_all(self) -> list[Episode]:
        """Every episode, oldest first — the GDPR-export surface (DCL-056)."""
        return await self.query()

    async def wipe(self) -> int:
        """Delete all episodes; returns how many were removed (DCL-057)."""
        async with self._sessionmaker() as session:
            episodes = (await session.exec(select(Episode))).all()
            for episode in episodes:
                await session.delete(episode)
            await session.commit()
        return len(episodes)
