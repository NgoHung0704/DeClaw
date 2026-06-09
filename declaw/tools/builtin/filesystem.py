"""filesystem_read: workspace-scoped, traversal-safe (DCL-021).

This is the first real built-in tool, so it is also the first place where a
path coming from the model can reach the actual filesystem. Defence-in-depth:

1. Absolute paths are rejected before resolution (no ``/etc/passwd``).
2. The user-supplied path is joined to the workspace root, then ``.resolve()``
   canonicalises symlinks and (on Windows) NTFS 8.3 short names.
3. The canonical path must be inside the workspace — checked via
   ``Path.relative_to``. Anything escaping (``..`` traversal, symlink to
   outside, short-name alias to outside) raises ``WorkspacePathError``.

``WorkspacePathError`` extends ``ValueError`` so LangGraph's ``ToolNode``
surfaces it as a ``ToolMessage`` error the model (and the audit trail) can see.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from declaw.config import get_settings
from declaw.tools.base import DeclawTool, ToolClass


class WorkspacePathError(ValueError):
    """Raised when a path is outside the workspace or otherwise unsafe."""


class FilesystemReadArgs(BaseModel):
    """Args for :class:`FilesystemReadTool`."""

    path: str = Field(
        ...,
        description=(
            "Path to the file, relative to the workspace root. "
            "Absolute paths and '..' segments are rejected."
        ),
    )
    max_bytes: int = Field(
        default=100_000,
        ge=1,
        description="Maximum number of bytes to read (default 100000).",
    )


_DESCRIPTION_EN = (
    "Read a UTF-8 text file from the user's workspace. PATH is relative to "
    "the workspace root; absolute paths and '..' traversal are rejected. "
    "MAX_BYTES caps how many bytes are read (default 100000)."
)

_DESCRIPTION_FR = (
    "Lit un fichier texte UTF-8 depuis l'espace de travail de l'utilisateur. "
    "PATH est relatif à la racine du workspace ; les chemins absolus et la "
    "traversée '..' sont refusés. MAX_BYTES limite le nombre d'octets lus "
    "(par défaut 100000)."
)


class FilesystemReadTool(DeclawTool[FilesystemReadArgs]):
    """Read a UTF-8 text file from the workspace (workspace-scoped, traversal-safe)."""

    name: str = "filesystem_read"
    description_en: str = _DESCRIPTION_EN
    description_fr: str = _DESCRIPTION_FR
    classification: ToolClass = ToolClass.READ
    args_schema: type[FilesystemReadArgs] = FilesystemReadArgs

    async def _arun(self, args: FilesystemReadArgs) -> str:
        resolved = _resolve_in_workspace(args.path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {args.path!r}")
        if not resolved.is_file():
            raise WorkspacePathError(f"Not a regular file: {args.path!r}")
        size = resolved.stat().st_size
        if size > args.max_bytes:
            raise WorkspacePathError(
                f"File is {size} bytes (max_bytes={args.max_bytes}); refusing to read."
            )
        return resolved.read_text(encoding="utf-8")


def _resolve_in_workspace(raw_path: str) -> Path:
    """Resolve ``raw_path`` inside the workspace root; raise on escape.

    ``Path.resolve()`` canonicalises symlinks and (on Windows) NTFS 8.3 short
    names, so containment is checked against the *real* path. Absolute paths
    are rejected before resolution to short-circuit ``/etc/passwd``-style
    attacks (they would otherwise replace the workspace root after joining).
    """
    workspace = Path(get_settings().workspace_dir).resolve()
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise WorkspacePathError(f"Absolute paths are not allowed: {raw_path!r}")
    resolved = (workspace / candidate).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise WorkspacePathError(
            f"Path resolves outside the workspace: {raw_path!r}"
        ) from exc
    return resolved
