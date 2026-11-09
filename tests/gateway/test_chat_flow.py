"""Integration: WS chat sessions, turns and correlated approvals (DCL-125).

The M3 end-to-end slice (spec section 17): an authenticated ``/ws/chat`` turn
that invokes a WRITE tool — correlated approval over the socket, audited
execution carrying the turn's task_id, the Task/Episode rows, and the
deny-by-default behavior on denial, timeout, cancellation and disconnect.

The model is a deterministic scripted fake (never Ollama); the database,
registry, confirmation gate and audit wrappers are the real production stack,
patched only where they would leave the process (plugin subprocesses, the
watchdog observer) or touch the user's real engine singleton (declaw.app
engine wiring, the Task 7 test seam).

Security-critical tests: written (and watched fail) before the
implementation, per spec section 17.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from sqlmodel import select as sm_select
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from declaw.app import Application
from declaw.config import Settings, get_settings
from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.db.models import AuditEvent, Episode, Task, TaskStatus
from declaw.gateway.app import create_app
from declaw.gateway.approval import ApprovalBroker, APPROVAL_REQUEST_TYPE
from declaw.gateway.auth import SESSION_COOKIE_NAME, mint_gateway_token
from declaw.gateway.middleware import RateLimiter
from declaw.gateway.session import (
    CHAT_FINAL_TYPE,
    ERROR_TYPE,
    MESSAGE_TYPE,
    TURN_CANCELLED_TYPE,
    TURN_STARTED_TYPE,
    GatewaySession,
)
TEST_PORT = 9000  # never the default 7842 (same convention as test_host_origin)
BIND_AUTHORITY = f"127.0.0.1:{TEST_PORT}"
ALLOWED_ORIGIN = f"http://{BIND_AUTHORITY}"
WRITE_TOOL = "filesystem_write"
WRITE_PATH = "note.txt"
WRITE_CONTENT = "hello world"
LONG_ANSWER = "A" * 600

# Error codes carried by typed ``{"type": "error"}`` frames.
BAD_FRAME = "bad_frame"
BUSY = "busy"
RATE_LIMITED = "rate_limited"
TURN_FAILED = "turn_failed"


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


class FakeClock:
    """Fixed ``() -> float`` clock: rate buckets never refill in these tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeHost:
    """PluginHost stand-in: no subprocesses, no tools, ordered stop."""

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
        return []


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


class ScriptedModel:
    """A deterministic ModelCallable scripted by its ModelHub.

    ``use_tool``: the first think-step returns a filesystem_write tool call
    (no ToolMessage in the history yet); after the tool observation, or when
    ``use_tool`` is off, the model answers directly with ``final_answer``.
    Records every message list it is handed, so tests can pin per-connection
    history isolation on real behavior (the graph input), not on mocks.
    """

    def __init__(self, hub: ModelHub) -> None:
        self.hub = hub
        self.calls: list[list[BaseMessage]] = []

    async def __call__(self, messages: Any) -> BaseMessage:
        snapshot = list(messages)
        self.calls.append(snapshot)
        if self.hub.raise_error:
            raise ConnectionError("ollama connection refused")
        if self.hub.use_tool and not any(isinstance(m, ToolMessage) for m in snapshot):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": WRITE_TOOL,
                        "args": {"path": WRITE_PATH, "content": WRITE_CONTENT},
                        "id": "call_1",
                    }
                ],
            )
        return AIMessage(content=self.hub.final_answer)


class ModelHub:
    """Per-session model factory: one fresh scripted model per connection."""

    def __init__(
        self,
        *,
        use_tool: bool = False,
        final_answer: str = "done",
        raise_error: bool = False,
    ) -> None:
        self.use_tool = use_tool
        self.final_answer = final_answer
        self.raise_error = raise_error
        self.models: list[ScriptedModel] = []

    def factory(self, tools: Any, snapshot: Any) -> Any:
        model = ScriptedModel(self)
        self.models.append(model)
        return model


