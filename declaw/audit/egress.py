"""Network egress monitor (DCL-064).

Principle #7: never make a network call without logging it. This monitor
patches ``httpx`` (the HTTP stack under every DeClaw network user: the Ollama
client, langchain-ollama, future plugins' SDK calls) so every outbound request
— success or failure — emits a :class:`NetworkCallEvent`. Requests to hosts
outside the local allowlist are **flagged** and raise an operational-log
warning: that flag is the source of truth behind the MVP's "data left the
device: yes/no" line (DCL-062) and the egress panel (Phase 9).

Honest scope: this is in-process *observation*, not OS-level enforcement. It
sees everything the DeClaw core process sends through httpx; it cannot see a
malicious C extension or another process. Blocking/verification at the OS
level is Phase 12 (DCL-216). ``requests`` is not hooked because DeClaw does
not depend on it — extend ``install()`` if that ever changes.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any

import httpx

from declaw.audit.events import NetworkCallEvent
from declaw.audit.logger import AuditLogger
from declaw.log import logger

DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Strong refs to fire-and-forget emit tasks (asyncio holds only weak refs).
_pending_tasks: set[asyncio.Task[None]] = set()


class EgressMonitor:
    """Patch httpx so every outbound request lands in the audit trail."""

    def __init__(
        self,
        audit: AuditLogger,
        *,
        allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
    ) -> None:
        self._audit = audit
        self._allowed_hosts = allowed_hosts
        self._installed = False
        self._orig_async_send: Any = None
        self._orig_sync_send: Any = None

    # -- lifecycle -----------------------------------------------------------

    def install(self) -> None:
        """Start observing. Idempotent."""
        if self._installed:
            return
        self._orig_async_send = httpx.AsyncClient.send
        self._orig_sync_send = httpx.Client.send
        monitor = self
        orig_async_send = self._orig_async_send
        orig_sync_send = self._orig_sync_send

        async def observed_async_send(
            client: httpx.AsyncClient, request: httpx.Request, **kwargs: Any
        ) -> httpx.Response:
            response: httpx.Response | None = None
            error: str | None = None
            try:
                response = await orig_async_send(client, request, **kwargs)
                return response
            except Exception as exc:
                error = str(exc)[:300]
                raise
            finally:
                await monitor._audit.emit(monitor._event(request, response, error))

        def observed_sync_send(
            client: httpx.Client, request: httpx.Request, **kwargs: Any
        ) -> httpx.Response:
            response: httpx.Response | None = None
            error: str | None = None
            try:
                response = orig_sync_send(client, request, **kwargs)
                return response
            except Exception as exc:
                error = str(exc)[:300]
                raise
            finally:
                monitor._emit_from_sync(monitor._event(request, response, error))

        httpx.AsyncClient.send = observed_async_send  # type: ignore[method-assign]
        httpx.Client.send = observed_sync_send  # type: ignore[method-assign, assignment]
        self._installed = True

    def uninstall(self) -> None:
        """Stop observing and restore httpx. Idempotent."""
        if not self._installed:
            return
        httpx.AsyncClient.send = self._orig_async_send  # type: ignore[method-assign]
        httpx.Client.send = self._orig_sync_send  # type: ignore[method-assign]
        self._installed = False

    def __enter__(self) -> EgressMonitor:
        self.install()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.uninstall()

    # -- event construction ----------------------------------------------------

    def _event(
        self,
        request: httpx.Request,
        response: httpx.Response | None,
        error: str | None,
    ) -> NetworkCallEvent:
        host = request.url.host or ""
        flagged = host not in self._allowed_hosts
        if flagged:
            # The "alert" half of the acceptance: loud, structured, immediate.
            logger.bind(
                event="network.egress.flagged",
                host=host,
                url=str(request.url),
                method=request.method,
            ).warning("Outbound network call OUTSIDE the local allowlist")
        return NetworkCallEvent(
            method=request.method,
            url=str(request.url),
            host=host,
            status_code=response.status_code if response is not None else None,
            error=error,
            flagged=flagged,
        )

    def _emit_from_sync(self, event: NetworkCallEvent) -> None:
        """Bridge a sync call site into the async audit logger."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._audit.emit(event))
        else:
            task = loop.create_task(self._audit.emit(event))
            _pending_tasks.add(task)
            task.add_done_callback(_pending_tasks.discard)


def allowed_hosts_from_settings(ollama_base_url: str) -> frozenset[str]:
    """Local allowlist + the configured Ollama host (it may be a LAN box)."""
    host = httpx.URL(ollama_base_url).host
    return DEFAULT_ALLOWED_HOSTS | ({host} if host else frozenset())
