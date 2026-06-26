"""Deterministic, privacy-preserving network-test scenario reports."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.core.updater import CURRENT_VERSION
from app.utils.helpers import mask_ips_in_text, mask_macs_in_text

SCHEMA = "dupez.scenario-report.v1"

__all__ = [
    "SCHEMA",
    "build_scenario_report",
    "fingerprint_params",
    "write_scenario_report",
]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


def fingerprint_params(params: Dict[str, Any]) -> str:
    """Fingerprint parameters without exporting their values."""
    if not isinstance(params, dict) or not params:
        return "none"
    return hashlib.sha256(_canonical_json(params)).hexdigest()[:16]


def _normalize_operations(
    operations: Iterable[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    normalized = []
    for item in operations:
        normalized.append({
            "target": str(item.get("target") or "<masked>"),
            "methods": sorted({
                str(method)
                for method in item.get("methods", [])
                if method
            }),
            "params_fingerprint": str(
                item.get("params_fingerprint") or "none"
            ),
            "elapsed_seconds": item.get("elapsed_seconds"),
            "deadline_at": item.get("deadline_at"),
            "remaining_seconds": item.get("remaining_seconds"),
            "automatic_stop_armed": bool(
                item.get("automatic_stop_armed", False)
            ),
            "process_running": bool(item.get("process_running", False)),
        })
    return sorted(
        normalized,
        key=lambda item: (
            item["target"],
            item["methods"],
            item["params_fingerprint"],
        ),
    )


def build_scenario_report(
    operations: Iterable[Dict[str, Any]],
    *,
    observation: Optional[Dict[str, Any]] = None,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a report whose ID is stable for identical scenario content."""
    normalized = _normalize_operations(operations)
    safe_observation = {
        "latency_ms": None,
        "jitter_ms": None,
        "loss_percent": None,
        "notes": "",
    }
    if observation:
        for key in safe_observation:
            if key in observation:
                safe_observation[key] = observation[key]
    safe_observation["notes"] = mask_macs_in_text(
        mask_ips_in_text(str(safe_observation["notes"] or ""))
    )
    basis = {
        "schema": SCHEMA,
        "product_version": CURRENT_VERSION,
        "operations": normalized,
        "observation": safe_observation,
        "methodology": {
            "time_standard": "UTC",
            "metrics": ["latency_ms", "jitter_ms", "loss_percent"],
            "references": [
                "RFC 2330",
                "RFC 2679",
                "RFC 2680",
                "RFC 5481",
            ],
        },
    }
    report_id = hashlib.sha256(_canonical_json(basis)).hexdigest()
    timestamp = generated_at or datetime.now(timezone.utc)
    return {
        **basis,
        "report_id": report_id,
        "generated_at": timestamp.astimezone(timezone.utc).isoformat(),
        "privacy": {
            "raw_target_addresses_included": False,
            "parameter_values_included": False,
            "packet_payloads_included": False,
            "notes_require_operator_review": True,
        },
    }


def write_scenario_report(
    report: Dict[str, Any],
    *,
    output_dir: Path | str,
) -> Path:
    """Atomically write a scenario report without overwriting another."""
    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    report_id = str(report.get("report_id") or "")
    if len(report_id) != 64:
        raise ValueError("scenario report has an invalid report_id")
    path = root / f"scenario-report-{report_id[:12]}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("report_id") == report_id:
            return path
        raise FileExistsError("scenario report path already exists")
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return path
