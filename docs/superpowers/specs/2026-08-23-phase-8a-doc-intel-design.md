# Phase 8a — doc-intel: indexing, search, citations

- **Date**: 2026-08-23
- **Status**: approved, ready for implementation planning
- **Tickets**: DCL-100..112 (DCL-113..117 are Phase 8b)
- **Branch**: `feat/phase-8-doc-intel` (from `feat/phase-7-plugin-host`)
- **Context**: `2026-08-23-phase-7-9-roadmap.md`, `2026-08-23-phase-7-plugin-host-design.md`

## Goal

Close **MVP DoD #2 and #3**: point DeClaw at a folder of PDF/DOCX/XLSX/TXT
files, ask a question in French or English, and get an answer whose sources are
shown and verifiable.

Phase 8b (DCL-113..117) adds summarize/move/rename/organize actions and the
quality benchmark, on top of a search layer that by then will have been
measured rather than guessed at.

## Non-goals

- OCR and scanned PDFs. See *Decision 2*.
- Running the file watcher for real. The component is built and tested; wiring
  it to a long-lived process is Phase 9, where the gateway exists.
- Actions (summarize / move / rename / organize) — Phase 8b.
- The Q&A quality benchmark — Phase 8b, but its corpus rules are fixed here so
  the development set cannot quietly become the exam.

## Architecture

The split follows roadmap decision 3: **thin plugin**.

```
  declaw index <folder>          declaw chat
        |                             |
        v                             v
   DocumentIndexer            document_search tool
        |                             |
        |  resolve_in_workspace       v
        |                        search()  --> per-chunk sanitize (cached)
        v                             |
   PluginHost.call(                   v
     "doc-intel", "parse",       DocumentStore  <--> Chroma "declaw_documents"
     {"path": <abs>})                 ^              (Fernet at rest)
        |                             |
        v                        Embedder (batched, Ollama)
  === process boundary ===
        |
   doc-intel plugin
     parsers/{pdf,docx,xlsx,text}.py
     chunker.py
```

### Why the boundary sits exactly there

`pypdf`, `python-docx` and `openpyxl` parse adversarial binary files that
arrived from strangers. That is the code worth isolating in a subprocess, and
it is the only part of doc-intel that is. Everything downstream — embedding,
encryption keys, the vector store — stays in core, which avoids handing a
Fernet key to a subprocess and avoids two processes writing one Chroma store.

## Modules

**Plugin — `plugins/builtin/doc-intel/`:**

| File | Responsibility |
| --- | --- |
| `plugin.yaml` | Manifest: name `doc-intel`, requests `filesystem.read` |
| `main.py` | `DocIntelPlugin(BasePlugin)` with the single `parse` capability |
| `parsers/pdf.py` | pypdf text extraction, per page |
| `parsers/docx.py` | python-docx: paragraphs, headings, tables |
| `parsers/xlsx.py` | openpyxl: rows per sheet |
| `parsers/text.py` | TXT + Markdown, heading-aware, YAML frontmatter |
| `chunker.py` | Heading/paragraph-aware chunking to ~512 tokens |

Token counting reuses the same conservative heuristic as
`declaw/brain/context.py` (`ceil(chars / 3)` plus per-item overhead). It
over-estimates by design, so a chunk never turns out larger than budgeted. The
plugin cannot import it — `declaw.*` is blocked — so the ~20-line function is
duplicated in the plugin with a comment naming core as the source of truth, and
a test asserts the two agree on a shared corpus. Duplication here is cheaper
than either widening the SDK or letting the two drift unnoticed.

**Core — `declaw/documents/`:**

| File | Responsibility |
| --- | --- |
| `models.py` | `DocumentChunk`, `IndexedDocument`, `SearchHit` — frozen |
| `store.py` | `DocumentStore`: batch add, top-k search, delete by document |
| `catalog.py` | File → hash index (SQLite), for incremental indexing |
| `indexer.py` | Walk, hash, parse via plugin, embed, store, report progress |
| `search.py` | Query → embed → top-k → sanitize (cached) → `SearchHit`s |
| `citations.py` | Deterministic source rendering |
| `prompts.py` | EN/FR chunk framing (data, not instructions) |
| `watcher.py` | watchdog component — built and tested, not wired |
| `tools.py` | `document_search` as a `DeclawTool` |

