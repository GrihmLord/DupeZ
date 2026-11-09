"""
Tests for the §9.2 second-factor gate (app/core/second_factor.py).

These tests exercise the authn gate end-to-end without touching real
DPAPI: we substitute an in-memory secret_store so the suite runs on
any OS and in CI. The cryptographic primitives (TOTP, constant-time
compare, rate limiter) are exercised directly.
"""

from __future__ import annotations

import sys
import time
import types

import pytest


# ── In-memory secret_store shim ───────────────────────────────────────

@pytest.fixture(autouse=True)
def _in_memory_secret_store(monkeypatch):
    """Replace app.core.secret_store with an in-memory backing AND
    silence the audit logger so tests don't pollute the production
    audit chain at app/data/audit.jsonl.

    Without the audit stub, every test emits real audit events that
    get written under an ephemeral HMAC key (because secret_store is
    stubbed, the audit logger can't load its real key) — which then
    fails to validate on the next run and triggers a chain rotation
    to audit.corrupted.<ts>.jsonl. Harmless but noisy.
    """
    shim = types.ModuleType("app.core.secret_store")
    store = {}

    class SecretStoreError(RuntimeError):
        pass

    def get_secret(k):
        return store.get(k)

    def put_secret(k, v, **kw):
        store[k] = bytes(v)

    def delete_secret(k):
        if k in store:
            del store[k]
            return True
        return False

    shim.SecretStoreError = SecretStoreError
    shim.get_secret = get_secret
    shim.put_secret = put_secret
    shim.delete_secret = delete_secret

    monkeypatch.setitem(sys.modules, "app.core.secret_store", shim)

    # Stub out the audit logger so tests don't touch app/data/audit.jsonl.
    audit_shim = types.ModuleType("app.logs.audit")
    audit_shim.audit_event = lambda event, data=None: None
    audit_shim.get_audit_logger = lambda: None
    monkeypatch.setitem(sys.modules, "app.logs.audit", audit_shim)

    # Force fresh import of second_factor so it binds to our shim.
    sys.modules.pop("app.core.second_factor", None)
    import app.core.second_factor as sf  # noqa: F401  — side-effect import
    # Reset singletons between tests.
    sf._GATE_SINGLETON = None
    yield sf
    sf._GATE_SINGLETON = None


# ── Enrollment + verify ───────────────────────────────────────────────

def test_totp_enroll_emits_sha256_uri(_in_memory_secret_store):
    sf = _in_memory_secret_store
    info = sf.enroll_totp(account_label="test@dupez")
    assert "otpauth_uri" in info
    assert "algorithm=SHA256" in info["otpauth_uri"]
    assert "digits=6" in info["otpauth_uri"]
    assert len(info["secret_b32"]) >= 40  # 256-bit key → ≥ 52 chars base32


def test_totp_current_code_verifies(_in_memory_secret_store):
    sf = _in_memory_secret_store
    info = sf.enroll_totp()
    gate = sf.get_gate()
    totp = next(p for p in gate.providers if isinstance(p, sf.TOTPProvider))
    seed = sf._b32_decode_lenient(info["secret_b32"])
    code = sf._totp(seed)
    assert totp.verify(code) is True


def test_totp_counter_cannot_be_replayed(_in_memory_secret_store):
    sf = _in_memory_secret_store
    info = sf.enroll_totp()
    gate = sf.get_gate()
    totp = next(p for p in gate.providers if isinstance(p, sf.TOTPProvider))
    code = sf._totp(sf._b32_decode_lenient(info["secret_b32"]))

    assert totp.verify(code) is True
    assert totp.verify(code) is False


def test_totp_wrong_code_fails(_in_memory_secret_store):
    sf = _in_memory_secret_store
    sf.enroll_totp()
    gate = sf.get_gate()
    totp = next(p for p in gate.providers if isinstance(p, sf.TOTPProvider))
    assert totp.verify("000000") is False
    assert totp.verify("999999") is False


def test_totp_accepts_skew_window(_in_memory_secret_store):
    sf = _in_memory_secret_store
    info = sf.enroll_totp()
    gate = sf.get_gate()
    totp = next(p for p in gate.providers if isinstance(p, sf.TOTPProvider))
    seed = sf._b32_decode_lenient(info["secret_b32"])
    # Code from 30s ago (one step back) must still verify.
    code_prev = sf._totp(seed, when=time.time() - 30)
    assert totp.verify(code_prev) is True
    # Code from 90s ago must NOT verify.
    code_stale = sf._totp(seed, when=time.time() - 90)
    assert totp.verify(code_stale) is False


