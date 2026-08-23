"""Exits hard while a request is in flight, to exercise crash handling."""

from __future__ import annotations

import os

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class NoArgs(BaseModel):
    pass


class CrashPlugin(BasePlugin):
    name = "crash-plugin"
    version = "1.0.0"

    @capability(name="die", description_en="Exit hard.", description_fr="Se termine.")
    async def die(self, args: NoArgs) -> str:
        # os._exit skips cleanup, which is exactly the ugly death being tested.
        os._exit(1)
