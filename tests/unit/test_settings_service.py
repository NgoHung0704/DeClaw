"""Unit tests for the mutable settings service (DCL-131, spec section 12).

The service composes the *env* layer (``Settings`` / ``get_settings()``) with
``data_dir/settings.json`` into an immutable per-session snapshot, and is the
only writer of that file. The global ``get_settings()`` cache is never
cleared or mutated on this path.

``ChatOllama`` is faked at its construction boundary (same pattern as
``test_chat_model.py``) so the snapshot-injection seam runs with no daemon.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from declaw.app import Application
from declaw.brain.chat_model import build_ollama_model
from declaw.brain.repl import build_brain
from declaw.brain.stub_tools import echo
from declaw.config import Settings, get_settings
from declaw.settings_service import SettingsService


# The env layer must be deterministic: no ambient DECLAW_* variables and no
# .env lookup leak their values into the composed snapshot.
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DECLAW_MODEL", "DECLAW_LANGUAGE", "DECLAW_WORKSPACE_DIR"):
        monkeypatch.delenv(name, raising=False)


def _service(data_dir: Path, **env: Any) -> SettingsService:
    """Build a service whose env layer is exactly the explicit values given."""
    settings = Settings(_env_file=None, data_dir=data_dir, **env)  # type: ignore[call-arg]
    return SettingsService(settings)


def _write_file(data_dir: Path, payload: dict[str, Any]) -> None:
    (data_dir / "settings.json").write_text(json.dumps(payload), encoding="utf-8")


def _read_file(data_dir: Path) -> dict[str, Any]:
    return json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))


# --- effective(): precedence env > file > defaults ---------------------------


def test_effective_prefers_explicit_env_over_file_over_default(tmp_path: Path) -> None:
    _write_file(
        tmp_path,
        {
            "model": "file-model",
            "language": "fr",
            "workspace_dir": "~/ws-file",
        },
    )

    # `data_dir` is passed positionally, so only `model` is an explicit env.
    snapshot = _service(tmp_path, model="env-model").effective()

    assert snapshot.model == "env-model"  # env > file
    assert snapshot.language == "fr"  # file > default
    assert snapshot.workspace_dir == Path("~/ws-file").expanduser()  # expanded file value


def test_effective_falls_back_to_defaults_without_file_or_env(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).effective()
    bare = Settings(_env_file=None)

    assert snapshot.model == bare.model
    assert snapshot.language == bare.language
    assert snapshot.workspace_dir == bare.workspace_dir


def test_effective_snapshot_is_immutable(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).effective()

    with pytest.raises(ValidationError):
        snapshot.model = "other-model"
    with pytest.raises(ValidationError):
        snapshot.workspace_dir = tmp_path


def test_effective_drops_invalid_file_values_instead_of_crashing(tmp_path: Path) -> None:
    # A hand-edited / corrupt file must not break every session start: the
    # invalid values are ignored and the env defaults apply.
    _write_file(tmp_path, {"model": "  ", "language": "de", "workspace_dir": 42})
    bare = Settings(_env_file=None)

    snapshot = _service(tmp_path).effective()

    assert snapshot.model == bare.model
    assert snapshot.language == bare.language
    assert snapshot.workspace_dir == bare.workspace_dir


# --- update() ---------------------------------------------------------------


def test_update_applies_model_and_language_as_new_session(tmp_path: Path) -> None:
    service = _service(tmp_path)

    applied = service.update(model="llama3.2:1b", language="fr")

    assert applied == {"model": "new_session", "language": "new_session"}
    assert _read_file(tmp_path) == {"model": "llama3.2:1b", "language": "fr"}
    snapshot = service.effective()
    assert snapshot.model == "llama3.2:1b"
    assert snapshot.language == "fr"


def test_update_applies_workspace_dir_as_restart_required_and_creates_it(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    workspace = tmp_path / "editor"

    applied = service.update(workspace_dir=str(workspace))

    assert applied == {"workspace_dir": "restart_required"}
    assert workspace.is_dir()  # "creatable" is made real, so a restart finds it
    assert _read_file(tmp_path)["workspace_dir"] == str(workspace)
    assert service.effective().workspace_dir == workspace


def test_update_creates_workspace_under_missing_parents(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "workspace"

    applied = _service(tmp_path).update(workspace_dir=str(deep))

    assert applied == {"workspace_dir": "restart_required"}
    assert deep.is_dir()


def test_update_rejects_invalid_language_without_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="language"):
        _service(tmp_path).update(language="de")

    assert not (tmp_path / "settings.json").exists()


def test_update_rejects_empty_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="model"):
        _service(tmp_path).update(model="   ")

    assert not (tmp_path / "settings.json").exists()


def test_update_rejects_workspace_equal_to_data_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="data_dir"):
        _service(tmp_path).update(workspace_dir=str(tmp_path))

    assert not (tmp_path / "settings.json").exists()


def test_update_is_atomic_no_partial_write_on_validation_error(tmp_path: Path) -> None:
    _write_file(tmp_path, {"model": "kept-model"})
    service = _service(tmp_path)

    with pytest.raises(ValueError):
        service.update(model="new-model", workspace_dir=str(tmp_path))

    assert _read_file(tmp_path) == {"model": "kept-model"}


def test_update_merges_with_existing_file_values(tmp_path: Path) -> None:
    _write_file(tmp_path, {"language": "fr"})
    service = _service(tmp_path)

    service.update(model="llama3.2:1b")

    assert _read_file(tmp_path) == {"language": "fr", "model": "llama3.2:1b"}


# --- the global get_settings() cache stays untouched ------------------------


def test_effective_and_update_never_clear_or_mutate_the_global_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(get_settings, "cache_clear", lambda: calls.append("clear"))
    cache_info_before = get_settings.cache_info()

    service = _service(tmp_path)
    service.effective()
    service.update(model="llama3.2:1b", language="fr")

    assert calls == []  # the lru_cache is never cleared or recomputed around
    assert get_settings.cache_info() == cache_info_before


def test_application_owns_a_settings_service(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "ws",
        sanitizer_required=False,
    )

    application = Application(settings, mode="cli")

    assert isinstance(application.settings_service, SettingsService)
    assert application.settings_service.path == settings.data_dir / "settings.json"


# --- explicit snapshot injection on the brain seams -------------------------


@pytest.fixture
def _fake_ollama(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    recorded: dict[str, Any] = {}

    class FakeBound:
        async def ainvoke(self, messages: Any) -> Any:
            raise AssertionError("not invoked in these tests")

    class FakeChatOllama:
        def __init__(self, *, model: str, base_url: str) -> None:
            recorded["model"] = model
            recorded["base_url"] = base_url

        def bind_tools(self, tools: Any) -> FakeBound:
            return FakeBound()

    monkeypatch.setattr("declaw.brain.chat_model.ChatOllama", FakeChatOllama)
    return recorded


def test_build_ollama_model_uses_explicit_snapshot_values(
    _fake_ollama: dict[str, Any],
) -> None:
    model = build_ollama_model([echo], model="llama3.2:1b", language="fr")

    assert _fake_ollama["model"] == "llama3.2:1b"
    assert _fake_ollama["base_url"] == get_settings().ollama_base_url
    assert model.language == "fr"  # the session layer reads it off the callable


def test_build_ollama_model_defaults_preserve_cli_behavior(
    _fake_ollama: dict[str, Any],
) -> None:
    settings = get_settings()

    model = build_ollama_model([echo])

    assert _fake_ollama["model"] == settings.model
    assert _fake_ollama["base_url"] == settings.ollama_base_url
    assert model.language == settings.language


def test_build_brain_forwards_explicit_snapshot_params(
    _fake_ollama: dict[str, Any],
) -> None:
    graph = build_brain([echo], model="llama3.2:1b", language="fr")

    assert _fake_ollama["model"] == "llama3.2:1b"
    assert graph is not None