class GatewayStack:
    """A real gateway application over a tmp sqlite DB and workspace."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        hub: ModelHub,
        *,
        broker: ApprovalBroker | None = None,
        limiter: RateLimiter | None = None,
        env_workspace: bool = True,
    ) -> None:
        self.workspace = tmp_path / "workspace"
        data = tmp_path / "data"
        self.workspace.mkdir(parents=True)
        data.mkdir(parents=True)
        if env_workspace:
            # The filesystem tools resolve the workspace through the env-layer
            # settings singleton, not through the snapshot (pre-existing seam).
            monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(self.workspace))
        self.data_dir = data
        self.db_path = data / "declaw.db"

        self.engine = build_engine(self.db_path)
        self.sessionmaker = build_sessionmaker(self.engine)
        # Task 7 seam: lifecycle tests patch these module-level names.
        monkeypatch.setattr("declaw.app.get_engine", lambda: self.engine)
        monkeypatch.setattr("declaw.app.get_sessionmaker", lambda: self.sessionmaker)
        monkeypatch.setattr("declaw.app.PluginHost", FakeHost)
        monkeypatch.setattr("declaw.app.DocumentWatcher", FakeWatcher)
        monkeypatch.setattr("declaw.app.EgressMonitor", FakeMonitor)

        values: dict[str, Any] = {
            "_env_file": None,
            "port": TEST_PORT,
            "data_dir": data,
            "sanitizer_required": False,
        }
        if env_workspace:
            values["workspace_dir"] = self.workspace
        self.settings = Settings(**values)  # type: ignore[call-arg]
        self.application = Application(self.settings, mode="gateway")
        self.store = FakeSecretStore()
        self.token = mint_gateway_token(self.store)
        self.broker = broker if broker is not None else ApprovalBroker()
        self.limiter = limiter if limiter is not None else RateLimiter()
        self.hub = hub
        self.app = create_app(
            self.settings,
            application=self.application,
            secret_store=self.store,
            approval_broker=self.broker,
            model_factory=hub.factory,
            rate_limiter=self.limiter,
        )
        # The tools resolve workspace paths through get_settings(); with
        # env_workspace off the env cache must not hold a stale value.
        get_settings.cache_clear()

    def client(self) -> TestClient:
        return TestClient(self.app, base_url=f"http://{BIND_AUTHORITY}")

    def login(self, client: TestClient) -> str:
        response = client.post(
            "/api/auth/login", json={"token": self.token}, headers={"Origin": ALLOWED_ORIGIN}
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        return cookie.split("=", 1)[1].split(";", 1)[0]

    def ws_headers(self, cookie: str | None = None) -> dict[str, str]:
        headers = {"Host": BIND_AUTHORITY, "Origin": ALLOWED_ORIGIN}
        if cookie is not None:
            headers["Cookie"] = f"{SESSION_COOKIE_NAME}={cookie}"
        return headers

    def connect(self, client: TestClient, cookie: str) -> Any:
        return client.websocket_connect("/ws/chat", headers=self.ws_headers(cookie))

    async def _fetch(self) -> dict[str, list[Any]]:
        engine = build_engine(self.db_path)
        maker = build_sessionmaker(engine)
        try:
            async with maker() as session:
                tasks = list((await session.exec(sm_select(Task))).all())
                episodes = list((await session.exec(sm_select(Episode))).all())
                audit = list((await session.exec(sm_select(AuditEvent))).all())
        finally:
            await engine.dispose()
        return {"tasks": tasks, "episodes": episodes, "audit": audit}

    def fetch(self) -> dict[str, list[Any]]:
        return asyncio.run(self._fetch())

    def audit_for(self, event_type: str, task_id: str) -> list[AuditEvent]:
        return [e for e in self.fetch()["audit"] if e.event_type == event_type and e.task_id == task_id]


def _stack(
    tmp_path: Path,
    monkeypatch: Any,
    hub: ModelHub,
    *,
    broker: ApprovalBroker | None = None,
    limiter: RateLimiter | None = None,
    env_workspace: bool = True,
) -> GatewayStack:
    return GatewayStack(
        tmp_path, monkeypatch, hub, broker=broker, limiter=limiter, env_workspace=env_workspace
    )


def _send_message(ws: Any, text: str) -> dict[str, Any]:
    ws.send_json({"type": MESSAGE_TYPE, "text": text})
    started = ws.receive_json()
    assert started["type"] == TURN_STARTED_TYPE
    return started


def _write_turn(ws: Any, text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drive one turn into a pending WRITE-tool approval request."""
    started = _send_message(ws, text)
    approval = ws.receive_json()
    assert approval["type"] == APPROVAL_REQUEST_TYPE
    assert approval["tool"] == WRITE_TOOL
    return started, approval


