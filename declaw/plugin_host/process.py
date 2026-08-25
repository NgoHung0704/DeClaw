"""One plugin subprocess: spawn it, talk to it, stop it.

Three details here are load-bearing and easy to get wrong:

* the environment is BUILT, not filtered — a filter forgets a variable, a
  build cannot;
* stderr is drained by a background task for the whole process lifetime,
  because an undrained pipe fills its OS buffer and blocks the plugin
  mid-write, which is indistinguishable from a hang;
* ``limit=MAX_FRAME_BYTES`` on the stream reader means an oversized line
  raises instead of buffering without bound.

One request is in flight at a time, guarded by a lock. After a timeout the
process MUST be killed rather than reused: its unread answer is still sitting
in the pipe and would be mistaken for the next request's reply.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from declaw.log import logger
from declaw.plugin_host.errors import (
    FrameTooLargeError,
    PluginCapabilityError,
    PluginCrashedError,
    PluginHostError,
    PluginTimeoutError,
    ProtocolViolationError,
)
from declaw.plugin_host.ipc import decode_response, encode_frame
from declaw_plugin_sdk.protocol import (
    MAX_FRAME_BYTES,
    Method,
    RequestFrame,
    ResponseFrame,
)

BOOTSTRAP_MODULE = "declaw_plugin_sdk.bootstrap"

# Variables a Python subprocess genuinely needs. Everything else is withheld.
_PASSTHROUGH = ("SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "HOME")


def build_plugin_env(plugin_name: str) -> dict[str, str]:
    """Build the plugin's environment from scratch (nothing is inherited)."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "DECLAW_PLUGIN_NAME": plugin_name,
    }
    for name in _PASSTHROUGH:
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


class PluginProcess:
    """A live plugin subprocess with one request in flight at a time."""

    def __init__(
        self,
        *,
        name: str,
        plugin_dir: Path,
        entrypoint: str,
        python: str | None = None,
    ) -> None:
        self._name = name
        self._plugin_dir = plugin_dir
        self._entrypoint = entrypoint
        self._python = python or sys.executable
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            self._python,
            "-m",
            BOOTSTRAP_MODULE,
            str(self._plugin_dir),
            self._entrypoint,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._plugin_dir),
            env=build_plugin_env(self._name),
            limit=MAX_FRAME_BYTES,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            logger.bind(plugin=self._name).debug(line.decode("utf-8", "replace").rstrip())

    async def request(
        self, method: Method, params: dict[str, Any] | None = None, *, timeout: float
    ) -> Any:
        """Send one request and return its result, or raise a typed error."""
        async with self._lock:
            proc = self._proc
            if proc is None or proc.stdin is None or proc.returncode is not None:
                raise PluginCrashedError(f"Plugin {self._name!r} is not running.")
            frame = RequestFrame(id=str(uuid.uuid4()), method=method, params=params or {})
            try:
                proc.stdin.write(encode_frame(frame))
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise PluginCrashedError(f"Plugin {self._name!r} closed its input.") from exc
            try:
                response = await asyncio.wait_for(self._read_matching(frame.id), timeout)
            except TimeoutError as exc:
                raise PluginTimeoutError(
                    f"Plugin {self._name!r} did not answer {method!r} within {timeout}s."
                ) from exc
            if not response.ok:
                error = response.error
                raise PluginCapabilityError(
                    error.code if error else "internal",
                    error.message if error else "plugin reported failure with no detail",
                )
            return response.result

    async def _read_matching(self, request_id: str) -> ResponseFrame:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise PluginCrashedError(f"Plugin {self._name!r} is not running.")
        try:
            line = await proc.stdout.readline()
        except ValueError as exc:
            # StreamReader raises ValueError when a line exceeds its limit.
            raise FrameTooLargeError(
                f"Plugin {self._name!r} sent a frame over {MAX_FRAME_BYTES} bytes."
            ) from exc
        if not line:
            raise PluginCrashedError(f"Plugin {self._name!r} exited mid-request.")
        response = decode_response(line)
        if response.id != request_id:
            raise ProtocolViolationError(
                f"Plugin {self._name!r} sent a frame for id {response.id!r}, "
                f"expected {request_id!r}."
            )
        return response

    async def shutdown(self) -> None:
        """Graceful, then firm, then final: frame -> 5s -> terminate -> 2s -> kill."""
        proc = self._proc
        if proc is None:
            return
        if proc.returncode is None and proc.stdin is not None:
            try:
                proc.stdin.write(
                    encode_frame(RequestFrame(id=str(uuid.uuid4()), method="shutdown"))
                )
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, PluginHostError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), 5.0)
            except TimeoutError:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 2.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        await self._cleanup()

    async def kill(self) -> None:
        """Stop immediately, for the timeout and violation paths."""
        proc = self._proc
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None
