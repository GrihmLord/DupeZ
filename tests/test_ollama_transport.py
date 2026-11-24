"""Security and routing tests for the local-only Ollama transport."""

from __future__ import annotations

import json
import urllib.request

import pytest

from app.ai import ollama_transport
from app.ai.secure_llm_runtime import ConfiguredLLMAdvisor, SecureLLMConfig
from app.core import secure_http
from app.core.validation import validate_url


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("http://localhost:11434", "http://127.0.0.1:11434"),
        ("HTTP://LOCALHOST:11434/", "http://127.0.0.1:11434"),
        ("http://127.0.0.1:11434/", "http://127.0.0.1:11434"),
        ("http://[::1]:11434", "http://[::1]:11434"),
        ("https://localhost:11434", "https://127.0.0.1:11434"),
        ("https://[::1]:11434/", "https://[::1]:11434"),
    ),
)
def test_ollama_base_url_accepts_only_canonical_listener_forms(
    value: str,
    expected: str,
) -> None:
    assert ollama_transport.validate_ollama_base_url(value) == expected
    config = SecureLLMConfig(provider="ollama", base_url=value)
    assert config.base_url == expected


@pytest.mark.parametrize(
    "value",
    (
        "",
        "localhost:11434",
        "//localhost:11434",
        "ftp://localhost:11434",
        "file://localhost:11434",
        "http://localhost",
        "http://localhost:80",
        "https://localhost:443",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:not-a-port",
        "http://localhost:011434",
        "http://127.0.0.2:11434",
        "http://127.1:11434",
        "http://2130706433:11434",
        "http://0x7f000001:11434",
        "http://[::ffff:127.0.0.1]:11434",
        "http://localhost.:11434",
        "http://localhost.localdomain:11434",
        "http://0.0.0.0:11434",
        "http://10.0.0.1:11434",
        "http://172.16.0.1:11434",
        "http://192.168.1.10:11434",
        "http://169.254.169.254:11434",
        "http://example.com:11434",
        "http://user@localhost:11434",
        "http://:password@localhost:11434",
        "http://@localhost:11434",
        "http://localhost:11434/api",
        "http://localhost:11434//",
        "http://localhost:11434/%2e",
        "http://localhost:11434?model=x",
        "http://localhost:11434?",
        "http://localhost:11434#fragment",
        "http://localhost:11434#",
        "http://localhost:11434\\@example.com",
        "http://localhost:11434 \t",
    ),
)
def test_ollama_base_url_rejects_ambiguous_or_nonlocal_targets(value: str) -> None:
    with pytest.raises(ValueError):
        ollama_transport.validate_ollama_base_url(value)
    if value:
        with pytest.raises(ValueError):
            SecureLLMConfig(provider="ollama", base_url=value)
    else:
        config = SecureLLMConfig(provider="ollama", base_url=value)
        assert config.base_url == "http://127.0.0.1:11434"


def test_generic_ssrf_validator_remains_fail_closed_for_loopback() -> None:
    with pytest.raises(ValueError, match="Blocked host"):
        validate_url("http://localhost:11434/api/tags")
    with pytest.raises(ValueError, match="Private/non-routable"):
        validate_url("http://127.0.0.2:11434/api/tags")


class _Response:
    def __init__(self, url: str, body: bytes) -> None:
        self._url = url
        self._body = body
        self.read_limit = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, limit: int) -> bytes:
        self.read_limit = limit
        return self._body


class _Opener:
    def __init__(self, body: bytes, *, final_url: str | None = None) -> None:
        self.body = body
        self.final_url = final_url
        self.requests = []

    def open(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        return _Response(self.final_url or request.full_url, self.body)


def test_local_get_canonicalizes_host_and_uses_bounded_direct_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = _Opener(b'{"models":[]}')
    monkeypatch.setattr(ollama_transport, "_build_opener", lambda _scheme: opener)

    assert ollama_transport.ollama_get(
        "http://localhost:11434/api/tags",
        timeout=5,
    ) == b'{"models":[]}'

    [(request, timeout)] = opener.requests
    assert request.full_url == "http://127.0.0.1:11434/api/tags"
    assert request.get_method() == "GET"
    assert timeout == 5.0


def test_local_post_uses_only_chat_endpoint_and_parses_object_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = _Opener(b'{"message":{"content":"ok"}}')
    monkeypatch.setattr(ollama_transport, "_build_opener", lambda _scheme: opener)

    result = ollama_transport.ollama_post_json(
        "http://[::1]:11434/api/chat",
        {"model": "mistral", "stream": False},
        timeout=30,
    )

    assert result == {"message": {"content": "ok"}}
    [(request, timeout)] = opener.requests
    assert request.full_url == "http://[::1]:11434/api/chat"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"model": "mistral", "stream": False}
    assert timeout == 30.0


