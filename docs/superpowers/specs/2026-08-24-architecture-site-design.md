# Architecture Site — Design

> Status: approved design, pre-implementation.
> Date: 2026-08-24. Branch: `feat/phase-7-plugin-host` (work lands directly here, per user decision).

## 1. Goal

A static, bilingual (EN + VI) web page that explains DeClaw's architecture to two
readers: a **new developer** about to write code, and a **person receiving handover**
who must judge what is finished and what is owed.

The page must be readable by eye and by keyboard, and — the binding constraint —
**it must not say anything false about the code**. Truthfulness is enforced by
CI guards, not by care.

## 2. Non-goals

- Not a replacement for `CLAUDE.md`, `TICKETS.md`, or `docs/phase-*-review.md`. It links to them.
- Not an API reference generated from source. Content is curated and anchored.
- No runtime data, no server, no analytics, no external network calls at page load.

## 3. Verified repository facts

Every fact below was checked by running the command, not by reading a document.

| Fact | How verified | Result |
|---|---|---|
| Test suite | `uv run pytest` | 733 passed, 1 skipped, exit 0 (Windows) |
| Lint gate | `uv run ruff check .` | All checks passed, exit 0 |
| Type gate | `uv run mypy declaw declaw_plugin_sdk` | 95 source files, 0 issues, exit 0 |
| Existing CI | `ls .github` | **Does not exist.** No CI in the repo today. |
| Remote | `git remote -v` | `https://github.com/NgoHung0704/DeClaw.git` |
| Toolchain | `node --version`, `npm --version` | Node 24.16.0, npm 11.13.0 |
| Empty placeholders | `declaw/gateway/__init__.py`, `declaw/sandbox/__init__.py` | Zero bytes — declared subsystems, not yet built |
| Frontend dirs | `find ui tauri -type f` | Only `.gitkeep` files |

`CLAUDE.md`'s "mypy strict (95 files)" is confirmed to mean `declaw` **plus**
`declaw_plugin_sdk` together.

## 4. Stack

Vite + React + TypeScript + Vitest, in `docs-site/`.

- **No animation library.** Motion/Framer write `opacity` into inline style, which
  silently defeats a `.dimmed` class on the same element. All dimming is a
  React-controlled inline `opacity` on a **parent** `<g>`, so opacities multiply
  and the value is directly assertable in tests.
- **Hand-rolled SVG.** Text wrapping, edge lane routing and label placement are
  written here because the failure modes (overflowing `<text>`, collapsed
  multi-edges, labels stacked at a box centre) are exactly what a diagram library
  hides.
- **Plain CSS with custom properties.** No CDN — the page must work offline and
  under a strict CSP.
- **Hash routing.** GitHub Pages has no server rewrites, and route-owned Escape
  handling depends on the route being the single source of truth.
- `npm install` / `npm ci` must be run from **PowerShell** on Windows. Through Git
  Bash, npm mis-detects the platform, skips native optional dependencies (rollup)
  and emits shims missing their `.cmd` files.

## 5. Content model

All human-visible strings live in `docs-site/content/`. Nothing user-facing —
including button labels and `aria-label`s — may be written in `.tsx`. The reason is
testability: guards can then assert content in the repo's own vocabulary without
parsing UI code.

| File | Holds |
|---|---|
| `ui.json` | chrome strings: nav, buttons, filters, `aria-label`s, empty states, diagram-list headings |
| `principles.json` | the 7 Inviolable Principles as first-class ids, referenced by edges, components and why-cards |
| `systems.json` | Layer 1 nodes and edges; each edge carries a `contract` |
| `ownership.json` | who owns / who writes each store, plus store kind, lifetime, enforcement point |
| `components.json` | Layer 2 grid: `id`, role group, `modules[]`, `tickets[]`, summary, `tier` |
| `details/<id>.json` | Layer 3: `functions[]`, `flow`, `snippets[]`, `quotes[]`, `why[]` |
| `tickets.json` | DCL id, phase, status, and three relation lists: `creates` / `modifies` / `traverses` |
| `debt.json` | what is unvalidated, unbuilt or temporary — each anchored to its source |
| `repo.json` | generated: owner/repo + commit SHA for line-accurate GitHub deep links |

Prose fields are `{ "en": "...", "vi": "..." }`. Structural fields (ids, paths, line
numbers) are language-neutral, so a path is guarded once rather than twice.

### 5.1 snippet vs quote — structurally exclusive

- A **snippet** embeds code: has `code`, must NOT have `anchor`. Guarded verbatim.
- A **quote** cites without embedding: has `anchor`, must NOT have `code`.
- A record carrying both, or neither, **fails the guard**. Without this rule an
  author escapes the anchor requirement simply by calling a record a snippet.

### 5.2 Ticket relations

Three distinct relations, because collapsing them breaks the diagram in two
different ways:

- `creates` — the ticket introduced the file.
- `modifies` — the ticket changed an existing file.
- `traverses` — the ticket's flow passes through a component it never edited.

