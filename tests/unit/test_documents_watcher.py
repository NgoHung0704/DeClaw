"""Watcher handoff, delete/move mapping and loop-side debouncing (DCL-128, spec section 10).

The pre-Phase-9 ``ChangeBuffer`` dict was unsynchronized by construction:
watchdog threads wrote it while whoever drained it read it. It is REPLACED by
a loop-owned ``asyncio.Queue`` fed through ``loop.call_soon_threadsafe`` from
the watchdog thread, with the debounce/coalescing keying moved to the LOOP
side — same semantics as before, now single-threaded by construction.
Delete and move handling is new: a delete removes chunks + catalog row, a
move is delete-old + index-new (two events).
"""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Iterator
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from declaw.documents.watcher import (
    QUEUE_LIMIT,
    DocumentChangeHandler,
    DocumentWatcher,
    PathCoalescer,
    WatcherEvent,
    WatcherHandoff,
)


class Event:
    """Minimal stand-in for a watchdog filesystem event."""

    def __init__(
        self, path: str, is_directory: bool = False, dest_path: str | None = None
    ) -> None:
        self.src_path = path
        self.is_directory = is_directory
        self.dest_path = dest_path


class Recorder:
    """A sink that records every event handed to it."""

    def __init__(self) -> None:
        self.events: list[WatcherEvent] = []

    def __call__(self, event: WatcherEvent) -> None:
        self.events.append(event)


def _handler(sink: Recorder) -> DocumentChangeHandler:
    return DocumentChangeHandler(sink)


def _kinds(sink: Recorder) -> list[tuple[str, str]]:
    return [(str(event.path), event.kind) for event in sink.events]


def _p(path: str) -> str:
    """Platform-safe expected string of a Path."""
    return str(Path(path))


# --- The handler: every watchdog callback mapped onto the sink -------------


def test_created_and_modified_events_are_both_handed_over() -> None:
    sink = Recorder()
    handler = _handler(sink)
    handler.on_created(Event("/w/a.pdf"))
    handler.on_modified(Event("/w/b.docx"))
    assert _kinds(sink) == [(_p("/w/a.pdf"), "created"), (_p("/w/b.docx"), "modified")]


def test_deleted_events_are_handed_over() -> None:
    sink = Recorder()
    _handler(sink).on_deleted(Event("/w/gone.txt"))
    assert _kinds(sink) == [(_p("/w/gone.txt"), "deleted")]


def test_a_move_hands_over_delete_old_and_create_new() -> None:
    # A move is delete-old + index-new: exactly two events, in that order.
    sink = Recorder()
    _handler(sink).on_moved(Event("/w/old.txt", dest_path="/w/new.txt"))
    assert _kinds(sink) == [
        (_p("/w/old.txt"), "deleted"),
        (_p("/w/new.txt"), "created"),
    ]


def test_a_move_to_an_unsupported_name_only_hands_over_the_delete() -> None:
    sink = Recorder()
    _handler(sink).on_moved(Event("/w/old.txt", dest_path="/w/photo.png"))
    assert _kinds(sink) == [(_p("/w/old.txt"), "deleted")]


def test_the_handler_ignores_unsupported_extensions() -> None:
    sink = Recorder()
    handler = _handler(sink)
    handler.on_created(Event("/w/photo.png"))
    handler.on_deleted(Event("/w/song.mp3"))
    handler.on_moved(Event("/w/old.png", dest_path="/w/new.png"))
    assert sink.events == []


def test_the_handler_ignores_directory_events() -> None:
    sink = Recorder()
    handler = _handler(sink)
    handler.on_modified(Event("/w/dossier", is_directory=True))
    handler.on_deleted(Event("/w/dossier", is_directory=True))
    assert sink.events == []


def test_every_supported_document_type_is_watched() -> None:
    sink = Recorder()
    handler = _handler(sink)
    for name in ("a.pdf", "b.docx", "c.xlsx", "d.txt", "e.md", "f.markdown"):
        handler.on_created(Event(f"/w/{name}"))
    assert len(sink.events) == 6


