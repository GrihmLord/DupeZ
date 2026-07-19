#!/usr/bin/env python3
"""Fail-closed source and artifact checks for DupeZ releases."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.update_verify import (
    SigVerifyError,
    UpdateManifest,
    verify_installer_sha256,
    verify_manifest as verify_update_manifest,
)

try:
    from scripts.verify_bundled_binaries import verify_manifest
except ImportError:  # direct `python scripts/release_preflight.py`
    from verify_bundled_binaries import verify_manifest

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


def _check_hermetic_python_policy(rel: str) -> list[str]:
    """Require release builds to run only through the repository virtualenv."""
    errors: list[str] = []
    text = _read(rel)
    required = (
        'set "DUPEZ_PYTHON=%CD%\\.venv\\Scripts\\python.exe"',
        'if not exist "%DUPEZ_PYTHON%"',
        '"%DUPEZ_PYTHON%" -m pip',
        '"%DUPEZ_PYTHON%" -m PyInstaller',
    )
    for snippet in required:
        if snippet not in text:
            errors.append(
                f"non-hermetic Python build policy in {rel}: "
                f"missing {snippet}"
            )

    import_checks = (
        "import PyInstaller",
        "import PyQt6.sip",
        "QtCore",
        "QtWidgets",
        "QtWebEngineWidgets",
    )
    prebuild_lines = [
        line
        for line in text.splitlines()
        if '"%DUPEZ_PYTHON%" -c ' in line
    ]
    combined_checks = "\n".join(prebuild_lines)
    for required_import in import_checks:
        if required_import not in combined_checks:
            errors.append(
                f"build import preflight missing in {rel}: "
                f"{required_import}"
            )

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        lowered = stripped.lower()
        if (
            not stripped
            or stripped.startswith("::")
            or lowered.startswith("rem ")
            or lowered.startswith("echo ")
        ):
            continue
        if re.match(r"(?i)^(?:python|pip)(?:\.exe)?\b", stripped):
            errors.append(
                f"ambient Python command in {rel}:{line_no}: {stripped}"
            )
        if re.search(r"(?i)\bscripts\\[^ ]+\.py\b", stripped):
            if not stripped.startswith('"%DUPEZ_PYTHON%" '):
                errors.append(
                    f"project script bypasses .venv in "
                    f"{rel}:{line_no}: {stripped}"
                )
    return errors


def _check_frozen_runtime_import_policy() -> list[str]:
    """Ensure the packaged executable proves its core Qt imports work."""
    errors: list[str] = []
    launcher = _read("dupez.py")
    for token in (
        "--verify-runtime-imports",
        "import PyQt6.sip",
        "QtCore",
        "QtWidgets",
        "QtWebEngineWidgets",
    ):
        if token not in launcher:
            errors.append(
                f"frozen runtime import verifier missing from dupez.py: {token}"
            )

    variant_build = _read("packaging/build_variants.bat")
    if (
        '"dist\\DupeZ-GPU.exe" --verify-runtime-imports'
        not in variant_build
    ):
        errors.append(
            "GPU build does not run the frozen runtime import verifier"
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


def _verify_update_sidecars(
    dist: Path,
    version: str,
    *,
    trusted_pubkeys_pem: Iterable[str] | None = None,
) -> list[str]:
    """Verify that updater sidecars authenticate the exact release installer."""
    installer = dist / "DupeZ_Setup.exe"
    manifest_path = dist / "DupeZ_Setup.exe.manifest.json"
    signature_path = dist / "DupeZ_Setup.exe.manifest.sig"
    if not all(
        path.is_file()
        for path in (installer, manifest_path, signature_path)
    ):
        return []

    try:
        manifest_bytes = manifest_path.read_bytes()
        signature_bytes = signature_path.read_bytes()
        kwargs = {}
        if trusted_pubkeys_pem is not None:
            kwargs["trusted_pubkeys_pem"] = trusted_pubkeys_pem
        manifest: UpdateManifest = verify_update_manifest(
            manifest_bytes,
            signature_bytes,
            **kwargs,
        )
    except (OSError, SigVerifyError, ValueError) as exc:
        return [f"update sidecar verification failed: {exc}"]

    errors: list[str] = []
    if manifest.version != version:
        errors.append(
            "update manifest version mismatch: "
            f"{manifest.version} != {version}"
        )
    if manifest.installer_filename != installer.name:
        errors.append(
            "update manifest installer mismatch: "
            f"{manifest.installer_filename!r} != {installer.name!r}"
        )
    try:
        verify_installer_sha256(str(installer), manifest)
    except SigVerifyError as exc:
        errors.append(f"update manifest does not match installer: {exc}")
    return errors


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
        "packaging/build.bat": _match_version(
            "packaging/build.bat",
            r'set "DUPEZ_VERSION=(\d+\.\d+\.\d+)"',
        ),
        "packaging/version_info.py": _match_version(
            "packaging/version_info.py",
            r"StringStruct\('FileVersion',\s+'(\d+\.\d+\.\d+)\.0'\)",
        ),
        "packaging/dupez.manifest": _match_version(
            "packaging/dupez.manifest",
            r'version="(\d+\.\d+\.\d+)\.0"',
        ),
        "packaging/dupez_compat.manifest": _match_version(
            "packaging/dupez_compat.manifest",
            r'version="(\d+\.\d+\.\d+)\.0"',
        ),
        "README.md": _match_version(
            "README.md",
            r"^# DupeZ v(\d+\.\d+\.\d+)$",
        ),
    }
    wanted = expected_version or versions["app/__version__.py"]
    for path, version in versions.items():
        if version != wanted:
            errors.append(f"version mismatch: {path}: {version} != {wanted}")
    for rel, marker in (
        ("CHANGELOG.md", f"## v{wanted} "),
        ("ROADMAP.md", f"## v{wanted} "),
        (f"docs/release-notes/v{wanted}.md", f"# DupeZ v{wanted}"),
    ):
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"release-version document missing: {rel}")
        elif marker not in _read(rel):
            errors.append(
                f"release-version marker missing from {rel}: {marker!r}"
            )

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
        errors.extend(_check_hermetic_python_policy(rel))

    errors.extend(_check_frozen_runtime_import_policy())

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
    errors.extend(_verify_update_sidecars(dist, version))
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
