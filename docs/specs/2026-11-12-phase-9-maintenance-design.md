# Phase 9 repository maintenance

Status: scoped maintenance requested by the owner on 2026-11-12, following
the repository review. No new product phase or security-policy decision.
Base: `110e9e7`, branch `feat/phase-9-gateway-web-ui`.

## Intent and approach

Make contributor documentation describe executable Phase 9 behavior; remove
unused installation requirements and empty deferred sandbox scaffolding;
remove transport ownership from document citations and break the settings
bootstrap import cycle without changing observable behavior.

The owner requested a plan, review, then implementation in this session.
Implementation choices below are maintainer choices, not new owner-ratified
security decisions. Work in the existing clean Phase 9 checkout: the owner
explicitly returned to this branch. Preserve main and Phase 10 refs and files.

Documentation-only cleanup would leave unused dependencies and core-to-gateway
imports intact. A broad package reorganization would touch unrelated working
systems. Use small moves with regression coverage instead.

## Boundaries

- Keep `Application` as shared chat/gateway lifecycle owner. CLI indexing keeps
  its deliberate smaller stack; no unrelated lifecycle rewrite.
- Move `TurnSources`, `current_turn_sources`, and `record_source` unchanged
  from `declaw/gateway/sources.py` to `declaw/documents/sources.py`. Update all
  callers; no forwarding module unless a real compatibility consumer exists.
- Extract file-value parsing and saved-workspace resolution into
  `declaw/settings_file.py`. It must not import config, settings service,
  application, or gateway. Use the existing loguru logger object for warnings.
  Both config bootstrap and SettingsService reuse it, preserving env provenance,
  invalid-value filtering, fail-closed workspace validation and restart semantics.
  Keep public imports of `InvalidSettingsFileError` from settings_service valid.
- Remove direct docker, playwright, apscheduler and python-multipart requirements
  after confirming no callers, multipart routes or transitive dependants need them.
  Regenerate uv.lock; do not manually prune lock entries or update other pins.
- CI pushes cover main and `feat/**`; PR checks remain. Keep Windows and existing
  Python/Node commands. No deployment or permission expansion.
- Remove only the empty `sandbox_images/*/.gitkeep` files and
  `declaw/sandbox/__init__.py`. Preserve `require_docker_sandbox`, shell isolation
  invariants, Tauri placeholders, fixtures, benchmark helpers and historical reviews.
- Preflight's strict Docker check is already documented in DCL-007; defer changing
  that behavior to a separate task. Removing the unused SDK does not remove the CLI probe.

## Documentation

Correct README status, mark readiness and completed plans as historical, repair
the machine-local ledger link, index all retained reviews/specs/plans, reconcile
DCL-082/084 and audit-correlation wording, clarify that document actions (not all
REST operations) are read-only outside chat. Keep historical measurements dated
and original plan checkboxes as historical instructions rather than claiming
this session watched their red/green execution. Link current delivery evidence.
Refresh stale gateway module docstrings. Record this maintenance's actual checks
and limitations in a dated report and update map/decisions/ticket notes.

## Verification and non-goals

Protect context-local citation isolation/copy/dedup behavior, saved workspace
containment/environment precedence and same-process settings edits. Security
regressions precede the settings extraction. Run targeted checks after each code
change, then one full Python CI sequence plus Node behavior tests and local
Markdown-link checks. Inspect the final diff with a fresh reviewer before handoff.
Do not claim live-browser security acceptance, Linux support or a packaged build.
No automatic push, merge or deletion of local caches/user data.
