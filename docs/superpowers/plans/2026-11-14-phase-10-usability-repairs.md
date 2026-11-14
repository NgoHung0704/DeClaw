# Phase 10 usability repairs implementation plan

> **For agentic workers:** Use superpowers:executing-plans task by task with regression tests first.

**Goal:** Repair the user-observed desktop navigation, audit and feedback failures.

**Spec:** [Observed review and reproduction steps](../../history/phase-10-usability-review-2026-11-14.md), within the settled [desktop design](../../specs/2026-11-12-phase-10-tauri-desktop-design.md).

**Architecture:** Keep vanilla JS and the existing Python API. Retain a live Chat view/socket across in-app navigation; discard it on authentication loss. Fetch audit downloads through the authenticated same-origin API and use a download link, retaining native popup denial. Use cursor history for backwards pagination and update all Settings labels after language changes.

**Tech stack:** Existing ES modules, local EN/FR JSON, Node test runner, Python/FastAPI, Tauri WebView2; no new dependencies.

## Global constraints

- Keep `127.0.0.1:7842`, existing auth/CSP/capabilities and default-deny approvals.
- Untrusted text stays in `textContent`; do not replay model/tool/approval actions.
- Preserve the current checkout and review reports; no push or integration commit in this repair task.
- Existing live UI is a baseline until reload; validate source changes after tests.

## Review focus

- Switching pages during a live turn retains socket, draft and cancellation controls.
- Authentication loss closes the retained connection and discards private view state.
- Export handles HTTP/auth failures and reports a result without allowing popups.
- Older/Newer preserve filters and cursor history, including failure and last page.
- Locale updates and tool errors/cancellation show honest localized outcomes.

## Task 1: Repair Chat continuity and feedback

Files: `ui/js/chat.js`, `ui/locales/{en,fr}.json`, `tests/gateway/ui-behavior.test.cjs`.

- [x] Add behavioral tests for Chat → Documents → Chat retaining the socket, draft, transcript and active turn; auth loss must discard them.
- [x] Observe failures with `node --experimental-vm-modules --test tests/gateway/ui-behavior.test.cjs`.
- [x] Retain the live view, add explicit cancelled response feedback and reconcile tool start/end/error activity with fixed labels.
- [x] Run Node regressions; retain pending approval identity and existing default-deny semantics.

## Task 2: Repair Audit workflows and Settings localization

Files: `ui/js/{audit,api,settings}.js`, locales, shared Node behavior tests.

- [x] Add failing tests for authenticated export success/failure without `window.open`, Older/Newer with cursor history, and complete Settings language updates.
- [x] Implement the smallest compatible fixes; improve Audit labels/layout without adding a UI framework.
- [x] Run Node regressions and gateway security tests.

## Task 3: Verify and record

- [x] Run frozen sync, Ruff, mypy, full pytest and Node tests; obtain an independent diff review.
- [x] Reload the actual desktop with the user's existing session and repeat repaired UI scenarios. Record any native download limitation explicitly. Final rebuilt-app JSON/Markdown acceptance and correction of the earlier Downloads-path inference are recorded in the architecture repair report.
- [x] Update status, code map, relevant spec and ticket ledger; append dated evidence without rewriting historical observations.

## Execution notes

The owner requested implementation after the concrete review and repair order;
routine choices above are delegated implementation decisions. Work proceeds
inline on existing `feat/phase-10`, preserving its current source-development
environment. Native lifecycle/pipe findings from the architecture review remain
a separate scope from these usability repairs.

The owner later authorized conditional push after review and then the separate
architecture repairs. That later authorization supersedes the original no-push
constraint for the integrated, verified repair delivery.
