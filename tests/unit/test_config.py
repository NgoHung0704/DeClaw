"""Unit tests for the DeClaw config system (DCL-004).

Verifies the four acceptance criteria:
  - Settings model loads defaults + ``.env`` + environment variables
  - Type validation (port range, language enum, loopback host)
  - ``get_settings()`` returns a process-wide singleton
  - Environment variables use the ``DECLAW_`` prefix
"""

from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from declaw.config import Settings, get_settings


def test_cold_settings_does_not_load_service_or_operational_logging(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    workspace = tmp_path / "saved-workspace"
    (data / "settings.json").write_text(
        json.dumps({"workspace_dir": str(workspace)}), encoding="utf-8"
    )
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("DECLAW_")}
    environment["DECLAW_DATA_DIR"] = str(data)
    probe = subprocess.run(
        [sys.executable, "-c", "import json, sys; from declaw.config import get_settings; "
         "s = get_settings(); print(json.dumps([str(s.workspace_dir), "
         "'declaw.settings_service' in sys.modules, 'declaw.log' in sys.modules]))"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=15,
        check=True,
    )
    assert json.loads(probe.stdout) == [str(workspace), False, False]


def test_cold_settings_rejects_saved_workspace_equal_to_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from declaw.settings_service import InvalidSettingsFileError

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DECLAW_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DECLAW_WORKSPACE_DIR", raising=False)
    (tmp_path / "settings.json").write_text(
        json.dumps({"workspace_dir": str(tmp_path)}), encoding="utf-8"
    )
    with pytest.raises(InvalidSettingsFileError, match="data_dir"):
        get_settings()


def test_saved_workspace_applies_to_cold_start_and_path_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from declaw.settings_service import SettingsService
    from declaw.tools.builtin._paths import resolve_in_workspace

    monkeypatch.chdir(tmp_path)  # no developer .env file
    monkeypatch.setenv("DECLAW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DECLAW_WORKSPACE_DIR", raising=False)
    settings = get_settings()
    new_workspace = tmp_path / "chosen-workspace"
    SettingsService(settings).update(workspace_dir=str(new_workspace))
    get_settings.cache_clear()  # a new process reads persisted settings
    assert get_settings().workspace_dir == new_workspace
    assert resolve_in_workspace("notes.txt") == new_workspace / "notes.txt"

    # Environment remains authoritative over the saved file on restart.
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(tmp_path / "env-workspace"))
    get_settings.cache_clear()
    assert get_settings().workspace_dir == tmp_path / "env-workspace"


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
    assert s.model == "qwen2.5:3b"
    # Bigger than the brain on purpose: the 3b classifier false-positives on
    # ordinary confidential documents (7.5-9% vs 0.0% measured, see config.py).
    assert s.sanitizer_model == "qwen2.5:7b"
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
