# DeClaw documentation

The root README introduces the product; this file indexes contributor context.

| Read | Purpose |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Shared instructions and invariants |
| [Project status](project-status.md) | Current behavior, gaps and limits |
| [Code map](code-map.md) | Source entry points and relevant tests |
| [Architecture decisions](architecture-decisions.md) | Active decisions and rationale |
| [Phase 9 readiness](phase-9-readiness.md) | Reusable services and remaining design work |
| [Context tools](agent-tools.md) | Serena/Context7 setup and verification |
| [Ticket ledger](../TICKETS.md) | Delivered, partial, planned and deferred scope |

## Reference

- [Approved specs](specs/) include the [Phase 7–9 roadmap](specs/2026-08-23-phase-7-9-roadmap.md).
- `phase-*-review.md` files preserve dated phase explanations, examples and results.
- [Python baseline](history/python-baseline-2026-10-25.md) records the DB fix and checks actually run.

Historical results are not fresh measurements. Source and current wiring take precedence.

## History

The long Claude diary, completed plans and optional architecture sites were
removed from the working tree. Their tracked versions remain in commit `5f168db`.
Recover the diary with `git show 5f168db:docs/history/claude-context-2026-08-26.md`.
The ignored original bootstrap prompt is superseded; `CLAUDE.md` imports `AGENTS.md`.
