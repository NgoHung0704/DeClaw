"""REST surface tests: every /api route of spec section 9 (DCL-126).

The security-critical tests — 401 on every route, the route inventory with no
mutating document verb, canonical error shape — are written (and watched
fail) before the implementation, per spec section 17.

The stack under test is the real production one wherever feasible: a real
sqlite ``declaw.db`` (engine + sessionmaker patched into ``declaw.app``), the
real ``PluginHost``/``PluginStateStore``/``GrantStore`` over a controlled
builtin-plugins directory and tmp ``data_dir``, the real audit trail and the
real report/export rendering. Only the process-spawning or network-bound edges
are faked: the Ollama health probe (status), the document store (Chroma) and
the indexer body of a reindex run, exactly where the production objects would
touch the network, spawn vectors or start subprocesses.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from declaw.app import Application
from declaw.audit.events import (
    AuthEvent,
    PermissionPromptEvent,
    ToolCallEvent,
    to_db_row,
)
from declaw.config import Settings
from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.db.models import AuditEvent as AuditEventRow
from declaw.db.models import IndexedDocument, Task, TaskStatus
from declaw.documents.indexer import IndexProgress, IndexReport
from declaw.documents.models import SearchHit
from declaw.documents.search import DEFAULT_K, ChunkSanitizer
from declaw.documents.session import DocumentStack
from declaw.gateway.app import create_app
from declaw.gateway.auth import mint_gateway_token
from declaw.settings_service import APPLIED_NEW_SESSION, APPLIED_RESTART_REQUIRED

TEST_PORT = 9000  # never the default 7842 (same convention as test_chat_flow)
BIND_AUTHORITY = f"127.0.0.1:{TEST_PORT}"
ALLOWED_ORIGIN = f"http://{BIND_AUTHORITY}"

EXPECTED_ROUTES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/status"),
    ("GET", "/api/status"),
    ("GET", "/api/tasks"),
    ("GET", "/api/tasks/{task_id}"),
    ("GET", "/api/audit"),
    ("GET", "/api/audit/export"),
    ("GET", "/api/plugins"),
    ("POST", "/api/plugins/{name}/enable"),
    ("POST", "/api/plugins/{name}/disable"),
    ("GET", "/api/plugins/{name}/permissions"),
    ("POST", "/api/plugins/{name}/permissions/{permission}/grant"),
    ("POST", "/api/plugins/{name}/permissions/{permission}/revoke"),
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/documents"),
    ("GET", "/api/documents/search"),
    ("POST", "/api/documents/reindex"),
}


# --- Shared fakes ------------------------------------------------------------


class FakeSecretStore:
    """In-memory ``SecretStore``; no test touches the OS vault."""

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


class FakeWatcher:
    def __init__(self, folder: Path, *args: Any, **kwargs: Any) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class FakeMonitor:
    def __init__(self, audit: Any, **kwargs: Any) -> None:
        pass

    def install(self) -> None:
        pass

    def uninstall(self) -> None:
        pass


class FastOllamaProbe:
    """Health check that answers immediately and counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> Any:
        self.calls += 1
        return SimpleNamespace(
            reachable=True,
            version="0.9.7",
            models=("test-model",),
            error=None,
            has_model=lambda name: name in ("test-model",),
        )


class SlowOllamaProbe:
    """Health check that parks on a portal-loop future until released."""

    def __init__(self) -> None:
        self.release: Any = None

    async def __call__(self) -> Any:
        loop = asyncio.get_running_loop()
        self.release = loop.create_future()
        await self.release
        return SimpleNamespace(
            reachable=True,
            version="0.9.7",
            models=("test-model",),
            error=None,
            has_model=lambda name: name in ("test-model",),
        )


class FakeDocumentStore:
    """Chroma-replacement exposing only the search seam the route needs."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.queries: list[tuple[str, int]] = []

    async def search(self, query: str, *, k: int = DEFAULT_K) -> list[SearchHit]:
        self.queries.append((query, k))
        return self.hits[:k]


class FakeSanitizer:
    """Structural ``Sanitizer``: quarantines an exact dangerous text."""

    def __init__(self, unsafe_text: str) -> None:
        self.unsafe = unsafe_text
        self.checked: list[str] = []

    async def check(self, content: str, *, source: str) -> Any:
        self.checked.append(source)
        if content == self.unsafe:
            return SimpleNamespace(is_safe=False, quarantine_id="quarantine-1")
        return SimpleNamespace(is_safe=True, quarantine_id=None)


class FakeIndexer:
    """Reindex body that parks on a portal-loop future, then emits progress."""

    def __init__(self) -> None:
        self.calls = 0
        self.finished = False
        self.release: Any = None

    async def index(
        self, folder: Path | None = None, *, on_progress: Any = None
    ) -> IndexReport:
        self.calls += 1
        loop = asyncio.get_running_loop()
        self.release = loop.create_future()
        await self.release
        if on_progress is not None:
            on_progress(IndexProgress(done=1, total=2, path="a.txt"))
            on_progress(IndexProgress(done=2, total=2, path="b.txt"))
        self.finished = True
        return IndexReport(indexed=2)


class FakeBroadcaster:
    """The seam Task 13 (/ws/events) will inject as ``app.state.event_broadcaster``."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def broadcast(self, event: dict[str, Any]) -> None:
        self.frames.append(event)


