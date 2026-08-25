# Phase 7 — Plugin Host: Design

- **Date**: 2026-08-23
- **Status**: approved, ready for implementation planning
- **Tickets**: DCL-090, 091, 092, 093, 094, 095, 096, 097
- **Branch**: `feat/phase-7-plugin-host` (from `main`, which carries Phase 6)
- **Context**: `2026-08-23-phase-7-9-roadmap.md`

## Goal

Make "every capability is a plugin in its own subprocess" real, for the one
plugin v0.1 actually ships (doc-intel, Phase 8), without building an app store.

Concretely: the core can discover a plugin shipped with the application, start
it in an isolated process, ask it what it can do, call it, survive it crashing,
turn it off, and expose selected capabilities to the brain as ordinary typed
tools.

## Non-goals

- Installing, updating, or uninstalling third-party plugins (roadmap decision 2)
- Runtime signature verification. v0.1 loads only plugins inside the
  application's own `plugins/builtin/` directory, which is a stronger
  restriction than verifying a signature. `signing.py` is untouched and waits
  for the install flow.
- The plugin credential API (DCL-071 / 072 / 073). A parser plugin needs no
  secrets, so there is nothing to build against.
- Defending against deliberately malicious plugin code. See *Honest
  limitations*.
- Concurrent requests to one plugin process. One in flight at a time.

## Architecture

```
                 core process                     |     plugin process
                                                  |
  brain (LangGraph)                               |
      |  StructuredTool                           |
      v                                           |
  ToolRegistry ---- PluginTool (proxy) ---.        |
      ^                                    \      |
      |                                     v     |
  declaw chat / CLI ---- PluginHost ---> Supervisor|
                              |               |   |
                              |          PluginProcess
                              |               |   |
                       PermissionEnforcer     |  stdin/stdout: NDJSON frames
                       GrantStore             |  stderr: logs -> loguru
                       PluginState (JSON)     |   |
                       AuditLogger            +---+--> declaw_plugin_sdk.bootstrap
                                                  |        loads entrypoint.py
                                                  |        runs BasePlugin
```

Nine modules, each with one job:

| Module | Job |
| --- | --- |
| `declaw/plugin_host/loader.py` | Discover plugin dirs, load + validate manifests (DCL-090) |
| `declaw/plugin_host/state.py` | Enabled / disabled / quarantined, persisted as JSON (DCL-091, 095) |
| `declaw/plugin_host/protocol.py` | Frame models and error codes (DCL-093) |
| `declaw/plugin_host/ipc.py` | NDJSON framing over a stream pair, size-capped (DCL-093) |
| `declaw/plugin_host/process.py` | Spawn with a scrubbed environment, own the pipes (DCL-092) |
| `declaw/plugin_host/supervisor.py` | Restart with backoff, quarantine, timeouts (DCL-096, 097) |
| `declaw/plugin_host/schema.py` | JSON Schema → pydantic model, restricted subset |
| `declaw/plugin_host/tools.py` | `PluginTool`: a `DeclawTool` that forwards over IPC |
| `declaw/plugin_host/host.py` | `PluginHost` facade — the only thing the app touches |

Plus `declaw_plugin_sdk/` as a separate top-level package (DCL-094).

## 1. Process model and isolation (DCL-092)

Spawn:

```
sys.executable -m declaw_plugin_sdk.bootstrap <plugin_dir>
```

with `cwd` set to the plugin directory and an environment built from scratch —
not inherited, not filtered:

| Variable | Why |
| --- | --- |
| `PATH` | Python needs it to locate its own runtime pieces |
| `SystemRoot` (Windows) | Required for sockets and SSL; omitting it breaks Python on Windows |
| `TEMP` / `TMP` | `tempfile` needs a writable location |
| `HOME` (POSIX) | Same |
| `PYTHONIOENCODING=utf-8` | Deterministic encoding, matters for French content on Windows |
| `PYTHONUNBUFFERED=1` | Frames must not sit in a buffer |
| `DECLAW_PLUGIN_NAME` | Identifies the plugin in its own logs |

