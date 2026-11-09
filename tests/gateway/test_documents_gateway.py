"""Documents over the gateway: watcher handoff + one serialized worker (DCL-128, spec section 10).

What is pinned here:

- ONE serialized indexing worker: watcher-triggered indexing, manual
  reindex and startup reconciliation all funnel through it; nothing runs
  concurrently behind its back.
- Bounded retry, fake-clock driven: a failing path is attempted at
  +0 s / +30 s / +5 min, then marked failed (catalog row + progress frame),
  never retried forever.
- Delete removes chunks + catalog row; a move is delete-old + index-new.
- Blocking Chroma calls leave the loop free: a ticker (the "concurrent chat
  turn" stand-in) keeps ticking during indexing with a sleep-instrumented
  store, and real Chroma survives concurrent threaded reads/writes (spec
  section 10 coordination test — if this failed, reads would have to
  serialize through the same worker).
- Gateway-mode-only wiring in Application.start(), and shutdown drains the
  watcher queue BEFORE the observer stops.
- Failed paths are visible: the catalog listing marks them, the REST route
  surfaces the marker, and POST /api/documents/reindex feeds the worker.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from declaw.app import Application
from declaw.config import Settings
from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.db.models import DocumentIndexFailure, IndexedDocument
from declaw.documents.indexer import DocumentIndexer, IndexProgress, IndexReport
from declaw.documents.models import DocumentChunk
from declaw.documents.search import ChunkSanitizer
from declaw.documents.store import DocumentStore
from declaw.documents.watcher import WatcherEvent
from declaw.gateway.app import create_app
from declaw.gateway.auth import mint_gateway_token
from declaw.memory.chroma import build_chroma_client, get_collection

TEST_PORT = 9000  # never the default 7842 (same convention as test_rest)
BIND_AUTHORITY = f"127.0.0.1:{TEST_PORT}"
ALLOWED_ORIGIN = f"http://{BIND_AUTHORITY}"


# --- Shared fakes -----------------------------------------------------------


class FakeClock:
    """Manual clock: sleep() records the wait and advances time instantly."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


class PausingClock(FakeClock):
    """Sleep() parks the RETRY waits (30 s / 5 min); short waits pass through."""

    def __init__(self, now: float = 1000.0) -> None:
        super().__init__(now)
        self.gate = asyncio.Event()

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds >= 30.0:  # the retry waits only — not the 2 s debounce
            await self.gate.wait()
        self.now += seconds


class FakeCatalog:
    def __init__(self) -> None:
        self.failures: list[tuple[str, str, int]] = []
        self.cleared: list[str] = []

    async def record_failure(self, *, relative_path: str, error: str, attempts: int) -> None:
        self.failures.append((relative_path, error, attempts))

    async def clear_failure(self, relative_path: str) -> None:
        self.cleared.append(relative_path)


