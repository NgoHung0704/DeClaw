# Phase 9 repository maintenance - 2026-11-12

Base: `110e9e7`, `feat/phase-9-gateway-web-ui`. The owner requested a plan,
review and implementation following the repository-cleanliness review.
See the [design](../specs/2026-11-12-phase-9-maintenance-design.md) and
[plan](../superpowers/plans/2026-11-12-phase-9-maintenance.md).

## Scope and evidence

- Inventory covered 324 tracked files before maintenance, including 27 files
  under docs. No identical nonempty tracked files were found. Fixture data,
  benchmarks, SDK bootstrap and Tauri scaffolding are retained intentionally.
- README/status/map/tickets now distinguish executable gateway/UI behavior
  from pre-Phase-9 planning. DCL-082 follows the already ratified permission-panel
  alternative. Gateway audit task correlation is distinguished from CLI chat.
- Historical readiness/plans are labeled and indexed without altering their
  original test/measurement claims. The baseline's broken ignored-ledger link
  now points to versioned design/plan evidence.
- Shared retrieval-source context moves from gateway to documents. Config and
  SettingsService share a settings-file reader and workspace resolver that do not
  import config/services/operational logging. File filtering, warning behavior,
  env precedence, error compatibility and workspace fail-closed checks remain.
- docker, playwright, apscheduler and python-multipart had no code/route uses;
  lockfile reverse references named only declaw. The resolver removed those four
  direct requirements and four now-unneeded transitive packages. A parsed
  comparison with the base lockfile confirmed no added packages and no changed
  retained version pins. Frozen sync passed.
- CI push branches cover main and `feat/**`; PR checks and job permissions remain.
  Only the three empty deferred sandbox placeholders are removed. The Docker
  CLI preflight check, isolation requirement flag and shell deferral remain.

## Verification record

Windows, Python 3.12.13. Async tests use the loopback-capable runner;
UV_CACHE_DIR=.cache/uv, TEMP/TMP=.cache/tmp and unique repository-local basetemps.

- Before refactor: new regressions reported 3 failures / 12 passes, showing
  missing documents-layer source context and cold config loading service/log.
  The workspace-equals-data_dir security regression was present before changes.
- After refactor: targeted config/settings/documents/citation/streaming/log and
  document-isolation tests: 94 passed in 9.05 seconds.
- Ruff passed; mypy passed for 122 source files after the module extraction.
- Offline lock resolution was unavailable because the cache lacked dependency
  metadata for the project's Python range. Network-enabled resolution completed
  and frozen sync removed unused packages. CLI help completed successfully.

| Final check | Observed result |
| --- | --- |
| `uv sync --frozen` | Passed; 153 installed packages checked |
| `uv run ruff check .` | Passed |
| `uv run mypy declaw declaw_plugin_sdk` | Passed; 121 source files after removing the empty sandbox package |
| `uv run pytest --basetemp=.cache/pytest-maintenance-full --tb=short` | Exit 0; 1056 passed, 1 skipped in 135.29 seconds |
| `node --experimental-vm-modules --test tests/gateway/ui-behavior.test.cjs` | 7 passed, 0 failed |
| Local Markdown links/index | 35 Markdown files checked; no broken local file links; every docs file has an incoming link |
| Module boundary check | Documents no longer import gateway; the settings-file reader imports no config, service, application or gateway module |
| CI configuration inspection | Main and `feat/**` push plus PR triggers; contents permission remains read-only |
| `git diff --check` | Passed; line-ending conversion warnings only |

Python/Node results above are fresh maintenance results, distinct from the
earlier Phase 9 baseline. The source move and settings extraction add four tests;
no historical acceptance checkboxes were retroactively marked complete.
Fresh independent final review found no actionable issues and judged the changes
ready for handoff. The reviewer checked the code, new tests, scope and full-suite
log; other check results were supplied by the executor. The local diagnostic
scripts/logs are ignored under `.cache/`.

The reviewer set aside existing strict Docker preflight behavior because the
plan explicitly defers changing it, and real-browser/Linux/packaged-release
acceptance because this maintenance did not verify those environments. Ruling:
retain both exclusions and their existing documented limitations; no readiness
claim is expanded. No critical, important or deferred minor finding remains.

## Limits and decisions

No live browser security checklist, model benchmark, Linux or packaged release
was verified by this maintenance. The previous owner feedback accepted visual
UI only; [manual acceptance](../phase-9-review.md) stays open. Preflight Docker
failure behavior is retained as a separate follow-up (DCL-007). No new product
phase, auth/sanitizer/approval-policy change, remote push or merge is included.
Main and Phase 10 refs remain unchanged during this maintenance.

After maintenance handoff, the owner explicitly requested committing and
publishing the necessary changes to GitHub. That follow-up publishes the Phase 9
branch only; it does not merge or advance main/Phase 10, or expand the validation
claims above. The commit and remote publication outcome are reported separately.
