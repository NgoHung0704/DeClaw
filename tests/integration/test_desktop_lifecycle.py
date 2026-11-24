"""Actual loopback server stop while a real gateway approval is pending."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.asyncio.client import connect

from declaw.desktop import runtime
from declaw.desktop.protocol import Ready, Stop
from declaw.gateway.app import create_app
from declaw.gateway.auth import SESSION_COOKIE_NAME
from declaw.db.models import TaskStatus
from tests.gateway.test_chat_flow import GatewayStack, ModelHub, WRITE_PATH
from tests.unit.test_desktop_runtime import FakeChannel, LAUNCH


async def test_stop_during_real_websocket_approval_denies_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = GatewayStack(tmp_path, monkeypatch, ModelHub(use_tool=True))
    settings = stack.settings.model_copy(update={"port": 7842})
    application = stack.application
    # Rewire the unused TestClient manager to the desktop-owned real server.
    application._stop_accepting_sessions = None
    application._cancel_in_flight_turns = None
    application._deny_pending_approvals = None
    monkeypatch.setattr(runtime, "Application", lambda *_a, **_k: application)
    monkeypatch.setattr(runtime, "default_credential_store", lambda *_a: stack.store)

    def factory(*args: Any, **kwargs: Any) -> Any:
        stack.broker = kwargs["approval_broker"]
        return create_app(*args, **kwargs, model_factory=stack.hub.factory)

    monkeypatch.setattr(runtime, "create_app", factory)
    ready = asyncio.Event()

    class Channel(FakeChannel):
        async def send(self, frame: Any) -> None:
            self.frames.append(frame)
            if isinstance(frame, Ready):
                ready.set()

    channel = Channel()
    child = asyncio.create_task(runtime.run_desktop(settings, channel))
    try:
        await asyncio.wait_for(ready.wait(), 10)
        async with httpx.AsyncClient(base_url="http://127.0.0.1:7842", trust_env=False) as client:
            response = await client.post("/api/auth/login", json={"token": stack.token},
                                         headers={"Origin": "http://127.0.0.1:7842"})
            assert response.status_code == 200
            cookie = client.cookies.get(SESSION_COOKIE_NAME)
            async with connect("ws://127.0.0.1:7842/ws/chat",
                               origin="http://127.0.0.1:7842",
                               additional_headers={"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"}) as ws:
                await ws.send(json.dumps({"type": "message", "text": "write a file"}))
                async with asyncio.timeout(10):
                    while json.loads(await ws.recv())["type"] != "approval.request":
                        pass
                await channel.incoming.put(Stop(launch_id=LAUNCH))
                assert await asyncio.wait_for(child, 10) == 0
        assert not (stack.workspace / WRITE_PATH).exists()
        assert stack.broker.pending_session_ids() == set()
        rows = await stack._fetch()
        assert rows["tasks"][0].status == TaskStatus.FAILED
        assert not [e for e in rows["audit"] if e.event_type == "tool.call"]
        lifecycle = [e.payload["phase"] for e in rows["audit"] if e.event_type == "desktop.lifecycle"]
        assert lifecycle == ["ready", "stop_requested"]
        assert channel.frames[-1].clean is True
    finally:
        if not child.done():
            await channel.incoming.put(None)
            await asyncio.wait_for(child, 12)