**Modified:** `declaw/main.py` (`declaw index`), `alembic/versions/` (one
migration), `pyproject.toml` (drop `unstructured`).

## 1. The plugin's one capability

```python
@capability(
    name="parse",
    description_en="Parse a document into text chunks with source metadata.",
    description_fr="Analyse un document en fragments de texte avec métadonnées.",
    requires=["filesystem.read"],
    exposed_to_model=False,
    produces_external_content=True,
    classification="read",
    timeout_s=300,
)
async def parse(self, args: ParseArgs) -> ParseResult: ...
```

`ParseArgs` is `{path: str}` — an absolute path the **core has already
validated** with `resolve_in_workspace` before calling. That function was
promoted to `declaw/tools/builtin/_paths.py` in Phase 7 precisely for this, its
fifth consumer.

`exposed_to_model=False` is the load-bearing flag: `parse` is infrastructure
the indexer drives, and the model must never see it as a tool.

`ParseResult`:

```python
{
  "doc_type": "pdf",
  "page_count": 12,
  "truncated": false,
  "chunks": [
    {"text": "...", "ordinal": 0, "page": 1, "sheet": null, "heading": "Article 3"}
  ]
}
```

Returning the whole document in one frame is fine under the 32 MiB cap: a
500-page PDF is a few MB of text. A document that would exceed the cap is
truncated with `truncated: true` rather than failing the frame, and the indexer
warns.

## 2. Decisions worth arguing with

### Decision 1 — `catalog.py` uses SQLite, not JSON

The opposite call to Phase 7's `plugin_state.json`, deliberately. That file
held four fields of user *policy*, where being diffable is a feature. This is a
machine-maintained index over potentially thousands of files, queried by hash
on every indexing pass. Different problem, different storage — SQLite with an
alembic migration, alongside the existing tables.

Table `indexed_documents`: `path` (PK, workspace-relative), `content_sha256`,
`size_bytes`, `mtime`, `doc_type`, `chunk_count`, `indexed_at`.

### Decision 2 — drop `unstructured`; pypdf only

`TICKETS.md` DCL-101 says "text-first via pypdf; unstructured for
scanned/complex". Scanned PDFs need OCR, which is a subproject in its own right
(model weights, language packs, a large dependency that may want to download at
runtime — against the offline promise).

So v0.1 uses pypdf alone, and **the failure is made loud rather than silent**:
when a PDF yields no extractable text, the parser reports
`doc_type="pdf-scanned"` with zero chunks, and the indexer tells the user
*"this looks like a scanned document — DeClaw cannot read it yet"*. A user
whose file was silently indexed as nothing would later get confidently wrong
answers about a document the system never read. `unstructured` is removed from
`pyproject.toml`; adding OCR back is a named future ticket, not a hidden gap.

### Decision 3 — `document_search` is `produces_external_content=False`

This looks wrong at a glance and needs the reason attached in the code.

Sanitizing happens **inside `search()`**, per chunk, cached by chunk SHA-256
and run concurrently. If the tool also carried
`produces_external_content=True`, the registry wrapper would sanitize the
concatenated top-k a second time — one large uncacheable call on every query,
on top of the per-chunk work already done.

Per-chunk was chosen over one-blob-per-query for two reasons: the verdict
**caches** (a user asking ten questions about one contract pays once), and it
is **granular** (one poisoned chunk does not quarantine the whole answer).

Two security tests hold the line so the flag cannot quietly become a hole:

- `search()` never returns a chunk that was not classified
- `search()` classifies each distinct chunk exactly once across repeated queries

### Decision 4 — DCL-112 is reframed

The ticket says "RAG prompt template (FR + EN): strict instruction to cite;
sanitize document chunks". Citations are structural (below), so the
"instruction to cite" half does not ship as written. What ships is:

