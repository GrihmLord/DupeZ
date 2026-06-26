"""CLI regression tests for non-admin maintenance commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def test_diagnostics_command_does_not_require_admin_or_controller(monkeypatch) -> None:
    from app import cli

    called = {}

    def fake_diagnostics(controller, args):
        called["controller"] = controller
        called["command"] = args.command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "diagnostics", fake_diagnostics)
    monkeypatch.setattr(sys, "argv", ["dupez-cli", "diagnostics"])

    cli.main()

    assert called == {"controller": None, "command": "diagnostics"}


def test_recovery_command_does_not_require_admin_or_controller(monkeypatch) -> None:
    from app import cli

    called = {}

    def fake_recovery(controller, args):
        called["controller"] = controller
        called["command"] = args.command
        called["recovery_command"] = args.recovery_command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "recovery", fake_recovery)
    monkeypatch.setattr(sys, "argv", ["dupez-cli", "recovery", "audit-status"])

    cli.main()

    assert called == {
        "controller": None,
        "command": "recovery",
        "recovery_command": "audit-status",
    }


def test_secret_store_recovery_command_does_not_require_admin_or_controller(
    monkeypatch,
) -> None:
    from app import cli

    called = {}

    def fake_recovery(controller, args):
        called["controller"] = controller
        called["command"] = args.command
        called["recovery_command"] = args.recovery_command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "recovery", fake_recovery)
    monkeypatch.setattr(
        sys,
        "argv",
        ["dupez-cli", "recovery", "secret-store-status"],
    )

    cli.main()

    assert called == {
        "controller": None,
        "command": "recovery",
        "recovery_command": "secret-store-status",
    }


def test_support_command_does_not_require_admin_or_controller(monkeypatch) -> None:
    from app import cli

    called = {}

    def fake_support(controller, args):
        called["controller"] = controller
        called["command"] = args.command
        called["support_command"] = args.support_command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "support", fake_support)
    monkeypatch.setattr(sys, "argv", ["dupez-cli", "support", "bundle"])

    cli.main()

    assert called == {
        "controller": None,
        "command": "support",
        "support_command": "bundle",
    }


def test_safety_command_does_not_require_admin_or_controller(monkeypatch) -> None:
    from app import cli

    called = {}

    def fake_safety(controller, args):
        called["controller"] = controller
        called["command"] = args.command
        called["safety_command"] = args.safety_command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "safety", fake_safety)
    monkeypatch.setattr(sys, "argv", ["dupez-cli", "safety", "status"])

    cli.main()

    assert called == {
        "controller": None,
        "command": "safety",
        "safety_command": "status",
    }


def test_storage_command_does_not_require_admin_or_controller(monkeypatch) -> None:
    from app import cli

    called = {}

    def fake_storage(controller, args):
        called["controller"] = controller
        called["command"] = args.command
        called["storage_command"] = args.storage_command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "storage", fake_storage)
    monkeypatch.setattr(sys, "argv", ["dupez-cli", "storage", "status"])

    cli.main()

    assert called == {
        "controller": None,
        "command": "storage",
        "storage_command": "status",
    }


def test_health_command_does_not_require_admin_or_controller(monkeypatch) -> None:
    from app import cli

    called = {}

    def fake_health(controller, args):
        called["controller"] = controller
        called["command"] = args.command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "health", fake_health)
    monkeypatch.setattr(sys, "argv", ["dupez-cli", "health", "--json"])

    cli.main()

    assert called == {"controller": None, "command": "health"}


def test_pktmon_plan_does_not_require_admin_or_controller(monkeypatch) -> None:
    from app import cli

    called = {}

    def fake_pktmon(controller, args):
        called["controller"] = controller
        called["command"] = args.command
        called["pktmon_command"] = args.pktmon_command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "pktmon", fake_pktmon)
    monkeypatch.setattr(
        sys,
        "argv",
        ["dupez-cli", "pktmon", "plan", "--port", "2302", "--json"],
    )

    cli.main()

    assert called == {
        "controller": None,
        "command": "pktmon",
        "pktmon_command": "plan",
    }


def test_performance_command_does_not_require_admin_or_controller(monkeypatch) -> None:
    from app import cli

    called = {}

    def fake_performance(controller, args):
        called["controller"] = controller
        called["command"] = args.command
        called["performance_command"] = args.performance_command

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setitem(cli._CMD_MAP, "performance", fake_performance)
    monkeypatch.setattr(sys, "argv", ["dupez-cli", "performance", "smoke"])

    cli.main()

    assert called == {
        "controller": None,
        "command": "performance",
        "performance_command": "smoke",
    }


def test_health_json_is_machine_readable(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.network_health as health

    monkeypatch.setattr(
        health,
        "build_network_health_snapshot",
        lambda: {
            "schema": "dupez.network-health.v1",
            "overall": {
                "status": "healthy",
                "score": 100,
                "summary": {"pass": 1, "warn": 0, "fail": 0},
            },
        },
    )

    cli.cmd_health(None, argparse_namespace(json=True))

    assert json.loads(capsys.readouterr().out)["schema"] == (
        "dupez.network-health.v1"
    )


def test_scenario_report_command_uses_active_snapshot(
    monkeypatch,
    capsys,
) -> None:
    from app import cli

    class Controller:
        def get_active_operations(self):
            return [{
                "target": "192.168.1.x",
                "methods": ["lag"],
                "params_fingerprint": "abc",
                "automatic_stop_armed": True,
            }]

    cli.cmd_report(
        Controller(),
        argparse_namespace(
            report_command="active",
            output_dir=None,
            json=True,
        ),
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "dupez.cli.scenario_report.v1"
    assert payload["ok"] is True
    assert payload["report"]["operations"][0]["target"] == "192.168.1.x"


def test_safety_acknowledgement_requires_explicit_flag(
    monkeypatch,
    capsys,
) -> None:
    from app import cli
    import app.core.operator_acknowledgement as acknowledgement

    called = []
    monkeypatch.setattr(
        acknowledgement,
        "record_acknowledgement",
        lambda: called.append(True),
    )

    cli.cmd_safety(
        None,
        argparse_namespace(
            safety_command="acknowledge",
            owned_authorized_network=False,
        ),
    )

    assert called == []
    assert "Explicit confirmation is required" in capsys.readouterr().out


def test_disrupt_refuses_without_acknowledgement(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.operator_acknowledgement as acknowledgement

    class Controller:
        def disrupt_device(self, *_args, **_kwargs):
            raise AssertionError("controller must not be called")

    monkeypatch.setattr(acknowledgement, "is_acknowledged", lambda: False)

    cli.cmd_disrupt(
        Controller(),
        argparse_namespace(
            ip="192.168.1.20",
            methods=None,
            params=None,
            dry_run=False,
        ),
    )

    assert "Authorized-use acknowledgement is required" in (
        capsys.readouterr().out
    )


def test_secret_store_status_reports_health(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.secret_store as secret_store

    health = secret_store.SecretStoreHealth(
        path=Path("C:/tmp/dupez-secrets"),
        reachable=True,
        writable=True,
    )
    monkeypatch.setattr(secret_store, "check_store_health", lambda: health)

    cli.cmd_recovery(None, argparse_namespace("secret-store-status"))

    out = capsys.readouterr().out
    assert "Secret store status" in out
    assert "Healthy:   True" in out
    assert "C:\\tmp\\dupez-secrets" in out or "C:/tmp/dupez-secrets" in out


def test_secret_store_status_json_reports_health(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.secret_store as secret_store

    health = secret_store.SecretStoreHealth(
        path=Path("C:/tmp/dupez-secrets"),
        reachable=True,
        writable=True,
    )
    monkeypatch.setattr(secret_store, "check_store_health", lambda: health)

    cli.cmd_recovery(None, argparse_namespace("secret-store-status", json=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "dupez.cli.secret_store_status.v1"
    assert payload["secret_store"]["healthy"] is True
    assert payload["secret_store"]["path"]
    assert "error_code" in payload["secret_store"]


def test_secret_store_repair_plan_json(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.secret_store as secret_store

    monkeypatch.setattr(
        secret_store,
        "secret_store_repair_plan",
        lambda: {
            "healthy": False,
            "error_code": "permission_denied",
            "path": r"%LOCALAPPDATA%\DupeZ\secrets",
            "warning": "review only",
            "steps": ["inspect"],
            "commands": ["icacls ..."],
        },
    )

    cli.cmd_recovery(
        None,
        argparse_namespace("secret-store-repair-plan", json=True),
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "dupez.cli.secret_store_repair_plan.v1"
    assert payload["commands"] == ["icacls ..."]


def test_support_bundle_json_reports_path(monkeypatch, tmp_path, capsys) -> None:
    from app import cli
    import app.core.support_bundle as support_bundle

    payload = {"schema": "dupez.support_bundle.v1", "diagnostics": {}}
    result = support_bundle.SupportBundleResult(
        payload=payload,
        path=tmp_path / "support-bundle-test.json",
    )
    monkeypatch.setattr(support_bundle, "write_support_bundle", lambda **_kw: result)

    cli.cmd_support(
        None,
        argparse_namespace(
            support_command="bundle",
            json=True,
            output_dir=str(tmp_path),
        ),
    )

    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "dupez.cli.support_bundle.v1"
    assert out["ok"] is True
    assert out["payload"] == payload
    assert out["path"].endswith("support-bundle-test.json")


def test_support_bundle_json_reports_write_error(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.support_bundle as support_bundle

    monkeypatch.setattr(
        support_bundle,
        "write_support_bundle",
        lambda **_kw: (_ for _ in ()).throw(
            PermissionError(r"C:\Users\Owner\AppData\Local\blocked")
        ),
    )

    cli.cmd_support(
        None,
        argparse_namespace(support_command="bundle", json=True),
    )

    out = json.loads(capsys.readouterr().out)
    rendered = json.dumps(out)
    assert out["schema"] == "dupez.cli.support_bundle.v1"
    assert out["ok"] is False
    assert out["path"] is None
    assert r"C:\Users\Owner" not in rendered


def test_diagnostics_json_reports_summary(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.diagnostics as diagnostics

    monkeypatch.setattr(
        diagnostics,
        "run_all_checks",
        lambda: [
            diagnostics.CheckResult(
                name="Unit check",
                status=diagnostics.CheckStatus.PASS,
                message="ok",
            ),
        ],
    )

    cli.cmd_diagnostics(None, argparse_namespace(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "dupez.cli.diagnostics.v1"
    assert payload["summary"] == {"fail": 0, "pass": 1, "warn": 0}
    assert payload["results"][0]["name"] == "Unit check"


def test_secret_store_status_redacts_user_path(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.secret_store as secret_store

    health = secret_store.SecretStoreHealth(
        path=Path(r"C:\Users\Owner\AppData\Local\DupeZ\secrets"),
        reachable=True,
        writable=False,
        error=(
            "[WinError 5] Access is denied: "
            "'C:\\Users\\Owner\\AppData\\Local\\DupeZ\\secrets'"
        ),
        error_code="permission_denied",
    )
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Owner\AppData\Local")
    monkeypatch.setattr(secret_store, "check_store_health", lambda: health)

    cli.cmd_recovery(None, argparse_namespace("secret-store-status", json=True))

    payload = json.loads(capsys.readouterr().out)
    rendered = json.dumps(payload)
    assert "%LOCALAPPDATA%" in rendered
    assert r"C:\Users\Owner" not in rendered
    assert payload["secret_store"]["error_code"] == "permission_denied"


def test_diagnostics_json_redirects_collector_stdout(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.diagnostics as diagnostics

    def noisy_checks():
        print("noisy initialization")
        return [
            diagnostics.CheckResult(
                name="Unit check",
                status=diagnostics.CheckStatus.PASS,
                message="ok",
            ),
        ]

    monkeypatch.setattr(diagnostics, "run_all_checks", noisy_checks)

    cli.cmd_diagnostics(None, argparse_namespace(json=True))

    captured = capsys.readouterr()
    assert "noisy initialization" not in captured.out
    assert "noisy initialization" in captured.err
    assert json.loads(captured.out)["schema"] == "dupez.cli.diagnostics.v1"


def test_privacy_scan_json_reports_items(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.privacy as privacy

    monkeypatch.setattr(
        privacy,
        "scan_privacy_items",
        lambda include_account_data=False: [
            privacy.PrivacyItem(
                path=Path("C:/tmp/audit.jsonl"),
                rel_path="audit.jsonl",
                category="audit",
                size_bytes=12,
                reason="test",
            ),
        ],
    )

    cli.cmd_privacy(
        None,
        argparse_namespace(
            privacy_command="scan",
            include_account_data=False,
            json=True,
        ),
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "dupez.cli.privacy_scan.v1"
    assert payload["total_files"] == 1
    assert payload["items"][0]["rel_path"] == "audit.jsonl"


def test_privacy_retention_json_reports_eligible_items(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.privacy as privacy

    item = privacy.PrivacyItem(
        path=Path("C:/tmp/old.pcapng"),
        rel_path="captures/old.pcapng",
        category="packet-capture",
        size_bytes=7,
        reason="test",
    )
    plan = privacy.RetentionPlan(
        rules={"packet-capture": 7},
        items=[item],
        eligible=[item],
        total_bytes=7,
        eligible_bytes=7,
    )
    result = privacy.ScrubResult(
        dry_run=True,
        quarantine_dir=None,
        items=[item],
        removed=[],
        errors=[],
    )
    monkeypatch.setattr(privacy, "build_retention_plan", lambda **_kw: plan)
    monkeypatch.setattr(privacy, "enforce_retention_policy", lambda **_kw: result)

    cli.cmd_privacy(
        None,
        argparse_namespace(
            privacy_command="retention",
            include_account_data=False,
            json=True,
            apply=False,
            delete=False,
            max_age=["packet-capture=7"],
        ),
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "dupez.cli.privacy_retention.v1"
    assert payload["dry_run"] is True
    assert payload["eligible_files"] == 1
    assert payload["eligible"][0]["rel_path"] == "captures/old.pcapng"


def test_privacy_retention_rejects_invalid_rule(capsys) -> None:
    from app import cli

    cli.cmd_privacy(
        None,
        argparse_namespace(
            privacy_command="retention",
            json=True,
            apply=False,
            delete=False,
            max_age=["packet-capture"],
        ),
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "dupez.cli.privacy_retention.v1"
    assert payload["ok"] is False
    assert "CATEGORY=DAYS" in payload["error"]


def test_storage_status_json_is_redacted(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.storage_status as storage_status

    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Owner\AppData\Local")
    monkeypatch.setattr(
        storage_status,
        "build_storage_status",
        lambda: {
            "schema": "dupez.storage-status.v1",
            "runtime": {
                "installed": True,
                "legacy_runtime_root": r"C:\Users\Owner\AppData\Local\DupeZ",
            },
            "roots": {},
            "migration": {"markers": {}, "legacy_candidates": {}},
            "recommendations": [],
        },
    )

    cli.cmd_storage(None, argparse_namespace(storage_command="status", json=True))

    payload = json.loads(capsys.readouterr().out)
    rendered = json.dumps(payload)
    assert payload["schema"] == "dupez.storage-status.v1"
    assert "%LOCALAPPDATA%" in rendered
    assert r"C:\Users\Owner" not in rendered


def test_performance_smoke_json_reports_checks(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.performance_smoke as performance_smoke

    monkeypatch.setattr(
        performance_smoke,
        "run_performance_smoke",
        lambda **_kw: {
            "schema": "dupez.performance-smoke.v1",
            "ok": True,
            "checks": [{"name": "unit", "ok": True}],
        },
    )

    cli.cmd_performance(
        None,
        argparse_namespace(
            performance_command="smoke",
            iterations=1,
            include_support_bundle=False,
            json=True,
        ),
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "dupez.performance-smoke.v1"
    assert payload["ok"] is True


def test_json_safe_command_suppresses_banner(monkeypatch, capsys) -> None:
    from app import cli
    import app.core.secret_store as secret_store

    health = secret_store.SecretStoreHealth(
        path=Path("C:/tmp/dupez-secrets"),
        reachable=True,
        writable=True,
    )
    monkeypatch.setattr(secret_store, "check_store_health", lambda: health)
    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["dupez-cli", "recovery", "secret-store-status", "--json"],
    )

    cli.main()

    out = capsys.readouterr().out
    assert out.lstrip().startswith("{")
    assert "CLI Mode" not in out


def test_active_command_still_requires_admin(monkeypatch) -> None:
    from app import cli

    monkeypatch.setattr(cli, "is_admin", lambda: False)
    monkeypatch.setattr(sys, "argv", ["dupez-cli", "status"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1


def argparse_namespace(
    recovery_command: str = "",
    *,
    privacy_command: str = "",
    performance_command: str = "",
    support_command: str = "",
    safety_command: str = "",
    storage_command: str = "",
    include_account_data: bool = False,
    include_file_list: bool = False,
    json: bool = False,
    output_dir: str | None = None,
    **extra,
):
    import argparse

    return argparse.Namespace(
        recovery_command=recovery_command,
        privacy_command=privacy_command,
        performance_command=performance_command,
        support_command=support_command,
        safety_command=safety_command,
        storage_command=storage_command,
        include_account_data=include_account_data,
        include_file_list=include_file_list,
        json=json,
        output_dir=output_dir,
        **extra,
    )
