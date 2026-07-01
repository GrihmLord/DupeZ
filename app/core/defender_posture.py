"""Passive Microsoft Defender posture and quarantine diagnostics.

This module is intentionally read-only. It queries Defender status and recent
threat detections when the local PowerShell Defender cmdlets are available,
then returns a path-free summary suitable for diagnostics and support bundles.
It never adds exclusions, disables protection, or changes policy.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


__all__ = ["DefenderPosture", "parse_defender_json", "query_defender_posture"]


@dataclass(frozen=True)
class DefenderPosture:
    available: bool
    status: str
    message: str
    antivirus_enabled: bool | None = None
    realtime_enabled: bool | None = None
    service_enabled: bool | None = None
    recent_detection_count: int = 0
    latest_threat_name: str = ""
    latest_action_success: bool | None = None
    latest_detection_time: str = ""

    @property
    def has_recent_detection(self) -> bool:
        return self.recent_detection_count > 0


def _powershell_path() -> Path:
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    return Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def parse_defender_json(payload: str) -> DefenderPosture:
    """Parse the compact JSON emitted by the PowerShell probe."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return DefenderPosture(
            available=False,
            status="unavailable",
            message=f"Defender probe returned invalid JSON: {exc}",
        )

    if not isinstance(data, dict):
        return DefenderPosture(
            available=False,
            status="unavailable",
            message="Defender probe returned an unexpected payload",
        )

    realtime = _as_bool(data.get("realTimeProtectionEnabled"))
    antivirus = _as_bool(data.get("antivirusEnabled"))
    service = _as_bool(data.get("amServiceEnabled"))
    recent_count = _as_int(data.get("recentDetectionCount"))
    latest_threat = str(data.get("latestThreatName") or "")[:120]
    latest_action = _as_bool(data.get("latestActionSuccess"))
    latest_time = str(data.get("latestDetectionTime") or "")[:80]

    if realtime is False or antivirus is False or service is False:
        status = "warn"
        message = "Microsoft Defender is present but one or more protections are disabled"
    elif recent_count:
        status = "warn"
        message = f"Microsoft Defender reported {recent_count} recent detection(s)"
    else:
        status = "pass"
        message = "Microsoft Defender reports no recent detections"

    return DefenderPosture(
        available=True,
        status=status,
        message=message,
        antivirus_enabled=antivirus,
        realtime_enabled=realtime,
        service_enabled=service,
        recent_detection_count=recent_count,
        latest_threat_name=latest_threat,
        latest_action_success=latest_action,
        latest_detection_time=latest_time,
    )


def query_defender_posture(days: int = 7) -> DefenderPosture:
    """Return a read-only Defender summary for the last *days* days."""
    if os.name != "nt":
        return DefenderPosture(
            available=False,
            status="unavailable",
            message="Microsoft Defender cmdlets are only available on Windows",
        )

    powershell = _powershell_path()
    if not powershell.is_file():
        return DefenderPosture(
            available=False,
            status="unavailable",
            message="PowerShell executable was not found",
        )

    bounded_days = min(30, max(1, int(days)))
    script = rf"""
$ErrorActionPreference = 'Stop'
$status = Get-MpComputerStatus
$since = (Get-Date).AddDays(-{bounded_days})
$detections = @(Get-MpThreatDetection |
    Where-Object {{ $_.InitialDetectionTime -ge $since }} |
    Sort-Object InitialDetectionTime -Descending)
$latest = $detections | Select-Object -First 1
[pscustomobject]@{{
    available = $true
    antivirusEnabled = $status.AntivirusEnabled
    realTimeProtectionEnabled = $status.RealTimeProtectionEnabled
    amServiceEnabled = $status.AMServiceEnabled
    recentDetectionCount = $detections.Count
    latestThreatName = if ($latest) {{ $latest.ThreatName }} else {{ "" }}
    latestActionSuccess = if ($latest) {{ $latest.ActionSuccess }} else {{ $null }}
    latestDetectionTime = if ($latest) {{ $latest.InitialDetectionTime.ToString("o") }} else {{ "" }}
}} | ConvertTo-Json -Compress
"""
    try:
        from app.core import safe_subprocess

        result = safe_subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=8,
            expect_returncode=(0,),
            intent="defender_posture_query",
        )
    except Exception as exc:
        return DefenderPosture(
            available=False,
            status="unavailable",
            message=f"Defender posture query failed: {exc}",
        )

    return parse_defender_json(result.stdout.strip())