Nothing else. No `DECLAW_*` settings, no `OLLAMA_*`, no credentials, no user
environment.

**Stdout hygiene.** A stray `print()` in plugin code would corrupt the protocol
stream. At bootstrap, before importing the plugin's entrypoint:

```python
protocol_fd = os.dup(1)     # keep the real stdout for frames
os.dup2(2, 1)               # anything written to stdout now goes to stderr
```

The plugin's stderr is read by the host and forwarded to loguru at DEBUG,
tagged with the plugin name. **A dedicated background task drains it for the
whole process lifetime** — an undrained stderr pipe fills its OS buffer and
then blocks the plugin mid-write, which would look exactly like a hang. The
drain task is started with the process and cancelled only after the process
has exited.

**Import boundary.** The bootstrap installs a `sys.meta_path` finder at index 0
that raises `ImportError` for `declaw` and anything under `declaw.`. This
enforces the architectural contract — a plugin author cannot accidentally reach
into core internals — and is not a security control. See *Honest limitations*.

## 2. IPC protocol (DCL-093)

Newline-delimited JSON, one object per line, on the protocol fd. Chosen over a
length-prefixed binary framing because JSON escapes newlines already, so NDJSON
is unambiguous, and because a corrupted stream stays human-readable in a log.

Maximum frame: **32 MB**. Set as `limit=` on the asyncio stream reader so an
oversized line raises instead of buffering without bound. The SDK checks its
own outgoing frame size and returns a `result_too_large` error rather than
writing a frame the host will reject.

**Request** (host → plugin):

```json
{"v": 1, "id": "<uuid4>", "method": "describe|invoke|shutdown", "params": {}}
```

**Response** (plugin → host):

```json
{"v": 1, "id": "<uuid4>", "ok": true,  "result": {}}
{"v": 1, "id": "<uuid4>", "ok": false, "error": {"code": "...", "message": "..."}}
```

Error codes: `unknown_method`, `unknown_capability`, `invalid_args`,
`capability_failed`, `result_too_large`, `internal`.

`describe` returns:

```json
{
  "name": "doc-intel",
  "version": "0.1.0",
  "sdk_version": 1,
  "capabilities": [
    {
      "name": "parse",
      "description_en": "Parse a document into text chunks.",
      "description_fr": "Analyse un document en fragments de texte.",
      "requires": ["filesystem.read"],
      "exposed_to_model": false,
      "produces_external_content": true,
      "timeout_s": 300,
      "args_schema": { "...JSON Schema..." }
    }
  ]
}
```

`invoke` takes `{"capability": "...", "args": {...}}` and returns any
JSON-serialisable value.

**`exposed_to_model` is load-bearing.** Not every capability should be a chat
tool. `doc-intel.parse` is infrastructure the indexer calls; the model must
never see it. Only capabilities with `exposed_to_model: true` are registered as
brain tools. Everything else is reachable solely through
`PluginHost.call(plugin, capability, args)`.

**Concurrency.** One request in flight per process; further calls queue behind
it. Parsing is CPU-bound, so serialising is what you would want anyway, and it
makes cancellation semantics trivial. Frames carry an `id` regardless, so
moving to a process pool later is additive.

**Version negotiation.** `v` and `sdk_version` are compared at handshake; a
mismatch fails the load with a readable message instead of a confusing runtime
error.

## 3. Capability → tool bridge

The SDK declares capability arguments as a pydantic model. `describe` ships
`model_json_schema()`. The host reconstructs a pydantic model with
`pydantic.create_model` from a **restricted subset** of JSON Schema:

- top level must be a flat `object`
- property types: `string`, `integer`, `number`, `boolean`, `array` of `string`
- `required`, `default`, `description`, and `enum` of strings are honoured
- anything else — nested objects, `$ref`, `oneOf`, tuples — is rejected at load
  with `PluginSchemaError` naming the offending property

