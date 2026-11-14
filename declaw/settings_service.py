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
from declaw.settings_file import (
    MUTABLE_KEYS,
    SETTINGS_FILENAME,
    InvalidSettingsFileError as InvalidSettingsFileError,
    effective_workspace,
    read_settings_file,
    same_path,
    validate_language,
    validate_model,
)
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
        self.path = self._settings.data_dir / SETTINGS_FILENAME

    def effective(self) -> EffectiveSettings:
        """Build the immutable effective-settings snapshot (env > file > defaults).

        Fails closed with :class:`InvalidSettingsFileError` when the composed
        workspace violates the ``workspace_dir != data_dir`` rule
        (:meth:`update` refuses to store such a value, but the file can be
        hand-edited — isolation rules hold regardless of the write path).
        """
        file_values = self._file_values()
        composed: dict[str, Any] = {}
        for key in MUTABLE_KEYS:
            if key == "workspace_dir":
                composed[key] = effective_workspace(
                    self._settings.workspace_dir,
                    self._settings.data_dir,
                    "workspace_dir" in self._settings.model_fields_set,
                    file_values,
                )
                continue
            env_value = getattr(self._settings, key)
            env_is_explicit = key in self._settings.model_fields_set
            file_value = file_values.get(key)
            if env_is_explicit or file_value is None:
                composed[key] = env_value
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
            validate_model(model)
            file_values["model"] = model
            applied["model"] = APPLIED_NEW_SESSION
        if language is not None:
            validate_language(language)
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
        return read_settings_file(self.path)

    def _write(self, values: dict[str, str]) -> None:
        self._settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")


def _resolve_workspace(workspace_dir: str, data_dir: Path) -> Path:
    """Validate a new workspace and make "creatable" real (mkdir).

    The workspace must not equal ``data_dir``: the document stack treats the
    workspace as untrusted user content while ``data_dir`` holds the database
    and this settings file — a workspace equal to the data directory would
    feed application state to the indexer.

    Empty or whitespace-only values are rejected before any path math: ""
    would become ``Path(".")`` (the CWD — a containment bypass) and a
    whitespace-only value would round-trip into a file value the read path
    drops, reporting "restart_required" for a setting that never applies.
    """
    if not workspace_dir.strip():
        raise ValueError("workspace_dir must be a non-empty string.")
    path = Path(workspace_dir).expanduser()
    if same_path(path, data_dir):
        raise ValueError(f"workspace_dir must not equal data_dir ({data_dir}).")
    try:
        # "Exists or is creatable" is proved by creating it now, so the
        # restart that applies this setting finds a real directory.
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"workspace_dir is not creatable: {exc}") from exc
    return path
