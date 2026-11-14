# Current implementation status

Initial source review: 2026-10-25; Phase 9 maintenance review: 2026-11-12.
Runtime claims below follow the current wiring.
The dated maintenance baseline is linked below; this Markdown review is not a
new product-test or model-benchmark run.

| Area | Evidence and current scope |
| --- | --- |
| CLI and agent | `declaw/main.py:chat`, `declaw/brain/repl.py:build_brain`, and `declaw/brain/loop.py` assemble model/tool execution. |
| Filesystem tools | `declaw/tools/registry.py` registers typed tools, confirmation, sanitizer and audit wrappers. |
| Plugin host | `declaw/plugin_host/host.py` and `declaw_plugin_sdk/` implement supervised subprocesses and IPC. This is not an OS sandbox. |
| Document intelligence | `declaw/documents/session.py:build_document_stack` shares index/chat assembly; `plugins/builtin/doc-intel/` parses; core owns embedding, storage, retrieval and actions. |
| Watcher | `declaw/documents/watcher.py` + `declaw/documents/worker.py`: gateway mode starts a loop-safe watcher handoff feeding ONE serialized indexing worker (retry 0s/30s/300s); CLI behavior unchanged; deletion/move reconcile. |
| Memory | Components exist under `declaw/memory/`; `with_memory` is not in the default `build_brain` stack. Do not assume episodic memory is populated by chat. |
| Gateway | `declaw start` runs the hardened loopback uvicorn launcher (`declaw/gateway/app.py`); a full FastAPI surface (auth, Host/Origin, rate/body caps, WS chat with approvals and streaming, REST, events) sits in `declaw/gateway/`. `declaw stop` stays unimplemented (DCL-234). Core wiring is `declaw/app.py` (`Application`, gateway/CLI shared). |
| Desktop and installer | Windows source desktop is in progress under `tauri/` and `declaw/desktop/`: owned core/Job supervision, private IPC, trusted bootstrap/tray and candidate workspace picker. Native build and component/process tests exist; authenticated WebView2 and crash-recovery acceptance remain open. See the [dated progress report](history/phase-10-implementation-2026-11-13.md) and [desktop checklist](phase-10-review.md). Installed notifications/packaging stay at Phase 14. |
| Shell sandbox | Deferred from v0.1; no product shell tool is exposed. |

Phase 0, 1, 2, 4, 5, 6 (buildable core), 7, 8a and 8b completion
is recorded by phase reviews and the ticket ledger. Phase 9 (gateway and web
UI, DCL-120..134) is implemented on `feat/phase-9-gateway-web-ui`; see the
dated [Phase 9 baseline](history/phase-9-baseline-2026-11-08.md).
DCL-071/072/073 remain deferred until a plugin actually needs credentials;
DCL-082 is delivered as the built-in permission panel (the ratified alternative
to first-run consent). The approved Phase 7–9 roadmap supersedes older
ticket assumptions: [roadmap](specs/2026-08-23-phase-7-9-roadmap.md).

## Limits to preserve in proposals

- Chroma text payloads are encrypted; vectors and some metadata are not. SQLite
  is not wholly encrypted. Logical deletion is not a disk scrub.
- HTTP observation covers instrumented core-process `httpx` calls, not every
  process or all network egress.
- The default brain uses context-window trimming. Repair, summarizing compaction,
  memory retrieval and a system prompt must not be described as enabled merely
  because their helpers exist. Inspect `build_brain` and `chat` before changing them.
- Historical sanitizer scores differ substantially between development and
  held-out corpora. Do not turn a dated corpus score into a security guarantee.
- Document organization validates before execution but is not an atomic batch.
  Gateway turns propagate audit task IDs through context; CLI chat does not use
  that gateway turn context. Packaged migrations and memory population remain
  follow-ups recorded in history.

