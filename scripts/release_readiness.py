#!/usr/bin/env python3
"""Read-only launch preparation inventory, never a publication authority.

Uses the canonical source/license preflight and artifact inventory. It does
not run binaries, inspect credentials, create evidence, or advance phases.
Exit 1 means known blockers; exit 2 means mandatory checks remain unverified.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import release_preflight as preflight

REQUIRED_CHECKS = frozenset({
    "Analyze Python", "dependency-review", "GPU and Compat frozen boundary",
    "Lockfile contract and installability", "Exact-head source release policy",
    "gitleaks", "pytest (3.12)", "pytest (3.13)",
    "Build-tool lock contract and installability", "detect-secrets", "ruff",
    "Test-tool lock contract and installability", "ast-lint", "verify-hardware-test-lock",
})
EVIDENCE_FILES = (
    "release-attestation.json", "frozen-runtime-evidence-gpu.json",
    "frozen-runtime-evidence-compat.json", "hardware-smoketest-evidence.json",
    "manual-release-validation.json", "release-validation-attestation.json",
    "SHA256SUMS.txt", "DefenderScan.txt",
)


def _check(check_id: str, state: str, detail: str, action: str) -> dict:
    return {"id": check_id, "state": state, "detail": detail, "next_action": action}


def _inventory_file(relative: str) -> dict:
    path = ROOT / relative
    try:
        # Reject linked ancestors as well as linked leaves, without traversing
        # an output directory into another user's data.
        cursor = ROOT
        for part in Path(relative).parts:
            cursor /= part
            metadata = cursor.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                return {"path": relative, "state": "unsafe-path"}
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
            return {"path": relative, "state": "missing-or-empty"}
        return {"path": relative, "state": "present-unverified", "size_bytes": metadata.st_size}
    except FileNotFoundError:
        return {"path": relative, "state": "missing-or-empty"}
    except OSError:
        return {"path": relative, "state": "unreadable"}


def _github_check(expected_commit: str) -> dict:
    action = "Restore hosted checks and require all exact-commit checks; never override failures."
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/GrihmLord/DupeZ/commits/{expected_commit}/check-runs?per_page=100"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode != 0:
            raise ValueError("GitHub query failed")
        payload = json.loads(result.stdout)
        runs = payload["check_runs"]
        if (not isinstance(runs, list) or type(payload["total_count"]) is not int
                or len(runs) != payload["total_count"] or len(runs) > 100):
            raise ValueError("Incomplete checks response")
        selected: dict[str, dict] = {}
        for run in runs:
            if run["head_sha"] != expected_commit:
                raise ValueError("Wrong commit")
            name = run["name"]
            if name in REQUIRED_CHECKS:
                if name in selected:
                    raise ValueError("Ambiguous duplicate check context")
                selected[name] = run
        missing = sorted(REQUIRED_CHECKS - selected.keys())
        failing = sorted(name for name, run in selected.items()
                         if run["status"] != "completed" or run["conclusion"] != "success")
        if missing or failing:
            return _check("hosted-checks", "blocked",
                          f"Missing: {', '.join(missing) or 'none'}; not successful: {', '.join(failing) or 'none'}.", action)
        return _check("hosted-checks", "passed", "All 14 expected contexts succeeded for the supplied commit.",
                      "Recheck the canonical main commit and live governance before release.")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return _check("hosted-checks", "not-checked", "GitHub data unavailable, incomplete or ambiguous.", action)


def collect_readiness(version: str, *, github_commit: str | None = None) -> dict:
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise ValueError("version must be major.minor.patch")
    if github_commit is not None and re.fullmatch(r"[0-9a-f]{40}", github_commit) is None:
        raise ValueError("expected commit must be a full lowercase SHA-1")
    checks = []
    try:
        errors = preflight.check_source(version)
        checks.append(_check("source-preflight", "blocked" if errors else "passed",
                             f"{len(errors)} canonical source checks failed; run preflight locally for details."
                             if errors else "Canonical source checks passed.",
                             "Fix source errors, then run the full locked test suites."))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        checks.append(_check("source-preflight", "blocked", f"Source checks could not finish ({type(exc).__name__}).",
                             "Run scripts/release_preflight.py directly for local diagnostics."))
    try:
        errors, _ = preflight._check_license_policy(distribution=True)
        checks.append(_check("owner-distribution-evidence", "blocked" if errors else "passed",
                             f"{len(errors)} owner distribution-evidence checks failed; run the license gate locally for details."
                             if errors else "Canonical owner-evidence checks passed; not a legal opinion.",
                             "Record owner-approved terms and pinned evidence in packaging/license-policy.json."))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        checks.append(_check("owner-distribution-evidence", "blocked", f"Evidence checks could not finish ({type(exc).__name__}).",
                             "Repair the owner-evidence record; do not manufacture approvals."))
    inventory = [_inventory_file(f"dist/{name}") for name in
                 (*preflight.required_distribution_artifacts(version), *EVIDENCE_FILES)]
    inventory.append(_inventory_file("LICENSE.txt"))
    unavailable = [item["path"] for item in inventory if item["state"] != "present-unverified"]
    checks.append(_check("release-input-inventory", "blocked" if unavailable else "not-checked",
                         "Unavailable: " + ", ".join(unavailable) if unavailable else
                         "Files exist but version, hashes, signatures, commit and freshness are NOT verified.",
                         "Rebuild and validate through scripts/release.ps1; do not promote old dist files."))
    checks.append(_github_check(github_commit) if github_commit else _check(
        "hosted-checks", "not-checked", "No live query requested.",
        "Rerun with --github --expected-commit FULL_SHA after reviewing the exact source commit."))
    checks.extend([
        _check("clean-main-and-governance", "not-checked",
               "This advisory does not authenticate local Git identity or repository protection.",
               "Use canonical release Git checks; require clean main, protected checks and production-release policy."),
        _check("exact-artifact-and-manual-gates", "not-checked",
               "No binaries, hardware, installers, signing keys or manual observations were exercised.",
               "Complete GPU, Compat, hardware, manual and verified-draft gates on the exact rebuilt bytes."),
        _check("publication", "not-checked", "Publication is never authorized by this report.",
               "Only the explicit admin-stage-publish phase may publish after every canonical gate passes."),
    ])
    return {
        "schema": "dupez.release-readiness.v1", "version": version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "disposition": "blocked" if any(item["state"] == "blocked" for item in checks) else "requires-gate-validation",
        "release_authorized": False, "expected_commit": github_commit,
        "checks": checks, "inventory": inventory,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="5.8.0")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON to stdout.")
    parser.add_argument("--github", action="store_true", help="Read exact-commit GitHub checks through gh; no writes.")
    parser.add_argument("--expected-commit", help="Full lowercase commit SHA for the optional live query.")
    args = parser.parse_args(argv)
    if args.github != bool(args.expected_commit):
        parser.error("--github and --expected-commit must be supplied together")
    try:
        report = collect_readiness(args.version, github_commit=args.expected_commit)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"DupeZ {report['version']}: {report['disposition'].upper()}")
        print("Read-only preparation report; not release authorization.\n")
        for check in report["checks"]:
            print(f"[{check['state']}] {check['id']}: {check['detail']}")
            print(f"  Next: {check['next_action']}")
    return 1 if report["disposition"] == "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
