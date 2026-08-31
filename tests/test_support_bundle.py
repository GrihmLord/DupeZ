"""Tests for redacted support bundle generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.diagnostics import CheckResult, CheckStatus
from app.core.support_bundle import (
    build_support_bundle,
    sanitize_support_value,
    write_support_bundle,
)


def _write(path: Path, text: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_support_bundle_redacts_paths_ips_and_macs(monkeypatch, tmp_path: Path) -> None:
    from app.core import support_bundle

    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\ExampleUser\AppData\Local")
    monkeypatch.setattr(
        support_bundle,
        "run_all_checks",
        lambda: [
            CheckResult(
                name="Network",
                status=CheckStatus.WARN,
                message=(
                    r"target 192.168.1.55 at C:\Users\ExampleUser\AppData\Local "
                    "mac aa:bb:cc:dd:ee:ff"
                ),
            ),
        ],
    )
    _write(tmp_path / "audit.jsonl", "{}\n")

    payload = build_support_bundle(data_dir=tmp_path)
    rendered = json.dumps(payload)

    assert payload["schema"] == "dupez.support_bundle.v1"
    assert "192.168.1.55" not in rendered
    assert "192.168.1.x" in rendered
    assert "aa:bb:cc:dd:ee:ff" not in rendered
    assert "aa:bb:cc:**:**:**" in rendered
    assert r"C:\Users\ExampleUser" not in rendered
    assert "%LOCALAPPDATA%" in rendered
    assert payload["privacy_inventory"]["total_files"] == 1
    assert payload["privacy_inventory"]["items"] == []
    assert payload["privacy_inventory"]["omitted_items"] == 1
    assert payload["retention"]["eligible_files"] == 0
    assert "packet-capture" in payload["retention"]["rules_days"]
    assert payload["storage"]["schema"] == "dupez.storage-status.v1"
    assert payload["secret_store"]["included"] is False


def test_support_bundle_file_list_is_opt_in(monkeypatch, tmp_path: Path) -> None:
    from app.core import support_bundle

    monkeypatch.setattr(support_bundle, "run_all_checks", lambda: [])
    _write(tmp_path / "audit.jsonl", "{}\n")

    payload = build_support_bundle(data_dir=tmp_path, include_file_list=True)

    assert payload["privacy_inventory"]["include_file_list"] is True
    assert payload["privacy_inventory"]["omitted_items"] == 0
    assert payload["privacy_inventory"]["items"][0]["rel_path"] == "audit.jsonl"


def test_write_support_bundle_creates_json_file(monkeypatch, tmp_path: Path) -> None:
    from app.core import support_bundle

    monkeypatch.setattr(support_bundle, "run_all_checks", lambda: [])
    result = write_support_bundle(output_dir=tmp_path, data_dir=tmp_path)

    assert result.path is not None
    assert result.path.exists()
    loaded = json.loads(result.path.read_text(encoding="utf-8"))
    assert loaded["schema"] == "dupez.support_bundle.v1"
    assert loaded == result.payload


def test_explicit_support_bundle_path_is_json_and_never_overwritten(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.core import support_bundle

    monkeypatch.setattr(support_bundle, "run_all_checks", lambda: [])
    requested = tmp_path / "chosen-name"

    result = write_support_bundle(
        output_path=requested,
        data_dir=tmp_path,
    )

    assert result.path == tmp_path / "chosen-name.json"
    original = result.path.read_bytes()
    with pytest.raises(FileExistsError):
        write_support_bundle(output_path=result.path, data_dir=tmp_path)
    assert result.path.read_bytes() == original


def test_default_support_bundle_collision_uses_a_new_filename(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.core import support_bundle

    monkeypatch.setattr(support_bundle, "run_all_checks", lambda: [])
    monkeypatch.setattr(
        support_bundle,
        "_utc_stamp",
        lambda _now=None: "20260824T120000Z",
    )
    existing = tmp_path / "support-bundle-20260824T120000Z.json"
    existing.write_text("do not overwrite", encoding="utf-8")

    result = write_support_bundle(output_dir=tmp_path, data_dir=tmp_path)

    assert existing.read_text(encoding="utf-8") == "do not overwrite"
    assert result.path == tmp_path / "support-bundle-20260824T120000Z-01.json"


def test_default_support_bundle_path_is_deterministic(tmp_path: Path) -> None:
    from app.core.support_bundle import default_support_bundle_path

    path = default_support_bundle_path(
        output_dir=tmp_path,
        now=datetime(2026, 8, 24, 12, 34, 56, tzinfo=timezone.utc),
    )

    assert path == tmp_path / "support-bundle-20260824T123456Z.json"


def test_default_support_bundle_path_uses_per_user_data_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.core import support_bundle

    monkeypatch.setattr(support_bundle, "_default_data_dir", lambda: tmp_path)

    path = support_bundle.default_support_bundle_path(
        now=datetime(2026, 8, 24, 12, 34, 56, tzinfo=timezone.utc),
    )

    assert path.parent == tmp_path


def test_unserializable_values_fail_before_any_bundle_file_is_created(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.core import support_bundle

    class _SecretBearingObject:
        def __str__(self) -> str:
            return "should-not-be-rendered"

    monkeypatch.setattr(
        support_bundle,
        "build_support_bundle",
        lambda **_kwargs: {"unsafe": _SecretBearingObject()},
    )

    with pytest.raises(TypeError):
        write_support_bundle(output_dir=tmp_path)

    assert list(tmp_path.glob("support-bundle-*.json")) == []


def test_supplied_diagnostics_are_reused_without_rerunning_checks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.core import support_bundle

    monkeypatch.setattr(
        support_bundle,
        "run_all_checks",
        lambda: (_ for _ in ()).throw(AssertionError("must not rerun")),
    )
    supplied = [
        CheckResult(
            name="Existing result",
            status=CheckStatus.PASS,
            message="already collected",
        )
    ]

    payload = build_support_bundle(
        data_dir=tmp_path,
        diagnostic_results=supplied,
    )

    assert payload["diagnostics"]["summary"] == {
        "pass": 1,
        "warn": 0,
        "fail": 0,
    }
    assert payload["diagnostics"]["results"][0]["name"] == "Existing result"


def test_support_sanitizer_removes_webhook_bearer_path() -> None:
    url = "https://discord.com/api/" + "webhooks/123/support-test"

    sanitized = sanitize_support_value({
        "audit_webhook": {"url": url},
        "diagnostic_message": f"transport failed for {url}",
    })

    rendered = json.dumps(sanitized)
    assert url not in rendered
    assert "support-test" not in rendered
    assert sanitized["audit_webhook"]["url"] == (
        "https://discord.com/[REDACTED]"
    )
    assert sanitized["diagnostic_message"] == (
        "transport failed for https://discord.com/[REDACTED]"
    )


def test_support_sanitizer_fails_closed_when_secret_scrubber_raises(
    monkeypatch,
) -> None:
    from app.core import secrets_manager

    def _raise(_value: str) -> str:
        raise RuntimeError("injected scrubber failure")

    monkeypatch.setattr(secrets_manager, "scrub_message", _raise)
    canary = "".join(("support-", "failure-", "canary"))

    sanitized = sanitize_support_value({"message": f"diagnostic {canary}"})

    assert canary not in sanitized["message"]
    assert sanitized["message"] == "[REDACTED: secret scrubber unavailable]"


def test_support_sanitizer_uses_builtin_path_fallback_when_redactor_raises(
    monkeypatch,
) -> None:
    from app.core import secret_store

    def _raise(_value: str) -> str:
        raise RuntimeError("injected path-redactor failure")

    monkeypatch.setattr(secret_store, "_redact_local_paths", _raise)
    monkeypatch.setenv(
        "LOCALAPPDATA",
        r"C:\Users\FallbackUser\AppData\Local",
    )
    raw_path = r"C:\Users\FallbackUser\AppData\Local\DupeZ\audit.jsonl"

    sanitized = sanitize_support_value({"message": f"read failed at {raw_path}"})

    assert "FallbackUser" not in sanitized["message"]
    assert sanitized["message"] == (
        r"read failed at %LOCALAPPDATA%\DupeZ\audit.jsonl"
    )


def test_support_sanitizer_redacts_sensitive_fields_without_value_heuristics() -> None:
    canary = "".join(("short-", "opaque-", "value"))

    sanitized = sanitize_support_value(
        {"api" + "_key": canary, "nested": {"authorization": canary}}
    )

    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["authorization"] == "[REDACTED]"