# --- WS handshake auth (spec sections 2 and 6: close 4401 BEFORE accept) ------


def test_ws_handshake_without_cookie_closes_4401() -> None:
    app = create_app(Settings(_env_file=None, port=TEST_PORT), secret_store=FakeSecretStore())  # type: ignore[call-arg]
    client = TestClient(app, base_url=f"http://{BIND_AUTHORITY}")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/chat", headers={"Host": BIND_AUTHORITY, "Origin": ALLOWED_ORIGIN}):
            pass

    assert exc_info.value.code == 4401


def test_ws_handshake_with_unknown_cookie_closes_4401() -> None:
    app = create_app(Settings(_env_file=None, port=TEST_PORT), secret_store=FakeSecretStore())  # type: ignore[call-arg]
    client = TestClient(app, base_url=f"http://{BIND_AUTHORITY}")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/chat",
            headers={
                "Host": BIND_AUTHORITY,
                "Origin": ALLOWED_ORIGIN,
                "Cookie": f"{SESSION_COOKIE_NAME}=attacker-guess",
            },
        ):
            pass

    assert exc_info.value.code == 4401


def test_handshake_refused_when_not_accepting_sessions(
    tmp_path: Path, monkeypatch: Any
) -> None:
    # stop-accepting runs FIRST in the shutdown order (spec section 5); a
    # new handshake after it must be refused, not half-served.
    stack = _stack(tmp_path, monkeypatch, ModelHub(use_tool=False))
    asyncio.run(stack.app.state.session_manager.stop_accepting_sessions())
    assert stack.app.state.session_manager.accepting is False

    with stack.client() as client:
        cookie = stack.login(client)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with stack.connect(client, cookie):
                pass
        assert exc_info.value.code == 1013


