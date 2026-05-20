"""Session-wide pytest fixtures for DeClaw.

Applied automatically to every test without explicit import.
"""

from __future__ import annotations

import pytest

from declaw.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear the get_settings() LRU cache before each test.

    Prevents env-var changes made by one test (via monkeypatch.setenv) from
    leaking into the next through the cached singleton.
    """
    get_settings.cache_clear()
    yield  # type: ignore[misc]
    get_settings.cache_clear()
