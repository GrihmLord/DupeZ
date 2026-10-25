#!/usr/bin/env python3
"""Create and validate privacy-safe authorized hardware-smoke evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROVENANCE = ROOT / "packaging" / "binary-provenance.json"
SCHEMA = "dupez.hardware-smoketest.v1"
EXPECTED_REPOSITORY = "GrihmLord/DupeZ"
EXPECTED_WORKFLOW = "Hardware Smoketest"
EXPECTED_WORKFLOW_PATH = ".github/workflows/hardware-smoketest.yml"
EXPECTED_WORKFLOW_REF = (
    f"{EXPECTED_REPOSITORY}/{EXPECTED_WORKFLOW_PATH}@refs/heads/main"
)
ALLOWED_EVENTS = frozenset({"schedule", "workflow_dispatch"})
CANONICAL_TEST_NODES = (
    "tests/test_clumsy_full_controls_hardware.py::"
    "test_every_clumsy_control_runs_on_one_owned_private_target",
    "tests/test_clumsy_hidden_window_hardware.py::"
    "test_owned_clumsy_is_hidden_until_authenticated_diagnostic_restore",
    "tests/test_direct_clumsy_event_hardware.py::"
    "test_explicit_direct_clumsy_event_runs_and_releases_cleanly",
    "tests/test_hardware_smoketest.py::"
    "test_bundled_clumsy_gui_automation_starts_verified",
    "tests/test_hardware_smoketest.py::"
    "test_each_advertised_module_receives_hardware_traffic",
    "tests/test_hardware_smoketest.py::"
    "test_scan_then_lag_then_stop_pipeline",
    "tests/test_hardware_smoketest.py::"
    "test_vendor_resolution_resolves_known_oui",
)
CANONICAL_TEST_FILES = tuple(sorted({
    node.partition("::")[0] for node in CANONICAL_TEST_NODES
}))
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_POSITIVE_INTEGER_RE = re.compile(r"[1-9][0-9]*")
_MAX_JUNIT_BYTES = 2 * 1024 * 1024
_FORBIDDEN_KEYS = {
    "cidr",
    "ip",
    "mac",
    "target",
    "target_cidr",
    "target_ip",
    "target_mac",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_commit(value: str | None) -> str:
    commit = (value or "").strip().casefold()
    if not commit:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError("could not resolve the current git commit")
        commit = completed.stdout.strip().casefold()
    if not _COMMIT_RE.fullmatch(commit):
        raise ValueError("hardware evidence commit must be a full SHA-1")
    return commit


def _provenance_expectations(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "dupez.bundled-binaries.v1":
        raise ValueError("unexpected binary provenance schema")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("binary provenance contains no artifacts")

    expected: list[dict] = []
    seen: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ValueError("binary provenance artifact must be an object")
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            raise ValueError("binary provenance path must be a string")
        relative = PurePosixPath(raw_path)
        canonical = relative.as_posix().casefold()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in raw_path
            or relative.parent != PurePosixPath("app/firewall")
            or canonical in seen
        ):
            raise ValueError(f"unsafe or duplicate binary provenance path: {raw_path}")
        size = entry.get("size")
        sha256 = str(entry.get("sha256") or "").casefold()
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError(f"invalid binary provenance size: {raw_path}")
        if not _SHA256_RE.fullmatch(sha256):
            raise ValueError(f"invalid binary provenance SHA-256: {raw_path}")
        seen.add(canonical)
        expected.append({
            "path": relative.as_posix(),
            "size": size,
            "sha256": sha256,
        })
    return sorted(expected, key=lambda item: item["path"].casefold())


def _verified_native_artifacts(
    provenance_path: Path,
    source_root: Path,
) -> list[dict]:
    artifacts = _provenance_expectations(provenance_path)
    source_root = source_root.resolve()
    for entry in artifacts:
        source = source_root.joinpath(*PurePosixPath(entry["path"]).parts).resolve()
        if source_root not in source.parents or not source.is_file():
            raise ValueError(f"source native artifact missing: {entry['path']}")
        if source.stat().st_size != entry["size"]:
            raise ValueError(f"source native artifact size mismatch: {entry['path']}")
        if _sha256(source) != entry["sha256"]:
            raise ValueError(f"source native artifact SHA-256 mismatch: {entry['path']}")
    return artifacts


def _testcase_node_id(case: ET.Element) -> str:
    name = str(case.get("name") or "").strip()
    raw_file = str(case.get("file") or "").strip().replace("\\", "/")
    if raw_file:
        test_file = PurePosixPath(raw_file).as_posix()
    else:
        classname = str(case.get("classname") or "").strip()
        if not classname:
            raise ValueError("hardware JUnit testcase has no file/classname")
        test_file = classname.replace(".", "/") + ".py"
    if not name:
        raise ValueError("hardware JUnit testcase has no name")
    return f"{test_file}::{name}"


def _junit_result(path: Path) -> tuple[int, list[str], list[str]]:
    if not path.is_file():
        raise ValueError("hardware JUnit report is not a regular file")
    if path.stat().st_size > _MAX_JUNIT_BYTES:
        raise ValueError("hardware JUnit report exceeds the size limit")
    raw = path.read_bytes()
    if len(raw) > _MAX_JUNIT_BYTES:
        raise ValueError("hardware JUnit report exceeds the size limit")
    try:
        document = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("hardware JUnit report must be strict UTF-8") from exc
    lowered = document.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("hardware JUnit report must not contain DTDs or entities")
    try:
        # Input is capped at 2 MiB and DTD/entity declarations are rejected above.
        root = ET.fromstring(document)  # nosec B314
    except ET.ParseError as exc:
        raise ValueError("hardware JUnit report is not valid XML") from exc
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("hardware JUnit report contains no test suites")
    totals = {
        key: sum(int(suite.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if totals["tests"] < 1:
        raise ValueError("hardware JUnit report contains no tests")
    if any(totals[key] for key in ("failures", "errors", "skipped")):
        raise ValueError(
            "hardware JUnit report is not a complete pass: "
            f"failures={totals['failures']} errors={totals['errors']} "
            f"skipped={totals['skipped']}"
        )
    cases = [case for suite in suites for case in suite.findall("testcase")]
    if len(cases) != totals["tests"]:
        raise ValueError("hardware JUnit testcase count does not match totals")
    if any(
        case.find(result) is not None
        for case in cases
        for result in ("failure", "error", "skipped")
    ):
        raise ValueError("hardware JUnit contains a non-passing testcase")
    nodes = sorted(_testcase_node_id(case) for case in cases)
    if nodes != list(CANONICAL_TEST_NODES):
        raise ValueError("hardware JUnit does not contain the exact canonical suite")
    files = sorted({node.partition("::")[0] for node in nodes})
    if files != list(CANONICAL_TEST_FILES):
        raise ValueError("hardware JUnit does not contain the exact canonical files")
    return totals["tests"], files, nodes


def _invocation(commit: str) -> dict:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("hardware evidence creation requires GitHub Actions")
    invocation = {
        "kind": "github-actions",
        "repository": os.environ.get("GITHUB_REPOSITORY", "").strip(),
        "workflow": os.environ.get("GITHUB_WORKFLOW", "").strip(),
        "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF", "").strip(),
        "event_name": os.environ.get("GITHUB_EVENT_NAME", "").strip(),
        "run_id": os.environ.get("GITHUB_RUN_ID", "").strip(),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "").strip(),
        "head_sha": os.environ.get("GITHUB_SHA", "").strip().casefold(),
    }
    if invocation["repository"] != EXPECTED_REPOSITORY:
        raise ValueError("unexpected GitHub repository for hardware evidence")
    if invocation["workflow"] != EXPECTED_WORKFLOW:
        raise ValueError("unexpected GitHub workflow for hardware evidence")
    if invocation["workflow_ref"] != EXPECTED_WORKFLOW_REF:
        raise ValueError("unexpected GitHub workflow ref for hardware evidence")
    if invocation["event_name"] not in ALLOWED_EVENTS:
        raise ValueError("unexpected GitHub event for hardware evidence")
    for field in ("run_id", "run_attempt"):
        if not _POSITIVE_INTEGER_RE.fullmatch(invocation[field]):
            raise ValueError(f"invalid GitHub {field} for hardware evidence")
    if invocation["head_sha"] != commit:
        raise ValueError("hardware evidence commit does not match GITHUB_SHA")
    return invocation


def build_evidence(
    *,
    junit_path: Path,
    commit: str,
    provenance_path: Path = DEFAULT_PROVENANCE,
    source_root: Path = ROOT,
    clumsy_processes_remaining: int,
) -> dict:
    resolved_commit = _resolve_commit(commit)
    if (
        isinstance(clumsy_processes_remaining, bool)
        or not isinstance(clumsy_processes_remaining, int)
        or clumsy_processes_remaining != 0
    ):
        raise ValueError("workflow-measured Clumsy process count must be zero")
    test_count, test_files, test_nodes = _junit_result(junit_path)
    return {
        "schema": SCHEMA,
        "commit": resolved_commit,
        "generated_at_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "invocation": _invocation(resolved_commit),
        "source_native_artifacts": _verified_native_artifacts(
            provenance_path, source_root
        ),
        "tests": {
            "result": "passed",
            "count": test_count,
            "files": test_files,
            "node_ids": test_nodes,
        },
        "process_cleanup": {
            "measurement": "workflow-post-cleanup-owned-path-cim",
            "clumsy_processes_remaining": clumsy_processes_remaining,
        },
    }


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _FORBIDDEN_KEYS:
                return True
            if _contains_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def validate_evidence(
    payload: dict,
    *,
    expected_commit: str,
    provenance_path: Path = DEFAULT_PROVENANCE,
    source_root: Path = ROOT,
) -> list[str]:
    errors: list[str] = []
    try:
        commit = _resolve_commit(expected_commit)
        expected_native = _verified_native_artifacts(provenance_path, source_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    if payload.get("schema") != SCHEMA:
        errors.append("hardware evidence schema mismatch")
    if payload.get("commit") != commit:
        errors.append("hardware evidence commit mismatch")
    if not str(payload.get("generated_at_utc") or "").strip():
        errors.append("hardware evidence has no timestamp")
    invocation = payload.get("invocation")
    if not isinstance(invocation, dict) or invocation.get("kind") != "github-actions":
        errors.append("hardware evidence invocation is invalid")
    else:
        if invocation.get("repository") != EXPECTED_REPOSITORY:
            errors.append("hardware evidence repository is invalid")
        if invocation.get("workflow") != EXPECTED_WORKFLOW:
            errors.append("hardware evidence workflow is invalid")
        if invocation.get("workflow_ref") != EXPECTED_WORKFLOW_REF:
            errors.append("hardware evidence workflow ref is invalid")
        if invocation.get("event_name") not in ALLOWED_EVENTS:
            errors.append("hardware evidence event is invalid")
        for field in ("run_id", "run_attempt"):
            if not _POSITIVE_INTEGER_RE.fullmatch(
                str(invocation.get(field) or "")
            ):
                errors.append(f"hardware evidence GitHub {field} is invalid")
        if invocation.get("head_sha") != commit:
            errors.append("hardware evidence GitHub head SHA mismatch")
    tests = payload.get("tests")
    if not isinstance(tests, dict):
        errors.append("hardware evidence test result is missing")
    else:
        if tests.get("result") != "passed":
            errors.append("hardware evidence test result is not passed")
        count = tests.get("count")
        if count != len(CANONICAL_TEST_NODES):
            errors.append("hardware evidence test count is invalid")
        if tests.get("files") != list(CANONICAL_TEST_FILES):
            errors.append("hardware evidence test file list is invalid")
        if tests.get("node_ids") != list(CANONICAL_TEST_NODES):
            errors.append("hardware evidence canonical test nodes are invalid")
    cleanup = payload.get("process_cleanup")
    if (
        not isinstance(cleanup, dict)
        or cleanup.get("measurement")
        != "workflow-post-cleanup-owned-path-cim"
        or cleanup.get("clumsy_processes_remaining") != 0
    ):
        errors.append("hardware evidence does not prove Clumsy process cleanup")
    if payload.get("source_native_artifacts") != expected_native:
        errors.append("hardware evidence native hashes do not match provenance")
    if _contains_forbidden_key(payload):
        errors.append("hardware evidence contains prohibited target identifiers")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_native = subparsers.add_parser("verify-native")
    verify_native.add_argument(
        "--provenance",
        type=Path,
        default=DEFAULT_PROVENANCE,
    )
    verify_native.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
    )
    create = subparsers.add_parser("create")
    create.add_argument("--junit", type=Path, required=True)
    create.add_argument("--out", type=Path, required=True)
    create.add_argument("--commit")
    create.add_argument(
        "--clumsy-processes-remaining", type=int, required=True
    )
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, required=True)
    validate.add_argument("--commit", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "verify-native":
            artifacts = _verified_native_artifacts(
                args.provenance,
                args.source_root,
            )
            print(
                "Hardware native provenance: PASS "
                f"({len(artifacts)} artifacts)"
            )
            return 0

        if args.command == "create":
            payload = build_evidence(
                junit_path=args.junit,
                commit=_resolve_commit(args.commit),
                clumsy_processes_remaining=args.clumsy_processes_remaining,
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"Hardware evidence written: {args.out}")
            return 0

        payload = json.loads(args.evidence.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("hardware evidence must contain a JSON object")
        errors = validate_evidence(payload, expected_commit=args.commit)
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"Hardware evidence error: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Hardware evidence: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
