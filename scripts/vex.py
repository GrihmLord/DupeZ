#!/usr/bin/env python3
"""Generate vulnerability-specific OpenVEX from a completed review.

VEX statements describe catalogued vulnerabilities; packages are not
vulnerabilities themselves.  This generator therefore refuses the historical
``dependency-review-pending`` skeleton and binds its output to the exact lock
and vulnerability-review artifact.  A clean review is sufficient release
evidence and must not produce an empty OpenVEX document.  Actual findings yield
valid ``affected`` statements with a blocking action so they cannot be mistaken
for release approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.sbom import normalize_package, parse_lock, purl_for
except ImportError:  # direct ``python scripts/vex.py`` execution
    from sbom import normalize_package, parse_lock, purl_for

try:
    from scripts.verify_requirements_lock import release_target_metadata
except ImportError:  # direct ``python scripts/vex.py`` execution
    from verify_requirements_lock import release_target_metadata

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_REVIEW_SCHEMA = "dupez.python-vulnerability-review.v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_purls(packages) -> list[str]:
    return sorted(
        purl_for(package.name, package.version)
        for package in (normalize_package(item) for item in packages)
    )


def validate_review(review: dict, packages, *, lock_sha256: str) -> None:
    packages = [normalize_package(item) for item in packages]
    if review.get("schema") != _REVIEW_SCHEMA:
        raise ValueError("unexpected vulnerability review schema")
    if review.get("lock_sha256") != lock_sha256:
        raise ValueError("vulnerability review does not match the release lock")
    if review.get("release_target") != release_target_metadata():
        raise ValueError("vulnerability review has the wrong release target")
    dependencies = review.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("vulnerability review dependencies must be a list")
    reviewed_purls = sorted(
        str(item.get("purl") or "")
        for item in dependencies
        if isinstance(item, dict)
    )
    expected = _expected_purls(packages)
    if reviewed_purls != expected:
        raise ValueError("vulnerability review dependency set is incomplete")
    expected_markers = {
        purl_for(package.name, package.version): package.marker
        for package in packages
    }
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        purl = str(dependency.get("purl") or "")
        expected_marker = expected_markers.get(purl)
        actual_marker = dependency.get("marker")
        if expected_marker:
            if actual_marker != expected_marker:
                raise ValueError(
                    "vulnerability review dependency marker metadata is incorrect"
                )
        elif "marker" in dependency:
            raise ValueError(
                "vulnerability review has unexpected dependency marker metadata"
            )
    if review.get("dependency_count") != len(expected):
        raise ValueError("vulnerability review dependency count is incorrect")
    active = review.get("active_vulnerabilities")
    if not isinstance(active, list):
        raise ValueError("active_vulnerabilities must be a list")
    if review.get("active_vulnerability_count") != len(active):
        raise ValueError("active vulnerability count is incorrect")


def build_vex(
    packages,
    review: dict,
    *,
    product_version: str,
    lock_sha256: str,
    review_sha256: str,
) -> dict:
    packages = [normalize_package(item) for item in packages]
    validate_review(review, packages, lock_sha256=lock_sha256)
    active = review["active_vulnerabilities"]
    if not active:
        raise ValueError(
            "zero-finding review requires no OpenVEX document; omit the output"
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    product = f"pkg:generic/dupez@{product_version}"
    expected_purls = set(_expected_purls(packages))
    seen_findings: set[tuple[str, str]] = set()
    statements = []
    for finding in active:
        if not isinstance(finding, dict):
            raise ValueError("active vulnerability must be an object")
        vuln_id = str(finding.get("id") or "").strip()
        dependency = str(finding.get("dependency") or "").strip()
        if not vuln_id or not dependency:
            raise ValueError("active vulnerability lacks an id or dependency purl")
        if dependency not in expected_purls:
            raise ValueError(
                "active vulnerability dependency is absent from the release lock"
            )
        finding_key = (vuln_id, dependency)
        if finding_key in seen_findings:
            raise ValueError("active vulnerability review contains a duplicate")
        seen_findings.add(finding_key)

        vulnerability = {"name": vuln_id}
        aliases = finding.get("aliases") or []
        if not isinstance(aliases, list):
            raise ValueError("active vulnerability aliases must be a list")
        if aliases:
            vulnerability["aliases"] = sorted(
                {
                    str(item).strip()
                    for item in aliases
                    if str(item).strip()
                }
            )
        link = str(finding.get("link") or "").strip()
        if link:
            vulnerability["@id"] = link
        statements.append({
            "vulnerability": vulnerability,
            "timestamp": now,
            "products": [{
                "@id": product,
                "subcomponents": [{"@id": dependency}],
            }],
            "status": "affected",
            "action_statement": (
                "Release is blocked until this dependency is upgraded, removed, "
                "or a reviewed vulnerability-specific disposition is supplied."
            ),
            "action_statement_timestamp": now,
        })

    return {
        "@context": "https://openvex.dev/ns/v0.2.0",
        "@id": f"urn:dupez:vex:{product_version}:{now}",
        "author": "DupeZ release tooling",
        "role": "Document Creator",
        "timestamp": now,
        "version": 1,
        "tooling": "scripts/vex.py + scripts/vulnerability_review.py",
        "statements": statements,
        "x-dupez-vulnerability-review": {
            "schema": review["schema"],
            "generated_at_utc": review["generated_at_utc"],
            "source": review["source"],
            "release_target": review["release_target"],
            "lock_sha256": lock_sha256,
            "review_sha256": review_sha256,
            "dependency_count": review["dependency_count"],
            "active_vulnerability_count": review["active_vulnerability_count"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--lock",
        type=Path,
        default=_ROOT / "requirements-locked.txt",
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=_ROOT / "dist" / "DupeZ.vulnerability-review.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "dist" / "DupeZ.vex.json",
    )
    parser.add_argument("--product-version", default="0.0.0-dev")
    args = parser.parse_args(argv)

    try:
        packages = parse_lock(args.lock)
        if not packages:
            raise ValueError(f"no packages parsed from {args.lock}")
        review = json.loads(args.review.read_text(encoding="utf-8"))
        vex = build_vex(
            packages,
            review,
            product_version=args.product_version,
            lock_sha256=_sha256(args.lock),
            review_sha256=_sha256(args.review),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"VEX generation failed: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(vex, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote reviewed VEX metadata: {args.out}")
    print(f"  dependencies reviewed: {review['dependency_count']}")
    print(f"  active advisories: {review['active_vulnerability_count']}")
    print("  release status: blocked while active advisories remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
