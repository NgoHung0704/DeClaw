"""Path-traversal protection corpus (DCL-026).

A 35+ entry adversarial corpus against ``_resolve_in_workspace`` — the single
security boundary between a model-supplied path and the user's filesystem.

The corpus was built by probing the resolver and recording, for every vector,
whether it raised or stayed inside the workspace (it found two non-obvious
weaknesses — NTFS alternate data streams were allowed, and NUL bytes raised a
bare ``ValueError`` — both since hardened).

Test strategy:

* ``test_invariant_never_escapes`` (the core guarantee, platform-agnostic):
  EVERY vector either raises ``WorkspacePathError`` or resolves to a path
  strictly inside the workspace. Nothing ever leaks out.
* ``test_always_rejected``: real escapes that must raise on every OS.
* ``test_windows_only_rejected`` (skipif != win32): drive specs, UNC paths,
  backslash traversal, and NTFS alternate data streams — all rely on Windows
  path semantics.
* ``test_contained_tricks_do_not_decode``: inputs that LOOK like traversal but
  are literal filenames (URL-encoding, unicode look-alikes, tilde) must stay
  inside — proof the resolver never URL-decodes or expands ``~``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from declaw.config import get_settings
from declaw.tools.builtin.filesystem import WorkspacePathError, _resolve_in_workspace


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(ws))
    return ws


# --- Corpus groups ----------------------------------------------------------

# Real escapes that must be rejected on every platform: '/' is a separator
# everywhere, '\x00' is never legal, and '/etc/passwd' is either absolute
# (POSIX) or resolves out of the workspace volume (Windows).
_ALWAYS_REJECTED = [
    "../outside.txt",
    "../../etc/passwd",
    "../../../",
    "a/../../escape.txt",
    "a/b/../../../escape.txt",
    "../../..//etc/passwd",
    "./../../x",
    "subdir/../../../etc",
    "/etc/passwd",
    "/",
    "a\x00.txt",
    "..\x00/escape",
    "good/../../\x00bad",
]

# Rely on Windows path semantics: drive letters, UNC, backslash separators,
# and the ':' alternate-data-stream / drive-relative side channels.
_WINDOWS_ONLY_REJECTED = [
    "..\\outside.txt",
    "a\\..\\..\\escape.txt",
    "C:\\Windows\\System32",
    "C:/Windows",
    "C:foo",
    "\\\\server\\share\\x",
    "\\absolute_from_root.txt",
    "notes.txt:hidden",
    "notes.txt::$DATA",
    "file.txt:secret:$DATA",
    "..\\..\\Users",
    "....//x",  # Windows treats '....' as a parent ref -> resolves outside
]

# Look like traversal but are literal filenames: the resolver must NOT
# URL-decode, must NOT treat unicode look-alikes as '.', and must NOT expand
# '~'. All of these stay inside the workspace.
_CONTAINED_TRICKS = [
    "%2e%2e/x",
    "..%2f..%2fx",
    "%2e%2e%2f%2e%2e%2fetc",
    "..%5c..%5cx",
    "．．/x",  # fullwidth full stops
    "..⁄x",  # U+2044 fraction slash, not '/'
    "．．／x",  # fullwidth dots + fullwidth solidus
    "~/secret",
    "~root/.ssh/id_rsa",
    "a/./b/../c",
    "normal_file.txt",
]

_FULL_CORPUS = _ALWAYS_REJECTED + _WINDOWS_ONLY_REJECTED + _CONTAINED_TRICKS


def test_corpus_is_at_least_30() -> None:
    assert len(_FULL_CORPUS) >= 30


# --- The core invariant: nothing ever escapes the workspace -----------------


@pytest.mark.parametrize("raw", _FULL_CORPUS)
def test_invariant_never_escapes(workspace: Path, raw: str) -> None:
    """Every adversarial path either raises or resolves strictly inside."""
    ws = Path(get_settings().workspace_dir).resolve()
    try:
        resolved = _resolve_in_workspace(raw)
    except WorkspacePathError:
        return  # rejected — fine
    # If it did not raise, it MUST be inside the workspace.
    resolved.relative_to(ws)  # raises ValueError if it escaped -> test fails


# --- Specific rejections ----------------------------------------------------


@pytest.mark.parametrize("raw", _ALWAYS_REJECTED)
def test_always_rejected(workspace: Path, raw: str) -> None:
    with pytest.raises(WorkspacePathError):
        _resolve_in_workspace(raw)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")
@pytest.mark.parametrize("raw", _WINDOWS_ONLY_REJECTED)
def test_windows_only_rejected(workspace: Path, raw: str) -> None:
    with pytest.raises(WorkspacePathError):
        _resolve_in_workspace(raw)


# --- Contained tricks: not decoded, not expanded, never escape --------------


@pytest.mark.parametrize("raw", _CONTAINED_TRICKS)
def test_contained_tricks_do_not_decode(workspace: Path, raw: str) -> None:
    """These resolve to a literal (usually nonexistent) path inside workspace."""
    ws = Path(get_settings().workspace_dir).resolve()
    resolved = _resolve_in_workspace(raw)
    resolved.relative_to(ws)  # must be inside; raises -> test fails


# --- Explicit named cases for the two hardening findings --------------------


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")
def test_alternate_data_stream_rejected(workspace: Path) -> None:
    with pytest.raises(WorkspacePathError, match="alternate data stream|':'"):
        _resolve_in_workspace("contract.txt:hidden_stream")


def test_nul_byte_rejected_as_workspace_error(workspace: Path) -> None:
    """NUL bytes raise WorkspacePathError, not a bare ValueError from resolve()."""
    with pytest.raises(WorkspacePathError, match="NUL"):
        _resolve_in_workspace("evil\x00.txt")