def test_uppercase_extensions_are_recognised() -> None:
    sink = Recorder()
    _handler(sink).on_modified(Event("/w/CONTRAT.PDF"))
    assert _kinds(sink) == [(_p("/w/CONTRAT.PDF"), "modified")]


# --- DocumentWatcher: observer ownership -----------------------------------


def test_the_watcher_schedules_its_observer_over_the_folder(monkeypatch: Any) -> None:
    scheduled: list[tuple[Any, str, bool]] = []
    started: list[bool] = []
    stopped: list[bool] = []
    joined: list[Any] = []

    class FakeObserver:
        def schedule(self, handler: Any, path: str, recursive: bool) -> None:
            scheduled.append((handler, path, recursive))

        def start(self) -> None:
            started.append(True)

        def stop(self) -> None:
            stopped.append(True)

        def join(self, timeout: float = 5) -> None:
            joined.append(timeout)

    monkeypatch.setattr("declaw.documents.watcher.Observer", FakeObserver)
    watcher = DocumentWatcher(Path("/w"), sink=Recorder())
    watcher.start()
    assert len(scheduled) == 1
    assert scheduled[0][1:] == (_p("/w"), True)  # recursive watch of exactly the folder
    assert started == [True]

    watcher.stop()
    assert stopped == [True]
    assert joined == [5]


def test_stop_without_start_is_a_no_op(monkeypatch: Any) -> None:
    # The application's teardown may face a failed start() (failure-safe startup).
    monkeypatch.setattr("declaw.documents.watcher.Observer", type("X", (), {}))
    DocumentWatcher(Path("/w"), sink=Recorder()).stop()


def test_the_watcher_accepts_running_without_a_sink() -> None:
    # Gateway mode runs the watcher even when the document stack could not be
    # built; events are simply dropped rather than crashing the observer.
    watcher = DocumentWatcher(Path("/w"), sink=None)
    assert watcher.folder == Path("/w")


# --- Loop-side debounce/coalescing: semantics unchanged ---------------------


def test_a_noted_change_is_not_due_immediately() -> None:
    coalescer = PathCoalescer(debounce_s=2.0)
    coalescer.note(WatcherEvent(Path("a.txt"), "modified"), now=100.0)
    assert coalescer.due(now=100.5) == []


def test_a_change_becomes_due_after_the_debounce_window() -> None:
    coalescer = PathCoalescer(debounce_s=2.0)
    coalescer.note(WatcherEvent(Path("a.txt"), "modified"), now=100.0)
    assert [e.path for e in coalescer.due(now=102.1)] == [Path("a.txt")]


def test_repeated_writes_collapse_into_one_event() -> None:
    # A single 'Save' in Word emits several events; indexing once is correct.
    coalescer = PathCoalescer(debounce_s=2.0)
    for moment in (100.0, 100.3, 100.9):
        coalescer.note(WatcherEvent(Path("a.txt"), "modified"), now=moment)
    assert coalescer.pending_count == 1
    assert [e.path for e in coalescer.due(now=103.0)] == [Path("a.txt")]


def test_a_later_write_extends_the_window() -> None:
    coalescer = PathCoalescer(debounce_s=2.0)
    coalescer.note(WatcherEvent(Path("a.txt"), "modified"), now=100.0)
    coalescer.note(WatcherEvent(Path("a.txt"), "modified"), now=101.5)
    assert coalescer.due(now=102.1) == []
    assert [e.path for e in coalescer.due(now=103.6)] == [Path("a.txt")]


def test_due_clears_what_it_returned() -> None:
    coalescer = PathCoalescer(debounce_s=1.0)
    coalescer.note(WatcherEvent(Path("a.txt"), "modified"), now=100.0)
    assert coalescer.due(now=102.0)
    assert coalescer.due(now=103.0) == []
    assert coalescer.pending_count == 0


def test_several_files_are_returned_sorted() -> None:
    coalescer = PathCoalescer(debounce_s=1.0)
    for name in ("z.txt", "a.txt", "m.txt"):
        coalescer.note(WatcherEvent(Path(name), "created"), now=100.0)
    assert [e.path for e in coalescer.due(now=102.0)] == [
        Path("a.txt"),
        Path("m.txt"),
        Path("z.txt"),
    ]


