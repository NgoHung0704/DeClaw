# Phase 8b — actions, index reconciliation, and the quality benchmark

- **Date**: 2026-08-26
- **Status**: approved, ready for implementation planning
- **Tickets**: DCL-113..117, plus one unticketed defect that outranks all of them
- **Branch**: `feat/phase-8b-actions-benchmark` (from `feat/phase-7-plugin-host`)
- **Context**: `2026-08-23-phase-8a-doc-intel-design.md`, `2026-08-23-phase-7-9-roadmap.md`

## Goal

Finish MVP DoD #4 ("move/rename/summarize via natural language, with
confirmation"), make the document index tell the truth about what exists on
disk, and put a number on retrieval quality that is not self-graded.

## The defect that comes first

Phase 8a shipped an index that **never forgets**. Measured, not theorised:

```
after index:    chunks=1  catalog=['contrat.txt']
after RENAME:   chunks=2  catalog=['archive-contrat.txt', 'contrat.txt']
after DELETE:   chunks=2  catalog=['archive-contrat.txt', 'contrat.txt']

search returns 2 hits citing: ['contrat.txt', 'archive-contrat.txt']
files actually on disk: []
```

`DocumentIndexer.index()` walks the files that exist. A file that was renamed
or deleted is simply never visited, so nothing ever calls
`store.delete_document()` or `catalog.forget()`.

Three consequences, in increasing order of seriousness:

1. A rename **doubles** the document instead of moving it.
2. Citations point at paths that no longer exist, so a user who follows a
   citation finds nothing — which destroys the one property Phase 8a was built
   to guarantee.
3. **A deleted document keeps being quoted.** For a product sold to EU
   professionals on GDPR grounds, retaining and surfacing the contents of a file
   the user deleted is the wrong failure to have. It is a right-to-erasure
   problem, not a staleness problem.

This is why DCL-114/115 are worth doing even though the *tools* already exist:
the tickets point at exactly the operation that exposes it.

## Non-goals

- A new move or rename tool. See below — one already exists and works.
- Watching the filesystem to reconcile continuously. Reconciliation happens on
  `declaw index`; live watching is the Phase 9 gateway's job (DCL-109's
  component is built and waiting).
- Undo. A move is reversible by moving back; the confirmation gate is the
  safeguard, and an undo stack is not v0.1 work.

## 1. Index reconciliation (unticketed, highest priority)

`DocumentIndexer.index()` gains a reconciliation pass: after walking, any
catalog entry whose file is gone has its chunks deleted and its catalog row
removed. `IndexReport` gains a `removed` count, and the CLI reports it.

**The subtlety that makes this dangerous to get wrong.** `declaw index
dossier/` indexes one subfolder. Reconciliation must prune **only within that
subtree** — comparing against the whole catalog would delete the index for
every document outside the folder the user happened to point at. The scope of
the prune must equal the scope of the walk.

Both halves get tests: files removed inside the scope are pruned; entries
outside the scope survive untouched.

## 2. DCL-114 / DCL-115 — verify, do not rebuild

`FilesystemMoveTool` (DCL-023) already:

- moves **and renames** (its own docstring says so; `test_move_renames_file_in_place` covers it)
- is `ToolClass.WRITE`, so `ToolRegistry.langchain_tools` already wraps it in
  the confirmation gate
- refuses to overwrite without an explicit flag, and verifies on every refusal
  that the source survives and the destination was not created
- is already wired into `declaw chat`

Both tickets list DCL-023 as their dependency. They are satisfied by
verification, not by new code: an end-to-end test that a natural-language move
and a natural-language rename each go through the confirmation gate, plus the
reconciliation above so the index follows the file.

Writing a second move tool would be duplication, and worse — two tools with
overlapping names is exactly the confusion the Phase 1 probes showed a 3B model
handles badly.

## 3. DCL-113 — summarize

**The model writes the prose; the tool supplies the citations.**

`document_summarize(query, summary)`:

1. the model has already searched and composed a summary
2. the tool **re-runs the retrieval itself** for `query`, so the sources block
   is built from real retrieval metadata rather than from anything the model
   typed
3. it writes the summary — default `summary.md` at the workspace root, or a
   caller-supplied relative path, always through `resolve_in_workspace` so it
   cannot escape — carrying the prose, the structural sources, and an explicit
   provenance line. It refuses to overwrite an existing file unless told to,
   the same rule `filesystem_write` already follows
4. `ToolClass.WRITE`, so nothing is written without confirmation

Re-running retrieval costs little: the chunk sanitizer caches verdicts by
SHA-256, so the second search over the same chunks classifies nothing.

**Why an LLM writes this when DCL-062's audit summaries are deterministic
templates.** The two are different objects. An audit summary is *evidence* —
what the system did, read by someone checking compliance, where a
plausible-but-wrong sentence is worse than none. A document summary is a
*derived convenience* the user asked for and reads knowing its origin. So it
carries a provenance line, EN and FR, and its sources are structural. The rule
that survives from DCL-062 is not "never use the model" — it is "never let the
model invent the citation".

`summary.md` is written **into the workspace**, which means a later
`declaw index` will index it. That is acceptable and even useful, but the
provenance line must survive into the chunk text so a future retrieval cannot
present AI-generated prose as if it came from a client document.

## 4. DCL-116 — organize

Whole-plan approval, once (decision taken 2026-08-26).

