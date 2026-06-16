"""Workspace-scoped filesystem tools (DCL-021 / DCL-022 / DCL-023 / DCL-024).

These tools are the first place where a path coming from the model can reach
the user's filesystem, so the path resolver is the security boundary.
Defence-in-depth:

1. Absolute paths are rejected before resolution (no ``/etc/passwd``).
2. The user-supplied path is joined to the workspace root, then ``.resolve()``
   canonicalises symlinks and (on Windows) NTFS 8.3 short names.
3. The canonical path must be inside the workspace — checked via
   ``Path.relative_to``. Anything escaping (``..`` traversal, symlink to
   outside, short-name alias to outside) raises ``WorkspacePathError``.

``WorkspacePathError`` extends ``ValueError`` so LangGraph's ``ToolNode``
surfaces it as a ``ToolMessage`` error the model (and the audit trail) can see.

Classifications: ``filesystem_read`` is READ (the confirmation queue lets it
auto-run); ``filesystem_write`` and ``filesystem_move`` are WRITE (every call
goes through ``declaw.tools.confirmation`` before reaching ``_arun``). The tools
themselves are *unaware* of the confirmation gate — that gate is layered in by
the brain when the tool is wired into ``ToolNode``.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
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
    # File contents are untrusted external content: route through the sanitizer.
    produces_external_content: bool = True

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


class FilesystemWriteArgs(BaseModel):
    """Args for :class:`FilesystemWriteTool`."""

    path: str = Field(
        ...,
        description=(
            "Path to the file, relative to the workspace root. "
            "Absolute paths and '..' segments are rejected."
        ),
    )
    content: str = Field(..., description="UTF-8 text content to write.")
    overwrite: bool = Field(
        default=False,
        description="Set true to overwrite an existing file (default false).",
    )


_WRITE_DESCRIPTION_EN = (
    "Write a UTF-8 text file in the user's workspace. PATH is relative to the "
    "workspace root; absolute paths and '..' traversal are rejected. "
    "OVERWRITE=true is required to replace an existing file. The parent "
    "directory must already exist (this tool does not create directories)."
)

_WRITE_DESCRIPTION_FR = (
    "Écrit un fichier texte UTF-8 dans l'espace de travail de l'utilisateur. "
    "PATH est relatif à la racine du workspace ; les chemins absolus et la "
    "traversée '..' sont refusés. OVERWRITE=true est requis pour remplacer un "
    "fichier existant. Le dossier parent doit déjà exister (cet outil ne crée "
    "pas de dossiers)."
)


class FilesystemWriteTool(DeclawTool[FilesystemWriteArgs]):
    """Write a UTF-8 text file in the workspace (workspace-scoped, WRITE-class).

    Classification is WRITE: every call MUST go through the confirmation gate
    in ``declaw.tools.confirmation`` before reaching this ``_arun``. This tool
    is intentionally unaware of confirmation - the gate is layered outside.
    """

    name: str = "filesystem_write"
    description_en: str = _WRITE_DESCRIPTION_EN
    description_fr: str = _WRITE_DESCRIPTION_FR
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[FilesystemWriteArgs] = FilesystemWriteArgs

    async def _arun(self, args: FilesystemWriteArgs) -> str:
        resolved = _resolve_in_workspace(args.path)
        if resolved.exists():
            if not resolved.is_file():
                raise WorkspacePathError(f"Not a regular file: {args.path!r}")
            if not args.overwrite:
                raise WorkspacePathError(
                    f"File already exists: {args.path!r} "
                    "(set overwrite=true to replace)."
                )
        if not resolved.parent.exists():
            raise WorkspacePathError(
                f"Parent directory does not exist for: {args.path!r}"
            )
        resolved.write_text(args.content, encoding="utf-8")
        return f"Wrote {len(args.content)} characters to {args.path}."


class FilesystemMoveArgs(BaseModel):
    """Args for :class:`FilesystemMoveTool`."""

    source: str = Field(
        ...,
        description=(
            "Path of the file to move, relative to the workspace root. "
            "Absolute paths and '..' segments are rejected."
        ),
    )
    destination: str = Field(
        ...,
        description=(
            "Destination path, relative to the workspace root. "
            "Absolute paths and '..' segments are rejected."
        ),
    )
    overwrite: bool = Field(
        default=False,
        description="Set true to overwrite an existing destination (default false).",
    )


_MOVE_DESCRIPTION_EN = (
    "Move or rename a file within the user's workspace. SOURCE and DESTINATION "
    "are both relative to the workspace root; absolute paths and '..' traversal "
    "are rejected, and moves across volumes are refused. OVERWRITE=true is "
    "required to replace an existing destination. The destination's parent "
    "directory must already exist."
)

_MOVE_DESCRIPTION_FR = (
    "Déplace ou renomme un fichier dans l'espace de travail de l'utilisateur. "
    "SOURCE et DESTINATION sont relatifs à la racine du workspace ; les chemins "
    "absolus et la traversée '..' sont refusés, et les déplacements entre "
    "volumes sont refusés. OVERWRITE=true est requis pour remplacer une "
    "destination existante. Le dossier parent de la destination doit déjà exister."
)


class FilesystemMoveTool(DeclawTool[FilesystemMoveArgs]):
    """Move/rename a file within the workspace (workspace-scoped, WRITE-class).

    Both paths go through ``_resolve_in_workspace``, so traversal/symlink/short-
    name escapes are rejected on either side. Cross-volume moves are refused as
    defence-in-depth (containment already keeps both paths on the workspace
    volume, but an explicit check makes the guarantee auditable). Like the write
    tool, this is unaware of confirmation - the gate is layered outside.
    """

    name: str = "filesystem_move"
    description_en: str = _MOVE_DESCRIPTION_EN
    description_fr: str = _MOVE_DESCRIPTION_FR
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[FilesystemMoveArgs] = FilesystemMoveArgs

    async def _arun(self, args: FilesystemMoveArgs) -> str:
        source = _resolve_in_workspace(args.source)
        destination = _resolve_in_workspace(args.destination)

        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {args.source!r}")
        if not source.is_file():
            raise WorkspacePathError(f"Source is not a regular file: {args.source!r}")
        if source.drive != destination.drive:
            raise WorkspacePathError(
                f"Refusing to move across volumes: "
                f"{args.source!r} -> {args.destination!r}."
            )
        if destination.exists():
            if not destination.is_file():
                raise WorkspacePathError(
                    f"Destination is not a regular file: {args.destination!r}"
                )
            if not args.overwrite:
                raise WorkspacePathError(
                    f"Destination already exists: {args.destination!r} "
                    "(set overwrite=true to replace)."
                )
        if not destination.parent.exists():
            raise WorkspacePathError(
                f"Destination parent directory does not exist for: "
                f"{args.destination!r}"
            )
        source.replace(destination)
        return f"Moved {args.source} to {args.destination}."


class FilesystemListArgs(BaseModel):
    """Args for :class:`FilesystemListTool`."""

    path: str = Field(
        default=".",
        description=(
            "Directory to list, relative to the workspace root (default '.', "
            "the workspace root itself). Absolute paths and '..' are rejected."
        ),
    )


_LIST_DESCRIPTION_EN = (
    "List the entries of a directory in the user's workspace, with each entry's "
    "type (dir/file), size in bytes, and last-modified time. PATH is relative "
    "to the workspace root (default '.'); absolute paths and '..' traversal are "
    "rejected."
)

_LIST_DESCRIPTION_FR = (
    "Liste le contenu d'un dossier de l'espace de travail, avec pour chaque "
    "entrée son type (dir/file), sa taille en octets et sa date de "
    "modification. PATH est relatif à la racine du workspace (par défaut '.') ; "
    "les chemins absolus et la traversée '..' sont refusés."
)


class FilesystemListTool(DeclawTool[FilesystemListArgs]):
    """List a workspace directory's entries with metadata (workspace-scoped, READ)."""

    name: str = "filesystem_list"
    description_en: str = _LIST_DESCRIPTION_EN
    description_fr: str = _LIST_DESCRIPTION_FR
    classification: ToolClass = ToolClass.READ
    args_schema: type[FilesystemListArgs] = FilesystemListArgs

    async def _arun(self, args: FilesystemListArgs) -> str:
        resolved = _resolve_in_workspace(args.path)
        if not resolved.exists():
            raise FileNotFoundError(f"Directory not found: {args.path!r}")
        if not resolved.is_dir():
            raise WorkspacePathError(f"Not a directory: {args.path!r}")

        entries = sorted(resolved.iterdir(), key=lambda p: p.name)
        if not entries:
            return f"{args.path} is empty."

        lines = [f"{'type':4}  {'size':>10}  {'modified':19}  name"]
        for entry in entries:
            stat = entry.stat()
            is_dir = entry.is_dir()
            kind = "dir" if is_dir else "file"
            size = "-" if is_dir else str(stat.st_size)
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            lines.append(f"{kind:4}  {size:>10}  {mtime:19}  {entry.name}")
        return "\n".join(lines)


