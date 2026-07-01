#!/usr/bin/env python3
"""Fail-closed source and artifact checks for DupeZ releases."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

try:
    from scripts.verify_bundled_binaries import verify_manifest
except ImportError:  # direct `python scripts/release_preflight.py`
    from verify_bundled_binaries import verify_manifest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

_POWERSHELL = Path(
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _match_version(rel: str, pattern: str) -> str:
    match = re.search(pattern, _read(rel), re.MULTILINE)
    if not match:
        raise ValueError(f"could not extract version from {rel}")
    return match.group(1)


def _check_signtool_policy(rel: str) -> list[str]:
    """Ensure Authenticode signing commands use modern digest/timestamp flags."""
    errors: list[str] = []
    for line_no, line in enumerate(_read(rel).splitlines(), start=1):
        lowered = line.lower()
        if " sign " not in lowered:
            continue
        if "signtool" not in lowered and "_signtool" not in lowered:
            continue
        missing = [
            flag
            for flag in ("/tr", "/td sha256", "/fd sha256")
            if flag not in lowered
        ]
        if missing:
            errors.append(
                f"weak Authenticode signing command: {rel}:{line_no} "
                f"missing {', '.join(missing)}"
            )
    return errors


def _powershell_path() -> Path:
    return _POWERSHELL


def _resolve_under(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    root = parent.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes release directory: {path}")
    return resolved


def _query_authenticode(paths: list[Path]) -> tuple[dict[str, str], str]:
    """Return ``{filename: Status}`` from Get-AuthenticodeSignature."""
    if os.name != "nt":
        return {}, "Authenticode dist checks require Windows"
    powershell = _powershell_path()
    if not powershell.is_file():
        return {}, "PowerShell not found for Authenticode dist checks"

    try:
        safe_paths = [_resolve_under(path, DIST) for path in paths]
    except ValueError as exc:
        return {}, str(exc)
    env = os.environ.copy()
    env["DUPEZ_AUTHENTICODE_PATHS"] = json.dumps(
        [str(path) for path in safe_paths]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$paths = @($env:DUPEZ_AUTHENTICODE_PATHS | ConvertFrom-Json)
$out = @()
foreach ($path in $paths) {
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $sig = Get-AuthenticodeSignature -LiteralPath $path
    $out += [pscustomobject]@{
        Name = Split-Path -Leaf $path
        Status = $sig.Status.ToString()
    }
}
$out | ConvertTo-Json -Compress
"""
    try:
        completed = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
            env=env,
        )
    except Exception as exc:
        return {}, f"Authenticode query failed: {exc}"
    if completed.returncode != 0:
        return {}, f"Authenticode query failed: {completed.stderr.strip()}"
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {}, f"Authenticode query returned invalid JSON: {exc}"
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return {}, "Authenticode query returned unexpected payload"
    statuses: dict[str, str] = {}
    for entry in payload:
        if isinstance(entry, dict):
            name = str(entry.get("Name") or "")
            status = str(entry.get("Status") or "")
            if name:
                statuses[name] = status
    return statuses, ""


