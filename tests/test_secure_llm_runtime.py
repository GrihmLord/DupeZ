"""Tests for the hardened Smart Ops provider runtime."""

from __future__ import annotations

import json
import threading
import time

import pytest

from app.ai import secure_llm_runtime as runtime
from app.ai import ollama_transport
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
    with pytest.raises(ValueError, match="HTTPS"):
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


def test_provider_concurrency_is_bounded_with_offline_overload(monkeypatch):
    advisor = ConfiguredLLMAdvisor(
        SecureLLMConfig(provider="none", base_url="", model="offline")
    )
    release = threading.Event()
    two_started = threading.Event()
    active_lock = threading.Lock()
    active = 0
    peak = 0
    callbacks = []

    def blocked_ask(prompt, _context=None):
        nonlocal active, peak
        with active_lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                two_started.set()
        release.wait(1.0)
        with active_lock:
            active -= 1
        return {"source": "provider", "prompt": prompt}

    monkeypatch.setattr(advisor, "ask", blocked_ask)
    monkeypatch.setattr(
        advisor,
        "_fallback_interpret",
        lambda prompt: {"source": "offline", "prompt": prompt},
    )

    first = advisor.ask_async("first", callbacks.append)
    second = advisor.ask_async("second", callbacks.append)
    assert two_started.wait(1.0)
    third = advisor.ask_async("third", callbacks.append)
    third.join(1.0)

    assert peak == 2
    assert callbacks == [{"source": "offline", "prompt": "third"}]

    release.set()
    first.join(1.0)
    second.join(1.0)


def _diagnostic_response() -> dict:
    return {"message": {"content": json.dumps({
        "name": "diagnostic",
        "methods": ["lag"],
        "params": {"lag_delay": 1},
    })}}


@pytest.mark.parametrize("invalidate", ("cancel", "reset", "reconfigure"))
@pytest.mark.parametrize("asynchronous", (False, True))
def test_invalidated_response_cannot_repopulate_conversation(
    monkeypatch, invalidate, asynchronous,
):
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(provider="ollama"))
    advisor._available = True
    started = threading.Event()
    release = threading.Event()
    payloads = []
    callbacks = []

    def local_post(_url, payload, **_kwargs):
        payloads.append(payload)
        if len(payloads) == 1:
            started.set()
            assert release.wait(3.0)
        return _diagnostic_response()

    monkeypatch.setattr(ollama_transport, "ollama_post_json", local_post)
    monkeypatch.setattr(ollama_transport, "ollama_get", lambda *a, **k: b"{}")
    if asynchronous:
        worker = advisor.ask_async("old-session-marker", callbacks.append)
    else:
        worker = threading.Thread(
            target=advisor.ask, args=("old-session-marker",), daemon=True,
        )
        worker.start()
    try:
        assert started.wait(3.0)
        if invalidate == "cancel":
            advisor.cancel_pending()
        elif invalidate == "reset":
            advisor.reset_conversation()
        else:
            advisor.reconfigure(
                SecureLLMConfig(provider="ollama", model="replacement"),
                persist=False,
            )
    finally:
        release.set()
        worker.join(3.0)

    assert not worker.is_alive()
    assert callbacks == []
    assert advisor._conversation_history == []
    assert advisor.ask("new-session-marker") is not None
    assert all(
        message["content"] != "old-session-marker"
        for message in payloads[-1]["messages"]
    )
    assert len(advisor._conversation_history) == 2


