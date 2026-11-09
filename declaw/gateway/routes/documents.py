"""``/api/documents`` — catalog listing, sanitized search, reindex start (DCL-126).

Read-only surface by construction (spec section 9 "no REST write actions"):
organize/summarize/move stay chat tools behind the approval transport, and
this module registers no document-mutating verb — the only POST is
``/api/documents/reindex``, a control action on the index itself.

Search is the chat path exactly: the same ``search_documents`` primitive,
the same ``DocumentStack`` store and chunk sanitizer the chat tool is built
from — retrieval here cannot drift from retrieval there.

Reindex starts the stack's existing reconciliation run as a background task
and stays honest about what is async: 202, one run at a time (a second start
is a 409, never a queued duplicate), progress frames handed to an optional
``EventBroadcaster`` that Task 13 (/ws/events) will inject as
``app.state.event_broadcaster``. Task 12's serialized worker will take over
the execution side; the route's contract — started-once, observable, honest —
is pinned here.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import col, select

from declaw.db.models import IndexedDocument
from declaw.documents.search import DEFAULT_K, search_documents
from declaw.gateway.routes.auth import require_session
from declaw.gateway.routes.errors import ApiError, application_from
from declaw.log import logger

router = APIRouter(
    prefix="/api/documents",
    dependencies=[Depends(require_session)],
)

_DOCUMENTS_UNAVAILABLE = "documents_unavailable"
_REINDEX_IN_PROGRESS = "reindex_in_progress"
_INDEX_PROGRESS_TYPE = "index.progress"


def _require_stack(application: Any) -> Any:
    """The document stack exists only when the doc-intel plugin loaded."""
    if application.stack is None:
        raise ApiError(
            404,
            _DOCUMENTS_UNAVAILABLE,
            "Document features are unavailable: the doc-intel plugin is not "
            "loaded (disabled, quarantined, or failed at startup).",
        )
    return application.stack


def _document_out(row: IndexedDocument) -> dict[str, Any]:
    return {
        "path": row.path,
        "content_sha256": row.content_sha256,
        "size_bytes": row.size_bytes,
        "doc_type": row.doc_type,
        "chunk_count": row.chunk_count,
        "mtime": row.mtime.isoformat(),
        "indexed_at": row.indexed_at.isoformat(),
        # "status" becomes richer in Task 12 (failed markers); every catalog
        # row today is a successfully indexed document.
        "status": "indexed",
    }


@router.get("")
async def list_documents(request: Request) -> dict[str, list[dict[str, Any]]]:
    application = application_from(request)
    statement = select(IndexedDocument).order_by(col(IndexedDocument.path))
    async with application.sessionmaker() as session:
        rows = (await session.exec(statement)).all()
    return {"documents": [_document_out(row) for row in rows]}


@router.get("/search")
async def search_documents_route(
    request: Request,
    q: str = Query(min_length=1),
    k: int = Query(DEFAULT_K, ge=1, le=50),
) -> dict[str, Any]:
    application = application_from(request)
    stack = _require_stack(application)
    # Exactly what chat sees: the tool built at startup calls the same
    # primitive with the same store and chunk sanitizer.
    outcome = await search_documents(stack.store, stack.chunk_sanitizer, q, k=k)
    return {"hits": [asdict(hit) for hit in outcome.hits], "withheld": outcome.withheld}


@router.post("/reindex", status_code=202)
async def start_reindex(request: Request) -> dict[str, str]:
    application = application_from(request)
    stack = _require_stack(application)
    running = getattr(request.app.state, "reindex_task", None)
    if running is not None and not running.done():
        raise ApiError(
            409,
            _REINDEX_IN_PROGRESS,
            "A reindex is already running; it must finish before another starts.",
        )

    # Optional seam, injected by Task 13: app.state.event_broadcaster is the
    # EventBroadcaster serving /ws/events. Absent (until that task lands),
    # progress is only visible in the catalog and operational log.
    broadcaster = getattr(request.app.state, "event_broadcaster", None)

    def on_progress(progress: Any) -> None:
        if broadcaster is None:
            return
        frame = {
            "type": _INDEX_PROGRESS_TYPE,
            "total": progress.total,
            "done": progress.done,
            "current_path": progress.path,
        }
        # Runs inside the indexing task on the loop: scheduling the broadcast
        # keeps the indexer's sync progress callback non-blocking.
        asyncio.get_running_loop().create_task(broadcaster.broadcast(frame))

    async def run() -> None:
        try:
            report = await stack.indexer.index(on_progress=on_progress)
            logger.info(
                "Reindex finished: indexed={} skipped={} failed={} removed={}",
                report.indexed,
                report.skipped,
                report.failed,
                report.removed,
            )
        except Exception:  # noqa: BLE001 - a background run must never crash the loop
            logger.exception("Reindex run failed")

    task = asyncio.create_task(run())
    task.add_done_callback(lambda _task: setattr(request.app.state, "reindex_task", None))
    request.app.state.reindex_task = task
    return {"status": "started"}
