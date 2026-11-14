"""Notice changed documents, and hand them to the application loop (DCL-128, spec section 10).

Phase 8a built a :class:`ChangeBuffer` dict that watchdog threads wrote and
whoever drained it read — unsynchronized by construction. It is REPLACED by
the design chosen in spec section 10: watchdog callbacks run on a watchdog
thread and hand events to the app loop via
``loop.call_soon_threadsafe(queue.put_nowait, ...)`` into a **loop-owned
:class:`asyncio.Queue`** (capped at 10 000 pending paths — a full queue drops
the OLDEST event with an operational-log warning). The debounce/coalescing
keyed by path lives on the LOOP side now (:class:`PathCoalescer`), so the
settle semantics are the old ones, single-threaded by construction.

Delete and move are captured too, because a right-to-erasure argument cuts
both ways: a deleted document must leave the index. ``on_deleted`` maps to
chunks + catalog row removal; ``on_moved`` is delete-old + index-new (two
events).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from declaw.documents.indexer import SUPPORTED_SUFFIXES
from declaw.log import logger

DEFAULT_DEBOUNCE_S = 2.0
QUEUE_LIMIT = 10_000

ChangeKind = Literal["created", "modified", "deleted"]


@dataclass(frozen=True, slots=True)
class WatcherEvent:
    """One filtered filesystem event, on its way to the loop."""

    path: Path
    kind: ChangeKind


class DocumentChangeHandler(FileSystemEventHandler):
    """Watchdog-thread side: filter, map and hand each event to ``sink``.

    ``sink`` must be safe to call from the watchdog thread — in practice the
    ``submit_from_thread()`` callable of a :class:`WatcherHandoff`, which
    crosses to the loop with ``loop.call_soon_threadsafe``. Unfiltered
    extensions and directory events are dropped here, before the queue spends
    capacity on them.
    """

    def __init__(self, sink: Callable[[WatcherEvent], None]) -> None:
        self._sink = sink

    def _accept(self, event: object, path_text: str, kind: ChangeKind) -> None:
        if getattr(event, "is_directory", False):
            return
        path = Path(path_text)
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return
        self._sink(WatcherEvent(path, kind))

    def on_created(self, event: object) -> None:
        self._accept(event, str(getattr(event, "src_path", "")), "created")

    def on_modified(self, event: object) -> None:
        self._accept(event, str(getattr(event, "src_path", "")), "modified")

    def on_deleted(self, event: object) -> None:
        self._accept(event, str(getattr(event, "src_path", "")), "deleted")

    def on_moved(self, event: object) -> None:
        # A move is delete-old + index-new, in that order.
        self._accept(event, str(getattr(event, "src_path", "")), "deleted")
        self._accept(event, str(getattr(event, "dest_path", "")), "created")


class DocumentWatcher:
    """Owns a watchdog observer over one folder.

    Still deliberately thin: events go to ``sink`` and that is all. The loop
    side (queue, debounce, retries, indexing) is :mod:`declaw.documents.worker`
    — the gateway wires the two together in ``Application.start()``.
    """

    def __init__(
        self,
        folder: Path,
        *,
        sink: Callable[[WatcherEvent], None] | None = None,
    ) -> None:
        self.folder = folder
        self._sink = sink
        self._handler = DocumentChangeHandler(sink if sink is not None else _drop)
        self._observer: BaseObserver | None = None

    def start(self) -> None:
        observer = Observer()
        observer.schedule(self._handler, str(self.folder), recursive=True)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None


def _drop(event: WatcherEvent) -> None:
    """Sink for a watcher running without a consumer (no document stack)."""


class WatcherHandoff:
    """The loop-owned queue watchdog threads feed through the app loop.

    The thread side never touches the queue directly: it calls
    ``loop.call_soon_threadsafe(offer, event)`` so items only ever appear
    from inside the loop, making the queue single-threaded by construction.
    A queue at capacity (10 000 pending paths) drops the OLDEST event and
    warns in the operational log — dropping the newest would starve paths
    whose first event is old.
    """

    def __init__(self, *, limit: int = QUEUE_LIMIT) -> None:
        self.queue: asyncio.Queue[WatcherEvent | None] = asyncio.Queue(maxsize=limit)

    def submit_from_thread(self, loop: asyncio.AbstractEventLoop) -> Callable[[WatcherEvent], None]:
        """Build the thread-safe sink a watchdog handler calls home with."""

        def submit(event: WatcherEvent) -> None:
            try:
                loop.call_soon_threadsafe(self.offer, event)
            except RuntimeError:
                # The loop is gone (shutdown race): the event is unobservable.
                logger.debug(f"watcher event dropped (loop closed): {event.path}")

        return submit

    def offer(self, event: WatcherEvent | None) -> None:
        """Queue one item from the loop thread, dropping the oldest when full."""
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            dropped = self.queue.get_nowait()
            logger.bind(
                event="documents.watch_queue_full",
                dropped_path=str(dropped.path) if dropped is not None else "wakeup",
            ).warning(
                "document watcher queue full: dropping the oldest event "
                "(the file will be picked up by the next full reconciliation)"
            )
            self.queue.put_nowait(event)

    def wakeup(self) -> None:
        """Wake a blocked consumer from the loop thread (shutdown/submit)."""
        self.offer(None)


@dataclass(slots=True)
class _Entry:
    event: WatcherEvent
    due_at: float


class PathCoalescer:
    """Loop-side debounce/coalescing keyed by path.

    Same settle semantics as the ``ChangeBuffer`` it replaced: one Save's
    several events collapse into one; a later write restarts the window; the
    latest KIND wins (modify-then-delete settles as delete). Now touched only
    from the loop, so it needs no lock.
    """

    def __init__(self, debounce_s: float = DEFAULT_DEBOUNCE_S) -> None:
        self._debounce_s = debounce_s
        self._pending: dict[Path, _Entry] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def note(self, event: WatcherEvent, *, now: float) -> None:
        """Record that ``path`` changed, restarting its settle timer."""
        self._pending[event.path] = _Entry(event=event, due_at=now + self._debounce_s)

    def due(self, *, now: float) -> list[WatcherEvent]:
        """Return and clear the paths quiet long enough, sorted by path."""
        settled = [entry.event for path, entry in self._pending.items() if entry.due_at <= now]
        settled.sort(key=lambda event: event.path)
        for event in settled:
            del self._pending[event.path]
        return settled

    def flush(self) -> list[WatcherEvent]:
        """Return and clear EVERYTHING now (shutdown drain: no more timers)."""
        flushed = [entry.event for _, entry in self._pending.items()]
        flushed.sort(key=lambda event: event.path)
        self._pending.clear()
        return flushed

    def next_due(self) -> float | None:
        """The earliest deadline among the pending paths, if any."""
        return min((entry.due_at for entry in self._pending.values()), default=None)
