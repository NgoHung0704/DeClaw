"""The spawned environment is built from scratch, never inherited."""

from __future__ import annotations

import pytest

from declaw.plugin_host.process import build_plugin_env


def test_no_declaw_setting_leaks_into_the_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECLAW_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("DECLAW_DATA_DIR", "/secret")
    env = build_plugin_env("echo-plugin")
    leaked = [k for k in env if k.startswith("DECLAW_") and k != "DECLAW_PLUGIN_NAME"]
    assert leaked == []


def test_no_ollama_variable_leaks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert [k for k in build_plugin_env("p") if k.startswith("OLLAMA")] == []


def test_arbitrary_user_variables_do_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nope")
    assert "AWS_SECRET_ACCESS_KEY" not in build_plugin_env("p")


def test_the_plugin_is_told_its_own_name() -> None:
    assert build_plugin_env("echo-plugin")["DECLAW_PLUGIN_NAME"] == "echo-plugin"


def test_python_needs_these_to_run_at_all() -> None:
    env = build_plugin_env("p")
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert "PATH" in env
