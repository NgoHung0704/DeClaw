"""Desktop listener ownership, readiness and cooperative stop ordering."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any
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