def _resolve_in_workspace(raw_path: str) -> Path:
    """Resolve ``raw_path`` inside the workspace root; raise on escape.

    Defence layers, in order:

    1. Reject embedded NUL bytes (never valid in any path; also stops C-string
       truncation tricks) — raised as ``WorkspacePathError`` for a consistent,
       auditable boundary rather than a bare ``ValueError`` from ``resolve()``.
    2. Reject absolute paths up front, so they cannot replace the workspace
       root after joining (``/etc/passwd``, ``C:\\Windows``, UNC shares).
    3. On Windows, reject any ``:`` — it can never be a legal filename
       character there, so it is always either a drive-relative spec (``C:foo``)
       or an NTFS alternate data stream (``notes.txt:hidden``), both of which
       are side channels a workspace path must not reach. (POSIX allows ``:``
       in filenames and has neither side channel, so the check is Windows-only.)
    4. Join + ``resolve()`` (canonicalises symlinks and NTFS 8.3 short names),
       then require containment via ``relative_to``.
    """
    if "\x00" in raw_path:
        raise WorkspacePathError(f"Path contains a NUL byte: {raw_path!r}")
    workspace = Path(get_settings().workspace_dir).resolve()
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise WorkspacePathError(f"Absolute paths are not allowed: {raw_path!r}")
    if sys.platform == "win32" and ":" in raw_path:
        raise WorkspacePathError(
            f"Path contains ':' (drive-relative or alternate data stream): "
            f"{raw_path!r}"
        )
    resolved = (workspace / candidate).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise WorkspacePathError(
            f"Path resolves outside the workspace: {raw_path!r}"
        ) from exc
    return resolved
