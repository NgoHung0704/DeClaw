# Phase 8b — actions, index reconciliation, and the benchmark

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the document index tell the truth about what exists on disk, finish MVP DoD #4's actions, and put a non-self-graded number on retrieval quality.

**Architecture:** One defect fix (the index never forgets renamed or deleted documents), two new WRITE-class tools that reuse the existing confirmation gate, a small hook so a multi-file plan can render a readable approval prompt, and a retrieval benchmark that reports a synthetic development score beside a real external held-out score.

**Tech Stack:** Python 3.12, pydantic v2, ChromaDB, pytest, mypy strict, ruff.

**Spec:** `docs/superpowers/specs/2026-08-26-phase-8b-actions-benchmark.md`

## Global Constraints

- Python `>=3.12`. `from __future__ import annotations` at the top of every module.
- `uv run mypy declaw declaw_plugin_sdk` under `strict = true`; `uv run ruff check` clean. Line length 100.
- `uv run pytest` green. `asyncio_mode = "auto"` — do **not** add `@pytest.mark.asyncio`.
- Code and comments in English; every user-facing string ships EN **and** FR.
- Unit tests never need Ollama, Docker, or a network. The EUR-Lex fixtures are read by the live runner only.
- Test fixtures use `build_engine(path)`, never `get_engine()` — the latter is a memoized process-wide singleton and tests would share one database.
- Retrieval benchmark reports **recall@5** (matching `search.DEFAULT_K`) and recall@1 and MRR.
- Divergence warning when development and held-out scores differ by more than **5 points**.
- Commit format `feat(DCL-XXX): …` / `fix(DCL-XXX): …`. Commit at the end of every task.

## File Structure

| File | Responsibility |
| --- | --- |
| `declaw/documents/indexer.py` (modify) | Reconciliation pass, scoped to the walk |
| `declaw/tools/base.py` (modify) | Optional `confirmation_preview` hook |
| `declaw/brain/repl.py` (modify) | Console provider consults the hook |
| `declaw/documents/actions.py` (create) | `organize_files` and `document_summarize` |
| `declaw/documents/benchmark.py` (create) | Model-agnostic recall/MRR harness |
| `declaw/documents/corpus/__init__.py` (create) | Question sets: synthetic + held-out |
| `declaw/documents/corpus/synthetic.py` (create) | Generated French documents + questions |
| `declaw/documents/corpus/heldout.py` (create) | EUR-Lex questions + attribution |
| `scripts/document_benchmark.py` (create) | Live runner |
| `declaw/main.py` (modify) | Report `removed`; register the two new tools |

**Task order:** 1 (defect) → 2 (hook) → 3 (organize) → 4 (summarize) → 5 (move/rename verification) → 6 (benchmark harness) → 7 (corpora + runner) → 8 (docs).

---

### Task 1: Index reconciliation — the defect fix

**Files:**
- Modify: `declaw/documents/indexer.py`
- Modify: `declaw/main.py` (report `removed`)
- Test: `tests/unit/test_documents_indexer.py` (extend)

**Interfaces:**
- Consumes: `DocumentCatalog.known_paths()`, `DocumentCatalog.forget(path)`, `DocumentStore.delete_document(doc_id)`, `document_id(path)`
- Produces: `IndexReport.removed: int`; `DocumentIndexer.index()` prunes entries whose files are gone, scoped to the walked subtree

**The bug, measured before the fix:** a rename leaves the old entry AND adds a
new one; a delete leaves the entry forever. Search then cites files that do not
exist, and a document the user deleted keeps being quoted.

