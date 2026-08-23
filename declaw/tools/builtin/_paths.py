"""Workspace containment for every path DeClaw touches.

Moved out of ``filesystem.py`` when it gained a fifth prospective consumer: the
plugin host resolves and validates a path before handing it to a parser plugin,
because a plugin opens files itself rather than receiving bytes over the pipe.

The guarantee, unchanged since DCL-026 and pinned by the 36-vector corpus in
``tests/unit/test_path_traversal.py``: every input either raises
``WorkspacePathError`` or resolves strictly inside the workspace. Nothing leaks,
on any platform.

``WorkspacePathError`` extends ``ValueError`` so LangGraph's ``ToolNode``
surfaces it as a ``ToolMessage`` error the model (and the audit trail) can see.
"""

from __future__ import annotations

import sys
from pathlib import Path

from declaw.config import get_settings


class WorkspacePathError(ValueError):
    """Raised when a path is outside the workspace or otherwise unsafe."""


def resolve_in_workspace(raw_path: str) -> Path:
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