def test_reconfigured_request_keeps_original_provider_and_timeout(monkeypatch):
    advisor = ConfiguredLLMAdvisor(
        SecureLLMConfig(provider="ollama", model="original", timeout=17)
    )
    advisor._available = True
    started = threading.Event()
    release = threading.Event()
    calls = []
    callbacks = []
    original_post = advisor._post_json

    def paused_post(url, payload, headers=None):
        started.set()
        assert release.wait(3.0)
        return original_post(url, payload, headers)

    def local_post(url, payload, **kwargs):
        calls.append((url, payload, kwargs))
        return _diagnostic_response()

    monkeypatch.setattr(advisor, "_post_json", paused_post)
    monkeypatch.setattr(ollama_transport, "ollama_post_json", local_post)
    from app.core import secure_http
    monkeypatch.setattr(
        secure_http,
        "secure_post_json",
        lambda *a, **k: pytest.fail("old request changed transport"),
    )
    worker = advisor.ask_async("diagnostic", callbacks.append)
    try:
        assert started.wait(3.0)
        advisor.reconfigure(SecureLLMConfig(provider="none"), persist=False)
    finally:
        release.set()
        worker.join(3.0)

    assert not worker.is_alive()
    assert len(calls) == 1
    url, payload, kwargs = calls[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert payload["model"] == "original"
    assert kwargs["timeout"] == 17
    assert callbacks == []
    assert advisor._conversation_history == []


@pytest.mark.parametrize("asynchronous", (False, True))
def test_stale_probe_cannot_overwrite_reconfigured_availability(monkeypatch, asynchronous):
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(provider="ollama"))
    started = threading.Event()
    release = threading.Event()
    callbacks = []

    def local_get(*_args, **_kwargs):
        started.set()
        assert release.wait(3.0)
        return b"{}"

    monkeypatch.setattr(ollama_transport, "ollama_get", local_get)
    if asynchronous:
        worker = advisor.refresh_availability_async(callbacks.append)
    else:
        worker = threading.Thread(target=advisor.refresh_availability, daemon=True)
        worker.start()
    try:
        assert started.wait(3.0)
        advisor.reconfigure(SecureLLMConfig(provider="none"), persist=False)
        assert advisor.is_available() is False
    finally:
        release.set()
        worker.join(3.0)

    assert not worker.is_alive()
    assert advisor._available is False
    assert callbacks == []


def test_probes_share_request_capacity_without_poisoning_cache(monkeypatch):
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(provider="ollama"))
    advisor._available = True
    release = threading.Event()
    first_started = threading.Event()
    second_started = threading.Event()
    check_calls = []
    callbacks = []

    def blocked_ask(prompt, _context=None):
        (first_started if prompt == "first" else second_started).set()
        assert release.wait(3.0)
        return {"prompt": prompt}

    def local_get(*args, **kwargs):
        check_calls.append((args, kwargs))
        return b"{}"

    monkeypatch.setattr(advisor, "ask", blocked_ask)
    monkeypatch.setattr(ollama_transport, "ollama_get", local_get)
    first = advisor.ask_async("first", None)
    second = None
    try:
        assert first_started.wait(3.0)
        second = advisor.ask_async("second", None)
        assert second_started.wait(3.0)
        check = advisor.refresh_availability_async(callbacks.append)
        check.join(3.0)
        assert not check.is_alive()
        assert callbacks == [False]
        assert check_calls == []
        assert advisor._available is True
    finally:
        release.set()
        first.join(3.0)
        if second is not None:
            second.join(3.0)

    assert not first.is_alive()
    assert second is not None and not second.is_alive()
    assert advisor.refresh_availability() is True
    assert len(check_calls) == 1