def test_corrupt_settings_file_closes_handshake(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(
        tmp_path,
        monkeypatch,
        ModelHub(),
        env_workspace=False,
    )
    (stack.data_dir / "settings.json").write_text(
        json.dumps({"workspace_dir": str(stack.data_dir)}), encoding="utf-8"
    )

    with stack.client() as client:
        cookie = stack.login(client)
        # The handshake is accepted, then the snapshot fails closed: the
        # first inbound read is the 1011 close frame.
        with stack.connect(client, cookie) as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
        assert exc_info.value.code == 1011


# --- Happy path: task row + episode row (spec section 6) -----------------------


def test_happy_turn_completes_task_and_episode_rows(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch, ModelHub(use_tool=False, final_answer=LONG_ANSWER))

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            started = _send_message(ws, "hello")
            final = ws.receive_json()
            assert final["type"] == CHAT_FINAL_TYPE
            assert final["turn_id"] == started["turn_id"]
            assert final["text"] == LONG_ANSWER

    data = stack.fetch()
    [task] = data["tasks"]
    assert task.id == started["turn_id"]
    assert task.prompt == "hello"
    assert task.status == TaskStatus.COMPLETED
    assert task.result == LONG_ANSWER

    [episode] = data["episodes"]
    assert episode.task_id == task.id
    assert episode.summary == "A" * 500  # truncated to 500 chars, no LLM call
    assert episode.tags == []


# --- M3 slice: WRITE tool, correlated approval, audited execution -------------


def test_write_tool_approval_end_to_end(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch, ModelHub(use_tool=True, final_answer="written"))

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            started, approval = _write_turn(ws, "make the file")
            turn_id = started["turn_id"]

            # While blocked on approval the task row is already RUNNING.
            [row] = stack.fetch()["tasks"]
            assert row.id == turn_id
            assert row.status == TaskStatus.RUNNING

            # The prompt shows the canonical validated arguments the user
            # is about to approve (validate-before-prompt, spec section 7).
            assert isinstance(approval["id"], str) and approval["id"]
            assert approval["args"]["path"] == WRITE_PATH
            assert approval["args"]["content"] == WRITE_CONTENT
            assert "overwrite" in approval["args"]  # schema default included
            assert WRITE_TOOL in approval["preview"]

            ws.send_json(
                {"type": "approval.response", "id": approval["id"], "approved": True}
            )
            final = ws.receive_json()
            assert final["type"] == CHAT_FINAL_TYPE
            assert final["turn_id"] == turn_id

    assert (stack.workspace / WRITE_PATH).read_text(encoding="utf-8") == WRITE_CONTENT

    data = stack.fetch()
    [task] = data["tasks"]
    assert task.status == TaskStatus.COMPLETED
    assert task.result == "written"

    # Correlated audit: execution + decision both carry the turn's task_id.
    [prompt_event] = stack.audit_for("permission.prompt", task.id)
    assert prompt_event.payload["decision"] == "approved"
    [tool_event] = stack.audit_for("tool.call", task.id)
    assert tool_event.payload["outcome"] == "ok"

    [episode] = data["episodes"]
    assert episode.task_id == task.id


def test_denied_approval_executes_nothing(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch, ModelHub(use_tool=True, final_answer="okay"))

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            started, approval = _write_turn(ws, "make the file")
            ws.send_json(
                {"type": "approval.response", "id": approval["id"], "approved": False}
            )
            final = ws.receive_json()
            assert final["type"] == CHAT_FINAL_TYPE

    assert not (stack.workspace / WRITE_PATH).exists()

    data = stack.fetch()
    [task] = data["tasks"]
    assert task.status == TaskStatus.COMPLETED  # the denial was an observation
    [prompt_event] = stack.audit_for("permission.prompt", task.id)
    assert prompt_event.payload["decision"] == "denied"
    [tool_event] = stack.audit_for("tool.call", task.id)
    assert tool_event.payload["outcome"] == "denied"


def test_approval_timeout_denies_by_default(tmp_path: Path, monkeypatch: Any) -> None:
    # 120 s in production; the injected broker shortens it so the test
    # crosses the expiry without sleeping. Default deny is the constant.
    stack = _stack(
        tmp_path,
        monkeypatch,
        ModelHub(use_tool=True, final_answer="okay"),
        broker=ApprovalBroker(timeout_seconds=0.1),
    )

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            _write_turn(ws, "make the file")  # never answered
            final = ws.receive_json()
            assert final["type"] == CHAT_FINAL_TYPE

    assert not (stack.workspace / WRITE_PATH).exists()
    data = stack.fetch()
    [task] = data["tasks"]
    [tool_event] = stack.audit_for("tool.call", task.id)
    assert tool_event.payload["outcome"] == "denied"
    assert stack.broker.pending_session_ids() == set()


# --- One active turn at a time (busy), cancellation, disconnect ----------------


def test_second_message_during_a_turn_is_busy(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch, ModelHub(use_tool=True, final_answer="written"))

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            started, approval = _write_turn(ws, "make the file")

            # A second message during the turn is rejected as busy, not queued.
            ws.send_json({"type": MESSAGE_TYPE, "text": "second message"})
            busy = ws.receive_json()
            assert busy["type"] == ERROR_TYPE
            assert busy["code"] == BUSY

            ws.send_json(
                {"type": "approval.response", "id": approval["id"], "approved": True}
            )
            final = ws.receive_json()
            assert final["type"] == CHAT_FINAL_TYPE
            assert final["turn_id"] == started["turn_id"]

    [task] = stack.fetch()["tasks"]
    assert task.prompt == "make the file"


def test_cancel_fails_task_and_denies_pending(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch, ModelHub(use_tool=True, final_answer="written"))

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            started, _approval = _write_turn(ws, "make the file")
            ws.send_json({"type": "cancel", "turn_id": started["turn_id"]})
            ack = ws.receive_json()
            assert ack["type"] == TURN_CANCELLED_TYPE
            assert ack["turn_id"] == started["turn_id"]

    data = stack.fetch()
    [task] = data["tasks"]
    assert task.status == TaskStatus.FAILED
    assert task.error == "cancelled by user"
    assert data["episodes"] == []
    assert not (stack.workspace / WRITE_PATH).exists()
    assert stack.broker.pending_session_ids() == set()
    # Nothing executed and no decision completed: no tool.call audit for it.
    assert [e for e in data["audit"] if e.event_type == "tool.call"] == []


def test_disconnect_cancels_turn_and_denies_pending(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch, ModelHub(use_tool=True, final_answer="written"))

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            _write_turn(ws, "make the file")
        # Leaving the with-block disconnects mid-approval.

    data = stack.fetch()
    [task] = data["tasks"]
    assert task.status == TaskStatus.FAILED
    assert task.error == "cancelled by user"
    assert data["episodes"] == []
    assert not (stack.workspace / WRITE_PATH).exists()
    assert stack.broker.pending_session_ids() == set()
    assert [e for e in data["audit"] if e.event_type == "tool.call"] == []
    # Session-scoped rate buckets are evicted when the connection drops.
    assert stack.limiter._chat_turn_buckets == {}  # noqa: SLF001 - Task 4 handoff
    assert stack.limiter._ws_message_buckets == {}  # noqa: SLF001 - Task 4 handoff


# --- A late cancel cannot overwrite a finished turn --------------------------


class FinalAnswerGraph:
    """A graph whose model already answered: the turn is in its terminal
    commit window (Task COMPLETED + Episode writes) the moment ainvoke
    returns — exactly where a late cancel can land."""

    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"messages": [*state["messages"], AIMessage(content=self.answer)]}


