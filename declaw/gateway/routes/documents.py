"""``/api/documents`` — catalog listing, sanitized search, reindex start (DCL-126).

Read-only surface by construction (spec section 9 "no REST write actions"):
organize/summarize/move stay chat tools behind the approval transport, and
this module registers no document-mutating verb — the only POST is
``/api/documents/reindex``, a control action on the index itself.

Search is the chat path exactly: the same ``search_documents`` primitive,
the same ``DocumentStack`` store and chunk sanitizer the chat tool is built
from — retrieval here cannot drift from retrieval there.

Reindex feeds the stack's existing reconciliation run to the serialized
indexing worker (Task 12, DCL-128) and stays honest about what is async: 202,
one run at a time (a second start is a 409, never a queued duplicate), progress
frames handed to an optional ``EventBroadcaster`` that Task 13 (/ws/events)
will inject as ``app.state.event_broadcaster``. The route's contract —
started-once, observable, honest — is pinned by tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import col, select

from declaw.db.models import DocumentIndexFailure, IndexedDocument
from declaw.documents.search import DEFAULT_K, search_documents
from declaw.documents.worker import ReindexInProgress
from declaw.gateway.routes.auth import require_session
from declaw.gateway.routes.errors import ApiError, application_from

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


def _document_out(
    row: IndexedDocument,
    failure: DocumentIndexFailure | None = None,
) -> dict[str, Any]:
    status = "failed" if failure is not None else "indexed"
    return {
        "path": row.path,
        "content_sha256": row.content_sha256,
        "size_bytes": row.size_bytes,
        "doc_type": row.doc_type,
        "chunk_count": row.chunk_count,
        "mtime": row.mtime.isoformat(),
        "indexed_at": row.indexed_at.isoformat(),
        # The catalog does not lie: a path whose last attempt failed shows
        # the marker (DCL-128), whether or not an older chunk set survives.
        "status": status,
        "error": failure.error if failure is not None else None,
    }


def _failure_out(failure: DocumentIndexFailure) -> dict[str, Any]:
    """A path that never indexed still appears — no silent loss."""
    return {
        "path": failure.path,
        "content_sha256": None,
        "size_bytes": None,
        "doc_type": None,
        "chunk_count": None,
        "mtime": None,
        "indexed_at": None,
        "status": "failed",
        "error": failure.error,
    }


@router.get("")
async def list_documents(request: Request) -> dict[str, list[dict[str, Any]]]:
    application = application_from(request)
    statement = select(IndexedDocument).order_by(col(IndexedDocument.path))
    async with application.sessionmaker() as session:
        rows = (await session.exec(statement)).all()
        failures = (await session.exec(select(DocumentIndexFailure))).all()
    failed = {failure.path: failure for failure in failures}
    documents = [_document_out(row, failed.pop(row.path, None)) for row in rows]
    documents.extend(_failure_out(failure) for failure in failed.values())
    documents.sort(key=lambda document: str(document["path"]))
    return {"documents": documents}


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

    # Task 12 (DCL-128): the SINGLE serialized indexing worker owns every run
    # — manual reindex, startup reconciliation and watcher triggers: one
    # executor, one guarantee about concurrency. Through it, a reindex and a
    # watcher-triggered index can never overlap at the Chroma level.
    worker = getattr(application, "document_worker", None)
    if worker is None:
        raise ApiError(
            404,
            _DOCUMENTS_UNAVAILABLE,
            "Document features are unavailable: the indexing worker is not "
            "running (the doc-intel plugin did not load, or the application "
            "did not start in gateway mode).",
        )

    # Optional seam, injected by Task 13: app.state.event_broadcaster is the
    # EventBroadcaster serving /ws/events. Absent, progress is only visible
    # in the catalog and operational log.
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

    try:
        worker.request_reindex(on_progress=on_progress)
    except ReindexInProgress as exc:
        raise ApiError(409, _REINDEX_IN_PROGRESS, str(exc)) from None

    del stack, worker  # presence checked: unavailable paths raised above
    return {"status": "started"}
