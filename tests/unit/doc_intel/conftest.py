"""Make the doc-intel plugin importable for fast unit tests.

The plugin is not a package on sys.path — at runtime it is loaded by file path
inside an isolated subprocess. These tests exercise its pure parsing and
chunking logic directly, which is far faster than driving a subprocess; the
subprocess path gets its own integration test in Task 6.
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins" / "builtin" / "doc-intel"

if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))