- the **chunk framing** template, EN + FR, presenting retrieved text as *data,
  not instructions*, in the same shape `brain/memory_context.py` already uses
- the sanitize wiring

No system prompt is added. The Phase 1 open decision stands: nothing goes into
the system prompt without an A/B probe on qwen2.5:3b first.

### Decision 5 — citations are structural

`SearchHit` carries the document's workspace-relative path, page or sheet or
heading, ordinal, text, and distance. The tool renders each chunk with a marker
(`[1] contrat.pdf p.12`) and always appends a `Sources:` block built from
retrieval metadata.

The model may or may not cite inline. The sources block is there regardless, so
what the user sees is what was actually retrieved. Same reasoning that made
DCL-062's audit summaries deterministic templates: for regulated professionals,
a plausible-but-wrong citation is worse than none.

## 3. Sanitizing at retrieval

Roadmap decision 4. Only the top-k chunks that actually enter the model's
context get classified, with the verdict cached by SHA-256.

- **Model stays `qwen2.5:7b`.** The FP asymmetry matters more here than in
  Phase 4: a wrongly-blocked *file read* is visible and announced to the user,
  but a wrongly-withheld *chunk* silently degrades an answer with no signal at
  all. `qwen2.5:3b`'s 7.5-9% FP would drop roughly one relevant chunk in eleven,
  invisibly.
- **Calls run concurrently**, so a cold query costs roughly one classification
  rather than k of them, subject to Ollama's parallelism setting.
- **The measured number goes in `CLAUDE.md`.** Estimates in this document are
  derived from Phase 4's p50 of 4.19 s; the real cold-query latency is measured
  on dev hardware during implementation and recorded, in the same way every
  other performance claim in this project is.
- The cache is owned by a `ChunkSanitizer` object (`search.py`), keyed by chunk
  SHA-256, holding the verdict only — never the text. It is process-local, and
  it is constructed once per session and injected, so tests can supply a fake
  and assert exactly how many classifications happened. Persisting verdicts is a
  later optimisation, not v0.1 work.

Stated plainly: an injection sitting in an indexed document is *stored*
unclassified. It is classified before it can influence the model. Any future
feature that reads chunks without going through `search()` must sanitize them
itself.

## 4. Indexing

`DocumentIndexer.index(folder, *, on_progress)`:

1. walk the folder for supported extensions
2. `resolve_in_workspace` each path — anything outside the workspace is skipped
   and reported, never followed
3. hash the file; skip if `content_sha256` matches the catalog (DCL-108)
4. call `doc-intel.parse` through `PluginHost`
5. embed the chunks in batches (default 32)
6. replace the document's chunks in the store, update the catalog

`on_progress(done, total, path)` drives a Rich progress bar under `declaw
index` today and streams over WebSocket in Phase 9 without the indexer
changing.

A file that fails to parse is reported and skipped; one bad PDF never aborts
the run.

## 5. Watcher

`watcher.py` wraps watchdog behind an injectable interface, with debouncing so
a burst of writes indexes once. It is unit-tested by driving synthetic events
— no real filesystem timing, no sleeps.

