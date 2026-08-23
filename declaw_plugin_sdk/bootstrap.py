"""``python -m declaw_plugin_sdk.bootstrap <plugin_dir> <entrypoint>``.

Order matters here. The real stdout is duplicated away and fd 1 is pointed at
stderr *before* any plugin code runs, so a stray ``print()`` in the plugin
cannot corrupt the protocol stream. The import blocker goes in next, before the
entrypoint is imported, so it covers the plugin's own imports.

The host passes the entrypoint path rather than letting this module read
``plugin.yaml``: the host has already parsed and validated the manifest, and
keeping YAML out of here keeps the SDK's dependencies to pydantic alone.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from declaw_plugin_sdk._isolation import install_import_blocker
from declaw_plugin_sdk.declaration import BasePlugin
from declaw_plugin_sdk.runtime import _write_all, run


def _load_plugin_class(plugin_dir: Path, entrypoint: str) -> type[BasePlugin]:
    module_path = plugin_dir / entrypoint
    spec = importlib.util.spec_from_file_location(f"declaw_plugin_{plugin_dir.name}", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot import plugin entrypoint {module_path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    found = [
        value
        for value in vars(module).values()
        if isinstance(value, type) and issubclass(value, BasePlugin) and value is not BasePlugin
    ]
    if len(found) != 1:
        raise SystemExit(
            f"{module_path} must define exactly one BasePlugin subclass, found {len(found)}."
        )
    return found[0]


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit("usage: python -m declaw_plugin_sdk.bootstrap <plugin_dir> <entrypoint>")
    plugin_dir = Path(args[0]).resolve()

    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    install_import_blocker()
    sys.path.insert(0, str(plugin_dir))

    plugin = _load_plugin_class(plugin_dir, args[1])()
    run(plugin, write_frame=lambda data: _write_all(protocol_fd, data))


if __name__ == "__main__":
    main()