The restriction is a feature, not a shortcut. Validation then happens
**host-side**, so malformed arguments never reach the subprocess (Principle
#6), and simple flat signatures are what a 3B model actually calls correctly —
the Phase 1 probes are unambiguous on that.

`PluginTool` is a `DeclawTool[ArgsT]` whose `_arun` awaits
`host.call(...)`. It mirrors the fields the registry already understands:
`classification` (declared per capability; defaults to `WRITE` so an
undeclared capability is gated rather than auto-run), bilingual descriptions,
and `produces_external_content` so the sanitizer wrapper applies unchanged.

One combination is refused at load time: a capability that is
`exposed_to_model` **and** non-READ **and** `produces_external_content`.
`ToolRegistry.langchain_tools` currently wraps READ external-content tools with
the sanitizer and non-READ tools with confirmation, but never composes both —
so such a capability would silently reach the model unsanitized. No plugin
needs that shape, so the loader rejects it with an explicit error rather than
leaving a quiet hole for a future plugin to fall into.

Tool names are prefixed with the plugin slug, dashes to underscores:
`doc-intel` + `search` → `doc_intel_search`. A plugin therefore cannot shadow
`filesystem_read`, and `ToolRegistry`'s existing duplicate check catches
collisions between plugins.

Capability names are validated as slugs (`^[a-z][a-z0-9_-]{1,50}$`) at load
time. This is not cosmetic: the name becomes a tool name sent to the model, and
Ollama's function-calling schema restricts what characters may appear there. A
capability with a name outside the pattern fails the load with the name quoted
in the error.

`ToolRegistry` gains `register_instance(tool)` — the current `register()` takes
a class and instantiates it, which does not fit proxy tools bound to a specific
plugin and capability.

## 4. Permissions (DCL-081 reuse, DCL-097)

Each capability declares `requires: [PluginPermission]`.

**At load time**, the host checks that every capability's `requires` is a
subset of the manifest's `permissions.requested`. A plugin that declares a
capability needing a permission its manifest never asked for is **refused
entirely** — it does not start. This is where DCL-097's "permission violation"
actually lives.

**At invoke time**, `PermissionEnforcer.require()` runs for each required
permission before the frame is written. Denials raise `PermissionDeniedError`,
which reaches the model as a tool error through the existing
`handle_tool_errors` path, and lands in the audit trail as `denied_call`.

**Files are opened by the plugin, not shipped over IPC.** The host resolves and
validates the path with `_resolve_in_workspace` first, then passes the
validated absolute path. The alternative — reading bytes in the core and
base64-ing them — would mean a 67 MB frame for a 50 MB PDF.

**Who grants, on a fresh install.** `plugin_grants.json` starts empty, so on
first run `doc-intel` would hold `filesystem.read` as *requested but not
granted* and every call would fail — and the permission dialog that would fix
that is Phase 9 work. Phase 7 has to answer this itself.

v0.1 answer: **builtin plugins are auto-granted the permissions their manifest
requests, on first load, transparently.** The justification is narrow and
should not be generalised — a builtin plugin ships inside the application
binary, so a user who does not trust it cannot trust DeClaw either; there is no
separate trust decision to ask about. Transparency is what makes this
acceptable rather than a silent grab:

- each auto-grant emits the normal `PluginPermissionEvent` with
  `action="granted"`, so it appears in the audit trail and the daily report
- `declaw plugins list` shows every plugin's permissions and their grant state
- `declaw plugins revoke <plugin> <permission>` works, and a revoked permission
  is **not** re-granted on the next start — auto-grant applies only to
  permissions never seen before, tracked in `plugin_state.json`

**This must not survive into the third-party install flow.** When plugins can
come from outside the application, auto-grant is exactly the wrong default and
the install-time dialog becomes mandatory. Recorded in the roadmap's deferred
list.

**Reframing DCL-097, honestly.** The ticket says a permission violation kills
the process. That presumes a plugin → host callback channel, which the thin
design does not have: a plugin cannot ask the core for anything, so it cannot
ask for something it may not have. Runtime permission violations are
structurally impossible in v0.1.

The terminate-and-quarantine machinery is still built, and its real runtime
trigger is **protocol violation**: an oversized frame, an unknown method, a
response with no matching request id, or unparseable output. Three protocol
violations **within one process lifetime** kill and quarantine the plugin; the
counter resets on restart, matching how crash counters behave. The acceptance
criterion is written to match what actually happens rather than what the ticket
assumed.

## 5. Lifecycle, crashes, quarantine (DCL-091, 095, 096)

**Discovery** scans only `plugins/builtin/*/plugin.yaml` in v0.1. The user
plugin directory is deliberately not scanned: scanning it would be a
third-party install path by file copy, with no signature check, which is
exactly what decision 2 excludes.

Resolving where that directory *is* needs care, because `plugins/` sits at the
repository root while `[tool.hatch.build.targets.wheel]` packages only
`declaw` — so the path that works in a git checkout does not exist in an
installed wheel. Resolution order: a new `builtin_plugins_dir` setting if set,
else `<package parent>/plugins/builtin` (the development checkout), else a
directory shipped beside the executable (the packaged app). A missing directory
is not an error — the host logs it and loads nothing. Making `plugins/builtin`
actually ship inside the distribution is Phase 14 packaging work; the setting
is the seam that lets Phase 14 solve it without touching the loader.

**State** lives in `<data_dir>/plugin_state.json`, alongside the existing
`plugin_grants.json` and for the same reason: this is the user's own policy,
and being able to read and diff it is a transparency feature, not an
implementation detail. Four fields per plugin: `enabled`, `quarantined`,
`quarantine_reason`, `last_version`. This replaces DCL-095's `installed.db` —
one JSON file beats a second SQLite database with its own migration chain for
four fields.

Crash counters are deliberately **not** persisted. A restart of DeClaw gives a
misbehaving plugin a fresh chance; if it still crashes, it is re-quarantined in
under a minute. Quarantine itself does persist, because clearing it should be a
deliberate user action.

**Supervision**: on unexpected exit, restart with exponential backoff
1 → 2 → 4 → … → 60 s. Three crashes within five minutes → quarantine: the
process stays down, `enabled` is untouched, `quarantined` is set with a reason,
a `PluginLifecycleEvent` is emitted, and the user is told through the same
notice channel the sanitizer uses for quarantined content.

**Timeouts**: per-capability, default 120 s, hard cap 600 s. On timeout the
process is killed and restarted and the caller gets a `PluginTimeoutError` —
because there is no reliable way to cancel work already running inside the
subprocess.

**In-flight requests** when a process dies get `PluginCrashedError`, which
reaches the model as a recoverable tool error.

**Shutdown** is graceful then forced: send the `shutdown` frame, wait 5 s for
the process to exit on its own, then `terminate()`, wait 2 s, then `kill()`.
Note for Windows: killing a process does not kill its children. No v0.1 plugin
spawns children, and the loader has no way to stop one that does — recorded as
a known limitation rather than papered over.

## 6. The SDK (DCL-094)

`declaw_plugin_sdk/` is a top-level package in this repository. Its only
dependency is pydantic. **It must not import `declaw`** — the import hook
blocks `declaw.*`, so an SDK living inside `declaw/` could not be imported by
the very processes it exists to serve.

Packaging: `[tool.hatch.build.targets.wheel]` currently lists
`packages = ["declaw"]` and must become `["declaw", "declaw_plugin_sdk"]`,
otherwise the bootstrap module is missing from any installed build and every
plugin fails to start with an import error that says nothing useful.

Surface:

```python
class BasePlugin:
    name: str

@capability(
    name="parse",
    description_en="...", description_fr="...",
    requires=[...], timeout_s=300,
    exposed_to_model=False, produces_external_content=True,
    classification="read",
)
async def parse(self, args: ParseArgs) -> ParseResult: ...

def run(plugin: BasePlugin) -> None:      # the stdio loop
```

Decorator defaults, chosen so that forgetting an argument fails safe:
`requires=[]`, `timeout_s=120`, `exposed_to_model=False` (invisible to the
model unless deliberately published), `produces_external_content=False`, and
`classification="write"` (gated behind confirmation unless deliberately
declared read-only).

`python -m declaw_plugin_sdk.bootstrap <plugin_dir>` reads `plugin.yaml`,
imports the entrypoint module, finds the single `BasePlugin` subclass,
installs the isolation hook and stdout redirection, and calls `run()`.

## 7. Wiring into the application

`PluginHost` is the only surface the rest of the app touches:

```python
class PluginHost:
    async def start(self) -> None
    async def stop(self) -> None
    def loaded(self) -> list[LoadedPlugin]
    async def call(self, plugin: str, capability: str, args: dict) -> Any
    def model_tools(self) -> list[DeclawTool[Any]]
    async def enable(self, name: str) -> None
    async def disable(self, name: str) -> None
```

`declaw chat` starts the host, merges `host.model_tools()` into the registry
before building the brain, and stops the host on exit. A new CLI group
`declaw plugins list | enable <name> | disable <name> | revoke <name> <perm>`
exposes lifecycle without a UI.

**This forces a restructure of the chat command.** Today `main.py:191` builds
the tool list and the graph *synchronously*, before `asyncio.run(_session())`.
`PluginHost.start()` is async, and asyncio subprocess transports are bound to
the loop that created them — so a host started outside that loop would produce
pipes the REPL cannot use. Registry assembly, `host.start()`, and
`build_brain()` all move inside `_session()`. This is the same constraint the
existing comment about `ensure_schema` and aiosqlite already documents, for the
same reason; the fix is to extend the pattern, not invent one.

**The tool list is bound once, at chat start.** Disabling or quarantining a
plugin mid-session does not remove its tools from the running graph — rebinding
would mean rebuilding the graph under the model. Instead the proxy tool returns
a `PluginUnavailableError` as an ordinary tool error, which the model can
report to the user. Live rebinding belongs to the Phase 9 gateway, where
sessions are already explicit objects.

## 8. Data, files, and audit

New files on disk: `<data_dir>/plugin_state.json`.

New audit event: `PluginLifecycleEvent` added to the discriminated union in
`declaw/audit/events.py`, with `event_type = "plugin.lifecycle"`, fields
`plugin`, `version`, `action` (`started` | `stopped` | `crashed` | `restarted`
| `quarantined` | `enabled` | `disabled` | `load_failed`) and `detail`.
`declaw/audit/summary.py` gains bilingual templates so these appear in the
natural-language report.

Capability invocations need no new event type: proxy tools are ordinary
registry tools, so the existing audit wrapper already records them.

## 9. Incidental cleanup, in scope

- Promote `_resolve_in_workspace` from `tools/builtin/filesystem.py` to
  `declaw/tools/builtin/_paths.py`. It has four consumers today and the plugin
  host makes five; the promotion was already flagged as reasonable in DCL-021.

Nothing else. No unrelated refactoring.

## 10. Error handling matrix

| Situation | Result |
| --- | --- |
| `plugin.yaml` invalid | Plugin skipped, `load_failed` audited, others load normally |
| Capability requires an unrequested permission | Plugin refused entirely, `load_failed` audited |
| `args_schema` outside the supported subset | Plugin refused, error names the property |
| SDK / protocol version mismatch | Plugin refused with a readable message |
| Permission not granted by the user | `PermissionDeniedError` → tool error to the model, `denied_call` audited |
| Capability raises | `capability_failed` error frame → tool error to the model; process stays up |
| Invoke exceeds timeout | Kill, restart, `PluginTimeoutError` to the caller |
| Process exits unexpectedly | `PluginCrashedError` to in-flight caller, restart with backoff |
| 3 crashes in 5 minutes | Quarantine, audit, user notice |
| Oversized / malformed / unsolicited frame | Protocol violation; 3 of them kill and quarantine |
| Plugin disabled before chat starts | Not started; its tools absent from the registry |
| Plugin disabled or quarantined mid-session | Tools stay bound; calls return `PluginUnavailableError` as a tool error |
| Capability name is not a slug | Plugin refused, name quoted in the error |
| `plugins/builtin` missing entirely | Logged, nothing loaded, application starts normally |

## 11. Testing strategy

Security-critical, so tests come first (TDD).

**Unit** — deterministic, no subprocess:

- framing: valid roundtrip, malformed JSON, oversized line, missing `id`,
  unknown `method`, unsolicited response
- `schema.py`: every supported type; each unsupported construct rejected with
  the property named
- permission gating: load-time subset check, invoke-time `require()`
- supervisor: backoff sequence, quarantine threshold, timeout path — driven by
  a fake process so no real spawning and no sleeping in real time
- registry integration: proxy tools registered, prefixed, collisions caught

**Integration** — real subprocesses, still deterministic and Ollama-free.
Three fixture plugins under `tests/fixtures/plugins/`:

| Fixture | Proves |
| --- | --- |
| `echo-plugin` | describe → invoke → shutdown; args validated; result returned |
| `crash-plugin` | exits mid-request; caller gets `PluginCrashedError`; restart and quarantine happen |
| `hang-plugin` | never responds; timeout kills and restarts |

The loader takes its search paths as a parameter, so fixtures are never
discovered by the real builtin scan.

**Security** (`tests/security/`):

- a plugin importing `declaw` gets `ImportError`
- a plugin whose stdout is polluted by `print()` still speaks the protocol
- a capability requiring an ungranted permission is denied and audited
- a manifest requesting a permission its capabilities never use is loadable;
  a capability requiring a permission the manifest never requested is not
- spawned environment contains no `DECLAW_*` or `OLLAMA_*` variable

## 12. Honest limitations

Written down because this project's culture is to record measured reality
rather than intent, and because these will be read as guarantees if they are
not.

1. **A malicious plugin is not contained.** It runs with the user's full
   privileges. It can read any file the user can read, open sockets, and remove
   the import hook. What the boundary gives is crash isolation, no shared
   memory, no keyring handle, a scrubbed environment, and a killable process.
   Real containment needs OS-level sandboxing.
2. **Permission enforcement is host-side only.** It governs what the core will
   *do on a plugin's behalf* — which paths it validates, which capabilities it
   dispatches. It cannot stop a plugin from acting directly.
3. **Builtin plugin code is not signature-verified in v0.1.** It ships inside
   the application; if that is tampered with, the core is compromised too.
4. **One request at a time per plugin.** A long parse blocks other calls to the
   same plugin. Acceptable because the core drives indexing and chat-path search
   does not touch the plugin.

## 13. Ticket mapping

| Ticket | Modules | Acceptance as built |
| --- | --- | --- |
| DCL-090 | `loader.py` | Scans `plugins/builtin/`, returns an index with per-plugin status; invalid manifests skipped, not fatal |
| DCL-091 | `state.py`, `host.py` | Enable / disable / quarantine persist across restarts. Install and update are out of scope |
| DCL-092 | `process.py`, SDK `_isolation.py` | Spawned with a scrubbed environment and no keyring; the import hook blocks `declaw.*` as an architectural boundary |
| DCL-093 | `protocol.py`, `ipc.py` | Malformed frames rejected, oversized frames refused, repeated violations kill the plugin |
| DCL-094 | `declaw_plugin_sdk/` | The `echo-plugin` fixture builds against the SDK and runs |
| DCL-095 | `state.py` | `plugin_state.json` survives restarts (JSON, not SQLite) |
| DCL-096 | `supervisor.py` | Killed plugin restarts with backoff; three crashes in five minutes quarantine it |
| DCL-097 | `loader.py`, `supervisor.py` | Permission violations refuse the load; protocol violations kill the process. Both audited |