@pytest.mark.parametrize(
    ("method", "url"),
    (
        ("get", "http://localhost:11434/api/chat"),
        ("get", "http://localhost:11434/api/tags?all=true"),
        ("get", "http://example.com:11434/api/tags"),
        ("post", "http://localhost:11434/api/tags"),
        ("post", "http://localhost:11434/api/chat#response"),
        ("post", "http://127.0.0.2:11434/api/chat"),
    ),
)
def test_local_transport_revalidates_exact_endpoint_before_open(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    url: str,
) -> None:
    opened = []
    monkeypatch.setattr(
        ollama_transport,
        "_build_opener",
        lambda scheme: opened.append(scheme),
    )

    with pytest.raises(ValueError):
        if method == "get":
            ollama_transport.ollama_get(url)
        else:
            ollama_transport.ollama_post_json(url, {})
    assert opened == []


def test_local_transport_rejects_changed_response_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = _Opener(
        b"redirected",
        final_url="http://169.254.169.254/latest/meta-data",
    )
    monkeypatch.setattr(ollama_transport, "_build_opener", lambda _scheme: opener)

    with pytest.raises(ValueError, match="changed unexpectedly"):
        ollama_transport.ollama_get("http://localhost:11434/api/tags")


def test_local_opener_disables_proxies_and_installs_redirect_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_handlers = []
    sentinel = object()

    def build_opener(*handlers):
        captured_handlers.extend(handlers)
        return sentinel

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)

    assert ollama_transport._build_opener("http") is sentinel
    proxy_handlers = [
        handler
        for handler in captured_handlers
        if isinstance(handler, urllib.request.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    assert any(
        isinstance(handler, ollama_transport._NoRedirectHandler)
        for handler in captured_handlers
    )


@pytest.mark.parametrize(
    "headers",
    (
        {"Host": "example.com"},
        {"Content-Length": "0"},
        {"Proxy-Authorization": "secret"},
        {"Authorization": "Bearer external-secret"},
        {"Cookie": "session=external-secret"},
        {"X-API-Key": "external-secret"},
        {"X-Test": "safe\r\nInjected: true"},
    ),
)
def test_local_transport_rejects_authority_or_framing_headers(
    headers: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        ollama_transport.ollama_get(
            "http://localhost:11434/api/tags",
            headers=headers,
        )


@pytest.mark.parametrize("timeout", (0, -1, 121, float("inf"), True, "five"))
def test_local_transport_rejects_bad_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    timeout,
) -> None:
    opener = _Opener(b"{}")
    monkeypatch.setattr(ollama_transport, "_build_opener", lambda _scheme: opener)

    with pytest.raises(ValueError, match="timeout"):
        ollama_transport.ollama_get(
            "http://localhost:11434/api/tags",
            timeout=timeout,
        )


def test_configured_advisor_routes_ollama_around_generic_external_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_calls = []

    def local_get(url, *, headers=None, timeout=5):
        local_calls.append((url, headers, timeout))
        return b'{"models":[]}'

    monkeypatch.setattr(ollama_transport, "ollama_get", local_get)
    monkeypatch.setattr(
        secure_http,
        "secure_get",
        lambda *_args, **_kwargs: pytest.fail(
            "generic external transport must not handle local Ollama"
        ),
    )
    config = SecureLLMConfig(
        provider="ollama",
        base_url="http://localhost:11434",
        model="mistral",
    )
    monkeypatch.setattr(
        config,
        "get_api_key",
        lambda: pytest.fail("an external API key must not be sent to Ollama"),
    )
    advisor = ConfiguredLLMAdvisor(config)

    assert advisor.refresh_availability() is True
    assert local_calls == [
        ("http://127.0.0.1:11434/api/tags", {}, 5)
    ]


def test_configured_advisor_routes_ollama_chat_to_local_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def local_post(url, payload, *, headers=None, timeout=30):
        calls.append((url, payload, headers, timeout))
        return {"message": {"content": "local answer"}}

    monkeypatch.setattr(ollama_transport, "ollama_post_json", local_post)
    advisor = ConfiguredLLMAdvisor(
        SecureLLMConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="mistral",
            timeout=17,
        )
    )

    assert advisor._call_llm([{"role": "user", "content": "hello"}]) == (
        "local answer"
    )
    assert calls
    assert calls[0][0] == "http://127.0.0.1:11434/api/chat"
    assert calls[0][2:] == (None, 17)


def test_openai_still_routes_through_generic_external_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generic_calls = []
    monkeypatch.setattr(
        ollama_transport,
        "ollama_get",
        lambda *_args, **_kwargs: pytest.fail(
            "local transport must not handle external providers"
        ),
    )

    def generic_get(url, *, headers=None, timeout=5, require_https=False):
        generic_calls.append((url, headers, timeout, require_https))
        return b"{}"

    monkeypatch.setattr(secure_http, "secure_get", generic_get)
    advisor = ConfiguredLLMAdvisor(
        SecureLLMConfig(
            provider="openai",
            base_url="https://api.openai.com",
            model="model",
        )
    )

    assert advisor.refresh_availability() is True
    assert generic_calls
    assert generic_calls[0][0] == "https://api.openai.com/v1/models"
    assert generic_calls[0][3] is True
