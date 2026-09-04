from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_both_release_consumers_use_the_shared_v3_contract() -> None:
    contract = _read("scripts/frozen_runtime_evidence_contract.ps1")
    stage = _read("scripts/stage_release.ps1")
    recorder = _read("scripts/record_manual_release_validation.ps1")

    for consumer in (stage, recorder):
        assert '"frozen_runtime_evidence_contract.ps1"' in consumer
        assert "Assert-FrozenRuntimeEvidenceContract `" in consumer
        assert '-ExpectedExecutable "DupeZ-GPU.exe"' in consumer
        assert '-ExpectedExecutable "DupeZ-Compat.exe"' in consumer

    required_contract_tokens = (
        "dupez.frozen-runtime-validation.v3",
        "production-safety-dry-run",
        "run.network_validation_mode -cne $Evidence.network_validation_mode",
        "source_fingerprint",
        "validation_session_id",
        "generated_at_utc",
        "started_at_utc",
        "run.variant -cne $Evidence.variant",
        "run.executable -cne $Evidence.executable",
        "run.executable_sha256 -cne $Evidence.executable_sha256",
        "run.commit -cne $Evidence.commit",
        "run.source_state -cne $Evidence.source_state",
        "run.source_fingerprint -cne $Evidence.source_fingerprint",
        "run.launched_from_admin -isnot [bool]",
        "Evidence.validation_host.administrator",
        "Evidence.cycles_per_profile",
        'foreach ($profile in @("normal", "forced-low-resource"))',
        "foreach ($cycle in 1..([int64]$Evidence.cycles_per_profile))",
        "run.webengine_helper_observed -isnot [bool]",
        'process_names_observed)',
        "$runs.Count -ne $requiredRunKeys.Count",
        "$seenRunKeys.Add($runKey)",
        "$missingRunKeys.Count -ne 0",
    )
    for token in required_contract_tokens:
        assert token in contract, token


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="PowerShell evidence contract is Windows-only",
)
def test_frozen_runtime_evidence_contract_is_executable() -> None:
    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    completed = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "tests" / "ci" / "frozen_runtime_evidence_contract_test.ps1"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        shell=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