It is **not started** by any command in Phase 8a. MVP DoD #2 needs `declaw
index`, not a daemon, and there is no long-lived process to host it until the
Phase 9 gateway.

## 6. Benchmark corpus rules (fixed now, used in 8b)

DCL-117 lands in Phase 8b, but its corpus discipline is set here because
getting it wrong is invisible until far too late.

The sanitizer scored **91.7% on its own corpus and 53.3% on external held-out
data** — a 38-point gap, because a self-authored corpus grades its own
homework. So:

- **Development set: synthetic.** French contracts, invoices and correspondence
  written for this project, committed as source.
- **Held-out set: external, openly licensed.** A handful of EUR-Lex /
  Légifrance open-data documents, committed with attribution, a few MB total.
- **Never tune against individual held-out failures.** Fix the concept, then
  re-measure — otherwise the held-out set silently becomes a second training
  set. Same rule already written into `declaw/sanitizer/corpus/heldout.py`.
- The benchmark reports both numbers side by side and warns when they diverge.

## 7. Testing

Deterministic throughout: no Ollama, no network, no sleeps.

**Parsers get generated fixtures.** `fpdf2` (already a dependency, from audit
PDF export), `python-docx` and `openpyxl` build documents *from known text*, so
DCL-101's ">95% text recall" is computed exactly rather than eyeballed. A
zero-text PDF fixture covers the scanned-document path.

| Layer | How it is tested |
| --- | --- |
| Parsers | Generated documents, exact recall against known input |
| Chunker | Deterministic; average size within ±15% of target asserted |
| `DocumentStore` | Deterministic fake embedder makes top-k exact |
| `search()` | Fake sanitizer; caching and per-chunk coverage asserted |
| `DocumentIndexer` | Fake `PluginHost`; incremental skip verified by call counts |
| `catalog` | Real SQLite, temp DB |
| `watcher` | Synthetic events, injected clock |
| Integration | The real doc-intel plugin as a subprocess, one document end to end |
| Security | Chunks are never returned unclassified; paths outside the workspace are refused |

## 8. Error handling

| Situation | Result |
| --- | --- |
| PDF with no extractable text | `doc_type="pdf-scanned"`, 0 chunks, user told it needs OCR |
| Corrupt or unparseable file | Reported, skipped; the run continues |
| File outside the workspace | `WorkspacePathError`, skipped, reported |
| Document larger than the frame cap | Truncated with `truncated: true`, user warned |
| doc-intel plugin disabled or quarantined | `declaw index` refuses with an actionable message |
| Chunk classified UNSAFE | Withheld from results, quarantined, user notified |
| Embedding fails mid-run | Document left unindexed and reported; catalog not updated, so a re-run retries it |
| Search before anything is indexed | Empty result with "no documents indexed yet", not an error |

## 9. Ticket mapping

| Ticket | Where | Acceptance as built |
| --- | --- | --- |
| DCL-100 | `plugins/builtin/doc-intel/` | Loads under `PluginHost`, `declaw plugins list` shows it |
| DCL-101 | `parsers/pdf.py` | >95% recall on generated PDFs; scanned PDFs reported, not silently empty |
| DCL-102 | `parsers/docx.py` | Headings, lists and tables preserved as structure |
| DCL-103 | `parsers/xlsx.py` | Multi-sheet workbook parsed, sheet name on every chunk |
| DCL-104 | `parsers/text.py` | Markdown headings preserved; frontmatter extracted |
| DCL-105 | `chunker.py` | Average chunk within ±15% of ~512 tokens |
| DCL-106 | `store.py` | Batched embedding; 1k chunks under 2 min measured on dev hardware |
| DCL-107 | `indexer.py` | Sample workspace indexed end to end |
| DCL-108 | `catalog.py` | Unchanged files skipped, verified by parse-call count |
| DCL-109 | `watcher.py` | Component tested against synthetic events; wiring is Phase 9 |
| DCL-110 | `store.py`, `search.py` | Top-k ranked results |
| DCL-111 | `citations.py` | Every hit carries document + page/sheet/heading, from metadata |
| DCL-112 | `prompts.py`, `search.py` | EN/FR chunk framing; every returned chunk sanitized |

## 10. Honest limitations

1. **Scanned documents cannot be read.** Reported clearly, never silently
   skipped, but a real gap for a market whose files are often scans.
2. **Embedding vectors are not encrypted.** Chunk text is Fernet-encrypted at
   rest, but Chroma must compare vectors in the clear, and embedding inversion
   can approximate the source text. Carried over from DCL-051 and still a Phase
   12 item — the exposure is larger here, because documents are the whole point.
3. **An indexed injection is stored unclassified.** It is caught before
   entering the model's context, not before entering the store.
4. **The sanitize cache is process-local**, so the first query after a restart
   pays again.
5. **Retrieval quality is unmeasured until Phase 8b.** Nothing in 8a proves the
   answers are good — only that the machinery is correct.
