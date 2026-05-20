"""Pre-flight environment checks for DeClaw.

The checks verify that everything DeClaw needs at runtime is in place:

  - Ollama daemon is reachable
  - The configured chat model is pulled
  - Docker is available (sandbox is mandatory — Principle #3)
  - The gateway port is free to bind on the loopback address

Each check returns a :class:`CheckResult` carrying a remedy string so the
caller can render an actionable error rather than a stack trace. The
module is import-safe (no side effects at import time) so it can be used
from both the standalone ``scripts/preflight.py`` and the FastAPI startup
hook added in a later ticket.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass

from declaw.brain.ollama_client import OllamaClient, OllamaHealth
from declaw.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of one pre-flight check."""

    name: str
    passed: bool
    message: str
    remedy: str | None = None


def _check_ollama_reachable(settings: Settings, health: OllamaHealth) -> CheckResult:
    if health.reachable:
        return CheckResult(
            name="ollama.reachable",
            passed=True,
            message=f"Ollama v{health.version} reachable at {settings.ollama_base_url}",
        )
    return CheckResult(
        name="ollama.reachable",
        passed=False,
        message=f"Ollama not reachable at {settings.ollama_base_url}: {health.error}",
        remedy="Install Ollama from https://ollama.com and run `ollama serve`.",
    )


def _check_model_pulled(settings: Settings, health: OllamaHealth) -> CheckResult:
    if not health.reachable:
        return CheckResult(
            name="ollama.model",
            passed=False,
            message=f"Cannot verify model {settings.model!r}: Ollama unreachable.",
            remedy="Start Ollama first (see ollama.reachable).",
        )
    if health.has_model(settings.model):
        return CheckResult(
            name="ollama.model",
            passed=True,
            message=f"Model {settings.model!r} is pulled.",
        )
    return CheckResult(
        name="ollama.model",
        passed=False,
        message=f"Model {settings.model!r} not pulled (have: {', '.join(health.models) or 'none'}).",
        remedy=f"Run `ollama pull {settings.model}`.",
    )


async def check_ollama_reachable(settings: Settings) -> CheckResult:
    """Verify the Ollama HTTP API responds on the configured base URL."""
    health = await OllamaClient(base_url=settings.ollama_base_url).health()
    return _check_ollama_reachable(settings, health)


async def check_model_pulled(settings: Settings) -> CheckResult:
    """Verify the configured chat model is among the pulled tags."""
    health = await OllamaClient(base_url=settings.ollama_base_url).health()
    return _check_model_pulled(settings, health)


def check_docker_available() -> CheckResult:
    """Verify the Docker CLI is on PATH and the daemon responds."""
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        return CheckResult(
            name="docker.available",
            passed=False,
            message="`docker` not found on PATH.",
            remedy="Install Docker Desktop from https://www.docker.com/products/docker-desktop/.",
        )
    try:
        proc = subprocess.run(
            [docker_bin, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult(
            name="docker.available",
            passed=False,
            message=f"`docker version` failed: {exc}",
            remedy="Start Docker Desktop and retry.",
        )
    if proc.returncode != 0:
        return CheckResult(
            name="docker.available",
            passed=False,
            message=f"Docker daemon not responding ({proc.stderr.strip() or 'unknown error'}).",
            remedy="Start Docker Desktop and retry.",
        )
    return CheckResult(
        name="docker.available",
        passed=True,
        message=f"Docker daemon reachable (server v{proc.stdout.strip()}).",
    )


def check_port_free(settings: Settings) -> CheckResult:
    """Verify the gateway can bind on (host, port)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((settings.host, settings.port))
    except OSError as exc:
        return CheckResult(
            name="gateway.port",
            passed=False,
            message=f"Port {settings.host}:{settings.port} not available: {exc}",
            remedy=(
                f"Stop whatever is listening on {settings.port}, or set "
                f"DECLAW_PORT to a free port."
            ),
        )
    else:
        return CheckResult(
            name="gateway.port",
            passed=True,
            message=f"Port {settings.host}:{settings.port} is free.",
        )
    finally:
        sock.close()


async def run_all(settings: Settings | None = None) -> list[CheckResult]:
    """Run every pre-flight check and return the results in fixed order.

    A single Ollama health snapshot is shared between the reachability and
    model checks to avoid making four HTTP requests when two suffice.
    """
    settings = settings or get_settings()
    health = await OllamaClient(base_url=settings.ollama_base_url).health()
    ollama_reachable = _check_ollama_reachable(settings, health)
    model_pulled = _check_model_pulled(settings, health)
    docker = check_docker_available()
    port = check_port_free(settings)
    return [ollama_reachable, model_pulled, docker, port]
