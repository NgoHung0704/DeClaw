"""Mutable UI-facing settings, composed and applied without cache tricks (DCL-131).

Spec section 12. Three layers exist:

* the environment layer — the existing process-wide :class:`Settings` /
  :func:`declaw.config.get_settings` (a ``lru_cache``) — stays untouched and
  keeps owning every security toggle;
* the UI layer — ``data_dir/settings.json``, the only store this service
  writes, holding just the three v0.1 mutable keys (``model``,
  ``language``, ``workspace_dir``);
* the defaults — the field defaults of :class:`Settings`.

Precedence is environment > file > defaults. A key carried in
``Settings.model_fields_set`` counts as *explicitly set* by the env layer
(whether via an environment variable or ``.env``) and wins over the file;
everything else falls through to the file, then to the defaults the env layer
already computes for us.

Application semantics never touch the global cache: :meth:`effective` builds a
fresh immutable :class:`EffectiveSettings` snapshot per new session, and the
brain seams (``build_brain`` / ``build_ollama_model``) take explicit
``model`` / ``language`` parameters fed from that snapshot — the cached
``get_settings()`` is never cleared or mutated to serve a browser request.
``model`` / ``language`` therefore apply to *new* sessions
(``applied: "new_session"``); ``workspace_dir`` is consumed at process start by
the document stack, watcher, catalog and path containment, so it is
``applied: "restart_required"``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from declaw.config import Language, Settings, get_settings
from declaw.log import logger

_SETTINGS_FILENAME = "settings.json"
_ALLOWED_LANGUAGES = ("en", "fr")
# The only keys editable from the UI in v0.1. Security toggles stay env-only
# so a compromised session cannot quietly lower defenses.
MUTABLE_KEYS = ("model", "language", "workspace_dir")
APPLIED_NEW_SESSION = "new_session"
APPLIED_RESTART_REQUIRED = "restart_required"


class EffectiveSettings(BaseModel):
    """Immutable per-session snapshot of the three mutable keys.

    A frozen pydantic model: any mutation attempt raises, so a session that
    stashes its snapshot can trust it for the rest of its life.
    """

    model_config = ConfigDict(frozen=True)

    model: str
    language: Language
    workspace_dir: Path


class SettingsService:
    """Compose env + ``data_dir/settings.json``; own every write to that file."""

    def __init__(self, settings: Settings | None = None) -> None:
        # The env layer is injectable so tests own it deterministically; the
        # production default is the process-wide cached Settings.
        self._settings = settings if settings is not None else get_settings()
        self.path = self._settings.data_dir / _SETTINGS_FILENAME

    def effective(self) -> EffectiveSettings:
        """Build the immutable effective-settings snapshot (env > file > defaults)."""
        file_values = self._file_values()
        composed: dict[str, Any] = {}
        for key in MUTABLE_KEYS:
            env_value = getattr(self._settings, key)
            env_is_explicit = key in self._settings.model_fields_set
            file_value = file_values.get(key)
            if env_is_explicit or file_value is None:
                composed[key] = env_value
            elif key == "workspace_dir":
                composed[key] = Path(str(file_value)).expanduser()
            else:
                composed[key] = file_value
        return EffectiveSettings(**composed)

    def update(
        self,
        model: str | None = None,
        language: str | None = None,
        workspace_dir: str | None = None,
    ) -> dict[str, str]:
        """Validate and persist the given mutable keys.

        Validation is fail-closed and atomic: every key argument is checked
        *before* anything is created or written, so a rejected update leaves
        the file (and the filesystem) exactly as it was. On success the merged
        file is written and each updated key is reported with its apply
        semantics: ``"new_session"`` for ``model``/``language``,
        ``"restart_required"`` for ``workspace_dir``.
        """
        file_values = self._file_values()
        applied: dict[str, str] = {}
        if model is not None:
            _validate_model(model)
            file_values["model"] = model
            applied["model"] = APPLIED_NEW_SESSION
        if language is not None:
            _validate_language(language)
            file_values["language"] = language
            applied["language"] = APPLIED_NEW_SESSION
        if workspace_dir is not None:
            path = _resolve_workspace(workspace_dir, self._settings.data_dir)
            file_values["workspace_dir"] = str(path)
            applied["workspace_dir"] = APPLIED_RESTART_REQUIRED
        if applied:
            self._write(file_values)
        return applied

    def _file_values(self) -> dict[str, str]:
        """Read the mutable keys from the file, dropping anything invalid.

        The file is local state, but hand-edited or partially corrupt files
        must not break every session start: unparsable content and values
        that fail the same validation as :meth:`update` are ignored with an
        operational-log warning, and the env defaults apply.
        """
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Unreadable settings file ignored: {}", self.path)
            return {}
        if not isinstance(payload, dict):
            logger.warning("Settings file is not a JSON object, ignored: {}", self.path)
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

    def _write(self, values: dict[str, str]) -> None:
        self._settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")


def _validate_model(model: str) -> None:
    # Existence is checked against Ollama at the next session start, not here:
    # saving must not require the daemon (spec section 12).
    if not model.strip():
        raise ValueError("model must be a non-empty string.")


def _validate_language(language: str) -> None:
    if language not in _ALLOWED_LANGUAGES:
        raise ValueError(f"language must be one of {list(_ALLOWED_LANGUAGES)}.")


def _validate_file_value(key: str, value: object) -> None:
    """Validate a raw JSON value from the file with the update() rules."""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string.")
    if key == "model":
        _validate_model(value)
    elif key == "language":
        _validate_language(value)
    elif key == "workspace_dir":
        if not value.strip():
            raise ValueError("workspace_dir must be a non-empty string.")


def _resolve_workspace(workspace_dir: str, data_dir: Path) -> Path:
    """Validate a new workspace and make "creatable" real (mkdir).

    The workspace must not equal ``data_dir``: the document stack treats the
    workspace as untrusted user content while ``data_dir`` holds the database
    and this settings file — a workspace equal to the data directory would
    feed application state to the indexer.
    """
    path = Path(workspace_dir).expanduser()
    if _same_path(path, data_dir):
        raise ValueError(f"workspace_dir must not equal data_dir ({data_dir}).")
    try:
        # "Exists or is creatable" is proved by creating it now, so the
        # restart that applies this setting finds a real directory.
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"workspace_dir is not creatable: {exc}") from exc
    return path


def _same_path(left: Path, right: Path) -> bool:
    """Compare two paths after resolution (case, symlinks, 8.3 short names)."""
    try:
        return left.resolve() == right.resolve()
    except OSError:  # pragma: no cover - resolve failures only surface the
        return left == right  # literal comparison as a conservative fallback
