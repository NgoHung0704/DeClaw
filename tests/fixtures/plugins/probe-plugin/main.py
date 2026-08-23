"""Reports what the plugin process can see, so tests can assert on it."""

from __future__ import annotations

import os

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class NoArgs(BaseModel):
    pass


class ProbePlugin(BasePlugin):
    name = "probe-plugin"
    version = "1.0.0"

    @capability(
        name="try_import",
        description_en="Try to import declaw and report the outcome.",
        description_fr="Tente d'importer declaw et rapporte le resultat.",
    )
    async def try_import(self, args: NoArgs) -> str:
        try:
            import declaw  # noqa: F401
        except ImportError as exc:
            return f"blocked: {exc}"
        return "IMPORT SUCCEEDED"

    @capability(
        name="import_sdk",
        description_en="Confirm the SDK itself is importable.",
        description_fr="Confirme que le SDK est importable.",
    )
    async def import_sdk(self, args: NoArgs) -> str:
        import declaw_plugin_sdk.protocol

        return f"ok {declaw_plugin_sdk.protocol.SDK_VERSION}"

    @capability(
        name="dump_env",
        description_en="Return the environment variable names visible here.",
        description_fr="Renvoie les noms des variables d'environnement visibles.",
    )
    async def dump_env(self, args: NoArgs) -> list[str]:
        return sorted(os.environ)
