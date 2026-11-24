# Phase 10 architecture repairs implementation plan

> Use TDD and systematic debugging. Independent Python, native supervision and gateway-view repairs may run in parallel; integrate and independently review before GUI testing.

**Goal:** Resolve all four P2 fault paths in the [architecture review](../../history/phase-10-architecture-review-2026-11-13.md), then build and open the app for acceptance.

**Constraints:** Preserve existing usability/download edits, same-origin and generation checks, explicit handle inheritance, owned Job cleanup, bounded shutdown, fixed diagnostics, default-deny approvals and existing data. No installer or new remote IPC grant. No commit/push until verification and acceptance are adequate.

## Tasks

- [x] Python: isolated regressions for server failure before/after Ready and drain failure; always attempt Application.shutdown under the existing total timeout, without swallowing cancellation or reporting a clean stop after an error.
- [x] Native: fake-core tests for event EOF while core alive; immediately revoke readiness and clean up within budget, preserving acknowledged Stop ordering.
- [x] Native: full-control-pipe regression; move writes off the lifecycle actor with bounded queue, write deadline and cancellable/joined writer cleanup. Start deadlines before writes.
- [x] View creation: inject builder failure in creation-state tests; show localized safe error in trusted bootstrap and retry the same live generation through existing Start/Open controls. Keep command/origin/generation grants unchanged; schedule creation on the GUI thread.
- [x] Run full Python/Node/native suites, Ruff/mypy/fmt/clippy and nonbundling native build after integration.
- [x] Independent diff review, fix any important findings, update dated evidence/status/map/spec/tickets.
- [x] Open updated app and verify lifecycle and download. Authentication remains user-assisted; preserve data and report remaining acceptance honestly. Stop/Start/Restart and JSON/Markdown downloads observed; tray Quit and actual WebView2 failure injection remain separate acceptance items.

## Ownership

Python worker owns runtime and runtime tests. Native worker owns supervisor,
Job/writer and their tests. Coordinator owns view creation, bootstrap/lib/UI
wiring and documentation. Shared Cargo checks serialize through Cargo's build
lock; full fixed-port tests run only when the user app is stopped.
