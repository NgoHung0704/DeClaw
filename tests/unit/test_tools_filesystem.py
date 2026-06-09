"""Adversarial tests for filesystem_read (DCL-021).

The path resolver is the security boundary between the model and the user's
filesystem. These tests cover the categories called out in the ticket
acceptance: ``..`` traversal, absolute paths, symlinks that escape the
workspace, and NTFS 8.3 short names. Symlink and Windows-specific tests
skip when the OS doesn't support them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from declaw.tools.builtin.filesystem import (
    FilesystemReadTool,
    FilesystemWriteTool,
    WorkspacePathError,
)


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace dir wired into Settings via DECLAW_WORKSPACE_DIR."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(ws))
    return ws


@pytest.fixture
def tool() -> FilesystemReadTool:
    return FilesystemReadTool()


# --- Happy path --------------------------------------------------------------


async def test_reads_text_file_inside_workspace(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    (workspace / "hello.txt").write_text("Hello world", encoding="utf-8")
    assert await tool.run_validated({"path": "hello.txt"}) == "Hello world"


async def test_reads_unicode_content(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    """Files with French accents must round-trip through UTF-8 unchanged."""
    (workspace / "fr.txt").write_text("Café — chocolat", encoding="utf-8")
    assert await tool.run_validated({"path": "fr.txt"}) == "Café — chocolat"


async def test_reads_nested_path(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    sub = workspace / "a" / "b"
    sub.mkdir(parents=True)
    (sub / "c.txt").write_text("nested", encoding="utf-8")
    assert await tool.run_validated({"path": "a/b/c.txt"}) == "nested"


# --- Adversarial: traversal & escape ---------------------------------------


async def test_rejects_dotdot_traversal(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    """A user-supplied '..' segment must not escape the workspace."""
    (workspace.parent / "outside.txt").write_text("secret", encoding="utf-8")
    with pytest.raises(WorkspacePathError):
        await tool.run_validated({"path": "../outside.txt"})


async def test_rejects_multi_level_dotdot(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    with pytest.raises(WorkspacePathError):
        await tool.run_validated({"path": "a/../../escape.txt"})


async def test_rejects_absolute_path(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    """Absolute paths would replace the workspace root after joining; reject them."""
    absolute = "C:\\Windows\\notepad.exe" if sys.platform == "win32" else "/etc/passwd"
    with pytest.raises(WorkspacePathError):
        await tool.run_validated({"path": absolute})


async def test_rejects_symlink_pointing_outside_workspace(
    workspace: Path, tmp_path: Path, tool: FilesystemReadTool
) -> None:
    """A symlink inside the workspace pointing outside must be rejected after resolve()."""
    target = tmp_path / "outside_target.txt"
    target.write_text("secret", encoding="utf-8")
    link = workspace / "evil_link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported in this environment")
    with pytest.raises(WorkspacePathError):
        await tool.run_validated({"path": "evil_link.txt"})


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS 8.3 short names are Windows-only")
async def test_rejects_short_name_traversal_on_windows(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    """An NTFS 8.3 short-name segment combined with '..' must not bypass containment."""
    with pytest.raises(WorkspacePathError):
        await tool.run_validated({"path": "../PROGRA~1/somefile.txt"})


# --- Adversarial: missing / not-a-file / oversize --------------------------


async def test_raises_on_missing_file(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    with pytest.raises(FileNotFoundError):
        await tool.run_validated({"path": "nonexistent.txt"})


async def test_rejects_directory_path(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    (workspace / "subdir").mkdir()
    with pytest.raises(WorkspacePathError):
        await tool.run_validated({"path": "subdir"})


async def test_rejects_file_larger_than_max_bytes(
    workspace: Path, tool: FilesystemReadTool
) -> None:
    (workspace / "big.txt").write_text("x" * 1000, encoding="utf-8")
    with pytest.raises(WorkspacePathError):
        await tool.run_validated({"path": "big.txt", "max_bytes": 100})


# --- Args schema -----------------------------------------------------------


async def test_max_bytes_must_be_positive(tool: FilesystemReadTool) -> None:
    with pytest.raises(ValidationError):
        await tool.run_validated({"path": "anything.txt", "max_bytes": 0})


async def test_path_is_required(tool: FilesystemReadTool) -> None:
    with pytest.raises(ValidationError):
        await tool.run_validated({})


# ============================================================================
# FilesystemWriteTool (DCL-022)
# ============================================================================


@pytest.fixture
def write_tool() -> FilesystemWriteTool:
    return FilesystemWriteTool()


# --- Write: happy path -----------------------------------------------------


async def test_write_creates_new_file(
    workspace: Path, write_tool: FilesystemWriteTool
) -> None:
    result = await write_tool.run_validated({"path": "out.txt", "content": "Hello"})
    assert (workspace / "out.txt").read_text(encoding="utf-8") == "Hello"
    assert "out.txt" in result  # the tool's reply names the file it wrote


async def test_write_round_trips_unicode_content(
    workspace: Path, write_tool: FilesystemWriteTool
) -> None:
    await write_tool.run_validated(
        {"path": "fr.txt", "content": "Café — chocolat"}
    )
    assert (workspace / "fr.txt").read_text(encoding="utf-8") == "Café — chocolat"


async def test_write_overwrites_when_flag_is_true(
    workspace: Path, write_tool: FilesystemWriteTool
) -> None:
    (workspace / "existing.txt").write_text("old", encoding="utf-8")
    await write_tool.run_validated(
        {"path": "existing.txt", "content": "new", "overwrite": True}
    )
    assert (workspace / "existing.txt").read_text(encoding="utf-8") == "new"


# --- Write: overwrite guardrail --------------------------------------------


async def test_write_refuses_to_overwrite_by_default(
    workspace: Path, write_tool: FilesystemWriteTool
) -> None:
    """Without ``overwrite=true`` an existing file must not be clobbered."""
    (workspace / "existing.txt").write_text("original", encoding="utf-8")
    with pytest.raises(WorkspacePathError):
        await write_tool.run_validated(
            {"path": "existing.txt", "content": "clobber"}
        )
    assert (workspace / "existing.txt").read_text(encoding="utf-8") == "original"


# --- Write: traversal & escape ---------------------------------------------


async def test_write_rejects_dotdot_traversal(
    workspace: Path, write_tool: FilesystemWriteTool
) -> None:
    with pytest.raises(WorkspacePathError):
        await write_tool.run_validated({"path": "../leak.txt", "content": "secret"})
    assert not (workspace.parent / "leak.txt").exists()


async def test_write_rejects_absolute_path(
    workspace: Path, write_tool: FilesystemWriteTool
) -> None:
    absolute = "C:\\temp\\evil.txt" if sys.platform == "win32" else "/tmp/evil.txt"
    with pytest.raises(WorkspacePathError):
        await write_tool.run_validated({"path": absolute, "content": "x"})


# --- Write: pre-conditions -------------------------------------------------


async def test_write_refuses_missing_parent_directory(
    workspace: Path, write_tool: FilesystemWriteTool
) -> None:
    """We never silently mkdir -p; the parent directory must already exist."""
    with pytest.raises(WorkspacePathError):
        await write_tool.run_validated(
            {"path": "nonexistent_dir/file.txt", "content": "x"}
        )


async def test_write_refuses_when_path_is_a_directory(
    workspace: Path, write_tool: FilesystemWriteTool
) -> None:
    (workspace / "subdir").mkdir()
    with pytest.raises(WorkspacePathError):
        await write_tool.run_validated(
            {"path": "subdir", "content": "x", "overwrite": True}
        )


# --- Write: schema ---------------------------------------------------------


async def test_write_requires_content(write_tool: FilesystemWriteTool) -> None:
    with pytest.raises(ValidationError):
        await write_tool.run_validated({"path": "x.txt"})
