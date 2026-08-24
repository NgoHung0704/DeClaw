"""Unit tests for the Ollama client wrapper.

All HTTP traffic is intercepted by ``httpx.MockTransport`` — these tests must
run with no Ollama daemon present.
"""

from __future__ import annotations

import httpx
import pytest

from declaw.brain.ollama_client import OllamaClient, OllamaHealth


def _transport(handler):  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


def _ok_handler(*, models: list[str], version: str = "0.3.14"):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": version})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": name} for name in models]}
            )
        return httpx.Response(404)

    return handler


async def test_health_reports_ok_when_model_present() -> None:
    client = OllamaClient(
        base_url="http://test",
        transport=_transport(_ok_handler(models=["mistral:7b", "nomic-embed-text"])),
    )

    health = await client.health()

    assert health == OllamaHealth(
        reachable=True,
        version="0.3.14",
        models=("mistral:7b", "nomic-embed-text"),
        error=None,
    )
    assert health.has_model("mistral:7b")
    assert not health.has_model("llama3:70b")


async def test_health_reports_model_missing() -> None:
    client = OllamaClient(
        base_url="http://test",
        transport=_transport(_ok_handler(models=["llama3:8b"])),
    )

    health = await client.health()

    assert health.reachable is True
    assert health.has_model("mistral:7b") is False


async def test_health_swallows_connection_errors() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = OllamaClient(base_url="http://test", transport=_transport(boom))

    health = await client.health()

    assert health.reachable is False
    assert health.version is None
    assert health.models == ()
    assert health.error is not None
    assert "connection refused" in health.error


async def test_health_handles_http_error_status() -> None:
    def server_error(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = OllamaClient(base_url="http://test", transport=_transport(server_error))

    health = await client.health()

    assert health.reachable is False
    assert health.error is not None


async def test_version_raises_on_failure() -> None:
    def server_error(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = OllamaClient(base_url="http://test", transport=_transport(server_error))

    with pytest.raises(httpx.HTTPStatusError):
        await client.version()


async def test_list_models_returns_tag_names() -> None:
    client = OllamaClient(
        base_url="http://test",
        transport=_transport(_ok_handler(models=["mistral:7b", "phi3:mini"])),
    )

    models = await client.list_models()

    assert models == ("mistral:7b", "phi3:mini")


# --- tag matching (found live 2026-08-23: nomic-embed-text vs :latest) -----


def test_has_model_matches_an_exact_tag() -> None:
    from declaw.brain.ollama_client import OllamaHealth

    health = OllamaHealth(reachable=True, version="1.0", models=("qwen2.5:3b-declaw",))
    assert health.has_model("qwen2.5:3b-declaw") is True


def test_an_untagged_name_matches_the_latest_tag() -> None:
    # `ollama pull nomic-embed-text` stores it as 'nomic-embed-text:latest'.
    # Without this, a user who follows our own remedy message is told the
    # model is still missing -- an unresolvable loop.
    from declaw.brain.ollama_client import OllamaHealth

    health = OllamaHealth(reachable=True, version="1.0", models=("nomic-embed-text:latest",))
    assert health.has_model("nomic-embed-text") is True


def test_a_different_tag_still_does_not_match() -> None:
    from declaw.brain.ollama_client import OllamaHealth

    health = OllamaHealth(reachable=True, version="1.0", models=("qwen2.5:7b",))
    assert health.has_model("qwen2.5:3b") is False


def test_an_absent_model_is_absent() -> None:
    from declaw.brain.ollama_client import OllamaHealth

    health = OllamaHealth(reachable=True, version="1.0", models=("qwen2.5:7b",))
    assert health.has_model("nomic-embed-text") is False