class FakeIndexer:
    """The worker's view of a DocumentIndexer: single paths, deletes, full runs."""

    def __init__(
        self,
        workspace: Path,
        *,
        clock: Callable[[], float] | None = None,
        failures: set[str] | None = None,
        park_runs: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.clock = clock if clock is not None else (lambda: 0.0)
        self.failures = failures if failures is not None else set()  # relative paths that explode
        self.park_runs = park_runs
        self.parked: list[Any] = []  # one future per parked run, FIFO
        self.events = events if events is not None else []
        self.indexed_calls: list[tuple[str, float]] = []  # (relative, clock at attempt)
        self.forgotten: list[str] = []
        self.full_started = 0
        self.full_finished = 0

    async def index(
        self, folder: Path | None = None, *, on_progress: Callable[[IndexProgress], None] | None = None
    ) -> IndexReport:
        # The full-scan reconciliation (manual reindex + startup run).
        self.full_started += 1
        if self.park_runs:
            future = asyncio.get_running_loop().create_future()
            self.parked.append(future)
            await future
        if on_progress is not None:
            on_progress(IndexProgress(done=1, total=1, path="progress.txt"))
        self.full_finished += 1
        return IndexReport(indexed=self.full_finished)

    def release_next_run(self) -> None:
        """Release the oldest parked run (called from the loop that parked it)."""
        self.parked.pop(0).set_result(True)

    async def index_document(self, relative: str) -> IndexReport:
        self.indexed_calls.append((relative, self.clock()))
        self.events.append(f"index:{relative}")
        if relative in self.failures:
            raise IndexError(f"parser exploded for {relative}")
        return IndexReport(indexed=1)

    async def forget_document(self, relative: str) -> None:
        self.forgotten.append(relative)
        self.events.append(f"forget:{relative}")


async def soon(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    """Await a background-work condition without real-time flakiness."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return predicate()


def make_worker(
    indexer: Any,
    catalog: Any = None,
    on_event: Any = None,
    *,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Any] | None = None,
    debounce_s: float = 2.0,
) -> Any:
    from declaw.documents.worker import IndexingWorker

    kwargs: dict[str, Any] = {
        "indexer": indexer,
        "clock": clock if clock is not None else time.monotonic,
        "sleep": sleep if sleep is not None else asyncio.sleep,
        "debounce_s": debounce_s,
    }
    if catalog is not None:
        kwargs["catalog"] = catalog
    if on_event is not None:
        kwargs["on_event"] = on_event
    return IndexingWorker(**kwargs)


# --- Application harness (fake services, fake stack, real worker) ----------


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "port": TEST_PORT,
        "data_dir": tmp_path / "data",
        "workspace_dir": tmp_path / "workspace",
        "sanitizer_required": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[call-arg]


def _gateway(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    settings: Settings,
    *,
    mode: str = "gateway",
    stack: Any = None,
) -> Application:
    """An Application whose services are recording fakes, with an optional fake stack."""
    import declaw.app as app_module

    class FakeHost:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            events.append("host.start")

        async def stop(self) -> None:
            events.append("host.stop")

        def failures(self) -> list[str]:
            return []

        def model_tools(self) -> list[Any]:
            return []

        def loaded(self) -> list[Any]:
            if stack is not None:
                from types import SimpleNamespace

                return [SimpleNamespace(manifest=SimpleNamespace(name="doc-intel"))]
            return []

    class FakeWatcher:
        def __init__(self, folder: Path, *args: Any, sink: Any = None, **kwargs: Any) -> None:
            self.folder = folder
            self.sink = sink
            events.append("watcher.new")

        def start(self) -> None:
            events.append("watcher.start")

        def stop(self) -> None:
            events.append("watcher.stop")

    class FakeMonitor:
        def __init__(self, audit: Any, **kwargs: Any) -> None:
            pass

        def install(self) -> None:
            events.append("monitor.install")

        def uninstall(self) -> None:
            events.append("monitor.uninstall")

    class FakeEngine:
        async def dispose(self) -> None:
            events.append("engine.dispose")

    monkeypatch.setattr(app_module, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(app_module, "get_sessionmaker", lambda: object())
    monkeypatch.setattr(app_module, "DbAuditLogger", lambda sessionmaker: object())
    monkeypatch.setattr(app_module, "ensure_schema", _fake_ensure_schema)
    monkeypatch.setattr(app_module, "PluginHost", FakeHost)
    monkeypatch.setattr(app_module, "DocumentWatcher", FakeWatcher)
    monkeypatch.setattr(app_module, "EgressMonitor", FakeMonitor)
    monkeypatch.setattr(app_module, "load_state", lambda data_dir: object())
    monkeypatch.setattr(app_module, "load_grants", lambda data_dir: object())
    monkeypatch.setattr(app_module, "default_registry", _fake_registry)
    if stack is not None:
        import declaw.documents.session as session_module

        monkeypatch.setattr(session_module, "build_document_stack", _fake_stack_builder(stack))
    return Application(settings, mode=mode)  # type: ignore[arg-type]


async def _fake_ensure_schema(engine: Any) -> None:
    return None


def _fake_registry() -> Any:
    return type("FakeRegistry", (), {
        "register_instance": lambda self, tool: None,
        "langchain_tools": lambda self, *a, **k: [],
    })()


def _fake_stack_builder(stack: Any) -> Any:
    def build(settings: Any, host: Any, *, sanitizer: Any = None) -> Any:
        return stack

    return build


# --- Gateway wiring: worker, startup reconciliation, shutdown order --------


async def test_gateway_start_builds_one_worker_and_reconciles_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    indexer = FakeIndexer(tmp_path / "workspace")
    stack = _fake_stack(tmp_path, indexer)
    app = _gateway(
        monkeypatch, events, stack=stack, settings=_settings(tmp_path, workspace_dir=tmp_path / "workspace")
    )
    await app.start()

    assert app.document_worker is not None
    assert await soon(lambda: indexer.full_finished == 1), "startup reconciliation must run once"
    await asyncio.sleep(0.05)
    assert indexer.full_finished == 1  # once — not a loop

    assert "watcher.start" in events
    await app.shutdown()
    assert "watcher.stop" in events


async def test_cli_mode_builds_no_worker_even_with_a_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    indexer = FakeIndexer(tmp_path / "workspace")
    stack = _fake_stack(tmp_path, indexer)
    app = _gateway(
        monkeypatch, events, mode="cli", stack=stack, settings=_settings(tmp_path)
    )
    await app.start()
    assert app.document_worker is None
    assert app.watcher is None
    assert indexer.full_finished == 0
    await app.shutdown()


async def test_shutdown_drains_pending_events_before_the_observer_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    indexer = FakeIndexer(tmp_path / "workspace", events=events)
    stack = _fake_stack(tmp_path, indexer)
    app = _gateway(
        monkeypatch, events, stack=stack, settings=_settings(tmp_path, workspace_dir=tmp_path / "workspace")
    )
    await app.start()
    assert await soon(lambda: indexer.full_finished == 1)

    # Two events still queued when shutdown begins: drain must process them.
    assert app.document_worker is not None
    loop = asyncio.get_running_loop()
    sink = app.document_worker.handoff.submit_from_thread(loop)
    sink(WatcherEvent(tmp_path / "workspace" / "late.txt", "created"))
    sink(WatcherEvent(tmp_path / "workspace" / "gone.txt", "deleted"))

    await app.shutdown()
    assert "index:late.txt" in events
    assert "gone.txt" in indexer.forgotten
    assert events.index("index:late.txt") < events.index("watcher.stop"), (
        "shutdown must drain the queue BEFORE stopping the observer"
    )
    assert events.index("forget:gone.txt") < events.index("watcher.stop")


def _fake_stack(tmp_path: Path, indexer: Any) -> Any:
    from declaw.documents.session import DocumentStack

    return DocumentStack(
        store=None,  # type: ignore[arg-type]
        catalog=None,  # type: ignore[arg-type]
        indexer=indexer,  # type: ignore[arg-type]
        chunk_sanitizer=ChunkSanitizer(None),
    )


# --- The single serialized worker ------------------------------------------


async def test_watcher_jobs_wait_for_a_running_full_reindex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spec section 10: watcher, manual and startup triggers feed ONE worker —
    # a parked full run holds a watcher-triggered index, it never overtakes.
    from declaw.documents.worker import ReindexInProgress

    workspace = tmp_path / "workspace"
    indexer = FakeIndexer(workspace, park_runs=True)
    worker = make_worker(indexer, debounce_s=0.05)

    worker.request_reindex()  # the manual job
    assert await soon(lambda: indexer.full_started == 1)
    worker.handoff.offer(WatcherEvent(workspace / "a.txt", "created"))

    await asyncio.sleep(0.3)
    assert [path for path, _ in indexer.indexed_calls] == [], "worker must serialize: no job runs beside a full reindex"

    with pytest.raises(ReindexInProgress):
        worker.request_reindex()

    indexer.release_next_run()
    assert await soon(lambda: [path for path, _ in indexer.indexed_calls] == ["a.txt"])
    assert indexer.full_finished == 1
    await worker.stop()


async def test_events_reach_the_worker_through_the_handoff_queue(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    indexer = FakeIndexer(workspace)
    worker = make_worker(indexer, debounce_s=0.05)
    worker.handoff.offer(WatcherEvent(workspace / "a.txt", "created"))
    worker.start()

    assert await soon(lambda: [path for path, _ in indexer.indexed_calls] == ["a.txt"])
    await worker.stop()


async def test_repeated_events_for_one_path_are_coalesced_into_one_job(tmp_path: Path) -> None:
    # Debounce semantics unchanged: several saves of one file = one index.
    clock = FakeClock(1000.0)
    indexer = FakeIndexer(tmp_path / "workspace", clock=clock)
    worker = make_worker(indexer, clock=clock, sleep=clock.sleep)

    for _ in range(3):
        worker.handoff.offer(WatcherEvent(tmp_path / "workspace" / "a.txt", "modified"))
    worker.start()
    assert await soon(lambda: len(indexer.indexed_calls) == 1)
    # Nothing more fires afterwards even though the window kept restarting.
    await asyncio.sleep(0.05)
    assert len(indexer.indexed_calls) == 1
    await worker.stop()


async def test_a_delete_event_removes_chunks_and_the_catalog_row(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    indexer = FakeIndexer(workspace)
    worker = make_worker(indexer, debounce_s=0.05)
    worker.handoff.offer(WatcherEvent(workspace / "gone.txt", "deleted"))
    worker.start()
    assert await soon(lambda: indexer.forgotten == ["gone.txt"])
    await worker.stop()


async def test_a_move_deletes_the_old_path_and_indexes_the_new(tmp_path: Path) -> None:
    # on_moved already maps to delete-old + created-new at the handler; the
    # worker turns the two settled events into the two actions.
    workspace = tmp_path / "workspace"
    indexer = FakeIndexer(workspace)
    worker = make_worker(indexer, debounce_s=0.05)
    worker.handoff.offer(WatcherEvent(workspace / "old.txt", "deleted"))
    worker.handoff.offer(WatcherEvent(workspace / "new.txt", "created"))
    worker.start()
    assert await soon(lambda: indexer.forgotten == ["old.txt"])
    assert await soon(lambda: [path for path, _ in indexer.indexed_calls] == ["new.txt"])
    await worker.stop()


async def test_events_outside_the_workspace_are_ignored(tmp_path: Path) -> None:
    # Fail-closed containment: the observer watches the workspace, but a
    # symlinked/junctioned escape must never turn into an indexing job.
    workspace = tmp_path / "workspace"
    indexer = FakeIndexer(workspace)
    worker = make_worker(indexer, debounce_s=0.05)
    worker.handoff.offer(WatcherEvent(tmp_path / "elsewhere.txt", "created"))
    worker.start()
    await asyncio.sleep(0.2)
    assert indexer.indexed_calls == []
    assert indexer.forgotten == []
    await worker.stop()


# --- Bounded retry: 0 s / 30 s / 5 min, then failed --------------------------


async def test_retry_schedule_then_marked_failed_no_infinite_retry(tmp_path: Path) -> None:
    clock = FakeClock(1000.0)
    workspace = tmp_path / "workspace"
    indexer = FakeIndexer(workspace, clock=clock, failures={"boom.txt"})
    catalog = FakeCatalog()
    frames: list[dict[str, Any]] = []
    worker = make_worker(
        indexer, catalog, on_event=frames.append, clock=clock, sleep=clock.sleep, debounce_s=2.0
    )
    worker.handoff.offer(WatcherEvent(workspace / "boom.txt", "created"))
    worker.start()

    assert await soon(lambda: len(catalog.failures) == 1), "must give up after the schedule"
    await worker.stop()

    attempt_offsets = [stamp - indexer.indexed_calls[0][1] for _, stamp in indexer.indexed_calls]
    assert attempt_offsets == [0.0, 30.0, 300.0], attempt_offsets  # the pinned schedule
    assert clock.sleeps == [2.0, 30.0, 270.0]  # debounce + the two retry waits

    # Marked failed: catalog record + progress-stream frame, exactly once.
    assert catalog.failures == [("boom.txt", "IndexError: parser exploded for boom.txt", 3)]
    failure_frames = [frame for frame in frames if frame.get("type") == "index.failed"]
    assert failure_frames == [
        {"type": "index.failed", "path": "boom.txt", "error": "IndexError: parser exploded for boom.txt", "attempts": 3}
    ]

    # No infinite retry: nothing fires again after the marking.
    clock.advance_far = True  # type: ignore[attr-defined]
    for _ in range(10):
        await asyncio.sleep(0)
    assert len(indexer.indexed_calls) == 3


async def test_a_retry_that_recovers_needs_no_failure_marker(tmp_path: Path) -> None:
    clock = FakeClock(1000.0)
    workspace = tmp_path / "workspace"
    indexer = FlakyIndexer(workspace, clock=clock, fail_times=1)
    catalog = FakeCatalog()
    frames: list[dict[str, Any]] = []
    worker = make_worker(
        indexer, catalog, on_event=frames.append, clock=clock, sleep=clock.sleep, debounce_s=2.0
    )
    worker.handoff.offer(WatcherEvent(workspace / "a.txt", "created"))
    worker.start()

    assert await soon(lambda: len(indexer.indexed_calls) == 2)
    await worker.stop()

    assert catalog.failures == []  # recovered: no marker
    assert catalog.cleared == ["a.txt"]
    progress = [frame for frame in frames if frame.get("type") == "index.progress"]
    assert progress == [{"type": "index.progress", "total": 1, "done": 1, "current_path": "a.txt"}]


async def test_shutdown_abandons_pending_retries_without_marking_failed(tmp_path: Path) -> None:
    # A retry still waiting when the gateway stops is not a failure: the next
    # startup reconciliation re-runs the full scan anyway.
    clock = PausingClock(1000.0)
    workspace = tmp_path / "workspace"
    indexer = FakeIndexer(workspace, clock=clock, failures={"boom.txt"})
    catalog = FakeCatalog()
    worker = make_worker(indexer, catalog, clock=clock, sleep=clock.sleep, debounce_s=2.0)
    worker.handoff.offer(WatcherEvent(workspace / "boom.txt", "created"))
    worker.start()
    assert await soon(lambda: len(indexer.indexed_calls) == 1)
    await asyncio.sleep(0.05)  # the second attempt parks in its 30 s wait

    await worker.stop()
    assert len(indexer.indexed_calls) == 1
    assert catalog.failures == []


class FlakyIndexer(FakeIndexer):
    """Fails the first N attempts for every path, then succeeds."""

    def __init__(
        self, workspace: Path, *, clock: Callable[[], float] | None = None, fail_times: int = 1
    ) -> None:
        super().__init__(workspace, clock=clock)
        self.fail_times = fail_times

    async def index_document(self, relative: str) -> IndexReport:
        self.indexed_calls.append((relative, self.clock()))
        if len(self.indexed_calls) <= self.fail_times:
            self.events.append(f"index:{relative}")
            raise IndexError(f"parser exploded for {relative}")
        self.events.append(f"index:{relative}")
        return IndexReport(indexed=1)


# --- Blocking work: the loop must stay free ----------------------------------


class SleepyCollection:
    """A Chroma collection whose every call blocks for a while (time.sleep)."""

    def __init__(self, seconds: float = 0.05) -> None:
        self._seconds = seconds

    def add(self, **kwargs: Any) -> None:
        time.sleep(self._seconds)

    def query(self, **kwargs: Any) -> dict[str, Any]:
        time.sleep(self._seconds)
        return {
            "ids": [["c1"]],
            "documents": [["safe text"]],
            "metadatas": [[{"doc_id": "d1", "path": "a.txt", "ordinal": 0}]],
            "distances": [[0.1]],
        }

    def count(self) -> int:
        time.sleep(self._seconds)
        return 1

    def delete(self, **kwargs: Any) -> None:
        time.sleep(self._seconds)


async def _embed(texts: list[str]) -> list[list[float]]:
    return [[float(len(t)), 1.0] for t in texts]


async def test_blocking_chroma_calls_do_not_stall_the_loop() -> None:
    from declaw.documents.models import document_id

    store = DocumentStore(SleepyCollection(0.05), _embed)  # type: ignore[arg-type]

    ticks = {"count": 0}
    stop = asyncio.Event()

    async def chat_turn_heartbeat() -> None:
        # The "concurrent chat turn keeps ticking" stand-in.
        while not stop.is_set():
            ticks["count"] += 1
            await asyncio.sleep(0.002)

    heartbeat = asyncio.create_task(chat_turn_heartbeat())
    before = ticks["count"]

    chunks = [DocumentChunk(text="clause", ordinal=0)]
    await store.add_document(document_id("a.txt"), "a.txt", chunks)  # blocks ~0.05 s
    during_add = ticks["count"]

    hits = await store.search("clause", k=1)  # count + query, both blocking
    during_search = ticks["count"]
    stop.set()
    await heartbeat

    assert before < during_add < during_search, "the loop stayed live during blocked calls"
    assert ticks["count"] >= 5, "many heartbeats must have been serviced"
    assert hits and hits[0].text == "safe text"


async def test_chroma_survives_concurrent_threaded_reads_and_writes(tmp_path: Path) -> None:
    # Spec section 10 coordination: rely on Chroma's thread safety only if a
    # dedicated test says so. If this flips red, reads must serialize through
    # the worker inste.
    from declaw.documents.models import document_id

    client = build_chroma_client(tmp_path / "chroma")
    collection = get_collection(client, "documents")
    store = DocumentStore(collection, _embed)
    chunks = [DocumentChunk(text=f"content {index}", ordinal=index) for index in range(3)]

    await asyncio.gather(
        store.add_document(document_id("a.txt"), "a.txt", chunks),
        store.add_document(document_id("b.txt"), "b.txt", chunks),
        store.search("content"),
        store.search("content"),
        store.delete_document(document_id("b.txt")),
    )


async def test_a_concurrent_chat_turn_keeps_ticking_during_a_reindex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The full indexer path with a sleep-instrumented store: hashing, parsing
    # and storing three documents while the heartbeat keeps being serviced.
    from declaw.documents.catalog import DocumentCatalog

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(workspace))
    from declaw.config import get_settings

    get_settings.cache_clear()

    engine = build_engine(tmp_path / "declaw.db")
    await ensure_schema(engine)
    try:
        store = DocumentStore(SleepyCollection(0.05), _embed)  # type: ignore[arg-type]
        catalog = DocumentCatalog(build_sessionmaker(engine))

        async def parse(path: str) -> dict[str, Any]:
            return {
                "doc_type": "text",
                "truncated": False,
                "chunks": [{"text": f"content of {Path(path).name}", "ordinal": 0}],
            }

        indexer = DocumentIndexer(
            parse=parse,  # type: ignore[arg-type]
            store=store,
            catalog=catalog,
            workspace=workspace,
        )
        for name in ("a.txt", "b.txt", "c.txt"):
            (workspace / name).write_text(f"hello {name}", encoding="utf-8")

        ticks = {"count": 0}
        stop = asyncio.Event()

        async def chat_turn_heartbeat() -> None:
            while not stop.is_set():
                ticks["count"] += 1
                await asyncio.sleep(0.005)

        heartbeat = asyncio.create_task(chat_turn_heartbeat())
        before = ticks["count"]
        report = await indexer.index()
        stop.set()
        await heartbeat

        assert report.indexed == 3
        assert ticks["count"] > before + 5, "the reindex must not have monopolized the loop"
    finally:
        await engine.dispose()
        get_settings.cache_clear()


# --- REST surface: failure visibility + reindex through the worker -----------


class _FakeSecretStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.data.get(name)

    def set(self, name: str, value: str) -> None:
        self.data[name] = value

    def delete(self, name: str) -> bool:
        return self.data.pop(name, None) is not None

    def purge(self, names: tuple[str, ...] = ()) -> int:
        return sum(1 for name in names if self.delete(name))


class _FakeWatcherRoute:
    def __init__(self, folder: Path, *args: Any, sink: Any = None, **kwargs: Any) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _FakeMonitor:
    def __init__(self, audit: Any, **kwargs: Any) -> None:
        pass

    def install(self) -> None:
        pass

    def uninstall(self) -> None:
        pass


class RouteStack:
    """A real gateway app over a tmp DB; the Application gets a fake stack."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, indexer: Any) -> None:
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.engine = build_engine(self.data_dir / "declaw.db")
        self.sessionmaker = build_sessionmaker(self.engine)
        monkeypatch.setattr("declaw.app.get_engine", lambda: self.engine)
        monkeypatch.setattr("declaw.app.get_sessionmaker", lambda: self.sessionmaker)
        monkeypatch.setattr("declaw.app.DocumentWatcher", _FakeWatcherRoute)
        monkeypatch.setattr("declaw.app.EgressMonitor", _FakeMonitor)

        self.settings = _settings(tmp_path, data_dir=self.data_dir)
        self.application = Application(self.settings, mode="gateway")
        import declaw.app as app_module
        import declaw.documents.session as session_module

        class _NoHost:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            def failures(self) -> list[str]:
                return []

            def model_tools(self) -> list[Any]:
                return []

            def loaded(self) -> list[Any]:
                from types import SimpleNamespace

                # Pretend doc-intel loaded: build_document_stack (patched below)
                # then returns the fake stack, so start() builds a real worker.
                return [SimpleNamespace(manifest=SimpleNamespace(name="doc-intel"))]

        class _NoEngine:
            async def dispose(self) -> None:
                pass

        monkeypatch.setattr(app_module, "PluginHost", _NoHost)
        monkeypatch.setattr(app_module, "default_registry", _fake_registry)
        monkeypatch.setattr(app_module, "load_state", lambda data_dir: object())
        monkeypatch.setattr(app_module, "load_grants", lambda data_dir: object())

        def build_stack(settings: Any, host: Any, *, sanitizer: Any = None) -> Any:
            return _fake_stack(tmp_path, indexer)

        monkeypatch.setattr(session_module, "build_document_stack", build_stack)

        self.store = _FakeSecretStore()
        self.token = mint_gateway_token(self.store)
        self.app = create_app(
            self.settings,
            application=self.application,
            secret_store=self.store,
            status_health_check=self._probe,
        )

    @staticmethod
    async def _probe() -> Any:
        from declaw.brain.ollama_client import OllamaHealth

        return OllamaHealth(reachable=True, version="test", models=())

    def client(self) -> TestClient:
        return TestClient(self.app, base_url=f"http://{BIND_AUTHORITY}")


def _login(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/auth/login", json={"token": token}, headers={"Origin": ALLOWED_ORIGIN}
    )
    assert response.status_code == 200
    return response.headers["set-cookie"].split("=", 1)[1].split(";", 1)[0]


async def _seed_rows(tmp_path: Path, rows: list[Any]) -> None:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    engine = build_engine(tmp_path / "data" / "declaw.db")
    maker = build_sessionmaker(engine)
    try:
        await ensure_schema(engine)
        async with maker() as session:
            for row in rows:
                session.add(row)
            await session.commit()
    finally:
        await engine.dispose()


def _indexed_row(path: str, **overrides: Any) -> IndexedDocument:
    values: dict[str, Any] = {
        "path": path,
        "content_sha256": "a" * 64,
        "size_bytes": 10,
        "mtime": datetime(2026, 1, 2, tzinfo=UTC),
        "doc_type": "text",
        "chunk_count": 1,
        "indexed_at": datetime(2026, 1, 3, tzinfo=UTC),
    }
    values.update(overrides)
    return IndexedDocument(**values)


async def test_document_listing_marks_failed_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_rows(
        tmp_path,
        [
            _indexed_row("good.txt"),
            _indexed_row("broken.txt"),
            DocumentIndexFailure(
                path="broken.txt", error="parser exploded", attempts=3, failed_at=datetime(2026, 1, 3, tzinfo=UTC)
            ),
            DocumentIndexFailure(
                path="never-indexed.txt",
                error="parser exploded too",
                attempts=3,
                failed_at=datetime(2026, 1, 3, tzinfo=UTC),
            ),
        ],
    )
    indexer = FakeIndexer(tmp_path / "workspace")
    stack = RouteStack(tmp_path, monkeypatch, indexer)

    with stack.client() as client:
        cookie = _login(client, stack.token)
        response = client.get("/api/documents", headers={"Cookie": f"declaw_session={cookie}"})

    assert response.status_code == 200
    documents = {doc["path"]: doc for doc in response.json()["documents"]}

    assert documents["good.txt"]["status"] == "indexed"
    # A failed path keeps its row but shows the marker, not a fake "indexed".
    assert documents["broken.txt"]["status"] == "failed"
    assert documents["broken.txt"]["error"] == "parser exploded"
    # A path that never indexed still appears — no silent loss.
    assert documents["never-indexed.txt"]["status"] == "failed"
    assert documents["never-indexed.txt"]["error"] == "parser exploded too"
    assert documents["never-indexed.txt"]["chunk_count"] is None


async def test_reindex_route_feeds_the_single_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indexer = FakeIndexer(tmp_path / "workspace", park_runs=True)
    stack = RouteStack(tmp_path, monkeypatch, indexer)

    with stack.client() as client:
        cookie = _login(client, stack.token)
        # The lifespan started the app: startup reconciliation (run 1) is in flight.
        deadline = time.time() + 3
        while time.time() < deadline and indexer.full_started < 1:
            time.sleep(0.01)
        assert indexer.full_started == 1
        client.portal.call(indexer.release_next_run)

        first = client.post(
            "/api/documents/reindex",
            headers={"Cookie": f"declaw_session={cookie}", "Origin": ALLOWED_ORIGIN},
        )
        assert first.status_code == 202
        assert first.json() == {"status": "started"}

        deadline = time.time() + 3
        while time.time() < deadline and indexer.full_started < 2:
            time.sleep(0.01)
        assert indexer.full_started == 2
        # The run is parked: a second start is refused, not queued.
        second = client.post(
            "/api/documents/reindex",
            headers={"Cookie": f"declaw_session={cookie}", "Origin": ALLOWED_ORIGIN},
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "reindex_in_progress"

        client.portal.call(indexer.release_next_run)
        deadline = time.time() + 3
        while time.time() < deadline and indexer.full_finished < 2:
            time.sleep(0.01)
        assert indexer.full_finished == 2

    assert stack.application.document_worker is not None, "the route must go through the worker"
