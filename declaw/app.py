"""The DeClaw application service container (DCL-120, spec section 5).

What ``main.chat`` used to assemble inline inside one ``asyncio.run`` is
extracted here into an :class:`Application` with an explicit lifecycle, so the
gateway (uvicorn) and the CLI build the *same* object and get the *same*
deterministic shutdown.

One event loop: aiosqlite connections and asyncio subprocess transports bind
to the loop that created them. ``start()`` therefore only does work that must
happen on the caller's loop (schema creation, plugin subprocesses, the
watchdog observer), while the constructor wires the sync pieces (engine,
sessionmaker, audit logger, quarantine pipeline, sanitizer). ``start()`` runs
on the uvicorn loop in the gateway; ``main.chat`` keeps its single
``asyncio.run`` and builds this object inside it.

The :class:`EgressMonitor` has exactly one owner — this object — and an
explicit uninstall in :meth:`Application.shutdown`. "One application owner, a
shutdown policy, not one per request."
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from declaw.audit.egress import EgressMonitor, allowed_hosts_from_settings
from declaw.audit.logger import DbAuditLogger
from declaw.audit.sinks import composite_sink, quarantine_db_sink
from declaw.config import Settings, get_settings
from declaw.db.engine import ensure_schema, get_engine, get_sessionmaker
from declaw.documents.watcher import DocumentWatcher
from declaw.log import logger
from declaw.plugin_host.grants_helper import load_grants, load_state
from declaw.plugin_host.host import PluginHost
from declaw.sanitizer.classifier import build_ollama_classifier
from declaw.sanitizer.quarantine import QuarantineStore, log_audit_sink, user_notice_sink
from declaw.sanitizer.sanitizer import Sanitizer
from declaw.settings_service import SettingsService
from declaw.tools.confirmation import ConfirmationProvider
from declaw.tools.registry import ToolRegistry, default_registry

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from declaw.documents.session import DocumentStack
    from declaw.gateway.session import SessionManager

# A step of the deterministic shutdown sequence (spec section 5). The gateway
# injects SessionManager/approval handlers here; the CLI leaves them unset and
# the steps are skipped.
ShutdownStep = Callable[[], Awaitable[None]]

AppMode = Literal["cli", "gateway"]


class Application:
    """Own every process-wide DeClaw service with an explicit lifecycle (spec §5).

    ``mode="cli"`` reproduces today's ``declaw chat`` exactly: no document
    watcher, quarantine notices printed to the console via
    ``quarantine_notice``, confirmations asked through ``confirmation_provider``.
    ``mode="gateway"`` additionally runs the :class:`DocumentWatcher`; sessions,
    turns and approvals arrive with the WS wiring and plug into the shutdown
    sequence through the injected step hooks.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        mode: AppMode = "gateway",
        quarantine_notice: Callable[[str], None] | None = None,
        confirmation_provider: ConfirmationProvider | None = None,
        stop_accepting_sessions: ShutdownStep | None = None,
        cancel_in_flight_turns: ShutdownStep | None = None,
        deny_pending_approvals: ShutdownStep | None = None,
    ) -> None:
        self.settings = settings if settings is not None else get_settings()
        self.mode = mode
        self.confirmation_provider = confirmation_provider

        # The Application is the single owner of engine/logger wiring: the
        # gateway reads ``application.audit`` instead of building its own
        # ``DbAuditLogger(get_sessionmaker())``. The factories stay the
        # process-wide singletons (DCL-005: concurrent cold-start safe).
        self.engine: AsyncEngine = get_engine()
        self.sessionmaker: async_sessionmaker[AsyncSession] = get_sessionmaker()
        self.audit = DbAuditLogger(self.sessionmaker)

        # Principle #4: external content is quarantined before the model sees
        # it. The store reports to the operational log and the audit DB
        # always; the user notice goes to the CLI console here (the gateway
        # gets its sink from the session queue wiring).
        sinks = [log_audit_sink, quarantine_db_sink(self.audit)]
        if quarantine_notice is not None:
            # The model only receives a neutral placeholder and paraphrases it
            # unreliably, so the application itself tells the user (seeded
            # rationale for user_notice_sink in declaw/sanitizer/quarantine.py).
            sinks.append(user_notice_sink(quarantine_notice, self.settings.language))
        self.quarantine = QuarantineStore(audit_sink=composite_sink(*sinks))

        # No sanitizer when the setting is off: tools then run unsanitized by
        # explicit operator decision, exactly as before this refactor.
        self.sanitizer: Sanitizer | None = (
            Sanitizer(
                build_ollama_classifier(language=self.settings.language),
                quarantine=self.quarantine,
            )
            if self.settings.sanitizer_required
            else None
        )

        # Services materialized by start().
        self.host: PluginHost | None = None
        self.registry: ToolRegistry | None = None
        self.stack: DocumentStack | None = None
        self.watcher: DocumentWatcher | None = None
        self.egress_monitor: EgressMonitor | None = None
        # User-owned plugin policy (spec section 11): one PluginStateStore and
        # one GrantStore per Application, owned here so the gateway's REST
        # surface mutates THE objects the PluginHost and its PermissionEnforcer
        # read (a second store reloaded from the file would let the host and
        # the /api/plugins routes disagree about grants). File reads happen
        # once, here; the host receives these instances in start().
        self.plugin_state = load_state(self.settings.data_dir)
        self.plugin_grants = load_grants(self.settings.data_dir)
        # The SettingsService (spec section 12) is owned here: it composes
        # this env layer with data_dir/settings.json into per-session
        # snapshots and owns every write to that file. Constructing it does
        # no I/O; the gateway settings routes read it off the Application.
        self.settings_service = SettingsService(self.settings)

        # Hooks slotted into the fixed shutdown order below. The CLI leaves
        # them unset: it has no sessions, no in-flight turns, no pending
        # approvals to deny.
        self._stop_accepting_sessions = stop_accepting_sessions
        self._cancel_in_flight_turns = cancel_in_flight_turns
        self._deny_pending_approvals = deny_pending_approvals

        self._started = False
        self._stopped = False

    async def start(self) -> None:
        """Materialize the loop-bound services on the caller's event loop.

        Idempotent: a second call returns immediately. Ollama is *not*
        health-checked here (spec section 5): the gateway must start and
        serve the status UI even when Ollama or a model is missing; chat
        turns then fail with a typed error. ``declaw chat`` keeps its own
        hard exit before building the Application.
        """
        if self._started:
            return

        # Failure-safe startup: a crash partway must not leak what start()
        # already acquired (above all the httpx observer patch — the old
        # inline CLI wiring guaranteed its removal with ``with monitor:``).
        # Whatever exists when a step raises is torn down, then the error
        # propagates.
        try:
            # Principle #7: every outbound network call is audited from the
            # first moment any service could make one; the monitor spans the
            # whole application lifetime and is uninstalled in shutdown().
            self.egress_monitor = EgressMonitor(
                self.audit,
                allowed_hosts=allowed_hosts_from_settings(self.settings.ollama_base_url),
            )
            self.egress_monitor.install()

            await ensure_schema(self.engine)

            self.host = PluginHost(
                state=self.plugin_state,
                grants=self.plugin_grants,
                settings=self.settings,
                audit=self.audit,
            )
            await self.host.start()

            registry = default_registry()
            for plugin_tool in self.host.model_tools():
                registry.register_instance(plugin_tool)

            # The document stack only exists when its plugin actually loaded;
            # lazy imports keep chroma/langchain out of `declaw version`.
            from declaw.documents.session import DOC_INTEL_PLUGIN, build_document_stack

            if any(p.manifest.name == DOC_INTEL_PLUGIN for p in self.host.loaded()):
                from declaw.documents.actions import (
                    OrganizeFilesTool,
                    build_document_summarize_tool,
                )
                from declaw.documents.tools import build_document_search_tool

                self.stack = build_document_stack(
                    self.settings, self.host, sanitizer=self.sanitizer
                )
                registry.register_instance(
                    build_document_search_tool(
                        store=self.stack.store,
                        chunk_sanitizer=self.stack.chunk_sanitizer,
                        language=self.settings.language,
                    )
                )
                registry.register_instance(OrganizeFilesTool())
                registry.register_instance(
                    build_document_summarize_tool(
                        store=self.stack.store,
                        chunk_sanitizer=self.stack.chunk_sanitizer,
                        language=self.settings.language,
                    )
                )
            self.registry = registry

            # Gateway-only: the watchdog fires while the CLI is not running
            # (spec section 5 — CLI behavior unchanged).
            if self.mode == "gateway":
                workspace = Path(self.settings.workspace_dir)
                workspace.mkdir(parents=True, exist_ok=True)
                self.watcher = DocumentWatcher(workspace)
                self.watcher.start()
        except BaseException:
            await self._teardown_owned()
            raise

        self._started = True

    async def shutdown(self) -> None:
        """Deterministic teardown, in the spec's fixed order.

        stop accepting sessions -> cancel in-flight turns -> deny all pending
        approvals -> stop watcher -> ``host.stop()`` -> uninstall egress
        monitor -> dispose engine. Each step is skipped when the concern does
        not exist (CLI: no watcher, no session hooks) and the whole call is a
        no-op when the application never started or already stopped.

        Every step is individually guarded: one raising step is logged and
        the teardown continues — a failed shutdown hook must not strand the
        remaining services. Task 10 extends the watcher step: drain its queue
        before stopping the observer, between "deny approvals" and
        "host.stop()".
        """
        if not self._started or self._stopped:
            return
        self._stopped = True

        if self._stop_accepting_sessions is not None:
            await self._guarded("stop accepting sessions", self._stop_accepting_sessions)
        if self._cancel_in_flight_turns is not None:
            await self._guarded("cancel in-flight turns", self._cancel_in_flight_turns)
        if self._deny_pending_approvals is not None:
            await self._guarded("deny pending approvals", self._deny_pending_approvals)
        await self._teardown_owned()

    def wire_gateway_shutdown(self, session_manager: SessionManager) -> None:
        """Give the session shutdown hooks their real handlers (Task 9 wiring).

        The hooks were constructor-injected seams since Task 7 because the
        ``SessionManager`` did not exist yet; the gateway (``create_app``)
        owns it and calls this once, so every application — however it was
        built — shuts down in the spec's fixed order: stop accepting sessions
        (manager), cancel in-flight turns (manager), deny pending approvals
        (manager's sessions each carry the shared broker). Only unset hooks
        are filled: an explicitly injected step always wins, so the Task 7
        lifecycle tests stay the owner of theirs.
        """
        if self._stop_accepting_sessions is None:
            self._stop_accepting_sessions = session_manager.stop_accepting_sessions
        if self._cancel_in_flight_turns is None:
            self._cancel_in_flight_turns = session_manager.cancel_in_flight_turns
        if self._deny_pending_approvals is None:
            self._deny_pending_approvals = session_manager.deny_pending_approvals

    async def _teardown_owned(self) -> None:
        """Tear down the owned services in the spec's order.

        Used by both shutdown() and the failed-start path: each step runs
        only for a service that exists, and a raising step never stops the
        rest.
        """
        if self.watcher is not None:
            self._guarded_sync("stop watcher", self.watcher.stop)
        if self.host is not None:
            await self._guarded("host.stop()", self.host.stop)
        if self.egress_monitor is not None:
            self._guarded_sync("uninstall egress monitor", self.egress_monitor.uninstall)
        await self._guarded("dispose engine", self.engine.dispose)

    async def _guarded(self, step: str, action: ShutdownStep) -> None:
        """Run one async teardown step; log a failure, never strand the rest."""
        try:
            await action()
        except Exception:
            logger.bind(event="application.shutdown_step_failed", step=step).exception(
                "Shutdown step failed; continuing with the remaining steps"
            )

    def _guarded_sync(self, step: str, action: Callable[[], None]) -> None:
        """Sync twin of :meth:`_guarded`."""
        try:
            action()
        except Exception:
            logger.bind(event="application.shutdown_step_failed", step=step).exception(
                "Shutdown step failed; continuing with the remaining steps"
            )

    def plugin_failures(self) -> list[str]:
        """Human-readable plugin load failures (may be empty)."""
        return self.host.failures() if self.host is not None else []

    def loaded_plugin_names(self) -> list[str]:
        """Names of the plugins that actually loaded."""
        return (
            [plugin.manifest.name for plugin in self.host.loaded()]
            if self.host is not None
            else []
        )

    def langchain_tools(self) -> list[StructuredTool]:
        """Build the brain-ready tool list from the owned registry."""
        if self.registry is None:
            raise RuntimeError("Application.start() must run before langchain_tools().")
        if self.confirmation_provider is None:
            raise RuntimeError(
                "Application needs a confirmation provider before langchain_tools()."
            )
        return self.registry.langchain_tools(
            self.settings.language,
            self.confirmation_provider,
            sanitizer=self.sanitizer,
            audit=self.audit,
        )
