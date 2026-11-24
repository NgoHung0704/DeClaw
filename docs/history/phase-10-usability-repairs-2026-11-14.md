# Phase 10 usability repairs — 2026-11-14

## Scope and implementation

Repairs the [hands-on review](phase-10-usability-review-2026-11-14.md) on
`feat/phase-10`, based on `4adb31b`. Existing changes and both review reports
are preserved. This report does not close the separate native lifecycle/pipe
findings in the [architecture review](phase-10-architecture-review-2026-11-13.md).

- Chat retains one view and live socket across in-app routing, including draft,
  transcript, active turn and cancellation. No history/tool actions are replayed.
  Authentication loss closes the connection and discards retained private state.
- New conversation explicitly creates a fresh connection, allowing recovery
  after transport loss and application of new-session model/language settings.
  It is disabled while a turn is active. Retained welcome/composer/speaker labels
  refresh locale without rewriting user/model text.
- Cancel adds a localized incomplete-response notice. Tool completion updates
  the running card; cancellation/final/error/connection loss clears orphan
  running activity with an honest fixed outcome label.
- Audit Older/Newer uses cursor history and committed filters, only changing
  history after successful requests. Clear/filter resets the page history.
- Audit exports preflight the existing authenticated same-origin API, then show
  an explicit Save link. The Python route supplies a deterministic filename
  from validated date and Literal format. Native popup/origin policy is unchanged.
  Only a native download-finished signal reports success; preparation alone
  reports that the export is ready.
- Settings Save updates all form labels and feedback in the selected language,
  uses localized field names and prevents overlapping saves.
- Audit uses fixed readable timestamp/event columns, localized time, short IDs
  with full-ID tooltip, and collapsible literal JSON details.

The download preflight and native attachment are two GET requests. Preflight
surfaces HTTP/auth errors but cannot observe a failure in the second request.
The first response body is cancelled; the native browser owns the attachment
request. This is a deliberate compatibility tradeoff without granting a new
native write command or allowing navigation to arbitrary blob origins. A narrow
Tauri download handler accepts only the live gateway view/generation and exact
audit endpoint with two validated query fields. It retains the browser-chosen
absolute destination, refuses an existing path, and sends fixed boolean-only
completion feedback; URLs, paths and payloads are not emitted to UI events.

## Regression evidence

Node tests were added before fixes and observed failing for lost Chat state,
missing auth cleanup/cancel feedback, duplicate activity cards, exports,
pagination and localization. Independent review then found missing explicit
connection recovery and untranslated retained Chat chrome; tests reproduced
those and passed after correction.

The old Python source-text guard requiring the literal substring `day=` was
replaced by executable Node coverage of actual URL/filename/credentials for
both JSON and Markdown. The test-count change is intentional, not a skipped
failure. Existing Python archive/report tests now also assert attachment headers.

| Check | Observed result |
| --- | --- |
| `uv sync --frozen` | Passed; 153 packages checked |
| `uv run ruff check .` | Passed |
| `uv run mypy declaw declaw_plugin_sdk` | Passed; 127 files |
| Node shipped-module behavior tests | 22 passed |
| Full `uv run pytest`, isolated basetemp, cache provider disabled | 1,104 passed, 1 skipped; 77.05 seconds |

The final Python run emitted three upstream Uvicorn/websockets deprecation
warnings; it did not reproduce the earlier aiosqlite thread warnings. An earlier
partial run exposed the obsolete source-text assertion and cache-directory
permission warnings; these are recorded rather than represented as a green run.

The initial source UI repairs did not change Rust. Follow-up native acceptance
required the download handler described above; dependencies, IPC capabilities and
origin/popup grants remain unchanged. The new native boundary regression first
failed for the missing gate, then all five bootstrap-security tests passed.
Locked all-target clippy also passed. Full native tests/build are recorded below
when complete. The export response header needs a core restart to load new Python.

An independent read-only reviewer checked the diff and scoped corrections,
finding no remaining important static issue. It explicitly retained the actual
native download acceptance requirement and the two-request limitation.

## Actual WebView verification

After reloading the live UI, sent `CHAT-RETAINED-OK`, left for Documents and
returned to Chat. The response and an unsent review draft remained visible.
New conversation was present. Audit column readability improvements were
visually observed. The first blob-download attempt showed feedback but did not
produce a named file in default/configured Downloads; that approach was replaced
by direct same-origin attachments rather than reported as successful.

The desktop was stopped through native controls to free port 7842 for the full
suite, then started again to load the new endpoint. In the resumed authenticated
UI, Older enabled Newer and Newer returned to the first page. Changing Settings
to French translated all form controls and feedback; English was restored.
The expandable payload and compact timestamp/event table were observed.

Blob, programmatic direct-link and explicit-link attempts did not produce a named
file in configured Downloads before the native handler. These were not counted
as successes based on a UI banner. The user then quit the app normally so the
native executable could be rebuilt. Actual named-file acceptance remains pending
that rebuilt executable.

## Limits

In-memory navigation continuity is not durable history/crash recovery. Direct
tray-menu Quit/Open, hostile-origin IPC, forced crash, installed notifications,
Office-file tool routing and Documents/Status formatting are not closed by this
repair. The gateway capability/auth/CSP and default-deny approvals remain in
force. No source commit, push or installer action is part of this handoff.

## Conditional pre-push recheck — 2026-11-14

The owner requested another analysis and a push only if acceptable. Fresh frozen
sync, Ruff, mypy, Node (22 tests), Rust formatting and locked all-target clippy
passed. The full native suite passed 17 tests; one worker is marked ignored and
is deliberately invoked by its passing driver. This is fresh evidence after
the old desktop process exited.
The pinned Tauri CLI debug build with `--no-bundle` also passed and produced
the updated desktop executable; no installer was generated. Actual authenticated
download acceptance on that new executable remains open.

The previous full native failure began with `PortConflict`, followed by
`Unavailable`; it was not an unexplained download-handler regression. The old
desktop process was still present at that time. No secrets, ignored caches,
installers or private test fixtures are part of the candidate changes.

The four P2 architecture findings remain open: runtime server errors can skip
application shutdown; event EOF can retain a ready lease; synchronous control
writes can block lifecycle deadlines; and gateway WebView builder failure is
discarded. The runtime/supervisor/Job files are unchanged by these usability
repairs, and the WebView failure branch remains in the modified bootstrap file.
Automated checks do not close those fault-path findings or actual download
acceptance. Until these gates are resolved, the condition for pushing as an
acceptable Phase 10 delivery is not met. No commit or push has been performed.

Follow-up: the owner subsequently authorized all four architecture repairs.
Their changes, independent review and fresh validation are recorded in the
[architecture repair report](phase-10-architecture-repairs-2026-11-14.md).
The paragraph above records the earlier pre-push state; it does not describe
the repaired runtime/supervisor/Job implementation.

Authenticated acceptance on the rebuilt app subsequently passed for JSON and
Markdown; see the linked architecture repair report for file sizes and checks.
Earlier claims that no named file was produced were based on checking the wrong
Downloads directory. The effective WebView destination was `D:\Downloads`, where
the earlier JSON exports were also present. The earlier absence observation is
not evidence that the native handler was necessary to enable downloads.
