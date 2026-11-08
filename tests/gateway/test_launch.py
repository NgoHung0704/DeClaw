"""Launch contract and `declaw start` tests (DCL-120, spec section 1).

The launch contract is stricter than the settings validator: only exactly
``127.0.0.1`` may launch the gateway, checked independently at launch time
(defense in depth). ``localhost`` and ``::1`` stay valid Settings values
but are refused by the launcher in v0.1.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import declaw.main as main_module
from declaw.config import Settings
from declaw.gateway.app import (
    GatewayLaunchError,
    assert_launch_contract,
    create_app,
    run_gateway,
)
from declaw.log import configure
from declaw.main import cli

runner = CliRunner()


def _fresh(**env: str) -> Settings:
    # ``_env_file=None`` skips ``.env`` lookup so tests do not depend on the
    # developer's CWD (same pattern as tests/unit/test_config.py).
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def _forged_host_settings(host: str) -> Settings:
    """Build a Settings whose host skipped the pydantic loopback validator.

    Parsing already refuses non-loopback hosts; the launch contract is
    defense in depth and must itself reject values that can only arrive by
    bypassing that validator, e.g. via ``model_copy``.
    """
    return _fresh().model_copy(update={"host": host})


@pytest.fixture
def stubbed_servers(monkeypatch: pytest.MonkeyPatch) -> list[uvicorn.Config]:
    """Replace ``uvicorn.Server`` with a recorder so tests never bind or block."""
    captured: list[uvicorn.Config] = []

    class StubServer:
        def __init__(self, config: uvicorn.Config) -> None:
            captured.append(config)

        def run(self) -> None:
            pass  # the real Server.run() blocks until the gateway stops

    monkeypatch.setattr(uvicorn, "Server", StubServer)
    return captured


# --- Launch contract: 127.0.0.1 only (spec section 1) ------------------------


def test_start_refuses_0000() -> None:
    with pytest.raises(GatewayLaunchError):
        assert_launch_contract(_forged_host_settings("0.0.0.0"))


def test_start_refuses_lan_ip() -> None:
    with pytest.raises(GatewayLaunchError):
        assert_launch_contract(_forged_host_settings("192.168.1.10"))


def test_start_refuses_localhost_and_ipv6() -> None:
    # Valid Settings values, but not launchable gateway configs in v0.1.
    for host in ("localhost", "::1"):
        with pytest.raises(GatewayLaunchError):
            assert_launch_contract(_forged_host_settings(host))


def test_launch_accepts_127001() -> None:
    assert assert_launch_contract(_fresh(host="127.0.0.1")) is None


# --- App factory ------------------------------------------------------------


def test_create_app_returns_fastapi() -> None:
    assert isinstance(create_app(_fresh()), FastAPI)


def test_create_app_serves_health_root() -> None:
    # Host must equal the bound authority once the DCL-122 policy is
    # installed (TestClient defaults to "testserver", which is forbidden).
    response = TestClient(create_app(_fresh())).get(
        "/", headers={"Host": "127.0.0.1:7842"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- Hardened uvicorn wiring (spec section 1) --------------------------------


def test_run_gateway_uses_hardened_uvicorn_config(
    monkeypatch: pytest.MonkeyPatch, stubbed_servers: list[uvicorn.Config]
) -> None:
    monkeypatch.setenv("DECLAW_HOST", "127.0.0.1")
    monkeypatch.setenv("DECLAW_PORT", "8123")  # port is configurable; host is not

    run_gateway(Settings())

    assert len(stubbed_servers) == 1
    config = stubbed_servers[0]
    assert config.host == "127.0.0.1"
    assert config.port == 8123
    # No proxy, ever: proxy headers stay off (forwarded_allow_ips is never
    # set, so uvicorn's env-derived default stays inert without the
    # ProxyHeadersMiddleware).
    assert config.proxy_headers is False
    assert config.reload is False
    # Access lines keep flowing (filtered by the loguru sink level), but
    # uvicorn must not install its own plain STDERR handlers.
    assert config.access_log is True
    assert config.log_config is None


def test_access_log_lines_land_in_loguru_at_debug(
    stubbed_servers: list[uvicorn.Config],
) -> None:
    buffer = io.StringIO()
    configure(level="TRACE", stream=buffer, force=True)

    run_gateway(_fresh())
    # Access lines can carry query strings; they must not reach the console
    # directly — they belong in the structured log at DEBUG.
    logging.getLogger("uvicorn.access").info('%s - "GET /?q=1 HTTP/1.1" 200', "127.0.0.1:44444")

    records = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    assert any(r["level"] == "DEBUG" and "GET /?q=1" in r["message"] for r in records)


# --- CLI wiring --------------------------------------------------------------


def test_start_aborts_when_host_is_not_launchable(
    monkeypatch: pytest.MonkeyPatch, stubbed_servers: list[uvicorn.Config]
) -> None:
    monkeypatch.setattr(main_module, "get_settings", lambda: _forged_host_settings("0.0.0.0"))

    result = runner.invoke(cli, ["start"])

    assert result.exit_code == 1
    assert stubbed_servers == []  # aborted before any server was handed a config
    assert "127.0.0.1" in result.stdout


def test_start_starts_hardened_gateway(
    monkeypatch: pytest.MonkeyPatch, stubbed_servers: list[uvicorn.Config]
) -> None:
    monkeypatch.setenv("DECLAW_HOST", "127.0.0.1")
    monkeypatch.setenv("DECLAW_PORT", "8123")

    result = runner.invoke(cli, ["start"])

    assert result.exit_code == 0
    assert len(stubbed_servers) == 1
    assert stubbed_servers[0].host == "127.0.0.1"
    assert stubbed_servers[0].port == 8123