# --- Harness -----------------------------------------------------------------

ALPHA = "alpha-tools"
BETA = "beta-tools"

_ALPHA_MANIFEST = """\
manifest_version: 1
name: alpha-tools
version: 1.2.3
description_en: Alpha plugin for tests.
description_fr: Plugin alpha pour les tests.
entrypoint: main.py
permissions:
  requested: [filesystem.read, network]
  denied: [credentials]
"""

_BETA_MANIFEST = """\
manifest_version: 1
name: beta-tools
version: 0.9.0
description_en: Beta plugin for tests.
description_fr: Plugin beta pour les tests.
entrypoint: main.py
"""

# Both built-ins are pre-disabled so the real PluginHost.start() never spawns
# a subprocess; enable/disable are exercised through the persisted state flags.
_PLUGIN_STATE = {
    ALPHA: {"enabled": False},
    BETA: {"enabled": False, "quarantined": True, "quarantine_reason": "crash loop"},
}


class RestStack:
    """A real gateway application over a tmp sqlite DB, workspace and plugins dir."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        *,
        probe: Any = None,
        language: str | None = "en",
        model: str | None = "test-model",
        env_workspace: bool = True,
    ) -> None:
        self.workspace = tmp_path / "workspace"
        self.data_dir = tmp_path / "data"
        self.plugins_dir = tmp_path / "plugins"
        self.workspace.mkdir(parents=True)
        self.data_dir.mkdir(parents=True)
        self.plugins_dir.mkdir(parents=True)

        for name, manifest in ((ALPHA, _ALPHA_MANIFEST), (BETA, _BETA_MANIFEST)):
            directory = self.plugins_dir / name
            directory.mkdir()
            (directory / "plugin.yaml").write_text(manifest, encoding="utf-8")
        (self.data_dir / "plugin_state.json").write_text(
            json.dumps(_PLUGIN_STATE), encoding="utf-8"
        )

        self.engine = build_engine(self.data_dir / "declaw.db")
        self.sessionmaker = build_sessionmaker(self.engine)
        monkeypatch.setattr("declaw.app.get_engine", lambda: self.engine)
        monkeypatch.setattr("declaw.app.get_sessionmaker", lambda: self.sessionmaker)
        monkeypatch.setattr("declaw.app.DocumentWatcher", FakeWatcher)
        monkeypatch.setattr("declaw.app.EgressMonitor", FakeMonitor)

        # Settings fields passed here are ENV-EXPLICIT: they win over
        # settings.json in the effective snapshot (Task 8 precedence). Tests
        # that must observe file-driven effects pass None and let the
        # default (non-explicit) env layer fall through to the file.
        values: dict[str, Any] = {
            "_env_file": None,
            "port": TEST_PORT,
            "data_dir": self.data_dir,
            "builtin_plugins_dir": self.plugins_dir,
            "sanitizer_required": False,
        }
        if model is not None:
            values["model"] = model
        if language is not None:
            values["language"] = language
        if env_workspace:
            values["workspace_dir"] = self.workspace
        self.settings = Settings(**values)  # type: ignore[call-arg]
        self.application = Application(self.settings, mode="gateway")
        self.store = FakeSecretStore()
        self.token = mint_gateway_token(self.store)
        self.probe = probe if probe is not None else FastOllamaProbe()
        self.app = create_app(
            self.settings,
            application=self.application,
            secret_store=self.store,
            status_health_check=self.probe,
        )

    def client(self) -> TestClient:
        return TestClient(self.app, base_url=f"http://{BIND_AUTHORITY}")

    def login(self, client: TestClient) -> str:
        response = client.post(
            "/api/auth/login", json={"token": self.token}, headers={"Origin": ALLOWED_ORIGIN}
        )
        assert response.status_code == 200
        return response.headers["set-cookie"].split("=", 1)[1].split(";", 1)[0]

    def headers(self, cookie: str) -> dict[str, str]:
        return {"Cookie": f"declaw_session={cookie}"}

    def post_headers(self, cookie: str) -> dict[str, str]:
        return {**self.headers(cookie), "Origin": ALLOWED_ORIGIN}


def _stack(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    probe: Any = None,
    language: str | None = "en",
    model: str | None = "test-model",
    env_workspace: bool = True,
) -> RestStack:
    return RestStack(
        tmp_path,
        monkeypatch,
        probe=probe,
        language=language,
        model=model,
        env_workspace=env_workspace,
    )


def assert_canonical_error(
    response: Any, status: int, code: str | None = None
) -> dict[str, Any]:
    """Every response an added route produces uses the gateway error shape."""
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message"}, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    if code is not None:
        assert body["error"]["code"] == code, body
    return body


def _seed_rows(tmp_path: Path, rows: list[Any]) -> None:
    """Insert arbitrary SQLModel rows into the stack's DB via a throwaway engine."""

    async def run() -> None:
        engine = build_engine(tmp_path / "data" / "declaw.db")
        maker = build_sessionmaker(engine)
        try:
            await ensure_schema(engine)  # the real schema, same as lifespan start
            async with maker() as session:
                for row in rows:
                    session.add(row)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def _tool_call_event(
    event_id: str, created_at: datetime, *, task_id: str | None = None, tool: str = "reader"
) -> AuditEventRow:
    return to_db_row(
        ToolCallEvent(
            tool_name=tool,
            classification="read",
            args={},
            outcome="ok",
            id=event_id,
            task_id=task_id,
            created_at=created_at,
        )
    )


