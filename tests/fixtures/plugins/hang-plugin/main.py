"""Never answers, to exercise the timeout path."""

from __future__ import annotations

import time

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class NoArgs(BaseModel):
    pass


class HangPlugin(BasePlugin):
    name = "hang-plugin"
    version = "1.0.0"

    @capability(name="wait", description_en="Never answer.", description_fr="Ne repond jamais.")
    async def wait(self, args: NoArgs) -> str:
        time.sleep(3600)
        return "unreachable"
