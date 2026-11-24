"""``GET``/``PUT /api/settings`` — the Task 8 handoffs, wired (DCL-131, spec §12).

GET serves the immutable effective-settings snapshot
(``SettingsService.effective().model_dump()``); PUT validates and persists
through ``SettingsService.update`` and reports the per-key apply flags
(``new_session`` / ``restart_required``) unchanged from Task 8.

Fail-closed file handling: a ``settings.json`` that violates the isolation
rule composes no snapshot — GET answers 409 ``invalid_settings_file``, not a
default-looking value that would quietly rebind the workspace. Editable keys
are only the three mutable ones (schemas enforce this); everything else stays
env-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request

from declaw.config import Language
from declaw.gateway.routes.auth import require_session
from declaw.gateway.routes.errors import ApiError, application_from
from declaw.gateway.schemas import SettingsUpdate
from declaw.settings_service import InvalidSettingsFileError

if TYPE_CHECKING:
    from declaw.app import Application

router = APIRouter(prefix="/api/settings", dependencies=[Depends(require_session)])

_FILE_ERROR_CODE = "invalid_settings_file"
_SETTINGS_ERROR_CODE = "invalid_settings"


def effective_language(application: Application) -> Language:
    """The composed UI language, or the env layer when the file fails closed.

    Localization of descriptions is cosmetic: a hand-corrupted settings file
    degrades the label language rather than failing status/plugin listings
    that must keep working precisely while the user repairs the file.
    """
    try:
        return application.settings_service.effective().language
    except InvalidSettingsFileError:
        return application.settings.language


def _effective_payload(application: Application) -> dict[str, str]:
    try:
        return application.settings_service.effective().model_dump(mode="json")
    except InvalidSettingsFileError as exc:
        raise ApiError(409, _FILE_ERROR_CODE, str(exc)) from exc


@router.get("")
async def get_settings(request: Request) -> dict[str, str]:
    """Serve the effective snapshot (env > file > defaults), composed per call."""
    application = application_from(request)
    return _effective_payload(application)


@router.put("")
async def put_settings(payload: SettingsUpdate, request: Request) -> dict[str, object]:
    """Validate, persist and report apply flags for the mutable keys.

    An empty body is a minimal no-op: nothing is written, every key stays
    untouched and the response carries the unchanged snapshot with an empty
    ``applied`` map (the semantics pinned with the Task 8 handoff).
    """
    application = application_from(request)
    try:
        applied = application.settings_service.update(
            model=payload.model,
            language=payload.language,
            workspace_dir=payload.workspace_dir,
        )
    except ValueError as exc:
        raise ApiError(422, _SETTINGS_ERROR_CODE, str(exc)) from exc
    response: dict[str, Any] = _effective_payload(application)
    response["applied"] = applied
    return response
