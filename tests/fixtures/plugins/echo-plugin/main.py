"""Echo plugin — the reference plugin the host integration tests drive."""

from __future__ import annotations

from pydantic import BaseModel

from declaw_plugin_sdk.declaration import BasePlugin, capability


class EchoArgs(BaseModel):
    message: str
    times: int = 1


class CountArgs(BaseModel):
    values: list[str]


class EchoPlugin(BasePlugin):
    name = "echo-plugin"
    version = "1.0.0"

    @capability(
        name="echo",
        description_en="Repeat a message back.",
        description_fr="Renvoie un message.",
        exposed_to_model=True,
        classification="read",
    )
    async def echo(self, args: EchoArgs) -> str:
        return " ".join([args.message] * args.times)

    @capability(
        name="count",
        description_en="Count the values given.",
        description_fr="Compte les valeurs fournies.",
        requires=["filesystem.read"],
    )
    async def count(self, args: CountArgs) -> dict[str, int]:
        return {"count": len(args.values)}

    @capability(
        name="noisy",
        description_en="Print to stdout, then answer.",
        description_fr="Ecrit sur stdout, puis repond.",
        exposed_to_model=True,
        classification="read",
    )
    async def noisy(self, args: EchoArgs) -> str:
        # Proves stdout hygiene: this must not corrupt the protocol stream.
        print("stray print that must not reach the host as a frame")
        return args.message
