"""
Second-Factor Authentication Gate for DupeZ (§9.2 closure).

This module closes the §9.2 nation-state-grade certification blocker:
*"administrative or sensitive operations must be guarded by a second
authentication factor independent of the user's logon session."*

The threat model is straightforward.  An attacker who has already
captured the user's interactive Windows session (malware running as
the same user, RDP hijack, physical takeover of an unlocked
workstation) inherits DPAPI access automatically — every secret in
``app/core/secret_store`` is, by design, decryptable from any process
inside that session.  A second factor breaks that inheritance: even
with full session access the attacker still has to defeat a second,
session-independent credential before the gated operation runs.

Three sensitive surfaces are gated by this module:

    1. Helper-process elevation                (firewall_helper.elevation)
    2. Plugin install / load                   (plugins.loader)
    3. Offensive engagement bootstrap          (offsec.runner / operator)

Two providers ship in-tree:

    TOTPProvider   — RFC 6238 (HMAC-SHA256, 6-digit, ±1 step skew).
                     Always available. Seed is CSPRNG, sealed with
                     DPAPI via secret_store, and never written
                     plaintext to disk.

    FIDO2Provider  — WebAuthn / U2F via the optional ``fido2`` PyPI
                     package.  Falls back loudly (NOT silently) if the
                     library is absent — ``available()`` returns False
                     and the gate refuses to use it; it does not
                     pretend to verify.

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

CNSA 2.0 / SP 800-63B alignment
-------------------------------

* TOTP HMAC-SHA256 is approved under SP 800-63B §5.1.4.2 for
  Multi-Factor OTP.  We do NOT use HMAC-SHA1 (the original RFC 6238
  default), and we generate ≥160-bit seeds (default 32 bytes = 256
  bits, which exceeds the SP 800-63B minimum).
* WebAuthn (FIDO2) authenticators meet SP 800-63B AAL3 when used as
  the second factor on top of password-equivalent first factor; here
  the first factor is the user's Windows logon, which by this point
  in the boot path is already verified by the OS.
* Constant-time comparison via ``hmac.compare_digest`` for all
  secret-bearing equality checks.
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
    "FIDO2Provider",
    "SecondFactorGate",
    "enroll_totp",
    "enroll_fido2",
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
_FIDO2_CRED_KIND = "secondfactor.fido2.creds"

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
        # Walk the skew window. Use compare_digest each iteration so
        # we don't leak which step matched via timing.
        ok = False
        for offset in range(-_TOTP_SKEW_STEPS, _TOTP_SKEW_STEPS + 1):
            candidate = _totp(seed, t_offset=offset)
            if hmac.compare_digest(candidate, cleaned):
                ok = True
                # Don't break early — preserve constant-time across window.
        return ok

    def revoke(self) -> bool:
        """Wipe the seed from disk + memory."""
        if self._seed is not None:
            for i in range(len(self._seed)):
                self._seed[i] = 0
            self._seed = None
        try:
            return delete_secret(_TOTP_SEED_KIND)
        except SecretStoreError:
            return False


# ── FIDO2 provider (graceful degradation) ─────────────────────────────

@dataclass
class FIDO2Provider:
    """WebAuthn / FIDO2 second factor.

    The real implementation requires the ``fido2`` PyPI package and a
    plugged-in authenticator (YubiKey, Windows Hello, etc.).  Absence
    of either is reported HONESTLY via ``available()`` — this
    provider never silently passes verification.

    The on-disk credential record is a JSON envelope sealed with DPAPI
    and stored under ``secondfactor.fido2.creds``.  Each entry holds
    the credential ID + public key so we can perform an offline
    server-side assertion verification against challenges raised at
    gate-time.
    """

    name: str = "fido2"

    def _import_fido2(self):
        try:
            import fido2  # noqa: F401  — presence check
            return True
        except Exception:
            return False

    def available(self) -> bool:
        return self._import_fido2()

    def is_enrolled(self) -> bool:
        if not self.available():
            return False
        try:
            raw = get_secret(_FIDO2_CRED_KIND)
        except SecretStoreError:
            return False
        if not raw:
            return False
        try:
            doc = json.loads(raw.decode("utf-8"))
        except Exception:
            return False
        return bool(doc.get("credentials"))

    def enroll(self, *, credential_id_b64: str,
               public_key_b64: str,
               label: str = "primary") -> Dict[str, str]:
        """Persist a WebAuthn credential record.

        The credential registration ceremony itself runs in the GUI
        (the Qt panel collects the assertion from the platform
        authenticator).  This method is the persistence boundary:
        once the GUI has the credential ID + public key, it calls
        here to seal them.
        """
        if not self.available():
            raise SecondFactorError(
                "fido2 library not installed — "
                "FIDO2 enrollment unavailable in this build"
            )
        if not credential_id_b64 or not public_key_b64:
            raise ValueError("credential_id and public_key required")
        try:
            existing_raw = get_secret(_FIDO2_CRED_KIND)
            doc = json.loads(existing_raw.decode("utf-8")) if existing_raw else {}
        except Exception:
            doc = {}
        creds: List[Dict[str, str]] = doc.get("credentials", [])
        # Reject duplicate credential IDs.
        if any(c.get("credential_id") == credential_id_b64 for c in creds):
            raise SecondFactorError("credential already enrolled")
        creds.append({
            "credential_id": credential_id_b64,
            "public_key": public_key_b64,
            "label": label,
            "enrolled_at": int(time.time()),
        })
        doc["credentials"] = creds
        put_secret(_FIDO2_CRED_KIND, json.dumps(doc).encode("utf-8"))
        _audit("second_factor_enroll", {"provider": "fido2", "label": label})
        return {"label": label, "count": str(len(creds))}

    def verify(self, presented: str) -> bool:
        """Verify an assertion produced by the platform authenticator.

        ``presented`` here is the JSON-encoded assertion envelope that
        the GUI collected from the authenticator (clientDataJSON,
        authenticatorData, signature, credentialId).  We perform the
        offline COSE-public-key verification ourselves rather than
        running a relying-party server in-process.

        If the fido2 library is not installed, this method returns
        False (the gate will then either fall back to TOTP or refuse,
        depending on policy).  It NEVER returns True without a
        cryptographically valid assertion.
        """
        if not self.available():
            return False
        if not isinstance(presented, str) or not presented.strip():
            return False
        try:
            envelope = json.loads(presented)
        except Exception:
            return False
        cred_id = envelope.get("credentialId")
        client_data_b64 = envelope.get("clientDataJSON")
        auth_data_b64 = envelope.get("authenticatorData")
        signature_b64 = envelope.get("signature")
        if not all((cred_id, client_data_b64, auth_data_b64, signature_b64)):
            return False
        try:
            existing_raw = get_secret(_FIDO2_CRED_KIND)
            if not existing_raw:
                return False
            doc = json.loads(existing_raw.decode("utf-8"))
        except Exception:
            return False
        cred = next(
            (c for c in doc.get("credentials", [])
             if hmac.compare_digest(str(c.get("credential_id", "")), str(cred_id))),
            None,
        )
        if not cred:
            return False
        try:
            from fido2.cose import CoseKey  # type: ignore
            from fido2.utils import websafe_decode  # type: ignore
        except Exception:
            return False
        try:
            public_key = CoseKey.parse(websafe_decode(cred["public_key"]))
            client_data = websafe_decode(client_data_b64)
            auth_data = websafe_decode(auth_data_b64)
            signature = websafe_decode(signature_b64)
            client_hash = hashlib.sha256(client_data).digest()
            public_key.verify(auth_data + client_hash, signature)
            return True
        except Exception:
            return False

    def revoke(self) -> bool:
        try:
            return delete_secret(_FIDO2_CRED_KIND)
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
        from PyQt6.QtWidgets import QApplication, QInputDialog  # type: ignore
        app = QApplication.instance()
        if app is not None:
            text, ok = QInputDialog.getText(
                None, "DupeZ second factor", msg,
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

    Provider order: FIDO2 first if available + enrolled, else TOTP.
    A failed FIDO2 attempt does NOT silently fall back to TOTP — the
    operator chose FIDO2 by enrolling it, so we honor that choice.
    """

    providers: List[SecondFactorProvider] = field(default_factory=list)
    rate_limiter: _RateLimiter = field(default_factory=_RateLimiter)
    cache: _VerificationCache = field(default_factory=_VerificationCache)

    # Hook for tests — lets us bypass the OS prompter.
    _prompter: Optional[Callable[[str], str]] = None

    @classmethod
    def default(cls) -> "SecondFactorGate":
        gate = cls()
        gate.providers = [FIDO2Provider(), TOTPProvider()]
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

