# Phase 9 regression repairs

Goal: repair the nine confirmed review findings without changing the approved
loopback, approval, sanitizer or settings precedence contracts.

1. Add executable UI regressions for bootstrap, Documents, final answers,
   tool-assisted answers and audit payloads. Run red, then repair initialization
   and rendering in `ui/js/`. Run with Node's built-in test runner.
2. Add gateway tests for startup token delivery and unauthenticated cookie
   flooding, plus application tests for task-correlated service audit events.
   Run red, then repair launcher, rate limiter and application logger ownership.
3. Add a cold configuration regression proving a saved workspace applies after
   restart, including the filesystem containment boundary. Preserve env priority
   and per-session model/language settings; run red before implementing.
4. Run focused regressions, Python CI checks and the full suite. Update status,
   code map, design, ticket ledger and a dated report with actual results.

Use the existing Phase 9 checkout. Do not commit, publish or change user data.

## Execution record

All four tasks completed. Red/green evidence and final checks are recorded in
[the dated report](../../history/phase-9-repairs-2026-11-10.md).
The only execution adjustment was using the loopback-capable runner for async
Python tests after a traceback showed the restricted runner hanging in socket
pair creation. Temporary files stayed under the workspace cache.
