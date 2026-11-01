#!/usr/bin/env python
"""
sbom.py — generate a CycloneDX SBOM from requirements-locked.txt.

The output is a CycloneDX 1.5 inventory of the pinned Python runtime
lock. It lists each locked dependency with its PyPI ``purl`` and
SHA-256 distribution hashes. It does not currently inventory native
subcomponents or emit license conclusions, so it must not be treated
as a complete licensing or legal-compliance record. Distribution
readiness is controlled separately by ``packaging/license-policy.json``.

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
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Sequence

try:
    from scripts.verify_requirements_lock import (
        LockedEntry,
        parse_release_lock_entries,
        release_target_metadata,
    )
except ImportError:  # direct ``python scripts/sbom.py`` execution
    from verify_requirements_lock import (
        LockedEntry,
        parse_release_lock_entries,
        release_target_metadata,
    )

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
RELEASE_TARGET_PROPERTY = "dupez:release-target"
PEP508_MARKER_PROPERTY = "dupez:pep508-marker"


@dataclass(frozen=True)
class ReleasePackage:
    name: str
    version: str
    hashes: tuple[str, ...]
    marker: str = ""


def normalize_package(
    package: ReleasePackage | LockedEntry | tuple[str, str, Sequence[str]],
) -> ReleasePackage:
    """Normalize parsed entries and legacy tuple callers for artifact builders."""

    if isinstance(package, ReleasePackage):
        return package
    if isinstance(package, LockedEntry):
        return ReleasePackage(
            name=package.name,
            version=package.version,
            hashes=package.hashes,
            marker=package.marker,
        )
    name, version, hashes = package
    return ReleasePackage(
        name=str(name),
        version=str(version),
        hashes=tuple(str(digest) for digest in hashes),
    )


def release_target_property_value() -> str:
    """Return the canonical serialized release-target SBOM property value."""

    return json.dumps(
        release_target_metadata(),
        sort_keys=True,
        separators=(",", ":"),
    )


def parse_lock(path: Path) -> list[ReleasePackage]:
    """Strictly parse and select packages for the canonical release target."""

    if not path.is_file():
        raise FileNotFoundError(f"lock file not found: {path}")
    return [
        normalize_package(entry)
        for entry in parse_release_lock_entries(path)
    ]


def purl_for(name: str, version: str) -> str:
    """Return the PackageURL for a PyPI distribution."""
    return f"pkg:pypi/{name}@{version}"


def build_sbom(
    packages: Iterable[
        ReleasePackage | LockedEntry | tuple[str, str, Sequence[str]]
    ],
    *,
    product_version: str,
    product_name: str = "DupeZ",
    tool_name: str = "scripts/sbom.py",
) -> Dict:
    """Assemble a CycloneDX 1.5 JSON document."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    serial_digest = hashlib.sha256(
        f"{product_name}@{product_version}@{now}".encode()
    ).hexdigest()[:32]
    serial = "urn:uuid:" + str(uuid.UUID(serial_digest))
    product_purl = f"pkg:generic/{product_name.casefold()}@{product_version}"

    components = []
    for raw_package in packages:
        package = normalize_package(raw_package)
        name = package.name
        version = package.version
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
        if package.hashes:
            comp["hashes"] = [
                {"alg": "SHA-256", "content": digest}
                for digest in package.hashes
            ]
        if package.marker:
            comp["properties"] = [{
                "name": PEP508_MARKER_PROPERTY,
                "value": package.marker,
            }]
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
                "bom-ref": product_purl,
                "name": product_name,
                "version": product_version,
                "purl": product_purl,
            },
            "properties": [{
                "name": RELEASE_TARGET_PROPERTY,
                "value": release_target_property_value(),
            }],
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
