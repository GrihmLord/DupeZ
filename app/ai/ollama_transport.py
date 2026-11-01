"""Narrow, proxy-free HTTP transport for the local Ollama service.

This module is intentionally separate from the generic external-URL client.
Only the canonical local Ollama listener and the two endpoints used by the
advisor are reachable through this transport.
"""

from __future__ import annotations

import json
import math
import ssl
import urllib.error
import urllib.request
from typing import Mapping, Optional
from urllib.parse import SplitResult, urlsplit

from app.__version__ import __version__

__all__ = [
    "ollama_get",
    "ollama_post_json",
    "validate_ollama_base_url",
]

_OLLAMA_PORT = 11434
_CANONICAL_NETLOCS = {
    "localhost:11434": "127.0.0.1:11434",
    "127.0.0.1:11434": "127.0.0.1:11434",
    "[::1]:11434": "[::1]:11434",
}
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_USER_AGENT = f"DupeZ/{__version__}"
_ALLOWED_CALLER_HEADERS = frozenset({"accept"})


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject every redirect without disclosing its destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del newurl
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            "local Ollama redirects are refused",
            headers,
            fp,
        )


def _split_url(value: str, *, context: str) -> tuple[str, SplitResult]:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    if not value:
        raise ValueError(f"{context} is required")
    if value != value.strip():
        raise ValueError(f"{context} contains unsafe characters")
    text = value
    if any(character.isspace() for character in text) or "\\" in text:
        raise ValueError(f"{context} contains unsafe characters")
    try:
        parsed = urlsplit(text)
        # Accessing port performs strict range and syntax validation.
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{context} has an invalid port") from exc
    return text, parsed


def validate_ollama_base_url(value: str) -> str:
    """Return a canonical local Ollama base URL or raise ValueError.

    The only accepted listener identities are localhost, 127.0.0.1,
    and ::1 on Ollama's standard port. localhost is canonicalized to
    the numeric IPv4 loopback address so the request cannot be redirected by
    DNS or a modified hosts file.
    """
    text, parsed = _split_url(value, context="Ollama base URL")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Ollama base URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Ollama base URL must not contain credentials")
    if "?" in text or "#" in text:
        raise ValueError("Ollama base URL must not contain query or fragment data")
    if parsed.path not in {"", "/"}:
        raise ValueError("Ollama base URL must not contain a path")
    if parsed.port != _OLLAMA_PORT:
        raise ValueError(f"Ollama base URL must use port {_OLLAMA_PORT}")

    netloc = parsed.netloc.lower()
    canonical_netloc = _CANONICAL_NETLOCS.get(netloc)
    if canonical_netloc is None:
        raise ValueError("Ollama base URL must use an approved loopback host")
    return f"{parsed.scheme}://{canonical_netloc}"


def _validated_endpoint_url(value: str, expected_path: str) -> str:
    text, parsed = _split_url(value, context="Ollama endpoint URL")
    if parsed.path != expected_path:
        raise ValueError("Ollama endpoint path is not allowed")
    if "?" in text or "#" in text:
        raise ValueError("Ollama endpoint must not contain query or fragment data")
    base_url = validate_ollama_base_url(
        f"{parsed.scheme}://{parsed.netloc}"
    )
    return f"{base_url}{expected_path}"


def _validated_timeout(value: int | float) -> float:
    if isinstance(value, bool):
        raise ValueError("Ollama timeout must be numeric")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ollama timeout must be numeric") from exc
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 120:
        raise ValueError("Ollama timeout must be between 0 and 120 seconds")
    return timeout


def _validated_headers(
    headers: Optional[Mapping[str, str]],
    *,
    json_body: bool,
) -> dict[str, str]:
    validated = {"User-Agent": _USER_AGENT}
    if json_body:
        validated["Content-Type"] = "application/json"
    for name, value in (headers or {}).items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("Ollama headers must be strings")
        normalized_name = name.strip().lower()
        # Ollama needs no credentials. Keeping the caller-controlled surface
        # to Accept prevents an external-provider key/cookie from being
        # forwarded to a potentially untrusted local process by a future call
        # site, while User-Agent and Content-Type remain transport-owned.
        if not normalized_name or normalized_name not in _ALLOWED_CALLER_HEADERS:
            raise ValueError("Ollama request header is not allowed")
        if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
            raise ValueError("Ollama request header contains a line break")
        validated[name] = value
    return validated


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if hasattr(ssl, "TLSVersion"):
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _build_opener(scheme: str):
    handlers = [
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    ]
    if scheme == "https":
        handlers.append(urllib.request.HTTPSHandler(context=_tls_context()))
    return urllib.request.build_opener(*handlers)


def _read_response(
    request: urllib.request.Request,
    *,
    timeout: int | float,
) -> bytes:
    parsed = urlsplit(request.full_url)
    opener = _build_opener(parsed.scheme)
    with opener.open(request, timeout=_validated_timeout(timeout)) as response:
        final_url = response.geturl()
        if final_url != request.full_url:
            raise ValueError("Ollama response URL changed unexpectedly")
        body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("Ollama response exceeds the size limit")
    return body


def ollama_get(
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int | float = 5,
) -> bytes:
    """GET the exact local Ollama tags endpoint without proxies/redirects."""
    endpoint = _validated_endpoint_url(url, "/api/tags")
    request = urllib.request.Request(
        endpoint,
        method="GET",
        headers=_validated_headers(headers, json_body=False),
    )
    return _read_response(request, timeout=timeout)


def ollama_post_json(
    url: str,
    payload: dict,
    *,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int | float = 30,
) -> dict:
    """POST JSON to the exact local Ollama chat endpoint."""
    if not isinstance(payload, dict):
        raise ValueError("Ollama payload must be an object")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(body) > _MAX_REQUEST_BYTES:
        raise ValueError("Ollama request exceeds the size limit")
    endpoint = _validated_endpoint_url(url, "/api/chat")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers=_validated_headers(headers, json_body=True),
    )
    raw = _read_response(request, timeout=timeout)
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Ollama response is not valid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("Ollama response must be a JSON object")
    return result