def test_availability_probes_are_bounded_and_release_failed_slots(monkeypatch):
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(provider="ollama"))
    release = threading.Event()
    first_started = threading.Event()
    second_started = threading.Event()
    calls_lock = threading.Lock()
    calls = 0
    callbacks = []

    def local_get(*_args, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
            call = calls
        if call <= 2:
            (first_started if call == 1 else second_started).set()
            assert release.wait(3.0)
            raise OSError("provider unavailable")
        return b"{}"

    monkeypatch.setattr(ollama_transport, "ollama_get", local_get)
    first = advisor.refresh_availability_async()
    second = None
    try:
        assert first_started.wait(3.0)
        second = advisor.refresh_availability_async()
        assert second_started.wait(3.0)
        third = advisor.refresh_availability_async(callbacks.append)
        third.join(3.0)
        assert not third.is_alive()
        assert callbacks == [False]
        assert calls == 2
    finally:
        release.set()
        first.join(3.0)
        if second is not None:
            second.join(3.0)

    assert not first.is_alive()
    assert second is not None and not second.is_alive()
    assert advisor.refresh_availability() is True
    assert calls == 3


def test_refresh_releases_capacity_when_check_raises(monkeypatch):
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(provider="none"))

    def failed_check():
        raise RuntimeError("check failed before transport")

    monkeypatch.setattr(advisor, "is_available", failed_check)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="check failed"):
            advisor.refresh_availability()
    monkeypatch.setattr(advisor, "is_available", lambda: True)
    assert advisor.refresh_availability() is True


def test_reconfigured_request_never_sends_replacement_key_to_original_provider(monkeypatch):
    from app.core import secure_http

    secrets = _Secrets()
    monkeypatch.setattr(runtime, "get_secrets_manager", lambda: secrets)
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(
        provider="openai", base_url="https://original.example",
        api_key="original-fixture-credential",  # pragma: allowlist secret
    ))
    started = threading.Event()
    release = threading.Event()
    calls = []

    def remote_get(url, **kwargs):
        calls.append((url, kwargs["headers"].get("Authorization")))
        if url.startswith("https://original.example/"):
            started.set()
            assert release.wait(3.0)
        return b"{}"

    def remote_post(url, _payload, **kwargs):
        calls.append((url, kwargs["headers"].get("Authorization")))
        return {"choices": [{"message": _diagnostic_response()["message"]}]}

    monkeypatch.setattr(secure_http, "secure_get", remote_get)
    monkeypatch.setattr(secure_http, "secure_post_json", remote_post)
    worker = advisor.ask_async("original diagnostic", None)
    try:
        assert started.wait(3.0)
        advisor.reconfigure(SecureLLMConfig(
            provider="openai", base_url="https://replacement.example",
            api_key="replacement-fixture-credential",  # pragma: allowlist secret
        ), persist=False)
    finally:
        release.set()
        worker.join(3.0)

    assert not worker.is_alive()
    assert calls == [
        ("https://original.example/v1/models", "Bearer original-fixture-credential"),
        ("https://original.example/v1/chat/completions", "Bearer original-fixture-credential"),
    ]
    assert advisor.ask("replacement diagnostic") is not None
    assert calls[2:] == [
        ("https://replacement.example/v1/models", "Bearer replacement-fixture-credential"),
        ("https://replacement.example/v1/chat/completions", "Bearer replacement-fixture-credential"),
    ]


@pytest.mark.parametrize("provider", ("none", "ollama"))
def test_local_and_offline_requests_never_retrieve_provider_credentials(monkeypatch, provider):
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(provider=provider))
    monkeypatch.setattr(
        SecureLLMConfig, "get_api_key",
        lambda _self: pytest.fail("non-remote provider retrieved a credential"),
    )
    monkeypatch.setattr(ollama_transport, "ollama_get", lambda *a, **k: b"{}")
    monkeypatch.setattr(
        ollama_transport, "ollama_post_json", lambda *a, **k: _diagnostic_response(),
    )
    assert advisor._request_api_key() == ""
    advisor.ask("diagnostic")
    advisor.refresh_availability()


