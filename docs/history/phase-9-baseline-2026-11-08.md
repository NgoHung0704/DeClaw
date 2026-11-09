# Phase 9 baseline — 2026-11-08

A dated, local, single-machine record. Not a guarantee for other machines,
CI environments or future commits. Source state: branch
`feat/phase-9-gateway-web-ui`, commit `dfb12c1` (Phase 9 tasks 1-15
landed; see the [SDD plan](../superpowers/plans/2026-11-08-phase-9-gateway-web-ui.md)
and the [ledger](../../../.superpowers/sdd/2026-11-08-phase-9-gateway-web-ui/progress.md)).

Machine: Windows 10 (Git Bash), Python 3.12.13 (uv-managed), Ollama
0.40.15 at `http://localhost:11434`, model `qwen2.5:3b-declaw`.

## Commands and results

| Command | Result |
| --- | --- |
| `uv sync --frozen` | Checked 161 packages, no changes |
| `uv run ruff check .` | All checks passed |
| `uv run mypy declaw declaw_plugin_sdk` | Success: no issues in 121 source files |
| `uv run pytest --basetemp .superpowers/tmp/pytest` | **1047 passed, 1 skipped** (baseline at phase start: 786 passed, 1 skip; +261 tests) |

Notes, honest about the environment:

- pytest must run with `--basetemp` in this checkout: the machine's default
  pytest temp root raises `PermissionError` (environment issue, unrelated
  to the product).
- The one skip is the pre-existing environment-related symlink skip noted
  in the 2026-10-25 baseline.
- The suite includes the full gateway integration stack: launch contract,
  auth/login, Host/Origin, rate/body caps, approval transport with
  validate-before-prompt ordering, WS chat turns with correlated
  approvals and task ids, streaming with the typed source side channel,
  watcher handoff and the serialized indexing worker, REST surface,
  `/ws/events`, and the UI security surface (CSP derived from the bind
  authority, no inline script/style, EN/FR locale parity).

## First-token latency (DCL-127, spec section 8/17 M5)

Measured, not asserted. `build_brain` graph + `graph.astream_events
(version="v2")` against the live Ollama, prompt "Say hello in one short
sentence.", three consecutive turns in one process:

| Turn | First `on_chat_model_stream` | Turn total |
| --- | --- | --- |
| 1 (cold) | 1.283 s | 1.45 s |
| 2 (warm) | 0.580 s | 0.75 s |
| 3 (warm) | 0.567 s | 0.83 s |

Reading: the streaming contract holds — real token events escape the
running graph, and warm first-token latency sits well under DCL-127's
1 s aspiration. The cold turn includes model prompt-load and exceeds it;
that is a recorded measurement on one machine with one small model, not a
product guarantee. Larger models or slower disks will differ.

## Manual verification status

- The DOM/interactive checklist (markup injection, approval modal,
  cancel, CSP in devtools) lives in
  [phase-9-review.md](../phase-9-review.md) and is **not executed in this
  record** — the repo has no JS test runner. Server-side CSP and
  no-inline-script checks run in CI; the interactive items remain manual.
