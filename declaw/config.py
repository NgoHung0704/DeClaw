"""Typed configuration for DeClaw, loaded from environment + .env file.

All settings are namespaced with the ``DECLAW_`` prefix in the environment.
Two settings (``OLLAMA_BASE_URL``) intentionally have no prefix because they
mirror the upstream Ollama convention.

The 7 Inviolable Principles constrain defaults here:
  - host is pinned to ``127.0.0.1`` and must never be widened
  - sandbox / sanitizer / signature requirements default to True
  - external network egress is blocked by default
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


Language = Literal["en", "fr"]
LogLevel = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings.

    Loaded from process environment and (optionally) ``.env`` in CWD.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DECLAW_",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core gateway -------------------------------------------------------
    host: str = Field(default="127.0.0.1", description="Gateway bind host (loopback only).")
    port: int = Field(default=7842, ge=1, le=65535, description="Gateway bind port.")
    debug: bool = Field(default=False, description="Enable verbose debug logging.")
    language: Language = Field(default="en", description="Default UI/system-prompt language.")
    log_level: LogLevel = Field(
        default="INFO", description="Minimum loguru log level (TRACE..CRITICAL)."
    )

    # --- Ollama -------------------------------------------------------------
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
        description="Ollama HTTP API base URL.",
    )
    model: str = Field(default="qwen2.5:3b", description="Primary brain model.")
    # Deliberately LARGER than the brain model. Measured 2026-07-25 on the full
    # 127-sample corpus: qwen2.5:3b gives 7.5-9% false positives (it quarantines
    # ordinary client documents that merely contain a password or an IBAN),
    # while qwen2.5:7b gives 0.0% at the same detection rate. The cost is
    # latency — p50 4.2s vs 1.1s per screened read — which is the right trade for
    # a security layer that gates whether the user can read their own files.
    # Set DECLAW_SANITIZER_MODEL=qwen2.5:3b to trade accuracy back for speed.
    sanitizer_model: str = Field(
        default="qwen2.5:7b",
        description="Sanitizer model (must be a separate Ollama session).",
    )
    embedding_model: str = Field(
        default="nomic-embed-text",
        description="Embedding model for vector memory.",
    )

    # --- Paths --------------------------------------------------------------
    data_dir: Path = Field(
        default=Path("~/.declaw").expanduser(),
        description="Persistent application data (DB, vectors, plugin registry).",
    )
    workspace_dir: Path = Field(
        default=Path("~/DeClaw-workspace").expanduser(),
        description="Default workspace folder (user documents).",
    )

    # --- Security toggles (defaults enforce the 7 principles) ---------------
    require_docker_sandbox: bool = Field(
        default=True,
        description="If True, shell tools are disabled when Docker is unavailable.",
    )
    sanitizer_required: bool = Field(
        default=True,
        description="If True, all external content must pass the sanitizer.",
    )
    plugin_signature_required: bool = Field(
        default=True,
        description="If True, third-party plugins must carry a valid ed25519 signature.",
    )
    block_external_network: bool = Field(
        default=True,
        description="If True, sandboxes start with --network=none.",
    )

    # ------------------------------------------------------------------ validators

    @field_validator("host")
    @classmethod
    def _enforce_loopback(cls, value: str) -> str:
        # Inviolable Principle #2: never bind outside loopback.
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                f"DECLAW_HOST must be a loopback address (got {value!r}). "
                "Binding the gateway outside 127.0.0.1 is forbidden."
            )
        return value

    @field_validator("data_dir", "workspace_dir", mode="before")
    @classmethod
    def _expand_user(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value).expanduser()
        if isinstance(value, Path):
            return value.expanduser()
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton."""
    return Settings()
