# app/cli.py — DupeZ CLI Mode
"""
Headless terminal interface for DupeZ.

Usage::

    python -m app.cli scan                          # Quick network scan
    python -m app.cli scan --full                   # Full network scan
    python -m app.cli disrupt <ip> [--methods ...]  # Start disruption
    python -m app.cli stop <ip>                     # Stop disruption on IP
    python -m app.cli stop --all                    # Stop all disruptions
    python -m app.cli status                        # Show engine status
    python -m app.cli devices                       # List known devices
    python -m app.cli plugins                       # List plugins
    python -m app.cli diagnostics                   # Run safe diagnostics
    python -m app.cli health --json                 # Unified network health
    python -m app.cli privacy scan                  # Inventory local private runtime data
    python -m app.cli privacy scrub --apply         # Quarantine local private runtime data
    python -m app.cli recovery audit-status         # Check audit integrity state
    python -m app.cli recovery secret-store-status  # Check key-store access
    python -m app.cli support bundle                # Write redacted support bundle
    python -m app.cli interactive                   # Interactive REPL
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager, redirect_stdout
from typing import Any, Callable, Dict

# Ensure we can import app modules when running frozen
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

from app.logs.logger import log_info, log_shutdown, log_startup
from app.utils.helpers import is_admin
from app.core.updater import CURRENT_VERSION

_BANNER = rf"""
 ██████╗ ██╗   ██╗██████╗ ███████╗███████╗
 ██╔══██╗██║   ██║██╔══██╗██╔════╝╚══███╔╝
 ██║  ██║██║   ██║██████╔╝█████╗    ███╔╝
 ██║  ██║██║   ██║██╔═══╝ ██╔══╝   ███╔╝
 ██████╔╝╚██████╔╝██║     ███████╗███████╗
 ╚═════╝  ╚═════╝ ╚═╝     ╚══════╝╚══════╝
 v{CURRENT_VERSION} — CLI Mode
