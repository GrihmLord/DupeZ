"""Shared pytest fixtures for DupeZ test suite."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_BASETEMP = _REPO_ROOT / ".pytest-tmp"


def pytest_configure(config):
    """Session-start setup: basetemp pin + v5.7.6 test isolation."""
    if not getattr(config.option, "basetemp", None):
        _REPO_BASETEMP.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(_REPO_BASETEMP)

    # v5.7.6 -- webhook host allowlist escape hatch for tests using
    # https://example.invalid/*. Shipped product never sets this var.
    os.environ.setdefault(
        "DUPEZ_TEST_WEBHOOK_HOSTS",
        "example.invalid,example.com,test.localhost,attacker.example.com",
    )

    # v5.7.6 -- redirect the global audit singleton to a per-session
    # tempdir BEFORE any test imports trigger get_audit_logger().
    # The TAMPER sentinel persists across processes by design, so
    # without this redirection a prior sealed session would block
    # every audit-emitting test until --reset-audit. Tests must never
    # depend on operator action.
    try:
        _td = tempfile.mkdtemp(prefix="dupez-audit-test-")
        from app.logs import audit as _audit_mod
        _audit_mod._audit_logger = _audit_mod.AuditLogger(audit_dir=_td)
        sys.stderr.write(
            f"[conftest] audit singleton -> {_td} sealed="
            f"{_audit_mod._audit_logger.sealed}\n"
        )
    except Exception as exc:
        sys.stderr.write(f"[conftest] audit isolation skipped: {exc}\n")


@pytest.fixture
def profiles_dir(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    return str(d)


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


@pytest.fixture(autouse=True)
def isolate_operation_journal(monkeypatch, tmp_path):
    """Never let tests write the host user's crash-recovery marker."""
    from app.core import operation_journal

    path = tmp_path / "recovery" / "active-operation.json"
    monkeypatch.setattr(operation_journal, "default_journal_path", lambda: path)
