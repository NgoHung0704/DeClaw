"""Baseline SQLModel tables for DeClaw.

Two tables ship in the initial schema:

  - ``tasks`` — one row per user request handed to the agent.
  - ``audit_events`` — append-only log mandated by Inviolable Principle #7
    ("never make a network call without logging it to the audit trail").

UUIDs are used as primary keys instead of auto-incrementing integers because
we will eventually sync data between devices and integer PKs would collide.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, Index
from sqlalchemy import JSON
from sqlalchemy import TypeDecorator
from sqlalchemy.types import DateTime as SADateTime
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator[datetime]):
    """DateTime column that always returns tz-aware UTC datetimes.

    SQLite stores datetimes as TEXT and aiosqlite returns naive Python
    datetimes on read even when the column declares timezone=True. This
    decorator re-attaches UTC tzinfo transparently so callers always get
    tz-aware values, matching the tz-aware values we store.
    """

    impl = SADateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _dt_col(*, index: bool = False) -> Any:
    """UTC-aware DateTime column — tzinfo survives aiosqlite round-trips."""
    return Column(UTCDateTime(), nullable=False, index=index)


def _dt_col_updated() -> Any:
    """Like _dt_col but wires onupdate so callers never need to touch it."""
    return Column(UTCDateTime(), default=_utcnow, onupdate=_utcnow, nullable=False)


class TaskStatus(str, enum.Enum):
    """Lifecycle states of a user task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(SQLModel, table=True):
    """A single user request processed by the agent."""

    __tablename__ = "tasks"

    id: str = Field(default_factory=_new_id, primary_key=True, max_length=36)
    prompt: str = Field(description="The raw user prompt that started this task.")
    status: TaskStatus = Field(default=TaskStatus.PENDING, index=True)
    result: str | None = Field(default=None, description="Final agent answer, if any.")
    error: str | None = Field(default=None, description="Error message if status is failed.")
    created_at: datetime = Field(default_factory=_utcnow, sa_column=_dt_col(index=True))
    # onupdate fires automatically on every ORM-level UPDATE — callers never
    # need to set this manually.
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=_dt_col_updated())


class Episode(SQLModel, table=True):
    """Episodic memory: one timestamped record per completed agent task (DCL-054).

    Episodes are the "what happened when" layer of memory — queryable by date
    and tag, linkable to both the task row and (via task_id) its audit events.
    Tags are stored as a JSON array; with local, per-user data volumes the
    date filter runs in SQL and tag matching in Python (documented trade-off
    over a normalized tag table).
    """

    __tablename__ = "episodes"

    id: str = Field(default_factory=_new_id, primary_key=True, max_length=36)
    task_id: str | None = Field(
        default=None,
        foreign_key="tasks.id",
        index=True,
        description="Task this episode records, if any.",
    )
    summary: str = Field(description="One-paragraph plain-language record of the episode.")
    tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="Free-form labels for retrieval (e.g. 'contracts', 'email').",
    )
    outcome: str | None = Field(
        default=None, description="Terminal outcome, e.g. 'completed' or 'failed'."
    )
    started_at: datetime = Field(default_factory=_utcnow, sa_column=_dt_col(index=True))
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(UTCDateTime(), nullable=True)
    )


class AuditEvent(SQLModel, table=True):
    """Append-only audit record. Required by Inviolable Principle #7."""

    __tablename__ = "audit_events"

    # Composite index covers the dominant query: events for a task in time order.
    __table_args__ = (
        Index("ix_audit_events_task_created", "task_id", "created_at"),
    )

    id: str = Field(default_factory=_new_id, primary_key=True, max_length=36)
    event_type: str = Field(
        index=True,
        max_length=64,
        description="Dotted event type, e.g. 'network.egress' or 'tool.shell'.",
    )
    task_id: str | None = Field(
        default=None,
        foreign_key="tasks.id",
        index=True,
        description="Task that triggered the event, if any.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
        description="Structured event payload (free-form JSON).",
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_column=_dt_col(index=True))
