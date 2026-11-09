"""UI security surface: strict CSP, nosniff, static files, locale parity
(DCL-127..130/132/133, spec section 13).

Security-critical tests: written (and watched fail) before the
implementation, per spec section 17. What is pinned:

- The CSP on EVERY response derives ``connect-src`` from the ACTUAL bind
  authority (Review Focus 3): with ``DECLAW_PORT=9000`` the header contains
  ``ws://127.0.0.1:9000`` and never the default 7842.
- ``X-Content-Type-Options: nosniff`` on the static ``/`` and API responses.
- The served markup carries no inline executable surface: no ``onclick=``
  handlers, no ``<script>`` without ``src``, no ``style=`` attributes — the
  CSP blocks them, the markup must not need them.
- The frontend derives its WebSocket URL from ``window.location`` — no
  hard-coded 7842 anywhere in the shipped JS.
- Locale completeness: ``en.json`` and ``fr.json`` expose the same dotted
  key set (spec section 14/17 M5).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from declaw.config import Settings
from declaw.gateway.app import UI_DIR, create_app

TEST_PORT = 9000  # never the default 7842 (same convention as test_host_origin)
BIND_AUTHORITY = f"127.0.0.1:{TEST_PORT}"


# --- Harness ------------------------------------------------------------------


class FakeSecretStore:
    """In-memory ``SecretStore``; no test touches the OS vault."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.data.get(name)

    def set(self, name: str, value: str) -> None:
        self.data[name] = value

    def delete(self, name: str) -> bool:
        return self.data.pop(name, None) is not None

    def purge(self, names: tuple[str, ...] = ()) -> int:
        return sum(1 for name in names if self.delete(name))


def _client() -> TestClient:
    settings = Settings(
        _env_file=None, port=TEST_PORT, data_dir=Path("build"), sanitizer_required=False
    )  # type: ignore[call-arg]
    app = create_app(settings, secret_store=FakeSecretStore())
    return TestClient(app, base_url=f"http://{BIND_AUTHORITY}")


def _get(path: str) -> Any:
    client = _client()
    response = client.get(path, headers={"Host": BIND_AUTHORITY})
    assert response.status_code == 200, response.text
    return response


# --- Security headers ---------------------------------------------------------


def test_csp_connect_src_derived_from_bind() -> None:
    response = _get("/")
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    # Derived from the actual bind authority (Review Focus 3): the WS
    # authority matches the configured port, never the default 7842.
    assert "connect-src 'self' ws://127.0.0.1:9000" in csp
    assert "7842" not in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "img-src 'self' data:" in csp
    assert "frame-ancestors 'none'" in csp


def test_csp_present_on_rejected_responses_too() -> None:
    # A 403 from the Host policy still carries the CSP: every response the
    # server can emit is covered by the policy.
    client = _client()
    response = client.get("/", headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert "content-security-policy" in response.headers


def test_nosniff_on_root_and_api() -> None:
    root = _get("/")
    assert root.headers["x-content-type-options"] == "nosniff"
    api = _client().get(
        "/api/auth/status", headers={"Host": BIND_AUTHORITY}
    )
    assert api.headers["x-content-type-options"] == "nosniff"


# --- Served markup ------------------------------------------------------------


def test_static_index_is_served_at_root() -> None:
    response = _get("/")
    assert "text/html" in response.headers["content-type"]
    assert "<!DOCTYPE html>" in response.text or "<html" in response.text


def test_no_inline_script_or_style_in_served_markup() -> None:
    body = _get("/").text
    # No inline handlers...
    assert "onclick=" not in body.replace("onclick =", "onclick=")
    for handler in re.findall(r"\son[a-z]+=", body):
        raise AssertionError(f"inline handler {handler!r} in served markup")
    # ...no script without src...
    for match in re.findall(r"<script[^>]*>", body):
        assert 'src="' in match, f"inline script tag {match!r}"
    # ...and no style attributes or inline <style> blocks.
    assert 'style="' not in body
    assert "<style" not in body


def test_shipped_js_derives_ws_url_from_window_location() -> None:
    js_files = sorted((UI_DIR / "js").glob("*.js"))
    assert js_files, "the UI ships JS modules"
    for js_file in js_files:
        text = js_file.read_text(encoding="utf-8")
        assert "7842" not in text, f"{js_file.name} hard-codes the default port"
    api_js = (UI_DIR / "js" / "api.js").read_text(encoding="utf-8")
    assert "window.location" in api_js, "REST/WS base must derive from window.location"


# --- Locales -------------------------------------------------------------------


def _flatten(node: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            nested = f"{prefix}.{key}" if prefix else str(key)
            keys.add(nested)
            keys |= _flatten(value, nested)
    return keys


def test_locale_files_have_identical_key_sets() -> None:
    en = json.loads((UI_DIR / "locales" / "en.json").read_text(encoding="utf-8"))
    fr = json.loads((UI_DIR / "locales" / "fr.json").read_text(encoding="utf-8"))
    en_keys = _flatten(en)
    fr_keys = _flatten(fr)
    assert en_keys == fr_keys, (
        f"locale divergence: only-en={sorted(en_keys - fr_keys)} "
        f"only-fr={sorted(fr_keys - en_keys)}"
    )
    assert en_keys, "locale files are not empty"
