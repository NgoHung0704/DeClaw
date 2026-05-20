"""Async SQLite engine + session factory for DeClaw.

The database file lives under ``settings.data_dir`` (defaults to
``~/.declaw/declaw.db``). All I/O goes through aiosqlite so the FastAPI
gateway can stay fully async.

Sessions are short-lived: one per logical operation, created via the
``get_session`` async context manager. We do **not** share a process-wide
session — that would serialize all DB access and leak transactions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from declaw.config import get_settings


def _sqlite_url(db_path: Path) -> str:
    # aiosqlite driver, absolute path. ``Path.as_posix()`` keeps Windows paths
    # consumable by SQLAlchemy's URL parser.
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def build_engine(db_path: Path | None = None, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine. Tests pass an explicit ``db_path``."""
    if db_path is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = settings.data_dir / "declaw.db"
    return create_async_engine(_sqlite_url(db_path), echo=echo, future=True)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Process-wide engine. Lazily created on first call."""
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = build_sessionmaker(get_engine())
    return _sessionmaker


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a short-lived async session. Commits/rollbacks are caller-owned."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session
