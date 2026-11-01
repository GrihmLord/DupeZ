"""Run bounded local maintenance checks, without issuing release approval.

Run GPU under the ordinary desktop token and Compat from a PowerShell session
opened through normal Windows UAC. This script never elevates itself, starts
the dashboard, or exercises network interception. Its result is a local
observation, not signed release or complete lifecycle evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import psutil


def _load_validator():
    path = Path(__file__).with_name("validate_frozen_runtime.py")
    spec = importlib.util.spec_from_file_location("_maintenance_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Maintenance validation helpers are unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()
CHECKS = ("runtime-imports", "native-tls")


def _check_token(variant: str, is_admin: bool) -> None:
    if variant not in {"GPU", "Compat"}:
        raise ValueError("Unknown frozen variant")
    if is_admin != (variant == "Compat"):
        raise RuntimeError("GPU requires a standard token; Compat requires normal UAC elevation")


def _read_report(path: Path, check: str) -> tuple[dict, str]:
    metadata = validator._assert_regular_non_reparse_file(path, require_single_link=True)
    if metadata.st_size > 4096:
        raise RuntimeError("Maintenance report exceeds its bounded schema")
    with path.open("rb") as stream:
        payload = stream.read(4097)
    if len(payload) > 4096:
        raise RuntimeError("Maintenance report grew during inspection")
    report = json.loads(payload)
    expected = {"check": check, "ok": True}
    if check == "native-tls":
        expected.update(backend="schannel", available_backends=["schannel"], supports_ssl=True)
    if (not isinstance(report, dict) or report != expected or report.get("ok") is not True
            or (check == "native-tls" and report.get("supports_ssl") is not True)):
        raise RuntimeError("Maintenance report did not match the required successful check")
    return report, hashlib.sha256(payload).hexdigest()


def _alive_owned(identities: set[tuple[int, float]]) -> list[psutil.Process]:
    """Never select a reused or inaccessible PID for cleanup."""
    result = []
    for pid, created in identities:
        try:
            process = psutil.Process(pid)
            if process.create_time() == created and process.is_running():
                result.append(process)
        except psutil.NoSuchProcess:
            continue
    return result


def _run_check(executable: Path, root: Path, check: str, timeout: int) -> dict:
    if check not in CHECKS:
        raise ValueError("Unsupported maintenance operation")
    report_path = root / f"{check}.json"
    environment = validator._validation_environment(
        runtime_root=root, temp_root=root / "temp", profile_environment={},
    )
    environment.update(DUPEZ_USER_ROOT=str(root), DUPEZ_VERIFY_REPORT=str(report_path))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    identities: set[tuple[int, float]] = set()
    started = time.monotonic()
    process = subprocess.Popen(
        [str(executable), f"--verify-{check}"], cwd=root, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        while process.poll() is None:
            validator._remember_process_tree(process.pid, identities)
            if time.monotonic() - started >= timeout:
                raise RuntimeError("Maintenance process exceeded its time limit")
            time.sleep(0.1)
        if process.returncode != 0:
            raise RuntimeError(f"Maintenance process failed with exit code {process.returncode}")
        if _alive_owned(identities):
            raise RuntimeError("Maintenance child process remained after its parent exited")
        report, report_hash = _read_report(report_path, check)
        return {"check": check, "exit_code": process.returncode, "report": report,
                "report_sha256": report_hash,
                "observed_processes": len(identities), "observed_processes_exited": True}
    finally:
        # Only the retained Popen handle and identity-checked descendants belong
        # to this run. Never kill processes by executable name or bare PID.
        validator._terminate_popen_handle(process)
        owned = _alive_owned(identities)
        for child in reversed(owned):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        if owned:
            _gone, remaining = psutil.wait_procs(owned, timeout=5)
            if remaining:
                raise RuntimeError("Maintenance process cleanup is unconfirmed")


def run(*, executable: Path, expected_sha256: str, variant: str, output_directory: Path,
        timeout: int = 60) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Frozen maintenance validation requires Windows")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or not 1 <= timeout <= 180:
        raise ValueError("A SHA-256 and a timeout from 1 to 180 seconds are required")
    is_admin = validator._is_admin()
    _check_token(variant, is_admin)
    executable = Path(os.path.abspath(executable))
    root = Path(os.path.abspath(output_directory))
    validator._assert_non_reparse_directories(executable.parent, allow_missing=False)
    validator._assert_non_reparse_directories(root.parent, allow_missing=False)
    metadata = validator._assert_regular_non_reparse_file(executable, require_single_link=True)
    with validator._locked_release_executable(
        executable, expected_hash=expected_sha256, expected_size=metadata.st_size,
    ):
        root.mkdir()  # Exclusive: never reuse profiles or overwrite prior evidence.
        validator._harden_private_directory(root)
        (root / "temp").mkdir()
        records = [_run_check(executable, root, check, timeout) for check in CHECKS]
        evidence = {
            "schema": "dupez.local-frozen-maintenance.v1", "variant": variant,
            "artifact": {"name": executable.name, "sha256": expected_sha256, "size": metadata.st_size},
            "runner_is_admin": is_admin, "checks": records,
            "scope": "maintenance imports and local TLS backend only",
            "release_approval": False, "dashboard_tested": False, "network_tested": False,
        }
        with (root / "maintenance-observation.json").open("x", encoding="utf-8") as stream:
            json.dump(evidence, stream, indent=2, sort_keys=True)
            stream.write("\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--variant", choices=("GPU", "Compat"), required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    result = run(executable=args.executable, expected_sha256=args.sha256, variant=args.variant,
                 output_directory=args.output_directory, timeout=args.timeout)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