def test_totp_rejects_non_digit_input(_in_memory_secret_store):
    sf = _in_memory_secret_store
    sf.enroll_totp()
    gate = sf.get_gate()
    totp = next(p for p in gate.providers if isinstance(p, sf.TOTPProvider))
    assert totp.verify("abcdef") is False
    assert totp.verify("12345") is False  # too short
    assert totp.verify("1234567") is False  # too long
    assert totp.verify("") is False


# ── Gate orchestration ────────────────────────────────────────────────

def test_gate_require_accepts_valid_code(_in_memory_secret_store):
    sf = _in_memory_secret_store
    info = sf.enroll_totp()
    seed = sf._b32_decode_lenient(info["secret_b32"])
    code = sf._totp(seed)
    ok = sf.get_gate().require("elevation", prompter=lambda scope: code)
    assert ok is True


def test_gate_require_rejects_unregistered_scope(_in_memory_secret_store):
    sf = _in_memory_secret_store
    sf.enroll_totp()
    with pytest.raises(sf.SecondFactorError):
        sf.get_gate().require("not_a_scope", prompter=lambda s: "000000")


def test_gate_require_without_enrollment_refuses(_in_memory_secret_store):
    sf = _in_memory_secret_store
    gate = sf.get_gate()
    assert gate.is_enrolled() is False
    with pytest.raises(sf.SecondFactorRequired):
        gate.require("elevation", prompter=lambda s: "000000")


def test_gate_cache_short_circuits_prompter(_in_memory_secret_store):
    sf = _in_memory_secret_store
    info = sf.enroll_totp()
    seed = sf._b32_decode_lenient(info["secret_b32"])
    code = sf._totp(seed)
    gate = sf.get_gate()
    calls = []
    gate.require("elevation", prompter=lambda s: (calls.append(1), code)[1])
    # Second require inside cache TTL must not call the prompter.
    gate.require("elevation", prompter=lambda s: (calls.append(2), "000000")[1])
    assert calls == [1]


def test_gate_rate_limiter_locks_out(_in_memory_secret_store):
    sf = _in_memory_secret_store
    sf.enroll_totp()
    gate = sf.get_gate()
    for _ in range(5):
        with pytest.raises(sf.SecondFactorRequired):
            gate.require("elevation", prompter=lambda s: "000000")
    with pytest.raises(sf.SecondFactorRateLimited):
        gate.require("elevation", prompter=lambda s: "000000")


def test_revoke_all_clears_enrollment(_in_memory_secret_store):
    sf = _in_memory_secret_store
    info = sf.enroll_totp()
    code = sf._totp(sf._b32_decode_lenient(info["secret_b32"]))
    assert sf.is_enrolled() is True
    sf.revoke_all(prompter=lambda _scope: code)
    assert sf.is_enrolled() is False


# ── Failure-mode tests ────────────────────────────────────────────────

def test_incomplete_fido2_surface_is_not_shipped(_in_memory_secret_store):
    """Unimplemented authentication providers must not be public stubs."""
    sf = _in_memory_secret_store
    assert not hasattr(sf, "FIDO2Provider")
    assert not hasattr(sf, "enroll_fido2")
    assert [provider.name for provider in sf.SecondFactorGate.default().providers] == [
        "totp"
    ]


def test_enroll_then_revoke_then_reenroll(_in_memory_secret_store):
    sf = _in_memory_secret_store
    info1 = sf.enroll_totp()
    code = sf._totp(sf._b32_decode_lenient(info1["secret_b32"]))
    sf.revoke_all(prompter=lambda _scope: code)
    info2 = sf.enroll_totp()
    assert info1["secret_b32"] != info2["secret_b32"], \
        "re-enrollment must rotate the seed"


def test_existing_totp_cannot_be_replaced_without_current_factor(
    _in_memory_secret_store,
) -> None:
    sf = _in_memory_secret_store
    first = sf.enroll_totp()

    with pytest.raises(sf.SecondFactorRequired):
        sf.enroll_totp(prompter=lambda _scope: "000000")

    gate = sf.get_gate()
    provider = next(p for p in gate.providers if isinstance(p, sf.TOTPProvider))
    valid = sf._totp(sf._b32_decode_lenient(first["secret_b32"]))
    second = sf.enroll_totp(prompter=lambda _scope: valid)
    assert second["secret_b32"] != first["secret_b32"]


def test_default_gui_prompter_masks_the_totp_code(
    _in_memory_secret_store,
    monkeypatch,
) -> None:
    sf = _in_memory_secret_store
    from PyQt6.QtWidgets import QApplication, QInputDialog, QLineEdit

    captured: list[object] = []
    monkeypatch.setattr(
        QApplication,
        "instance",
        staticmethod(lambda: object()),
    )

    def get_text(*args):
        captured.extend(args)
        return "123456", True

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(get_text))

    assert sf._default_prompter("elevation") == "123456"
    assert captured[-1] == QLineEdit.EchoMode.Password
