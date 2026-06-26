#!/usr/bin/env python3
"""Fail-closed source and artifact checks for DupeZ releases."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from scripts.verify_bundled_binaries import verify_manifest
except ImportError:  # direct `python scripts/release_preflight.py`
    from verify_bundled_binaries import verify_manifest

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _match_version(rel: str, pattern: str) -> str:
    match = re.search(pattern, _read(rel), re.MULTILINE)
    if not match:
        raise ValueError(f"could not extract version from {rel}")
    return match.group(1)


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