def test_only_settled_files_are_returned() -> None:
    coalescer = PathCoalescer(debounce_s=2.0)
    coalescer.note(WatcherEvent(Path("settled.txt"), "created"), now=100.0)
    coalescer.note(WatcherEvent(Path("still-writing.txt"), "modified"), now=102.0)
    assert [e.path for e in coalescer.due(now=102.5)] == [Path("settled.txt")]


def test_the_latest_kind_wins_for_one_path() -> None:
    # Modified then deleted inside one window: the settled state is "deleted".
    coalescer = PathCoalescer(debounce_s=2.0)
    coalescer.note(WatcherEvent(Path("a.txt"), "modified"), now=100.0)
    coalescer.note(WatcherEvent(Path("a.txt"), "deleted"), now=100.5)
    due = coalescer.due(now=103.0)
    assert [(e.path, e.kind) for e in due] == [(Path("a.txt"), "deleted")]


def test_flush_returns_everything_regardless_of_timer() -> None:
    coalescer = PathCoalescer(debounce_s=2.0)
    coalescer.note(WatcherEvent(Path("b.txt"), "created"), now=100.0)
    coalescer.note(WatcherEvent(Path("a.txt"), "deleted"), now=100.1)
    flushed = coalescer.flush()
    assert [(e.path, e.kind) for e in flushed] == [
        (Path("a.txt"), "deleted"),
        (Path("b.txt"), "created"),
    ]
    assert coalescer.pending_count == 0


def test_next_due_reports_the_earliest_deadline() -> None:
    coalescer = PathCoalescer(debounce_s=2.0)
    assert coalescer.next_due() is None
    coalescer.note(WatcherEvent(Path("a.txt"), "created"), now=100.0)
    coalescer.note(WatcherEvent(Path("b.txt"), "created"), now=101.0)
    assert coalescer.next_due() == 102.0
    coalescer.due(now=102.0)
    assert coalescer.next_due() == 103.0
    coalescer.due(now=103.0)
    assert coalescer.next_due() is None


# --- The loop-owned handoff queue -------------------------------------------


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    """Fresh JSON log sink capturing operational warnings."""
    from declaw.log import configure, set_request_id

    buffer = io.StringIO()
    configure(level="WARNING", stream=buffer, force=True)
    try:
        yield buffer
    finally:
        set_request_id(None)


def _warned(buffer: io.StringIO) -> list[dict[str, Any]]:
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    records = [json.loads(line) for line in lines]
    return [record for record in records if record["level"] == "WARNING"]


def test_the_queue_cap_is_ten_thousand_pending_paths() -> None:
    assert QUEUE_LIMIT == 10_000


async def test_events_from_a_watchdog_thread_reach_the_loop_queue() -> None:
    handoff = WatcherHandoff()
    sink = handoff.submit_from_thread(asyncio.get_running_loop())

    thread = Thread(target=lambda: sink(WatcherEvent(Path("/w/a.txt"), "created")))
    thread.start()
    deadline = asyncio.get_running_loop().time() + 2.0
    while handoff.queue.empty() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    thread.join(timeout=2)

    event = handoff.queue.get_nowait()
    assert event is not None
    assert (event.path, event.kind) == (Path("/w/a.txt"), "created")


def test_a_full_queue_drops_the_oldest_event_with_a_warning(logs: io.StringIO) -> None:
    handoff = WatcherHandoff(limit=3)
    for index in range(4):
        handoff.offer(WatcherEvent(Path(f"/w/file{index}.txt"), "modified"))

    assert handoff.queue.qsize() == 3
    first = handoff.queue.get_nowait()
    assert first is not None
    assert first.path == Path("/w/file1.txt")

    warnings = _warned(logs)
    assert len(warnings) == 1
    assert "oldest" in warnings[0]["message"]
    assert warnings[0].get("extra", {}).get("event") == "documents.watch_queue_full"


def test_wakeup_places_a_sentinel_into_the_queue() -> None:
    # The worker's run loop is woken through the same queue.
    handoff = WatcherHandoff(limit=1)
    handoff.wakeup()
    assert handoff.queue.qsize() == 1
    assert handoff.queue.get_nowait() is None
