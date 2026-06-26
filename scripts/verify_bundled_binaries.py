#!/usr/bin/env python3
"""Verify hashes and sizes of privileged bundled binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
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
