# DeClaw documentation

The root README introduces the product; this file indexes contributor context.

| Read | Purpose |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Shared instructions and invariants |
| [Project status](project-status.md) | Current behavior, gaps and limits |
| [Code map](code-map.md) | Source entry points and relevant tests |
| [Architecture decisions](architecture-decisions.md) | Active decisions and rationale |
| [Phase 9 design](specs/2026-11-08-phase-9-gateway-web-ui-design.md) | Ratified gateway/UI contracts |
| [Phase 9 manual checklist](phase-9-review.md) | Browser acceptance still to verify |
| [Context tools](agent-tools.md) | Serena/Context7 setup and verification |
| [Ticket ledger](../TICKETS.md) | Delivered, partial, planned and deferred scope |

## Reference

- [Approved specs](specs/) include the [Phase 7–9 roadmap](specs/2026-08-23-phase-7-9-roadmap.md); the [Phase 9 gateway/UI design](specs/2026-11-08-phase-9-gateway-web-ui-design.md) is a ratified record, implemented on `feat/phase-9-gateway-web-ui` (see the [Phase 9 baseline](history/phase-9-baseline-2026-11-08.md)).
- The phase reviews listed below preserve dated explanations, examples and results.
- [Python baseline](history/python-baseline-2026-10-25.md) records the DB fix and checks actually run.

Historical results are not fresh measurements. Source and current wiring take precedence.

## Phase 10 planning (decisions settled)

- [Desktop specification](specs/2026-11-12-phase-10-tauri-desktop-design.md)
- [Desktop implementation plan](superpowers/plans/2026-11-12-phase-10-desktop.md)
- [Documentation re-review, 2026-11-12](history/phase-10-spec-plan-review-2026-11-12.md)
- [Implementation progress, 2026-11-13](history/phase-10-implementation-2026-11-13.md)
- [Desktop acceptance checklist](phase-10-review.md)
- [Source run guide](../tauri/README.md)
- [Release-boundary dossier](phase-10-release-boundaries.md)

Seven architecture/scope decisions were settled under explicit owner delegation
on 2026-11-12. Implementation is in progress on the integrated Phase 9 maintenance
baseline; open acceptance is tracked separately. Installed native-notification
acceptance remains at Phase 14. Historical results remain dated.

## Specifications and maintenance

- [Phase 7 plugin host](specs/2026-08-23-phase-7-plugin-host-design.md)
- [Phase 8a document intelligence](specs/2026-08-23-phase-8a-doc-intel-design.md)
- [Phase 8b actions and benchmark](specs/2026-08-26-phase-8b-actions-benchmark.md)
- [Phase 9 repository maintenance design](specs/2026-11-12-phase-9-maintenance-design.md)
- [Phase 9 maintenance plan](superpowers/plans/2026-11-12-phase-9-maintenance.md)
- [Phase 9 maintenance evidence](history/phase-9-maintenance-2026-11-12.md)

## Dated phase reviews

- [Phase 0 foundation](phase-0-review.md)
- [Phase 1 brain](phase-1-review.md)
- [Phase 2 tools](phase-2-review.md)
- [Phase 4 sanitizer](phase-4-review.md)
- [Phase 5 memory](phase-5-review.md)
- [Phase 6 audit and credentials](phase-6-review.md)
- [Phase 7 plugin host](phase-7-review.md)
- [Phase 8a documents](phase-8a-review.md)
- [Phase 8b actions and benchmark](phase-8b-review.md)
- [Phase 9 manual acceptance checklist](phase-9-review.md) (open checks, not a completed review)

## Phase 9 implementation history

- [Pre-implementation readiness assessment, 2026-10-25](phase-9-readiness.md)
- [Original gateway/UI plan, completed](superpowers/plans/2026-11-08-phase-9-gateway-web-ui.md)
- [Original delivery baseline, 2026-11-08](history/phase-9-baseline-2026-11-08.md)
- [Regression repair plan, completed](superpowers/plans/2026-11-10-phase-9-repairs.md)
- [Regression repair evidence, 2026-11-10](history/phase-9-repairs-2026-11-10.md)
- [Renewed verification and owner visual feedback, 2026-11-12](history/phase-9-verification-2026-11-12.md)

## History

The long Claude diary, plans predating the 2026-10-25 cleanup and optional
architecture sites were removed from the working tree. Their tracked versions
remain in commit `5f168db`. The later Phase 9 plans listed above are retained as
historical records; their original task checkboxes are not the current backlog.
Recover the diary with `git show 5f168db:docs/history/claude-context-2026-08-26.md`.
The ignored original bootstrap prompt is superseded; `CLAUDE.md` imports `AGENTS.md`.
