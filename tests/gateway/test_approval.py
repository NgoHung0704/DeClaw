"""ApprovalBroker tests (DCL-125, spec section 7).

The broker is the gateway's answer to the reusable ``ConfirmationProvider``
seam: per session, its provider publishes an ``approval.request`` message on
that session's outbound queue (never a socket; the transport is a later task)
and resolves the decision from ``approval.response`` replies, defaulting to
deny on every failure mode. Reply acceptance is strict — the id must exist,
belong to the answering session, be unexpired and unanswered; anything else
is ignored and logged as an attack/bug indicator.

Red first: this module is written before ``declaw/gateway/approval.py``
exists and before the confirmation wrapper validates before prompting, so the
invalid-args test below fails against the current wrapper too (it raises a
``ValidationError`` instead of returning an observation without prompting).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from loguru import logger as loguru_logger
from pydantic import BaseModel

from declaw.gateway.approval import ApprovalBroker
from declaw.tools.base import DeclawTool, ToolClass
from declaw.tools.confirmation import wrap_tool_with_confirmation


# --- Scaffolding: DeclawTools with/without a preview ------------------------


class _MoveArgs(BaseModel):
    moves: list[str]
    dry_run: bool = False


class _MoveTool(DeclawTool[_MoveArgs]):
    name: str = "organize"
    description_en: str = "Organize files (EN)."
    description_fr: str = "Organise les fichiers (FR)."
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[_MoveArgs] = _MoveArgs

    def confirmation_preview(self, args: dict[str, Any]) -> str | None:
        return "Move files:\n  a.pdf -> ACME/a.pdf"

    async def _arun(self, args: _MoveArgs) -> str:
        return f"moved {len(args.moves)}"


class _WriteArgs(BaseModel):
    path: str


class _WriteTool(DeclawTool[_WriteArgs]):
    name: str = "gateway_write"
    description_en: str = "Write a file (EN)."
    description_fr: str = "Ecrire un fichier (FR)."
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[_WriteArgs] = _WriteArgs

    async def _arun(self, args: _WriteArgs) -> str:
        return f"wrote {args.path}"


class ManualClock:
    """Callable clock the broker accepts; ``advance`` moves time forward."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def captured_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture loguru records into caplog (caplog only sees stdlib logging)."""
    caplog.set_level(logging.DEBUG)
    sink_logger = logging.getLogger("declaw.gateway.test_approval_sink")

    def sink(message: object) -> None:
        sink_logger.debug(str(message))

    handler_id = loguru_logger.add(sink, level="DEBUG")
    try:
        yield caplog
    finally:
        loguru_logger.remove(handler_id)


def logged_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


# --- Request publishing -----------------------------------------------------


async def test_publishes_approval_request_and_approves_on_reply() -> None:
    clock = ManualClock()
    broker = ApprovalBroker(clock=clock)
    outbound: list[dict[str, Any]] = []
    approve = broker.create_provider("session-a", outbound.append)

    task = asyncio.create_task(approve(_MoveTool(), {"moves": ["a.pdf"], "dry_run": False}))
    await asyncio.sleep(0)  # let the request be published

    [request] = outbound
    assert request["type"] == "approval.request"
    assert request["session_id"] == "session-a"
    assert request["tool"] == "organize"
    assert request["args"] == {"moves": ["a.pdf"], "dry_run": False}
    assert request["preview"] == "Move files:\n  a.pdf -> ACME/a.pdf"
    assert request["expires_at"] == clock() + 120  # now + 120s (spec section 7)
    assert isinstance(request["id"], str) and request["id"]

    broker.handle_response("session-a", {"id": request["id"], "approved": True})
    assert await asyncio.wait_for(task, 2.0) is True


async def test_default_preview_renders_the_console_text_and_denies() -> None:
    broker = ApprovalBroker()
    outbound: list[dict[str, Any]] = []
    approve = broker.create_provider("session-a", outbound.append)

    task = asyncio.create_task(approve(_WriteTool(), {"path": "x.txt"}))
    await asyncio.sleep(0)

    [request] = outbound
    # Same text the console flow shows when a tool has no preview of its own.
    assert request["preview"] == "DeClaw wants to call gateway_write(path='x.txt')."

    broker.handle_response("session-a", {"id": request["id"], "approved": False})
    assert await asyncio.wait_for(task, 2.0) is False


# --- Validate before prompt, on the gateway path as well --------------------


async def test_invalid_args_return_observation_without_publishing_a_request() -> None:
    """The wrapper validates first: invalid args mean nothing is published on
    the session's queue — the model gets the validation error directly."""
    broker = ApprovalBroker()
    outbound: list[dict[str, Any]] = []
    approve = broker.create_provider("session-a", outbound.append)

    wrapped = wrap_tool_with_confirmation(_WriteTool(), "en", approve)
    result = await wrapped.ainvoke({"destination": "missing the required path"})

    assert "Invalid arguments for gateway_write" in result
    assert outbound == []  # no approval.request ever left the broker


# --- Default deny survives every failure mode -------------------------------


async def test_timeout_denies_by_default() -> None:
    broker = ApprovalBroker(timeout_seconds=0.02)
    outbound: list[dict[str, Any]] = []
    approve = broker.create_provider("session-a", outbound.append)

    assert await approve(_WriteTool(), {"path": "x"}) is False
    assert len(outbound) == 1  # the request was published, just never answered