def check_source(expected_version: str | None = None) -> list[str]:
    errors: list[str] = []
    versions = {
        "app/__version__.py": _match_version(
            "app/__version__.py",
            r'__version__\s*=\s*"(\d+\.\d+\.\d+)"',
        ),
        "packaging/installer.iss": _match_version(
            "packaging/installer.iss",
            r'#define MyAppVersion\s+"(\d+\.\d+\.\d+)"',
        ),
        "packaging/build_variants.bat": _match_version(
            "packaging/build_variants.bat",
            r'set "DUPEZ_VERSION=(\d+\.\d+\.\d+)"',
        ),
        "packaging/version_info.py": _match_version(
            "packaging/version_info.py",
            r"StringStruct\('FileVersion',\s+'(\d+\.\d+\.\d+)\.0'\)",
        ),
    }
    wanted = expected_version or versions["app/__version__.py"]
    for path, version in versions.items():
        if version != wanted:
            errors.append(f"version mismatch: {path}: {version} != {wanted}")

    for required in (
        "SECURITY.md",
        ".github/CODEOWNERS",
        "packaging/binary-provenance.json",
        "requirements-locked.txt",
    ):
        if not (ROOT / required).is_file():
            errors.append(f"required release-control file missing: {required}")

    if "--hash=sha256:" not in _read("requirements-locked.txt"):
        errors.append("requirements-locked.txt has no SHA-256 hashes")

    for rel in ("packaging/build_common.py", "packaging/dupez.spec"):
        if re.search(r"\bupx\s*=\s*True\b", _read(rel)):
            errors.append(
                "UPX must remain disabled for Defender-friendly releases: "
                f"{rel}"
            )

    unsafe_defender_patterns = (
        r"Add-MpPreference",
        r"Set-MpPreference",
        r"DisableRealtimeMonitoring",
        r"Exclude\s+%TEMP%",
        r"add an exception\s+for the DupeZ install folder",
    )
    scanned_text = "\n".join(
        _read(rel)
        for rel in (
            "README.md",
            "app/core/diagnostics.py",
            "app/gui/panels/help_panel.py",
            "packaging/build.bat",
            "packaging/build_variants.bat",
        )
    )
    for pattern in unsafe_defender_patterns:
        if re.search(pattern, scanned_text, re.IGNORECASE):
            errors.append(
                "unsafe Defender-exclusion guidance or policy mutation found: "
                f"{pattern}"
            )

    for rel in ("packaging/build.bat", "packaging/build_variants.bat"):
        errors.extend(_check_signtool_policy(rel))

    variant_build = _read("packaging/build_variants.bat")
    for artifact in (
        r'call :sign_file "dist\DupeZ-GPU.exe"',
        r'call :sign_file "dist\DupeZ-Compat.exe"',
        r'call :sign_file "dist\%DUPEZ_INSTALLER%"',
        r'call :sign_file "dist\DupeZ_Setup.exe"',
    ):
        if artifact not in variant_build:
            errors.append(
                "variant release artifact is not Authenticode-signed when "
                f"DUPEZ_SIGN_CERT is configured: {artifact}"
            )

    action_re = re.compile(r"uses:\s*[^@\s]+@([^\s#]+)")
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        for ref in action_re.findall(workflow.read_text(encoding="utf-8")):
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                errors.append(
                    f"mutable GitHub Action reference: {workflow.name}: {ref}"
                )

    errors.extend(verify_manifest())
    return errors


def check_dist(version: str) -> list[str]:
    errors: list[str] = []
    required = (
        "DupeZ-GPU.exe",
        "DupeZ-Compat.exe",
        f"DupeZ_v{version}_Setup.exe",
        "DupeZ_Setup.exe",
        "DupeZ_Setup.exe.manifest.json",
        "DupeZ_Setup.exe.manifest.sig",
        "DupeZ.sbom.json",
        "DupeZ.vex.json",
        "binary-provenance.json",
    )
    dist = ROOT / "dist"
    for name in required:
        path = dist / name
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"required release artifact missing/empty: dist/{name}")

    for name, key in (
        ("DupeZ.sbom.json", "components"),
        ("DupeZ.vex.json", "statements"),
    ):
        path = dist / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON in dist/{name}: {exc}")
            continue
        if not payload.get(key):
            errors.append(f"dist/{name} contains no {key}")
    signed_artifacts = [
        dist / name
        for name in (
            "DupeZ-GPU.exe",
            "DupeZ-Compat.exe",
            f"DupeZ_v{version}_Setup.exe",
            "DupeZ_Setup.exe",
        )
        if (dist / name).is_file()
    ]
    if signed_artifacts:
        statuses, error = _query_authenticode(signed_artifacts)
        if error:
            errors.append(error)
        for path in signed_artifacts:
            status = statuses.get(path.name)
            if status != "Valid":
                errors.append(
                    f"release artifact is not Authenticode-valid: "
                    f"dist/{path.name}: {status or 'missing status'}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--dist", action="store_true")
    args = parser.parse_args()

    errors = check_source(args.version)
    if args.dist:
        if not args.version:
            parser.error("--dist requires --version")
        errors.extend(check_dist(args.version))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Release preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
