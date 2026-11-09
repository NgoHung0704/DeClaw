# Phase 9 — manual DOM checklist (post-implementation review)

The repository ships no JavaScript test runner (spec section 17, M5):
server-side CSP and no-inline-script checks run in CI
(`tests/gateway/test_ui_security.py`), but markup-injection and interactive
behavior are verified by this manual checklist. Run against a real
`uv run declaw start` (token from the console) on the loopback URL.

## Markup injection (XSS class deleted at the source)

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