For any new task, verify the relevant row against the current checkout. Update
this file when executable behavior changes; put dated measurements in a separate
report with command, environment and corpus. Do not carry forward old test counts
as current validation.

## Phase 9 readiness and maintenance

The [maintenance report](history/phase-9-maintenance-2026-11-12.md) records the
documentation/dependency cleanup and shared-module boundaries. Document citation
context lives in `declaw/documents/sources.py`; configuration bootstrap and
SettingsService share `declaw/settings_file.py` without importing each other in
a cycle. Empty deferred sandbox scaffolding is removed; shell isolation rules
and the existing preflight Docker-probe limitation are unchanged.

The [2026-11-12 verification report](history/phase-9-verification-2026-11-12.md)
records a completed full Python suite and companion checks. The owner accepted
the visual UI; authenticated real-browser security/interaction acceptance remains
open in the manual checklist. Phase 10's seven architecture choices were settled
under owner delegation; acceptance remains tracked separately.

The Phase 10 usability repairs retain the live Chat view/socket across in-app
navigation, with an explicit New conversation action for fresh settings or a
closed connection. Authentication loss discards retained private state. Audit
uses authenticated same-origin attachments, bidirectional cursor history and
collapsible payloads; Settings updates all localized form labels after saving.
See the [dated usability repair evidence](history/phase-10-usability-repairs-2026-11-14.md).

Desktop fault handling now continues cooperative cleanup after service/server
failures within one shutdown budget, revokes readiness on unexpected event EOF,
and keeps bounded control writes off the lifecycle actor. Failed gateway-window
creation exposes a localized same-core retry in the trusted bootstrap. The
[architecture repair report](history/phase-10-architecture-repairs-2026-11-14.md)
tracks verification and remaining real-WebView acceptance.
The rebuilt app's Stop/Start/Restart and authenticated JSON/Markdown downloads
were observed on 2026-11-14. This does not close the remaining security,
tray-Quit, forced-crash or release acceptance checklist.
The acceptance follow-up restores minimized windows before focus and parents
the native picker to its requesting window. See the [acceptance report](history/phase-10-acceptance-2026-11-14.md)
for the corrected Cancel diagnosis and manual checks.

The [2026-11-10 repair report](history/phase-9-repairs-2026-11-10.md) records
the review regressions and validation. UI page registration now loads shared
state first; Documents, chat final answers/citations and audit event details
have executable Node regressions. `declaw start` supplies the vault-backed
login token on the console. Cold configuration applies the saved workspace to
all consumers, with environment precedence retained. Gateway-owned quarantine
and network emitters use task-correlated audit; invalid cookies allocate no
REST rate buckets.

The browser UI also has a shared dark workspace layout, distinct chat message
roles, localized empty/connection/working states, and a multiline composer.
Send is disabled while a turn is pending; Cancel is enabled only after the
server announces an active turn. UI behavior tests cover keyboard submission
and recovery after a rejected turn, in addition to the repair regressions.

The [readiness assessment](phase-9-readiness.md) identified the reusable CLI
services and the gateway/UI contracts; the [Phase 9 design](specs/2026-11-08-phase-9-gateway-web-ui-design.md)
answered them and was ratified in full (all twelve section-20 decisions) on
2026-11-08. The gateway/UI is implemented on this branch; current limits stay
recorded in the design's section 18 and the [manual UI checklist](phase-9-review.md).

The cold DB factory deadlock found during assessment was fixed in `5f168db`.
`get_sessionmaker()` initializes the engine before taking the shared factory
lock. Factory-first and concurrent cold-start regression tests preserve the
single-engine/single-factory contract. See the
[dated Python baseline](history/python-baseline-2026-10-25.md) for red/green
results and the full 786-pass, one-skip suite result.

## Documentation scope

The optional architecture viewers, site-specific specification and CI site
build/deployment jobs were removed at the owner's request. Documentation is
maintained in Markdown. Python CI and the Phase 9 product UI scope remain.
