"""DeClaw plugin SDK — the contract a plugin process is written against.

This package is deliberately independent of ``declaw``: a plugin runs in a
subprocess where importing ``declaw.*`` is blocked, so anything a plugin needs
must live here. Its only dependency is pydantic.

The host imports this package too. That direction is fine and intentional —
one definition of the wire format means the two sides cannot drift apart.
"""

from __future__ import annotations

from declaw_plugin_sdk.protocol import PROTOCOL_VERSION, SDK_VERSION

__all__ = ["PROTOCOL_VERSION", "SDK_VERSION"]