def test_late_cancel_in_commit_window_keeps_completed_turn(tmp_path: Path) -> None:
    # The terminal state of a turn is decided exactly once. A cancel landing
    # while the COMPLETED/Episode writes are already in flight must be a
    # no-op on the Task row: overwriting a finished turn to FAILED
    # "cancelled by user" contradicts the Episode and audit rows.
    asyncio.run(_late_cancel_in_commit_window(tmp_path))


async def _late_cancel_in_commit_window(tmp_path: Path) -> None:
    engine = build_engine(tmp_path / "declaw.db")
    maker = build_sessionmaker(engine)
    await ensure_schema(engine)

    session = GatewaySession(
        "session-1",
        language="en",
        broker=ApprovalBroker(timeout_seconds=60),
        limiter=RateLimiter(),
        sessionmaker=maker,
    )
    session.attach_graph(FinalAnswerGraph("all finished"))

    # The cancel is delivered reader-shaped (its own task, like the frame
    # loop in production) and released by an event set exactly when the
    # terminal COMPLETED write starts — deterministic, no sleeps.
    window = asyncio.Event()

    async def late_cancel_reader() -> None:
        await window.wait()
        assert isinstance(session.active_turn_id, str)
        await session._handle_cancel(session.active_turn_id)

    reader = asyncio.create_task(late_cancel_reader())
    real_update = session._update_task

    async def update_releasing_the_late_cancel(turn_id: str, **values: Any) -> None:
        if values.get("status") is TaskStatus.COMPLETED:
            window.set()
        await real_update(turn_id, **values)

    session._update_task = update_releasing_the_late_cancel

    await session._handle_message("do it")
    turn_task = session._turn_task
    turn_id = session.active_turn_id
    assert isinstance(turn_task, asyncio.Task)
    assert isinstance(turn_id, str)

    with suppress(asyncio.CancelledError):
        await turn_task
    await reader

    # The cancel ack frame still goes out (frame emission is fine).
    frames: list[dict[str, Any]] = []
    while True:
        try:
            frames.append(session.outbound.get_nowait())
        except asyncio.QueueEmpty:
            break
    assert {"type": TURN_CANCELLED_TYPE, "turn_id": turn_id} in frames

    try:
        async with maker() as db:
            task = await db.get(Task, turn_id)
            episodes = list((await db.exec(sm_select(Episode))).all())
    finally:
        await engine.dispose()

    assert task is not None
    assert task.status == TaskStatus.COMPLETED
    assert task.result == "all finished"
    assert task.error is None
    assert [episode.task_id for episode in episodes] == [turn_id]
    assert episodes[0].summary == "all finished"


