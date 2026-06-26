"""Tests for redacted support bundle generation."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.diagnostics import CheckResult, CheckStatus
from app.core.secret_store import SecretStoreHealth
from app.core.support_bundle import build_support_bundle, write_support_bundle


def _write(path: Path, text: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_support_bundle_redacts_paths_ips_and_macs(monkeypatch, tmp_path: Path) -> None:
    from app.core import support_bundle

    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Owner\AppData\Local")
    monkeypatch.setattr(
        support_bundle,
        "run_all_checks",
        lambda: [
            CheckResult(
                name="Network",
                status=CheckStatus.WARN,
                message=(
                    r"target 192.168.1.55 at C:\Users\Owner\AppData\Local "
                    "mac aa:bb:cc:dd:ee:ff"
                ),
            ),
        ],
    )
    monkeypatch.setattr(
        support_bundle,
        "check_store_health",
        lambda: SecretStoreHealth(
            path=Path(r"C:\Users\Owner\AppData\Local\DupeZ\secrets"),
            reachable=True,
            writable=False,
            error=(
                "[WinError 5] Access is denied: "
                r"'C:\Users\Owner\AppData\Local\DupeZ\secrets'"
            ),
            error_code="permission_denied",
        ),
    )
    _write(tmp_path / "audit.jsonl", "{}\n")

    payload = build_support_bundle(data_dir=tmp_path)
    rendered = json.dumps(payload)

    assert payload["schema"] == "dupez.support_bundle.v1"
    assert "192.168.1.55" not in rendered
    assert "192.168.1.x" in rendered
    assert "aa:bb:cc:dd:ee:ff" not in rendered
    assert "aa:bb:cc:**:**:**" in rendered
    assert r"C:\Users\Owner" not in rendered
    assert "%LOCALAPPDATA%" in rendered
    assert payload["privacy_inventory"]["total_files"] == 1
    assert payload["privacy_inventory"]["items"] == []
    assert payload["privacy_inventory"]["omitted_items"] == 1
    assert payload["retention"]["eligible_files"] == 0
    assert "packet-capture" in payload["retention"]["rules_days"]
    assert payload["storage"]["schema"] == "dupez.storage-status.v1"


def test_support_bundle_file_list_is_opt_in(monkeypatch, tmp_path: Path) -> None:
    from app.core import support_bundle

    monkeypatch.setattr(support_bundle, "run_all_checks", lambda: [])
    monkeypatch.setattr(
        support_bundle,
        "check_store_health",
        lambda: SecretStoreHealth(path=None, reachable=False, writable=False),
    )
    _write(tmp_path / "audit.jsonl", "{}\n")

    payload = build_support_bundle(data_dir=tmp_path, include_file_list=True)

    assert payload["privacy_inventory"]["include_file_list"] is True
    assert payload["privacy_inventory"]["omitted_items"] == 0
    assert payload["privacy_inventory"]["items"][0]["rel_path"] == "audit.jsonl"


def test_write_support_bundle_creates_json_file(monkeypatch, tmp_path: Path) -> None:
    from app.core import support_bundle

    monkeypatch.setattr(support_bundle, "run_all_checks", lambda: [])
    monkeypatch.setattr(
        support_bundle,
        "check_store_health",
        lambda: SecretStoreHealth(path=None, reachable=False, writable=False),
    )

    result = write_support_bundle(output_dir=tmp_path, data_dir=tmp_path)

    assert result.path is not None
    assert result.path.exists()
    loaded = json.loads(result.path.read_text(encoding="utf-8"))
    assert loaded["schema"] == "dupez.support_bundle.v1"
    assert loaded == result.payload
