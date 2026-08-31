from __future__ import annotations

import urllib.error

import pytest

from app.core import secure_http


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._body


class _Opener:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def test_secure_get_installs_redirect_refusal_and_keeps_headers_origin_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_handlers = []
    opener = _Opener(_Response(b"ok"))

    def build_opener(*handlers):
        captured_handlers.extend(handlers)
        return opener

    monkeypatch.setattr(secure_http.urllib.request, "build_opener", build_opener)
    monkeypatch.setattr(secure_http, "_get_tls_context", lambda: None)

    assert secure_http.secure_get(
        "https://example.com/data",
        headers={"Authorization": "Bearer test-only"},
        require_https=True,
    ) == b"ok"

    assert any(
        isinstance(handler, secure_http._NoRedirectHandler)
        for handler in captured_handlers
    )
    request, timeout = opener.requests[0]
    assert request.full_url == "https://example.com/data"
    assert request.get_header("Authorization") == "Bearer test-only"
    assert timeout == secure_http.DEFAULT_TIMEOUT_S


def test_redirect_handler_never_builds_a_followup_request() -> None:
    handler = secure_http._NoRedirectHandler()
    request = secure_http.urllib.request.Request("https://example.com/start")

    assert handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://attacker.invalid/collect",
    ) is None


def test_secure_post_treats_redirect_response_as_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect = urllib.error.HTTPError(
        "https://example.com/start",
        307,
        "Temporary Redirect",
        {"Location": "https://attacker.invalid/collect"},
        None,
    )
    opener = _Opener(error=redirect)
    monkeypatch.setattr(
        secure_http.urllib.request,
        "build_opener",
        lambda *_handlers: opener,
    )
    monkeypatch.setattr(secure_http, "_get_tls_context", lambda: None)

    assert secure_http.secure_post_json(
        "https://example.com/start",
        {"test": True},
        headers={"Authorization": "Bearer test-only"},
        require_https=True,
    ) is None
    assert len(opener.requests) == 1


def test_secure_post_error_log_omits_private_url_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "".join(("signed-", "url-", "canary"))
    url = (
        f"https://account:{canary}@example.com/private/path"
        f"?signature={canary}#fragment"
    )
    opener = _Opener(error=urllib.error.URLError(f"transport failed for {url}"))
    messages: list[str] = []
    monkeypatch.setattr(
        secure_http.urllib.request,
        "build_opener",
        lambda *_handlers: opener,
    )
    monkeypatch.setattr(secure_http, "_get_tls_context", lambda: None)
    monkeypatch.setattr(secure_http, "log_error", messages.append)

    assert secure_http.secure_post_json(url, {"test": True}) is None

    rendered = "\n".join(messages)
    assert canary not in rendered
    assert "account" not in rendered
    assert "private/path" not in rendered
    assert "fragment" not in rendered
    assert messages == [
        "secure_post_json failed for https://example.com/[REDACTED] (URLError)"
    ]


def test_secure_get_json_error_log_omits_private_url_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "".join(("query-", "failure-", "canary"))
    url = f"https://example.com/private?signature={canary}#fragment"
    messages: list[str] = []

    def _fail(*_args, **_kwargs) -> bytes:
        raise ValueError(f"request rejected for {url}")

    monkeypatch.setattr(secure_http, "secure_get", _fail)
    monkeypatch.setattr(secure_http, "log_error", messages.append)

    assert secure_http.secure_get_json(url) is None

    rendered = "\n".join(messages)
    assert canary not in rendered
    assert "private" not in rendered
    assert "fragment" not in rendered
    assert messages == [
        "secure_get_json failed for https://example.com/[REDACTED] (ValueError)"
    ]
