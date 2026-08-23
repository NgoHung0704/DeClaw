"""Crash and hang against real subprocesses, with backoff collapsed to zero."""

from __future__ import annotations

from pathlib import Path

import pytest

from declaw.plugin_host.errors import PluginCrashedError, PluginTimeoutError
from declaw.plugin_host.process import PluginProcess
from declaw.plugin_host.supervisor import PluginSupervisor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"


def _supervisor(directory: Path, quarantines: list[str]) -> PluginSupervisor:
    async def no_sleep(_seconds: float) -> None:
        return None

    return PluginSupervisor(
        name=directory.name,
        factory=lambda: PluginProcess(
            name=directory.name, plugin_dir=directory, entrypoint="main.py"
        ),
        on_quarantine=quarantines.append,
        sleep=no_sleep,
    )


async def test_a_real_crash_is_reported_and_the_plugin_comes_back() -> None:
    quarantines: list[str] = []
    supervisor = _supervisor(FIXTURES / "crash-plugin", quarantines)
    await supervisor.start()
    try:
        with pytest.raises(PluginCrashedError):
            await supervisor.call("invoke", {"capability": "die", "args": {}}, timeout=30)
        assert supervisor.restarts == 1
        assert quarantines == []
    finally:
        await supervisor.stop()


async def test_repeated_real_crashes_quarantine_the_plugin() -> None:
    quarantines: list[str] = []
    supervisor = _supervisor(FIXTURES / "crash-plugin", quarantines)
    await supervisor.start()
    try:
        for _ in range(3):
            with pytest.raises(PluginCrashedError):
                await supervisor.call("invoke", {"capability": "die", "args": {}}, timeout=30)
        assert supervisor.quarantined is True
        assert quarantines
    finally:
        await supervisor.stop()


async def test_a_real_hang_times_out_and_the_process_is_replaced() -> None:
    quarantines: list[str] = []
    supervisor = _supervisor(FIXTURES / "hang-plugin", quarantines)
    await supervisor.start()
    try:
        with pytest.raises(PluginTimeoutError):
            await supervisor.call("invoke", {"capability": "wait", "args": {}}, timeout=1.0)
        assert supervisor.restarts == 1
    finally:
        await supervisor.stop()
