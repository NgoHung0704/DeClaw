# DeClaw documentation

Start with current implementation, then follow only the code and tests needed
for your task. Historical completion claims and benchmark counts are not fresh
verification.

## Current context

| Document | Purpose |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Shared instructions and product invariants |
| [Project status](project-status.md) | Current executable behavior and limits |
| [Code map](code-map.md) | Entry points, callers and relevant tests |
| [Architecture decisions](architecture-decisions.md) | Active direction and approved scope |
| [Phase 9 readiness](phase-9-readiness.md) | Source/test assessment, gaps and prerequisites; no implementation approval |
| [Context tools](agent-tools.md) | Serena/Context7 setup and verification boundaries |
| [TICKETS.md](../TICKETS.md) | Backlog; approved specs override superseded acceptance text |

`CLAUDE.md` imports `AGENTS.md`; it is no longer the development diary.
The former diary is preserved in [history](history/claude-context-2026-08-26.md).
The ignored local `DeClaw_CLAUDE_CODE_PROMPT.md` is an original bootstrap prompt,
not current project instructions.

## Specifications and plans

- [Phase 7–9 roadmap](superpowers/specs/2026-08-23-phase-7-9-roadmap.md): approved cross-phase decisions; Phase 9 remains a sketch.
- [Plugin host](superpowers/specs/2026-08-23-phase-7-plugin-host-design.md)
- [Document indexing and retrieval](superpowers/specs/2026-08-23-phase-8a-doc-intel-design.md)
- [Document actions and benchmark](superpowers/specs/2026-08-26-phase-8b-actions-benchmark.md)
- [Architecture explorer](superpowers/specs/2026-08-24-architecture-site-design.md)

Files under `superpowers/plans/` are execution records, not startup reading or
proof that a feature is wired. Preserve them for rationale; do not copy their
long instructions into current context.

## Historical phase reviews

| Phase | Review |
| --- | --- |
| 0 — foundation | [Phase 0](phase-0-review.md) |
| 1 — brain | [Phase 1](phase-1-review.md) |
| 2 — typed tools and confirmation | [Phase 2](phase-2-review.md) |
| 4 — sanitizer | [Phase 4](phase-4-review.md) |
| 5 — memory and audit | [Phase 5](phase-5-review.md) |
| 6 — credentials and permissions | [Phase 6](phase-6-review.md) |
| 7 — plugin host | [Phase 7](phase-7-review.md) |
| 8a — parsing, indexing and retrieval | [Phase 8a](phase-8a-review.md) |
| 8b — actions, reconciliation and benchmark | [Phase 8b](phase-8b-review.md) |

Phase 3 is deferred because v0.1 exposes no shell tool. This does not waive the
Docker isolation requirement if shell execution returns. Phase 9 and subsequent
desktop, hardening and installer work are planned, not completed.

## Architecture viewers

- [docs-site](../docs-site/README.md): React/TypeScript explorer with source-citation guards, built and deployed by GitHub Actions.
- [architecture-site](../architecture-site/README.md): standalone EN/FR/VI Atlas with its own build, tests and owner-private publication workflow.

Both explain the repository; neither is the Phase 9 product UI. They have
separate source and publication workflows. Their prose must be checked against
current code; path guards alone cannot prove semantic accuracy.

Last reviewed: 2026-10-25. See the readiness assessment for checks actually run.
