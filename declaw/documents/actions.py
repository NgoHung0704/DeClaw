"""Actions the model can propose over the user's documents.

Both tools here are WRITE-class, so the registry gates them behind the
confirmation provider before anything touches disk.

``organize_files`` validates the ENTIRE plan before executing any of it. A
half-finished reorganisation is worse than a refused one: the user no longer
knows where their files are, and neither does the index.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from declaw.tools.base import DeclawTool, ToolClass
from declaw.tools.builtin._paths import resolve_in_workspace

# How many moves to show in full before summarising the rest.
_PREVIEW_LINES = 10


class FileMove(BaseModel):
    """One move in an organisation plan."""

    source: str = Field(description="Existing file, relative to the workspace root.")
    destination: str = Field(description="Where it should end up, relative to the root.")


class OrganizeArgs(BaseModel):
    """Arguments for ``organize_files``."""

    moves: list[FileMove] = Field(
        min_length=1, description="Every move to perform, as one reviewable plan."
    )


_ORGANIZE_EN = (
    "Reorganise several files at once, for example grouping invoices by supplier. "
    "Give the complete plan as a list of moves; the user approves the whole plan "
    "once. Missing folders are created. Paths are relative to the workspace root."
)
_ORGANIZE_FR = (
    "Réorganise plusieurs fichiers d'un coup, par exemple regrouper les factures "
    "par fournisseur. Fournissez le plan complet sous forme de liste de "
    "déplacements ; l'utilisateur approuve le plan en une fois. Les dossiers "
    "manquants sont créés. Les chemins sont relatifs à la racine."
)


def _entry_fields(entry: Any) -> tuple[str, str]:
    """Read source/destination whether the entry is a dict or a FileMove.

    ``confirmation_preview`` receives the raw kwargs the model produced, which
    are still dicts; the same helper is handy for rendering validated models.
    """
    if isinstance(entry, dict):
        return str(entry.get("source", "")), str(entry.get("destination", ""))
    return str(entry.source), str(entry.destination)


class OrganizeFilesTool(DeclawTool[OrganizeArgs]):
    """Execute a reviewed multi-file reorganisation."""

    name: str = "organize_files"
    description_en: str = _ORGANIZE_EN
    description_fr: str = _ORGANIZE_FR
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[OrganizeArgs] = OrganizeArgs

    def confirmation_preview(self, args: dict[str, Any]) -> str | None:
        """Render the plan so the user can actually read what they approve."""
        raw = args.get("moves") or []
        lines = [f"Move {len(raw)} file(s):"]
        for entry in raw[:_PREVIEW_LINES]:
            source, destination = _entry_fields(entry)
            lines.append(f"  {source} -> {destination}")
        if len(raw) > _PREVIEW_LINES:
            lines.append(f"  ... {len(raw) - _PREVIEW_LINES} more")
        return "\n".join(lines)

    async def _arun(self, args: OrganizeArgs) -> str:
        resolved: list[tuple[Path, Path, FileMove]] = []
        claimed: set[Path] = set()

        # Validate everything first. One bad entry refuses the whole plan:
        # a half-executed reorganisation loses the user their own filing.
        for move in args.moves:
            source = resolve_in_workspace(move.source)
            destination = resolve_in_workspace(move.destination)
            if not source.is_file():
                raise FileNotFoundError(
                    f"Refusing the whole plan: {move.source!r} does not exist."
                )
            if destination.exists():
                raise ValueError(
                    f"Refusing the whole plan: {move.destination!r} already exists."
                )
            if destination in claimed:
                raise ValueError(
                    f"Refusing the whole plan: two moves both target {move.destination!r}."
                )
            claimed.add(destination)
            resolved.append((source, destination, move))

        done: list[str] = []
        for source, destination, move in resolved:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            done.append(f"{move.source} -> {move.destination}")

        listing = "\n".join(done)
        return f"Moved {len(done)} file(s):\n{listing}"
