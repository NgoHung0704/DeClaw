"""Application lifecycle tests — the M2 service container (DCL-120, spec section 5).

``declaw.app.Application`` owns what ``main.chat`` used to assemble inline:
engine/sessionmaker, ``DbAuditLogger``, ``QuarantineStore``, ``Sanitizer``,
``PluginHost``, ``DocumentStack``, ``DocumentWatcher`` (gateway mode only),
one process-wide ``EgressMonitor`` and the tool registry factory.

Every service here is a recording fake: the point of these tests is the
*sequence* of lifecycle calls, not the behavior of any single service (each
of those has its own suite). Watchdog observers, plugin subprocesses and
sqlite files have no place in a unit test of ordering.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from declaw.config import Settings

# A shutdown step hook: awaited by Application.shutdown() in a fixed slot.
ShutdownStep = Callable[[], Awaitable[None]]

EXPECTED_SHUTDOWN_ORDER = [
    "sessions.stop",
    "turns.cancel",
    "approvals.deny",
    "watcher.stop",
    "host.stop",
    "monitor.uninstall",
    "engine.dispose",
]


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Settings pointed at a tmp dir, no sanitizer (keeps Ollama out of init)."""
    values: dict[str, Any] = {
        "_env_file": None,
        "data_dir": tmp_path / "data",
        "workspace_dir": tmp_path / "workspace",
        "sanitizer_required": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[call-arg]


class FakeHealth:
    reachable = True
    version = "test"
    error: str | None = None

    def has_model(self, model: str) -> bool:
        return True


class FakeOllamaClient:
    def __init__(self, health: FakeHealth | None = None) -> None:
        self._health = health if health is not None else FakeHealth()

    async def health(self) -> FakeHealth:
        return self._health


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace every service declaw.app constructs with a recording fake.

    Returns the shared event list the fakes append to.
    """
    events: list[str] = []

    class FakeHost:
        def __init__(self, **kwargs: Any) -> None:
            self.started = False

        async def start(self) -> None:
            self.started = True
            events.append("host.start")

        async def stop(self) -> None:
            events.append("host.stop")

        def failures(self) -> list[str]:
            return []

        def model_tools(self) -> list[Any]:
            return []

        def loaded(self) -> list[Any]:
            return []

    class FakeWatcher:
        def __init__(self, folder: Path, *args: Any, **kwargs: Any) -> None:
            self.folder = folder

        def start(self) -> None:
            events.append("watcher.start")

        def stop(self) -> None:
            events.append("watcher.stop")

    class FakeMonitor:
        def __init__(self, audit: Any, **kwargs: Any) -> None:
            self.audit = audit

        def install(self) -> None:
            events.append("monitor.install")

        def uninstall(self) -> None:
            events.append("monitor.uninstall")

    class FakeEngine:
        async def dispose(self) -> None:
            events.append("engine.dispose")

    async def fake_ensure_schema(engine: Any) -> None:
        events.append("schema.ensure")

    monkeypatch.setattr("declaw.app.get_engine", lambda: FakeEngine())
    monkeypatch.setattr("declaw.app.get_sessionmaker", lambda: object())
    monkeypatch.setattr("declaw.app.DbAuditLogger", lambda sessionmaker: object())
    monkeypatch.setattr("declaw.app.ensure_schema", fake_ensure_schema)
    monkeypatch.setattr("declaw.app.PluginHost", FakeHost)
    monkeypatch.setattr("declaw.app.DocumentWatcher", FakeWatcher)
    monkeypatch.setattr("declaw.app.EgressMonitor", FakeMonitor)
    monkeypatch.setattr("declaw.app.load_state", lambda data_dir: object())
    monkeypatch.setattr("declaw.app.load_grants", lambda data_dir: object())
    monkeypatch.setattr(
        "declaw.app.default_registry",
        lambda: type(  # minimal registry: accepts registrations, yields nothing
            "FakeRegistry",
            (),
            {
                "register_instance": lambda self, tool: None,
                "langchain_tools": lambda self, *a, **k: [],
            },
        )(),
    )
    return events


def step(name: str, events: list[str]) -> ShutdownStep:
    async def run() -> None:
        events.append(name)

    return run


async def test_shutdown_runs_each_step_in_the_spec_order(
    fakes: list[str], tmp_path: Path
) -> None:
    """Spec section 5: sessions -> turns -> approvals -> watcher -> host -> monitor -> engine."""  # noqa: E501
    from declaw.app import Application

    app = Application(
        make_settings(tmp_path),
        mode="gateway",
        stop_accepting_sessions=step("sessions.stop", fakes),
        cancel_in_flight_turns=step("turns.cancel", fakes),
        deny_pending_approvals=step("approvals.deny", fakes),
    )
    await app.start()
    await app.shutdown()

    assert fakes == [
        "monitor.install",
        "schema.ensure",
        "host.start",
        "watcher.start",
        *EXPECTED_SHUTDOWN_ORDER,
    ]


async def test_double_shutdown_is_safe(fakes: list[str], tmp_path: Path) -> None:
    """A second shutdown() is a no-op: idempotent, no duplicated service stops."""
    from declaw.app import Application

    app = Application(make_settings(tmp_path), mode="gateway")
    await app.start()
    await app.shutdown()
    await app.shutdown()

    assert fakes.count("host.stop") == 1
    assert fakes.count("monitor.uninstall") == 1
    assert fakes.count("engine.dispose") == 1
    assert fakes.count("watcher.stop") == 1


async def test_cli_mode_starts_no_watcher(fakes: list[str], tmp_path: Path) -> None:
    """The DocumentWatcher is a gateway-mode service only; CLI is unchanged."""
    from declaw.app import Application

    app = Application(make_settings(tmp_path), mode="cli")
    await app.start()
    assert app.watcher is None
    assert "watcher.start" not in fakes

    await app.shutdown()
    assert "watcher.stop" not in fakes


async def test_start_succeeds_when_ollama_is_missing(
    fakes: list[str], tmp_path: Path
) -> None:
    """Spec section 5: gateway start does not depend on Ollama health."""
    from declaw.app import Application

    settings = make_settings(tmp_path, ollama_base_url="http://127.0.0.1:1")
    app = Application(settings, mode="gateway")
    # No hard exit, no health check: start() must simply succeed.
    await app.start()
    assert app.host is not None
    await app.shutdown()


def test_chat_builds_exactly_one_application(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``declaw chat`` assembles the same Application the gateway will use.

    Sync on purpose: ``main.chat`` calls ``asyncio.run`` itself, which refuses
    to start a loop while pytest-asyncio's loop is already running.
    """
    import declaw.app as app_module
    import declaw.brain.repl as repl_module
    import declaw.main as main_module

    calls: list[dict[str, Any]] = []
    chat_ran: list[bool] = []

    class FakeApplication:
        def __init__(self, settings: Settings, **kwargs: Any) -> None:
            self.settings = settings
            self.mode = kwargs.get("mode")
            self.quarantine_notice = kwargs.get("quarantine_notice")
            self.confirmation_provider = kwargs.get("confirmation_provider")
            self.watcher = None
            self.host = None
            calls.append({"mode": self.mode, "settings": settings, "kwargs": kwargs})

        async def start(self) -> None:
            pass

        async def shutdown(self) -> None:
            pass

        def plugin_failures(self) -> list[str]:
            return []

        def loaded_plugin_names(self) -> list[str]:
            return []

        def langchain_tools(self) -> list[Any]:
            return []

    async def fake_run_chat(*args: Any, **kwargs: Any) -> None:
        chat_ran.append(True)

    settings = make_settings(tmp_path)
    monkeypatch.setattr(app_module, "Application", FakeApplication)
    monkeypatch.setattr(repl_module, "build_brain", lambda tools=None: object())
    monkeypatch.setattr(repl_module, "run_chat", fake_run_chat)
    monkeypatch.setattr(main_module, "OllamaClient", FakeOllamaClient)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    main_module.chat(debug=False)

    assert len(calls) == 1, "chat must build exactly one Application"
    assert calls[0]["mode"] == "cli"
    assert callable(calls[0]["kwargs"]["quarantine_notice"])
    assert callable(calls[0]["kwargs"]["confirmation_provider"])
    assert chat_ran == [True]


async def test_failed_start_uninstalls_the_egress_monitor(
    fakes: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A startup crash partway must not leak the httpx observer.

    The old inline CLI wiring guaranteed this with ``with monitor:``; the
    Application must guarantee it too: if any start() step raises after the
    monitor is installed, the acquired services are torn down before the
    exception propagates.
    """

    class ExplodingHost:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            fakes.append("host.start")
            raise RuntimeError("plugin host exploded during start")

        async def stop(self) -> None:
            fakes.append("host.stop")

        def failures(self) -> list[str]:
            return []

        def model_tools(self) -> list[Any]:
            return []

        def loaded(self) -> list[Any]:
            return []

    monkeypatch.setattr("declaw.app.PluginHost", ExplodingHost)
    from declaw.app import Application

    app = Application(make_settings(tmp_path), mode="gateway")
    with pytest.raises(RuntimeError, match="plugin host exploded"):
        await app.start()

    # Exception propagated AND the acquired services were torn down first.
    assert fakes == [
        "monitor.install",
        "schema.ensure",
        "host.start",
        "host.stop",
        "monitor.uninstall",
        "engine.dispose",
    ]


async def test_a_failing_shutdown_step_does_not_strand_the_rest(
    fakes: list[str], tmp_path: Path
) -> None:
    """One raising shutdown hook must not strand the remaining teardown."""

    async def exploding_step() -> None:
        fakes.append("sessions.stop")
        raise RuntimeError("session gate exploded")

    from declaw.app import Application

    app = Application(
        make_settings(tmp_path),
        mode="gateway",
        stop_accepting_sessions=exploding_step,
    )
    await app.start()
    # The hook raises, but every later step still runs (and the failure is
    # swallowed: teardown must be unstoppable).
    await app.shutdown()

    assert fakes == [
        "monitor.install",
        "schema.ensure",
        "host.start",
        "watcher.start",
        "sessions.stop",
        "watcher.stop",
        "host.stop",
        "monitor.uninstall",
        "engine.dispose",
    ]