`organize_files(moves: list[FileMove])` where `FileMove` is
`{source: str, destination: str}`. Core tools are not restricted to the flat
plugin schema subset, so a nested model is fine here.

Execution order: validate every move first (each path through
`resolve_in_workspace`, sources exist, destinations do not collide with each
other or with existing files), then execute. A plan that fails validation is
refused **whole**, with the offending entry named — half-executing a
reorganisation is how a user loses track of their own files.

**This needs a small extension to the confirmation gate.** The approval question
is built in `make_console_confirmation_provider` (`declaw/brain/repl.py`), which
renders `tool.name(key=value, ...)` — verified by reading it, not assumed. For a
thirty-move plan that is an unreadable blob, and an unreadable approval prompt
trains people to click through: the exact habit the gate exists to prevent.

So `DeclawTool` gains an optional `confirmation_preview(args) -> str | None`,
defaulting to `None`. The console provider uses it when present and falls back to
the current rendering otherwise, so no existing tool changes behaviour. The
Phase 9 WebSocket provider will consult the same hook.
`organize_files` overrides it to render:

```
Move 12 files:
  factures/2024-03-acme.pdf      -> factures/ACME/2024-03.pdf
  factures/2024-04-acme.pdf      -> factures/ACME/2024-04.pdf
  ... 9 more
  factures/2024-01-dupont.pdf    -> factures/DUPONT/2024-01.pdf
```

Directories are created as needed — that is the "create folder structure" half
of the ticket — but only inside the workspace, and only as parents of an
approved destination.

## 5. DCL-117 — the benchmark

Corpus rules were fixed in the 8a spec and are not re-opened:

- **Development set: synthetic.** French contracts, invoices and correspondence
  written for this project, generated reproducibly by a script so the fixtures
  are diffable and regenerable.
- **Held-out set: real EUR-Lex documents**, downloaded once at authoring time
  and committed with source URL and licence, a few MB total. Confirmed with the
  user on 2026-08-26.
- **Never tune against individual held-out failures.** Fix the concept and
  re-measure. The sanitizer scored 91.7% on its own corpus and 53.3% on
  external data; that 38-point gap is the entire reason this rule exists.

**What is measured.** Retrieval quality, not answer quality — the model's
prose is not the thing under test and a 3B model's phrasing would swamp the
signal. For each question, a known-correct passage:

- **recall@k** at **k = 5**, matching `search.DEFAULT_K` so the number describes
  what the product actually retrieves; recall@1 reported alongside it
- **MRR**: how far down is it?

Both reported for the development and held-out sets side by side, with an
explicit warning when they diverge by more than 5 points — the same shape as
`scripts/sanitizer_benchmark.py`.

`scripts/document_benchmark.py` is the live runner; the harness itself is
model-agnostic and unit-tested with a fake retriever, exactly as the sanitizer
benchmark is.

**A number that will be uncomfortable is the point.** Phase 8a proved the
machinery is correct. This is the first evidence about whether the answers are
any good, and it is better to learn that now than after the UI is built on top.

## Testing

Deterministic, no Ollama, no network:

| Area | How |
| --- | --- |
| Reconciliation | Fake parser; assert pruning inside scope and survival outside it |
| Move / rename | Existing tool through the registry's confirmation gate, end to end |
| Summarize | Fake store + fake sanitizer; assert sources come from retrieval, not from the model's argument |
| Organize | Validation refuses a whole plan on one bad entry; no file is touched when it does |
| `confirmation_preview` | Existing tools unaffected (returns `None`); organize renders a readable plan |
| Benchmark harness | Fake retriever with known answers; recall@k and MRR arithmetic |

The EUR-Lex fixtures are read by the live runner only, never by the unit tests,
so the suite stays fast and offline.

## Honest limitations

1. **Reconciliation only runs on `declaw index`.** Between runs the index can
   still cite a file the user deleted a minute ago. Continuous reconciliation
   needs the Phase 9 gateway.
2. **A summary written into the workspace becomes indexable content.** The
   provenance line mitigates it; it does not eliminate the oddity of the corpus
   containing the assistant's own prose.
3. **Organize validates then executes; it is not atomic.** A failure partway
   through (a disk error, a permission change between validation and execution)
   leaves the reorganisation half-done. The report names exactly which moves
   succeeded so the user can finish or reverse them.
4. **The benchmark measures retrieval, not answers.** A good recall@5 with a
   model that then misreads the passage still produces a bad experience, and
   this number will not catch that.
5. **Embedding vectors are still unencrypted** (Phase 12), and reconciliation
   deleting a document's chunks does not scrub them from Chroma's on-disk
   segments immediately — deletion is logical. Worth stating for a
   right-to-erasure claim.

## Ticket mapping

| Ticket | Delivered as |
| --- | --- |
| — (new) | Index reconciliation: renamed and deleted documents are pruned, scoped to the walk |
| DCL-113 | `document_summarize`: model prose, structural sources, provenance line, confirmed write |
| DCL-114 | Verified: existing `filesystem_move` through the confirmation gate, index follows the file |
| DCL-115 | Verified: same tool renames; conflicts already refused without `overwrite` |
| DCL-116 | `organize_files`: typed plan, validate-all-then-execute, readable one-shot approval |
| DCL-117 | `declaw/documents/benchmark.py` + `scripts/document_benchmark.py`, dev vs held-out reported side by side |
