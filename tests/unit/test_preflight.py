"""Unit tests for pre-flight checks (DCL-007).

Each check is exercised independently with the relevant external thing
(Ollama, Docker, port) mocked, plus one happy-path test of ``run_all``.
"""

from __future__ import annotations

import socket
import subprocess
from typing import Any

import httpx
import pytest

from declaw.brain.ollama_client import OllamaClient
from declaw.config import Settings
from declaw.preflight import (
    check_docker_available,
    check_model_pulled,
    check_ollama_reachable,
    check_port_free,
    run_all,
)


def _free_port() -> int:
    """Ask the kernel for an unused TCP port, then release it. Tiny race
    window between releasing and the test calling check_port_free again,
    but acceptable for unit tests on a developer machine."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": _free_port(),
        "model": "mistral:7b",
        "ollama_base_url": "http://test-ollama",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def _mock_ollama(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    # Force every OllamaClient instance built during the test to use the
    # given MockTransport instead of a real HTTP connection.
    original_init = OllamaClient.__init__

    def patched_init(self: OllamaClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(OllamaClient, "__init__", patched_init)


# --- check_ollama_reachable -------------------------------------------------


async def test_ollama_reachable_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.3.14"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(404)

    _mock_ollama(monkeypatch, handler)

    result = await check_ollama_reachable(_settings())

    assert result.passed
    assert "0.3.14" in result.message
    assert result.remedy is None


async def test_ollama_reachable_fails_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    _mock_ollama(monkeypatch, handler)

    result = await check_ollama_reachable(_settings())

    assert not result.passed
    assert "not reachable" in result.message
    assert result.remedy is not None
    assert "ollama serve" in result.remedy


# --- check_model_pulled -----------------------------------------------------


async def test_model_pulled_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.3.14"})
        return httpx.Response(200, json={"models": [{"name": "mistral:7b"}]})

    _mock_ollama(monkeypatch, handler)

    result = await check_model_pulled(_settings())

    assert result.passed
    assert "mistral:7b" in result.message


async def test_model_pulled_fails_with_pull_remedy(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.3.14"})
        return httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})

    _mock_ollama(monkeypatch, handler)

    result = await check_model_pulled(_settings())

    assert not result.passed
    assert result.remedy is not None
    assert "ollama pull mistral:7b" in result.remedy


async def test_model_check_short_circuits_when_ollama_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    _mock_ollama(monkeypatch, handler)

    result = await check_model_pulled(_settings())

    assert not result.passed
    assert "Ollama unreachable" in result.message


# --- check_docker_available -------------------------------------------------


def test_docker_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("declaw.preflight.shutil.which", lambda _: "/usr/bin/docker")

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="24.0.7\n", stderr="")

    monkeypatch.setattr("declaw.preflight.subprocess.run", fake_run)

    result = check_docker_available()

    assert result.passed
    assert "24.0.7" in result.message


def test_docker_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("declaw.preflight.shutil.which", lambda _: None)

    result = check_docker_available()

    assert not result.passed
    assert "not found" in result.message
    assert result.remedy is not None


def test_docker_daemon_not_responding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("declaw.preflight.shutil.which", lambda _: "/usr/bin/docker")

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Cannot connect to daemon"
        )

    monkeypatch.setattr("declaw.preflight.subprocess.run", fake_run)

    result = check_docker_available()

    assert not result.passed
    assert "daemon" in result.message.lower()


# --- check_port_free --------------------------------------------------------


def test_port_free_passes_on_unused_port() -> None:
    result = check_port_free(_settings())  # _free_port() picks an unused one
    assert result.passed


def test_port_free_fails_when_already_bound() -> None:
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    bound_port = blocker.getsockname()[1]
    try:
        result = check_port_free(_settings(port=bound_port))
    finally:
        blocker.close()

    assert not result.passed
    assert str(bound_port) in result.message
    assert result.remedy is not None


# --- run_all ---------------------------------------------------------------


async def test_run_all_returns_one_result_per_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.3.14"})
        return httpx.Response(200, json={"models": [{"name": "mistral:7b"}]})

    _mock_ollama(monkeypatch, handler)
    monkeypatch.setattr("declaw.preflight.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        "declaw.preflight.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="24.0.7\n", stderr=""
        ),
    )

    results = await run_all(_settings())

    assert [r.name for r in results] == [
        "ollama.reachable",
        "ollama.model",
        "docker.available",
        "gateway.port",
    ]
    assert all(r.passed for r in results)
