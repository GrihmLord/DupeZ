#!/usr/bin/env python3
"""Verify hashes and sizes of privileged bundled binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "packaging" / "binary-provenance.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> list[str]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("schema") != "dupez.bundled-binaries.v1":
        errors.append(f"unsupported provenance schema: {data.get('schema')!r}")
    for entry in data.get("artifacts", []):
        rel_path = entry.get("path", "")
        path = ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing: {rel_path}")
            continue
        actual_size = path.stat().st_size
        if actual_size != entry.get("size"):
            errors.append(
                f"size mismatch: {rel_path}: {actual_size} != {entry.get('size')}"
            )
        actual_hash = _sha256(path)
        if actual_hash != str(entry.get("sha256", "")).lower():
            errors.append(f"sha256 mismatch: {rel_path}: {actual_hash}")
        if rel_path == "app/firewall/clumsy.exe":
            source = str(entry.get("source", ""))
            commit = str(entry.get("source_commit", ""))
            asset_hash = str(entry.get("release_asset_sha256", ""))
            if not source.startswith("https://github.com/"):
                errors.append("clumsy.exe provenance must pin a GitHub release")
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                errors.append("clumsy.exe provenance has no pinned source commit")
            if not re.fullmatch(r"[0-9a-f]{64}", asset_hash):
                errors.append(
                    "clumsy.exe provenance has no release-asset SHA-256"
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
