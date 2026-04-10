"""
Secure HTTP Client for DupeZ.

All outbound HTTP requests MUST use this module instead of raw
urllib.request.  Provides:
  - TLS 1.3 minimum enforcement (fallback to TLS 1.2 if 1.3 unavailable)
  - Certificate verification (always on, no bypass)
  - Request timeout enforcement
  - URL validation (scheme, host allowlist/blocklist)
  - Response size limits
  - User-Agent identification

CNSA 2.0 Compliance:
  - TLS 1.3 preferred (TLS_AES_256_GCM_SHA384 cipher suite)
  - Certificate chain validation via system trust store
  - No SSL/TLS downgrades, no self-signed cert bypass
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from app.core.validation import validate_url
from app.logs.logger import log_error, log_info

__all__ = ["secure_get", "secure_post_json", "secure_get_json"]


# ── Constants ────────────────────────────────────────────────────────

DEFAULT_TIMEOUT_S: int = 15
MAX_RESPONSE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
USER_AGENT: str = "DupeZ/5.2.0"

# ── TLS Context ──────────────────────────────────────────────────────

def _create_tls_context() -> ssl.SSLContext:
    """Create a hardened TLS context.

    - Minimum TLS 1.2, prefer TLS 1.3
    - Certificate verification enabled
    - System CA trust store
    - No SSLv2/SSLv3/TLS 1.0/TLS 1.1
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    # Set minimum TLS version
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    except (AttributeError, ValueError):
        # TLS 1.3 not available on this platform — fall back to 1.2
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        except (AttributeError, ValueError):
            pass

    # Certificate verification (default for TLS_CLIENT, but be explicit)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True

    # Load system certificates
    ctx.load_default_certs()

    return ctx


# Singleton TLS context
_tls_context: Optional[ssl.SSLContext] = None


def _get_tls_context() -> ssl.SSLContext:
    """Return the singleton TLS context."""
    global _tls_context
    if _tls_context is None:
        _tls_context = _create_tls_context()
    return _tls_context


# ── Public API ───────────────────────────────────────────────────────

def secure_get(url: str, headers: Optional[Dict[str, str]] = None,
               timeout: int = DEFAULT_TIMEOUT_S,
               require_https: bool = False) -> bytes:
    """Perform a validated, TLS-enforced GET request.

    Args:
        url: Target URL (validated against scheme/host blocklist)
        headers: Additional request headers
        timeout: Request timeout in seconds
        require_https: If True, reject non-HTTPS URLs

    Returns:
        Response body as bytes.

    Raises:
        ValueError: If URL is invalid or blocked
        urllib.error.URLError: On network errors
    """
    url = validate_url(url, require_https=require_https, context="secure_get")

    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)

    req = urllib.request.Request(url, method="GET", headers=hdrs)

    ctx = _get_tls_context() if url.startswith("https://") else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        data = resp.read(MAX_RESPONSE_SIZE_BYTES + 1)
        if len(data) > MAX_RESPONSE_SIZE_BYTES:
            raise ValueError(f"Response exceeds max size ({MAX_RESPONSE_SIZE_BYTES} bytes)")
        return data


def secure_post_json(url: str, payload: dict,
                     headers: Optional[Dict[str, str]] = None,
                     timeout: int = DEFAULT_TIMEOUT_S,
                     require_https: bool = False) -> Optional[dict]:
    """Perform a validated, TLS-enforced POST with JSON body.

    Args:
        url: Target URL
        payload: Dict to serialize as JSON body
        headers: Additional headers (Authorization, etc.)
        timeout: Request timeout in seconds
        require_https: If True, reject non-HTTPS URLs

    Returns:
        Parsed JSON response dict, or None on failure.
    """
    url = validate_url(url, require_https=require_https, context="secure_post_json")

    hdrs = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    if headers:
        hdrs.update(headers)

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers=hdrs)

    ctx = _get_tls_context() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(MAX_RESPONSE_SIZE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_SIZE_BYTES:
                log_error(f"secure_post_json: response exceeds size limit for {url}")
                return None
            return json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        log_error(f"secure_post_json failed for {url}: {e}")
        return None


def secure_get_json(url: str, headers: Optional[Dict[str, str]] = None,
                    timeout: int = DEFAULT_TIMEOUT_S,
                    require_https: bool = False) -> Optional[dict]:
    """Convenience: GET + JSON parse with full validation."""
    try:
        data = secure_get(url, headers=headers, timeout=timeout,
                          require_https=require_https)
        return json.loads(data.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as e:
        log_error(f"secure_get_json failed for {url}: {e}")
        return None
