"""Native notice loss cannot affect authoritative approvals or audit."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from declaw.desktop.notifications import NoticeEmitter
from declaw.desktop.protocol import Notice
from declaw.gateway.approval import ApprovalBroker
from tests.gateway.test_approval import _WriteTool


async def test_notice_is_bounded_safe_and_uses_effective_language() -> None:
    frames: list[Notice] = []

    async def send(frame: Notice) -> None:
        frames.append(frame)

    emitter = NoticeEmitter(str(uuid4()), lambda: "fr", send)
    for _ in range(100):
        emitter.emit_notice("quarantine", str(uuid4()), None)
    assert emitter.pending == 64
    task = asyncio.create_task(emitter.run())
    for _ in range(100):
        if len(frames) == 64:
            break
        await asyncio.sleep(.001)
    await emitter.close()
    await task
    assert len(frames) == 64
    assert all(frame.language == "fr" and frame.task_id is None for frame in frames)
    assert not any(hasattr(frame, "preview") for frame in frames)


async def test_bad_notice_hook_or_transport_does_not_escape() -> None:
    async def broken(_frame: Notice) -> None:
        raise RuntimeError("fake-secret must not be logged")

    emitter = NoticeEmitter(str(uuid4()), lambda: "en", broken)
    emitter.emit_notice("quarantine", "filename.txt", None)
    assert emitter.pending == 0
    emitter.emit_notice("quarantine", str(uuid4()), None)
    task = asyncio.create_task(emitter.run())
    await asyncio.sleep(.01)
    await emitter.close()
    await task
    assert emitter.pending == 0


async def test_approval_notice_cannot_change_default_deny() -> None:
    notices: list[str] = []

    def broken(request_id: str) -> None:
        notices.append(request_id)
        raise RuntimeError("unavailable native notice")

    broker = ApprovalBroker(timeout_seconds=.01, pending_notice=broken)
    outbound: list[dict[str, object]] = []
    provider = broker.create_provider("session", outbound.append)
    assert await provider(_WriteTool(), {"path": "test.txt"}) is False
    assert notices == [outbound[0]["id"]]
    assert broker.pending_session_ids() == set()
