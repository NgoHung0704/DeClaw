"""Declares a capability needing a permission the manifest never requested."""

from __future__ import annotations

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class NoArgs(BaseModel):
    pass


class OverreachPlugin(BasePlugin):
    name = "overreach-plugin"
    version = "1.0.0"

    @capability(
        name="peek",
        description_en="Read files.",
        description_fr="Lit des fichiers.",
        requires=["filesystem.read"],
    )
    async def peek(self, args: NoArgs) -> str:
        return "never reached"
