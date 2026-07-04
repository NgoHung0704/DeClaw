"""Natural-language audit summaries, EN + FR (DCL-062).

Turns a task's typed audit events into a plain-language account a lawyer or
doctor can read, always ending with the headline fact the MVP promises:
**did data leave this device — yes or no** (from NetworkCallEvent.flagged).

Deliberately template-based, NOT LLM-generated: an audit summary must be
deterministic and incapable of hallucination — for regulated professionals a
plausible-but-wrong account is worse than none. A local model may later add
prose polish on top, but the facts below come straight from the events.
"""

from __future__ import annotations

from collections.abc import Sequence

from declaw.audit.events import (
    AnyAuditEvent,
    NetworkCallEvent,
    PermissionPromptEvent,
    QuarantineEvent,
    ToolCallEvent,
)
from declaw.config import Language

_L = {
    "en": {
        "no_events": "No recorded activity.",
        "read": "Read file {path}",
        "list": "Listed folder {path}",
        "write": "Wrote file {path}",
        "move": "Moved {source} to {destination}",
        "generic": "Called tool {name}",
        "denied": " (denied by you)",
        "error": " (failed)",
        "quarantine": "Blocked potentially unsafe content from {source} and quarantined it",
        "network": "Made {count} network call(s), all to local services",
        "network_flagged": "Made {count} network call(s), {flagged} of them OUTSIDE this device",
        "egress_no": "Data left this device: no",
        "egress_yes": "Data left this device: YES ({hosts})",
    },
    "fr": {
        "no_events": "Aucune activité enregistrée.",
        "read": "Lecture du fichier {path}",
        "list": "Consultation du dossier {path}",
        "write": "Écriture du fichier {path}",
        "move": "Déplacement de {source} vers {destination}",
        "generic": "Appel de l'outil {name}",
        "denied": " (refusé par vous)",
        "error": " (échec)",
        "quarantine": "Contenu potentiellement dangereux provenant de {source} bloqué et mis en quarantaine",
        "network": "{count} appel(s) réseau, tous vers des services locaux",
        "network_flagged": "{count} appel(s) réseau, dont {flagged} HORS de cet appareil",
        "egress_no": "Des données ont quitté cet appareil : non",
        "egress_yes": "Des données ont quitté cet appareil : OUI ({hosts})",
    },
}

_TOOL_TEMPLATES = {
    "filesystem_read": ("read", ("path",)),
    "filesystem_list": ("list", ("path",)),
    "filesystem_write": ("write", ("path",)),
    "filesystem_move": ("move", ("source", "destination")),
}


def _tool_line(event: ToolCallEvent, language: Language) -> str:
    strings = _L[language]
    template_key, arg_names = _TOOL_TEMPLATES.get(event.tool_name, ("generic", ()))
    if template_key == "generic" or any(name not in event.args for name in arg_names):
        line = strings["generic"].format(name=event.tool_name)
    else:
        line = strings[template_key].format(**{name: event.args[name] for name in arg_names})
    if event.outcome == "denied":
        line += strings["denied"]
    elif event.outcome == "error":
        line += strings["error"]
    return line


def summarize_events(events: Sequence[AnyAuditEvent], language: Language = "en") -> str:
    """Render ``events`` (one task's worth) as plain-language bullet lines.

    The last line is always the egress verdict — "data left this device:
    yes/no" — derived from the network events, never asserted otherwise.
    """
    strings = _L[language]
    if not events:
        return strings["no_events"]

    lines: list[str] = []
    network_events: list[NetworkCallEvent] = []
    for event in events:
        if isinstance(event, ToolCallEvent):
            lines.append(f"- {_tool_line(event, language)}")
        elif isinstance(event, QuarantineEvent):
            lines.append(f"- {strings['quarantine'].format(source=event.source)}")
        elif isinstance(event, NetworkCallEvent):
            network_events.append(event)
        elif isinstance(event, PermissionPromptEvent):
            # The decision already shows on the ToolCall line; skip the prompt
            # itself to keep the summary readable.
            continue

    flagged = [e for e in network_events if e.flagged]
    if network_events:
        if flagged:
            lines.append(
                "- "
                + strings["network_flagged"].format(
                    count=len(network_events), flagged=len(flagged)
                )
            )
        else:
            lines.append("- " + strings["network"].format(count=len(network_events)))

    if flagged:
        hosts = ", ".join(sorted({e.host for e in flagged}))
        lines.append(strings["egress_yes"].format(hosts=hosts))
    else:
        lines.append(strings["egress_no"])
    return "\n".join(lines)
