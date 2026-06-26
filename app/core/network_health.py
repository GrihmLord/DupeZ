"""Unified, privacy-preserving network health snapshot."""

from __future__ import annotations

import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from app.core.diagnostics import CheckStatus, run_all_checks
from app.core.operation_journal import OperationJournal
from app.core.operator_acknowledgement import acknowledgement_status
from app.core.updater import CURRENT_VERSION
from app.utils.helpers import mask_ips_in_text, mask_macs_in_text

SCHEMA = "dupez.network-health.v1"

__all__ = ["SCHEMA", "build_network_health_snapshot"]


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        try:
            from app.core.secret_store import _redact_local_paths

            value = _redact_local_paths(value)
        except Exception:
            pass
        value = re.sub(
            r"(?i)\badapter\s+'[^'\r\n]+'",
            "adapter '<redacted>'",
            value,
        )
        return mask_macs_in_text(mask_ips_in_text(value))
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


def _pktmon_available() -> bool:
    if not sys.platform.startswith("win"):
        return False
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return (system_root / "System32" / "pktmon.exe").is_file()


def _collect_adapter_summary() -> Dict[str, Any]:
    """Collect aggregate adapter state without names, addresses, or MACs."""
    try:
        import psutil

        stats = psutil.net_if_stats()
        up = [item for item in stats.values() if item.isup]
        speeds = [
            int(item.speed)
            for item in up
            if isinstance(item.speed, (int, float)) and item.speed > 0
        ]
        counters = psutil.net_io_counters()
        return {
            "available": True,
            "adapter_count": len(stats),
            "up_adapter_count": len(up),
            "max_link_speed_mbps": max(speeds, default=None),
            "bytes_sent": int(getattr(counters, "bytes_sent", 0)),
            "bytes_received": int(getattr(counters, "bytes_recv", 0)),
            "errors_in": int(getattr(counters, "errin", 0)),
            "errors_out": int(getattr(counters, "errout", 0)),
            "drops_in": int(getattr(counters, "dropin", 0)),
            "drops_out": int(getattr(counters, "dropout", 0)),
        }
    except Exception as exc:
        return {"available": False, "error": _sanitize(str(exc))}


def _collect_route_summary() -> Dict[str, Any]:
    try:
        from app.network.wifi_probe import get_wifi_route_info

        route = get_wifi_route_info()
        return {
            "available": route.psutil_available,
            "kind": "wifi" if route.is_wifi else "wired_or_unknown",
            "local_ip": route.masked_local_ip,
            "reason": route.reason,
        }
    except Exception as exc:
        return {
            "available": False,
            "kind": "unknown",
            "local_ip": None,
            "reason": _sanitize(str(exc)),
        }


def _collect_safety_summary() -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "acknowledgement": acknowledgement_status(),
        "dry_run": None,
        "max_operation_seconds": None,
        "allowed_cidrs": [],
    }
    try:
        from app.core.safety_policy import SafetyPolicy
        from app.core.state import AppState

        policy = SafetyPolicy.from_settings(AppState().settings)
        summary.update({
            "dry_run": policy.dry_run,
            "max_operation_seconds": policy.max_operation_seconds,
            "allowed_cidrs": list(policy.allowed_cidrs),
        })
    except Exception as exc:
        summary["error"] = _sanitize(str(exc))
    return summary


def _deduplicated_recommendations(results: Iterable[Any]) -> list[str]:
    recommendations: list[str] = []
    for result in results:
        if result.status == CheckStatus.PASS or not result.fix_hint:
            continue
        candidate = str(_sanitize(result.fix_hint))
        if candidate not in recommendations:
            recommendations.append(candidate)
        if len(recommendations) >= 5:
            break
    return recommendations


def build_network_health_snapshot() -> Dict[str, Any]:
    """Build a stable health report suitable for GUI, CLI, and support use."""
    diagnostics = run_all_checks()
    counts = {
        "pass": sum(1 for item in diagnostics if item.status == CheckStatus.PASS),
        "warn": sum(1 for item in diagnostics if item.status == CheckStatus.WARN),
        "fail": sum(1 for item in diagnostics if item.status == CheckStatus.FAIL),
    }
    score = max(0, 100 - (counts["warn"] * 5) - (counts["fail"] * 20))
    overall = (
        "critical"
        if counts["fail"]
        else "attention"
        if counts["warn"]
        else "healthy"
    )
    pktmon = _pktmon_available()
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product": {
            "version": CURRENT_VERSION,
            "platform": platform.system() or sys.platform,
        },
        "overall": {
            "status": overall,
            "score": score,
            "summary": counts,
        },
        "capabilities": {
            "pktmon_available": pktmon,
            "pcapng_export_supported": pktmon,
        },
        "network": {
            "adapters": _collect_adapter_summary(),
            "default_route": _collect_route_summary(),
        },
        "safety": _collect_safety_summary(),
        "recovery": {
            "pending": OperationJournal().is_pending(),
        },
        "diagnostics": [
            {
                "name": item.name,
                "status": item.status,
                "message": item.message,
                "fix_hint": item.fix_hint,
            }
            for item in diagnostics
        ],
        "recommendations": _deduplicated_recommendations(diagnostics),
        "privacy": {
            "raw_ip_addresses_included": False,
            "mac_addresses_included": False,
            "adapter_names_included": False,
            "packet_payloads_included": False,
        },
    }
    return _sanitize(payload)
