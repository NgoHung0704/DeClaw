"""Which plugins are on, off, or quarantined — as plain JSON.

Deliberately not SQLite, and deliberately next to ``plugin_grants.json``. This
file is the user's own policy, so being able to open it, read it and diff it is
a transparency feature rather than an implementation detail. Four fields per
plugin do not justify a second database with its own migration chain.

Crash counters are NOT here. A restart gives a misbehaving plugin a fresh
chance; if it still misbehaves it is re-quarantined within a minute. Quarantine
itself does persist, because clearing it should be a deliberate act.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from declaw.log import logger

STATE_FILENAME = "plugin_state.json"


@dataclass(frozen=True, slots=True)
class PluginRecord:
    """Everything remembered about one plugin between runs."""

    enabled: bool = True
    quarantined: bool = False
    quarantine_reason: str = ""
    last_version: str = ""
    # Permissions auto-granted at least once. Presence here means "never
    # auto-grant again", which is what makes a user's revoke permanent.
    auto_granted: tuple[str, ...] = ()


class PluginStateStore:
    """Load, mutate and persist :class:`PluginRecord`s."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: dict[str, PluginRecord] = {}
        if path.is_file():
            self._records = self._load(path)

    @staticmethod
    def _load(path: Path) -> dict[str, PluginRecord]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Ignoring unreadable {path}: {exc}. Plugin state resets to defaults.")
            return {}
        if not isinstance(raw, dict):
            logger.warning(f"Ignoring {path}: top level is not an object.")
            return {}
        records: dict[str, PluginRecord] = {}
        for name, values in raw.items():
            if not isinstance(values, dict):
                continue
            records[name] = PluginRecord(
                enabled=bool(values.get("enabled", True)),
                quarantined=bool(values.get("quarantined", False)),
                quarantine_reason=str(values.get("quarantine_reason", "")),
                last_version=str(values.get("last_version", "")),
                auto_granted=tuple(str(p) for p in values.get("auto_granted", [])),
            )
        return records

    def record(self, name: str) -> PluginRecord:
        return self._records.get(name, PluginRecord())

    def all(self) -> dict[str, PluginRecord]:
        return dict(self._records)

    def _update(self, name: str, **changes: Any) -> None:
        self._records[name] = replace(self.record(name), **changes)
        self._save()

    def set_enabled(self, name: str, enabled: bool) -> None:
        self._update(name, enabled=enabled)

    def quarantine(self, name: str, reason: str) -> None:
        self._update(name, quarantined=True, quarantine_reason=reason)

    def clear_quarantine(self, name: str) -> None:
        self._update(name, quarantined=False, quarantine_reason="")

    def note_version(self, name: str, version: str) -> None:
        self._update(name, last_version=version)

    def note_auto_grant(self, name: str, permission: str) -> None:
        current = self.record(name).auto_granted
        if permission not in current:
            self._update(name, auto_granted=(*current, permission))

    def has_auto_granted(self, name: str, permission: str) -> bool:
        return permission in self.record(name).auto_granted

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            name: {
                "enabled": record.enabled,
                "quarantined": record.quarantined,
                "quarantine_reason": record.quarantine_reason,
                "last_version": record.last_version,
                "auto_granted": sorted(record.auto_granted),
            }
            for name, record in sorted(self._records.items())
        }
        # Write-then-replace so a crash mid-write cannot leave a truncated file.
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self._path)
