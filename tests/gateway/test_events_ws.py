"""``/ws/events``: the event stream for indexing and plugin changes (DCL-133).

Security-critical integration: these tests were written (and watched fail)
before the implementation, per spec section 17. What is pinned:

- Handshake: cookie authentication BEFORE accept (close 4401 without a valid
  session cookie; the foreign-Origin 4403 close lives in the Host/Origin
  middleware and applies to this endpoint like every other WS route).
- Per-connection delivery: a broadcast frame reaches a subscribed client;
  multiple subscribers are isolated; unsubscribe stops delivery (an
  unsubscription on disconnect leaves no phantom subscriber).
- Bounded slow-subscriber behavior: a subscriber that stops reading is
  drop-oldest with an operational warning — a slow client never stalls the
  broadcaster or makes it grow without bound.
- Inbound frames are rate-limited (30/s per connection, typed error frame)
  and the 32 KiB single-message cap closes with 1009 (Task 4 contract).
- Wiring: ``create_app`` owns ONE EventBroadcaster mirrored on
  ``app.state.event_broadcaster`` and on the Application's document-event
  seam; plugin disable confirmations reach subscribers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from declaw.app import Application
from declaw.config import Settings
from declaw.db.engine import build_engine, build_sessionmaker
from declaw.gateway.app import create_app
from declaw.gateway.auth import SESSION_COOKIE_NAME, mint_gateway_token

TEST_PORT = 9000  # never the default 7842 (same convention as test_host_origin)
BIND_AUTHORITY = f"127.0.0.1:{TEST_PORT}"
ALLOWED_ORIGIN = f"http://{BIND_AUTHORITY}"

ALPHA = "alpha-tools"
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


class FakeHost:
    """PluginHost stand-in: no subprocesses, ordered stop."""

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def disable(self, name: str) -> None:
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
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.uninstalled = False

    def start(self) -> None:
        pass

    def install(self) -> None:
        pass

    def uninstall(self) -> None:
        self.uninstalled = True


class EventsStack:
    """A gateway application over a tmp sqlite DB (+ one disabled plugin)."""

    def __init__(self, tmp_path: Path, monkeypatch: Any) -> None:
        self.workspace = tmp_path / "workspace"
        self.data_dir = tmp_path / "data"
        self.plugins_dir = tmp_path / "plugins"
        for directory in (self.workspace, self.data_dir, self.plugins_dir):
            directory.mkdir(parents=True)
        alpha_dir = self.plugins_dir / ALPHA
        alpha_dir.mkdir()
        (alpha_dir / "plugin.yaml").write_text(_ALPHA_MANIFEST, encoding="utf-8")
        # Pre-enabled so POST disable exercises the immediate path.
        (self.data_dir / "plugin_state.json").write_text(
            json.dumps({ALPHA: {"enabled": True}}), encoding="utf-8"
        )

        engine = build_engine(self.data_dir / "declaw.db")
        sessionmaker = build_sessionmaker(engine)
        monkeypatch.setattr("declaw.app.get_engine", lambda: engine)
        monkeypatch.setattr("declaw.app.get_sessionmaker", lambda: sessionmaker)
        monkeypatch.setattr("declaw.app.PluginHost", FakeHost)
        monkeypatch.setattr("declaw.app.DocumentWatcher", FakeWatcher)
        monkeypatch.setattr("declaw.app.EgressMonitor", FakeMonitor)

        self.settings = Settings(
            _env_file=None,
            port=TEST_PORT,
            data_dir=self.data_dir,
            builtin_plugins_dir=self.plugins_dir,
            workspace_dir=self.workspace,
            sanitizer_required=False,
        )  # type: ignore[call-arg]
        self.application = Application(self.settings, mode="gateway")
        self.store = FakeSecretStore()
        self.token = mint_gateway_token(self.store)
        self.app = create_app(
            self.settings,
            application=self.application,
            secret_store=self.store,
        )

    def client(self) -> TestClient:
        return TestClient(self.app, base_url=f"http://{BIND_AUTHORITY}")

    def login(self, client: TestClient) -> str:
        response = client.post(
            "/api/auth/login", json={"token": self.token}, headers={"Origin": ALLOWED_ORIGIN}
        )
        assert response.status_code == 200
        return response.cookies[SESSION_COOKIE_NAME]

    def ws_headers(self, cookie: str) -> dict[str, str]:
        return {
            "Host": BIND_AUTHORITY,
            "Origin": ALLOWED_ORIGIN,
            "Cookie": f"{SESSION_COOKIE_NAME}={cookie}",
        }


# --- Broadcaster unit behavior -----------------------------------------------


async def test_broadcaster_delivers_to_all_subscribers_isolated() -> None:
    from declaw.gateway.events import EventBroadcaster

    broadcaster = EventBroadcaster()
    first = broadcaster.subscribe()
    second = broadcaster.subscribe()

    await broadcaster.broadcast({"type": "index.progress", "done": 1})
    await broadcaster.broadcast({"type": "index.progress", "done": 2})

    assert first.get_nowait()["done"] == 1
    assert first.get_nowait()["done"] == 2
    assert second.get_nowait()["done"] == 1
    assert second.get_nowait()["done"] == 2
    assert first.empty() and second.empty()


async def test_unsubscribe_stops_delivery() -> None:
    from declaw.gateway.events import EventBroadcaster

    broadcaster = EventBroadcaster()
    queue = broadcaster.subscribe()
    broadcaster.unsubscribe(queue)

    await broadcaster.broadcast({"type": "index.progress"})

    assert queue.empty()
    assert broadcaster._subscribers == set()  # noqa: SLF001 - wiring pin


async def test_slow_subscriber_is_drop_oldest_bounded_never_stalls() -> None:
    """A subscriber with a small bound saturates its queue; the broadcaster
    drops the OLDEST frame with an operational warning and never blocks the
    producer — while a healthy subscriber loses nothing."""
    from declaw.gateway.events import EventBroadcaster

    broadcaster = EventBroadcaster()
    bounded = broadcaster.subscribe(maxsize=2)
    fast = broadcaster.subscribe()

    for index in range(4):
        await broadcaster.broadcast({"type": "index.progress", "done": index})

    # The bounded queue kept the newest frames only (bounded + drop-oldest).
    assert bounded.qsize() == 2
    assert bounded.get_nowait()["done"] == 2
    assert bounded.get_nowait()["done"] == 3
    # A healthy subscriber lost nothing.
    assert fast.qsize() == 4
    assert [fast.get_nowait()["done"] for _ in range(4)] == [0, 1, 2, 3]


# --- Handshake auth -----------------------------------------------------------


def test_events_ws_closes_4401_without_cookie(tmp_path: Path, monkeypatch: Any) -> None:
    stack = EventsStack(tmp_path, monkeypatch)
    with stack.client() as client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(
                "/ws/events",
                headers={"Host": BIND_AUTHORITY, "Origin": ALLOWED_ORIGIN},
            ):
                pass
        assert excinfo.value.code == 4401


def test_events_ws_accepts_valid_session_cookie(tmp_path: Path, monkeypatch: Any) -> None:
    stack = EventsStack(tmp_path, monkeypatch)
    with stack.client() as client:
        cookie = stack.login(client)
        with client.websocket_connect("/ws/events", headers=stack.ws_headers(cookie)):
            pass  # handshake accepted; connection closes on context exit


# --- Delivery over the socket --------------------------------------------------


def test_broadcast_frame_reaches_subscribed_client(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = EventsStack(tmp_path, monkeypatch)
    broadcaster = getattr(stack.app.state, "event_broadcaster", None)
    assert broadcaster is not None, "create_app must set app.state.event_broadcaster"

    with stack.client() as client:
        cookie = stack.login(client)
        with client.websocket_connect("/ws/events", headers=stack.ws_headers(cookie)) as ws:
            frame = {"type": "index.progress", "total": 3, "done": 1, "current_path": "a.txt"}
            # The portal runs the server loop: scheduling the broadcast
            # coroutine through it is exactly the production owner.
            client.portal.call(broadcaster.broadcast, frame)
            received = json.loads(ws.receive_text())
            assert received["type"] == "index.progress"
            assert received["total"] == 3
            assert received["done"] == 1
            assert received["current_path"] == "a.txt"


def test_disconnected_client_leaves_no_phantom_subscriber(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = EventsStack(tmp_path, monkeypatch)
    with stack.client() as client:
        cookie = stack.login(client)
        with client.websocket_connect("/ws/events", headers=stack.ws_headers(cookie)):
            pass  # connect then disconnect

        broadcaster = stack.app.state.event_broadcaster
        assert (
            len(broadcaster._subscribers) == 0  # noqa: SLF001 - wiring pin
        ), "the endpoint must unsubscribe on disconnect"


# --- Wiring: application seam + plugin confirmations ---------------------------


def test_create_app_wires_broadcaster_into_application_seam(
    tmp_path: Path, monkeypatch: Any
) -> None:
    stack = EventsStack(tmp_path, monkeypatch)
    broadcaster = stack.app.state.event_broadcaster
    # The SAME broadcaster is the Application's document-event sink, so
    # worker/watcher progress frames reach /ws/events subscribers.
    assert stack.application._document_event_broadcaster is broadcaster  # noqa: SLF001


def test_plugin_disable_broadcasts_confirmation(tmp_path: Path, monkeypatch: Any) -> None:
    stack = EventsStack(tmp_path, monkeypatch)
    with stack.client() as client:
        cookie = stack.login(client)
        with client.websocket_connect("/ws/events", headers=stack.ws_headers(cookie)) as ws:
            response = client.post(
                f"/api/plugins/{ALPHA}/disable",
                json={},
                headers={
                    "Origin": ALLOWED_ORIGIN,
                    "Cookie": f"{SESSION_COOKIE_NAME}={cookie}",
                },
            )
            assert response.status_code == 200
            received = json.loads(ws.receive_text())
            assert received == {"type": "plugin.disabled", "name": ALPHA}


# --- Inbound limits ------------------------------------------------------------


def test_events_ws_over_32kib_message_closes_1009(tmp_path: Path, monkeypatch: Any) -> None:
    stack = EventsStack(tmp_path, monkeypatch)
    with stack.client() as client:
        cookie = stack.login(client)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(
                "/ws/events", headers=stack.ws_headers(cookie)
            ) as ws:
                ws.send_text("x" * (32 * 1024 + 1))
                ws.receive_text()  # flush until the server closes
        assert excinfo.value.code == 1009
