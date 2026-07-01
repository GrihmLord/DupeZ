"""Redacted local support bundle generation.

The support bundle is deliberately JSON-only and data-light. It captures
diagnostics, privacy inventory metadata, and secret-store health without
including raw logs, account tracker contents, secrets, MAC addresses, or raw
local IPs. The artifact is safe to attach to a bug report after review.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.diagnostics import CheckStatus, run_all_checks
from app.core.privacy import build_retention_plan, scan_privacy_items
from app.core.storage_status import build_storage_status
from app.core.updater import CURRENT_VERSION
from app.utils.helpers import mask_ips_in_text, mask_macs_in_text

__all__ = [
    "SupportBundleResult",
    "build_support_bundle",
    "sanitize_support_value",
    "write_support_bundle",
]


@dataclass(frozen=True)
class SupportBundleResult:
    """Generated support bundle payload and optional destination path."""

    payload: Dict[str, Any]
    path: Optional[Path] = None


def _default_data_dir() -> Path:
    from app.core.data_persistence import _resolve_data_directory
    return Path(_resolve_data_directory())


def _redact_local_paths(text: str) -> str:
    """Redact user-specific filesystem roots from support payload strings."""
    try:
        from app.core.secret_store import _redact_local_paths as redact
        return redact(text)
    except Exception:
        return text


def _sanitize(value: Any) -> Any:
    """Recursively scrub strings before they enter the bundle."""
    if isinstance(value, str):
        value = _redact_local_paths(value)
        value = mask_ips_in_text(value)
        value = mask_macs_in_text(value)
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize(v) for v in value]
    return value


def sanitize_support_value(value: Any) -> Any:
    """Public wrapper for support-safe redaction of arbitrary values."""
    return _sanitize(value)


def _diagnostic_result_dict(result: Any) -> Dict[str, Any]:
    return _sanitize({
        "name": result.name,
        "status": result.status,
        "message": result.message,
        "fix_hint": result.fix_hint,
        "fix_command": result.fix_command,
    })


def build_support_bundle(
    *,
    include_account_data: bool = False,
    include_file_list: bool = False,
    data_dir: Path | str | None = None,
) -> Dict[str, Any]:
    """Build a redacted support bundle payload."""
    diagnostics = run_all_checks()
    privacy_items = scan_privacy_items(
        data_dir=data_dir,
        include_account_data=include_account_data,
    )
    diagnostic_summary = {
        "pass": sum(1 for item in diagnostics if item.status == CheckStatus.PASS),
        "warn": sum(1 for item in diagnostics if item.status == CheckStatus.WARN),
        "fail": sum(1 for item in diagnostics if item.status == CheckStatus.FAIL),
    }
    privacy_summary: Dict[str, int] = {}
    for item in privacy_items:
        privacy_summary[item.category] = privacy_summary.get(item.category, 0) + 1
    retention_plan = build_retention_plan(
        data_dir=data_dir,
        include_account_data=include_account_data,
    )
    retention_summary: Dict[str, int] = {}
    for item in retention_plan.eligible:
        retention_summary[item.category] = retention_summary.get(item.category, 0) + 1

    payload = {
        "schema": "dupez.support_bundle.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product": {
            "name": "DupeZ",
            "version": CURRENT_VERSION,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "platform": platform.system() or sys.platform,
        },
        "diagnostics": {
            "summary": diagnostic_summary,
            "results": [_diagnostic_result_dict(item) for item in diagnostics],
        },
        "secret_store": {
            "included": False,
            "reason": "use local diagnostics for key-store health",
        },
        "storage": _sanitize(build_storage_status()),
        "privacy_inventory": {
            "include_account_data": include_account_data,
            "include_file_list": include_file_list,
            "total_files": len(privacy_items),
            "total_bytes": sum(item.size_bytes for item in privacy_items),
            "by_category": privacy_summary,
            "omitted_items": 0 if include_file_list else len(privacy_items),
            "items": [
                {
                    "rel_path": item.rel_path,
                    "category": item.category,
                    "size_bytes": item.size_bytes,
                    "reason": item.reason,
                }
                for item in privacy_items
            ] if include_file_list else [],
        },
        "retention": {
            "rules_days": retention_plan.rules,
            "eligible_files": len(retention_plan.eligible),
            "eligible_bytes": retention_plan.eligible_bytes,
            "eligible_by_category": retention_summary,
        },
    }
    return _sanitize(payload)


def write_support_bundle(
    *,
    output_dir: Path | str | None = None,
    include_account_data: bool = False,
    include_file_list: bool = False,
    data_dir: Path | str | None = None,
) -> SupportBundleResult:
    """Write a redacted support bundle JSON file and return its path."""
    payload = build_support_bundle(
        include_account_data=include_account_data,
        include_file_list=include_file_list,
        data_dir=data_dir,
    )
    root = Path(output_dir) if output_dir is not None else _default_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"support-bundle-{stamp}.json"
    safe_payload = sanitize_support_value(payload)
    import json
    path.write_text(
        json.dumps(safe_payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return SupportBundleResult(payload=safe_payload, path=path)
