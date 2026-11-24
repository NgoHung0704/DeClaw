"""``GET /api/tasks`` and ``GET /api/tasks/{task_id}`` (DCL-126, spec section 9).

Durable task rows are written by the WS turn lifecycle (Tasks 9/10); these
read-only routes list them newest-first with the status, result, error and
timestamps, straight from the Application's sessionmaker — no caching, the
same rows ``/ws/chat`` leaves behind.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlmodel import col, select

from declaw.db.models import Task
from declaw.gateway.routes.auth import require_session
from declaw.gateway.routes.errors import ApiError, application_from

router = APIRouter(
    prefix="/api/tasks",
    dependencies=[Depends(require_session)],
)


def _task_out(row: Task) -> dict[str, Any]:
    return {
        "id": row.id,
        "prompt": row.prompt,
        "status": row.status.value,
        "result": row.result,
        "error": row.error,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("")
async def list_tasks(request: Request) -> dict[str, list[dict[str, Any]]]:
    """Every task, newest first (created_at, then id, for stable order)."""
    application = application_from(request)
    statement = select(Task).order_by(
        col(Task.created_at).desc(), col(Task.id).desc()
    )
    async with application.sessionmaker() as session:
        rows = (await session.exec(statement)).all()
    return {"tasks": [_task_out(row) for row in rows]}


@router.get("/{task_id}")
async def task_detail(task_id: str, request: Request) -> dict[str, Any]:
    application = application_from(request)
    async with application.sessionmaker() as session:
        row = await session.get(Task, task_id)
    if row is None:
        raise ApiError(404, "not_found", f"No task {task_id!r}.")
    return _task_out(row)
