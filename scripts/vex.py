#!/usr/bin/env python
"""Generate an OpenVEX-style dependency review skeleton.

This script intentionally does not claim packages are "not affected".
It creates an ``under_investigation`` statement for each pinned runtime
dependency so release reviewers have a concrete artifact to fill in or
replace with vulnerability-specific statements.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sbom import parse_lock, purl_for

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent


def build_vex(packages, *, product_version: str) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    statements = []
    for name, version, _hashes in packages:
        statements.append({
            "vulnerability": {
                "name": "dependency-review-pending",
            },
            "timestamp": now,
            "product": purl_for(name, version),
            "status": "under_investigation",
            "impact_statement": (
                "No vulnerability-specific assertion has been made for this "
                "dependency in this generated skeleton."
            ),
            "action_statement": (
                "Review current vulnerability data before release and replace "
                "this skeleton statement with affected/not_affected/fixed "
                "statements where applicable."
            ),
        })

    return {
        "@context": "https://openvex.dev/ns/v0.2.0",
        "@id": f"urn:dupez:vex:{product_version}:{now}",
        "author": "DupeZ release tooling",
        "role": "DocumentCreator",
        "timestamp": now,
        "version": 1,
        "tooling": "scripts/vex.py",
        "statements": statements,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lock", type=Path,
                    default=_ROOT / "requirements-locked.txt")
    ap.add_argument("--out", type=Path,
                    default=_ROOT / "dist" / "DupeZ.vex.json")
    ap.add_argument("--product-version", default="0.0.0-dev")
    args = ap.parse_args()

    packages = parse_lock(args.lock)
    if not packages:
        print(f"No packages parsed from {args.lock}", file=sys.stderr)
        return 1

    vex = build_vex(packages, product_version=args.product_version)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(vex, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote VEX skeleton: {args.out}")
    print(f"  packages: {len(packages)}")
    print("  status:   under_investigation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
