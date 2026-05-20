"""Async client wrapper around the Ollama HTTP API.

Only the calls DeClaw needs are exposed. The wrapper exists so that the rest
of the codebase never imports ``httpx`` directly, which makes mocking trivial
and lets us swap transports later without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from declaw.config import get_settings


@dataclass(frozen=True, slots=True)
class OllamaHealth:
    """Snapshot of Ollama reachability and required-model presence."""

    reachable: bool
    version: str | None
    models: tuple[str, ...]
    error: str | None = None

    def has_model(self, name: str) -> bool:
        """True if ``name`` is among the pulled models (exact tag match)."""
        return name in self.models


class OllamaClient:
    """Minimal async client for the local Ollama daemon."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or get_settings().ollama_base_url).rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    async def version(self) -> str:
        """Return the Ollama server version string. Raises on failure."""
        async with self._client() as http:
            response = await http.get("/api/version")
            response.raise_for_status()
            return str(response.json()["version"])

    async def list_models(self) -> tuple[str, ...]:
        """Return the tags of every model currently pulled by Ollama."""
        async with self._client() as http:
            response = await http.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
            return tuple(model["name"] for model in payload.get("models", []))

    async def health(self) -> OllamaHealth:
        """Single-call health snapshot. Never raises — errors are reported in-band."""
        try:
            async with self._client() as http:
                version_resp = await http.get("/api/version")
                version_resp.raise_for_status()
                version = str(version_resp.json()["version"])

                tags_resp = await http.get("/api/tags")
                tags_resp.raise_for_status()
                models = tuple(m["name"] for m in tags_resp.json().get("models", []))
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return OllamaHealth(reachable=False, version=None, models=(), error=str(exc))

        return OllamaHealth(reachable=True, version=version, models=models)