def test_two_connections_have_isolated_histories(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch, ModelHub(use_tool=False, final_answer="fine"))

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws1:
            _send_message(ws1, "first question")
            assert ws1.receive_json()["type"] == CHAT_FINAL_TYPE

            # A second tab: same cookie, its own session and history.
            with stack.connect(client, cookie) as ws2:
                _send_message(ws2, "second question")
                assert ws2.receive_json()["type"] == CHAT_FINAL_TYPE

            # The first session's next turn still sees only its own history.
            _send_message(ws1, "third question")
            assert ws1.receive_json()["type"] == CHAT_FINAL_TYPE

    model1, model2 = stack.hub.models
    first_turn = model1.calls[0]
    fourth_turn = model1.calls[1]
    second_turn = model2.calls[0]
    assert first_turn[-1].content == "first question"  # type: ignore[attr-defined]
    assert fourth_turn[-1].content == "third question"  # type: ignore[attr-defined]
    assert second_turn[-1].content == "second question"  # type: ignore[attr-defined]
    # Tab 2's transcript never mixed into tab 1's, and vice versa.
    assert "second question" not in str(first_turn)
    assert "second question" not in str(fourth_turn)
    assert "first question" not in str(second_turn)
    assert len(second_turn) == 1  # a fresh history: only its own human message
    assert len(fourth_turn) == 3  # tab 1 kept its own completed turn


# --- Rate limits (spec section 4): typed error frames --------------------------


def test_chat_turn_rate_limit_sends_error_frame(tmp_path: Path, monkeypatch: Any) -> None:
    # FakeClock: buckets never refill, so turn 11 is deterministically over
    # the 10/minute per-session cap.
    stack = _stack(
        tmp_path, monkeypatch, ModelHub(use_tool=False), limiter=RateLimiter(clock=FakeClock())
    )

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            for _ in range(10):
                _send_message(ws, "hi")
                assert ws.receive_json()["type"] == CHAT_FINAL_TYPE

            ws.send_json({"type": MESSAGE_TYPE, "text": "eleventh"})
            error = ws.receive_json()
            assert error["type"] == ERROR_TYPE
            assert error["code"] == RATE_LIMITED

    assert len(stack.fetch()["tasks"]) == 10  # no turn row for the 11th