**The subtlety:** `declaw index dossier/` walks one subfolder. Pruning against
the whole catalog would delete the index for every document outside it. **The
prune scope must equal the walk scope.**

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_documents_indexer.py`:

```python
async def test_a_deleted_file_is_pruned_from_the_index(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    # The defect this phase exists to fix: a document the user deleted must
    # stop being quoted, and stop being cited.
    index, _parser, workspace = indexer
    _write(workspace, "contrat.txt")
    await index.index()
    assert index.store.count() == 1

    (workspace / "contrat.txt").unlink()
    report = await index.index()

    assert report.removed == 1
    assert index.store.count() == 0
    assert await index.catalog.known_paths() == []


async def test_a_renamed_file_moves_rather_than_doubling(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, _parser, workspace = indexer
    _write(workspace, "contrat.txt")
    await index.index()

    (workspace / "contrat.txt").rename(workspace / "archive.txt")
    report = await index.index()

    assert report.indexed == 1
    assert report.removed == 1
    assert index.store.count() == 1
    assert await index.catalog.known_paths() == ["archive.txt"]


async def test_search_never_cites_a_file_that_is_gone(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, _parser, workspace = indexer
    _write(workspace, "a.txt")
    _write(workspace, "b.txt")
    await index.index()
    (workspace / "a.txt").unlink()
    await index.index()

    hits = await index.store.search("content", k=5)
    assert {h.path for h in hits} == {"b.txt"}


async def test_indexing_a_subfolder_does_not_prune_outside_it(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    # The dangerous half: `declaw index dossier/` must not wipe the index for
    # everything the user did not point at.
    index, _parser, workspace = indexer
    _write(workspace, "racine.txt")
    _write(workspace, "dossier/interne.txt")
    await index.index()
    assert index.store.count() == 2

    report = await index.index(workspace / "dossier")

    assert report.removed == 0
    assert sorted(await index.catalog.known_paths()) == ["dossier/interne.txt", "racine.txt"]
    assert index.store.count() == 2


async def test_a_subfolder_walk_still_prunes_inside_its_own_scope(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, _parser, workspace = indexer
    _write(workspace, "racine.txt")
    _write(workspace, "dossier/interne.txt")
    await index.index()

    (workspace / "dossier" / "interne.txt").unlink()
    report = await index.index(workspace / "dossier")

    assert report.removed == 1
    assert await index.catalog.known_paths() == ["racine.txt"]


async def test_nothing_is_pruned_when_nothing_changed(
    indexer: tuple[DocumentIndexer, FakeParser, Path],
) -> None:
    index, _parser, workspace = indexer
    _write(workspace, "a.txt")
    await index.index()
    report = await index.index()
    assert report.removed == 0
    assert report.skipped == 1
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_documents_indexer.py -q`
Expected: FAIL — `AttributeError: 'IndexReport' object has no attribute 'removed'`

- [ ] **Step 3: Add `removed` to the report**

In `declaw/documents/indexer.py`:

```python
@dataclass(slots=True)
class IndexReport:
    """What one indexing run did."""

    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    removed: int = 0
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Add the reconciliation pass**

In `DocumentIndexer.index()`, after the per-file loop and before `return report`:

```python
        await self._reconcile(root, candidates, report)
        return report

    async def _reconcile(
        self, root: Path, seen: list[Path], report: IndexReport
    ) -> None:
        """Forget documents whose files are no longer on disk.

        Without this the index never forgets: a rename doubles the document, a
        delete leaves it, and search cites files that do not exist. For a
        product sold on GDPR grounds, continuing to quote a document the user
        deleted is the wrong failure to have.

        Scope matters. `declaw index dossier/` walks one subfolder, so only
        catalog entries UNDER THAT SUBFOLDER may be pruned — comparing against
        the whole catalog would delete the index for everything the user did
        not point at.
        """
        try:
            scope = root.relative_to(self.workspace).as_posix()
        except ValueError:
            return
        prefix = "" if scope in {"", "."} else f"{scope}/"

        present = {path.relative_to(self.workspace).as_posix() for path in seen}
        for known in await self.catalog.known_paths():
            if not known.startswith(prefix):
                continue  # outside the walked subtree: not ours to prune
            if known in present:
                continue
            self.store.delete_document(document_id(known))
            await self.catalog.forget(known)
            report.removed += 1
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_documents_indexer.py -q`
Expected: PASS (12 existing + 6 new)

If `test_indexing_a_subfolder_does_not_prune_outside_it` fails, the prefix
check is wrong — that test is the whole reason the scope logic exists.

- [ ] **Step 6: Report it in the CLI**

In `declaw/main.py`, in the `index` command, change the summary line:

```python
        console.print(
            f"[green]Indexed {report.indexed}[/green], skipped {report.skipped} unchanged, "
            f"removed {report.removed} no longer on disk, {report.failed} failed."
        )
```

- [ ] **Step 7: Verify the original defect is gone**

Re-run the exact reproduction from the spec:

```bash
uv run python - <<'EOF'
import asyncio, tempfile, shutil, os
from pathlib import Path
from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.documents.catalog import DocumentCatalog
from declaw.documents.indexer import DocumentIndexer
from declaw.documents.store import DocumentStore
from declaw.memory.chroma import build_chroma_client, get_collection

async def embed(texts): return [[float(len(t)), 1.0] for t in texts]
async def fake_parse(path):
    return {"doc_type": "text", "page_count": 1, "truncated": False,
            "chunks": [{"text": f"content of {Path(path).name}", "ordinal": 0,
                        "page": 1, "page_end": 1, "sheet": None, "heading": None}]}

async def main():
    tmp = Path(tempfile.mkdtemp()); ws = tmp / "workspace"; ws.mkdir()
    os.environ["DECLAW_WORKSPACE_DIR"] = str(ws)
    from declaw.config import get_settings; get_settings.cache_clear()
    engine = build_engine(tmp / "t.db"); await ensure_schema(engine)
    store = DocumentStore(get_collection(build_chroma_client(tmp / "chroma"), "documents"), embed)
    catalog = DocumentCatalog(build_sessionmaker(engine))
    idx = DocumentIndexer(parse=fake_parse, store=store, catalog=catalog, workspace=ws)
    (ws / "contrat.txt").write_text("hello", encoding="utf-8")
    await idx.index()
    (ws / "contrat.txt").rename(ws / "archive-contrat.txt"); await idx.index()
    print(f"after RENAME: chunks={store.count()} catalog={await catalog.known_paths()}")
    (ws / "archive-contrat.txt").unlink(); await idx.index()
    print(f"after DELETE: chunks={store.count()} catalog={await catalog.known_paths()}")
    print("search cites:", [h.path for h in await store.search('contrat', k=5)])
    await engine.dispose(); shutil.rmtree(tmp, ignore_errors=True)

asyncio.run(main())
EOF
```

Expected now: `after RENAME: chunks=1 catalog=['archive-contrat.txt']`,
`after DELETE: chunks=0 catalog=[]`, `search cites: []`.

- [ ] **Step 8: Typecheck, lint, commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/documents/indexer.py declaw/main.py tests/unit/test_documents_indexer.py
git commit -m "fix(DCL-114): the document index must forget renamed and deleted files

Phase 8a shipped an index that never forgets. A rename doubled the
document, a delete left it, and search then cited paths that no longer
existed -- so a user who deleted a client file kept seeing it quoted.
For a product sold on GDPR grounds that is a right-to-erasure problem.

Reconciliation is scoped to the walked subtree: indexing one subfolder
must not prune the index for everything outside it."
```

---

### Task 2: The `confirmation_preview` hook

**Files:**
- Modify: `declaw/tools/base.py`
- Modify: `declaw/brain/repl.py`
- Test: `tests/unit/test_tools_base.py` (extend), `tests/unit/test_repl.py` (extend)

**Interfaces:**
- Consumes: `DeclawTool`, `make_console_confirmation_provider`
- Produces: `DeclawTool.confirmation_preview(args: dict[str, Any]) -> str | None`, default `None`; the console provider uses it when present

**Why:** the approval question is rendered in `make_console_confirmation_provider`
as `tool.name(key=value, ...)`. A thirty-move plan renders as an unreadable
blob, and an unreadable prompt trains people to click through — the exact habit
the gate exists to prevent.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_tools_base.py`:

```python
def test_confirmation_preview_defaults_to_none() -> None:
    # Existing tools must be completely unaffected.
    from declaw.tools.builtin.filesystem import FilesystemWriteTool

    assert FilesystemWriteTool().confirmation_preview({"path": "a.txt"}) is None


def test_a_tool_can_override_the_preview() -> None:
    from typing import Any

    from pydantic import BaseModel

    from declaw.tools.base import DeclawTool, ToolClass

    class Args(BaseModel):
        count: int

    class PreviewTool(DeclawTool[Args]):
        name: str = "preview_tool"
        description_en: str = "x"
        description_fr: str = "x"
        classification: ToolClass = ToolClass.WRITE
        args_schema: type[Args] = Args

        def confirmation_preview(self, args: dict[str, Any]) -> str | None:
            return f"Move {args['count']} files"

        async def _arun(self, args: Args) -> str:
            return "done"

    assert PreviewTool().confirmation_preview({"count": 12}) == "Move 12 files"
```

Append to `tests/unit/test_repl.py`:

```python
async def test_the_prompt_uses_a_tools_preview_when_it_has_one() -> None:
    from typing import Any

    from pydantic import BaseModel

    from declaw.brain.repl import make_console_confirmation_provider
    from declaw.tools.base import DeclawTool, ToolClass

    class Args(BaseModel):
        count: int

    class PreviewTool(DeclawTool[Args]):
        name: str = "organize_files"
        description_en: str = "x"
        description_fr: str = "x"
        classification: ToolClass = ToolClass.WRITE
        args_schema: type[Args] = Args

        def confirmation_preview(self, args: dict[str, Any]) -> str | None:
            return "Move 12 files:\n  a.pdf -> ACME/a.pdf"

        async def _arun(self, args: Args) -> str:
            return "done"

    asked: list[str] = []

    def prompt(question: str) -> str:
        asked.append(question)
        return "y"

    approve = make_console_confirmation_provider(prompt, "en")
    assert await approve(PreviewTool(), {"count": 12}) is True
    assert "Move 12 files" in asked[0]
    assert "a.pdf -> ACME/a.pdf" in asked[0]
    assert "[y/N]" in asked[0]


async def test_tools_without_a_preview_keep_the_old_prompt() -> None:
    from declaw.brain.repl import make_console_confirmation_provider
    from declaw.tools.builtin.filesystem import FilesystemWriteTool

    asked: list[str] = []

    def prompt(question: str) -> str:
        asked.append(question)
        return "n"

    approve = make_console_confirmation_provider(prompt, "en")
    await approve(FilesystemWriteTool(), {"path": "a.txt", "content": "x"})
    assert "filesystem_write(" in asked[0]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_tools_base.py tests/unit/test_repl.py -q`
Expected: FAIL — `AttributeError: 'FilesystemWriteTool' object has no attribute 'confirmation_preview'`

- [ ] **Step 3: Add the hook to `DeclawTool`**

In `declaw/tools/base.py`, inside the class:

```python
    def confirmation_preview(self, args: dict[str, Any]) -> str | None:
        """Human-readable approval text, or ``None`` for the default rendering.

        The default prompt renders ``tool.name(key=value, ...)``, which is fine
        for a two-argument write and unreadable for a thirty-move plan. An
        unreadable approval prompt trains people to click through, which is the
        one habit the confirmation gate exists to prevent — so a tool whose
        arguments are a *plan* renders its own summary instead.
        """
        return None
```

- [ ] **Step 4: Use it in the console provider**

In `declaw/brain/repl.py`, inside `make_console_confirmation_provider`, replace
the body of the inner `question` function:

```python
    def question(tool: DeclawTool[Any], args: dict[str, Any]) -> str:
        preview = tool.confirmation_preview(args)
        if preview is not None:
            if language == "fr":
                return f"{preview}\nAutoriser ? [y/N] "
            return f"{preview}\nAllow? [y/N] "
        rendered = ", ".join(f"{key}={value!r}" for key, value in args.items())
        if language == "fr":
            return f"DeClaw veut appeler {tool.name}({rendered}). Autoriser ? [y/N] "
        return f"DeClaw wants to call {tool.name}({rendered}). Allow? [y/N] "
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_tools_base.py tests/unit/test_repl.py -q`
Expected: PASS — including every pre-existing test, since the default is `None`.

- [ ] **Step 6: Typecheck, lint, commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/tools/base.py declaw/brain/repl.py tests/unit/test_tools_base.py tests/unit/test_repl.py
git commit -m "feat(DCL-116): optional confirmation_preview so a plan can render its own approval"
```

---

### Task 3: `organize_files`

**Files:**
- Create: `declaw/documents/actions.py`
- Test: `tests/unit/test_documents_actions.py`

**Interfaces:**
- Consumes: `resolve_in_workspace`, `WorkspacePathError` (`declaw/tools/builtin/_paths.py`); `DeclawTool`, `ToolClass`; `confirmation_preview` (Task 2)
- Produces: `FileMove(source, destination)`, `OrganizeArgs(moves)`, `OrganizeFilesTool` (name `organize_files`, WRITE)

**Validate-all-then-execute.** A plan that fails validation is refused whole,
with the offending entry named. Half-executing a reorganisation is how a user
loses track of their own files.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_documents_actions.py`:

```python
"""Multi-file organisation: one plan, one approval, all-or-nothing validation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from declaw.documents.actions import OrganizeFilesTool
from declaw.tools.base import ToolClass


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "workspace"
    target.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(target))
    from declaw.config import get_settings

    get_settings.cache_clear()
    yield target
    get_settings.cache_clear()


def _write(workspace: Path, name: str) -> Path:
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("contenu", encoding="utf-8")
    return path


def _run(moves: list[dict[str, str]]) -> str:
    return asyncio.run(OrganizeFilesTool().run_validated({"moves": moves}))


def test_the_tool_is_write_class_so_it_is_gated() -> None:
    assert OrganizeFilesTool().classification is ToolClass.WRITE


def test_a_plan_moves_every_file(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    _write(workspace, "b.pdf")
    result = _run(
        [
            {"source": "a.pdf", "destination": "ACME/a.pdf"},
            {"source": "b.pdf", "destination": "ACME/b.pdf"},
        ]
    )
    assert (workspace / "ACME" / "a.pdf").is_file()
    assert (workspace / "ACME" / "b.pdf").is_file()
    assert not (workspace / "a.pdf").exists()
    assert "2" in result


def test_destination_folders_are_created(workspace: Path) -> None:
    # 'create folder structure' is the other half of DCL-116.
    _write(workspace, "facture.pdf")
    _run([{"source": "facture.pdf", "destination": "factures/2024/ACME/facture.pdf"}])
    assert (workspace / "factures" / "2024" / "ACME" / "facture.pdf").is_file()


def test_a_missing_source_refuses_the_whole_plan(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    with pytest.raises(ValueError) as excinfo:
        _run(
            [
                {"source": "a.pdf", "destination": "ACME/a.pdf"},
                {"source": "ghost.pdf", "destination": "ACME/ghost.pdf"},
            ]
        )
    assert "ghost.pdf" in str(excinfo.value)
    # Nothing was moved: the good entry must not have been executed either.
    assert (workspace / "a.pdf").is_file()
    assert not (workspace / "ACME").exists()


def test_an_existing_destination_refuses_the_whole_plan(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    _write(workspace, "ACME/a.pdf")
    with pytest.raises(ValueError) as excinfo:
        _run([{"source": "a.pdf", "destination": "ACME/a.pdf"}])
    assert "ACME/a.pdf" in str(excinfo.value)
    assert (workspace / "a.pdf").is_file()


def test_two_moves_onto_the_same_destination_are_refused(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    _write(workspace, "b.pdf")
    with pytest.raises(ValueError) as excinfo:
        _run(
            [
                {"source": "a.pdf", "destination": "ACME/x.pdf"},
                {"source": "b.pdf", "destination": "ACME/x.pdf"},
            ]
        )
    assert "ACME/x.pdf" in str(excinfo.value)
    assert (workspace / "a.pdf").is_file() and (workspace / "b.pdf").is_file()


def test_a_path_outside_the_workspace_is_refused(workspace: Path) -> None:
    _write(workspace, "a.pdf")
    with pytest.raises(ValueError):
        _run([{"source": "a.pdf", "destination": "../escape.pdf"}])
    assert (workspace / "a.pdf").is_file()


def test_an_empty_plan_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        asyncio.run(OrganizeFilesTool().run_validated({"moves": []}))


def test_the_preview_lists_the_moves_readably(workspace: Path) -> None:
    preview = OrganizeFilesTool().confirmation_preview(
        {"moves": [{"source": "a.pdf", "destination": "ACME/a.pdf"}]}
    )
    assert preview is not None
    assert "a.pdf" in preview and "ACME/a.pdf" in preview
    assert "1" in preview


def test_a_long_plan_is_summarised_not_dumped(workspace: Path) -> None:
    # Thirty raw lines in a terminal prompt is how people learn to press 'y'
    # without reading.
    moves = [{"source": f"f{i}.pdf", "destination": f"ACME/f{i}.pdf"} for i in range(30)]
    preview = OrganizeFilesTool().confirmation_preview({"moves": moves})
    assert preview is not None
    assert "30" in preview
    assert preview.count("\n") < 15
    assert "more" in preview.lower()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_documents_actions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.documents.actions'`

- [ ] **Step 3: Write the tool**

Create `declaw/documents/actions.py`:

```python
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
            source = entry["source"] if isinstance(entry, dict) else entry.source
            destination = entry["destination"] if isinstance(entry, dict) else entry.destination
            lines.append(f"  {source} -> {destination}")
        if len(raw) > _PREVIEW_LINES:
            lines.append(f"  ... {len(raw) - _PREVIEW_LINES} more")
        return "\n".join(lines)

    async def _arun(self, args: OrganizeArgs) -> str:
        resolved: list[tuple[Path, Path, FileMove]] = []
        claimed: set[Path] = set()

        # Validate everything first. One bad entry refuses the whole plan.
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_documents_actions.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Typecheck, lint, commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/documents/actions.py tests/unit/test_documents_actions.py
git commit -m "feat(DCL-116): organize_files with whole-plan validation and a readable approval"
```

---

### Task 4: `document_summarize`

**Files:**
- Modify: `declaw/documents/actions.py`
- Test: `tests/unit/test_documents_actions.py` (extend)

**Interfaces:**
- Consumes: `search_documents`, `ChunkSanitizer`, `SearchableStore` (Task 8a); `format_source`; `resolve_in_workspace`
- Produces: `SummarizeArgs(query, summary, path="summary.md", overwrite=False)`, `build_document_summarize_tool(*, store, chunk_sanitizer, language) -> DocumentSummarizeTool`

**The rule that carries over from DCL-062:** never let the model invent the
citation. The model supplies the prose; **the tool re-runs the retrieval itself**
and builds the sources block from real metadata.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_documents_actions.py`:

```python
from declaw.documents.models import SearchHit
from declaw.documents.search import ChunkSanitizer


class _Store:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.queries: list[str] = []

    async def search(self, query: str, *, k: int = 5) -> list[SearchHit]:
        self.queries.append(query)
        return self._hits[:k]


def _hit(path: str, page: int | None = 3) -> SearchHit:
    return SearchHit(
        chunk_id=f"{path}:0",
        doc_id=path,
        path=path,
        text=f"clause from {path}",
        ordinal=0,
        distance=0.1,
        page=page,
        page_end=page,
    )


def _summarize_tool(hits: list[SearchHit], language: str = "en"):
    from declaw.documents.actions import build_document_summarize_tool

    store = _Store(hits)
    tool = build_document_summarize_tool(
        store=store, chunk_sanitizer=ChunkSanitizer(None), language=language
    )
    return tool, store


def test_the_summary_file_is_written(workspace: Path) -> None:
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    asyncio.run(
        tool.run_validated({"query": "resiliation", "summary": "Le preavis est de trois mois."})
    )
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "Le preavis est de trois mois." in written


def test_sources_come_from_retrieval_not_from_the_model(workspace: Path) -> None:
    # The rule that survives from DCL-062: the model never invents a citation.
    tool, store = _summarize_tool([_hit("contrat.pdf", page=12)])
    asyncio.run(
        tool.run_validated(
            {
                "query": "resiliation",
                "summary": "According to invented-source.pdf page 99, ...",
            }
        )
    )
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "contrat.pdf p.12" in written
    assert store.queries == ["resiliation"]
    # The model's invented citation is in its prose but never in the sources block.
    sources_block = written.split("Sources")[1]
    assert "invented-source.pdf" not in sources_block


def test_the_file_declares_that_a_model_wrote_it(workspace: Path) -> None:
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    asyncio.run(tool.run_validated({"query": "q", "summary": "resume"}))
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "AI" in written or "IA" in written
    assert "verify" in written.lower()


def test_the_french_summary_is_in_french(workspace: Path) -> None:
    tool, _store = _summarize_tool([_hit("contrat.pdf")], language="fr")
    asyncio.run(tool.run_validated({"query": "q", "summary": "resume"}))
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "IA" in written
    assert "Sources" in written


def test_it_refuses_to_overwrite_by_default(workspace: Path) -> None:
    (workspace / "summary.md").write_text("existing work", encoding="utf-8")
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    with pytest.raises(ValueError):
        asyncio.run(tool.run_validated({"query": "q", "summary": "new"}))
    assert (workspace / "summary.md").read_text(encoding="utf-8") == "existing work"


def test_overwrite_is_possible_when_asked(workspace: Path) -> None:
    (workspace / "summary.md").write_text("existing", encoding="utf-8")
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    asyncio.run(
        tool.run_validated({"query": "q", "summary": "new", "overwrite": True})
    )
    assert "new" in (workspace / "summary.md").read_text(encoding="utf-8")


def test_a_path_outside_the_workspace_is_refused(workspace: Path) -> None:
    tool, _store = _summarize_tool([_hit("contrat.pdf")])
    with pytest.raises(ValueError):
        asyncio.run(
            tool.run_validated({"query": "q", "summary": "s", "path": "../escape.md"})
        )


def test_a_summary_with_no_matching_documents_still_writes_but_says_so(
    workspace: Path,
) -> None:
    tool, _store = _summarize_tool([])
    asyncio.run(tool.run_validated({"query": "q", "summary": "resume"}))
    written = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "resume" in written


def test_the_tool_is_write_class_so_it_is_gated(workspace: Path) -> None:
    tool, _store = _summarize_tool([])
    assert tool.classification is ToolClass.WRITE
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_documents_actions.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_document_summarize_tool'`

- [ ] **Step 3: Write the tool**

Append to `declaw/documents/actions.py`:

```python
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
            "ci-dessous. Elle peut se tromper — vérifiez les sources avant de "
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
    """Wire retrieval into the summarize tool so citations cannot be invented."""
    strings = _SUMMARY_STRINGS[language]

    async def build_document(args: SummarizeArgs) -> str:
        target = resolve_in_workspace(args.path)
        if target.exists() and not args.overwrite:
            raise ValueError(
                f"{args.path!r} already exists. Pass overwrite=true to replace it."
            )
        if not target.parent.is_dir():
            raise FileNotFoundError(f"Folder for {args.path!r} does not exist.")

        # The tool does its own retrieval: the sources block is built from real
        # metadata, never from anything the model typed.
        outcome = await search_documents(store, chunk_sanitizer, args.query)
        sources = [format_source(hit) for hit in outcome.hits]

        body = [strings["heading"], "", args.summary.strip(), "", strings["provenance"], ""]
        body.append(strings["sources"])
        if sources:
            seen: list[str] = []
            for source in sources:
                if source not in seen:
                    seen.append(source)
            body.extend(f"- {source}" for source in seen)
        else:
            body.append(strings["none"])

        target.write_text("\n".join(body) + "\n", encoding="utf-8")
        return strings["written"].format(path=args.path, count=len(sources))

    return DocumentSummarizeTool(build_document=build_document)
```

Add these imports at the top of `actions.py`:

```python
from collections.abc import Awaitable, Callable

from declaw.config import Language
from declaw.documents.citations import format_source
from declaw.documents.search import ChunkSanitizer, SearchableStore, search_documents
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_documents_actions.py -q`
Expected: PASS (10 organize + 9 summarize)

- [ ] **Step 5: Register both tools in chat**

In `declaw/main.py`, inside `_session()` where `document_search` is registered,
add the two actions in the same `if` block:

```python
            from declaw.documents.actions import (
                OrganizeFilesTool,
                build_document_summarize_tool,
            )

            registry.register_instance(OrganizeFilesTool())
            registry.register_instance(
                build_document_summarize_tool(
                    store=stack.store,
                    chunk_sanitizer=stack.chunk_sanitizer,
                    language=settings.language,
                )
            )
```

- [ ] **Step 6: Typecheck, lint, commit**

```bash
uv run pytest -q
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/documents/actions.py declaw/main.py tests/unit/test_documents_actions.py
git commit -m "feat(DCL-113): document_summarize with sources DeClaw looks up itself

The model writes the prose; the tool re-runs retrieval and builds the
sources block from real metadata, so a citation cannot be invented --
the rule that survives from DCL-062. The file carries an explicit
provenance line in EN and FR."
```

---

### Task 5: Move and rename, verified end to end

**Files:**
- Test: `tests/integration/test_document_actions_e2e.py`

**Interfaces:**
- Consumes: `default_registry`, `FilesystemMoveTool`, `OrganizeFilesTool` (Task 3), `DocumentIndexer` (Task 1)
- Produces: nothing — this task proves DCL-114 and DCL-115 rather than building them

**Why there is no new tool here.** `FilesystemMoveTool` already moves *and*
renames, is WRITE-class so already gated, refuses to overwrite without an
explicit flag, and is already wired into chat. Both tickets name DCL-023 as
their dependency. A second move tool would duplicate it and give a 3B model two
confusable names.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_document_actions_e2e.py`:

```python
"""DCL-114 / DCL-115: move and rename go through the gate, and the index follows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from declaw.db.engine import build_engine, build_sessionmaker, ensure_schema
from declaw.documents.catalog import DocumentCatalog
from declaw.documents.indexer import DocumentIndexer
from declaw.documents.store import DocumentStore
from declaw.memory.chroma import build_chroma_client, get_collection
from declaw.tools.base import DeclawTool
from declaw.tools.registry import ToolRegistry


async def _embed(texts: list[str]) -> list[list[float]]:
    return [[float(len(t)), 1.0] for t in texts]


async def _parse(path: str) -> dict[str, Any]:
    return {
        "doc_type": "text",
        "page_count": 1,
        "truncated": False,
        "chunks": [
            {
                "text": f"content of {Path(path).name}",
                "ordinal": 0,
                "page": 1,
                "page_end": 1,
                "sheet": None,
                "heading": None,
            }
        ],
    }


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "workspace"
    target.mkdir()
    monkeypatch.setenv("DECLAW_WORKSPACE_DIR", str(target))
    from declaw.config import get_settings

    get_settings.cache_clear()
    yield target
    get_settings.cache_clear()


async def _indexer(tmp_path: Path, workspace: Path) -> DocumentIndexer:
    engine = build_engine(tmp_path / "t.db")
    await ensure_schema(engine)
    collection = get_collection(build_chroma_client(tmp_path / "chroma"), "documents")
    return DocumentIndexer(
        parse=_parse,
        store=DocumentStore(collection, _embed),
        catalog=DocumentCatalog(build_sessionmaker(engine)),
        workspace=workspace,
    )


def _move_tool(decisions: list[bool], asked: list[str]) -> Any:
    """Build the real filesystem_move tool behind a scripted confirmation gate."""
    from declaw.tools.registry import default_registry

    async def approve(tool: DeclawTool[Any], args: dict[str, Any]) -> bool:
        asked.append(tool.name)
        return decisions.pop(0)

    tools = default_registry().langchain_tools("en", approve)
    return next(t for t in tools if t.name == "filesystem_move")


async def test_a_rename_requires_confirmation_and_happens(
    tmp_path: Path, workspace: Path
) -> None:
    # DCL-115: rename is a move within the same folder.
    (workspace / "brouillon.txt").write_text("x", encoding="utf-8")
    asked: list[str] = []
    tool = _move_tool([True], asked)

    await tool.ainvoke({"source": "brouillon.txt", "destination": "contrat-final.txt"})

    assert asked == ["filesystem_move"]
    assert (workspace / "contrat-final.txt").is_file()
    assert not (workspace / "brouillon.txt").exists()


async def test_a_denied_move_changes_nothing(tmp_path: Path, workspace: Path) -> None:
    # DCL-114's acceptance: no move without explicit confirmation.
    (workspace / "a.txt").write_text("x", encoding="utf-8")
    asked: list[str] = []
    tool = _move_tool([False], asked)

    result = await tool.ainvoke({"source": "a.txt", "destination": "dossier/a.txt"})

    assert asked == ["filesystem_move"]
    assert "denied" in result.lower()
    assert (workspace / "a.txt").is_file()
    assert not (workspace / "dossier").exists()


async def test_the_index_follows_a_rename(tmp_path: Path, workspace: Path) -> None:
    # The whole reason these tickets matter: the citation must track the file.
    (workspace / "contrat.txt").write_text("x", encoding="utf-8")
    index = await _indexer(tmp_path, workspace)
    await index.index()
    assert [h.path for h in await index.store.search("content", k=5)] == ["contrat.txt"]

    (workspace / "contrat.txt").rename(workspace / "contrat-2024.txt")
    await index.index()

    assert [h.path for h in await index.store.search("content", k=5)] == ["contrat-2024.txt"]


async def test_organize_then_reindex_leaves_one_entry_per_file(
    tmp_path: Path, workspace: Path
) -> None:
    from declaw.documents.actions import OrganizeFilesTool

    for name in ("f1.txt", "f2.txt"):
        (workspace / name).write_text("x", encoding="utf-8")
    index = await _indexer(tmp_path, workspace)
    await index.index()
    assert index.store.count() == 2

    await OrganizeFilesTool().run_validated(
        {
            "moves": [
                {"source": "f1.txt", "destination": "ACME/f1.txt"},
                {"source": "f2.txt", "destination": "ACME/f2.txt"},
            ]
        }
    )
    report = await index.index()

    assert report.removed == 2
    assert index.store.count() == 2
    assert sorted(await index.catalog.known_paths()) == ["ACME/f1.txt", "ACME/f2.txt"]
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/integration/test_document_actions_e2e.py -q`
Expected: PASS (4 tests)

- [ ] **Step 3: Mark the tickets and commit**

```bash
uv run pytest -q
uv run ruff check
git add tests/integration/test_document_actions_e2e.py
git commit -m "test(DCL-114,DCL-115): verify move and rename through the confirmation gate

No new tool: FilesystemMoveTool already moves AND renames, is
WRITE-class so already gated, and both tickets name DCL-023 as their
dependency. What was missing was proof that the index follows the
file, which is now covered."
```

---

### Task 6: The benchmark harness

**Files:**
- Create: `declaw/documents/benchmark.py`
- Test: `tests/unit/test_documents_benchmark.py`

**Interfaces:**
- Consumes: `SearchHit`
- Produces: `BenchmarkQuestion(question, expected_path, expected_snippet, language)`, `QuestionResult(question, rank)`, `BenchmarkReport` with `recall_at_1`, `recall_at_5`, `mrr`, `misses`; `run_benchmark(retrieve, questions) -> BenchmarkReport`; `DIVERGENCE_WARNING_POINTS = 5.0`

**What is measured and why.** Retrieval, not answer quality — the model's prose
would swamp the signal and a 3B model's phrasing is already a known variable.
A question is "hit" when the expected document appears in the top-k **and** the
retrieved text contains the expected snippet, so matching the right file for
the wrong reason does not count.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_documents_benchmark.py`:

```python
"""Recall and MRR arithmetic, with a fake retriever so the numbers are exact."""

from __future__ import annotations

from declaw.documents.benchmark import (
    DIVERGENCE_WARNING_POINTS,
    BenchmarkQuestion,
    run_benchmark,
)
from declaw.documents.models import SearchHit


def _hit(path: str, text: str) -> SearchHit:
    return SearchHit(
        chunk_id=f"{path}:0", doc_id=path, path=path, text=text, ordinal=0, distance=0.1
    )


def _question(path: str = "contrat.pdf", snippet: str = "preavis") -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question="Quel est le preavis ?",
        expected_path=path,
        expected_snippet=snippet,
        language="fr",
    )


def _retriever(results: dict[str, list[SearchHit]]):
    async def retrieve(question: str, *, k: int = 5) -> list[SearchHit]:
        return results.get(question, [])[:k]

    return retrieve


async def test_a_first_place_hit_scores_perfectly() -> None:
    question = _question()
    report = await run_benchmark(
        _retriever({question.question: [_hit("contrat.pdf", "le preavis est de trois mois")]}),
        [question],
    )
    assert report.recall_at_1 == 1.0
    assert report.recall_at_5 == 1.0
    assert report.mrr == 1.0
    assert report.misses == []


async def test_a_third_place_hit_counts_for_recall_at_5_not_at_1() -> None:
    question = _question()
    hits = [
        _hit("autre.pdf", "sans rapport"),
        _hit("encore.pdf", "sans rapport"),
        _hit("contrat.pdf", "le preavis est de trois mois"),
    ]
    report = await run_benchmark(_retriever({question.question: hits}), [question])
    assert report.recall_at_1 == 0.0
    assert report.recall_at_5 == 1.0
    assert report.mrr == 1 / 3


async def test_the_right_file_with_the_wrong_passage_is_not_a_hit() -> None:
    # Matching the document for the wrong reason must not score.
    question = _question(snippet="preavis")
    hits = [_hit("contrat.pdf", "clause de confidentialite")]
    report = await run_benchmark(_retriever({question.question: hits}), [question])
    assert report.recall_at_5 == 0.0
    assert report.misses == [question.question]


async def test_snippet_matching_ignores_case_and_accents() -> None:
    question = _question(snippet="préavis")
    hits = [_hit("contrat.pdf", "LE PREAVIS EST DE TROIS MOIS")]
    report = await run_benchmark(_retriever({question.question: hits}), [question])
    assert report.recall_at_5 == 1.0


async def test_no_results_is_a_miss_not_a_crash() -> None:
    question = _question()
    report = await run_benchmark(_retriever({}), [question])
    assert report.recall_at_5 == 0.0
    assert report.mrr == 0.0
    assert report.misses == [question.question]


async def test_scores_average_across_questions() -> None:
    first = BenchmarkQuestion("A?", "a.pdf", "alpha", "fr")
    second = BenchmarkQuestion("B?", "b.pdf", "beta", "fr")
    report = await run_benchmark(
        _retriever(
            {
                "A?": [_hit("a.pdf", "alpha here")],
                "B?": [_hit("wrong.pdf", "nothing")],
            }
        ),
        [first, second],
    )
    assert report.recall_at_5 == 0.5
    assert report.mrr == 0.5
    assert report.misses == ["B?"]


async def test_an_empty_question_set_scores_zero_without_dividing_by_zero() -> None:
    report = await run_benchmark(_retriever({}), [])
    assert report.recall_at_5 == 0.0
    assert report.total == 0


def test_the_divergence_threshold_is_five_points() -> None:
    # Same shape as the sanitizer benchmark's seen-vs-unseen warning.
    assert DIVERGENCE_WARNING_POINTS == 5.0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_documents_benchmark.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.documents.benchmark'`

- [ ] **Step 3: Write the harness**

Create `declaw/documents/benchmark.py`:

```python
"""Measure retrieval quality: does the right passage come back, and how high?

Retrieval, not answer quality. A 3B model's phrasing is a known and large
variable (Phase 1), and letting it into the measurement would swamp the signal
this is meant to produce.

A question counts as a hit only when the expected DOCUMENT appears in the top-k
AND the retrieved text contains the expected SNIPPET. Matching the right file
for the wrong reason is not a hit — otherwise a corpus of one document would
score perfectly.

Model-agnostic on purpose: ``run_benchmark`` takes a retrieve callable, so the
unit tests use a fake and the live runner passes the real store.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from declaw.documents.models import SearchHit

DEFAULT_K = 5
# Warn when the development and held-out scores diverge by more than this.
# Same shape as the sanitizer benchmark's seen-vs-unseen warning, and for the
# same reason: a self-authored corpus grades its own homework.
DIVERGENCE_WARNING_POINTS = 5.0

Retriever = Callable[..., Awaitable[list[SearchHit]]]


@dataclass(frozen=True, slots=True)
class BenchmarkQuestion:
    """One question with the passage that should answer it."""

    question: str
    expected_path: str
    expected_snippet: str
    language: str


@dataclass(frozen=True, slots=True)
class QuestionResult:
    """Where the expected passage landed. ``rank`` is 1-based, 0 means absent."""

    question: str
    rank: int


@dataclass(slots=True)
class BenchmarkReport:
    """Aggregate retrieval quality over one question set."""

    results: list[QuestionResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def recall_at_1(self) -> float:
        return self._recall(1)

    @property
    def recall_at_5(self) -> float:
        return self._recall(5)

    @property
    def mrr(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 / r.rank for r in self.results if r.rank > 0) / len(self.results)

    @property
    def misses(self) -> list[str]:
        return [r.question for r in self.results if r.rank == 0]

    def _recall(self, k: int) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if 0 < r.rank <= k) / len(self.results)


def _normalise(text: str) -> str:
    """Casefold and strip accents, so 'préavis' matches 'PREAVIS'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _rank_of(question: BenchmarkQuestion, hits: Sequence[SearchHit]) -> int:
    snippet = _normalise(question.expected_snippet)
    for position, hit in enumerate(hits, start=1):
        if hit.path != question.expected_path:
            continue
        if snippet in _normalise(hit.text):
            return position
    return 0


async def run_benchmark(
    retrieve: Retriever,
    questions: Sequence[BenchmarkQuestion],
    *,
    k: int = DEFAULT_K,
) -> BenchmarkReport:
    """Score ``questions`` against ``retrieve``."""
    report = BenchmarkReport()
    for question in questions:
        hits = await retrieve(question.question, k=k)
        report.results.append(
            QuestionResult(question=question.question, rank=_rank_of(question, hits))
        )
    return report
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_documents_benchmark.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Typecheck, lint, commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/documents/benchmark.py tests/unit/test_documents_benchmark.py
git commit -m "feat(DCL-117): retrieval benchmark harness measuring recall@k and MRR"
```

---

### Task 7: Corpora and the live runner

**Files:**
- Create: `declaw/documents/corpus/__init__.py`, `declaw/documents/corpus/synthetic.py`, `declaw/documents/corpus/heldout.py`
- Create: `tests/fixtures/documents/heldout/` (downloaded EUR-Lex PDFs + `ATTRIBUTION.md`)
- Create: `scripts/document_benchmark.py`
- Test: `tests/unit/test_documents_corpus.py`

**Interfaces:**
- Consumes: `BenchmarkQuestion` (Task 6)
- Produces: `SYNTHETIC_DOCUMENTS: tuple[SyntheticDocument, ...]`, `SYNTHETIC_QUESTIONS: tuple[BenchmarkQuestion, ...]`, `write_synthetic_corpus(folder) -> list[Path]`, `HELDOUT_QUESTIONS: tuple[BenchmarkQuestion, ...]`, `HELDOUT_DIR: Path`

**The rule, restated because it is the whole point:** the development set is
ours and the held-out set is not. **Never tune against an individual held-out
failure** — fix the concept and re-measure, or the held-out set silently
becomes a second training set. The sanitizer scored 91.7% on its own corpus and
53.3% on external data.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_documents_corpus.py`:

```python
"""Corpus integrity. The rules matter more than the contents."""

from __future__ import annotations

from pathlib import Path

from declaw.documents.corpus.heldout import HELDOUT_DIR, HELDOUT_QUESTIONS
from declaw.documents.corpus.synthetic import (
    SYNTHETIC_QUESTIONS,
    write_synthetic_corpus,
)


def test_the_development_set_has_at_least_ten_questions() -> None:
    # DCL-117 asks for 10+ sample contracts' worth of evaluation.
    assert len(SYNTHETIC_QUESTIONS) >= 10


def test_every_synthetic_question_is_answerable_from_a_generated_document(
    tmp_path: Path,
) -> None:
    # A question whose expected passage is not in the corpus scores zero
    # forever and looks like a retrieval failure. Catch it here instead.
    written = write_synthetic_corpus(tmp_path)
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in written if p.suffix != ".pdf")
    names = {p.name for p in written}
    for question in SYNTHETIC_QUESTIONS:
        assert question.expected_path in names, question.expected_path


def test_the_corpus_is_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    a = {p.name: p.read_bytes() for p in write_synthetic_corpus(first)}
    b = {p.name: p.read_bytes() for p in write_synthetic_corpus(second)}
    assert a.keys() == b.keys()


def test_the_development_set_is_french() -> None:
    assert all(q.language == "fr" for q in SYNTHETIC_QUESTIONS)


def test_the_heldout_set_exists_and_is_attributed() -> None:
    # External text with a recorded source is the only thing that makes the
    # held-out number mean anything.
    assert (HELDOUT_DIR / "ATTRIBUTION.md").is_file()
    text = (HELDOUT_DIR / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "eur-lex" in text.lower()
    assert "http" in text


def test_every_heldout_question_names_a_committed_file() -> None:
    for question in HELDOUT_QUESTIONS:
        assert (HELDOUT_DIR / question.expected_path).is_file(), question.expected_path


def test_no_heldout_question_text_appears_in_the_development_set() -> None:
    # If a held-out question leaked into the development set, the gap between
    # the two scores would stop meaning anything.
    development = {q.question.casefold() for q in SYNTHETIC_QUESTIONS}
    for question in HELDOUT_QUESTIONS:
        assert question.question.casefold() not in development
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_documents_corpus.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'declaw.documents.corpus'`

- [ ] **Step 3: Write the synthetic corpus**

Create `declaw/documents/corpus/__init__.py` (empty) and
`declaw/documents/corpus/synthetic.py`. Write **at least four documents** and
**at least ten questions**. Generate them into a folder with `fpdf2`,
`python-docx` and plain text so all three parsers are exercised. Each document
must contain the exact snippet its questions expect. Shape:

```python
"""The development question set: French business documents we wrote ourselves.

Deliberately self-authored, and therefore deliberately NOT the number that
matters. It is the set we may iterate against; `heldout.py` is the one we may
not. The sanitizer scored 91.7% on its own corpus and 53.3% on external data —
that 38-point gap is why these two files exist separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF

from declaw.documents.benchmark import BenchmarkQuestion


@dataclass(frozen=True, slots=True)
class SyntheticDocument:
    """One generated document: its filename and its paragraphs."""

    name: str
    paragraphs: tuple[str, ...]


SYNTHETIC_DOCUMENTS: tuple[SyntheticDocument, ...] = (
    SyntheticDocument(
        name="contrat-prestation.pdf",
        paragraphs=(
            "CONTRAT DE PRESTATION DE SERVICES",
            "Entre MARTIN CONSEIL, ci-apres le Prestataire, et DUPONT SARL, "
            "ci-apres le Client.",
            "ARTICLE 7 - RESILIATION",
            "Chaque partie peut resilier le present contrat moyennant un preavis "
            "de trois mois notifie par lettre recommandee.",
            "ARTICLE 8 - CONFIDENTIALITE",
            "Les parties gardent confidentielles les informations echangees "
            "pendant une duree de cinq ans apres la fin du contrat.",
            "ARTICLE 9 - LOI APPLICABLE",
            "Le present contrat est soumis au droit francais et tout litige "
            "releve du tribunal de commerce de Lyon.",
        ),
    ),
    SyntheticDocument(
        name="facture-2024-03.txt",
        paragraphs=(
            "FACTURE N 2024-03-017",
            "Emise le 15 mars 2024 par MARTIN CONSEIL a l'attention de DUPONT SARL.",
            "Prestation de conseil en organisation : 12000 euros HT.",
            "Formation des equipes : 3500 euros HT.",
            "Total a regler : 15500 euros HT, soit 18600 euros TTC.",
            "Le reglement intervient a trente jours fin de mois.",
        ),
    ),
    SyntheticDocument(
        name="compte-rendu-reunion.txt",
        paragraphs=(
            "COMPTE RENDU DE REUNION",
            "Reunion du 12 mars 2024, en presence de Madame Martin et Monsieur Dupont.",
            "Le budget formation est porte a 3500 euros pour l'exercice en cours.",
            "La prochaine revue de contrat est fixee au 30 juin 2024.",
            "Il est decide de reporter le recrutement du second consultant.",
        ),
    ),
    SyntheticDocument(
        name="lettre-resiliation.txt",
        paragraphs=(
            "Objet : resiliation du contrat de prestation",
            "Lyon, le 2 avril 2024",
            "Madame, Monsieur,",
            "Par la presente, nous vous informons de notre decision de resilier le "
            "contrat signe le 4 janvier 2023, conformement a son article 7.",
            "La resiliation prendra effet le 2 juillet 2024, au terme du preavis "
            "contractuel de trois mois.",
            "Nous restons a votre disposition pour organiser la transition.",
        ),
    ),
)

SYNTHETIC_QUESTIONS: tuple[BenchmarkQuestion, ...] = (
    BenchmarkQuestion(
        question="Quel est le delai de preavis pour resilier le contrat ?",
        expected_path="contrat-prestation.pdf",
        expected_snippet="preavis de trois mois",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Combien de temps dure l'obligation de confidentialite ?",
        expected_path="contrat-prestation.pdf",
        expected_snippet="duree de cinq ans",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel tribunal est competent en cas de litige ?",
        expected_path="contrat-prestation.pdf",
        expected_snippet="tribunal de commerce de Lyon",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Qui sont les parties au contrat de prestation ?",
        expected_path="contrat-prestation.pdf",
        expected_snippet="MARTIN CONSEIL",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel est le montant total de la facture de mars ?",
        expected_path="facture-2024-03.txt",
        expected_snippet="15500 euros HT",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Combien coute la prestation de conseil en organisation ?",
        expected_path="facture-2024-03.txt",
        expected_snippet="12000 euros HT",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quel est le delai de reglement de la facture ?",
        expected_path="facture-2024-03.txt",
        expected_snippet="trente jours fin de mois",
        language="fr",
    ),
    BenchmarkQuestion(
        question="A combien s'eleve le budget formation ?",
        expected_path="compte-rendu-reunion.txt",
        expected_snippet="3500 euros",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quand a lieu la prochaine revue de contrat ?",
        expected_path="compte-rendu-reunion.txt",
        expected_snippet="30 juin 2024",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Qui etait present a la reunion de mars ?",
        expected_path="compte-rendu-reunion.txt",
        expected_snippet="Madame Martin",
        language="fr",
    ),
    BenchmarkQuestion(
        question="A quelle date la resiliation prend-elle effet ?",
        expected_path="lettre-resiliation.txt",
        expected_snippet="2 juillet 2024",
        language="fr",
    ),
    BenchmarkQuestion(
        question="Quand le contrat resilie avait-il ete signe ?",
        expected_path="lettre-resiliation.txt",
        expected_snippet="4 janvier 2023",
        language="fr",
    ),
)


def write_synthetic_corpus(folder: Path) -> list[Path]:
    """Generate the development corpus into ``folder``. Reproducible."""
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for document in SYNTHETIC_DOCUMENTS:
        path = folder / document.name
        if path.suffix == ".pdf":
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.set_font("helvetica", size=12)
            pdf.add_page()
            for paragraph in document.paragraphs:
                # w=0 raises FPDFException; an explicit width is required.
                pdf.multi_cell(w=180, h=8, text=paragraph)
            path.write_bytes(bytes(pdf.output()))
        else:
            path.write_text("\n\n".join(document.paragraphs), encoding="utf-8")
        written.append(path)
    return written
```

That is four documents (PDF and text, so both parser paths are exercised) and
twelve questions spanning resiliation, amounts, dates, parties and obligations.
Every `expected_snippet` above appears verbatim in its document — the corpus
test in Step 1 fails if one does not.

- [ ] **Step 4: Download the held-out documents**

EUR-Lex publishes French legal texts as open data. Download **3-5 French PDFs**
into `tests/fixtures/documents/heldout/`, keeping them small (a few MB total).

Then write `tests/fixtures/documents/heldout/ATTRIBUTION.md` recording, for each
file: the source URL, the document title, the date retrieved, and the licence
(EUR-Lex content is reusable with source acknowledgement — state that).

**This is the only step in the plan that needs network access.** If it is
unavailable, stop and say so rather than substituting self-written documents:
a held-out set we authored is not a held-out set, and quietly making one would
destroy the only external measurement this phase produces.

- [ ] **Step 5: Write the held-out question set**

Create `declaw/documents/corpus/heldout.py`:

```python
"""The held-out question set: real EUR-Lex documents nobody here wrote.

TWO RULES, and they are the entire value of this file:

1. **Never quote these documents or questions in a prompt.** The moment their
   text appears in a prompt, the number stops measuring generalisation.
2. **Never tune against an individual failure here.** Fix the concept in the
   retrieval pipeline, then re-measure. Otherwise this silently becomes a
   second training set — which is exactly how the sanitizer ended up scoring
   91.7% on its own corpus and 53.3% on external data.

Questions are written by reading the documents; the DOCUMENTS are external and
unmodified, which is the property that matters.
"""

from __future__ import annotations

from pathlib import Path

from declaw.documents.benchmark import BenchmarkQuestion

HELDOUT_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "documents" / "heldout"

HELDOUT_QUESTIONS: tuple[BenchmarkQuestion, ...] = (
    # One entry per real question, expected_path matching a committed filename.
)
```

Fill in **at least 8 questions** across the downloaded documents.

- [ ] **Step 6: Write the live runner**

Create `scripts/document_benchmark.py`: index the synthetic corpus into a
temporary store, score `SYNTHETIC_QUESTIONS`, then do the same for the held-out
corpus and `HELDOUT_QUESTIONS`, and print both side by side:

```
development  recall@1 0.00  recall@5 0.00  MRR 0.00  (n=0)
held-out     recall@1 0.00  recall@5 0.00  MRR 0.00  (n=0)
```

When `recall@5` differs by more than `DIVERGENCE_WARNING_POINTS`, print a
warning naming the gap — the development number is the optimistic one, and
saying so in the output stops it being quoted alone.

Requires Ollama with `nomic-embed-text`; the script must say so and exit
non-zero if it is missing, reusing `check_embedding_model_pulled`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_documents_corpus.py -q`
Expected: PASS (7 tests)

- [ ] **Step 8: Run the benchmark live and record the numbers**

```bash
uv run python scripts/document_benchmark.py
```

Record both scores in `CLAUDE.md` **as measured facts**, including the gap. If
the held-out score is much worse than the development score, that is the
finding — write it down rather than adjusting the corpus until it looks better.

- [ ] **Step 9: Typecheck, lint, commit**

```bash
uv run mypy declaw declaw_plugin_sdk && uv run ruff check
git add declaw/documents/corpus/ scripts/document_benchmark.py tests/fixtures/documents/ tests/unit/test_documents_corpus.py
git commit -m "feat(DCL-117): French retrieval benchmark, synthetic development set vs EUR-Lex held-out"
```

---

### Task 8: Documentation

**Files:**
- Create: `docs/phase-8b-review.md`
- Modify: `CLAUDE.md`, `TICKETS.md`

- [ ] **Step 1: Run everything twice and collect real numbers**

```bash
uv run pytest -q
uv run pytest -q
uv run mypy declaw declaw_plugin_sdk
uv run ruff check
```

Both runs green with identical counts. Use these, not the plan's estimates.

- [ ] **Step 2: Write the phase review**

Create `docs/phase-8b-review.md` following `docs/phase-8a-review.md` — Vietnamese
onboarding guide, same section shape. It must cover:

- the index-never-forgets defect, its GDPR framing, and the scope subtlety in the fix
- why DCL-114/115 needed verification rather than new code
- why an LLM writes the summary while DCL-062's audit summaries are templates
- **the measured benchmark numbers, development and held-out, with the gap stated plainly**
- the honest limitations from the spec, in full

- [ ] **Step 3: Update TICKETS.md**

Mark DCL-113..117 `[x]`. Rewrite two acceptance criteria:

- **DCL-114**: "Verified end to end: the existing `filesystem_move` (DCL-023) moves and renames through the confirmation gate; a denied move changes nothing. The index now follows the file — before this phase a rename doubled the document and a delete left it, so search cited files that no longer existed."
- **DCL-115**: "Verified: the same tool renames; conflicts are refused without an explicit `overwrite`. No second tool was written — two confusable move tools is exactly what the Phase 1 probes showed a 3B model handles badly."

- [ ] **Step 4: Update CLAUDE.md**

- **Current state**: Phase 8b complete; **MVP DoD #4 closed**; next is Phase 9
- Add a **Phase 8b section** under Completed tickets
- **Notes for next session**: the reconciliation defect and its fix; the measured benchmark numbers with the development/held-out gap; that reconciliation only runs on `declaw index` until the Phase 9 gateway hosts the watcher
- Update **Last updated**

- [ ] **Step 5: Final verification and commit**

```bash
uv run pytest -q
uv run mypy declaw declaw_plugin_sdk
uv run ruff check
git add -A
git commit -m "docs(DCL-117): Phase 8b review, tickets, and living context"
```

Report the real numbers. If anything fails, fix it before committing.

---

## Notes for the executor

**Task 1 is the reason this phase exists.** It fixes a defect that is already
shipped and already user-visible. Do it first, and verify the reproduction from
Step 7 with your own eyes.

**Task 7 Step 4 needs network access** — the only step that does. If you cannot
download the EUR-Lex documents, stop and say so. Substituting self-written
documents would produce a held-out score that measures nothing, which is worse
than having no number at all.

**Do not weaken a test to make it pass.** If `test_indexing_a_subfolder_does_not_prune_outside_it`
fails, the prune scope is wrong — that test exists because getting it wrong
deletes the user's index.