async def test_expired_request_auto_denies_and_cannot_be_resurrected(
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    broker = ApprovalBroker(timeout_seconds=0.02)
    outbound: list[dict[str, Any]] = []
    approve = broker.create_provider("session-a", outbound.append)

    task = asyncio.create_task(approve(_WriteTool(), {"path": "x"}))
    await asyncio.sleep(0)
    request_id = outbound[0]["id"]

    assert await asyncio.wait_for(task, 2.0) is False  # expiry denied the future

    # A late "yes" for the expired request must not resurrect it.
    broker.handle_response("session-a", {"id": request_id, "approved": True})
    assert any("ignored" in message for message in logged_messages(captured_logs))
    assert task.result() is False


async def test_session_disconnect_denies_only_that_sessions_requests() -> None:
    broker = ApprovalBroker()
    outbound_a: list[dict[str, Any]] = []
    outbound_b: list[dict[str, Any]] = []
    approve_a = broker.create_provider("session-a", outbound_a.append)
    approve_b = broker.create_provider("session-b", outbound_b.append)
    tool = _WriteTool()

    task_a1 = asyncio.create_task(approve_a(tool, {"path": "one.txt"}))
    task_a2 = asyncio.create_task(approve_a(tool, {"path": "two.txt"}))
    task_b = asyncio.create_task(approve_b(tool, {"path": "other.txt"}))
    await asyncio.sleep(0)

    broker.deny_all("session-a", "session disconnect")

    assert await asyncio.wait_for(task_a1, 2.0) is False
    assert await asyncio.wait_for(task_a2, 2.0) is False
    assert not task_b.done()  # another user's pending approval survived

    broker.handle_response("session-b", {"id": outbound_b[0]["id"], "approved": True})
    assert await asyncio.wait_for(task_b, 2.0) is True


# --- Reply acceptance: strict, and rejects are logged -----------------------


async def test_cross_session_reply_ignored(
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    broker = ApprovalBroker()
    outbound: list[dict[str, Any]] = []
    approve = broker.create_provider("session-a", outbound.append)

    task = asyncio.create_task(approve(_WriteTool(), {"path": "x.txt"}))
    await asyncio.sleep(0)
    request_id = outbound[0]["id"]

    # session-b answers session-a's request: never allowed (one user's
    # approval must not release another user's tool call).
    broker.handle_response("session-b", {"id": request_id, "approved": True})
    await asyncio.sleep(0)
    assert not task.done()
    assert any("session" in message.lower() for message in logged_messages(captured_logs))

    # The rightful session can still answer.
    broker.handle_response("session-a", {"id": request_id, "approved": True})
    assert await asyncio.wait_for(task, 2.0) is True


async def test_duplicate_reply_accepted_once_then_rejected(
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    broker = ApprovalBroker()
    outbound: list[dict[str, Any]] = []
    approve = broker.create_provider("session-a", outbound.append)

    task = asyncio.create_task(approve(_WriteTool(), {"path": "x.txt"}))
    await asyncio.sleep(0)
    reply = {"id": outbound[0]["id"], "approved": True}

    broker.handle_response("session-a", reply)
    assert await asyncio.wait_for(task, 2.0) is True

    broker.handle_response("session-a", reply)  # replayed: ignored + logged
    assert any("ignored" in message for message in logged_messages(captured_logs))


async def test_stale_reply_rejected(
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    clock = ManualClock()
    broker = ApprovalBroker(timeout_seconds=0.05, clock=clock)
    outbound: list[dict[str, Any]] = []
    approve = broker.create_provider("session-a", outbound.append)

    task = asyncio.create_task(approve(_WriteTool(), {"path": "x.txt"}))
    await asyncio.sleep(0)
    request_id = outbound[0]["id"]

    clock.advance(10)  # the request is past its expiry when the reply lands
    broker.handle_response("session-a", {"id": request_id, "approved": True})
    await asyncio.sleep(0)
    assert not task.done()  # the stale approval did not resolve the future
    assert any("expired" in message.lower() for message in logged_messages(captured_logs))

    assert await asyncio.wait_for(task, 2.0) is False  # default deny stands


async def test_unknown_request_id_reply_is_ignored_and_logged(
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    broker = ApprovalBroker()
    broker.handle_response("session-a", {"id": "never-issued", "approved": True})
    assert any("unknown" in message.lower() for message in logged_messages(captured_logs))


async def test_reply_without_id_is_ignored_and_logged(
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    broker = ApprovalBroker()
    broker.handle_response("session-a", {"approved": True})
    assert any("ignored" in message.lower() for message in logged_messages(captured_logs))


async def test_unusable_queue_fails_closed_without_leaking_pending(
    captured_logs: pytest.LogCaptureFixture,
) -> None:
    """A session queue that cannot take the request must not leave a ghost
    entry the broker would later resolve on (default deny stands)."""

    def broken_enqueue(message: dict[str, Any]) -> None:
        raise RuntimeError("queue closed")

    broker = ApprovalBroker()
    approve = broker.create_provider("session-a", broken_enqueue)
    with pytest.raises(RuntimeError):
        await approve(_WriteTool(), {"path": "x"})

    assert broker._pending == {}  # no ghost request to answer later
    assert any("could not be queued" in message for message in logged_messages(captured_logs))