def _ts(day: str, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=UTC)


DAY = date(2026, 1, 2)


# --- Route inventory: exactly spec section 9, no mutating document route ------


def test_route_inventory_matches_spec_section_9(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)
    inventory: dict[str, set[str]] = {}
    for route in stack.app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue  # the bare "/" health probe predates this surface
        inventory.setdefault(route.path, set()).update(route.methods)

    actual = {(method, path) for path, methods in inventory.items() for method in methods}
    assert actual == EXPECTED_ROUTES


def test_no_rest_route_mutates_documents(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)
    for route in stack.app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api/documents"):
            continue
        if route.path == "/api/documents/reindex":
            continue  # control action on the INDEX, not a document write
        assert route.methods <= {"GET"}, route.path


# --- Every route: 401 + canonical shape without a session cookie ------------


_EXCEPTIONED_ROUTES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/status"),
}
"""Routes that BY DESIGN answer without a session: login mints the session,
logout must work with a stale cookie, and auth/status reports (and never
grants) authentication state (spec section 2)."""


def _concrete_paths_including_auth() -> list[tuple[str, str, dict[str, Any]]]:
    """Concrete (method, path, request kwargs) valid enough to reach the route."""
    path_params = {
        "{task_id}": "does-not-exist",
        "{name}": ALPHA,
        "{permission}": "network",
    }
    out: list[tuple[str, str, dict[str, Any]]] = []
    for method, template in sorted(EXPECTED_ROUTES):
        if (method, template) in _EXCEPTIONED_ROUTES:
            continue
        path = template
        for key, value in path_params.items():
            path = path.replace(key, value)
        kwargs: dict[str, Any] = {}
        if method not in ("GET", "HEAD"):
            kwargs["headers"] = {"Origin": ALLOWED_ORIGIN}
        if path == "/api/audit/export":
            kwargs["params"] = {"day": "2026-01-02", "format": "md"}
        elif path == "/api/documents/search":
            kwargs["params"] = {"q": "hello", "k": "5"}
        elif method == "PUT" and path == "/api/settings":
            kwargs["json"] = {}
        out.append((method, path, kwargs))
    return out


