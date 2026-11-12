"""Read mutable settings values without loading application/configuration services."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from loguru import logger

SETTINGS_FILENAME = "settings.json"
MUTABLE_KEYS = ("model", "language", "workspace_dir")
_ALLOWED_LANGUAGES = ("en", "fr")


class InvalidSettingsFileError(RuntimeError):
    """The composed workspace violates a hard rule; callers must fail closed."""


def read_settings_file(path: Path) -> dict[str, str]:
    """Read valid mutable keys; warn and ignore malformed data as before."""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Unreadable settings file ignored: {}", path)
        return {}
    if not isinstance(payload, dict):
        logger.warning("Settings file is not a JSON object, ignored: {}", path)
        return {}
    values: dict[str, str] = {}
    for key in MUTABLE_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        try:
            _validate_file_value(key, value)
        except ValueError as exc:
            logger.warning("Invalid {} in settings file ignored: {}", key, exc)
            continue
        values[key] = value
    return values


def effective_workspace(
    default: Path, data_dir: Path, explicit: bool, values: Mapping[str, str]
) -> Path:
    """Compose env > file > default workspace and preserve the containment guard."""
    saved = values.get("workspace_dir")
    workspace = default if explicit or saved is None else Path(saved).expanduser()
    if same_path(workspace, data_dir):
        raise InvalidSettingsFileError(
            f"{data_dir / SETTINGS_FILENAME}: workspace_dir must not equal data_dir "
            f"({data_dir}); fix or delete the settings file."
        )
    return workspace


def validate_model(model: str) -> None:
    # Saving does not depend on the model or Ollama being available.
    if not model.strip():
        raise ValueError("model must be a non-empty string.")


def validate_language(language: str) -> None:
    if language not in _ALLOWED_LANGUAGES:
        raise ValueError(f"language must be one of {list(_ALLOWED_LANGUAGES)}.")


def _validate_file_value(key: str, value: object) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string.")
    if key == "model":
        validate_model(value)
    elif key == "language":
        validate_language(value)
    elif key == "workspace_dir" and not value.strip():
        raise ValueError("workspace_dir must be a non-empty string.")


def same_path(left: Path, right: Path) -> bool:
    """Compare resolved paths, including case, symlinks and NTFS short names."""
    try:
        return left.resolve() == right.resolve()
    except OSError:  # pragma: no cover - conservative fallback on resolve failure
        return left == right