Counting only `creates` leaves tickets owning nothing, and they vanish from the
diagram. Counting only `creates` + `modifies` makes a ticket's request look severed
mid-pipeline, because components it *calls* but does not *edit* stay dimmed.

`creates` and `modifies` are derived mechanically at authoring time from
`git log --name-only` over the repo's `feat(DCL-XXX)` commit convention. This is a
**derivation, not a CI guard** — a history rewrite would make such a guard lie.
`traverses` is curated from the declared call flow.

## 6. The three layers

### Layer 1 — system map

Where this repo sits among Ollama, SQLite, ChromaDB, the OS keyring / encrypted
fallback, plugin subprocesses, the workspace filesystem, the JSON policy files, and
the declared-but-unbuilt FastAPI gateway and Docker sandbox. Every edge is clickable
and opens the **real** contract: method, path, auth, request/response shape, error
codes. Sources include `declaw/brain/ollama_client.py` (`/api/version`, `/api/tags`,
`/api/embed`), `declaw_plugin_sdk/protocol.py` (NDJSON frames, `MAX_FRAME_BYTES`,
the closed `ErrorCode` literal) and `declaw/plugin_host/errors.py`.

Alongside it, the **ownership table** — who owns and who writes each store. This is
where new developers are most often wrong.

Only contracts that can be read in this repo are documented. Anything inside a
third-party library is either read and cited, or omitted.

### Layer 2 — component grid

Every module in source, grouped by role, filterable by phase and ticket. Coverage is
100% and guard-enforced, including the empty `gateway/`/`sandbox/` placeholders and a
"dev tooling" component for `scripts/` and `alembic/versions/`.

### Layer 3 — component detail

Call-flow diagram, function list with signature and `file:line`, **real embedded
code**, GitHub deep links pinned to a commit SHA, and "why" cards drawn from the
docstrings and comments already in the code. No invented rationale.

Two tiers, guard-enforced so a component cannot silently degrade:

- **Tier A** — flow diagram + functions + embedded code + why cards. The spine:
  agent loop, tool registry and wrapper order, confirmation gate, sanitizer pipeline,
  plugin host + IPC, document indexer, document search + citations, audit + egress.
- **Tier B** — functions + anchored quotes + why cards, no flow diagram.

### The machine diagram

DeClaw drawn as a production line: intake ports, parts, exits. Filtering by ticket
lights the participating parts and dims the rest.

**It must be drawn as a gate, not a chain.** `registry.langchain_tools()` routes a
READ tool with `produces_external_content` through the **sanitizer**, and every
non-READ tool through **confirmation** — mutually exclusive branches — with **audit
wrapping whichever branch was taken**. The docstring records that the both-at-once
path is deliberately not wired because no such tool ships. A linear
audit -> confirmation -> sanitizer -> tool chain would misrepresent the code.

## 7. Diagram mechanics

- **Text wrapping.** `wrapText()` emits `<tspan>` lines; box height grows with line
  count. Runtime layout re-measures with `getComputedTextLength()` and re-wraps, so
  real browser metrics win. jsdom returns 0 and falls back to the estimator.
- **Multi-edge lanes.** Edges sharing a node pair (in either direction) are grouped,
  assigned lane offsets, and routed as polylines. Each label sits at the midpoint of
  **its own routed segment** — never the source box centre, which is what collapses
  two opposite-direction edges onto one point.
- **Column gaps** are computed from lanes-crossing × spacing with a floor. Five lanes
  cannot be asked to fit in 40px.
- **Dimming** is inline `opacity` on the parent group, asserted by value.

## 8. Routing, keyboard, accessibility

- The **router owns the only `keydown` listener**. Escape pops exactly one route
  level. `stopPropagation` does not separate listeners bound to the same target, so
  per-panel document listeners would close the whole stack at once and push several
  history entries.
- A **mount-order stack is explicitly rejected**: a panel playing its exit transition
  is still mounted and would swallow the next key. The route is the truth.
- Escape calls `history.back()` when the router itself pushed that level, and
  `navigate(parent, { replace: true })` when the user arrived by deep link — so
  history never grows and the first Back press is never dead.
- **Focus**: opening a panel moves focus to its heading; Escape returns focus to the
  trigger. Asserted via `document.activeElement`.
- **The diagram's companion list is always visible** (beside on wide screens, below on
  narrow) and is built from real `<button>` elements generated from the same records
  as the diagram — nodes, edge labels, and gate branch labels. The SVG is never
  `aria-hidden` with an incomplete substitute; keyboard control does not depend on
  focusable `<g>` elements, whose behaviour varies by browser. On narrow screens this
  list is the primary readable view.
- All transitions sit behind `@media (prefers-reduced-motion: no-preference)`, so
  reduced motion is the default rather than an afterthought.

## 9. Guards (Vitest, reading the real repo from `../`)

1. **snippet-verbatim** — each embedded snippet equals its file's declared line range
   exactly. CRLF normalised to LF; indentation preserved exactly; only a trailing
   newline may differ.
2. **quote-anchor** — every non-embedded citation carries `anchor`, and that substring
   appears **inside** the declared range. Boundary checking alone stays green when a
   paragraph is inserted above and the citation slides onto different content.
