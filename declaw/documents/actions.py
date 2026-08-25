"""Actions the model can propose over the user's documents.

Both tools here are WRITE-class, so the registry gates them behind the
confirmation provider before anything touches disk.

``organize_files`` validates the ENTIRE plan before executing any of it. A
half-finished reorganisation is worse than a refused one: the user no longer
knows where their files are, and neither does the index.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from declaw.config import Language
from declaw.documents.citations import format_source
from declaw.documents.search import ChunkSanitizer, SearchableStore, search_documents
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


_SUMMARY_STRINGS = {
    "en": {
        "heading": "# Summary",
        "sources": "## Sources",
        "provenance": (
            "_Written by DeClaw's local AI from the passages listed below. "
            "It can be wrong — verify against the sources before relying on it._"
        ),
        "none": "_No indexed document matched this query._",
        "written": "Wrote {path} ({count} source(s)).",
    },
    "fr": {
        "heading": "# Résumé",
        "sources": "## Sources",
        "provenance": (
            "_Rédigé par l'IA locale de DeClaw à partir des passages listés "
            "ci-dessous. Elle peut se tromper : vérifiez les sources avant de "
            "vous y fier._"
        ),
        "none": "_Aucun document indexé ne correspond à cette requête._",
        "written": "{path} écrit ({count} source(s)).",
    },
}


class SummarizeArgs(BaseModel):
    """Arguments for ``document_summarize``."""

    query: str = Field(description="What the summary is about, for finding its sources.")
    summary: str = Field(description="The summary text you wrote.")
    path: str = Field(default="summary.md", description="Where to save it, relative to the root.")
    overwrite: bool = Field(default=False, description="Replace the file if it exists.")


_SUMMARIZE_EN = (
    "Save a summary you have written about the user's documents. Give the same "
    "query you searched with: DeClaw looks the sources up itself and appends them, "
    "so the citations are always real. Writes summary.md by default."
)
_SUMMARIZE_FR = (
    "Enregistre un résumé que vous avez rédigé sur les documents de l'utilisateur. "
    "Fournissez la même requête que pour la recherche : DeClaw retrouve les sources "
    "lui-même et les ajoute, donc les citations sont toujours réelles. Écrit "
    "summary.md par défaut."
)


class DocumentSummarizeTool(DeclawTool[SummarizeArgs]):
    """Write a summary whose citations DeClaw looked up, not the model."""

    name: str = "document_summarize"
    description_en: str = _SUMMARIZE_EN
    description_fr: str = _SUMMARIZE_FR
    classification: ToolClass = ToolClass.WRITE
    args_schema: type[SummarizeArgs] = SummarizeArgs

    build_document: Callable[[SummarizeArgs], Awaitable[str]]

    async def _arun(self, args: SummarizeArgs) -> str:
        return await self.build_document(args)


def build_document_summarize_tool(
    *,
    store: SearchableStore,
    chunk_sanitizer: ChunkSanitizer,
    language: Language,
) -> DocumentSummarizeTool:
    """Wire retrieval into the summarize tool so citations cannot be invented.

    The model supplies the prose; this tool re-runs the search and builds the
    sources block from real retrieval metadata. That is the rule which survives
    from DCL-062 — not "never use the model", but "never let the model invent
    the citation".
    """
    strings = _SUMMARY_STRINGS[language]

    async def build_document(args: SummarizeArgs) -> str:
        target = resolve_in_workspace(args.path)
        if target.exists() and not args.overwrite:
            raise ValueError(
                f"{args.path!r} already exists. Pass overwrite=true to replace it."
            )
        if not target.parent.is_dir():
            raise FileNotFoundError(f"Folder for {args.path!r} does not exist.")

        outcome = await search_documents(store, chunk_sanitizer, args.query)
        sources: list[str] = []
        for hit in outcome.hits:
            rendered = format_source(hit)
            if rendered not in sources:
                sources.append(rendered)

        body = [strings["heading"], "", args.summary.strip(), "", strings["provenance"], ""]
        body.append(strings["sources"])
        if sources:
            body.extend(f"- {source}" for source in sources)
        else:
            body.append(strings["none"])

        target.write_text("\n".join(body) + "\n", encoding="utf-8")
        return strings["written"].format(path=args.path, count=len(sources))

    return DocumentSummarizeTool(build_document=build_document)
