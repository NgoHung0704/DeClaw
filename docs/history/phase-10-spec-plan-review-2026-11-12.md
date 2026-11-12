# Phase 10 spec and plan re-review - 2026-11-12

Scope: documentation review requested by the owner, on `feat/phase-10` at
`ecc615a`. No Phase 10 product code, dependency installation, architecture
ratification, main merge or remote publication is part of this work.

Reviewed: [spec](../specs/2026-11-12-phase-10-tauri-desktop-design.md),
[plan](../superpowers/plans/2026-11-12-phase-10-desktop.md), active decisions,
ticket scope and executable gateway/Application/auth/approval/chat/settings seams.

## Findings and corrections

| Finding | Correction / remaining gate |
| --- | --- |
| Spec described a denied branch creation and uncommitted Phase 9 repairs | Record actual local refs: Phase 10 `ecc615a` on `110e9e7`, main `110e9e7`, Phase 9 `3f1d803`. Task 0 requires latest Phase 9 integration without discarding planning work; this review does not perform that integration. |
| Source-only Windows scope assumed normal native-notification identity/activation | Record the known upstream limitation and add explicit owner decision 7. No developer toast can silently satisfy DCL-144. |
| Native-command restrictions were aspirational rather than a checkable privilege matrix | Specify bootstrap/gateway/tray boundaries, explicit app-command permission/capability setup and launch-lease/liveness rejection; require unchanged CSP proof. |
| Protocol/credential channel direction and errors were underspecified | Align strict parent/child types, UUID/generation rules, byte bounds before decoding, separate correlated token reply pipe and safe diagnostics; one shared vault/fallback store for token and auth. |
| Port/readiness checks could occur after Application startup side effects | Require exclusive exact-port binding before services and ready only after serving the owned socket; test busy-port noninterference. |
| Shutdown and retry could block UI or wait on live chat before cancellation hooks | Add serialized nonblocking supervisor, monotonic budgets, launch-generation checks and live WebSocket/approval shutdown tests. |
| Notification click could remount Chat, replacing its socket or referencing nonexistent views | Focus the existing window first; tests preserve socket/turn/modal/input; stale IDs use safe feedback and no tool replay. |
| Crash termination was liable to be mistaken for generic data recovery | Require owned-write identification, unrelated CLI preservation and a separate architecture decision if durable ownership/schema changes are needed. |
| Native picker wording inherited a nonexistent web file input | Keep current text path field, backend save/restart semantics and explicit environment precedence. |
| Updater/installer/signing research had no implementation-plan deliverable | Add Task 8 release-boundary dossier while preserving open ticket acceptance and owner scope gates. |
| Node verification command omitted the flag used by the current VM-module harness | Use `node --experimental-vm-modules --test tests/gateway/ui-behavior.test.cjs` consistently. |

## Upstream verification and limits

Public documentation queries contained library/platform topics only; no project
documents, source or credentials were sent to Context7. Tauri documentation was
queried through Context7, then the primary capability/notification pages checked
directly. Capability defaults require explicit application-command restrictions;
Windows notification guidance distinguishes installed apps from development
identity. These are documentation observations, not a tested WebView2 build.
See [Tauri capabilities](https://v2.tauri.app/security/capabilities/) and
[Tauri notifications](https://v2.tauri.app/plugin/notification/).

The [Microsoft Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
supports process-group supervision and breakaway/kill-on-close behavior, not a
claim of plugin sandboxing. Existing uvicorn shutdown ordering was inspected in
the installed source; the plan guards the potential connection-drain/lifespan
ordering risk without claiming a reproduced product deadlock.

No Python, Node, Rust or native GUI test was run for this documentation-only
review. Product-test results from earlier Phase 9 reports are not rerun results
for this branch. Checks completed: local links in all five changed Markdown
files; matching protocol names/byte bounds and pending gates in spec/plan;
preserved documentation history anchor; `git diff --check`. All passed.
The ancestry check returned false for `3f1d803` under this branch, confirming
that Task 0 must remain open rather than reporting the dependency integrated.

## Review outcome

Independent read-only builder review found no material defects beyond the
explicit execution gates. It compared the revised documents with selected
executable lifecycle, approval, workspace and Chat-routing behavior; it made no
edits and ran no product tests. The remaining gates are Phase 9 maintenance
integration, all seven owner decisions (including Windows notification scope),
and any later durable recovery-ownership decision required by evidence.

All seven owner decisions remain pending; document review is not permission to
begin implementation or install software. No Phase 10 ticket is marked complete.
The final local consistency checks passed after recording this outcome. Changes
remain uncommitted on `feat/phase-10`; main and Phase 9 refs are preserved.

## Subsequent owner-delegated decisions ? 2026-11-12

After the review above, the owner explicitly delegated selection of the seven
spec decisions. The agent selected the thin shell, owned core, Job Object/private
IPC, paste-once login, close-to-tray/explicit Quit, source-development delivery
and deferral of installed notification identity/activation to Phase 14. See spec
section 10 for rationale and boundaries. Earlier pending-decision statements in
this report describe the review before this delegation. The spec, plan, decision
index, documentation index and ticket scope note now reflect the selected scope.
No product code, dependency installation, branch integration, commit or push was
performed in this decision update. Product tests were not run (docs only).
