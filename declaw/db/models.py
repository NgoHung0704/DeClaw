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

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


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
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    updated_at: datetime = Field(default_factory=_utcnow)


class AuditEvent(SQLModel, table=True):
    """Append-only audit record. Required by Inviolable Principle #7."""

    __tablename__ = "audit_events"

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
    created_at: datetime = Field(default_factory=_utcnow, index=True)