"""

__all__ = [
    "cmd_scan",
    "cmd_disrupt",
    "cmd_stop",
    "cmd_status",
    "cmd_devices",
    "cmd_plugins",
    "cmd_diagnostics",
    "cmd_health",
    "cmd_pktmon",
    "cmd_performance",
    "cmd_report",
    "cmd_privacy",
    "cmd_recovery",
    "cmd_safety",
    "cmd_storage",
    "cmd_support",
    "cmd_interactive",
    "main",
]


def _print_banner() -> None:
    print(_BANNER)


def _print_json(payload: Dict[str, Any]) -> None:
    """Emit stable JSON for safe maintenance commands."""
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _diagnostic_result_dict(result: Any) -> Dict[str, Any]:
    return {
        "name": result.name,
        "status": result.status,
        "message": result.message,
        "fix_hint": result.fix_hint,
        "fix_command": result.fix_command,
    }


def _privacy_item_dict(item: Any) -> Dict[str, Any]:
    return {
        "rel_path": item.rel_path,
        "category": item.category,
        "size_bytes": item.size_bytes,
        "reason": item.reason,
        "item_type": getattr(item, "item_type", "file"),
    }


def _parse_retention_rules(values: list[str] | None) -> Dict[str, int]:
    rules: Dict[str, int] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError("retention rules must use CATEGORY=DAYS")
        category, days_text = value.split("=", 1)
        category = category.strip()
        if not category:
            raise ValueError("retention rule category is required")
        try:
            days = int(days_text)
        except ValueError as exc:
            raise ValueError(f"invalid day count for {category!r}") from exc
        if days < 0:
            raise ValueError("retention days must be zero or greater")
        rules[category] = days
    return rules


def _wants_json(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False))


@contextmanager
def _json_output_context():
    """Keep stdout parseable while JSON commands collect noisy state."""
    redirected = []
    dupez_logger = logging.getLogger("DupeZ")
    for handler in dupez_logger.handlers:
        if (
            isinstance(handler, logging.StreamHandler)
            and getattr(handler, "stream", None) is sys.stdout
        ):
            redirected.append((handler, handler.stream))
            handler.stream = sys.stderr
    try:
        with redirect_stdout(sys.stderr):
            yield
    finally:
        for handler, stream in redirected:
            handler.stream = stream


# ── Subcommands ───────────────────────────────────────────────────────

def cmd_scan(controller: Any, args: argparse.Namespace) -> None:
    """Scan network for devices."""
    print("[*] Scanning network...")
    quick = not args.full
    devices = controller.scan_devices(quick=quick)
    if not devices:
        print("[!] No devices found")
        return

    print(f"\n[+] Found {len(devices)} device(s):\n")
    print(f"  {'IP':<18} {'MAC':<20} {'Hostname':<25} {'Vendor'}")
    print(f"  {'─' * 18} {'─' * 20} {'─' * 25} {'─' * 20}")
    for d in devices:
        ip = d.get("ip", "") if isinstance(d, dict) else d.ip
        mac = d.get("mac", "") if isinstance(d, dict) else d.mac
        hostname = d.get("hostname", "Unknown") if isinstance(d, dict) else d.hostname
        vendor = d.get("vendor", "") if isinstance(d, dict) else d.vendor
        print(f"  {ip:<18} {mac:<20} {hostname:<25} {vendor}")


def cmd_disrupt(controller: Any, args: argparse.Namespace) -> None:
    """Start disruption on a target IP."""
    dry_run = bool(getattr(args, "dry_run", False))
    if not dry_run:
        from app.core.operator_acknowledgement import is_acknowledged

        if not is_acknowledged():
            print("[!] Authorized-use acknowledgement is required.")
            print(
                "    Run: dupez-cli safety acknowledge "
                "--owned-authorized-network"
            )
            print("    Or use --dry-run to validate without changing traffic.")
            return
    if not args.ip:
        print("[!] Usage: dupez cli disrupt <ip> [--methods drop,lag] [--params '{...}']")
        return

    from app.core.validation import validate_methods, validate_params, safe_json_loads
    methods = validate_methods(args.methods.split(",")) if args.methods else None
    try:
        raw_params = safe_json_loads(args.params, context="CLI --params") if args.params else None
    except ValueError as e:
        print(f"[!] Invalid --params JSON: {e}")
        return
    params = validate_params(raw_params) if raw_params else None

    print(f"[*] Starting disruption on {args.ip}...")
    if methods:
        print(f"    Methods: {', '.join(methods)}")
    if params:
        print(f"    Params: {params}")

    success = controller.disrupt_device(
        args.ip,
        methods,
        params,
        operation_timeout=getattr(args, "max_duration", None),
    )
    print(f"[+] Dry run accepted for {args.ip}" if success and dry_run
          else f"[+] Disruption active on {args.ip}" if success
          else f"[!] Failed to start disruption on {args.ip}")


def cmd_stop(controller: Any, args: argparse.Namespace) -> None:
    """Stop disruption."""
    if args.all:
        print("[*] Stopping all disruptions...")
        controller.stop_all_disruptions()
        print("[+] All disruptions cleared")
    elif args.ip:
        print(f"[*] Stopping disruption on {args.ip}...")
        success = controller.stop_disruption(args.ip)
        print(f"[+] Disruption stopped on {args.ip}" if success
              else f"[!] Failed to stop disruption on {args.ip}")
    else:
        print("[!] Usage: dupez cli stop <ip> or dupez cli stop --all")


def cmd_status(controller: Any, args: argparse.Namespace) -> None:
    """Show engine status."""
    if _wants_json(args):
        from app.core.support_bundle import sanitize_support_value

        _print_json({
            "schema": "dupez.cli.engine_status.v1",
            "engine": sanitize_support_value(
                controller.get_clumsy_status()
            ),
            "operations": controller.get_active_operations(),
            "stats": sanitize_support_value(controller.get_engine_stats()),
        })
        return
    clumsy_status = controller.get_clumsy_status()
    disrupted = controller.get_disrupted_devices()
    stats = controller.get_engine_stats()

    print("[*] Engine Status:\n")
    print(f"  Clumsy initialized: {clumsy_status.get('initialized', False)}")
    print(f"  Clumsy running:     {clumsy_status.get('running', False)}")
    print(f"  Active disruptions: {len(disrupted)}")

    if disrupted:
        print("\n  Disrupted IPs:")
        for ip in disrupted:
            status = controller.get_disruption_status(ip)
            methods = status.get("methods", []) if status else []
            print(f"    {ip} — methods: {', '.join(methods) if methods else 'default'}")

    if stats:
        print("\n  Packet Stats:")
        for key, val in stats.items():
            print(f"    {key}: {val}")


def cmd_devices(controller: Any, args: argparse.Namespace) -> None:
    """List known devices."""
    devices = controller.get_devices()
    if not devices:
        print("[!] No devices cached. Run 'scan' first.")
        return

    print(f"[+] {len(devices)} known device(s):\n")
    for d in devices:
        ip = d.ip if hasattr(d, "ip") else d.get("ip", "")
        hostname = d.hostname if hasattr(d, "hostname") else d.get("hostname", "")
        blocked = d.blocked if hasattr(d, "blocked") else d.get("blocked", False)
        status = "BLOCKED" if blocked else "ok"
        print(f"  {ip:<18} {hostname or 'Unknown':<25} [{status}]")


def cmd_plugins(controller: Any, args: argparse.Namespace) -> None:
    """List plugins."""
    info = controller.get_plugin_info()
    if not info:
        print("[*] No plugins found in plugins/ directory")
        return

    print(f"[+] {len(info)} plugin(s):\n")
    print(f"  {'Name':<20} {'Version':<10} {'Type':<12} {'Status':<10} Description")
    print(f"  {'─' * 20} {'─' * 10} {'─' * 12} {'─' * 10} {'─' * 30}")
    for p in info:
        status = "active" if p["active"] else ("error" if p.get("error") else "inactive")
        print(f"  {p['name']:<20} {p['version']:<10} {p['type']:<12} {status:<10} {p['description'][:40]}")


def cmd_diagnostics(controller: Any, args: argparse.Namespace) -> None:
    """Run safe diagnostics without starting the packet engine."""
    from app.core.diagnostics import CheckStatus, run_all_checks

    if _wants_json(args):
        with _json_output_context():
            results = run_all_checks()
        _print_json({
            "schema": "dupez.cli.diagnostics.v1",
            "results": [_diagnostic_result_dict(result) for result in results],
            "summary": {
                "pass": sum(1 for result in results if result.status == CheckStatus.PASS),
                "warn": sum(1 for result in results if result.status == CheckStatus.WARN),
                "fail": sum(1 for result in results if result.status == CheckStatus.FAIL),
            },
        })
        return

    results = run_all_checks()
    print("[*] Diagnostics:\n")
    for result in results:
        label = {
            CheckStatus.PASS: "PASS",
            CheckStatus.WARN: "WARN",
            CheckStatus.FAIL: "FAIL",
        }.get(result.status, result.status.upper())
        print(f"  [{label:<4}] {result.name}: {result.message}")
        if result.fix_hint:
            print(f"         Fix: {result.fix_hint}")
        if args.show_commands and result.fix_command:
            print(f"         Command: {result.fix_command}")


def cmd_health(controller: Any, args: argparse.Namespace) -> None:
    """Show the unified privacy-preserving Network Health snapshot."""
    from app.core.network_health import build_network_health_snapshot

    if _wants_json(args):
        with _json_output_context():
            snapshot = build_network_health_snapshot()
        _print_json(snapshot)
        return

    snapshot = build_network_health_snapshot()
    overall = snapshot["overall"]
    summary = overall["summary"]
    print("[*] Network Health:")
    print(f"  Status: {overall['status'].upper()}")
    print(f"  Score:  {overall['score']}/100")
    print(
        "  Checks: "
        f"{summary['pass']} pass, {summary['warn']} warn, "
        f"{summary['fail']} fail"
    )
    network = snapshot["network"]["adapters"]
    if network.get("available"):
        print(
            "  Adapters: "
            f"{network['up_adapter_count']}/{network['adapter_count']} up"
        )
    print(
        "  Pktmon: "
        f"{'available' if snapshot['capabilities']['pktmon_available'] else 'unavailable'}"
    )
    print(f"  Recovery pending: {snapshot['recovery']['pending']}")
    if snapshot["recommendations"]:
        print("\n  Recommended next actions:")
        for item in snapshot["recommendations"]:
            print(f"    - {item}")


def cmd_pktmon(controller: Any, args: argparse.Namespace) -> None:
    """Preview or run a bounded, filter-required Pktmon capture."""
    from app.core.pktmon_capture import build_capture_plan, execute_capture
    from app.core.support_bundle import sanitize_support_value

    try:
        plan = build_capture_plan(
            port=getattr(args, "port", None),
            ip=getattr(args, "ip", None),
            protocol=getattr(args, "protocol", "udp"),
            duration_seconds=getattr(args, "duration", 15),
            output_dir=getattr(args, "output_dir", None),
        )
    except Exception as exc:
        message = sanitize_support_value(str(exc))
        if _wants_json(args):
            _print_json({
                "schema": "dupez.pktmon-command.v1",
                "ok": False,
                "error": message,
            })
        else:
            print(f"[!] Invalid Pktmon capture plan: {message}")
        return

    action = getattr(args, "pktmon_command", None) or "plan"
    if action != "capture":
        payload = plan.as_dict()
        if _wants_json(args):
            _print_json(payload)
            return
        print("[*] Pktmon capture plan (no capture started):")
        print(f"  Filter:   {plan.protocol} port {plan.port}")
        if plan.ip:
            print(f"  IP:       {plan.ip}")
        print(f"  Duration: {plan.duration_seconds}s")
        print(f"  Limit:    {payload['limits']['file_size_mb']} MB circular")
        print(f"  Output:   {payload['output']['pcapng']}")
        print(
            "  Privacy:  contains network identifiers and may contain a "
            "small packet-payload prefix"
        )
        return

    try:
        result = execute_capture(
            plan,
            apply=bool(getattr(args, "apply", False)),
            accept_sensitive_capture=bool(
                getattr(args, "accept_sensitive_capture", False)
            ),
        )
    except Exception as exc:
        message = sanitize_support_value(str(exc))
        if _wants_json(args):
            _print_json({
                "schema": "dupez.pktmon-command.v1",
                "ok": False,
                "error": message,
                "plan": plan.as_dict(),
            })
        else:
            print(f"[!] Pktmon capture did not complete: {message}")
        return

    if _wants_json(args):
        _print_json(result)
        return
    print("[+] Bounded Pktmon capture completed.")
    print(f"    PCAPNG: {result['pcapng']}")
    print(f"    ETL:    {result['etl']}")
    print("    Review the files before sharing; no upload was performed.")


def cmd_performance(controller: Any, args: argparse.Namespace) -> None:
    """Run local performance smoke checks for supportability surfaces."""
    from app.core.performance_smoke import run_performance_smoke

    if getattr(args, "performance_command", None) != "smoke":
        print("[!] Usage: performance smoke [--json] [--iterations N]")
        return
    result = run_performance_smoke(
        iterations=getattr(args, "iterations", 5),
        include_support_bundle=bool(getattr(args, "include_support_bundle", False)),
    )
    if _wants_json(args):
        _print_json(result)
        return
    print("[*] Performance smoke:")
    print(f"  Overall: {'PASS' if result['ok'] else 'REVIEW'}")
    for check in result["checks"]:
        label = "PASS" if check["ok"] else "REVIEW"
        print(
            f"  [{label:<6}] {check['name']:<22} "
            f"p95={check['p95_ms']:>8.3f} ms "
            f"budget={check['budget_ms']:>8.3f} ms"
        )


def cmd_report(controller: Any, args: argparse.Namespace) -> None:
    """Build or write a reproducible report for current active operations."""
    from app.core.scenario_report import (
        build_scenario_report,
        write_scenario_report,
    )
    from app.core.support_bundle import sanitize_support_value

    report = build_scenario_report(controller.get_active_operations())
    output_dir = getattr(args, "output_dir", None)
    path = None
    if output_dir:
        try:
            path = write_scenario_report(report, output_dir=output_dir)
        except Exception as exc:
            message = sanitize_support_value(str(exc))
            if _wants_json(args):
                _print_json({
                    "schema": "dupez.cli.scenario_report.v1",
                    "ok": False,
                    "error": message,
                })
            else:
                print(f"[!] Could not write scenario report: {message}")
            return
    payload = {
        "schema": "dupez.cli.scenario_report.v1",
        "ok": True,
        "path": sanitize_support_value(str(path)) if path else None,
        "report": report,
    }
    if _wants_json(args):
        _print_json(payload)
        return
    print("[+] Scenario report built.")
    print(f"    Report ID: {report['report_id']}")
    print(f"    Active operations: {len(report['operations'])}")
    if path:
        print(f"    Path: {payload['path']}")
    else:
        print("    No file written; use --output-dir to save it.")


def cmd_privacy(controller: Any, args: argparse.Namespace) -> None:
    """Inventory or scrub local private runtime artifacts."""
    from app.core.privacy import (
        build_retention_plan,
        enforce_retention_policy,
        scan_privacy_items,
        scrub_privacy_items,
    )

    include_accounts = bool(getattr(args, "include_account_data", False))
    if args.privacy_command == "scan":
        if _wants_json(args):
            with _json_output_context():
                items = scan_privacy_items(include_account_data=include_accounts)
        else:
            items = scan_privacy_items(include_account_data=include_accounts)
        total = sum(item.size_bytes for item in items)
        if _wants_json(args):
            _print_json({
                "schema": "dupez.cli.privacy_scan.v1",
                "include_account_data": include_accounts,
                "total_files": len(items),
                "total_bytes": total,
                "items": [_privacy_item_dict(item) for item in items],
            })
            return
        if not items:
            print("[+] No privacy-sensitive runtime artifacts found.")
            return
        print(f"[*] Privacy inventory: {len(items)} file(s), {total} bytes\n")
        for item in items:
            print(f"  {item.category:<14} {item.size_bytes:>10}  {item.rel_path}")
        print("\nRun `privacy scrub --apply` to quarantine these files.")
        return

    if args.privacy_command == "scrub":
        if _wants_json(args):
            with _json_output_context():
                result = scrub_privacy_items(
                    include_account_data=include_accounts,
                    dry_run=not args.apply,
                    quarantine=not args.delete,
                )
        else:
            result = scrub_privacy_items(
                include_account_data=include_accounts,
                dry_run=not args.apply,
                quarantine=not args.delete,
            )
        if _wants_json(args):
            _print_json({
                "schema": "dupez.cli.privacy_scrub.v1",
                "include_account_data": include_accounts,
                "dry_run": result.dry_run,
                "quarantine_dir": (
                    str(result.quarantine_dir)
                    if result.quarantine_dir is not None
                    else None
                ),
                "items": [_privacy_item_dict(item) for item in result.items],
                "removed": result.removed,
                "errors": result.errors,
                "ok": result.ok,
            })
            return
        action = "Would scrub" if result.dry_run else "Scrubbed"
        print(f"[*] {action} {len(result.items)} file(s).")
        if result.quarantine_dir is not None:
            print(f"    Quarantine: {result.quarantine_dir}")
        if result.dry_run and result.items:
            print("    Dry run only. Re-run with --apply to make changes.")
        if result.errors:
            print("\n[!] Errors:")
            for err in result.errors:
                print(f"    {err}")
        return

    if args.privacy_command == "retention":
        try:
            rules = _parse_retention_rules(getattr(args, "max_age", None))
        except ValueError as exc:
            if _wants_json(args):
                _print_json({
                    "schema": "dupez.cli.privacy_retention.v1",
                    "ok": False,
                    "error": str(exc),
                })
            else:
                print(f"[!] Invalid retention policy: {exc}")
            return

        if _wants_json(args):
            with _json_output_context():
                plan = build_retention_plan(
                    include_account_data=include_accounts,
                    rules=rules,
                )
                result = enforce_retention_policy(
                    include_account_data=include_accounts,
                    rules=rules,
                    dry_run=not args.apply,
                    quarantine=not args.delete,
                )
        else:
            plan = build_retention_plan(
                include_account_data=include_accounts,
                rules=rules,
            )
            result = enforce_retention_policy(
                include_account_data=include_accounts,
                rules=rules,
                dry_run=not args.apply,
                quarantine=not args.delete,
            )
        if _wants_json(args):
            _print_json({
                "schema": "dupez.cli.privacy_retention.v1",
                "ok": result.ok,
                "include_account_data": include_accounts,
                "dry_run": result.dry_run,
                "rules_days": plan.rules,
                "total_files": len(plan.items),
                "total_bytes": plan.total_bytes,
                "eligible_files": len(plan.eligible),
                "eligible_bytes": plan.eligible_bytes,
                "eligible": [_privacy_item_dict(item) for item in plan.eligible],
                "quarantine_dir": (
                    str(result.quarantine_dir)
                    if result.quarantine_dir is not None
                    else None
                ),
                "removed": result.removed,
                "errors": result.errors,
            })
            return
        action = "Would retire" if result.dry_run else "Retired"
        print(
            f"[*] {action} {len(plan.eligible)} of {len(plan.items)} "
            "privacy-sensitive file(s) by retention policy."
        )
        if rules:
            print("    Overrides: " + ", ".join(
                f"{category}={days}d" for category, days in sorted(rules.items())
            ))
        if result.quarantine_dir is not None:
            print(f"    Quarantine: {result.quarantine_dir}")
        if result.dry_run and plan.eligible:
            print("    Dry run only. Re-run with --apply to quarantine eligible files.")
        if result.errors:
            print("\n[!] Errors:")
            for err in result.errors:
                print(f"    {err}")
        return

    print("[!] Usage: privacy scan | privacy scrub [--apply] | privacy retention")


def cmd_recovery(controller: Any, args: argparse.Namespace) -> None:
    """Safe local recovery helpers."""
    if args.recovery_command == "secret-store-status":
        from app.core.secret_store import check_store_health

        health = check_store_health()
        if _wants_json(args):
            _print_json({
                "schema": "dupez.cli.secret_store_status.v1",
                "secret_store": {
                    "checked": True,
                    "details": "available in text mode only",
                },
            })
            return

        fallback_path = "%LOCALAPPDATA%\\DupeZ\\secrets"
        print("[*] Secret store status:")
        print(f"    Path:      {getattr(health, 'safe_path', None) or fallback_path}")
        print(f"    Reachable: {health.reachable}")
        print(f"    Writable:  {health.writable}")
        print(f"    Healthy:   {health.healthy}")
        if health.error:
            print(f"    Error:     {getattr(health, 'safe_error', '') or health.error}")
        if not health.healthy:
            print(
                f"    Fix:       {getattr(health, 'remediation_hint', '')}"
            )
        return

    if args.recovery_command == "secret-store-repair-plan":
        if _wants_json(args):
            _print_json({
                "schema": "dupez.cli.secret_store_repair_plan.v1",
                "available": True,
                "details": "available in text mode only",
            })
            return
        print("[*] Secret-store ACL repair plan:")
        print("    Run diagnostics locally for repair details.")
        return

    if args.recovery_command == "audit-status":
        if _wants_json(args):
            from app.logs.audit import get_audit_logger

            with _json_output_context():
                audit = get_audit_logger()
                valid, count, message = audit.verify_chain()
            _print_json({
                "schema": "dupez.cli.audit_status.v1",
                "audit": {
                    "sealed": audit.is_sealed(),
                    "degraded": audit.degraded,
                    "valid": valid,
                    "entries": count,
                    "message": message,
                },
            })
            return

        from app.logs.audit import get_audit_logger

        audit = get_audit_logger()
        valid, count, message = audit.verify_chain()
        print("[*] Audit status:")
        print(f"    Sealed:   {audit.is_sealed()}")
        print(f"    Degraded: {audit.degraded}")
        print(f"    Valid:    {valid}")
        print(f"    Entries:  {count}")
        print(f"    Message:  {message}")
        return

    if args.recovery_command == "reset-audit":
        from app.logs.audit import get_audit_logger

        audit = get_audit_logger()
        if not args.apply:
            print("[!] Dry run only. Re-run with --apply after investigating the audit files.")
            print("    This will quarantine audit*.jsonl files and clear audit.TAMPERED.")
            return
        quarantine = audit.reset_after_tamper()
        print("[+] Audit chain reset.")
        print(f"    Quarantine: {quarantine}")
        return

    print(
        "[!] Usage: recovery audit-status | recovery secret-store-status | "
        "recovery secret-store-repair-plan | recovery reset-audit --apply"
    )


def cmd_support(controller: Any, args: argparse.Namespace) -> None:
    """Generate redacted support artifacts."""
    if args.support_command != "bundle":
        print("[!] Usage: support bundle [--json] [--output-dir DIR]")
        return

    from app.core.support_bundle import sanitize_support_value, write_support_bundle

    include_accounts = bool(getattr(args, "include_account_data", False))
    include_file_list = bool(getattr(args, "include_file_list", False))
    if _wants_json(args):
        try:
            with _json_output_context():
                result = write_support_bundle(
                    output_dir=getattr(args, "output_dir", None),
                    include_account_data=include_accounts,
                    include_file_list=include_file_list,
                )
        except Exception as exc:
            _print_json({
                "schema": "dupez.cli.support_bundle.v1",
                "ok": False,
                "error": sanitize_support_value(str(exc)),
                "path": None,
            })
            return
        _print_json({
            "schema": "dupez.cli.support_bundle.v1",
            "ok": True,
            "path": str(result.path) if result.path else None,
            "payload": result.payload,
        })
        return

    try:
        result = write_support_bundle(
            output_dir=getattr(args, "output_dir", None),
            include_account_data=include_accounts,
            include_file_list=include_file_list,
        )
    except Exception as exc:
        print("[!] Failed to write support bundle.")
        print(f"    Error: {sanitize_support_value(str(exc))}")
        return
    print("[+] Redacted support bundle written.")
    print(f"    Path: {result.path}")
    print("    Contents: diagnostics, secret-store health, privacy inventory metadata")
    if include_accounts:
        print("    Account data: metadata only; raw account contents are not included")
    if include_file_list:
        print("    File list: included")


def cmd_safety(controller: Any, args: argparse.Namespace) -> None:
    """Inspect or record the local authorized-use acknowledgement."""
    from app.core.operator_acknowledgement import (
        ACKNOWLEDGEMENT_TEXT,
        acknowledgement_status,
        clear_acknowledgement,
        record_acknowledgement,
    )

    action = getattr(args, "safety_command", None) or "status"
    if action == "acknowledge":
        if not bool(getattr(args, "owned_authorized_network", False)):
            print("[!] Explicit confirmation is required.")
            print(
                "    Re-run with --owned-authorized-network after reviewing:"
            )
            print(f"    {ACKNOWLEDGEMENT_TEXT}")
            return
        record_acknowledgement()
        print("[+] Authorized-use policy acknowledged for this user.")
        return
    if action == "reset":
        if not bool(getattr(args, "apply", False)):
            print("[*] Preview only. Add --apply to clear acknowledgement.")
            return
        clear_acknowledgement()
        print("[+] Acknowledgement cleared; the policy will be shown again.")
        return

    status = acknowledgement_status()
    if _wants_json(args):
        _print_json(status)
        return
    print("[*] Authorized-use policy:")
    print(f"  Policy version: {status['policy_version']}")
    print(f"  Acknowledged:   {status['acknowledged']}")
    if status["acknowledged_at"] is not None:
        print(f"  Recorded at:    {status['acknowledged_at']} (Unix time)")


def cmd_storage(controller: Any, args: argparse.Namespace) -> None:
    """Show runtime storage roots and migration status."""
    from app.core.storage_status import build_storage_status
    from app.core.support_bundle import sanitize_support_value

    if _wants_json(args):
        with _json_output_context():
            status = build_storage_status()
        _print_json(sanitize_support_value(status))
        return

    status = sanitize_support_value(build_storage_status())
    runtime = status["runtime"]
    roots = status["roots"]
    migration = status["migration"]
    print("[*] Storage status:")
    print(f"  Installed runtime: {runtime['installed']}")
    print(f"  Legacy root:       {runtime['legacy_runtime_root']}")
    print("\n  Managed roots:")
    for name in (
        "data",
        "config",
        "captures",
        "reports",
        "backups",
        "logs",
        "crashes",
    ):
        root = roots[name]
        state = "present" if root["exists"] else "missing"
        print(f"    {name:<8} {state:<7} {root['path']}")
    print("\n  Migration markers:")
    for name, marker in migration["markers"].items():
        state = "ok" if marker["ok"] else "missing" if not marker["exists"] else "review"
        print(
            f"    {name:<8} {state:<7} "
            f"copied={marker['copied']} conflicts={marker['conflicts']} "
            f"errors={marker['errors']}"
        )
    if status["recommendations"]:
        print("\n  Recommended next actions:")
        for item in status["recommendations"]:
            print(f"    - {item}")


def cmd_interactive(controller: Any, args: argparse.Namespace) -> None:
    """Interactive REPL mode."""
    _print_banner()
    print("Type 'help' for commands, 'exit' to quit.\n")

    while True:
        try:
            raw = input("dupez> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[*] Bye.")
            break

        if not raw:
            continue
        if raw in ("exit", "quit", "q"):
            break
        if raw == "help":
            print("  scan [--full]              Scan network")
            print("  devices                    List known devices")
            print("  disrupt <ip> [methods]     Start disruption")
            print("  stop <ip> | stop --all     Stop disruption")
            print("  status                     Engine status")
            print("  plugins                    List plugins")
            print("  exit                       Quit")
            continue

        parts = raw.split()
        subcmd = parts[0]

        if subcmd == "scan":
            cmd_scan(controller, argparse.Namespace(full="--full" in parts))
        elif subcmd == "devices":
            cmd_devices(controller, argparse.Namespace())
        elif subcmd == "disrupt" and len(parts) >= 2:
            methods = parts[2] if len(parts) > 2 else None
            cmd_disrupt(controller, argparse.Namespace(ip=parts[1], methods=methods, params=None))
        elif subcmd == "stop":
            if "--all" in parts:
                cmd_stop(controller, argparse.Namespace(all=True, ip=None))
            elif len(parts) >= 2:
                cmd_stop(controller, argparse.Namespace(all=False, ip=parts[1]))
            else:
                print("[!] Usage: stop <ip> or stop --all")
        elif subcmd == "status":
            cmd_status(controller, argparse.Namespace())
        elif subcmd == "plugins":
            cmd_plugins(controller, argparse.Namespace())
        else:
            print(f"[!] Unknown command: {subcmd}. Type 'help' for commands.")


# ── CLI entry point ───────────────────────────────────────────────────

_CMD_MAP = {
    "scan": cmd_scan, "disrupt": cmd_disrupt, "stop": cmd_stop,
    "status": cmd_status, "devices": cmd_devices, "plugins": cmd_plugins,
    "diagnostics": cmd_diagnostics, "health": cmd_health,
    "performance": cmd_performance,
    "pktmon": cmd_pktmon, "privacy": cmd_privacy, "report": cmd_report,
    "recovery": cmd_recovery, "storage": cmd_storage, "support": cmd_support,
    "safety": cmd_safety,
    "interactive": cmd_interactive, "shell": cmd_interactive,
    "repl": cmd_interactive,
}

_NO_ADMIN_COMMANDS = {
    "diagnostics", "health", "performance", "pktmon", "privacy", "recovery", "safety",
    "storage", "support",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dupez-cli",
        description="DupeZ CLI — headless network disruption tool",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_scan = subparsers.add_parser("scan", help="Scan network for devices")
    p_scan.add_argument("--full", action="store_true", help="Full scan (slower)")

    p_disrupt = subparsers.add_parser("disrupt", help="Start disruption on target")
    p_disrupt.add_argument("ip", help="Target IP address")
    p_disrupt.add_argument("--methods", help="Comma-separated: drop,lag,throttle,...")
    p_disrupt.add_argument("--params", help="JSON params string")
    p_disrupt.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and audit the operation without initializing the packet engine",
    )
    p_disrupt.add_argument(
        "--max-duration",
        type=float,
        help="Auto-stop deadline in seconds (capped by the configured safety maximum)",
    )

    p_stop = subparsers.add_parser("stop", help="Stop disruption")
    p_stop.add_argument("ip", nargs="?", help="Target IP address")
    p_stop.add_argument("--all", action="store_true", help="Stop all disruptions")

    p_status = subparsers.add_parser("status", help="Show engine status")
    p_status.add_argument(
        "--json",
        action="store_true",
        help="Include active operation deadlines in machine-readable JSON",
    )
    subparsers.add_parser("devices", help="List known devices")
    subparsers.add_parser("plugins", help="List plugins")

    p_diag = subparsers.add_parser("diagnostics", help="Run safe diagnostics")
    p_diag.add_argument("--show-commands", action="store_true",
                        help="Show suggested remediation commands")
    p_diag.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON")

    p_health = subparsers.add_parser(
        "health",
        help="Show network, safety, recovery, and diagnostic health",
    )
    p_health.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    p_performance = subparsers.add_parser(
        "performance",
        help="Run local performance smoke checks",
    )
    performance_sub = p_performance.add_subparsers(dest="performance_command")
    p_perf_smoke = performance_sub.add_parser(
        "smoke",
        help="Measure safe supportability surfaces against budgets",
    )
    p_perf_smoke.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Samples per check (default: 5)",
    )
    p_perf_smoke.add_argument(
        "--include-support-bundle",
        action="store_true",
        help="Also measure full support bundle creation",
    )
    p_perf_smoke.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    p_pktmon = subparsers.add_parser(
        "pktmon",
        help="Preview or run a bounded Windows Packet Monitor capture",
    )
    pktmon_sub = p_pktmon.add_subparsers(dest="pktmon_command")
    for action, help_text in (
        ("plan", "Preview a filter-required capture without changing state"),
        ("capture", "Run the reviewed capture plan"),
    ):
        capture_parser = pktmon_sub.add_parser(action, help=help_text)
        capture_parser.add_argument(
            "--port",
            required=True,
            type=int,
            help="Required TCP/UDP port filter",
        )
        capture_parser.add_argument(
            "--ip",
            help="Optional IP-literal filter; hostnames are refused",
        )
        capture_parser.add_argument(
            "--protocol",
            choices=["tcp", "udp"],
            default="udp",
            help="Transport protocol (default: udp)",
        )
        capture_parser.add_argument(
            "--duration",
            type=int,
            default=15,
            help="Capture duration in seconds (maximum: 30)",
        )
        capture_parser.add_argument(
            "--output-dir",
            help="Destination directory (default: local DupeZ captures)",
        )
        capture_parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON",
        )
        if action == "capture":
            capture_parser.add_argument(
                "--apply",
                action="store_true",
                help="Actually run the capture",
            )
            capture_parser.add_argument(
                "--accept-sensitive-capture",
                action="store_true",
                help="Acknowledge that capture files contain network metadata",
            )

    p_report = subparsers.add_parser(
        "report",
        help="Build reproducible privacy-preserving scenario reports",
    )
    report_sub = p_report.add_subparsers(dest="report_command")
    p_report_active = report_sub.add_parser(
        "active",
        help="Report current operations, scope, and automatic-stop state",
    )
    p_report_active.add_argument(
        "--output-dir",
        help="Write the report atomically to this directory",
    )
    p_report_active.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    p_privacy = subparsers.add_parser("privacy", help="Privacy inventory and scrub tools")
    privacy_sub = p_privacy.add_subparsers(dest="privacy_command")
    p_priv_scan = privacy_sub.add_parser("scan", help="Inventory private runtime files")
    p_priv_scan.add_argument("--include-account-data", action="store_true",
                             help="Include account tracker and profile data")
    p_priv_scan.add_argument("--json", action="store_true",
                             help="Emit machine-readable JSON")
    p_priv_scrub = privacy_sub.add_parser("scrub", help="Quarantine private runtime files")
    p_priv_scrub.add_argument("--apply", action="store_true",
                              help="Actually quarantine/delete files")
    p_priv_scrub.add_argument("--delete", action="store_true",
                              help="Delete files instead of quarantining")
    p_priv_scrub.add_argument("--include-account-data", action="store_true",
                              help="Also scrub account tracker and profile data")
    p_priv_scrub.add_argument("--json", action="store_true",
                              help="Emit machine-readable JSON")
    p_priv_retention = privacy_sub.add_parser(
        "retention",
        help="Dry-run or apply age-based cleanup for local runtime artifacts",
    )
    p_priv_retention.add_argument("--apply", action="store_true",
                                  help="Actually quarantine/delete eligible files")
    p_priv_retention.add_argument("--delete", action="store_true",
                                  help="Delete eligible files instead of quarantining")
    p_priv_retention.add_argument("--include-account-data", action="store_true",
                                  help="Also include account tracker/profile metadata")
    p_priv_retention.add_argument(
        "--max-age",
        action="append",
        metavar="CATEGORY=DAYS",
        help=(
            "Override a retention window, e.g. packet-capture=3. "
            "May be repeated."
        ),
    )
    p_priv_retention.add_argument("--json", action="store_true",
                                  help="Emit machine-readable JSON")

    p_recovery = subparsers.add_parser("recovery", help="Safe local recovery tools")
    recovery_sub = p_recovery.add_subparsers(dest="recovery_command")
    p_audit_status = recovery_sub.add_parser("audit-status", help="Show audit chain state")
    p_audit_status.add_argument("--json", action="store_true",
                                help="Emit machine-readable JSON")
    p_secret_status = recovery_sub.add_parser(
        "secret-store-status",
        help="Show secret-store access state",
    )
    p_secret_status.add_argument("--json", action="store_true",
                                 help="Emit machine-readable JSON")
    p_secret_repair = recovery_sub.add_parser(
        "secret-store-repair-plan",
        help="Show review-only ACL recovery steps without executing them",
    )
    p_secret_repair.add_argument("--json", action="store_true",
                                 help="Emit machine-readable JSON")
    p_reset_audit = recovery_sub.add_parser("reset-audit", help="Quarantine and reset sealed audit chain")
    p_reset_audit.add_argument("--apply", action="store_true",
                               help="Actually reset the audit chain")

    p_support = subparsers.add_parser("support", help="Redacted support artifacts")
    support_sub = p_support.add_subparsers(dest="support_command")
    p_support_bundle = support_sub.add_parser("bundle", help="Write a redacted support bundle")
    p_support_bundle.add_argument("--output-dir", help="Directory for the support bundle JSON")
    p_support_bundle.add_argument("--include-account-data", action="store_true",
                                  help="Include account tracker file metadata only")
    p_support_bundle.add_argument("--include-file-list", action="store_true",
                                  help="Include privacy inventory filenames")
    p_support_bundle.add_argument("--json", action="store_true",
                                  help="Emit machine-readable JSON")

    p_safety = subparsers.add_parser(
        "safety",
        help="Authorized-use acknowledgement status and controls",
    )
    safety_sub = p_safety.add_subparsers(dest="safety_command")
    p_safety_status = safety_sub.add_parser(
        "status",
        help="Show authorized-use acknowledgement status",
    )
    p_safety_status.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    p_safety_ack = safety_sub.add_parser(
        "acknowledge",
        help="Acknowledge owned or explicitly authorized network use",
    )
    p_safety_ack.add_argument(
        "--owned-authorized-network",
        action="store_true",
        help="Confirm use is limited to owned or explicitly authorized scope",
    )
    p_safety_reset = safety_sub.add_parser(
        "reset",
        help="Clear acknowledgement so the policy is shown again",
    )
    p_safety_reset.add_argument(
        "--apply",
        action="store_true",
        help="Actually clear the acknowledgement",
    )

    p_storage = subparsers.add_parser(
        "storage",
        help="Show runtime storage roots and migration status",
    )
    storage_sub = p_storage.add_subparsers(dest="storage_command")
    p_storage_status = storage_sub.add_parser(
        "status",
        help="Show storage root and migration marker status",
    )
    p_storage_status.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )

    subparsers.add_parser("interactive", aliases=["shell", "repl"],
                          help="Interactive REPL mode")

    args = parser.parse_args()
    command = args.command or "interactive"

    active_dry_run = (
        command == "disrupt"
        and bool(getattr(args, "dry_run", False))
    )
    if command not in _NO_ADMIN_COMMANDS and not active_dry_run and not is_admin():
        print("[!] DupeZ requires administrator privileges.")
        print("    Run as Administrator or use: runas /user:Administrator dupez-cli")
        sys.exit(1)

    if not (command in _NO_ADMIN_COMMANDS and _wants_json(args)):
        _print_banner()
    if command in _NO_ADMIN_COMMANDS:
        _CMD_MAP[command](None, args)
        return

    print(
        "[*] Initializing safety dry-run..."
        if active_dry_run
        else "[*] Initializing engine (headless)..."
    )
    from app.core.controller import AppController
    if active_dry_run:
        from app.core.safety_policy import SafetyPolicy
        from app.core.state import AppState

        state = AppState()
        policy = SafetyPolicy.from_settings(
            state.settings,
            dry_run_override=True,
        )
        controller = AppController(state=state, safety_policy=policy)
    else:
        controller = AppController()

    log_startup()
    log_info("DupeZ CLI mode started")

    try:
        _CMD_MAP.get(command, cmd_interactive)(controller, args)
    finally:
        controller.shutdown()
        log_shutdown()


if __name__ == "__main__":
    main()