@pytest.mark.parametrize("initial_key", ("initial-fixture-credential", ""))
def test_provider_credentials_are_hidden_and_cached_only_for_one_request(monkeypatch, initial_key):
    from app.core import secure_http

    secrets = _Secrets()
    secrets.values[runtime.LLM_SECRET_NAME] = initial_key
    reads = []

    def retrieve(name):
        reads.append(name)
        return secrets.values.get(name)

    monkeypatch.setattr(secrets, "retrieve", retrieve)
    monkeypatch.setattr(runtime, "get_secrets_manager", lambda: secrets)
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(
        provider="openai", base_url="https://fixture.example",
    ))
    snapshots = []
    authorizations = []

    def observe(headers):
        snapshot = advisor._request_local.snapshot
        snapshots.append(snapshot)
        authorizations.append(headers.get("Authorization"))
        if snapshot.api_key:
            assert snapshot.api_key not in repr(snapshot)
            assert snapshot.api_key not in repr(advisor.config)
            assert snapshot.api_key not in json.dumps(advisor.config.public_settings())

    def remote_get(_url, **kwargs):
        observe(kwargs["headers"])
        secrets.values[runtime.LLM_SECRET_NAME] = "rotated-fixture-credential"  # pragma: allowlist secret
        return b"{}"

    def remote_post(_url, _payload, **kwargs):
        observe(kwargs["headers"])
        return {"choices": [{"message": _diagnostic_response()["message"]}]}

    monkeypatch.setattr(secure_http, "secure_get", remote_get)
    monkeypatch.setattr(secure_http, "secure_post_json", remote_post)
    assert advisor.ask("first diagnostic") is not None
    assert reads == [runtime.LLM_SECRET_NAME]
    original_authorization = f"Bearer {initial_key}" if initial_key else None
    assert authorizations == [original_authorization, original_authorization]
    assert all(snapshot.api_key is None for snapshot in snapshots)
    assert not hasattr(advisor._request_local, "snapshot")

    assert advisor.ask("second diagnostic") is not None
    assert reads == [runtime.LLM_SECRET_NAME, runtime.LLM_SECRET_NAME]
    assert authorizations[-1] == "Bearer rotated-fixture-credential"
    assert all(snapshot.api_key is None for snapshot in snapshots)
    assert advisor.config.api_key == ""


def test_credential_retrieved_after_request_cancellation_is_discarded(monkeypatch):
    from app.core import secure_http

    started = threading.Event()
    release = threading.Event()
    secrets = _Secrets()

    def retrieve(_name):
        started.set()
        assert release.wait(3.0)
        return "replacement-fixture-credential"

    monkeypatch.setattr(secrets, "retrieve", retrieve)
    monkeypatch.setattr(runtime, "get_secrets_manager", lambda: secrets)
    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(
        provider="openai", base_url="https://original.example",
    ))
    headers = []

    def remote_get(_url, **kwargs):
        headers.append(kwargs["headers"])
        return b"{}"

    monkeypatch.setattr(secure_http, "secure_get", remote_get)
    worker = advisor.refresh_availability_async()
    try:
        assert started.wait(3.0)
        advisor.reconfigure(SecureLLMConfig(provider="none"), persist=False)
    finally:
        release.set()
        worker.join(3.0)
    assert not worker.is_alive()
    assert headers == [{}]


def test_invalidated_request_does_not_perform_its_first_credential_read(monkeypatch):
    from app.core import secure_http

    advisor = ConfiguredLLMAdvisor(SecureLLMConfig(
        provider="openai", base_url="https://original.example",
    ))
    started = threading.Event()
    release = threading.Event()
    headers = []
    original_check = advisor.is_available

    def paused_check():
        started.set()
        assert release.wait(3.0)
        return original_check()

    def remote_get(_url, **kwargs):
        headers.append(kwargs["headers"])
        return b"{}"

    monkeypatch.setattr(advisor, "is_available", paused_check)
    monkeypatch.setattr(secure_http, "secure_get", remote_get)
    monkeypatch.setattr(
        SecureLLMConfig, "get_api_key",
        lambda _self: pytest.fail("invalidated request retrieved a credential"),
    )
    worker = advisor.refresh_availability_async()
    try:
        assert started.wait(3.0)
        advisor.reconfigure(SecureLLMConfig(provider="none"), persist=False)
    finally:
        release.set()
        worker.join(3.0)
    assert not worker.is_alive()
    assert headers == [{}]
