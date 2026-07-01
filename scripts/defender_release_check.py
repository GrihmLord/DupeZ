#!/usr/bin/env python3
"""Read-only Defender/AuthentiCode release artifact check.

This script does not add exclusions, disable protection, or alter Defender
policy. By default it reports Authenticode status and recent Defender
detections for release artifacts. With ``--scan`` it asks Defender to run a
custom scan against ``dist`` and then reports detections again.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
_POWERSHELL = Path(
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
)


def _powershell_path() -> Path:
    return _POWERSHELL


def _run_powershell(
    script: str,
    *,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    powershell = _powershell_path()
    if not powershell.is_file():
        return 127, "", "PowerShell not found"
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
        env=env,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _resolve_under(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    root = parent.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes release directory: {path}")
    return resolved


def _dist_artifacts() -> list[Path]:
    return sorted(
        path
        for path in DIST.glob("*.exe")
        if path.name.startswith("DupeZ")
    )


def check_authenticode(paths: list[Path]) -> tuple[list[dict], list[str]]:
    if os.name != "nt":
        return [], ["Authenticode checks require Windows"]
    if not paths:
        return [], ["no dist/*.exe release artifacts found"]
    try:
        safe_paths = [_resolve_under(path, DIST) for path in paths]
    except ValueError as exc:
        return [], [str(exc)]
    env = os.environ.copy()
    env["DUPEZ_AUTHENTICODE_PATHS"] = json.dumps(
        [str(path) for path in safe_paths]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$paths = @($env:DUPEZ_AUTHENTICODE_PATHS | ConvertFrom-Json)
$out = @()
foreach ($path in $paths) {
    $sig = Get-AuthenticodeSignature -LiteralPath $path
    $out += [pscustomobject]@{
        name = Split-Path -Leaf $path
        status = $sig.Status.ToString()
        signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { "" }
        thumbprint = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { "" }
    }
}
$out | ConvertTo-Json -Compress
"""
    rc, stdout, stderr = _run_powershell(script, env=env)
    if rc != 0:
        return [], [f"Authenticode query failed: {stderr.strip()}"]
    try:
        payload = json.loads(stdout or "[]")
    except json.JSONDecodeError as exc:
        return [], [f"Authenticode query returned invalid JSON: {exc}"]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return [], ["Authenticode query returned unexpected payload"]
    errors = [
        f"{entry.get('name')}: signature status {entry.get('status')}"
        for entry in payload
        if isinstance(entry, dict) and entry.get("status") != "Valid"
    ]
    return payload, errors


def run_defender_scan(path: Path) -> list[str]:
    if os.name != "nt":
        return ["Defender scan requires Windows"]
    try:
        safe_path = _resolve_under(path, ROOT)
    except ValueError as exc:
        return [str(exc)]
    env = os.environ.copy()
    env["DUPEZ_DEFENDER_SCAN_PATH"] = str(safe_path)
    script = r"""
$ErrorActionPreference = 'Stop'
Start-MpScan -ScanType CustomScan -ScanPath $env:DUPEZ_DEFENDER_SCAN_PATH
"""
    rc, _stdout, stderr = _run_powershell(script, timeout=900, env=env)
    if rc != 0:
        return [f"Defender custom scan failed: {stderr.strip()}"]
    return []


def recent_defender_detections(days: int = 7) -> tuple[list[dict], list[str]]:
    if os.name != "nt":
        return [], ["Defender detections require Windows"]
    bounded_days = min(30, max(1, int(days)))
    script = f"""
$ErrorActionPreference = 'Stop'
$since = (Get-Date).AddDays(-{bounded_days})
$detections = @(Get-MpThreatDetection |
    Where-Object {{ $_.InitialDetectionTime -ge $since }} |
    Sort-Object InitialDetectionTime -Descending)
$detections | Select-Object -First 20 ThreatName,ActionSuccess,InitialDetectionTime |
    ConvertTo-Json -Compress
"""
    rc, stdout, stderr = _run_powershell(script)
    if rc != 0:
        return [], [f"Defender detection query failed: {stderr.strip()}"]
    if not stdout.strip():
        return [], []
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return [], [f"Defender detection query returned invalid JSON: {exc}"]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return [], ["Defender detection query returned unexpected payload"]
    return [entry for entry in payload if isinstance(entry, dict)], []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true", help="run a Defender custom scan of dist")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    artifacts = _dist_artifacts()
    signatures, errors = check_authenticode(artifacts)
    if args.scan:
        errors.extend(run_defender_scan(DIST))
    detections, detection_errors = recent_defender_detections(args.days)
    errors.extend(detection_errors)
    if detections:
        errors.append(f"Defender reported {len(detections)} recent detection(s)")

    report = {
        "artifacts": [path.name for path in artifacts],
        "signatures": signatures,
        "recent_detections": detections,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print("Artifacts:", ", ".join(report["artifacts"]) or "(none)")
        for sig in signatures:
            print(f"Signature: {sig.get('name')} -> {sig.get('status')}")
        for detection in detections:
            print(f"Defender detection: {detection.get('ThreatName')}")
        for error in errors:
            print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
