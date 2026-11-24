"""Desktop listener ownership, readiness and cooperative stop ordering."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI

from declaw.config import Settings
from declaw.desktop import runtime
from declaw.desktop.protocol import BootstrapToken, ChildFrame, Ready, RequestBootstrapToken, Stop

LAUNCH = str(uuid4())


class FakeChannel:
    launch_id = LAUNCH

    def __init__(self) -> None:
        self.incoming: asyncio.Queue[Stop | RequestBootstrapToken | None] = asyncio.Queue()
        self.frames: list[ChildFrame] = []
        self.tokens: list[BootstrapToken] = []
        self.closed = False

    async def receive(self) -> Stop | RequestBootstrapToken | None:
        return await self.incoming.get()

    async def send(self, frame: ChildFrame) -> None:
        self.frames.append(frame)
        if isinstance(frame, Ready):
            await self.incoming.put(Stop(launch_id=LAUNCH))

    async def send_bootstrap_token(self, frame: BootstrapToken) -> None:
        self.tokens.append(frame)

    async def close(self) -> None:
        self.closed = True


def settings(tmp_path: Path, **values: Any) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data",  # type: ignore[call-arg]
                    workspace_dir=tmp_path / "workspace", **values)


@pytest.mark.parametrize("change", [{"port": 7843}, {"host": "localhost"}])
async def test_invalid_desktop_settings_before_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, object],
) -> None:
    monkeypatch.setattr(runtime, "Application", lambda *_a, **_k: pytest.fail("constructed"))
    channel = FakeChannel()
    result = await runtime.run_desktop(settings(tmp_path).model_copy(update=change), channel)
    assert result == 1
    assert channel.frames[0].code == "invalid_settings"  # type: ignore[union-attr]
    assert channel.closed


async def test_busy_port_does_not_construct_application_or_touch_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 7842))
        listener.listen()
        monkeypatch.setattr(runtime, "Application", lambda *_a, **_k: pytest.fail("constructed"))
        channel = FakeChannel()
        assert await runtime.run_desktop(settings(tmp_path), channel) == 1
        assert channel.frames[0].code == "port_conflict"  # type: ignore[union-attr]
        assert listener.getsockname()[1] == 7842
    finally:
        listener.close()


@pytest.mark.parametrize("shutdown_fails", [False, True])
async def test_ready_only_after_serving_and_quiesce_before_server_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shutdown_fails: bool,
) -> None:
    calls: list[str] = []

    class App:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            calls.append("construct")

        async def start(self) -> None:
            calls.append("start")

        async def shutdown(self) -> None:
            calls.append("shutdown")
            if shutdown_fails:
                raise RuntimeError("private exception text")

    class Manager:
        async def stop_accepting_sessions(self) -> None:
            calls.append("refuse")

        async def cancel_in_flight_turns(self) -> None:
            calls.append("cancel")

        async def deny_pending_approvals(self) -> None:
            calls.append("deny")

    gateway = FastAPI()
    gateway.state.session_manager = Manager()

    class Server:
        started = False
        should_exit = False

        def __init__(self, _config: object) -> None:
            pass

        async def serve(self, sockets: list[socket.socket]) -> None:
            assert sockets[0].getsockname() == ("127.0.0.1", 7842)
            calls.append("lifespan.started")
            self.started = True
            while not self.should_exit:
                await asyncio.sleep(.001)
            calls.append("drain")

    monkeypatch.setattr(runtime, "Application", App)
    monkeypatch.setattr(runtime, "create_app", lambda *_a, **_k: gateway)
    monkeypatch.setattr(runtime.uvicorn, "Server", Server)
    monkeypatch.setattr(runtime, "default_credential_store", lambda *_a: object())
    channel = FakeChannel()
    assert await runtime.run_desktop(settings(tmp_path), channel) == (1 if shutdown_fails else 0)
    assert calls.index("lifespan.started") < calls.index("refuse")
    assert calls.index("refuse") < calls.index("cancel") < calls.index("deny") < calls.index("drain")
    assert calls.count("shutdown") == 1
    assert channel.frames[-1].clean is (not shutdown_fails)  # type: ignore[union-attr]
    assert channel.closed


async def test_stale_control_generation_fails_closed(tmp_path: Path) -> None:
    channel = FakeChannel()
    await channel.incoming.put(Stop(launch_id=str(uuid4())))
    # Validation is separately testable before constructing real application services.
    with pytest.raises(runtime.ProtocolError, match="protocol_invalid"):
        await runtime.receive_control(channel, asyncio.Event(), lambda: "fake-token")


async def test_token_only_on_explicit_request_and_separate_sender() -> None:
    channel = FakeChannel()
    request_id = str(uuid4())
    await channel.incoming.put(RequestBootstrapToken(launch_id=LAUNCH, request_id=request_id))
    await channel.incoming.put(None)
    stopped = asyncio.Event()
    await runtime.receive_control(channel, stopped, lambda: "fake-token")
    assert stopped.is_set()
    assert channel.frames == []
    assert len(channel.tokens) == 1
    assert channel.tokens[0].request_id == request_id


@pytest.mark.parametrize("fault", [
    "before_ready", "after_ready", "cancelled_server", "cancelled_drain",
    "refuse", "cancel", "deny",
    "timeout_refuse", "timeout_drain", "timeout_shutdown",
])
async def test_runtime_fault_still_shuts_down_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    calls: list[str] = []
    ready = asyncio.Event()

    class Channel(FakeChannel):
        async def send(self, frame: ChildFrame) -> None:
            self.frames.append(frame)
            if isinstance(frame, Ready):
                ready.set()
                if fault not in {"after_ready", "cancelled_server"}:
                    await self.incoming.put(Stop(launch_id=LAUNCH))

    class App:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            calls.append("start")

        async def shutdown(self) -> None:
            calls.append("shutdown")
            if fault == "timeout_shutdown":
                try:
                    await asyncio.Future[None]()
                finally:
                    calls.append("shutdown.cancelled")

    class Manager:
        async def step(self, name: str) -> None:
            calls.append(name)
            if fault == name:
                raise RuntimeError("private exception text")
            if fault == "timeout_refuse" and name == "refuse":
                await asyncio.Future[None]()

        async def stop_accepting_sessions(self) -> None:
            await self.step("refuse")

        async def cancel_in_flight_turns(self) -> None:
            await self.step("cancel")

        async def deny_pending_approvals(self) -> None:
            await self.step("deny")

    class Server:
        started = False
        should_exit = False

        def __init__(self, _config: object) -> None:
            pass

        async def serve(self, sockets: list[socket.socket]) -> None:
            if fault == "before_ready":
                raise RuntimeError("private exception text")
            self.started = True
            if fault in {"after_ready", "cancelled_server"}:
                await ready.wait()
                if fault == "cancelled_server":
                    raise asyncio.CancelledError
                raise RuntimeError("private exception text")
            while not self.should_exit:
                await asyncio.sleep(0)
            calls.append("drain")
            if fault == "cancelled_drain":
                raise asyncio.CancelledError
            if fault == "timeout_drain":
                await asyncio.Future[None]()

    listener = Mock()
    gateway = FastAPI()
    gateway.state.session_manager = Manager()
    monkeypatch.setattr(runtime, "reserve_listener", lambda _settings: listener)
    monkeypatch.setattr(runtime, "Application", App)
    monkeypatch.setattr(runtime, "create_app", lambda *_a, **_k: gateway)
    monkeypatch.setattr(runtime, "default_credential_store", lambda *_a: object())
    monkeypatch.setattr(runtime.uvicorn, "Server", Server)
    monkeypatch.setattr(runtime, "SHUTDOWN_SECONDS", .05)
    channel = Channel()

    assert await asyncio.wait_for(runtime.run_desktop(settings(tmp_path), channel), 1) == 1
    assert calls.count("shutdown") == (
        0 if fault in {"timeout_refuse", "timeout_drain"} else 1
    )
    assert [call for call in calls if call in {"refuse", "cancel", "deny"}] == [
        "refuse", *([] if fault == "timeout_refuse" else ["cancel", "deny"]),
    ]
    assert ready.is_set() is (fault != "before_ready")
    if fault in {"refuse", "cancel", "deny"}:
        assert calls.index("drain") < calls.index("shutdown")
    if fault == "timeout_shutdown":
        assert "shutdown.cancelled" in calls
    assert channel.frames[-1].clean is False  # type: ignore[union-attr]
    assert "private exception text" not in repr(channel.frames)
    assert channel.closed
    listener.close.assert_called_once()


async def test_partial_start_cancellation_does_not_swallow_shutdown_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    calls: list[str] = []

    class Channel(FakeChannel):
        async def receive(self) -> Stop:
            await started.wait()
            return Stop(launch_id=LAUNCH)

    class App:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            started.set()
            try:
                await asyncio.Future[None]()
            except asyncio.CancelledError:
                calls.append("rollback")
                # Rollback also cooperates when the shared stop budget expires.
                await asyncio.Future[None]()

        async def shutdown(self) -> None:
            calls.append("shutdown")

    listener = Mock()
    monkeypatch.setattr(runtime, "reserve_listener", lambda _settings: listener)
    monkeypatch.setattr(runtime, "Application", App)
    monkeypatch.setattr(runtime, "create_app", lambda *_a, **_k: FastAPI())
    monkeypatch.setattr(runtime, "default_credential_store", lambda *_a: object())
    monkeypatch.setattr(runtime, "SHUTDOWN_SECONDS", .05)
    channel = Channel()

    assert await asyncio.wait_for(runtime.run_desktop(settings(tmp_path), channel), 1) == 1
    assert calls == ["rollback"]
    assert channel.frames[-1].clean is False  # type: ignore[union-attr]
    assert channel.closed
    listener.close.assert_called_once()
