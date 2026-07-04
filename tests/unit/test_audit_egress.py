"""Tests for the network egress monitor (DCL-064).

Acceptance: any unintended external call is logged + flagged. All HTTP goes
through httpx.MockTransport — no real network.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from declaw.audit.egress import (
    DEFAULT_ALLOWED_HOSTS,
    EgressMonitor,
    allowed_hosts_from_settings,
)
from declaw.audit.events import NetworkCallEvent
from declaw.audit.logger import InMemoryAuditLogger


def _ok_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))


async def test_local_call_logged_not_flagged() -> None:
    audit = InMemoryAuditLogger()
    with EgressMonitor(audit):
        async with httpx.AsyncClient(transport=_ok_transport()) as client:
            await client.get("http://localhost:11434/api/tags")

    [event] = audit.events
    assert isinstance(event, NetworkCallEvent)
    assert event.host == "localhost"
    assert event.method == "GET"
    assert event.status_code == 200
    assert event.flagged is False


async def test_external_call_logged_and_flagged() -> None:
    audit = InMemoryAuditLogger()
    with EgressMonitor(audit):
        async with httpx.AsyncClient(transport=_ok_transport()) as client:
            await client.post("https://api.example.com/upload", json={"data": "x"})

    [event] = audit.events
    assert isinstance(event, NetworkCallEvent)
    assert event.host == "api.example.com"
    assert event.flagged is True  # the acceptance


async def test_failed_call_still_audited_and_error_propagates() -> None:
    audit = InMemoryAuditLogger()

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with EgressMonitor(audit):
        async with httpx.AsyncClient(transport=httpx.MockTransport(explode)) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get("https://api.example.com/x")

    [event] = audit.events
    assert isinstance(event, NetworkCallEvent)
    assert event.status_code is None
    assert event.error is not None and "refused" in event.error
    assert event.flagged is True


def test_sync_client_is_observed_too() -> None:
    audit = InMemoryAuditLogger()
    with EgressMonitor(audit):
        with httpx.Client(transport=_ok_transport()) as client:
            client.get("https://api.example.com/x")

    [event] = audit.events
    assert isinstance(event, NetworkCallEvent)
    assert event.flagged is True


async def test_sync_client_inside_running_loop_is_observed() -> None:
    audit = InMemoryAuditLogger()
    with EgressMonitor(audit):
        with httpx.Client(transport=_ok_transport()) as client:
            client.get("http://127.0.0.1:7842/status")
        await asyncio.sleep(0)  # let the scheduled emit task run

    [event] = audit.events
    assert isinstance(event, NetworkCallEvent)
    assert event.host == "127.0.0.1"
    assert event.flagged is False


async def test_uninstall_restores_httpx() -> None:
    audit = InMemoryAuditLogger()
    monitor = EgressMonitor(audit)
    monitor.install()
    monitor.install()  # idempotent
    monitor.uninstall()
    monitor.uninstall()  # idempotent

    async with httpx.AsyncClient(transport=_ok_transport()) as client:
        await client.get("https://api.example.com/x")
    assert audit.events == []  # nothing observed after uninstall


def test_allowed_hosts_from_settings_adds_ollama_host() -> None:
    hosts = allowed_hosts_from_settings("http://192.168.1.50:11434")
    assert "192.168.1.50" in hosts
    assert DEFAULT_ALLOWED_HOSTS <= hosts
