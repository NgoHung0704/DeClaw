"""A real subprocess, a real pipe. Deterministic: no Ollama, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from declaw.plugin_host.errors import PluginCapabilityError, PluginTimeoutError
from declaw.plugin_host.process import PluginProcess

ECHO_DIR = Path(__file__).parent.parent / "fixtures" / "plugins" / "echo-plugin"


async def _started(directory: Path = ECHO_DIR) -> PluginProcess:
    process = PluginProcess(name=directory.name, plugin_dir=directory, entrypoint="main.py")
    await process.start()
    return process


async def test_describe_round_trips_through_a_real_pipe() -> None:
    process = await _started()
    try:
        described = await process.request("describe", timeout=30)
        assert described["name"] == "echo-plugin"
        assert {c["name"] for c in described["capabilities"]} == {"echo", "count", "noisy"}
    finally:
        await process.shutdown()


async def test_invoke_returns_the_capability_result() -> None:
    process = await _started()
    try:
        result = await process.request(
            "invoke", {"capability": "echo", "args": {"message": "salut", "times": 2}}, timeout=30
        )
        assert result == "salut salut"
    finally:
        await process.shutdown()


async def test_a_stray_print_does_not_corrupt_the_stream() -> None:
    # 'noisy' prints to stdout before answering. If stdout hygiene were broken
    # the next frame read would be the print output, not JSON.
    process = await _started()
    try:
        first = await process.request(
            "invoke", {"capability": "noisy", "args": {"message": "ok"}}, timeout=30
        )
        assert first == "ok"
        second = await process.request("describe", timeout=30)
        assert second["name"] == "echo-plugin"
    finally:
        await process.shutdown()


async def test_an_error_frame_becomes_a_typed_exception() -> None:
    process = await _started()
    try:
        with pytest.raises(PluginCapabilityError) as excinfo:
            await process.request("invoke", {"capability": "nope", "args": {}}, timeout=30)
        assert excinfo.value.code == "unknown_capability"
    finally:
        await process.shutdown()


async def test_invalid_args_are_reported_as_a_typed_exception() -> None:
    process = await _started()
    try:
        with pytest.raises(PluginCapabilityError) as excinfo:
            await process.request(
                "invoke", {"capability": "echo", "args": {"times": 2}}, timeout=30
            )
        assert excinfo.value.code == "invalid_args"
    finally:
        await process.shutdown()


async def test_timeout_raises_rather_than_hanging() -> None:
    process = await _started()
    try:
        # 'describe' answers instantly; a zero timeout is the deterministic way
        # to exercise the timeout path without a sleeping fixture. The process
        # must be killed afterwards, never reused: its unread answer is still
        # in the pipe and would be mistaken for the next request's reply.
        with pytest.raises(PluginTimeoutError):
            await process.request("describe", timeout=0.0)
    finally:
        await process.kill()


async def test_shutdown_stops_the_process() -> None:
    process = await _started()
    await process.shutdown()
    assert process.running is False
