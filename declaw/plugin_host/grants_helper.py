"""Where the grant and state files live, in one place.

Two CLI commands and the chat session all need these paths; deriving them
separately in each would be three chances to disagree.
"""

from __future__ import annotations

from pathlib import Path

from declaw.plugin_host.permissions import GRANTS_FILENAME, GrantStore
from declaw.plugin_host.state import STATE_FILENAME, PluginStateStore


def load_grants(data_dir: Path) -> GrantStore:
    """Open the user's plugin permission grants."""
    return GrantStore(data_dir / GRANTS_FILENAME)


def load_state(data_dir: Path) -> PluginStateStore:
    """Open the user's plugin enable/disable/quarantine state."""
    return PluginStateStore(data_dir / STATE_FILENAME)
