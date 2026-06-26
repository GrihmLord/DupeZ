"""Tests for non-secret secret-store health probing."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.core.secret_store as secret_store


def test_check_store_health_passes_for_writable_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(secret_store, "store_root", lambda: tmp_path)

    health = secret_store.check_store_health()

    assert health.healthy
    assert health.path == tmp_path
    assert health.reachable
    assert health.writable
    assert health.error == ""
    assert not (tmp_path / ".diagnostics_write_probe.tmp").exists()


def test_check_store_health_reports_unreachable_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_permission_error() -> Path:
        raise PermissionError("denied")

    monkeypatch.setattr(secret_store, "store_root", raise_permission_error)

    health = secret_store.check_store_health()

    assert not health.healthy
    assert health.path is None
    assert not health.reachable
    assert not health.writable
    assert "denied" in health.error
    assert health.error_code == "permission_denied"
    assert "current Windows user" in health.remediation_hint


def test_health_redacts_local_appdata_from_user_facing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_appdata = r"C:\Users\Owner\AppData\Local"
    monkeypatch.setenv("LOCALAPPDATA", local_appdata)

    health = secret_store.SecretStoreHealth(
        path=Path(local_appdata) / "DupeZ" / "secrets",
        reachable=True,
        writable=False,
        error=(
            "[WinError 5] Access is denied: "
            "'C:\\Users\\Owner\\AppData\\Local\\DupeZ\\secrets'"
        ),
        error_code="permission_denied",
    )

    assert "%LOCALAPPDATA%" in (health.safe_path or "")
    assert "%LOCALAPPDATA%" in health.safe_error
    assert r"C:\Users\Owner" not in (health.safe_path or "")
    assert r"C:\Users\Owner" not in health.safe_error


def test_repair_plan_is_review_only_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health = secret_store.SecretStoreHealth(
        path=Path(r"C:\Users\Owner\AppData\Local\DupeZ\secrets"),
        reachable=True,
        writable=False,
        error_code="permission_denied",
    )
    monkeypatch.setattr(secret_store, "check_store_health", lambda: health)
    monkeypatch.setattr(secret_store.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Owner\AppData\Local")

    plan = secret_store.secret_store_repair_plan()

    assert plan["healthy"] is False
    assert "never executed automatically" in plan["warning"]
    assert any("icacls" in command for command in plan["commands"])
    assert all(r"C:\Users\Owner" not in command for command in plan["commands"])
