"""Tests for the hardened Smart Ops provider runtime."""

from __future__ import annotations

import threading
import time

import pytest

from app.ai import secure_llm_runtime as runtime
from app.ai.secure_llm_runtime import ConfiguredLLMAdvisor, SecureLLMConfig


class _Secrets:
    def __init__(self):
        self.values = {}

    def store(self, name, value):
        self.values[name] = value
        return True

    def retrieve(self, name):
        return self.values.get(name)

    def delete(self, name):
        return self.values.pop(name, None) is not None


def test_plaintext_key_is_migrated_to_correct_encrypted_secret(monkeypatch):
    secrets = _Secrets()
    monkeypatch.setattr(runtime, "get_secrets_manager", lambda: secrets)

    config = SecureLLMConfig(
        provider="openai",
        base_url="https://api.openai.com",
        model="test-model",
        api_key="test-key-value",  # pragma: allowlist secret
    )

    assert config.api_key == ""
    assert config.get_api_key() == "test-key-value"  # pragma: allowlist secret
    assert secrets.values == {
        runtime.LLM_SECRET_NAME: "test-key-value"  # pragma: allowlist secret
    }


def test_public_settings_never_include_api_key(monkeypatch):
    secrets = _Secrets()
    monkeypatch.setattr(runtime, "get_secrets_manager", lambda: secrets)
    config = SecureLLMConfig(
        provider="openai",
        base_url="https://example.com",
        model="model",
        api_key="private-test-key",  # pragma: allowlist secret
    )

    settings = config.public_settings()

    assert "api_key" not in settings
    assert "key" not in " ".join(settings)


def test_remote_plaintext_provider_url_is_rejected():
    with pytest.raises(ValueError, match="loopback"):
        SecureLLMConfig(
            provider="openai",
            base_url="http://example.com",
            model="model",
        )


def test_loopback_ollama_http_is_allowed():
    config = SecureLLMConfig(
        provider="ollama",
        base_url="http://127.0.0.1:11434/",
        model="mistral",
    )

    assert config.base_url == "http://127.0.0.1:11434"


def test_from_settings_loads_only_public_configuration(monkeypatch):
    monkeypatch.setattr(
        runtime.settings_manager,
        "get_setting",
        lambda key, default=None: {
            "provider": "none",
            "base_url": "",
            "model": "offline",
            "temperature": 0.5,
            "max_tokens": 500,
            "timeout": 10,
        },
    )

    config = SecureLLMConfig.from_settings()

    assert config.provider == "none"
    assert config.model == "offline"
    assert config.get_api_key() == ""


def test_new_async_request_suppresses_stale_callback(monkeypatch):
    advisor = ConfiguredLLMAdvisor(
        SecureLLMConfig(provider="none", base_url="", model="offline")
    )
    first_started = threading.Event()
    release_first = threading.Event()
    callbacks = []

    def fake_ask(prompt, _context=None):
        if prompt == "first":
            first_started.set()
            release_first.wait(1.0)
        return {"prompt": prompt}

    monkeypatch.setattr(advisor, "ask", fake_ask)

    first = advisor.ask_async("first", callbacks.append)
    assert first_started.wait(1.0)
    second = advisor.ask_async("second", callbacks.append)
    second.join(1.0)
    release_first.set()
    first.join(1.0)

    assert callbacks == [{"prompt": "second"}]


def test_cancel_pending_suppresses_callback(monkeypatch):
    advisor = ConfiguredLLMAdvisor(
        SecureLLMConfig(provider="none", base_url="", model="offline")
    )
    release = threading.Event()
    callbacks = []

    def fake_ask(_prompt, _context=None):
        release.wait(1.0)
        return {"ok": True}

    monkeypatch.setattr(advisor, "ask", fake_ask)
    worker = advisor.ask_async("request", callbacks.append)
    time.sleep(0.02)
    advisor.cancel_pending()
    release.set()
    worker.join(1.0)

    assert callbacks == []
