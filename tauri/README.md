# DeClaw desktop development (Windows)

This is a source-development shell. Run it from the checkout that built it:
the executable resolves that checkout's `.venv/Scripts/python.exe` and Python/UI
assets. Copying the executable alone does not distribute DeClaw.

## Prerequisites and commands

- Windows with Microsoft C++ build tools (MSVC x64) and Windows SDK. Validation
  used MSVC 14.44.35207 and SDK 10.0.26100.0.
- Rust 1.100.0 with rustfmt/clippy, pinned in `rust-toolchain.toml`.
- WebView2 runtime. Validation used 157.0.4341.46.
- Python 3.12+ and uv. Run `uv sync --frozen` at the repository root.
- Tauri CLI exactly 2.12.4: `cargo install tauri-cli --version 2.12.4 --locked`.
  Tauri/build/plugin crate versions and Cargo.lock are committed separately.

From `tauri/`:

```powershell
cargo tauri dev --no-watch --no-dev-server
cargo tauri build --debug --no-bundle
```

The CLI help was checked for these options. The non-bundling build creates an
executable without an MSI, application installation or notification registration.
`bundle.active` is false. Development does not need npm or a frontend build.

From the repository root, native checks are:

```powershell
cargo +1.100.0 fmt --manifest-path tauri/src-tauri/Cargo.toml --check
cargo +1.100.0 clippy --manifest-path tauri/src-tauri/Cargo.toml --locked --all-targets -- -D warnings
cargo +1.100.0 test --manifest-path tauri/src-tauri/Cargo.toml --locked
```

Run Python/Node checks from [AGENTS.md](../AGENTS.md) too. Native tests need the
checkout's synchronized Python environment; process tests use fake cores and
temporary files under ignored `.cache/`. Windows is the only supported target
for this phase. No macOS/Linux support is implied.

## Behavior and troubleshooting

The shell owns its Python core and descendants. Only `127.0.0.1:7842` is
accepted; an occupied port is a conflict. Stop the other service yourself rather
than attaching to it. The desktop never selects a different port or kills an
unrelated process. Ollama/model unavailability does not prevent opening the UI.

Close hides a window to the tray. Tray Open focuses the gateway; Status and
login reopens the trusted bootstrap. Explicitly reveal the token there and paste
it into the existing login form. Native credential/lifecycle commands are not
granted to gateway content. Quit stops owned work and then exits. Forced Job
termination cannot guarantee flushed audit writes or completed indexing.

Workspace Choose folder fills the existing candidate field. Save still goes
through gateway validation; the effective workspace changes after restart and
environment overrides remain authoritative.

Native notice events are bounded and filtered, but installed Windows toast
identity/activation is deferred to Phase 14. Existing in-app approvals remain
authoritative; native notices cannot approve or replay a tool.

See the [acceptance checklist](../docs/phase-10-review.md),
[implementation report](../docs/history/phase-10-implementation-2026-11-13.md)
and [release boundaries](../docs/phase-10-release-boundaries.md).
