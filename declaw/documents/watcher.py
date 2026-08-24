"""Notice changed documents, and wait until they have settled.

DCL-109. **Nothing starts this in Phase 8a.** The component is built and tested
here so that Phase 9 — where the gateway finally provides a long-lived process
— wires an already-proven piece rather than writing one under time pressure.
MVP DoD #2 is served by ``declaw index``, which needs no daemon.

Debouncing is the substance. One "Save" in Word emits several filesystem
events, and re-indexing a half-written file wastes work and can simply fail.
``ChangeBuffer`` holds the clock at arm's length so the whole policy is tested
without a single real second passing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from declaw.documents.indexer import SUPPORTED_SUFFIXES

DEFAULT_DEBOUNCE_S = 2.0


class ChangeBuffer:
    """Paths seen changing, released once they stop changing."""

    def __init__(self, debounce_s: float = DEFAULT_DEBOUNCE_S) -> None:
        self._debounce_s = debounce_s
        self._last_seen: dict[Path, float] = {}

    @property
    def pending_count(self) -> int:
        return len(self._last_seen)

    def note(self, path: Path, *, now: float) -> None:
        """Record that ``path`` changed, restarting its settle timer."""
        self._last_seen[path] = now

    def due(self, *, now: float) -> list[Path]:
        """Return and clear the paths that have been quiet long enough."""
        settled = sorted(
            path for path, seen in self._last_seen.items() if now - seen >= self._debounce_s
        )
        for path in settled:
            del self._last_seen[path]
        return settled


class DocumentChangeHandler(FileSystemEventHandler):
    """Feeds a :class:`ChangeBuffer` from watchdog events."""

    def __init__(
        self, buffer: ChangeBuffer, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._buffer = buffer
        self._clock = clock

    def _note(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            return
        self._buffer.note(path, now=self._clock())

    def on_created(self, event: Any) -> None:
        self._note(event)

    def on_modified(self, event: Any) -> None:
        self._note(event)


class DocumentWatcher:
    """Owns a watchdog observer over one folder.

    Deliberately dumb: it fills a buffer and nothing more. Whoever runs the
    event loop decides how often to drain it and what to do with the result —
    which in Phase 9 will be the gateway.
    """

    def __init__(
        self,
        folder: Path,
        buffer: ChangeBuffer | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.folder = folder
        self.buffer = buffer if buffer is not None else ChangeBuffer()
        self._handler = DocumentChangeHandler(self.buffer, clock=clock)
        self._observer: Any | None = None

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
