# Phase 9 Repository Maintenance Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in this session. Track the tasks below; review the final diff with a fresh reviewer.

**Goal:** Reconcile Phase 9 documentation, dependencies and module ownership without changing security behavior.

**Architecture:** Document citations belong to the shared documents layer. Configuration bootstrap and UI settings reuse a lower-level settings-file reader/resolver, avoiding config/service/log cycles. Preserve existing public settings and tool contracts.

**Tech Stack:** Python 3.12+, uv, existing FastAPI/LangGraph, vanilla JS, Windows CI and Node's built-in runner.

**Spec:** [Maintenance design](../../specs/2026-11-12-phase-9-maintenance-design.md).

## Global constraints

Work in the clean Phase 9 checkout at `110e9e7`; preserve Phase 10/main refs.
Keep credentials, exact loopback launch, sanitizer, typed containment, confirmation
and audit invariants. No new product phase, runtime packages, shell feature,
UI redesign, deployment, push or merge. Preserve historical evidence and local caches.

## Review focus

1. Citation context crosses async tasks but never independent turns; no-op outside
   a collector and copied/deduplicated metadata remain intact (Task 1 tests).
2. Workspace loaded from disk cannot equal data_dir; explicit environment values
   keep precedence and model_fields_set provenance (Task 1 and existing config tests).
3. Settings bootstrap must not import service/log/gateway; corrupt file warnings
   and invalid model/language filtering remain the same (Task 1 regressions).
4. Dependency removal must not break FastAPI JSON endpoints, WebSockets, document
   parsing or CLI preflight's executable Docker probe (Task 2 full suite).
5. Historical plans must not be relabeled as newly tested; no links rely on
   ignored local ledgers and every retained doc is indexed (Task 3 link check).

## Task 1: Repair shared-module ownership

Files: move gateway/sources.py to documents/sources.py; update documents tools,
actions, gateway/session.py and code/test references. Create settings_file.py;
modify config.py and settings_service.py. Tests: new tests/unit/test_documents_sources.py,
tests/unit/test_config.py and existing settings, documents and streaming tests.

Interfaces: TurnSources.record(metadata: dict[str, Any]) -> None;
TurnSources.sources() -> list[dict[str, Any]]; record_source(metadata) -> None;
current_turn_sources: ContextVar[TurnSources | None]. Settings reader:
read_settings_file(path: Path) -> dict[str, str]; effective_workspace(default: Path,
data_dir: Path, explicit: bool, values: Mapping[str, str]) -> Path.
InvalidSettingsFileError retains its settings_service import path.

- [x] Write collector tests asserting no-op, dedup, copies and async context isolation;
  run red against the new module path, then move the unchanged implementation.
- [x] Add config regression using a cold subprocess with isolated cwd/env proving
  settings bootstrap loads a saved workspace without loading settings_service or
  declaw.log; run red. Add fail-closed saved-workspace-equals-data_dir regression
  before implementation. Reuse existing environment-precedence/security tests.
- [x] Extract parsing/validators/workspace resolver once; use it from config and
  service. Preserve all default/exception/cache/provenance behavior.
- [x] Run targeted documents/citation, streaming, config, settings and log tests,
  ruff and mypy. Expected: all pass; inspect references for old module path.

## Task 2: Remove unused installation/scaffold baggage

Files: pyproject.toml, uv.lock, .github/workflows/ci.yml; remove three empty
sandbox placeholder files only. No changes to Tauri or local environment contents.

- [x] Confirm the four packages have no code/route uses and inspect reverse lock
  references. Remove direct requirements; run `uv lock --offline` first and
  inspect the diff for unrelated package updates. Use network only if required.
- [x] Run `uv sync --frozen`; ensure installed project imports/CLI help still work.
- [x] Set push branches to `[main, 'feat/**']`, preserving PR trigger and job checks.
- [x] Remove only verified empty sandbox placeholders. Keep the deferred isolation
  config contract and document strict preflight's existing limitation.

## Task 3: Reconcile docs and review the complete result

Files: README.md, docs/README.md, project-status.md, code-map.md,
architecture-decisions.md, phase-9-readiness.md; Phase 9 original and repairs
plans, dated baseline, TICKETS.md, gateway/app.py module docstring; new dated
docs/history/phase-9-maintenance-2026-11-12.md.

- [x] Correct contradictions and label historical records; explicitly index
  retained reviews/specs/plans and remove the ignored-ledger link. Do not mark
  historical task checkboxes as witnessed completions or browser checks as passed.
- [x] Self-review plan coverage, signatures and scope before implementation;
  resolve ambiguities in the execution log below. No new unresolved architecture choice.
- [x] Run uv sync --frozen; ruff check .; mypy declaw declaw_plugin_sdk; full pytest
  with a fresh workspace-local basetemp in the loopback-capable runner; Node UI suite;
  Markdown local-link checks; git diff --check. Record actual output and skips.
- [x] Request fresh final diff review, fix material findings with regression coverage,
  update report/map/decisions/tickets and record any limitations honestly.
- [x] Leave the reviewed implementation on Phase 9 for handoff; no push/merge or
  automatic advancement of main/Phase 10. Commit only when authorized.

## Plan review and execution log

Plan self-review completed before implementation: each design boundary maps to
Tasks 1-3; collector/settings interfaces and review-focus checks are explicit.
Ruling: keep preflight behavior and all historical measurements unchanged; this
maintenance removes the unused Docker SDK, not the executable probe. Changing
preflight is a separate behavior change and would expand the accepted cleanup.
Ruling: implement in the existing clean Phase 9 checkout as requested; no worktree
or new phase branch. Main and Phase 10 remain at their existing commits.
Ruling: use loguru's shared logger in the low-level file reader; importing
declaw.log there would recreate config -> reader -> log -> config coupling.
Owner requested continuous execution after plan review; use inline implementation
with one final independent review. Product invariants and public error imports stay intact.

Task 1: implementation complete, working-tree changes; new tests RED (3 failed,
12 passed), then targeted checks GREEN (94 passed); ruff and mypy passed. The
existing invalid-settings-value test also covers filtering after extraction.
Task 2: implementation complete; reverse lock references named only declaw;
resolver removed eight packages and changed no retained version pins; frozen sync
and CLI help passed. Empty sandbox placeholders removed; Tauri retained.
Task 3: complete. Full suite completed with 1056 passed / 1 skipped; Node 7 passed;
frozen sync, ruff, mypy and all local Markdown links passed. Fresh independent
review found no actionable issues and judged the changes ready for handoff.
No commit, ref movement or publication during execution.
Final: Ruling: retain the review exclusions for existing strict Docker preflight,
real-browser acceptance, Linux and packaged-release behavior. They are documented
limits, not verified outcomes; changing them would expand this maintenance scope.
No deferred minor findings. Final results are in the dated maintenance report.
