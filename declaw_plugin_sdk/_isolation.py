"""Block ``declaw.*`` imports inside a plugin process.

This is an ARCHITECTURAL boundary, not a security control, and the difference
matters. ``declaw`` lives in the same virtualenv, so it is importable no matter
what PYTHONPATH says, and plugin code could remove this hook from
``sys.meta_path`` in one line. What the hook buys is that a plugin author
cannot accidentally couple to core internals: the failure is immediate and the
message says what to do instead.

Real containment of hostile plugin code needs OS-level sandboxing.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from importlib.machinery import ModuleSpec
from types import ModuleType


class DeclawImportBlocker:
    """A ``sys.meta_path`` finder that refuses the core package."""

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        # Exact match or a real submodule. 'declaw_plugin_sdk' must pass.
        if fullname == "declaw" or fullname.startswith("declaw."):
            raise ImportError(
                f"Plugins may not import {fullname!r}. A plugin talks to DeClaw only "
                "over the IPC protocol; everything you need is in declaw_plugin_sdk."
            )
        return None


def install_import_blocker() -> None:
    """Install the blocker ahead of every other finder."""
    sys.meta_path.insert(0, DeclawImportBlocker())
