"""Unit tests for the DeClaw config system (DCL-004).

Verifies the four acceptance criteria:
  - Settings model loads defaults + ``.env`` + environment variables
  - Type validation (port range, language enum, loopback host)
  - ``get_settings()`` returns a process-wide singleton
  - Environment variables use the ``DECLAW_`` prefix
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from declaw.config import Settings, get_settings


# Settings(_env_file=None) skips ``.env`` lookup so the test does not depend on
# whatever .env happens to sit in CWD.
def _fresh(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


# --- Defaults --------------------------------------------------------------


def test_defaults_match_locked_decisions() -> None:
    s = _fresh()

    assert s.host == "127.0.0.1"
    assert s.port == 7842
    assert s.language == "en"
    assert s.model == "mistral:7b"
    assert s.sanitizer_model == "mistral:7b"
    assert s.embedding_model == "nomic-embed-text"
    assert s.ollama_base_url == "http://localhost:11434"

    # The 7 Inviolable Principles default to True.
    assert s.require_docker_sandbox is True
    assert s.sanitizer_required is True
    assert s.plugin_signature_required is True
    assert s.block_external_network is True


# --- Loading from environment (DECLAW_ prefix) -----------------------------


def test_loads_from_declaw_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECLAW_PORT", "9000")
    monkeypatch.setenv("DECLAW_LANGUAGE", "fr")
    monkeypatch.setenv("DECLAW_MODEL", "phi3:mini")

    s = _fresh()

    assert s.port == 9000
    assert s.language == "fr"
    assert s.model == "phi3:mini"


def test_ollama_base_url_uses_unprefixed_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    # The alias is OLLAMA_BASE_URL (no DECLAW_ prefix) so it matches the
    # upstream Ollama convention.
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.local:11434")

    s = _fresh()

    assert s.ollama_base_url == "http://ollama.local:11434"


# --- Type validation -------------------------------------------------------


def test_port_must_be_in_range() -> None:
    with pytest.raises(ValidationError):
        _fresh(port="70000")  # type: ignore[arg-type]


def test_language_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        _fresh(language="es")  # type: ignore[arg-type]


def test_host_must_be_loopback() -> None:
    # Inviolable Principle #2: gateway must never bind outside loopback.
    with pytest.raises(ValidationError, match="loopback"):
        _fresh(host="0.0.0.0")

    with pytest.raises(ValidationError, match="loopback"):
        _fresh(host="192.168.1.50")


def test_host_accepts_all_loopback_variants() -> None:
    for value in ("127.0.0.1", "localhost", "::1"):
        assert _fresh(host=value).host == value


def test_paths_expand_user_tilde() -> None:
    s = _fresh(data_dir="~/.declaw-test", workspace_dir="~/work-test")  # type: ignore[arg-type]

    assert s.data_dir == Path("~/.declaw-test").expanduser()
    assert s.workspace_dir == Path("~/work-test").expanduser()
    assert "~" not in str(s.data_dir)


# --- Singleton -------------------------------------------------------------


def test_get_settings_returns_singleton() -> None:
    get_settings.cache_clear()
    try:
        first = get_settings()
        second = get_settings()
        assert first is second
    finally:
        get_settings.cache_clear()


# --- .env file support -----------------------------------------------------


def test_loads_from_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DECLAW_PORT=12345\n"
        "DECLAW_LANGUAGE=fr\n"
        "DECLAW_MODEL=test-model\n",
        encoding="utf-8",
    )

    s = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

    assert s.port == 12345
    assert s.language == "fr"
    assert s.model == "test-model"
