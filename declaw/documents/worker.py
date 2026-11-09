"""One serialized indexing worker for every trigger (DCL-128, spec section 10).

Watcher-triggered indexing, manual reindex and startup reconciliation all feed
this ONE worker: a single ``run()`` task executes jobs one at a time, so the
vector store never sees concurrent writes from DeClaw's own machinery and one
run can never starve behind another at the Chroma level.

Retry is bounded and fake-clock testable: a failing path is attempted at
+0 s / +30 s / +5 min (offsets from the job's first readiness), then marked
failed — a catalog fail marker plus an ``index.failed`` progress frame. No
silent loss, no infinite retry. Cancelled-at-shutdown attempts are abandoned
with a warning instead (the next startup reconciliation re-runs the scan).

The handoff from the watchdog thread is owned by :class:`WatcherHandoff`
(loop-owned queue); this module consumes it, debouncing and coalescing keyed
by path on the loop side.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from declaw.documents.catalog import DocumentCatalog
from declaw.documents.indexer import DocumentIndexer, ProgressCallback
from declaw.documents.watcher import DEFAULT_DEBOUNCE_S, PathCoalescer, WatcherHandoff, WatcherEvent
from declaw.log import logger

RETRY_SCHEDULE_S: tuple[float, ...] = (0.0, 30.0, 300.0)

JobKind = Literal["index", "delete", "reindex"]


class ReindexInProgress(RuntimeError):
    """A reindex is queued or running; the route maps this to its 409."""


class _Job:
    __slots__ = ("kind", "path", "first_due", "attempts", "on_progress")

    def __init__(
        self,
        kind: JobKind,
        *,
        path: str | None = None,
        first_due: float = 0.0,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.kind: JobKind = kind
        self.path: str | None = path
        self.first_due: float = first_due
        self.attempts: int = 0
        self.on_progress: ProgressCallback | None = on_progress


class IndexingWorker:
    """The single executor behind every indexing trigger of the gateway."""

    def __init__(
        self,
        *,
        indexer: DocumentIndexer,
        catalog: DocumentCatalog | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        debounce_s: float = DEFAULT_DEBOUNCE_S,
        handoff: WatcherHandoff | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._indexer = indexer
        self._catalog = catalog
        self._on_event = on_event
        self._coalescer = PathCoalescer(debounce_s=debounce_s)
        self.handoff = handoff if handoff is not None else WatcherHandoff()
        self._clock = clock if clock is not None else time.monotonic
        self._sleep = sleep
        self._jobs: deque[_Job] = deque()
        self._scheduled: list[tuple[float, _Job]] = []  # heap of (due_at, job)
        self._task: asyncio.Task[None] | None = None
        self._reindex_active = False
        self._closing = False

    # --- producers ---------------------------------------------------------

    def start(self) -> None:
        """Start consuming on the running loop (idempotent, lazy-safe)."""
        if self._closing:
            raise RuntimeError("The indexing worker has stopped and cannot restart.")
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run())

    def request_reindex(self, *, on_progress: ProgressCallback | None = None) -> None:
        """Schedule one full reconciliation; refuse a concurrent one."""
        if self._closing:
            raise RuntimeError("The indexing worker has stopped and cannot accept runs.")
        if self._reindex_active or any(job.kind == "reindex" for job in self._jobs):
            raise ReindexInProgress(
                "A reindex is already running; it must finish before another starts."
            )
        self._jobs.append(_Job("reindex", on_progress=on_progress))
        self.start()
        self.handoff.wakeup()

    async def stop(self) -> None:
        """Drain the queue, then stop consuming (spec section 10 shutdown).

        The in-flight job is cancelled like an in-flight chat turn, pending
        retries are abandoned with a warning (startup reconciliation recovers
        them), and everything already observed — handed to the loop or
        coalesced — is executed once, serially, with no new retries. Only
        after that does the caller (the Application) stop the observer.
        """
        self._closing = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._scheduled:
            logger.warning(
                "document worker shutdown: abandoning {} pending retry timer(s); "
                "the next startup reconciliation re-runs the full scan",
                len(self._scheduled),
            )
            self._scheduled.clear()
        # Drop queued reindex runs: shutdown must not start a full scan.
        self._jobs = deque(job for job in self._jobs if job.kind != "reindex")
        # Drain everything the threads handed over plus the coalesced state.
        while True:
            try:
                item = self.handoff.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is not None:
                self._coalescer.note(item, now=self._clock())
        for event in self._coalescer.flush():
            job = self._job_for(event)
            if job is not None:
                self._jobs.append(job)
        while self._jobs:
            job = self._jobs.popleft()
            await self._execute(job, closing=True)

    # --- the single consumer loop -------------------------------------------

    async def run(self) -> None:
        """Execute one job at a time, forever, until cancelled by stop()."""
        while True:
            now = self._clock()
            self._admit_due(now)
            if self._jobs:
                job = self._jobs.popleft()
                await self._execute(job)
                continue
            await self._wait_for_work()

    async def _wait_for_work(self) -> None:
        """Block until an event arrives or the next deadline (retry/debounce) passes."""
        now = self._clock()
        next_due = self._coalescer.next_due()
        if self._scheduled:
            timed_due = self._scheduled[0][0]
            next_due = timed_due if next_due is None else min(next_due, timed_due)
        if next_due is None:
            item = await self.handoff.queue.get()
            if item is not None:
                self._coalescer.note(item, now=self._clock())
            return
        timeout = next_due - now
        if timeout <= 0:
            return
        getter = asyncio.ensure_future(self.handoff.queue.get())
        timer = asyncio.ensure_future(self._sleep(timeout))
        done, _pending = await asyncio.wait(
            {getter, timer}, return_when=asyncio.FIRST_COMPLETED
        )
        for pending in (getter, timer):
            if not pending.done():
                pending.cancel()
        if getter in done:
            item = getter.result()
            if item is not None:
                self._coalescer.note(item, now=self._clock())

    def _admit_due(self, now: float) -> None:
        while self._scheduled and self._scheduled[0][0] <= now:
            self._jobs.append(heapq.heappop(self._scheduled)[1])
        for event in self._coalescer.due(now=now):
            job = self._job_for(event)
            if job is not None:
                self._jobs.append(job)

    def _job_for(self, event: WatcherEvent) -> _Job | None:
        """Map a settled event to a job; fail closed outside the workspace."""
        try:
            resolved = event.path.resolve()
            relative = resolved.relative_to(self._indexer.workspace).as_posix()
        except (OSError, ValueError):
            logger.bind(
                event="documents.watch_outside_workspace", path=str(event.path)
            ).warning(
                "watcher event outside the workspace ignored: {} ({})", event.path, event.kind
            )
            return None
        kind: JobKind = "delete" if event.kind == "deleted" else "index"
        return _Job(kind, path=relative, first_due=self._clock())

    # --- execution -----------------------------------------------------------

    async def _execute(self, job: _Job, *, closing: bool = False) -> None:
        if job.kind == "reindex":
            await self._execute_reindex(job)
            return
        assert job.path is not None
        try:
            if job.kind == "index":
                report = await self._indexer.index_document(job.path)
                for warning in report.warnings:
                    logger.warning("indexing {}: {}", job.path, warning)
            else:  # delete: remove chunks + drop the catalog row
                await self._indexer.forget_document(job.path)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad path must not stop the worker
            job.attempts += 1
            await self._on_job_failure(job, exc, closing=closing)
            return
        await self._on_success(job)

    async def _execute_reindex(self, job: _Job) -> None:
        self._reindex_active = True
        try:
            report = await self._indexer.index(on_progress=job.on_progress)
            logger.info(
                "Reindex finished: indexed={} skipped={} failed={} removed={}",
                report.indexed,
                report.skipped,
                report.failed,
                report.removed,
            )
        except Exception:  # noqa: BLE001 - a background run must never crash the loop
            logger.exception("Reindex run failed")
        finally:
            self._reindex_active = False

    async def _on_job_failure(self, job: _Job, exc: Exception, *, closing: bool) -> None:
        assert job.path is not None
        if closing:
            # Shutdown: the attempt is abandoned, not failed — the next
            # startup reconciliation re-runs the full scan over the file.
            logger.warning(
                "document worker shutdown: attempt abandoned for {} ({})",
                job.path,
                exc,
            )
            return
        if job.attempts >= len(RETRY_SCHEDULE_S):
            logger.bind(event="documents.index_failed", path=job.path).warning(
                "indexing failed for {} after {} attempts: {}", job.path, job.attempts, exc
            )
            if self._catalog is not None:
                await self._catalog.record_failure(
                    relative_path=job.path,
                    error=f"{type(exc).__name__}: {exc}",
                    attempts=job.attempts,
                )
            self._emit(
                {
                    "type": "index.failed",
                    "path": job.path,
                    "error": f"{type(exc).__name__}: {exc}",
                    "attempts": job.attempts,
                }
            )
            return
        # Bounded backoff: attempt N+1 fires at first_ready + schedule[N]
        # (the pinned +0 s / +30 s / +5 min schedule never drifts when an
        # attempt runs late: a slow attempt does not push the next one out).
        due_at = max(self._clock(), job.first_due + RETRY_SCHEDULE_S[job.attempts])
        heapq.heappush(self._scheduled, (due_at, job))
        logger.info(
            "indexing attempt {} failed for {} ({}); retrying",
            job.attempts,
            job.path,
            exc,
        )

    async def _on_success(self, job: _Job) -> None:
        assert job.path is not None
        self._emit(
            {"type": "index.progress", "total": 1, "done": 1, "current_path": job.path}
        )
        if self._catalog is None:
            return
        await self._catalog.clear_failure(job.path)

    def _emit(self, frame: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(frame)
