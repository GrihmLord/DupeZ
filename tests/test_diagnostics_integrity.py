"""Focused tests for diagnostics covering integrity substrate health."""

from __future__ import annotations

import pytest

import app.core.diagnostics as diagnostics
from app.core.diagnostics import CheckStatus


def test_secret_store_passes_when_probe_is_writable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import app.core.secret_store as secret_store

    monkeypatch.setattr(secret_store, "store_root", lambda: tmp_path)

    result = diagnostics._check_secret_store()

    assert result.status == CheckStatus.PASS
    assert result.fix_hint == ""
    assert not (tmp_path / ".diagnostics_write_probe.tmp").exists()


def test_persistence_key_warns_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.data_persistence as data_persistence

    monkeypatch.setattr(
        data_persistence,
        "persistence_key_degraded",
        lambda: True,
    )

    result = diagnostics._check_persistence_key()

    assert result.status == CheckStatus.WARN
    assert "fallback key" in result.message
    assert result.fix_hint


def test_persistence_key_passes_when_not_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.data_persistence as data_persistence

    monkeypatch.setattr(
        data_persistence,
        "persistence_key_degraded",
        lambda: False,
    )

    result = diagnostics._check_persistence_key()

    assert result.status == CheckStatus.PASS
    assert result.fix_hint == ""


def test_audit_chain_fails_when_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.logs.audit as audit_module

    class FakeAudit:
        degraded = False

        def verify_chain(self) -> tuple[bool, int, str]:
            return True, 4, ""

        def is_sealed(self) -> bool:
            return True

    monkeypatch.setattr(audit_module, "get_audit_logger", FakeAudit)

    result = diagnostics._check_audit_chain()

    assert result.status == CheckStatus.FAIL
    assert "sealed" in result.message
    assert "reset-audit" in result.fix_hint


def test_audit_chain_fails_when_verification_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.logs.audit as audit_module

    class FakeAudit:
        degraded = False

        def verify_chain(self) -> tuple[bool, int, str]:
            return False, 2, "HMAC mismatch"

        def is_sealed(self) -> bool:
            return False

    monkeypatch.setattr(audit_module, "get_audit_logger", FakeAudit)

    result = diagnostics._check_audit_chain()

    assert result.status == CheckStatus.FAIL
    assert "HMAC mismatch" in result.message
    assert result.fix_hint


def test_audit_chain_warns_when_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.logs.audit as audit_module

    class FakeAudit:
        degraded = True

        def verify_chain(self) -> tuple[bool, int, str]:
            return True, 3, ""

        def is_sealed(self) -> bool:
            return False

    monkeypatch.setattr(audit_module, "get_audit_logger", FakeAudit)

    result = diagnostics._check_audit_chain()

    assert result.status == CheckStatus.WARN
    assert "degraded" in result.message
    assert result.fix_hint