@pytest.mark.parametrize(
    ("method", "path", "kwargs"), _concrete_paths_including_auth()
)
def test_every_route_requires_a_session_cookie(
    tmp_path: Path, monkeypatch: Any, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        response = client.request(method, path, **kwargs)
        assert_canonical_error(response, 401, "unauthorized")


# --- GET /api/status ----------------------------------------------------------


def test_status_aggregates_health_plugins_version_and_flags(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get("/api/status", headers=stack.headers(cookie))

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "0.1.0"
    assert body["ollama"] == {
        "reachable": True,
        "version": "0.9.7",
        "model": "test-model",
        "model_present": True,
        "error": None,
    }
    plugins = {p["name"]: p for p in body["plugins"]}
    assert plugins[ALPHA] == {"name": ALPHA, "version": "1.2.3", "state": "disabled"}
    assert plugins[BETA]["state"] == "quarantined"
    assert body["egress_monitor"] is True
    assert body["watcher"] is True


def test_status_ollama_health_is_latched_not_polled(tmp_path: Path, monkeypatch: Any) -> None:
    # A latched probe: three GETs inside the TTL issue exactly one health call,
    # so a slow or down daemon can never absorb the status endpoint's requests.
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        for _ in range(3):
            response = client.get("/api/status", headers=stack.headers(cookie))
            assert response.status_code == 200

    assert stack.probe.calls == 1


def test_status_does_not_wait_for_a_hung_daemon(tmp_path: Path, monkeypatch: Any) -> None:
    # The very first probe call hangs until released: the status route must
    # answer with an unknown ollama section instead of holding the request.
    probe = SlowOllamaProbe()
    stack = _stack(tmp_path, monkeypatch, probe=probe)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get("/api/status", headers=stack.headers(cookie))
        assert response.status_code == 200
        assert response.json()["ollama"]["reachable"] is None

        # The background refresh completes: the next GET serves the latch.
        client.portal.call(probe.release.set_result, True)
        for _ in range(100):
            if probe.release.done() and _probe_latched(probe, stack):
                break
            time.sleep(0.02)
        response = client.get("/api/status", headers=stack.headers(cookie))
        assert response.status_code == 200
        assert response.json()["ollama"]["reachable"] is True


def _probe_latched(probe: Any, stack: RestStack) -> bool:
    return stack.app.state.ollama_status._latched is not None  # noqa: SLF001


# --- GET /api/tasks, GET /api/tasks/{id} --------------------------------------


def test_task_list_and_detail(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)
    older = Task(
        id="t1",
        prompt="first question",
        status=TaskStatus.COMPLETED,
        result="first answer",
        created_at=_ts("2026-01-02", 10),
        updated_at=_ts("2026-01-02", 10, 1),
    )
    newer = Task(
        id="t2",
        prompt="second question",
        status=TaskStatus.FAILED,
        error="cancelled by user",
        created_at=_ts("2026-01-02", 11),
        updated_at=_ts("2026-01-02", 11, 1),
    )
    _seed_rows(tmp_path, [older, newer])

    with stack.client() as client:
        cookie = stack.login(client)
        listing = client.get("/api/tasks", headers=stack.headers(cookie))
        assert listing.status_code == 200
        tasks = listing.json()["tasks"]
        assert [t["id"] for t in tasks] == ["t2", "t1"]  # newest first
        assert tasks[0]["prompt"] == "second question"
        assert tasks[0]["status"] == "failed"
        assert tasks[0]["error"] == "cancelled by user"
        assert tasks[0]["result"] is None
        assert tasks[0]["created_at"].startswith("2026-01-02T11:00:00")

        detail = client.get("/api/tasks/t1", headers=stack.headers(cookie))
        assert detail.status_code == 200
        assert detail.json()["id"] == "t1"
        assert detail.json()["result"] == "first answer"

        missing = client.get("/api/tasks/nope", headers=stack.headers(cookie))
        assert_canonical_error(missing, 404, "not_found")


# --- GET /api/audit: filters + keyset pagination on (created_at, id) ----------


def test_audit_keyset_pagination_walks_without_gaps_or_duplicates(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)
    rows = [
        _tool_call_event(f"e{hour}", _ts("2026-01-02", hour)) for hour in range(10, 14)
    ]
    _seed_rows(tmp_path, rows)

    with stack.client() as client:
        cookie = stack.login(client)
        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while pages < 10:
            params = {"limit": 2, "event_type": "tool.call"}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(
                "/api/audit", params=params, headers=stack.headers(cookie)
            )
            assert response.status_code == 200
            body = response.json()
            seen.extend(e["id"] for e in body["events"])
            cursor = body["next_cursor"]
            pages += 1
            if cursor is None:
                break

        assert pages == 2
        assert seen == ["e13", "e12", "e11", "e10"]  # newest first, no gap/dupe


def test_audit_keyset_tiebreaks_on_id_for_equal_timestamps(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)
    same = _ts("2026-01-02", 10)
    _seed_rows(
        tmp_path,
        [
            _tool_call_event("aaa", same),
            _tool_call_event("bbb", same),
            _tool_call_event("ccc", same),
        ],
    )

    with stack.client() as client:
        cookie = stack.login(client)
        page1 = client.get(
            "/api/audit",
            params={"limit": 2, "event_type": "tool.call"},
            headers=stack.headers(cookie),
        ).json()
        assert [e["id"] for e in page1["events"]] == ["ccc", "bbb"]
        page2 = client.get(
            "/api/audit",
            params={"limit": 2, "event_type": "tool.call", "cursor": page1["next_cursor"]},
            headers=stack.headers(cookie),
        ).json()
        assert [e["id"] for e in page2["events"]] == ["aaa"]
        assert page2["next_cursor"] is None


def test_audit_filters(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)
    _seed_rows(
        tmp_path,
        [
            _tool_call_event("ev1", _ts("2026-01-02", 10), task_id="t1", tool="reader"),
            _tool_call_event("ev2", _ts("2026-01-02", 12), tool="writer"),
            _tool_call_event("ev3", _ts("2026-01-03", 9), task_id="t2", tool="reader"),
        ],
    )

    with stack.client() as client:
        cookie = stack.login(client)
        base = {"headers": stack.headers(cookie)}

        by_type = client.get(
            "/api/audit", params={"event_type": "tool.call"}, headers=stack.headers(cookie)
        ).json()
        assert [e["id"] for e in by_type["events"]] == ["ev3", "ev2", "ev1"]

        by_task = client.get(
            "/api/audit", params={"task_id": "t1"}, **base
        ).json()
        assert [e["id"] for e in by_task["events"]] == ["ev1"]

        by_tool_name = client.get(
            "/api/audit", params={"task_id": "t2"}, **base
        ).json()
        assert [e["id"] for e in by_tool_name["events"]] == ["ev3"]

        within_day = client.get(
            "/api/audit",
            params={"date_from": "2026-01-02", "date_to": "2026-01-02"},
            headers=stack.headers(cookie),
        ).json()
        assert [e["id"] for e in within_day["events"]] == ["ev2", "ev1"]

        from_day = client.get(
            "/api/audit",
            params={"date_from": "2026-01-03", "date_to": "2026-01-03"},
            headers=stack.headers(cookie),
        ).json()
        assert [e["id"] for e in from_day["events"]] == ["ev3"]


def test_audit_counts_rows_the_current_schema_cannot_read(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)
    corrupt = AuditEventRow(
        id="bad1",
        event_type="tool.call",
        task_id=None,
        payload={"event_type": "tool.call", "schema_version": 1},
        created_at=_ts("2026-01-02", 10),
    )
    _seed_rows(tmp_path, [corrupt, _tool_call_event("good1", _ts("2026-01-02", 11))])

    with stack.client() as client:
        cookie = stack.login(client)
        body = client.get(
            "/api/audit",
            params={"event_type": "tool.call"},
            headers=stack.headers(cookie),
        ).json()
        assert [e["id"] for e in body["events"]] == ["good1"]
        assert body["unreadable"] == 1


def test_audit_rejects_a_garbage_cursor(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get(
            "/api/audit", params={"cursor": "not-a-cursor"}, headers=stack.headers(cookie)
        )
        assert_canonical_error(response, 400, "invalid_cursor")


# --- GET /api/audit/export: report.py / export.py round-trip -------------------


def _seed_export_day(tmp_path: Path) -> None:
    _seed_rows(
        tmp_path,
        [
            _tool_call_event("ex1", _ts("2026-01-02", 10), task_id="t1"),
            to_db_row(
                PermissionPromptEvent(
                    tool_name="filesystem_write",
                    args={},
                    decision="approved",
                    id="ex2",
                    task_id="t1",
                    created_at=_ts("2026-01-02", 11),
                )
            ),
            to_db_row(
                AuthEvent(action="login_success", id="ex3", created_at=_ts("2026-01-02", 12))
            ),
        ],
    )


def test_audit_export_markdown_reuses_daily_report(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)
    _seed_export_day(tmp_path)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get(
            "/api/audit/export",
            params={"day": "2026-01-02", "format": "md"},
            headers=stack.headers(cookie),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    body = response.text
    assert "DeClaw daily report — 2026-01-02" in body
    assert "Task t1" in body
    assert "reader" in body or "ex1" in body


def test_audit_export_json_round_trips_the_archive(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)
    _seed_export_day(tmp_path)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get(
            "/api/audit/export",
            params={"day": "2026-01-02", "format": "json"},
            headers=stack.headers(cookie),
        )

    assert response.status_code == 200
    archive = response.json()
    envelope = archive["declaw_audit_export"]
    assert envelope["schema_version"] == 1
    assert envelope["event_count"] == 3
    assert {e["event_type"] for e in archive["events"]} == {
        "tool.call",
        "permission.prompt",
        "gateway.auth",
    }


def test_audit_export_validates_params(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        missing_day = client.get(
            "/api/audit/export", params={"format": "md"}, headers=stack.headers(cookie)
        )
        assert_canonical_error(missing_day, 422, "invalid_request")

        bad_format = client.get(
            "/api/audit/export",
            params={"day": "2026-01-02", "format": "pdf"},
            headers=stack.headers(cookie),
        )
        assert_canonical_error(bad_format, 422, "invalid_request")

        bad_day = client.get(
            "/api/audit/export", params={"day": "not-a-date"}, headers=stack.headers(cookie)
        )
        assert_canonical_error(bad_day, 422, "invalid_request")


# --- GET /api/plugins + enable/disable ------------------------------------------


def test_plugin_list_states_versions_and_descriptions(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get("/api/plugins", headers=stack.headers(cookie))

    assert response.status_code == 200
    plugins = {p["name"]: p for p in response.json()["plugins"]}
    assert plugins[ALPHA]["version"] == "1.2.3"
    assert plugins[ALPHA]["description"] == "Alpha plugin for tests."
    assert plugins[ALPHA]["state"] == "disabled"
    assert plugins[BETA]["state"] == "quarantined"
    assert plugins[BETA]["version"] == "0.9.0"


def test_plugin_list_localizes_descriptions_for_french(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch, language="fr")

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get("/api/plugins", headers=stack.headers(cookie))

    plugins = {p["name"]: p for p in response.json()["plugins"]}
    assert plugins[ALPHA]["description"] == "Plugin alpha pour les tests."


def test_plugin_enable_is_a_next_start_flag_and_clears_quarantine(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.post(f"/api/plugins/{BETA}/enable", headers=stack.post_headers(cookie))

        assert response.status_code == 200
        assert response.json() == {
            "name": BETA,
            "state": "enabled",
            "takes_effect": "next_gateway_start",
        }

        persisted = json.loads(
            (stack.data_dir / "plugin_state.json").read_text(encoding="utf-8")
        )
        assert persisted[BETA]["enabled"] is True
        assert persisted[BETA]["quarantined"] is False

        # Startup did not run again: the plugin is flagged, never hot-loaded.
        host = stack.application.host
        assert host is not None
        loaded = [p.manifest.name for p in host.loaded()]
        assert BETA not in loaded

        # The listing route reads the same persisted flags the response carried.
        listing = {
            p["name"]: p for p in client.get("/api/plugins", headers=stack.headers(cookie)).json()["plugins"]
        }
        assert listing[BETA]["state"] == "enabled"

        lifecycle = client.get(
            "/api/audit",
            params={"event_type": "plugin.lifecycle"},
            headers=stack.headers(cookie),
        ).json()
        enable_events = [
            e for e in lifecycle["events"] if e["plugin"] == BETA and e["action"] == "enabled"
        ]
        assert enable_events, lifecycle


def test_plugin_disable_is_immediate_and_audited(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.post(f"/api/plugins/{ALPHA}/disable", headers=stack.post_headers(cookie))

        assert response.status_code == 200
        assert response.json() == {
            "name": ALPHA,
            "state": "disabled",
            "takes_effect": "immediate",
        }

        persisted = json.loads(
            (stack.data_dir / "plugin_state.json").read_text(encoding="utf-8")
        )
        assert persisted[ALPHA]["enabled"] is False

        lifecycle = client.get(
            "/api/audit",
            params={"event_type": "plugin.lifecycle"},
            headers=stack.headers(cookie),
        ).json()
        disable_events = [
            e for e in lifecycle["events"] if e["plugin"] == ALPHA and e["action"] == "disabled"
        ]
        assert disable_events, lifecycle


def test_plugin_enable_and_disable_of_unknown_plugin_is_404(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        enable = client.post(
            "/api/plugins/ghost/enable", headers=stack.post_headers(cookie)
        )
        assert_canonical_error(enable, 404, "not_found")

        disable = client.post(
            "/api/plugins/ghost/disable", headers=stack.post_headers(cookie)
        )
        assert_canonical_error(disable, 404, "not_found")


# --- Plugin permissions --------------------------------------------------------


def test_plugin_permissions_lists_requested_denied_granted(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get(
            f"/api/plugins/{ALPHA}/permissions", headers=stack.headers(cookie)
        )

    assert response.status_code == 200
    assert response.json() == {
        "name": ALPHA,
        "requested": ["filesystem.read", "network"],
        "denied": ["credentials"],
        "granted": [],
    }


def test_permission_grant_and_revoke_are_audited_as_plugin_permission_events(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        grant = client.post(
            f"/api/plugins/{ALPHA}/permissions/filesystem.read/grant",
            headers=stack.post_headers(cookie),
        )
        assert grant.status_code == 200
        assert grant.json()["granted"] == ["filesystem.read"]

        listed = client.get(
            f"/api/plugins/{ALPHA}/permissions", headers=stack.headers(cookie)
        ).json()
        assert listed["granted"] == ["filesystem.read"]

        revoke = client.post(
            f"/api/plugins/{ALPHA}/permissions/filesystem.read/revoke",
            headers=stack.post_headers(cookie),
        )
        assert revoke.status_code == 200
        assert revoke.json()["granted"] == []

        trail = client.get(
            "/api/audit",
            params={"event_type": "plugin.permission"},
            headers=stack.headers(cookie),
        ).json()
        actions = [(e["plugin"], e["permission"], e["action"]) for e in trail["events"]]
        assert (ALPHA, "filesystem.read", "granted") in actions
        assert (ALPHA, "filesystem.read", "revoked") in actions

    # The store persists only non-empty grant sets: after the revoke the file
    # exists again with an empty mapping (a real revoke is a persisted fact).
    persisted = json.loads(
        (stack.data_dir / "plugin_grants.json").read_text(encoding="utf-8")
    )
    assert persisted == {}


def test_permission_route_rejects_unknown_plugin_and_unknown_permission(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        unknown_plugin = client.post(
            "/api/plugins/ghost/permissions/network/grant",
            headers=stack.post_headers(cookie),
        )
        assert_canonical_error(unknown_plugin, 404, "not_found")

        bogus_permission = client.post(
            f"/api/plugins/{ALPHA}/permissions/root.shell/grant",
            headers=stack.post_headers(cookie),
        )
        assert_canonical_error(bogus_permission, 422, "invalid_request")

        ghost_list = client.get(
            "/api/plugins/ghost/permissions", headers=stack.headers(cookie)
        )
        assert_canonical_error(ghost_list, 404, "not_found")


# --- GET/PUT /api/settings -------------------------------------------------------


def test_settings_get_returns_the_effective_snapshot(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get("/api/settings", headers=stack.headers(cookie))

    assert response.status_code == 200
    assert response.json() == {
        "model": "test-model",
        "language": "en",
        "workspace_dir": str(stack.workspace),
    }


def test_settings_put_reports_applied_flags(tmp_path: Path, monkeypatch: Any) -> None:
    # model/language are not env-explicit here, so the written file values are
    # what every GET composes back (Task 8 precedence: file > defaults).
    stack = _stack(tmp_path, monkeypatch, model=None, language=None, env_workspace=False)
    client = stack.client()  # settings routes need no started application

    cookie = stack.login(client)
    response = client.put(
        "/api/settings",
        json={"model": "qwen2.5:7b", "language": "fr"},
        headers=stack.post_headers(cookie),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "qwen2.5:7b"
    assert body["language"] == "fr"
    assert body["applied"] == {
        "model": APPLIED_NEW_SESSION,
        "language": APPLIED_NEW_SESSION,
    }

    follow = client.get("/api/settings", headers=stack.headers(cookie))
    assert follow.json()["language"] == "fr"
    assert follow.json()["model"] == "qwen2.5:7b"


def test_settings_put_workspace_dir_is_restart_required_and_creates_it(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)
    new_workspace = tmp_path / "deeper" / "new-workspace"

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.put(
            "/api/settings",
            json={"workspace_dir": str(new_workspace)},
            headers=stack.post_headers(cookie),
        )

    assert response.status_code == 200
    assert response.json()["applied"] == {"workspace_dir": APPLIED_RESTART_REQUIRED}
    assert new_workspace.is_dir()


def test_settings_empty_put_is_a_no_op(tmp_path: Path, monkeypatch: Any) -> None:
    # Empty PUT semantics (Task 8 handoff): a document-sized zero-key update
    # changes nothing, writes nothing, and reports an empty applied map.
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.put("/api/settings", json={}, headers=stack.post_headers(cookie))

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == {}
    assert body["model"] == "test-model"
    assert not (stack.data_dir / "settings.json").exists()


def test_settings_put_rejects_invalid_language_and_model_without_writing(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)
    settings_path = stack.data_dir / "settings.json"

    with stack.client() as client:
        cookie = stack.login(client)
        bad_language = client.put(
            "/api/settings", json={"language": "es"}, headers=stack.post_headers(cookie)
        )
        assert_canonical_error(bad_language, 422)
        assert not settings_path.exists()

        empty_model = client.put(
            "/api/settings", json={"model": "  "}, headers=stack.post_headers(cookie)
        )
        assert_canonical_error(empty_model, 422)
        assert not settings_path.exists()


def test_settings_put_rejects_workspace_equal_to_data_dir(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.put(
            "/api/settings",
            json={"workspace_dir": str(stack.data_dir)},
            headers=stack.post_headers(cookie),
        )
    assert_canonical_error(response, 422)
    assert not (stack.data_dir / "settings.json").exists()


def test_settings_get_with_unsafe_file_is_409(tmp_path: Path, monkeypatch: Any) -> None:
    # workspace_dir must fall through to the FILE (not env-explicit) for the
    # composed snapshot to hit the isolation rule and fail closed.
    stack = _stack(tmp_path, monkeypatch, model=None, language=None, env_workspace=False)
    (stack.data_dir / "settings.json").write_text(
        json.dumps({"workspace_dir": str(stack.data_dir)}), encoding="utf-8"
    )

    client = stack.client()  # settings routes need no started application
    cookie = stack.login(client)
    response = client.get("/api/settings", headers=stack.headers(cookie))
    assert_canonical_error(response, 409, "invalid_settings_file")


def test_settings_put_rejects_unknown_keys(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.put(
            "/api/settings",
            json={"sanitizer_required": False},
            headers=stack.post_headers(cookie),
        )
    assert_canonical_error(response, 422, "invalid_request")


# --- GET /api/documents -----------------------------------------------------------


def test_document_catalog_lists_indexed_documents(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)
    _seed_rows(
        tmp_path,
        [
            IndexedDocument(
                path="notes/b.txt",
                content_sha256="b" * 64,
                size_bytes=20,
                mtime=_ts("2026-01-02", 8),
                doc_type="text",
                chunk_count=2,
                indexed_at=_ts("2026-01-02", 9),
            ),
            IndexedDocument(
                path="a.txt",
                content_sha256="a" * 64,
                size_bytes=10,
                mtime=_ts("2026-01-02", 8),
                doc_type="text",
                chunk_count=1,
                indexed_at=_ts("2026-01-02", 9),
            ),
        ],
    )

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get("/api/documents", headers=stack.headers(cookie))

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert [d["path"] for d in documents] == ["a.txt", "notes/b.txt"]
    first = documents[0]
    assert first["size_bytes"] == 10
    assert first["content_sha256"] == "a" * 64
    assert first["doc_type"] == "text"
    assert first["chunk_count"] == 1
    assert first["status"] == "indexed"
    assert first["mtime"].startswith("2026-01-02T08:00:00")
    assert first["indexed_at"].startswith("2026-01-02T09:00:00")


# --- GET /api/documents/search -------------------------------------------------------


def _hits() -> list[SearchHit]:
    return [
        SearchHit(
            chunk_id="c1", doc_id="d1", path="good.txt", text="safe passage", ordinal=1, distance=0.1
        ),
        SearchHit(
            chunk_id="c2", doc_id="d2", path="secret.txt", text="the IBAN is X", ordinal=1, distance=0.2
        ),
        SearchHit(
            chunk_id="c3", doc_id="d3", path="other.txt", text="another passage", ordinal=1, distance=0.3
        ),
    ]


def test_document_search_is_the_sanitized_retrieval_chat_uses(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)
    hits = _hits()
    sanitizer = FakeSanitizer(unsafe_text="the IBAN is X")
    stack.application.stack = DocumentStack(
        store=FakeDocumentStore(hits),  # type: ignore[arg-type]
        catalog=None,  # type: ignore[arg-type]
        indexer=None,  # type: ignore[arg-type]
        chunk_sanitizer=ChunkSanitizer(sanitizer),  # type: ignore[arg-type]
    )

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get(
            "/api/documents/search",
            params={"q": "passage", "k": 2},
            headers=stack.headers(cookie),
        )

    assert response.status_code == 200
    body = response.json()
    assert [h["path"] for h in body["hits"]] == ["good.txt"]  # unsafe chunk withheld
    assert "IBAN" not in response.text
    assert body["withheld"] == 1
    # Exactly what chat asks for: the retrieval call passed q and k through.
    store = stack.application.stack.store  # type: ignore[union-attr]
    assert store.queries == [("passage", 2)]  # type: ignore[union-attr]


def test_document_search_without_a_stack_is_documents_unavailable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)  # doc-intel never loaded -> stack None

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.get(
            "/api/documents/search", params={"q": "hello"}, headers=stack.headers(cookie)
        )
    assert_canonical_error(response, 404, "documents_unavailable")


def test_document_search_validates_q_and_k(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch)
    stack.application.stack = DocumentStack(
        store=FakeDocumentStore([]),  # type: ignore[arg-type]
        catalog=None,  # type: ignore[arg-type]
        indexer=None,  # type: ignore[arg-type]
        chunk_sanitizer=ChunkSanitizer(None),
    )

    with stack.client() as client:
        cookie = stack.login(client)
        missing_q = client.get("/api/documents/search", headers=stack.headers(cookie))
        assert_canonical_error(missing_q, 422, "invalid_request")

        bad_k = client.get(
            "/api/documents/search", params={"q": "x", "k": 0}, headers=stack.headers(cookie)
        )
        assert_canonical_error(bad_k, 422, "invalid_request")

        huge_k = client.get(
            "/api/documents/search", params={"q": "x", "k": 500}, headers=stack.headers(cookie)
        )
        assert_canonical_error(huge_k, 422, "invalid_request")


# --- POST /api/documents/reindex ------------------------------------------------------


def test_reindex_starts_reconciliation_once_and_broadcasts_progress(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)
    indexer = FakeIndexer()
    broadcaster = FakeBroadcaster()
    stack.application.stack = DocumentStack(
        store=None,  # type: ignore[arg-type]
        catalog=None,  # type: ignore[arg-type]
        indexer=indexer,  # type: ignore[arg-type]
        chunk_sanitizer=ChunkSanitizer(None),
    )

    with stack.client() as client:
        cookie = stack.login(client)
        client.app.state.event_broadcaster = broadcaster

        first = client.post("/api/documents/reindex", headers=stack.post_headers(cookie))
        assert first.status_code == 202
        assert first.json()["status"] == "started"

        # 202 means "scheduled", not "synchronously running": wait until the
        # run has actually started before asserting the one-run guard.
        deadline = time.time() + 5
        while time.time() < deadline and indexer.calls == 0:
            time.sleep(0.02)
        assert indexer.calls == 1

        # A run is in flight: a second start is refused, not queued.
        second = client.post("/api/documents/reindex", headers=stack.post_headers(cookie))
        assert_canonical_error(second, 409, "reindex_in_progress")

        client.portal.call(indexer.release.set_result, True)
        deadline = time.time() + 5
        while time.time() < deadline and not indexer.finished:
            time.sleep(0.02)
        assert indexer.finished

        third = client.post("/api/documents/reindex", headers=stack.post_headers(cookie))
        assert third.status_code == 202

    assert broadcaster.frames == [
        {"type": "index.progress", "total": 2, "done": 1, "current_path": "a.txt"},
        {"type": "index.progress", "total": 2, "done": 2, "current_path": "b.txt"},
    ]


def test_reindex_without_a_stack_is_documents_unavailable(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = _stack(tmp_path, monkeypatch)

    with stack.client() as client:
        cookie = stack.login(client)
        response = client.post("/api/documents/reindex", headers=stack.post_headers(cookie))
    assert_canonical_error(response, 404, "documents_unavailable")
