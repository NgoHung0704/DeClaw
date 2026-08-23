"""Every way the plugin host can fail, as one importable taxonomy.

Kept in its own module so ``ipc``, ``process``, ``supervisor`` and ``host`` can
raise each other's errors without importing each other.
"""

from __future__ import annotations


class PluginHostError(Exception):
    """Base class for every plugin-host failure."""


class PluginLoadError(PluginHostError):
    """A plugin could not be loaded. Message is user-facing."""


class ProtocolViolationError(PluginHostError):
    """The plugin broke the wire contract. Three of these kill the process."""


class FrameTooLargeError(ProtocolViolationError):
    """A frame exceeded MAX_FRAME_BYTES in either direction."""


class MalformedFrameError(ProtocolViolationError):
    """A frame was not parseable as a valid response."""


class PluginCrashedError(PluginHostError):
    """The plugin process exited while a request was in flight."""


class PluginTimeoutError(PluginHostError):
    """A capability exceeded its declared timeout; the process was restarted."""


class PluginUnavailableError(PluginHostError):
    """The plugin is disabled or quarantined, so the call cannot be made."""


class PluginCapabilityError(PluginHostError):
    """The plugin answered a request with a structured error frame."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")
