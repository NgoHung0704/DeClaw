# Phase 9 — manual DOM checklist (post-implementation review)

Node's built-in test runner executes module bootstrap and key DOM behavior
regressions in CI (`tests/gateway/ui-behavior.test.cjs`, using a minimal DOM).
Server-side CSP and no-inline-script checks run in Python CI
(`tests/gateway/test_ui_security.py`). Real-browser markup-injection, layout
and the remaining interactions are verified by this manual checklist. Run against a real
`uv run declaw start` (token from the console) on the loopback URL.

The 2026-11-10 visual refinement retains local CSS and system fonts. Shared
tokens style the sidebar, forms, tables and approval overlay. Chat distinguishes
user/assistant/tool entries and shows pending/active/disconnected state;
Shift+Enter inserts a line, Enter sends (except during IME composition).
These keyboard/control states are covered by executable Node regressions.

## Markup injection (XSS class deleted at the source)

2026-11-12: the owner accepted the visual UI. This does not check off the
security and interaction items below. The renewed automated Python and Node
results and browser-tool limitation are recorded in the
[verification report](history/phase-9-verification-2026-11-12.md).

- [ ] Chat: send a turn whose model answer contains `<img src=x
      onerror=alert(1)>` and `<script>alert(1)</script>` — the bubble must
      render the raw text (no element ever inserted). Same for `"`
      and `'` quoting.
- [ ] Documents: index a workspace file whose name and content contain the
      same payloads — catalog rows and chat citations render as text.
- [ ] Audit: trigger an audited tool call; the payload column renders the
      JSON (including any attacker-shaped strings) as text.
- [ ] Plugins: a plugin description containing HTML renders as text.
- [ ] Inspect served `/` HTML and all `ui/js/*.js`: no `innerHTML`,
      `outerHTML`, `insertAdjacentHTML`, `document.write`, no inline
      handlers; every insertion goes through `textContent`/`createTextNode`.

## Session and approval surface

- [ ] Connect page: paste-once login sets the cookie; the token never
      appears in the URL, and reloading keeps the session until logout/12 h.
- [ ] Chat WRITE turn: the approval modal shows the tool name and the exact
      validated arguments (canonical dump); Approve executes, Deny does
      not; closing the modal without answering leaves the tool denied
      (timeout deny).
- [ ] Cancel during a streaming turn stops tokens; no `chat.final` follows
      the cancel acknowledgement.
- [ ] Kill the gateway mid-turn: the connection-lost banner appears; the
      task row is FAILED, not COMPLETED.

## Documents / plugins / settings / status honesty

- [ ] Documents page shows the configured workspace path verbatim with a
      Reindex button — there is no folder picker that pretends browsers can
      return server paths.
- [ ] Plugins page: enable shows the "takes effect at the next gateway
      start" badge; disable is immediate.
- [ ] Settings: changing model/language reports "applies to new chat
      sessions"; workspace reports "requires a gateway restart".
- [ ] Status page reflects Ollama down as `reachable: false` (or not
      measured) without spinning.

## i18n

- [ ] Switch language to FR in Settings: nav, page titles, approval modal
      chrome, error messages and status labels switch to French
      (`ui/locales/fr.json`); missing keys fall back to English strings.

## CSP

- [ ] Browser devtools: no CSP violations on any page; the policy contains
      `connect-src 'self' ws://127.0.0.1:<the actual port>`.
