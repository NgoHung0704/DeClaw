"""Security regressions from the Phase 9 review; no OS vault or daemon I/O."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from declaw.config import Settings
from declaw.gateway.app import create_app
from declaw.gateway.auth import GATEWAY_TOKEN_NAME, SESSION_COOKIE_NAME
from declaw.gateway.middleware import RateLimiter
from declaw.main import cli


class MemorySecrets:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None

    def purge(self, names: tuple[str, ...] = ()) -> int:
        return sum(self.delete(name) for name in names)


def test_start_delivers_a_reusable_login_token(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemorySecrets()
    monkeypatch.setattr("declaw.credentials.store.CredentialStore", lambda: store)
    monkeypatch.setattr("declaw.gateway.app.run_gateway", lambda settings: None)
    monkeypatch.setattr("declaw.log.configure", lambda: None)
    runner = CliRunner()
    first = runner.invoke(cli, ["start"])
    assert first.exit_code == 0, first.exception
    token = store.get(GATEWAY_TOKEN_NAME)
    assert token is not None
    assert token in first.stdout
    second = runner.invoke(cli, ["start"])
    assert second.exit_code == 0
    assert store.get(GATEWAY_TOKEN_NAME) == token
    assert token in second.stdout


def test_forged_rest_cookies_do_not_allocate_rate_buckets() -> None:
    limiter = RateLimiter()
    settings = Settings(_env_file=None, port=9000)  # type: ignore[call-arg]
    app = create_app(settings, rate_limiter=limiter, secret_store=MemorySecrets())
    with TestClient(app, base_url="http://127.0.0.1:9000") as client:
        for index in range(200):
            response = client.get(
                "/api/tasks", headers={"Cookie": f"{SESSION_COOKIE_NAME}=forged-{index}"}
            )
            assert response.status_code == 401
    assert not limiter._rest_read_buckets
