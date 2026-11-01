"""
Second-Factor Authentication Gate for DupeZ.

This module adds a deliberate operator-verification boundary around
sensitive actions.  Its built-in TOTP seed is DPAPI-protected at rest,
but DPAPI is available to code already executing as the logged-in user.
Accordingly, this gate mitigates stolen primary credentials and
unattended-operation mistakes; it does not claim independence from
same-user malware or a fully captured interactive session.

Three sensitive surfaces are gated by this module:

    1. Helper-process elevation                (firewall_helper.elevation)
    2. Plugin install / load                   (plugins.loader)
    3. Offensive engagement bootstrap          (offsec.runner / operator)

One provider ships in-tree:

    TOTPProvider   — RFC 6238 (HMAC-SHA256, 6-digit, ±1 step skew).
                     Always available. Seed is CSPRNG, sealed with
                     DPAPI via secret_store, and never written
                     plaintext to disk.

Verification results are *audit-logged* via the existing HMAC-chained
audit trail (``app.logs.audit.audit_event``) and rate-limited
(5 attempts / 15-minute sliding window per scope) to defeat brute
force.  A short-lived in-memory verification cache (default 5 min,
scope-bound) avoids re-prompting for back-to-back gated operations
inside one operator session — the cache is process-local and is
flushed on revocation, scope mismatch, or expiry.

Public API
----------

    SecondFactorGate.require(scope: str, *,
                             reason: str | None = None,
                             prompter: Callable[[str], str] | None = None,
                             cache_ttl_sec: int = 300) -> bool

        Returns True on success, raises SecondFactorRequired on
        failure (caller MUST refuse the gated operation in that case).
        ``scope`` must be one of the registered scopes
        ('elevation', 'plugin_install', 'offsec.engagement', ...).

    enroll_totp(account_label: str = "DupeZ") -> dict
        Generate a fresh TOTP seed, persist it sealed via DPAPI,
        return ``{"otpauth_uri": ..., "secret_b32": ...}`` for
        authenticator-app provisioning.

    is_enrolled(scope: str | None = None) -> bool
        True iff at least one provider has an enrollment record.

    revoke_all() -> int
        Wipe enrollment + verification cache.  Returns count removed.

    get_gate() -> SecondFactorGate
        Process-wide singleton.

Test seam
---------

The module accepts an injectable ``prompter`` callable so unit tests
can drive the gate without a real GUI / stdin.  In production the
default prompter calls ``app.gui`` only if a Qt application is
running, otherwise it falls back to ``getpass.getpass`` for headless
operation (useful for the offsec CLI path).

Security properties
-------------------

* TOTP uses HMAC-SHA256, a 256-bit random seed, and constant-time code
  comparison.  The seed is protected at rest through ``secret_store``.
* Verification is rate-limited and scope-bound in memory.
* FIDO2 remains disabled until assertions can be bound to a fresh,
  one-time challenge, an expected origin and relying-party ID, required
  authenticator flags, and a monotonic signature counter.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Protocol, Tuple
from urllib.parse import quote

from app.core.secret_store import (
    SecretStoreError,
    delete_secret,
    get_secret,
    put_secret,
)

__all__ = [
    "SecondFactorError",
    "SecondFactorRequired",
    "SecondFactorRateLimited",
    "SecondFactorProvider",
    "TOTPProvider",
    "SecondFactorGate",
    "enroll_totp",
    "is_enrolled",
    "revoke_all",
    "get_gate",
    "REGISTERED_SCOPES",
]


# ── Errors ────────────────────────────────────────────────────────────

class SecondFactorError(RuntimeError):
    """Base class for second-factor failures."""


class SecondFactorRequired(SecondFactorError):
    """Caller must refuse the gated operation: factor missing or invalid."""


class SecondFactorRateLimited(SecondFactorRequired):
    """Too many recent failed attempts. Caller MUST refuse."""


# ── Scopes (gated surfaces) ───────────────────────────────────────────
#
# Adding a scope to this set is part of the certification surface —
# every gated entry point in the codebase MUST cite a registered scope
# string. Unregistered scopes are rejected by SecondFactorGate.require.

REGISTERED_SCOPES: frozenset = frozenset({
    "elevation",            # firewall_helper.elevation.ensure_helper_running
    "plugin_install",       # plugins.loader.load_plugin / load_all
    "offsec.engagement",    # offsec.runner / operator engagement bootstrap
    "secret_rotation",      # any caller rotating a DPAPI-sealed secret
    "self_test",            # internal: test harness only
})


# ── Secret-store key namespaces ───────────────────────────────────────

_TOTP_SEED_KIND = "secondfactor.totp.seed"
_TOTP_LAST_COUNTER_KIND = "secondfactor.totp.lastcounter"
_LEGACY_FIDO2_CRED_KIND = "secondfactor.fido2.creds"

# RFC 6238 defaults (we use SHA-256 not SHA-1 — see module docstring).
_TOTP_DIGITS = 6
_TOTP_PERIOD_SEC = 30
_TOTP_DIGEST = hashlib.sha256
_TOTP_SKEW_STEPS = 1                # ±30 s clock skew tolerance
_TOTP_SEED_BYTES = 32               # 256-bit seed

# Rate limit (per scope, per process)
_RATE_LIMIT_WINDOW_SEC = 15 * 60    # 15-minute sliding window
_RATE_LIMIT_MAX = 5                 # 5 failures before lockout

# Verification-cache TTL upper bound (caller may pick smaller; never larger)
_CACHE_TTL_MAX_SEC = 30 * 60        # 30 minutes hard ceiling


# ── Lazy audit hook ───────────────────────────────────────────────────

def _audit(event: str, data: Dict) -> None:
    """Forward an audit event without forcing the import at module load."""
    try:
        from app.logs.audit import audit_event
        audit_event(event, data)
    except Exception:
        # Audit MUST NEVER block the security path.  Failures are
        # expected during early bootstrap / unit tests.
        pass


# ── TOTP primitive (RFC 6238, SHA-256) ────────────────────────────────

def _totp(seed: bytes, *, when: Optional[float] = None,
          step: int = _TOTP_PERIOD_SEC, digits: int = _TOTP_DIGITS,
          digest=_TOTP_DIGEST, t_offset: int = 0) -> str:
    """RFC 6238 TOTP. Returns a zero-padded ``digits``-character string."""
    now = time.time() if when is None else when
    counter = int(now // step) + t_offset
    msg = struct.pack(">Q", counter)
    mac = hmac.new(seed, msg, digest).digest()
    # Dynamic truncation (RFC 4226 §5.4)
    offset = mac[-1] & 0x0F
    code_int = (
        ((mac[offset]     & 0x7F) << 24)
        | ((mac[offset + 1] & 0xFF) << 16)
        | ((mac[offset + 2] & 0xFF) << 8)
        | (mac[offset + 3]  & 0xFF)
    )
    code = code_int % (10 ** digits)
    return str(code).zfill(digits)


def _b32_encode_no_pad(data: bytes) -> str:
    """Base32 without padding — what authenticator apps expect in the URI."""
    return base64.b32encode(data).decode("ascii").rstrip("=")


def _b32_decode_lenient(s: str) -> bytes:
    """Accept padded or unpadded, mixed-case, space-separated base32."""
    cleaned = s.strip().upper().replace(" ", "").replace("-", "")
    pad = (-len(cleaned)) % 8
    return base64.b32decode(cleaned + ("=" * pad))


# ── Provider protocol ─────────────────────────────────────────────────

class SecondFactorProvider(Protocol):
    """Minimal contract every concrete second-factor must satisfy."""

    name: str

    def available(self) -> bool: ...
    def is_enrolled(self) -> bool: ...
    def verify(self, presented: str) -> bool: ...


# ── TOTP provider ─────────────────────────────────────────────────────

@dataclass
class TOTPProvider:
    """RFC 6238 TOTP backed by DPAPI-sealed seed."""

    name: str = "totp"

    # Cached seed for in-process reuse — wiped by ``revoke``.
    _seed: Optional[bytearray] = field(default=None, repr=False)
    _verify_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )

    def available(self) -> bool:
        # TOTP needs nothing beyond the standard library + secret_store.
        return True

    def is_enrolled(self) -> bool:
        if self._seed is not None:
            return True
        try:
            return get_secret(_TOTP_SEED_KIND) is not None
        except SecretStoreError:
            return False

    def _load_seed(self) -> bytes:
        if self._seed is not None:
            return bytes(self._seed)
        raw = get_secret(_TOTP_SEED_KIND)
        if not raw:
            raise SecondFactorRequired("TOTP not enrolled")
        self._seed = bytearray(raw)
        return raw

    def enroll(self, account_label: str = "DupeZ",
               issuer: str = "DupeZ") -> Dict[str, str]:
        """Generate + persist a fresh seed. Returns provisioning info."""
        if not isinstance(account_label, str) or not account_label.strip():
            raise ValueError("account_label must be a non-empty string")
        previous_counter = get_secret(_TOTP_LAST_COUNTER_KIND)
        if previous_counter is not None and not delete_secret(
            _TOTP_LAST_COUNTER_KIND
        ):
            raise SecondFactorError(
                "could not reset the TOTP replay counter; enrollment refused"
            )
        seed = secrets.token_bytes(_TOTP_SEED_BYTES)
        put_secret(_TOTP_SEED_KIND, seed)
        self._seed = bytearray(seed)
        b32 = _b32_encode_no_pad(seed)
        # otpauth URI per Google Authenticator spec.
        # Algorithm=SHA256 and digits=6 matter because the verifier here
        # is not the default (SHA1 / 6-digit).
        uri = (
            "otpauth://totp/"
            + quote(f"{issuer}:{account_label}", safe="@:")
            + "?secret=" + b32
            + "&issuer=" + quote(issuer, safe="")
            + "&algorithm=SHA256"
            + f"&digits={_TOTP_DIGITS}"
            + f"&period={_TOTP_PERIOD_SEC}"
        )
        _audit("second_factor_enroll", {"provider": "totp",
                                        "account": account_label,
                                        "digits": _TOTP_DIGITS,
                                        "algorithm": "SHA256"})
        return {"otpauth_uri": uri, "secret_b32": b32}

    def verify(self, presented: str) -> bool:
        """Constant-time compare against current ± skew window."""
        if not isinstance(presented, str):
            return False
        cleaned = presented.strip().replace(" ", "")
        if len(cleaned) != _TOTP_DIGITS or not cleaned.isdigit():
            return False
        try:
            seed = self._load_seed()
        except SecondFactorRequired:
            return False
        with self._verify_lock:
            # Walk the skew window. Use compare_digest each iteration so we
            # don't leak which step matched via timing. A verifier must accept
            # a TOTP counter only once; persist the highest accepted counter so
            # bypass-cache calls and process restarts cannot replay a code.
            now = time.time()
            current_counter = int(now // _TOTP_PERIOD_SEC)
            matched_counter: Optional[int] = None
            for offset in range(-_TOTP_SKEW_STEPS, _TOTP_SKEW_STEPS + 1):
                candidate = _totp(seed, when=now, t_offset=offset)
                if hmac.compare_digest(candidate, cleaned):
                    counter = current_counter + offset
                    matched_counter = (
                        counter
                        if matched_counter is None
                        else max(matched_counter, counter)
                    )
            if matched_counter is None:
                return False

            try:
                previous_raw = get_secret(_TOTP_LAST_COUNTER_KIND)
                previous = int(previous_raw.decode("ascii")) if previous_raw else -1
                if previous < -1:
                    return False
            except (AttributeError, UnicodeDecodeError, ValueError, SecretStoreError):
                return False
            if matched_counter <= previous:
                return False
            try:
                put_secret(
                    _TOTP_LAST_COUNTER_KIND,
                    str(matched_counter).encode("ascii"),
                )
            except (OSError, SecretStoreError, ValueError):
                return False
            return True

    def revoke(self) -> bool:
        """Wipe the seed from disk + memory."""
        if self._seed is not None:
            for i in range(len(self._seed)):
                self._seed[i] = 0
            self._seed = None
        try:
            removed_seed = delete_secret(_TOTP_SEED_KIND)
            removed_counter = delete_secret(_TOTP_LAST_COUNTER_KIND)
            return removed_seed or removed_counter
        except SecretStoreError:
            return False


# ── Default prompter (GUI-aware, headless-safe) ───────────────────────

def _default_prompter(scope: str) -> str:
    """Collect a 6-digit TOTP from the operator.

    Uses the Qt input dialog if a QApplication is already running,
    otherwise falls back to ``getpass.getpass`` (so the offsec CLI
    path works in headless mode).
    """
    msg = f"DupeZ second factor required for: {scope}\nEnter 6-digit code: "
    # Try GUI first — but ONLY if a QApplication already exists. We
    # must not spin one up here: a fresh QApplication from a non-GUI
    # context can crash the host process.
    try:
        from PyQt6.QtWidgets import (  # type: ignore
            QApplication,
            QInputDialog,
            QLineEdit,
        )
        app = QApplication.instance()
        if app is not None:
            text, ok = QInputDialog.getText(
                None,
                "DupeZ second factor",
                msg,
                QLineEdit.EchoMode.Password,
            )
            if ok and isinstance(text, str):
                return text
            return ""
    except Exception:
        pass
    # Headless fallback. getpass keeps the code off the terminal scrollback.
    try:
        return getpass.getpass(msg)
    except Exception:
        return ""


# ── Rate limiter ──────────────────────────────────────────────────────

@dataclass
class _RateLimiter:
    """Per-scope sliding window failure counter."""

    window_sec: int = _RATE_LIMIT_WINDOW_SEC
    max_failures: int = _RATE_LIMIT_MAX

    _failures: Dict[str, List[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _trim(self, scope: str, now: float) -> None:
        cutoff = now - self.window_sec
        bucket = self._failures.get(scope, [])
        self._failures[scope] = [t for t in bucket if t >= cutoff]

    def check(self, scope: str) -> Tuple[bool, int]:
        """Return (allowed, retry_in_sec).  allowed=False means refuse."""
        with self._lock:
            now = time.time()
            self._trim(scope, now)
            bucket = self._failures.get(scope, [])
            if len(bucket) >= self.max_failures:
                oldest = bucket[0]
                retry_in = max(0, int(self.window_sec - (now - oldest)))
                return False, retry_in
            return True, 0

    def record_failure(self, scope: str) -> None:
        with self._lock:
            now = time.time()
            self._failures.setdefault(scope, []).append(now)
            self._trim(scope, now)

    def reset(self, scope: Optional[str] = None) -> None:
        with self._lock:
            if scope is None:
                self._failures.clear()
            else:
                self._failures.pop(scope, None)


# ── Verification cache ────────────────────────────────────────────────

@dataclass
class _VerificationCache:
    """Process-local short-lived per-scope verification record."""

    _records: Dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def grant(self, scope: str, ttl_sec: int) -> None:
        ttl = max(0, min(ttl_sec, _CACHE_TTL_MAX_SEC))
        with self._lock:
            self._records[scope] = time.time() + ttl

    def has_grant(self, scope: str) -> bool:
        with self._lock:
            exp = self._records.get(scope, 0.0)
            if exp <= time.time():
                self._records.pop(scope, None)
                return False
            return True

    def revoke(self, scope: Optional[str] = None) -> int:
        with self._lock:
            if scope is None:
                n = len(self._records)
                self._records.clear()
                return n
            return 1 if self._records.pop(scope, None) is not None else 0


# ── Gate ──────────────────────────────────────────────────────────────

@dataclass
class SecondFactorGate:
    """Orchestrator for second-factor verification.

    The production provider is TOTP.  Incomplete authentication providers
    are not exposed as public APIs or included in the default gate.
    """

    providers: List[SecondFactorProvider] = field(default_factory=list)
    rate_limiter: _RateLimiter = field(default_factory=_RateLimiter)
    cache: _VerificationCache = field(default_factory=_VerificationCache)

    # Hook for tests — lets us bypass the OS prompter.
    _prompter: Optional[Callable[[str], str]] = None

    @classmethod
    def default(cls) -> "SecondFactorGate":
        gate = cls()
        gate.providers = [TOTPProvider()]
        return gate

    def _select_provider(self) -> Optional[SecondFactorProvider]:
        for p in self.providers:
            if p.available() and p.is_enrolled():
                return p
        return None

    def is_enrolled(self) -> bool:
        return self._select_provider() is not None

    def require(
        self,
        scope: str,
        *,
        reason: Optional[str] = None,
        prompter: Optional[Callable[[str], str]] = None,
        cache_ttl_sec: int = 300,
        bypass_cache: bool = False,
    ) -> bool:
        """Demand a second factor for ``scope``.

        Returns True on success, raises SecondFactorRequired (or
        subclass SecondFactorRateLimited) on failure. The caller MUST
        treat any exception as "operation refused".
        """
        if scope not in REGISTERED_SCOPES:
            raise SecondFactorError(
                f"unregistered second-factor scope {scope!r} — refusing"
            )

        # Cache hit short-circuits prompting + audit (record cache hit
        # at debug only — it's a non-event, repeated audit noise here
        # would dilute the trail).
        if not bypass_cache and self.cache.has_grant(scope):
            return True

        # Rate limit BEFORE prompting — protects against trivial
        # password-guess loops + UX hangs from repeated dialog modal.
        allowed, retry = self.rate_limiter.check(scope)
        if not allowed:
            _audit("second_factor_lockout",
                   {"scope": scope, "retry_in_sec": retry,
                    "reason": reason or ""})
            raise SecondFactorRateLimited(
                f"second-factor lockout for scope {scope!r}; "
                f"retry in {retry}s"
            )

        provider = self._select_provider()
        if provider is None:
            # No enrolled provider. Refuse — better than silently
            # passing.  Operators can run ``enroll_totp()`` once to
            # set this up.
            _audit("second_factor_unavailable",
                   {"scope": scope, "reason": reason or ""})
            raise SecondFactorRequired(
                "no second-factor provider enrolled; "
                "run app.core.second_factor.enroll_totp() first"
            )

        prompt_fn = prompter or self._prompter or _default_prompter
        try:
            presented = prompt_fn(scope)
        except Exception as e:
            _audit("second_factor_prompt_error",
                   {"scope": scope, "error_type": type(e).__name__})
            raise SecondFactorRequired(f"prompter raised: {e}") from e

        ok = bool(presented) and provider.verify(presented)
        # Best-effort scrub of the presented value once verified.
        try:
            del presented
        except Exception:
            pass

        if ok:
            self.cache.grant(scope, cache_ttl_sec)
            self.rate_limiter.reset(scope)
            _audit("second_factor_verify",
                   {"scope": scope, "provider": provider.name,
                    "result": "success", "reason": reason or ""})
            return True

        # Failure path — record + audit, then refuse.
        self.rate_limiter.record_failure(scope)
        _audit("second_factor_verify",
               {"scope": scope, "provider": provider.name,
                "result": "failure", "reason": reason or ""})
        raise SecondFactorRequired(
            f"second-factor verification failed for scope {scope!r}"
        )

    def revoke(self, scope: Optional[str] = None) -> int:
        """Drop verification cache for ``scope`` (or all scopes)."""
        return self.cache.revoke(scope)


# ── Process-wide singleton ────────────────────────────────────────────

_GATE_LOCK = threading.Lock()
_GATE_SINGLETON: Optional[SecondFactorGate] = None


def get_gate() -> SecondFactorGate:
    global _GATE_SINGLETON
    if _GATE_SINGLETON is None:
        with _GATE_LOCK:
            if _GATE_SINGLETON is None:
                _GATE_SINGLETON = SecondFactorGate.default()
    return _GATE_SINGLETON


# ── Convenience top-level functions ───────────────────────────────────

def _authorize_enrollment_change(
    gate: SecondFactorGate,
    *,
    prompter: Optional[Callable[[str], str]],
    reason: str,
) -> None:
    """Require the existing factor before replacing or deleting it."""
    if not gate.is_enrolled():
        return
    gate.require(
        "secret_rotation",
        reason=reason,
        prompter=prompter,
        cache_ttl_sec=0,
        bypass_cache=True,
    )
    gate.cache.revoke("secret_rotation")


def enroll_totp(
    account_label: str = "DupeZ",
    issuer: str = "DupeZ",
    *,
    prompter: Optional[Callable[[str], str]] = None,
) -> Dict[str, str]:
    """Enroll TOTP, re-authenticating before replacing an existing seed."""
    gate = get_gate()
    _authorize_enrollment_change(
        gate,
        prompter=prompter,
        reason="replace second-factor enrollment",
    )
    for p in gate.providers:
        if isinstance(p, TOTPProvider):
            return p.enroll(account_label=account_label, issuer=issuer)
    # Should never happen — TOTP is in the default provider list.
    p = TOTPProvider()
    gate.providers.append(p)
    return p.enroll(account_label=account_label, issuer=issuer)


def is_enrolled(scope: Optional[str] = None) -> bool:
    """True iff a usable second-factor provider exists. Scope is advisory."""
    return get_gate().is_enrolled()


def revoke_all(
    *,
    prompter: Optional[Callable[[str], str]] = None,
) -> int:
    """Authenticate, then wipe all enrollments and verification grants."""
    gate = get_gate()
    _authorize_enrollment_change(
        gate,
        prompter=prompter,
        reason="revoke all second-factor enrollments",
    )
    n = gate.cache.revoke()
    for p in gate.providers:
        try:
            if hasattr(p, "revoke"):
                if p.revoke():  # type: ignore[attr-defined]
                    n += 1
        except Exception:
            pass
    # Older development builds could persist an incomplete FIDO2 record.
    # It is never consumed, but revocation still removes it so stale secret
    # material does not survive the removal of that unsupported API.
    try:
        if delete_secret(_LEGACY_FIDO2_CRED_KIND):
            n += 1
    except SecretStoreError:
        pass
    gate.rate_limiter.reset()
    _audit("second_factor_revoke_all", {"count": n})
    return n


# ── Smoke test (manual) ───────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description="second_factor manual check")
    ap.add_argument("--smoke", action="store_true",
                    help="end-to-end TOTP enroll + verify in-process")
    args = ap.parse_args()
    if args.smoke:
        gate = SecondFactorGate.default()
        provider = next(p for p in gate.providers if isinstance(p, TOTPProvider))
        info = provider.enroll(account_label="smoke@dupez")
        print(f"enrolled: {info['otpauth_uri']}")
        seed = _b32_decode_lenient(info["secret_b32"])
        code = _totp(seed)
        print(f"current code: {code}")
        assert provider.verify(code), "self-verify failed"
        provider.revoke()
        print("smoke OK")
        sys.exit(0)
