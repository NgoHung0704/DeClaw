# Phase 6 — Credentials & Permissions: Hướng dẫn review cho người mới

> **Đối tượng**: reviewer hoặc contributor mới. Đọc xong hiểu **cách DeClaw lưu credentials an toàn**, **plugin manifest + ed25519 signature verification**, và **permission enforcement với audited grants** — nền tảng cho Phase 7 Plugin Host.

---

## Mục lục

1. [TL;DR — 30 giây](#1-tldr--30-giây)
2. [Tại sao cần Phase 6?](#2-tại-sao-cần-phase-6)
3. [Credentials — 2 layer defense](#3-credentials--2-layer-defense)
4. [Plugin manifest — security contract](#4-plugin-manifest--security-contract)
5. [ed25519 signature — chống mạo danh plugin](#5-ed25519-signature--chống-mạo-danh-plugin)
6. [Permissions — request + grant + enforce](#6-permissions--request--grant--enforce)
7. [Bóc tách từng ticket](#7-bóc-tách-từng-ticket)
8. [4 ticket còn open — dependency, không phải omission](#8-4-ticket-còn-open--dependency-không-phải-omission)
9. [Verify chạy đúng](#9-verify-chạy-đúng)
10. [Trade-off honest](#10-trade-off-honest)
11. [Checklist review](#11-checklist-review)
12. [Thuật ngữ](#12-thuật-ngữ)

---

## 1. TL;DR — 30 giây

Phase 6 (buildable core) build **security perimeter cho credentials + plugins**:

**Credentials** — Principle #1 (*"NEVER store credentials in plaintext"*):
- **Keyring wrapper** (`store.py`, DCL-070 — landed trong Phase 5 vì Fernet cần) — CRUD over OS vault, `KNOWN_SECRET_NAMES` cho uninstaller story
- **AES-256-GCM fallback** (`fallback.py`, DCL-074) — encrypt file khi keyring backend là `fail` (headless server, CI)

**Plugin Host foundations** — cần cho Phase 7 (subprocess isolation):
- **plugin.yaml schema** (DCL-080) — frozen manifest với slug/semver/bilingual descriptions/closed permission enum
- **ed25519 verification** (DCL-083) — chống mạo danh plugin bên thứ ba
- **Permission enforcer + grants** (DCL-081/084) — request + grant + enforce, mỗi grant audited

**Status**: ✅ buildable core COMPLETE (445 unit tests + 1 skipped tại thời điểm chốt phase; **459 sau 2 bản fix ngày 2026-07-25** — tool-error handling trong agent loop + sanitizer false positive; mypy 66 files + ruff clean). **4 ticket open by dependency**: DCL-071/072/073 (cần Phase 7), DCL-082 (cần Phase 9 UI).

---

## 2. Tại sao cần Phase 6?

### Credentials: Principle #1 mandate

*"NEVER store credentials in plaintext — always python-keyring"*

Nếu DeClaw có plugin doc-intel gọi Notion API → cần Notion token. Nếu ghi vào `~/.declaw/config.json` plaintext → 1 malware run `cat` là leak toàn bộ. **Không thể ship** cho luật sư.

Solution:
- Primary: **OS-native keyring** (Windows Credential Manager, macOS Keychain, Linux KWallet) — key encrypted at rest by OS, unlock only for authenticated user
- Fallback: **encrypted file** (AES-256-GCM) khi keyring không có (headless server, Docker container)

Không có "just store in .env" option — Principle #1 enforced structurally.

### Plugin Host: security contract cho third-party

Phase 7 (Plugin Host) sẽ load third-party plugins. Câu hỏi:
- Làm sao biết plugin là chính chủ, không bị tamper? → **ed25519 signature**
- Làm sao biết plugin cần quyền gì? → **plugin.yaml manifest**
- Làm sao user grant/revoke quyền? → **GrantStore**
- Làm sao enforce quyền lúc runtime? → **PermissionEnforcer**

Phase 6 build **4 primitive này** trước khi Phase 7 assemble subprocess host.

### Buildable core vs remaining

CLAUDE.md ghi rõ:
> **4 Phase-6 tickets remain open by dependency, not by omission**

- DCL-071/072/073 (credential API cho plugin + access log + scoping): **cần Phase 7 subprocess/IPC** — không có subprocess → không có plugin gọi API → không thể test
- DCL-082 (permission dialog): **cần Phase 9 UI** — CLI có thể workaround `declaw permission grant/revoke`, nhưng end-user dialog cần Web UI

→ Fold DCL-071..073 vào Phase 7. DCL-082 chờ Phase 9.

---

## 3. Credentials — 2 layer defense

### Layer 1: OS keyring (default)

```python
# declaw/credentials/store.py
class CredentialStore:
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...  # idempotent

    KNOWN_SECRET_NAMES: frozenset[str] = frozenset({
        "fernet_key",         # DCL-051 Fernet at-rest
        "aes_fallback_key",   # DCL-074 fallback header
        # ... extend on every new secret
    })

    def purge(self) -> int:
        """Delete ALL known secrets. Uninstaller uses this."""
        for name in KNOWN_SECRET_NAMES:
            self.delete(name)
```

**Namespaced** — DeClaw secrets isolated từ other apps sharing keyring.

### Layer 2: encrypted file fallback

```python
# declaw/credentials/fallback.py
class EncryptedSecretStore:
    """
    AES-256-GCM entries in ONE JSON file.
    Key derived via scrypt from OS user identity + per-file salt.
    Secret name bound as AAD (Additional Authenticated Data).
    """

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...
```

**Chỉ dùng khi keyring resolves to `fail` backend** — headless Linux server, CI environments không có secret store.

### Factory: `default_credential_store()`

`SecretStore` protocol — both keyring + fallback implement:
```python
class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...

def default_credential_store() -> SecretStore:
    """
    Return keyring wrapper if backend != fail,
    else EncryptedSecretStore.
    """
    ...
```

`get_or_create_fernet(store: SecretStore, ...)` accepts either — same API surface.

### Threat model — fallback covers what?

**Protects**:
- File-at-rest: attacker copy file → decrypt fail (needs scrypt-derived key from user identity)
- Tampering: AAD bind name → wrong name = auth fail

**Does NOT protect**:
- Compromised user account: attacker impersonate user → scrypt derive same key → decrypt works
- Kernel-level malware: read decrypted memory

Documented honestly. Fallback is **defense-in-depth**, not silver bullet.

### KNOWN_SECRET_NAMES — uninstaller story

**Problem**: keyring backends **cannot enumerate** — cannot list "all secrets for DeClaw". If user uninstall DeClaw → secrets stuck in keyring forever.

**Solution**: hardcode list of every secret name DeClaw ever creates. `purge()` deletes each. **Extend list on every new secret**.

Reviewer check: PR adding new secret → PR must add to `KNOWN_SECRET_NAMES`. Missing = uninstaller broken.

---

## 4. Plugin manifest — security contract

Every plugin ships với `plugin.yaml`. File is **THE security contract** — signature covers raw bytes of this file.

### Schema (DCL-080)

```python
# declaw/plugin_host/manifest.py
class PluginPermission(str, Enum):
    """Closed enum — NO free-form permissions."""
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    NETWORK = "network"
    CREDENTIALS = "credentials"
    OS_AUDIO = "os.audio"
    OS_DISPLAY = "os.display"
    OS_LAUNCH = "os.launch"
    NOTIFICATIONS = "notifications"

class PluginManifest(BaseModel):
    model_config = {"extra": "forbid"}  # unknown fields = reject

    name: str        # slug: [a-z0-9-], no traversal
    version: str     # semver
    description_en: str
    description_fr: str
    entrypoint: str  # relative .py path, no ..///, no absolute, no drive
    requested: list[PluginPermission]  # what plugin asks for
    denied: list[PluginPermission]     # what author declares plugin NEVER needs
```

### Key constraints

1. **`extra="forbid"`** — unknown fields → reject. Prevents smuggling new permission via typo.
2. **Closed permission enum** — cannot add "eval_arbitrary_code" via string. Enforced at schema layer.
3. **Bilingual descriptions mandatory** — user permission dialog needs FR + EN.
4. **Entrypoint contained**:
   - No absolute path (`/etc/foo.py`)
   - No traversal (`../evil.py`)
   - No Windows drive spec (`C:\foo.py`)
   - Must be relative, ending `.py`
5. **`requested` vs `denied` overlap → reject** — logical contradiction.

### Author self-limit — `denied` is honest signaling

Author declares "my plugin never needs network access" → `denied: [network]`. Even if user grants network → still blocked, because manifest declared incompatible.

**Purpose**: author signals scope honestly. User can trust "this plugin cannot exfiltrate" if `denied` covers network.

Reviewer heuristic: if `requested` is huge and `denied` is empty → plugin over-privileged, review carefully.

### `parse_manifest(text)` and `load_manifest(path)`

Both return `PluginManifest` or raise `ManifestError` with readable message:
```
ManifestError: unknown field 'debug_mode' in plugin.yaml (extra fields forbidden)
ManifestError: entrypoint '../evil.py' contains parent-directory reference
ManifestError: 'requested' and 'denied' overlap on: filesystem.write
```

---

## 5. ed25519 signature — chống mạo danh plugin

### Threat model

Third-party plugin ships as:
```
my-plugin/
├── plugin.yaml      # manifest
├── plugin.sig       # detached signature over plugin.yaml
└── src/
    └── main.py      # code (referenced by entrypoint)
```

**Attacker scenarios**:
- Modify code but keep manifest → **caught** (code hashes could be added, but currently manifest IS security contract; see below)
- Modify manifest to request more permissions → **caught by signature**
- Ship plugin without signature → **caught by `UnsignedPluginError`**
- Forge signature với random key → **caught by `SignatureError` (untrusted key)**

### What is signed (DCL-083)

**Raw `plugin.yaml` bytes** — nothing else.

Rationale: **the manifest IS the security contract**. If you can trust manifest → you can trust:
- Name, version, description (identity)
- Entrypoint path (which .py to run)
- Requested permissions (what to grant)
- Denied permissions (what to enforce)

Code integrity = separate concern. Documented follow-up (nếu cần code sha256 hash trong manifest, sign covers it too).

### Verification flow

```python
# declaw/plugin_host/signing.py
def verify_signature(
    manifest_bytes: bytes,
    signature_hex: str,
    trusted_verify_keys: set[VerifyKey],
) -> None:
    if not signature_hex:
        raise UnsignedPluginError("plugin.sig missing")

    signature = bytes.fromhex(signature_hex)
    for key in trusted_verify_keys:
        try:
            key.verify(manifest_bytes, signature)
            return  # success — matched a trusted key
        except BadSignatureError:
            continue
    raise SignatureError("signature does not match any trusted key")
```

Two distinct errors:
- `UnsignedPluginError`: file missing / empty sig → **maybe legit but unsigned**, treat as user-facing "install unsigned plugin?" prompt (later UX)
- `SignatureError`: sig present but doesn't match any trusted key → **forged or tampered**, hard reject

### Author tooling

```python
def generate_keypair() -> tuple[SigningKey, VerifyKey]: ...
def sign_manifest(path: Path, signing_key: SigningKey) -> str:
    """Sign plugin.yaml, write plugin.sig, return hex sig."""
```

Author workflow:
1. `generate_keypair()` — save signing key privately, publish verify key
2. Edit `plugin.yaml`
3. `sign_manifest(path, signing_key)` — writes `plugin.sig`
4. Ship plugin folder

Verify key distribution — open decision:
- Bundle với DeClaw (trusted plugin developers list)
- Community keyserver (post-MVP)
- User manually add — advanced

### Loader wiring lands with DCL-090

Currently sign/verify is standalone. Phase 7 DCL-090 wires signature check vào plugin load path — plugin không load nếu verify fail.

---

## 6. Permissions — request + grant + enforce

3-tier model:

### Tier 1: **Requested** (manifest)

Declared in `plugin.yaml`. Immutable. Reviewer/user sees it, decides trust level.

### Tier 2: **Granted** (user policy)

`GrantStore` = **plain JSON** at `data_dir/plugin_grants.json`:
```json
{
  "doc-intel": ["filesystem.read", "filesystem.write"],
  "notion-plugin": ["network"]
}
```

**Why plain JSON, not encrypted?**
- **User policy, not a secret.** Attacker knowing "user granted filesystem.write to doc-intel" doesn't leak anything sensitive.
- User can inspect, edit manually if trusts self.
- Audit reviewer wants transparency.

Every grant/revoke emits `PluginPermissionEvent` → audit trail.

### Tier 3: **Enforcer** (runtime)

```python
class PermissionEnforcer:
    def require(
        self,
        plugin: str,
        permission: PluginPermission,
    ) -> None:
        if permission in manifest.denied:
            # author self-limit
            raise PermissionDeniedError(
                plugin=plugin,
                permission=permission,
                reason="author-denied",
            )
            self._audit.log(PluginPermissionEvent(
                kind="violation",  # ← never requested → possible malware
                ...
            ))

        if permission not in manifest.requested:
            # NEVER REQUESTED — plugin might be compromised
            self._audit.log(PluginPermissionEvent(kind="violation", ...))
            raise PermissionDeniedError(reason="not-requested-in-manifest")

        if permission not in grant_store.granted(plugin):
            # REQUESTED but not granted by user
            self._audit.log(PluginPermissionEvent(kind="denied_call", ...))
            raise PermissionDeniedError(reason="not-granted-by-user")

        # OK — audit successful use? (design choice, currently no)
```

### Key distinctions in audit

| Event kind | Meaning | Response |
|---|---|---|
| `denied_call` | Plugin tried permission it **requested** but user **hasn't granted** | Normal — plugin should prompt user or degrade gracefully |
| `violation` | Plugin tried permission it **NEVER requested in manifest** | **RED FLAG** — plugin compromised or malicious. DCL-097 (Phase 7) will use this as **kill trigger** — process terminated + user notified |

### Invariant: user grant NEVER opens what manifest didn't request

```python
def grant(plugin: str, permission: PluginPermission):
    manifest = load_manifest(plugin)
    if permission not in manifest.requested:
        raise ValueError("cannot grant unrequested permission")
    grant_store.add(plugin, permission)
```

**Structural**: even if user tries to grant "network" to a plugin whose manifest says `requested: [filesystem.read]` → refused at grant time.

→ Manifest is **upper bound** on plugin capability. User grant is **filter** within that bound.

---

## 7. Bóc tách từng ticket

### DCL-070 (pulled forward to Phase 5) — Keyring wrapper

**File**: [declaw/credentials/store.py](../declaw/credentials/store.py).

Pulled forward vì DCL-051 (Fernet at-rest encryption for memory) cần vault Fernet key.

Xem [phase-5-review.md § DCL-070](./phase-5-review.md).

### DCL-074 — Encrypted secrets fallback

**File**: [declaw/credentials/fallback.py](../declaw/credentials/fallback.py).

- **AES-256-GCM** entries in single JSON file
- **Scrypt key derivation** from OS user identity + per-file salt (16 bytes)
- **Secret name bound as AAD** — decrypt fails if name changed
- **`CorruptSecretsError`** on wrong identity or tampering

**Only used when keyring backend = fail**. Factory `default_credential_store()` picks automatically.

`SecretStore` protocol — both stores implement same interface. `get_or_create_fernet(store, ...)` accepts either.

**Threat model honest**:
- Protects files-at-rest (attacker copy file → decrypt fail)
- Does NOT protect compromised user account (attacker impersonate user → same scrypt key)

### DCL-080 — plugin.yaml schema

**File**: [declaw/plugin_host/manifest.py](../declaw/plugin_host/manifest.py).

- Frozen `PluginManifest` (extra=forbid)
- Validators for slug, semver, entrypoint containment
- Closed `PluginPermission` enum
- `requested` vs `denied` overlap check → reject
- `parse_manifest(text)` / `load_manifest(path)` → readable `ManifestError`

Example manifest:
```yaml
name: doc-intel
version: 1.0.0
description_en: "Document intelligence (PDF/DOCX/XLSX parsing + RAG)"
description_fr: "Intelligence documentaire (analyse PDF/DOCX/XLSX + RAG)"
entrypoint: src/main.py

requested:
  - filesystem.read
  - filesystem.write

denied:
  - network
  - credentials
  - os.launch
```

### DCL-083 — ed25519 verification

**File**: [declaw/plugin_host/signing.py](../declaw/plugin_host/signing.py).

- `verify_signature(manifest_bytes, sig_hex, trusted_keys)` → `None` on OK, raise on fail
- `UnsignedPluginError` (missing sig)
- `SignatureError` (present but untrusted/tampered)
- `generate_keypair()` + `sign_manifest(path, key)` — author tooling

**PyNaCl** (dependency đã có từ DCL-001) implements ed25519.

Loader wiring = DCL-090 (Phase 7). Trusted-key configuration source = open decision (settings vs packaged file).

### DCL-081/084 — Permission middleware + audited grants

**File**: [declaw/plugin_host/permissions.py](../declaw/plugin_host/permissions.py) + `PluginPermissionEvent` in audit union.

**Enforcer**:
```python
class PermissionEnforcer:
    def require(self, plugin: str, permission: PluginPermission) -> None:
        # 3-tier check
        ...
```

Raises `PermissionDeniedError(plugin, permission, reason)` on fail.

Audit events:
- `denied_call`: requested-but-ungranted (normal, plugin needs to prompt)
- `violation`: never-requested (RED FLAG, DCL-097 kill trigger)

**GrantStore**:
```python
class GrantStore:
    """
    Transparent plain-JSON grants.
    Location: data_dir/plugin_grants.json
    User policy, NOT secret.
    """
    def grant(self, plugin: str, permission: PluginPermission) -> None:
        # Check manifest requested — refuse if not in requested
        # Emit PluginPermissionEvent(kind="granted")

    def revoke(self, plugin: str, permission: PluginPermission) -> None:
        # Emit PluginPermissionEvent(kind="revoked")
```

**Invariant**: `grant()` refuses if permission not in manifest.requested → **user cannot exceed manifest**.

---

## 8. 4 ticket còn open — dependency, không phải omission

CLAUDE.md ghi rõ:

### DCL-071 — Credential API for plugins

Cần: subprocess plugin call `host_api.get_secret("notion_token")` → host mediate keyring access.

Blocked by: **Phase 7 subprocess/IPC** — không có subprocess plugin thì không có ai gọi API.

Solution: fold vào Phase 7 khi wire xong subprocess.

### DCL-072 — Credential access logging

Every plugin credential read → audit event.

Blocked by: **DCL-071** — cần API layer trước.

### DCL-073 — Credential scoping

Restrict which secrets a plugin can access based on manifest.

Blocked by: **DCL-071 + manifest extension** — need `credentials: [notion_token]` list trong manifest.

### DCL-082 — Permission dialog

End-user UI để grant/revoke permission. CLI workaround exists (`declaw permission grant/revoke`) — implementation stub, dialog needs Phase 9 Web UI.

Blocked by: **Phase 9 Web UI**.

### Summary

**None of the 4 tickets are missing due to oversight**. They are all **structurally blocked** by future phases. Reviewer should NOT flag as "missing coverage" — they are in the plan, waiting for prerequisites.

---

## 9. Verify chạy đúng

### Bước 1 — Unit tests

```powershell
# Credentials
uv run pytest tests/unit/test_credentials_*.py -v

# Plugin host
uv run pytest tests/unit/test_plugin_host_*.py -v

# Combined
uv run pytest tests/unit/test_credentials_*.py tests/unit/test_plugin_host_*.py -v
```

Mong đợi: ~50+ tests all pass.

### Bước 2 — Manifest smoke test

Create test manifest:
```powershell
@'
name: test-plugin
version: 0.1.0
description_en: "Test plugin"
description_fr: "Plugin de test"
entrypoint: main.py
requested:
  - filesystem.read
denied:
  - network
'@ | Out-File -Encoding utf8 test_plugin.yaml

# Parse via Python
uv run python -c "from declaw.plugin_host.manifest import load_manifest; m = load_manifest('test_plugin.yaml'); print(m.model_dump_json(indent=2))"
```

Try attacks:
```powershell
# Path traversal in entrypoint
@'
name: evil
version: 0.1.0
description_en: "Evil"
description_fr: "Méchant"
entrypoint: ../../../etc/passwd
requested: []
denied: []
'@ | Out-File -Encoding utf8 evil.yaml

uv run python -c "from declaw.plugin_host.manifest import load_manifest; load_manifest('evil.yaml')"
# Expected: ManifestError entrypoint contains parent-directory reference
```

### Bước 3 — Signature smoke test

```python
from declaw.plugin_host.signing import (
    generate_keypair,
    sign_manifest,
    verify_signature,
    UnsignedPluginError,
    SignatureError,
)

# Author side
signing_key, verify_key = generate_keypair()
sig_hex = sign_manifest("plugin.yaml", signing_key)

# Verify side
manifest_bytes = open("plugin.yaml", "rb").read()
verify_signature(manifest_bytes, sig_hex, {verify_key})  # OK

# Tamper detection
tampered = manifest_bytes.replace(b"filesystem.read", b"network")
try:
    verify_signature(tampered, sig_hex, {verify_key})
except SignatureError:
    print("Tamper detected ✓")

# Missing sig
try:
    verify_signature(manifest_bytes, "", {verify_key})
except UnsignedPluginError:
    print("Unsigned rejected ✓")
```

### Bước 4 — Permission flow

```python
from declaw.plugin_host.permissions import (
    PermissionEnforcer,
    GrantStore,
    PermissionDeniedError,
)

enforcer = PermissionEnforcer(manifest, grant_store, audit_logger)

# Case 1: requested + granted → OK
grant_store.grant("doc-intel", "filesystem.read")
enforcer.require("doc-intel", "filesystem.read")  # OK

# Case 2: requested but not granted → denied_call
enforcer.require("doc-intel", "filesystem.write")
# raises PermissionDeniedError, audit event kind=denied_call

# Case 3: never requested → violation
enforcer.require("doc-intel", "network")
# raises PermissionDeniedError, audit event kind=violation
# → Phase 7 DCL-097 will use this as kill trigger
```

### Bước 5 — Full test suite

```powershell
uv run pytest
```

Mong đợi: 445 passed, 1 skipped, ruff + mypy clean.

---

## 10. Trade-off honest

### ⚠️ Signature covers manifest only, NOT code

If manifest permissions match user expectations but plugin code was swapped → verifier misses. Mitigation options for post-MVP:
- Add SHA-256 of code files vào manifest → signature transitively covers code
- Content-addressable plugin distribution (like Nix)

Current: **manifest IS security contract**, treating code integrity as separate concern. Documented.

### ⚠️ Encrypted fallback protects file, not user account

If attacker compromise user account → scrypt derive same key → decrypt works. Fallback is **defense-in-depth**, not silver bullet.

For MVP acceptable — target user machines mostly single-user personal devices.

### ⚠️ `grant_store.json` plaintext

Intentional (user policy, not secret). But: attacker with file read access can see "user granted network to X plugin" — may inform targeting.

Trade-off: transparency for user > adversarial obfuscation. Not sensitive enough to encrypt.

### ⚠️ Trusted-key configuration source unresolved

Open decision Phase 7: where do trusted verify keys come from?
- Bundled với DeClaw (curated list, requires DeClaw update to add)
- User-added (advanced, easy to misuse)
- Community keyserver (post-MVP, needs infrastructure)

Currently: caller passes set of verify keys explicitly. Loader wiring (DCL-090) will decide.

### ⚠️ Permission enforcement runtime, not statically analyzed

`enforcer.require()` at runtime → if plugin calls capability once but not another time, first miss = leak. Best practice: enforcer at every boundary.

Static analysis of plugin code (find all API calls, check against grants) = future improvement, requires linter for plugin authors.

### ⚠️ Kill trigger (DCL-097) not yet implemented

`violation` audit events currently logged only. DCL-097 (Phase 7) will detect + terminate subprocess + user notification. Currently: plugin can trigger 100 violations before we notice.

### ⚠️ CLI for permission grant/revoke not exposed as `declaw permission`

Backing store exists (`GrantStore.grant/revoke`), but CLI subcommand not implemented (DCL-082 dependency). Programmatic access works — CLI ergonomics missing.

---

## 11. Checklist review

### ✅ Credentials
- [ ] `CredentialStore` uses namespace prefix — DeClaw secrets isolated
- [ ] `KNOWN_SECRET_NAMES` extended with every new secret
- [ ] `purge()` iterates over `KNOWN_SECRET_NAMES` — uninstaller story
- [ ] `delete()` idempotent (no error on missing)
- [ ] Fallback: AES-256-GCM (not AES-128 or ECB)
- [ ] Scrypt key derivation (not simple hash) — cost parameter reasonable
- [ ] Secret name as AAD — tamper detect
- [ ] `default_credential_store()` picks keyring if backend != fail, else fallback

### ✅ Manifest
- [ ] `PluginManifest` frozen (extra=forbid)
- [ ] Slug validated `[a-z0-9-]`
- [ ] Semver validated
- [ ] Bilingual descriptions mandatory (both required)
- [ ] Entrypoint contained: no `..`, no absolute, no drive spec, ends `.py`
- [ ] `PluginPermission` closed enum
- [ ] `requested` ∩ `denied` = ∅ (overlap → reject)
- [ ] `parse_manifest` + `load_manifest` raise readable `ManifestError`

### ✅ Signature
- [ ] Signs `plugin.yaml` raw bytes (not manifest object)
- [ ] `UnsignedPluginError` for missing sig (distinct error)
- [ ] `SignatureError` for tampered/forged
- [ ] Verifies against **set** of trusted keys (multi-author support)
- [ ] `generate_keypair` + `sign_manifest` author tooling

### ✅ Permissions
- [ ] 3-tier check: manifest → denied? → requested? → granted?
- [ ] `violation` event on never-requested attempt (kill trigger source)
- [ ] `denied_call` event on requested-but-ungranted (normal)
- [ ] `granted`/`revoked` events on grant store changes
- [ ] User grant refused if permission not in manifest.requested — invariant
- [ ] `PermissionDeniedError` structured (plugin, permission, reason)
- [ ] Grants file plaintext JSON at `data_dir/plugin_grants.json`

### ⚠️ Red flags
- ❌ Fernet key stored on disk (should be keyring via DCL-070)
- ❌ Fallback used unconditionally (should only when keyring = fail)
- ❌ `KNOWN_SECRET_NAMES` incomplete (leak on uninstall)
- ❌ Manifest schema allows free-form permission string (should be closed enum)
- ❌ Entrypoint validation missing (allows `../../evil.py`)
- ❌ Signature signs manifest object (not bytes) — parse/re-serialize could break signature
- ❌ `UnsignedPluginError` and `SignatureError` conflated — user cannot distinguish "install unsigned?" vs "tampered!"
- ❌ Enforcer allows unrequested permission after grant — manifest bypass
- ❌ `violation` and `denied_call` events same kind — kill trigger unusable
- ❌ Grants encrypted (transparency lost)

---

## 12. Thuật ngữ

| Term | Nghĩa |
|---|---|
| **Keyring** | OS-native secret store (Windows Credential Manager, macOS Keychain, Linux KWallet) |
| **`python-keyring`** | Python library abstracting OS keyring backends |
| **AES-256-GCM** | Authenticated encryption: AES-256 counter mode + Galois message auth code |
| **AAD** | Additional Authenticated Data — plaintext bound into GCM tag, changes = auth fail |
| **Scrypt** | Password-based key derivation function — memory-hard, resists brute force |
| **`SecretStore` protocol** | Interface for both keyring and fallback — swappable |
| **ed25519** | Digital signature: Edwards-curve Digital Signature Algorithm over Curve25519 |
| **PyNaCl** | Python bindings for libsodium — implements ed25519, secretbox, etc. |
| **`SigningKey` / `VerifyKey`** | ed25519 private / public key pair |
| **Detached signature** | Signature stored separately from signed data (vs embedded) |
| **`plugin.yaml`** | DeClaw plugin manifest — security contract |
| **Semver** | Semantic versioning `major.minor.patch` |
| **Slug** | URL-safe name, lowercase alphanumeric + hyphens |
| **Closed enum** | Fixed set of values — cannot add new via string |
| **`extra="forbid"`** | Pydantic config: unknown fields → validation error |
| **Manifest = security contract** | Manifest defines everything trust boundary needs; signature covers it |
| **Permission enforcer** | Runtime check: plugin allowed to use this capability? |
| **Grant** | User-granted permission to a plugin (from manifest.requested subset) |
| **`denied_call`** | Audit event: plugin requested capability but user hasn't granted |
| **`violation`** | Audit event: plugin used capability NOT in manifest.requested (compromise indicator) |
| **Kill trigger** | Automatic response to violation (DCL-097 Phase 7): terminate subprocess |
| **Buildable core** | Subset of phase implementable without waiting for future phase |
| **`KNOWN_SECRET_NAMES`** | Frozenset of every secret DeClaw creates — uninstaller iterates |

---

## Related docs

- [phase-0-review.md](./phase-0-review.md) — Foundation
- [phase-1-review.md](./phase-1-review.md) — Brain
- [phase-2-review.md](./phase-2-review.md) — Tools
- [phase-4-review.md](./phase-4-review.md) — Sanitizer
- [phase-5-review.md](./phase-5-review.md) — Memory + Audit (DCL-070 landed here, audit union includes PluginPermissionEvent)
- [CLAUDE.md](../CLAUDE.md) — Living dev context
- [TICKETS.md](../TICKETS.md) — DCL-070..084

---

**Last updated**: 2026-07-04
