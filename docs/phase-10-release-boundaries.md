# Phase 10 release boundaries

Decision date: 2026-11-12; implementation handoff updated 2026-11-13.
Authority: [desktop design, section 10](specs/2026-11-12-phase-10-tauri-desktop-design.md#10-settled-decisions--2026-11-12).
Phase 10 delivers a Windows source-development shell. These release tickets
remain open; this dossier is not an installed/signed release acceptance record.

| Item | Phase 10 deliverable | Evidence required at Phase 14 | Acceptance owner |
| --- | --- | --- | --- |
| DCL-146 updates | Updater absent/disabled; no update network check | Explicit opt-in, signed authenticated channel, version/downgrade policy, interrupted-update rollback and failure tests | Release/security owner |
| DCL-147 Windows MSI | Non-bundling shell build and prerequisite inventory | Clean-machine install/run/uninstall with core, assets, migrations and WebView2; upgrade/rollback; no missing Python checkout | Windows release owner |
| DCL-148 macOS | No support claim or artifact | Native lifecycle supervision alternative, Keychain, webview/CSP, notarization, arm64/x64 matrix, install/upgrade/uninstall | macOS release owner |
| DCL-149 Linux | No support claim or artifact | Process-tree ownership, webview runtime, credential fallback, desktop integration and supported distro/package tests | Linux release owner |
| DCL-150 signing | Keys excluded from repository/application | Key custody, restricted CI signing, certificate/identity choice, rotation/revocation, verified published artifacts | Release/security owner |
| DCL-144 installed notifications | Typed private notices, fixed EN/FR bodies, queue/rate/dedup policy and in-app fallback | Installed identity/branding, OS permission denial, click activation without chat remount, stale IDs, update identity continuity | Windows release owner |

## Distribution inventory and feasibility

- The current executable references its source checkout's Python virtual
  environment. Phase 14 must choose and validate Python/core distribution,
  dependency versions and plugin subprocess executable resolution. An MSI that
  installs only the shell fails acceptance.
- Bundle and locate `ui/`, EN/FR locales, built-in plugin manifests/code/assets
  and Alembic migrations. Validate discovery without a source checkout and
  preserve manifest/signature/grant semantics.
- MSI/WiX feasibility depends on that complete payload and prerequisite policy.
  The current `--no-bundle` build does not test WiX, installer elevation or an
  installed application identity. No installer/registration fixture is approved
  by decision 7 and none is needed to claim this dossier complete.
- Define WebView2 provisioning/offline behavior and MSVC runtime requirements;
  Rust/MSVC/uv are development prerequisites, not a proposed end-user setup.
- Define per-user install/data ownership, paths, workspace retention and explicit
  uninstall choices. Never silently delete user documents, SQLite/vector data,
  audit history or credential-vault entries. Logical deletion is not secure erase.
- Validate migration backup/rollback before binary rollback. Do not roll an old
  core over an incompatible new data schema or replay interrupted tools.
- Signing keys stay outside source/build bundles and are accessible only to
  approved release jobs. No signing keys, model downloads or login autostart are
  introduced by this dossier.

The product owner assigns the named acceptance roles before release. Platform
jobs, installed-notification validation and clean-machine evidence are still
required; a Windows source build cannot close these tickets.
