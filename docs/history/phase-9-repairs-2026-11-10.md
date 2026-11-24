# Phase 9 repair validation — 2026-11-10

Source: uncommitted repairs on `feat/phase-9-gateway-web-ui`, based on
`f14c7c1`. This is a dated Windows/Python 3.12.13/Node 24.16.0 validation
record, not a guarantee for other machines or future changes.

## Repairs

1. Move shared UI state/helpers into `ui/js/core.js`; the `app.js` entry loads
   page modules only after shared exports are initialized, then bootstraps.
2. Mint/reuse the OS-vault token in `declaw start` and deliver it only on the
   console, never through a logger, URL or browser storage.
3. Initialize Documents progress before attaching it to the page.
4. Resolve the persisted workspace in the cold `get_settings()` factory so
   Application, watcher, plugin parsing, indexing and path containment agree.
   Preserve original environment provenance for SettingsService composition;
   no browser request mutates or clears the singleton.
5. Render the authoritative chat final answer and sources before ending its
   assistant bubble.
6. Keep the assistant bubble separately from tool progress entries so tool
   execution cannot discard subsequent answer deltas.
7. Render flat audit events as returned by the REST API, rather than reading
   a nonexistent nested `payload`.
8. Give gateway-owned quarantine, plugin and network emitters the task-aware
   logger at Application construction; CLI logging behavior is unchanged.
9. Validate authentication before allocating REST rate buckets and discard
   buckets whose sessions have been dropped or expired.

## Verification

Regressions were observed failing before their fixes: module initialization,
Documents initialization, final answer/citation and post-tool rendering,
audit details, startup token delivery, cold workspace containment,
quarantine/network task correlation and forged-cookie bucket allocation.

| Command | Result |
| --- | --- |
| `uv sync --frozen` | Checked 161 packages |
| `uv run ruff check .` | Passed |
| `uv run mypy declaw declaw_plugin_sdk` | Passed, 121 source files |
| `uv run pytest tests/gateway tests/unit/test_config.py tests/unit/test_app_lifecycle.py -q` | 216 passed |
| `uv run pytest -q` | 1052 passed, 1 skipped; 85.44 seconds |
| `node --experimental-vm-modules --test tests/gateway/ui-behavior.test.cjs` | 5 passed |

Node's built-in runner executes the shipped module graph against a minimal
DOM and controlled REST/WebSocket transports. CI now runs those regressions
with Node 22, without a frontend build or new package dependencies.

The restricted Windows runner initially hung while Python created its
internal socket pair (`asyncio`/`TestClient`), before product requests ran.
The successful Python async runs used the permitted loopback-capable runner,
with `TEMP`/`TMP` directed to `.cache/test-tmp` and uv's cache to `.cache/uv`.
Tests of startup/login use an in-memory vault; they do not rotate or expose
the user's credentials.

## Limits and handoff

No live Ollama chat, real-browser layout/XSS checklist or packaged build was
verified in this repair run. The existing manual checklist remains necessary.
The running gateway was not restarted and no commit or publication was made.
Restart it to pick up Python changes, then reload the browser with Ctrl+F5.
Use the token printed by the restarted `uv run declaw start` to connect.
`declaw stop` remains deferred; Ctrl+C stops the foreground gateway.

## Subsequent UI refinement on the same date

The requested visual pass adds a slate/lavender workspace theme with shared
CSS tokens, sidebar navigation, responsive forms/tables, labeled message
roles, an empty-chat introduction, connection/working feedback and a multiline
composer. Fonts/assets remain local; no framework, CDN or package was added.
Enter sends, Shift+Enter inserts a line, and IME composition does not submit.
Pending-turn sends are guarded, cancellation waits for an active turn ID,
and a rate-limit rejection restores the Send control.

Validation after this pass: 7 Node behavior tests passed; the full Python
suite passed with 1052 passed / 1 skipped in 80.79 seconds; ruff and mypy
passed. Text contrast for the shared primary/secondary/action pairs was
measured between 7.28:1 and 15.43:1. The actual running gateway's unauthenticated
Connect and Chat layouts were inspected in the in-app browser at desktop and
375px width, with no document-level horizontal overflow at 375px. This was
a layout inspection, not an authenticated live-model chat test; deterministic
WebSocket tests verify the composer behavior. Reload the existing browser tab
with Ctrl+F5 to load the changed local assets.