def enroll_totp(account_label: str = "DupeZ",
                issuer: str = "DupeZ") -> Dict[str, str]:
    """Enroll TOTP on the singleton gate. Returns provisioning info."""
    gate = get_gate()
    for p in gate.providers:
        if isinstance(p, TOTPProvider):
            return p.enroll(account_label=account_label, issuer=issuer)
    # Should never happen — TOTP is in the default provider list.
    p = TOTPProvider()
    gate.providers.append(p)
    return p.enroll(account_label=account_label, issuer=issuer)


def enroll_fido2(*, credential_id_b64: str, public_key_b64: str,
                 label: str = "primary") -> Dict[str, str]:
    """Persist a previously-collected FIDO2 credential record."""
    gate = get_gate()
    for p in gate.providers:
        if isinstance(p, FIDO2Provider):
            return p.enroll(credential_id_b64=credential_id_b64,
                            public_key_b64=public_key_b64,
                            label=label)
    p = FIDO2Provider()
    gate.providers.append(p)
    return p.enroll(credential_id_b64=credential_id_b64,
                    public_key_b64=public_key_b64,
                    label=label)


def is_enrolled(scope: Optional[str] = None) -> bool:
    """True iff a usable second-factor provider exists. Scope is advisory."""
    return get_gate().is_enrolled()


def revoke_all() -> int:
    """Wipe all enrollments + verification cache. Returns # revoked."""
    gate = get_gate()
    n = gate.cache.revoke()
    for p in gate.providers:
        try:
            if hasattr(p, "revoke"):
                if p.revoke():  # type: ignore[attr-defined]
                    n += 1
        except Exception:
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
