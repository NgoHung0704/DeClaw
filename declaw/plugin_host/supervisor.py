"""Keep one plugin alive, and know when to stop trying.

Two independent counters, because they mean different things. A *crash* is the
plugin dying; three inside five minutes means it cannot run here, so it is
quarantined. A *protocol violation* is the plugin lying on the wire; three of them,
counted cumulatively, mean it is not speaking our language, so it is
quarantined too.

Violations are cumulative and crashes are windowed, and that asymmetry is
deliberate. A crash can be environmental and transient, so old ones are
forgiven. Malformed frames are not transient — the plugin either speaks the
protocol or it does not — and since the first violation already kills the
process, a per-process counter could never exceed one. Neither counter
persists across a restart of DeClaw: a plugin gets a fresh chance, and
re-quarantine takes under a minute if nothing changed.

``clock`` and ``sleep`` are injected so the tests exercise the whole policy
without spending real seconds on it.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from declaw.log import logger
from declaw.plugin_host.errors import (
    PluginCrashedError,
    PluginTimeoutError,
    PluginUnavailableError,
    ProtocolViolationError,
)
from declaw_plugin_sdk.protocol import Method

CRASH_LIMIT = 3
CRASH_WINDOW_S = 300.0
VIOLATION_LIMIT = 3
BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0)


class SupervisedProcess(Protocol):
    """The slice of :class:`PluginProcess` the supervisor depends on."""

    @property
    def running(self) -> bool: ...

    async def start(self) -> None: ...

    async def request(
        self, method: Method, params: dict[str, Any] | None = None, *, timeout: float
    ) -> Any: ...

    async def shutdown(self) -> None: ...

    async def kill(self) -> None: ...


ProcessFactory = Callable[[], SupervisedProcess]
QuarantineCallback = Callable[[str], None]


class PluginSupervisor:
    """One plugin's process, restarted on failure until it earns quarantine."""

    def __init__(
        self,
        *,
        name: str,
        factory: ProcessFactory,
        on_quarantine: QuarantineCallback,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._name = name
        self._factory = factory
        self._on_quarantine = on_quarantine
        self._clock = clock
        self._sleep = sleep
        self._process: SupervisedProcess | None = None
        self._crashes: deque[float] = deque()
        self._violations = 0
        self._restarts = 0
        self._quarantined = False

    @property
    def quarantined(self) -> bool:
        return self._quarantined

    @property
    def restarts(self) -> int:
        return self._restarts

    async def start(self) -> None:
        self._process = self._factory()
        await self._process.start()

    async def call(
        self, method: Method, params: dict[str, Any] | None = None, *, timeout: float
    ) -> Any:
        """Make one request, applying the restart policy to whatever goes wrong."""
        if self._quarantined:
            raise PluginUnavailableError(
                f"Plugin {self._name!r} is quarantined and will not be called."
            )
        process = self._process
        if process is None:
            raise PluginUnavailableError(f"Plugin {self._name!r} was never started.")
        try:
            return await process.request(method, params, timeout=timeout)
        except ProtocolViolationError:
            await self._on_violation(process)
            raise
        except PluginTimeoutError:
            # The unread answer is still in the pipe, so the process cannot be
            # reused: kill it rather than let the next call read a stale frame.
            await process.kill()
            await self._restart()
            raise
        except PluginCrashedError:
            await self._on_crash()
            raise

    async def _on_violation(self, process: SupervisedProcess) -> None:
        self._violations += 1
        await process.kill()
        if self._violations >= VIOLATION_LIMIT:
            self._quarantine(f"{self._violations} protocol violations")
            return
        await self._restart()

    async def _on_crash(self) -> None:
        now = self._clock()
        self._crashes.append(now)
        while self._crashes and now - self._crashes[0] > CRASH_WINDOW_S:
            self._crashes.popleft()
        if len(self._crashes) >= CRASH_LIMIT:
            self._quarantine(f"{len(self._crashes)} crashes within {int(CRASH_WINDOW_S)} seconds")
            return
        await self._restart()

    async def _restart(self) -> None:
        delay = BACKOFF_SECONDS[min(self._restarts, len(BACKOFF_SECONDS) - 1)]
        logger.warning(f"Restarting plugin {self._name!r} in {delay}s.")
        await self._sleep(delay)
        self._restarts += 1
        self._process = self._factory()
        await self._process.start()

    def _quarantine(self, reason: str) -> None:
        self._quarantined = True
        self._process = None
        logger.error(f"Quarantining plugin {self._name!r}: {reason}.")
        self._on_quarantine(reason)

    async def stop(self) -> None:
        if self._process is not None:
            await self._process.shutdown()
            self._process = None
