"""Restart policy, driven by a fake process and an injected clock.

No test here sleeps: `sleep` records the durations it was asked for.
"""

from __future__ import annotations

from typing import Any

import pytest

from declaw.plugin_host.errors import (
    PluginCrashedError,
    PluginTimeoutError,
    PluginUnavailableError,
    ProtocolViolationError,
)
from declaw.plugin_host.supervisor import CRASH_LIMIT, VIOLATION_LIMIT, PluginSupervisor


class FakeProcess:
    """A process whose next answer the test chooses."""

    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.started = 0
        self.killed = 0
        self.stopped = 0

    @property
    def running(self) -> bool:
        return self.started > self.stopped + self.killed

    async def start(self) -> None:
        self.started += 1

    async def request(self, method: str, params: Any = None, *, timeout: float) -> Any:
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def shutdown(self) -> None:
        self.stopped += 1

    async def kill(self) -> None:
        self.killed += 1


class Harness:
    def __init__(self, script: list[Any]) -> None:
        self.processes: list[FakeProcess] = []
        self.script = script
        self.slept: list[float] = []
        self.now = 0.0
        self.quarantines: list[str] = []

    def factory(self) -> FakeProcess:
        process = FakeProcess(self.script)
        self.processes.append(process)
        return process

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def supervisor(self) -> PluginSupervisor:
        return PluginSupervisor(
            name="echo-plugin",
            factory=self.factory,
            on_quarantine=self.quarantines.append,
            clock=self.clock,
            sleep=self.sleep,
        )


async def test_a_healthy_call_just_returns() -> None:
    harness = Harness(["pong"])
    supervisor = harness.supervisor()
    await supervisor.start()
    assert await supervisor.call("invoke", {}, timeout=1.0) == "pong"


async def test_a_crash_restarts_the_process_and_still_raises() -> None:
    harness = Harness([PluginCrashedError("died"), "pong"])
    supervisor = harness.supervisor()
    await supervisor.start()
    with pytest.raises(PluginCrashedError):
        await supervisor.call("invoke", {}, timeout=1.0)
    assert len(harness.processes) == 2  # a replacement was spawned
    assert await supervisor.call("invoke", {}, timeout=1.0) == "pong"


async def test_backoff_grows_then_caps_at_sixty_seconds() -> None:
    harness = Harness([PluginCrashedError("x") for _ in range(20)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(8):
        with pytest.raises((PluginCrashedError, PluginUnavailableError)):
            await supervisor.call("invoke", {}, timeout=1.0)
        harness.now += 400.0  # keep each crash outside the window, so it never quarantines
    assert harness.slept[:3] == [1.0, 2.0, 4.0]
    assert max(harness.slept) <= 60.0


async def test_three_crashes_inside_the_window_quarantine_the_plugin() -> None:
    harness = Harness([PluginCrashedError("x") for _ in range(CRASH_LIMIT)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(CRASH_LIMIT):
        with pytest.raises(PluginCrashedError):
            await supervisor.call("invoke", {}, timeout=1.0)
    assert supervisor.quarantined is True
    assert harness.quarantines and "crash" in harness.quarantines[0].lower()


async def test_a_quarantined_plugin_refuses_further_calls() -> None:
    harness = Harness([PluginCrashedError("x") for _ in range(CRASH_LIMIT)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(CRASH_LIMIT):
        with pytest.raises(PluginCrashedError):
            await supervisor.call("invoke", {}, timeout=1.0)
    with pytest.raises(PluginUnavailableError):
        await supervisor.call("invoke", {}, timeout=1.0)


async def test_crashes_spread_beyond_the_window_do_not_quarantine() -> None:
    harness = Harness([PluginCrashedError("x") for _ in range(CRASH_LIMIT)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(CRASH_LIMIT):
        with pytest.raises(PluginCrashedError):
            await supervisor.call("invoke", {}, timeout=1.0)
        harness.now += 400.0  # push each crash outside the 300s window
    assert supervisor.quarantined is False


async def test_a_timeout_kills_and_restarts() -> None:
    harness = Harness([PluginTimeoutError("slow"), "pong"])
    supervisor = harness.supervisor()
    await supervisor.start()
    with pytest.raises(PluginTimeoutError):
        await supervisor.call("invoke", {}, timeout=1.0)
    assert harness.processes[0].killed == 1
    assert await supervisor.call("invoke", {}, timeout=1.0) == "pong"


async def test_three_protocol_violations_quarantine_the_plugin() -> None:
    harness = Harness([ProtocolViolationError("garbage") for _ in range(VIOLATION_LIMIT)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(VIOLATION_LIMIT):
        with pytest.raises(ProtocolViolationError):
            await supervisor.call("invoke", {}, timeout=1.0)
    assert supervisor.quarantined is True
    assert "protocol" in harness.quarantines[0].lower()


async def test_violations_accumulate_across_restarts() -> None:
    # Each violation kills the process, so a per-process counter could never
    # exceed one and the limit would be unreachable. Violations are counted
    # cumulatively: two, then an unrelated crash, then a third still quarantines.
    harness = Harness(
        [
            ProtocolViolationError("a"),
            ProtocolViolationError("b"),
            PluginCrashedError("c"),
            ProtocolViolationError("d"),
        ]
    )
    supervisor = harness.supervisor()
    await supervisor.start()
    for expected in (
        ProtocolViolationError,
        ProtocolViolationError,
        PluginCrashedError,
        ProtocolViolationError,
    ):
        with pytest.raises(expected):
            await supervisor.call("invoke", {}, timeout=1.0)
    assert supervisor.quarantined is True
    assert "protocol" in harness.quarantines[0].lower()


async def test_an_old_crash_is_forgiven_but_an_old_violation_is_not() -> None:
    # The asymmetry, stated as a test: crashes age out of a window because they
    # can be environmental; malformed frames never age out.
    harness = Harness([ProtocolViolationError("x") for _ in range(VIOLATION_LIMIT)])
    supervisor = harness.supervisor()
    await supervisor.start()
    for _ in range(VIOLATION_LIMIT):
        with pytest.raises(ProtocolViolationError):
            await supervisor.call("invoke", {}, timeout=1.0)
        harness.now += 10_000.0  # far outside any crash window
    assert supervisor.quarantined is True


async def test_calling_before_start_is_reported_not_crashed() -> None:
    supervisor = Harness([]).supervisor()
    with pytest.raises(PluginUnavailableError):
        await supervisor.call("invoke", {}, timeout=1.0)


async def test_stop_shuts_the_process_down() -> None:
    harness = Harness(["pong"])
    supervisor = harness.supervisor()
    await supervisor.start()
    await supervisor.stop()
    assert harness.processes[0].stopped == 1