3. **module-coverage** — every git-tracked `.py` outside `tests/` appears in at least
   one component's `modules[]`, read from `components.json` **alone**. A companion
   assertion proves a module mentioned only by `tickets.json` still fails, so a module
   cannot pass merely by being named in a ticket. Using `git ls-files` keeps
   `__pycache__` and ignored files out by construction.
4. **paths-exist** — every declared path resolves; every line range is within the
   file's length.
5. **xref-bidirectional** — component↔ticket, component↔detail file, edge↔node,
   flow-edge↔flow-node, module↔component all resolve in **both** directions.
6. **ticket-relations** — every ticket's `creates ∪ modifies ∪ traverses` is non-empty,
   every target resolves, and the component→ticket direction agrees.
7. **diagram-labels** — every flow edge and every gate branch carries a label in both
   languages, and the rendered companion list contains every node label, every edge
   label and every gate branch label, in both languages.
8. **i18n-complete** — every prose field has non-empty `en` and `vi`; key sets are
   identical across languages.
9. **no-strings-in-code** — `src/**/*.tsx` contains no literal JSX text and no literal
   `aria-label` / `title` values. Allowlist: whitespace-only, punctuation-only and
   numeric literals.
10. **tier-structure** — a Tier A component has a `flow`; every node, edge and gate it
    declares carries resolvable bilingual labels. No magic node counts.

No guard hardcodes a quantity. Every guard iterates the content and asserts per item,
so adding content is never a failure.

`npm run sync:snippets` re-pulls snippet `code` from the **declared range only**. It
never re-locates a range and never touches an `anchor` — an auto-fixer that re-finds
anchors would launder exactly the drift guard #2 exists to catch.

### What the guards cannot do

They prove a snippet is verbatim, a citation is anchored, a path exists and a
reference resolves. They **cannot** prove the prose interprets the code correctly;
that remains human judgement. `no-strings-in-code` is a lint over JSX shapes, so a
string smuggled through a helper would evade it. And the text-fitting check compares
the estimator against itself — it proves internal consistency, not that text visually
fits. Visual truth requires opening the page.

## 10. CI and deployment

`.github/workflows/ci.yml` — the repo has no CI today, so this creates it. Every
command runs bare: `cmd | tail` returns `tail`'s exit code, which lets a failing
command pass a following `&&`.

- **python** (`windows-latest`): `uv sync`, `ruff check .`, `mypy declaw declaw_plugin_sdk`,
  `pytest`. Windows because that is the only environment where the suite has been
  observed green; asserting Linux-green without running it would be the same error
  class the guards exist to prevent.
- **docs-site** (`ubuntu-latest`): `npm ci`, guards, build, upload Pages artifact.
- **deploy**: GitHub Pages, on pushes to `feat/phase-7-plugin-host` and `main`, so the
  page is visible without merging first.

**deploy depends on docs-site only, not on python.** The site's truthfulness is
guarded by the docs guards; blocking publication on an unrelated pre-existing Python
failure is coupling the user did not ask for. A red Python gate still marks the commit.

Vite `base` is `/DeClaw/` for project Pages. Deep-link SHAs come from `github.sha` at
build time, falling back to `git rev-parse HEAD` locally.

**Known risk:** GitHub may restrict the `github-pages` environment to protected
branches, which would block deploying from `feat/phase-7-plugin-host`. Pages will be
switched to Actions mode via `gh api`, and the environment branch policy relaxed if
needed. If GitHub refuses, that is reported — not silently worked around by switching
to `main`.

## 11. Honest content policy

The page records what is owed: unvalidated claims, unbuilt subsystems, temporary
measures. Sources already in the repo include the empty `gateway/` and `sandbox/`
packages, the deferred Phase 3 sandbox, the sanitizer's 38-point held-out detection
gap and its measured French weakness, the unreachable p95 target, unencrypted
embedding vectors, the in-process-only egress monitor, unpopulated episodic memory,
and the builtin-plugin auto-grant that must close before third-party install.

Every debt item is **anchored to its source** using the `quote` shape. When someone
later fixes the debt and edits that line, the anchor breaks and CI reports the page as
stale — honest debt stays drift-checked instead of decaying into a lie.

"Why" cards are drawn from reasons already present in code and documentation. No
rationale is invented.

## 12. Acceptance

- For **every** test written to protect a behaviour: break the behaviour, observe the
  test fail, restore it. A test never seen red is not evidence.
- Run the full CI gates locally, exit codes unmasked.
- Open the page and inspect each layer visually — tests catch neither overflowing
  text, overlapping edges, nor poor contrast. If a browser cannot be driven in this
  environment, say so plainly rather than implying inspection happened.
- Check a narrow viewport and `prefers-reduced-motion`.
- Switch language and confirm no strings from the other language remain.

## 13. Cost accepted knowingly

Because work lands on `feat/phase-7-plugin-host`, any later commit that shifts a
documented line range turns CI red until content is re-synced. That is the mechanism
working as designed; `npm run sync:snippets` is the release valve.