def test_other_ws_messages_rate_limited(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(
        tmp_path, monkeypatch, ModelHub(use_tool=False), limiter=RateLimiter(clock=FakeClock())
    )

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            for _ in range(30):
                ws.send_json({"type": "nonsense"})
            # 30 frames consumed the 30/second per-connection bucket.
            ws.send_json({"type": "nonsense"})
            frames = [ws.receive_json() for _ in range(31)]

    codes = [f for f in frames[:30]]
    assert all(f["type"] == ERROR_TYPE and f["code"] == BAD_FRAME for f in codes)
    assert frames[30]["code"] == RATE_LIMITED


# --- Model failure: typed chat error, gateway keeps serving -------------------


def test_model_failure_is_a_typed_chat_error(tmp_path: Path, monkeypatch: Any) -> None:
    stack = _stack(tmp_path, monkeypatch, ModelHub(raise_error=True))

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            _send_message(ws, "hello")
            error = ws.receive_json()
            assert error["type"] == ERROR_TYPE
            assert error["code"] == TURN_FAILED
            assert "ConnectionError" in error["message"]

            # The session survives the failed turn (error matrix, section 16).
            _send_message(ws, "again")
            assert ws.receive_json()["type"] == ERROR_TYPE

    data = stack.fetch()
    statuses = [t.status for t in data["tasks"]]
    assert all(s == TaskStatus.FAILED for s in statuses)
    for task in data["tasks"]:
        assert task.error is not None and "ConnectionError" in task.error
    assert data["episodes"] == []


# --- Gateway shutdown hooks (spec section 5, Task 7 -> Task 9 wiring) ----------


def test_gateway_shutdown_denies_pending_approvals_and_fails_tasks(
    tmp_path: Path, monkeypatch: Any
) -> None:
    # Starlette's TestClient serves in-context websockets on the SAME portal
    # as the lifespan, so "exit the client while a socket is open" is not a
    # scenario that transport can drive (the portal join never returns). The
    # shutdown sequence itself IS driveable: run the real Application.shutdown()
    # — the wired Task 7 hooks, the real manager and broker — while the
    # websocket (and its pending approval) is still connected.
    stack = _stack(
        tmp_path,
        monkeypatch,
        ModelHub(use_tool=True, final_answer="written"),
        broker=ApprovalBroker(timeout_seconds=300),
    )
    application = stack.application
    assert application._stop_accepting_sessions is not None  # noqa: SLF001 - wiring pin
    assert application._cancel_in_flight_turns is not None  # noqa: SLF001 - wiring pin
    assert application._deny_pending_approvals is not None  # noqa: SLF001 - wiring pin

    with stack.client() as client:
        cookie = stack.login(client)
        with stack.connect(client, cookie) as ws:
            _write_turn(ws, "make the file")  # approval pending, turn in flight

            # Stop accepting sessions -> cancel in-flight turns -> deny
            # pending approvals -> watcher -> host -> monitor -> engine.
            asyncio.run(application.shutdown())

            data = stack.fetch()
            [task] = data["tasks"]
            assert task.status == TaskStatus.FAILED
            assert task.error == "cancelled by user"
            assert not (stack.workspace / WRITE_PATH).exists()
            assert stack.broker.pending_session_ids() == set()
            assert stack.app.state.session_manager.accepting is False
            assert [e for e in data["audit"] if e.event_type == "tool.call"] == []


# --- Rate bucket eviction on drop (Task 4 review handoff) ---------------------


def test_rate_buckets_evicted_on_drop_connection() -> None:
    limiter = RateLimiter(clock=FakeClock())
    for _ in range(10):
        assert limiter.allow_chat_turn("session-1") is True
        assert limiter.allow_chat_turn("session-2") is True
    assert limiter.allow_chat_turn("session-1") is False
    assert limiter.allow_chat_turn("session-2") is False

    limiter.drop_connection("session-2")

    assert limiter.allow_chat_turn("session-2") is True  # fresh bucket post-eviction
    assert limiter.allow_chat_turn("session-1") is False  # untouched key stays drained
    for _ in range(30):
        assert limiter.allow_ws_message("session-2") is True
    assert limiter.allow_ws_message("session-2") is False
    limiter.drop_connection("session-2")
    assert limiter.allow_ws_message("session-2") is True


# --- Helpers ------------------------------------------------------------------

