#!/usr/bin/env python
"""
sbom.py — generate a CycloneDX SBOM from requirements-locked.txt.

The output is a CycloneDX 1.5 JSON document suitable for publishing
alongside each release. It lists every pinned runtime dependency with
its PyPI ``purl``, SHA-256 hashes, and license metadata where
available on disk.

Usage::

    python scripts/sbom.py                       # → dist/DupeZ.sbom.json
    python scripts/sbom.py --out custom.json     # override output
    python scripts/sbom.py --product-version 5.8.0

Design notes
------------
1. We parse ``requirements-locked.txt`` directly rather than
   introspecting the installed environment, because the SBOM must
   match the EXACT set of wheels pip will install on the build host,
   not whatever happens to be on the signer's machine.
2. Hashes in the lock file are SHA-256 of the wheel/sdist files. For
   Python packaging these are the canonical integrity anchors.
3. Component ``purl`` follows ``pkg:pypi/<name>@<version>`` per the
   purl spec.
4. The tool metadata names DupeZ itself as the application component
   so downstream SCA / VEX tooling can trace findings back to the
   release.

This is a build-time tool. It does NOT import any app module, so it
can be run in an environment that lacks PyQt6 / WinDivert / etc. —
useful in CI where only the dependency lock is available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

# Matches: ``name==version \`` followed by one-or-more ``--hash=sha256:HEX`` lines.
_PKG_LINE_RE = re.compile(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-]+)\s*\\?\s*$")
_HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})")


def parse_lock(path: Path) -> List[Tuple[str, str, List[str]]]:
    """Parse a pip-compile-style lock file into (name, version, hashes)."""
    packages: List[Tuple[str, str, List[str]]] = []
    if not path.is_file():
        raise FileNotFoundError(f"lock file not found: {path}")

    current: Tuple[str, str, List[str]] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if current:
                packages.append(current)
                current = None
            continue
        m = _PKG_LINE_RE.match(line)
        if m:
            if current:
                packages.append(current)
            current = (m.group(1).lower(), m.group(2), [])
            continue
        hm = _HASH_RE.search(line)
        if hm and current:
            current[2].append(hm.group(1))
    if current:
        packages.append(current)
    return packages


def purl_for(name: str, version: str) -> str:
    """Return the PackageURL for a PyPI distribution."""
    return f"pkg:pypi/{name}@{version}"


def build_sbom(
    packages: List[Tuple[str, str, List[str]]],
    *,
    product_version: str,
    product_name: str = "DupeZ",
    tool_name: str = "scripts/sbom.py",
) -> Dict:
    """Assemble a CycloneDX 1.5 JSON document."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    serial = "urn:uuid:" + hashlib.sha256(
        f"{product_name}@{product_version}@{now}".encode()
    ).hexdigest()[:32]

    components = []
    for name, version, hashes in packages:
        comp = {
            "type": "library",
            "bom-ref": f"pkg:pypi/{name}@{version}",
            "name": name,
            "version": version,
            "purl": purl_for(name, version),
            "scope": "required",
            "externalReferences": [
                {
                    "type": "distribution",
                    "url": f"https://pypi.org/project/{name}/{version}/",
                }
            ],
        }
        if hashes:
            comp["hashes"] = [
                {"alg": "SHA-256", "content": h} for h in hashes
            ]
        components.append(comp)

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": serial,
        "version": 1,
        "metadata": {
            "timestamp": now,
            "tools": [
                {"name": tool_name, "version": "1.0"}
            ],
            "component": {
                "type": "application",
                "bom-ref": f"pkg:app/{product_name}@{product_version}",
                "name": product_name,
                "version": product_version,
                "purl": f"pkg:app/{product_name}@{product_version}",
            },
        },
        "components": components,
    }
    return sbom


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lock", type=Path,
                    default=_ROOT / "requirements-locked.txt")
    ap.add_argument("--out", type=Path,
                    default=_ROOT / "dist" / "DupeZ.sbom.json")
    ap.add_argument("--product-version", default="0.0.0-dev")
    args = ap.parse_args()

    packages = parse_lock(args.lock)
    if not packages:
        print(f"No packages parsed from {args.lock}", file=sys.stderr)
        return 1

    sbom = build_sbom(packages, product_version=args.product_version)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(sbom, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote CycloneDX SBOM: {args.out}")
    print(f"  packages: {len(packages)}")
    print(f"  product:  {sbom['metadata']['component']['name']} "
          f"v{sbom['metadata']['component']['version']}")
    print(f"  serial:   {sbom['serialNumber']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
