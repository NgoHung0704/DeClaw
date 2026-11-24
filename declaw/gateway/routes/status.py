"""``GET /api/status`` and the latched Ollama health probe (DCL-126, spec §9).

Ruling (controller-delegated): Ollama health must reach the status page
WITHOUT a slow or down daemon absorbing requests or blocking the loop. The
probe below is the "cheap latched status" option from the task brief:

* the first request awaits ONE bounded refresh (default 2 s) — the loop is
  never blocked, and even a black-holed daemon cannot hold the request;
* every request within the TTL (default 15 s) is served from the latch with
  zero network calls;
* a refresh that outruns the budget keeps running in the background and
  lands in the latch on completion — the route serves the previous state
  (or an explicit "unknown" ollama section on the very first call) rather
  than a hang.

An unsafe settings file degrades the reported model to the env layer's
value (it never rebinds anything — this is a read-only aggregate), and the
plugin slice reuses the /api/plugins inventory so the two pages can never
disagree about plugin states.

Task 13 (/ws/events) consumes ``build_status`` for its initial snapshot.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request

from declaw import __version__
from declaw.brain.ollama_client import OllamaClient, OllamaHealth
from declaw.gateway.routes.auth import require_session
from declaw.gateway.routes.errors import application_from
from declaw.settings_service import InvalidSettingsFileError

if TYPE_CHECKING:
    from declaw.app import Application

router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])

HealthCheck = Callable[[], Awaitable[OllamaHealth]]

_REFRESH_TIMEOUT_S = 2.0
_TTL_S = 15.0


def default_health_check(base_url: str) -> HealthCheck:
    """The production check: one ``OllamaClient.health()`` call, never raises."""
    client = OllamaClient(base_url=base_url)
    return client.health


class LatchedOllamaHealth:
    """Latched Ollama health, refreshed on demand inside a TTL window."""

    def __init__(
        self,
        health_check: HealthCheck,
        *,
        refresh_timeout_s: float = _REFRESH_TIMEOUT_S,
        ttl_s: float = _TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._health_check = health_check
        self._refresh_timeout_s = refresh_timeout_s
        self._ttl_s = ttl_s
        self._clock = clock
        self._latched: OllamaHealth | None = None
        self._latched_at: float = 0.0
        self._in_flight: asyncio.Task[OllamaHealth] | None = None

    async def current(self) -> OllamaHealth | None:
        """The freshest known health; serves the latch whenever possible."""
        task = self._in_flight
        if task is not None and not task.done():
            return await self._await_bounded(task)

        if self._latched is not None and (self._clock() - self._latched_at) < self._ttl_s:
            return self._latched

        # No fresh latch, nothing in flight: launch one shared refresh.
        task = asyncio.ensure_future(self._health_check())
        task.add_done_callback(self._absorb)
        self._in_flight = task
        return await self._await_bounded(task)

    async def _await_bounded(self, task: asyncio.Task[OllamaHealth]) -> OllamaHealth | None:
        """Wait for one refresh within the budget; never raise, never block long.

        ``shield`` keeps the underlying refresh alive past the budget, so a
        slow daemon still lands in the latch for the NEXT request.
        """
        try:
            health = await asyncio.wait_for(asyncio.shield(task), self._refresh_timeout_s)
        except Exception:  # noqa: BLE001 - a status read must never 500
            return self._latched
        self._latched = health
        self._latched_at = self._clock()
        return health

    def _absorb(self, task: asyncio.Task[OllamaHealth]) -> None:
        """Late completion of a timed-out refresh: latch it, keep the loop alive."""
        if task.cancelled() or task.exception() is not None:
            return
        self._latched = task.result()
        self._latched_at = self._clock()


def _status_model(application: Application) -> str:
    try:
        return application.settings_service.effective().model
    except InvalidSettingsFileError:
        return application.settings.model


async def build_status(application: Application, probe: LatchedOllamaHealth) -> dict[str, Any]:
    """The section 9 aggregate: Ollama health + model presence, plugin states,
    DeClaw version, egress-monitor and watcher on/off flags."""
    from declaw.gateway.routes.plugins import plugin_inventory
    from declaw.gateway.routes.settings import effective_language

    health = await probe.current()
    model = _status_model(application)
    if health is None:
        ollama: dict[str, Any] = {
            "reachable": None,
            "version": None,
            "model": model,
            "model_present": None,
            "error": None,
        }
    else:
        ollama = {
            "reachable": health.reachable,
            "version": health.version,
            "model": model,
            "model_present": health.reachable and health.has_model(model),
            "error": health.error,
        }
    plugins = [
        {"name": entry["name"], "version": entry["version"], "state": entry["state"]}
        for entry in plugin_inventory(application, effective_language(application))
    ]
    return {
        "version": __version__,
        "ollama": ollama,
        "plugins": plugins,
        "egress_monitor": application.egress_monitor is not None,
        "watcher": application.watcher is not None,
    }


@router.get("/status")
async def get_status(request: Request) -> dict[str, Any]:
    application = application_from(request)
    probe: LatchedOllamaHealth = request.app.state.ollama_status
    return await build_status(application, probe)
