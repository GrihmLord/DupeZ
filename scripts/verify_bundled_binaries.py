#!/usr/bin/env python3
"""Verify hashes and sizes of privileged bundled binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "packaging" / "binary-provenance.json"
RELEASE_DATA_MANIFEST = ROOT / "packaging" / "release-data.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(
    manifest_path: Path = DEFAULT_MANIFEST,
    release_data_path: Path = RELEASE_DATA_MANIFEST,
) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        release_data = json.loads(
            release_data_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read binary provenance controls: {exc}"]
    if data.get("schema") != "dupez.bundled-binaries.v1":
        errors.append(f"unsupported provenance schema: {data.get('schema')!r}")
    if release_data.get("schema") != "dupez.release-data.v1":
        errors.append(
            f"unsupported release-data schema: {release_data.get('schema')!r}"
        )
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return errors + ["binary provenance manifest contains no artifacts"]

    provenance_paths: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict):
            errors.append("binary provenance artifact must be an object")
            continue
        rel_path = entry.get("path", "")
        if not isinstance(rel_path, str):
            errors.append("binary provenance path must be a string")
            continue
        relative = PurePosixPath(rel_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in rel_path
            or relative.parent != PurePosixPath("app/firewall")
            or relative.suffix.casefold() not in {".dll", ".exe", ".sys"}
        ):
            errors.append(f"unsafe binary provenance path: {rel_path!r}")
            continue
        canonical_path = relative.as_posix().casefold()
        if canonical_path in provenance_paths:
            errors.append(f"duplicate binary provenance path: {rel_path}")
            continue
        provenance_paths.add(canonical_path)
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing: {rel_path}")
            continue
        actual_size = path.stat().st_size
        expected_size = entry.get("size")
        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size < 1
        ):
            errors.append(f"invalid provenance size: {rel_path}")
        elif actual_size != expected_size:
            errors.append(
                f"size mismatch: {rel_path}: {actual_size} != {expected_size}"
            )
        actual_hash = _sha256(path)
        expected_hash = str(entry.get("sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            errors.append(f"invalid provenance SHA-256: {rel_path}")
        elif actual_hash != expected_hash:
            errors.append(f"sha256 mismatch: {rel_path}: {actual_hash}")
        if not str(entry.get("source", "")).startswith("https://"):
            errors.append(f"binary provenance source must use HTTPS: {rel_path}")
        if not str(entry.get("version", "")).strip():
            errors.append(f"binary provenance version is missing: {rel_path}")
        if entry.get("authenticode") not in {"valid", "unsigned"}:
            errors.append(f"binary provenance signing state is invalid: {rel_path}")
        if canonical_path in {
            "app/firewall/clumsy.exe",
            "app/firewall/iup.dll",
        }:
            source = str(entry.get("source", ""))
            commit = str(entry.get("source_commit", ""))
            asset_hash = str(entry.get("release_asset_sha256", ""))
            if not source.startswith("https://github.com/"):
                errors.append(f"{rel_path} provenance must pin a GitHub release")
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                errors.append(f"{rel_path} provenance has no pinned source commit")
            if not re.fullmatch(r"[0-9a-f]{64}", asset_hash):
                errors.append(
                    f"{rel_path} provenance has no release-asset SHA-256"
                )

    release_binaries = release_data.get("binaries")
    if not isinstance(release_binaries, list) or not release_binaries:
        errors.append("release-data manifest contains no binaries")
    else:
        release_paths = {
            str(path).replace("\\", "/").casefold()
            for path in release_binaries
        }
        missing = sorted(release_paths - provenance_paths)
        extra = sorted(provenance_paths - release_paths)
        if missing:
            errors.append(
                "release binaries lack provenance: " + ", ".join(missing)
            )
        if extra:
            errors.append(
                "provenance lists non-release binaries: " + ", ".join(extra)
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    errors = verify_manifest(args.manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Bundled binary provenance verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
