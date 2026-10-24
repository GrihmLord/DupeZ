"""Static and parser-level policy tests for v5.8.0 release finalization."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement
from packaging.version import Version
import pytest

from scripts.release_preflight import _check_workflow_run_context_policy

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_windows_lock_driver_is_powershell_51_ascii_safe():
    script = _read("scripts/lock-requirements.ps1")

    # Windows PowerShell 5.1 decodes BOM-less UTF-8 as the active ANSI code
    # page. Smart punctuation can become quote-like bytes and corrupt parsing.
    assert script.isascii()


def test_release_gate_launcher_rejects_stale_or_dirty_state():
    script = _read("scripts/release_gate_launcher.ps1")

    for token in (
        '$stateSchema = "dupez.blocked-release-gates-progress.v3"',
        '$releaseMode = if ($AllowUnsigned) { "unsigned" } else { "authenticode" }',
        "release_mode = $releaseMode",
        "validation_policy = $validationPolicy",
        "function Get-RepositoryIdentity",
        '$requiredBranch = if ($AllowNonMainValidation -or $Phase -eq "status")',
        "branch = $identity.Branch",
        '$sequenceScriptPath = Join-Path $PSScriptRoot "blocked_release_gates_sequence.ps1"',
        '"-File", $sequenceScriptPath',
        "function Read-State",
        "the file is unchanged until a phase result is recorded.",
        '"release_git_contract.ps1"',
        "Get-ReleaseGitIdentity",
        "-AllowDirty",
        "commit = $repositoryIdentity.commit",
        "[string]$raw.schema -ne $stateSchema",
        "[string]$raw.version -ne $Version",
        "[string]$raw.commit -ne $repositoryIdentity.commit",
        "[string]$raw.release_mode -ne $releaseMode",
        "[string]$raw.validation_policy -ne $validationPolicy",
        "schema/version/commit/release-mode/validation-policy",
        "Refusing to resume release progress from a dirty working tree",
    ):
        assert token in script, token

    assert "Write-State -state $default" not in script
    assert "Read-State -NoWrite" not in script
    assert 'Write-Host "\\n' not in script
    assert "dupez.blocked-release-gates-progress.v2" not in script
    assert "dupez.blocked-release-gates-progress.v1" not in script
    assert "Get-Command \"git\"" not in script
    assert "Set-Location $repoRoot" not in script


def test_release_gate_launcher_pins_shell_and_enforces_phase_chain():
    script = _read("scripts/release_gate_launcher.ps1")

    for token in (
        "function Resolve-InboxWindowsPowerShell",
        "[Environment+SpecialFolder]::System",
        'Join-Path $systemDirectory "WindowsPowerShell\\v1.0\\powershell.exe"',
        "$inboxWindowsPowerShell = Resolve-InboxWindowsPowerShell",
        "Test-Path -LiteralPath $candidate -PathType Leaf",
        "-FilePath $inboxWindowsPowerShell `",
        "& $inboxWindowsPowerShell @seqArgs",
        "function Assert-PhasePredecessorsDone",
        "status=DONE",
        "function Invalidate-SuccessorDoneStates",
        '$state.phases[$successor] = "PENDING"',
        "New-ElevatedLauncherEncodedCommand",
        '"-EncodedCommand", $encodedCommand',
        "ConvertTo-Json -Compress",
        "Convert]::ToBase64String",
        "-Wait `",
        "-PassThru",
        "$elevatedProcess.ExitCode -ne 0",
        "$phaseExitCode = $LASTEXITCODE",
        "Publication is never automatic.",
        "the FAILED state also could not be persisted",
        "completed successfully, but its DONE state",
        "Verify external effects before",
        "Auto mode will not publish.",
    ):
        assert token in script, token

    assert script.count("$inboxWindowsPowerShell = Resolve-InboxWindowsPowerShell") == 1
    assert 'Start-Process -FilePath "powershell"' not in script
    assert "& powershell @seqArgs" not in script
    assert '($argList -join " ")' not in script
    assert "('\"' + $Operator + '\"')" not in script
    assert 'return "RELAUNCHED_ELEVATED"' not in script
    assert 'return "DONE"' not in script
    assert "$result = Invoke-Phase" not in script
    assert "exit 0" not in script
    assert '[string]$Phase = "status"' in script

    invoke = script.index("function Invoke-Phase")
    invoke_body = script[invoke : script.index("$state = Read-State", invoke)]
    predecessor = invoke_body.index("Assert-PhasePredecessorsDone")
    elevation = invoke_body.index("if ($needsAdmin -and -not $isAdmin)")
    invalidation = invoke_body.index("Invalidate-SuccessorDoneStates")
    nested_launch = invoke_body.index("& $inboxWindowsPowerShell @seqArgs")
    assert predecessor < elevation < invalidation < nested_launch

    auto = script.index('if ($Phase -eq "auto")')
    explicit_publish = script.index(
        '$selected -eq "admin-stage-publish"', auto
    )
    phase_invoke = script.index(
        "Invoke-Phase -phaseName $selected", explicit_publish
    )
    assert auto < explicit_publish < phase_invoke


def test_release_gate_launcher_operator_is_bounded_to_safe_characters():
    script = _read("scripts/release_gate_launcher.ps1")
    operator_param = script[script.index("[ValidateLength(0, 80)]") : script.index("[switch]$AllowUnsigned")]

    assert ("[ValidatePattern('^$|^[\\p{L}\\p{M}\\p{N}]" "[\\p{L}\\p{M}\\p{N} ._-]{0,79}$')]") in operator_param
    assert "ValidateLength(0, 80)" in operator_param


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell and file-sharing contract")
def test_release_progress_io_contract(tmp_path):
    script = _read("scripts/release_gate_launcher.ps1")
    assert "Set-Content -LiteralPath $statePath" not in script
    assert "$stream.Flush($true)" in script
    assert "[IO.File]::Replace($temporaryPath, $statePath" in script
    assert script.count("$progressLock = Enter-ReleaseProgressLock") == 2
    assert script.count("$progressLock.Dispose()") == 2
    assert 'phase = $(if ($Phase -eq "auto") { "auto" }' in script
    powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    completed = subprocess.run(
        [
            str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(ROOT / "tests/ci/release_progress_io_contract_test.ps1"),
            "-FixtureRoot", str(tmp_path),
        ],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Release progress I/O contracts passed." in completed.stdout


def test_blocked_gate_sequencer_propagates_nested_phase_failures():
    script = _read("scripts/blocked_release_gates_sequence.ps1")
    run_checked = script.index("function Run-Checked")
    switch = script.index("switch ($Phase)", run_checked)
    body = script[run_checked:switch]

    action_index = body.index("& $Action")
    capture_index = body.index("$phaseExitCode = $LASTEXITCODE")
    reject_index = body.index("$phaseExitCode -ne 0")
    throw_index = body.index("failed with exit code $phaseExitCode")

    assert action_index < capture_index < reject_index < throw_index
    assert "function Resolve-InboxWindowsPowerShell" in script
    assert "$inboxWindowsPowerShell = Resolve-InboxWindowsPowerShell" in script
    assert "& $inboxWindowsPowerShell" in script
    assert "{ powershell @args }" not in script
    assert "            powershell " not in script


def test_installer_uses_restart_manager_without_force_kill_hook():
    installer = _read("packaging/installer.iss")
    lowered = installer.lower()

    assert '#define MyAppVersion   "5.8.0"' in installer
    assert "CloseApplications=yes" in installer
    assert "CloseApplicationsFilter=dupez.exe,DupeZ-GPU.exe,DupeZ-Compat.exe" in installer
    assert "RestartApplications=no" in installer
    assert "[code]" not in lowered
    assert "preparetoinstall" not in lowered
    assert "taskkill.exe" not in lowered
    assert "'/im'" not in lowered and '"/im"' not in lowered
    assert "dupez_helper.exe" not in lowered


def test_installer_x64_driver_is_restricted_to_x64_windows():
    installer = _read("packaging/installer.iss")
    driver_sources = [
        line for line in installer.splitlines() if line.startswith("Source:") and ".sys" in line.casefold()
    ]
    architecture = {
        key: value
        for line in installer.splitlines()
        if line.startswith("Architectures")
        for key, _, value in (line.partition("="),)
    }

    assert len(driver_sources) == 1
    assert "WinDivert64.sys" in driver_sources[0]
    assert architecture == {
        "ArchitecturesInstallIn64BitMode": "x64os",
        "ArchitecturesAllowed": "x64os",
    }
    assert "RedirectionGuard=yes" in installer
    assert "x64compatible" not in installer


def test_release_finalizer_requires_real_signing_and_security_gates():
    script = _read("scripts/finalize_release.ps1")

    required = (
        "DUPEZ_SIGN_CERT",
        "DUPEZ_SIGN_PRIVKEY",
        "DUPEZ_SIGNTOOL",
        "Windows SDK SignTool",
        "packaging\\release-tools.json",
        "Read-ReleaseToolPins",
        "Resolve-PinnedReleaseTool",
        "Inno Setup ISCC.exe",
        "Get-AuthenticodeSignature",
        "TimeStamperCertificate",
        "verify /pa /all /tw /q",
        "Get-MpComputerStatus",
        "Update-MpSignature",
        "-DisableRemediation",
        "-ReturnHR",
        "scripts\\release_preflight.py",
        ".release-venv\\Scripts\\python.exe",
        "--dist",
        "SHA256SUMS.txt",
        "release-attestation.json",
        "5555f0e8c31a40ed",  # pragma: allowlist secret
    )
    for token in required:
        assert token in script, token

    assert "Add-MpPreference" not in script
    assert "Set-MpPreference" not in script
    assert "DisableRealtimeMonitoring" not in script
    assert "--gen-key" not in script
    assert "$signableNames = @(" in script
    assert "$signableArtifacts" in script
    assert "Test-AuthenticodeArtifacts `" in script
    assert "-Artifacts $signableArtifacts `" in script
    assert "-SignToolPin $releaseToolPins.signtool" in script
    assert "Invoke-DefenderScan -Artifacts $artifacts" in script
    assert "Write-ReleaseEvidence -Artifacts $artifacts" in script
    assert "Test-AuthenticodeArtifacts -Artifacts $artifacts" not in script
    assert "Pinned release tool manifest must not be a reparse point." in script
    assert "$pins -isnot [System.Management.Automation.PSCustomObject]" in script
    assert "$raw.TrimStart().StartsWith(" in script

    source_preflight = script.index('-Description "SOURCE RELEASE PREFLIGHT"')
    build = script.index('-Description "BUILD RELEASE ARTIFACTS"')
    boundary_sign_tool = script.index("-ConfiguredPath $signTool", source_preflight)
    boundary_iscc = script.index("-ConfiguredPath $iscc", source_preflight)
    assert source_preflight < boundary_sign_tool < build
    assert source_preflight < boundary_iscc < build


def test_release_finalizer_normalizes_only_iscc_version_metadata_padding():
    script = _read("scripts/finalize_release.ps1")
    helper_start = script.index("function Test-PinnedProductVersion")
    helper_end = script.index("function Resolve-PinnedReleaseTool", helper_start)
    helper = script[helper_start:helper_end]

    assert "$ActualVersion.Trim() -ceq $PinnedVersion" in helper
    assert "[string]::IsNullOrWhiteSpace($ActualVersion)" in helper

    identity_checks = script.index("$actualHash")
    sign_tool_start = script.index('if ($Name -ceq "Windows SDK SignTool") {', identity_checks)
    iscc_start = script.index('elseif ($Name -ceq "Inno Setup ISCC.exe") {', sign_tool_start)
    sign_tool_scope = script[sign_tool_start:iscc_start]
    iscc_scope = script[iscc_start : script.index("return $item.FullName", iscc_start)]

    assert "$item.VersionInfo.ProductVersion -cne [string]$Pin.version" in (sign_tool_scope)
    assert "Test-PinnedProductVersion" not in sign_tool_scope
    assert "-not (Test-PinnedProductVersion `" in iscc_scope
    assert "-ActualVersion ([string]$versionCarrier.VersionInfo.ProductVersion)" in (iscc_scope)
    assert "-PinnedVersion ([string]$Pin.version)" in iscc_scope


def test_release_tools_are_reverified_at_their_actual_use_points():
    build = _read("packaging/build_variants.bat")
    sign_start = build.index("\n:sign_file")
    sign_end = build.index("\n:force_delete", sign_start)
    sign_scope = build[sign_start:sign_end]
    sign_verify = '"%DUPEZ_PYTHON%" -I packaging\\release_data.py verify-tool ' '--name signtool --path "%_SIGNTOOL%"'
    assert sign_scope.index(sign_verify) < sign_scope.index('"%_SIGNTOOL%" sign ')

    release_data = _read("packaging/release_data.py")
    verify_iscc = 'verified_iscc = tool_verifier("iscc", iscc)'
    invoke_iscc = "[str(verified_iscc), str(definition)]"
    assert "def verify_release_tool(" in release_data
    assert release_data.index(verify_iscc) < release_data.index(invoke_iscc)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="PowerShell contract is Windows-only",
)
def test_release_tool_pin_manifest_contract_is_executable():
    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
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
            str(ROOT / "tests" / "ci" / "release_tool_pin_contract_test.ps1"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        shell=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_canonical_release_toolchain_is_python_31317_x64():
    for relative in ("packaging/build.bat", "packaging/build_variants.bat"):
        script = _read(relative)
        assert "if not defined DUPEZ_BOOTSTRAP_PYTHON set" in script
        assert "64-bit Python 3.13.17" in script
        assert "sys.version_info[:3] == (3, 13, 17)" in script
        assert "3.11.9" not in script
        assert 'set "PYTHONHASHSEED=0"' in script
        assert 'set "SOURCE_DATE_EPOCH=315532800"' in script

    finalizer = _read("scripts/finalize_release.ps1")
    assert "repository Python 3.13.17 x64" in finalizer
    assert "sys.version_info[:3]==(3,13,17)" in finalizer
    assert "struct.calcsize('P')==8" in finalizer

    for relative in (
        ".github/workflows/release.yml",
        ".github/workflows/frozen-smoke.yml",
        ".github/workflows/unsigned-public-release.yml",
    ):
        workflow = _read(relative)
        assert "Setup canonical release Python 3.13.17" in workflow
        assert "python-version: '3.13.17'" in workflow
        assert "architecture: x64" in workflow
        assert "sys.version_info[:3]==(3,13,17)" in workflow
        assert "struct.calcsize('P')==8" in workflow
        assert "Canonical Python 3.13.17 x64 verification failed." in workflow


def test_frozen_build_requires_patched_pyinstaller_bootloader():
    requirements = [
        Requirement(line)
        for line in _read("packaging/requirements-build.in").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    pyinstaller = next(requirement for requirement in requirements if requirement.name.casefold() == "pyinstaller")
    specifiers = list(pyinstaller.specifier)

    assert len(specifiers) == 1
    assert specifiers[0].operator == "=="
    assert Version(specifiers[0].version) >= Version("6.22.1")


def test_ci_exercises_supported_modern_python_and_lock_is_fail_closed():
    tests_ci = _read(".github/workflows/tests-ci.yml")
    lock = _read(".github/workflows/requirements-lock.yml")
    hardware = _read(".github/workflows/hardware-smoketest.yml")

    assert "python-version: ['3.12', '3.13']" in tests_ci
    assert "python-version: ['3.11', '3.12']" not in tests_ci
    assert 'python-version: "3.13.17"' in lock
    assert "pip install --dry-run --require-hashes" in lock
    assert "|| {" not in lock
    assert "::warning::Full hashed install" not in lock
    assert "python-version: '3.13.17'" in hardware


def test_unsigned_workflow_is_artifact_only_and_requires_protected_staging():
    workflow = _read(".github/workflows/unsigned-public-release.yml")
    finalizer = _read("scripts/finalize_release.ps1")
    preflight = _read("scripts/release_preflight.py")

    for token in (
        "BUILD UNSIGNED ARTIFACTS",
        "No Publication",
        "-AllowUnsigned",
        "DUPEZ_SIGN_PRIVKEY",
        "--verify-runtime-imports",
        "--allow-unsigned",
        "subject-checksums: dist/SHA256SUMS.txt",
        "sbom-path: dist/DupeZ.sbom.json",
        "DefenderScan.txt",
        "all 16 gates",
        "scripts\\validate_frozen_runtime.ps1 -Variant GPU",
        "scripts\\validate_frozen_runtime.ps1 -Variant Compat",
        "scripts\\record_manual_release_validation.ps1",
        "scripts\\stage_release.ps1 -Mode Draft",
        "scripts\\stage_release.ps1 -Mode Publish",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    ):
        assert token in workflow, token

    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "GH_TOKEN" not in workflow
    assert "gh release" not in workflow
    assert "release create" not in workflow
    assert "release edit" not in workflow
    assert "--latest" not in workflow
    assert "run: .\\scripts\\record_manual_release_validation.ps1" not in workflow
    assert "manual-release-validation.json" not in workflow
    assert "distribution_signing_mode" in finalizer
    assert '"--allow-unsigned"' in preflight


def test_release_staging_requires_exact_artifact_evidence():
    script = _read("scripts/stage_release.ps1")
    frozen_contract = _read("scripts/frozen_runtime_evidence_contract.ps1")

    required = (
        "scripts\\release_preflight.py",
        "--dist",
        "--allow-unsigned",
        "AllowUnsigned",
        "SHA256SUMS.txt",
        "release-attestation.json",
        "frozen-runtime-evidence-gpu.json",
        "frozen-runtime-evidence-compat.json",
        "hardware-smoketest-evidence.json",
        "scripts\\hardware_evidence.py",
        "HARDWARE EVIDENCE VALIDATION",
        "Assert-AuthenticatedHardwareEvidence",
        '"api", "--hostname", "github.com", "--method", "GET", "user"',
        "Hardware workflow run metadata does not match release policy",
        "Hardware workflow identity does not match release policy",
        "hardware-smoketest-evidence-$commit",
        "actions/artifacts/$ArtifactId/zip",
        "artifact_archive_sha256",
        "Authenticated hardware evidence archive digest mismatch",
        "Expected exactly one authenticated hardware evidence artifact",
        "Hardware evidence artifact listing is incomplete or ambiguous",
        "Local hardware evidence does not exactly match the",
        "Copy-ReleaseAssetSnapshot",
        "Release snapshot before upload",
        "Downloaded release",
        "authenticated_github_actions",
        "manual-release-validation.json",
        "dupez.release-attestation.v1",
        "dupez.manual-release-validation.v1",
        "source_native_artifacts",
        "distribution_signing_mode",
        "Release attestation signing mode mismatch",
        "Manual release validation signing mode mismatch",
        "release-validation-attestation.json",
        "frozen_runtime_evidence_contract.ps1",
        "Assert-FrozenRuntimeEvidenceContract",
        "already published",
        "immutable assets will not be replaced",
        '"--draft"',
        '"--draft=false"',
        'ValidateSet("Draft", "Publish")',
        "targetCommitish",
        "Staged release size mismatch",
        "unexpected assets",
        "DOWNLOAD STAGED RELEASE FOR HASH VERIFICATION",
        "Downloaded release SHA-256 mismatch",
    )
    for token in required:
        assert token in script, token

    for token in (
        "dupez.frozen-runtime-validation.v3",
        "production-safety-dry-run",
        "Architecture: split | Admin: False",
        "Architecture: inproc | Admin: True",
        'source_state -cne "clean"',
        "Map: dashboard view active with WebEngine ready",
    ):
        assert token in frozen_contract, token

    unsigned_preflight = script.index('$preflightArguments += "--allow-unsigned"')
    preflight_call = script.index('-Description "FINAL DIST RELEASE PREFLIGHT"')
    assert unsigned_preflight < preflight_call
    local_evidence_read = script.index("$localHardwareEvidence = Read-JsonFile")
    authenticated_evidence = script.index(
        "$authenticatedHardwareEvidenceResult = " "Assert-AuthenticatedHardwareEvidence",
        local_evidence_read,
    )
    trusted_evidence_use = script.index(
        "$hardwareEvidence = $authenticatedHardwareEvidenceResult.Evidence",
        authenticated_evidence,
    )
    assert local_evidence_read < authenticated_evidence < trusted_evidence_use
    assert "HARDWARE EVIDENCE VALIDATION (AUTHENTICATED DOWNLOAD)" in script
    assert "Evidence = $trustedEvidence" in script
    assert '"--evidence", $hardwareEvidencePath' not in script


def test_release_staging_verifies_exact_provenance_and_sbom_subjects():
    import yaml

    stage = _read("scripts/stage_release.ps1")
    expected_workflow_subjects = {
        "dist/DupeZ-GPU.exe",
        "dist/DupeZ-Compat.exe",
        "dist/DupeZ_v${{ inputs.version }}_Setup.exe",
        "dist/DupeZ_Setup.exe",
    }
    base_assets_start = stage.index("$baseAssetNames = @(")
    base_assets_end = stage.index("\n    )", base_assets_start)
    base_assets = stage[base_assets_start:base_assets_end]
    staged_executables = {
        "dist/"
        + line.strip()
        .rstrip(",")
        .strip('"')
        .replace(
            "${Version}",
            "${{ inputs.version }}",
        )
        for line in base_assets.splitlines()
        if line.strip().rstrip(",").strip('"').endswith(".exe")
    }
    assert staged_executables == expected_workflow_subjects

    for relative in (
        ".github/workflows/release.yml",
        ".github/workflows/unsigned-public-release.yml",
    ):
        workflow = yaml.load(_read(relative), Loader=yaml.BaseLoader)
        job = next(iter(workflow["jobs"].values()))
        provenance_step = next(step for step in job["steps"] if step.get("name", "").endswith("build provenance"))
        sbom_step = next(step for step in job["steps"] if step.get("name", "").endswith("release SBOM"))
        subjects = {line.strip() for line in sbom_step["with"]["subject-path"].splitlines() if line.strip()}

        assert provenance_step["with"] == {"subject-checksums": "dist/SHA256SUMS.txt"}
        assert subjects == expected_workflow_subjects
        assert sbom_step["with"]["sbom-path"] == "dist/DupeZ.sbom.json"

    policy_start = stage.index("function Assert-GitHubArtifactAttestations")
    policy_end = stage.index("\nfunction New-PrivateStageDirectory", policy_start)
    policy = stage[policy_start:policy_end]
    assert '$item.Extension -ieq ".exe"' in policy
    assert '$item.Name -ceq "DupeZ.sbom.json"' in policy
    assert "$provenanceSubjects = @($publishableExecutables) + @($sbomAssets)" in policy
    assert policy.count("foreach ($subject in $publishableExecutables)") == 1
    for non_attested_evidence in (
        "SHA256SUMS.txt",
        "release-attestation.json",
        "release-validation-attestation.json",
        "DefenderScan.txt",
    ):
        assert non_attested_evidence not in policy

    for executable in (
        '"DupeZ-GPU.exe"',
        '"DupeZ-Compat.exe"',
        '"DupeZ_v${Version}_Setup.exe"',
        '"DupeZ_Setup.exe"',
    ):
        assert executable in stage


def test_release_attestation_checks_bind_identity_commit_and_all_three_phases():
    stage = _read("scripts/stage_release.ps1")
    verifier_start = stage.index("function Invoke-GhAttestationVerification")
    verifier_end = stage.index(
        "\nfunction Assert-GitHubArtifactAttestations",
        verifier_start,
    )
    verifier = stage[verifier_start:verifier_end]

    for token in (
        '"attestation", "verify", $item.FullName',
        '"--repo", $Repository',
        '"--signer-workflow", $SignerWorkflow',
        '"--signer-digest", $SourceCommit',
        '"--source-ref", "refs/heads/main"',
        '"--source-digest", $SourceCommit',
        '"--predicate-type", $PredicateType',
        '"--format", "json"',
        '"--jq", "length"',
        "2>$null",
        "$exitCode -ne 0",
        "$matchCount -lt 1",
        "GitHub $AttestationKind attestation verification failed for",
    ):
        assert token in verifier, token
    assert "Write-Host $result" not in verifier
    assert "Write-Output $result" not in verifier

    assert '"https://slsa.dev/provenance/v1"' in stage
    assert '"https://cyclonedx.org/bom"' in stage
    assert '"$Repository/.github/workflows/release.yml"' in stage
    assert '"$Repository/.github/workflows/unsigned-public-release.yml"' in stage
    assert stage.count("Assert-GitHubArtifactAttestations `") == 3

    local_verify = stage.index('-Description "VERIFY LOCAL RELEASE SUBJECT ATTESTATIONS BEFORE DRAFT"')
    draft_mutation = stage.index("-Description $draftMutationDescription")
    upload = stage.index('-Description "UPLOAD VERIFIED RELEASE ASSETS"')
    download = stage.index('-Description "DOWNLOAD STAGED RELEASE FOR HASH VERIFICATION"')
    download_lock = stage.index("Open-ReleaseAssetReadLocks -Assets $downloadedAssets")
    downloaded_verify = stage.index('-Description "VERIFY DOWNLOADED RELEASE SUBJECT ATTESTATIONS AFTER UPLOAD"')
    final_verify = stage.index('-Description "FINAL RELEASE SUBJECT ATTESTATIONS BEFORE PUBLISH"')
    publish = stage.index('-Description "PUBLISH VERIFIED RELEASE"')

    assert local_verify < draft_mutation < upload < download < download_lock
    assert download_lock < downloaded_verify
    assert downloaded_verify < final_verify < publish
    assert "-Assets $downloadedAssets `" in stage[final_verify - 300 : publish]
    assert '-Description "Downloaded release immediately before publish"' in stage[downloaded_verify:final_verify]
    lock_disposal = stage.index(
        "foreach ($lock in $downloadedAssetLocks)",
        publish,
    )
    assert publish < lock_disposal


def test_remote_main_guard_is_wired_immediately_before_mutating_release_phases():
    stage = _read("scripts/stage_release.ps1")
    function_start = stage.index("function Assert-RemoteMainCommit")
    function_end = stage.index("\nfunction ", function_start + 10)
    contract = stage[function_start:function_end]

    for token in (
        'if ($ExpectedRepository -cne "GrihmLord/DupeZ")',
        "repos/GrihmLord/DupeZ/git/ref/heads/main",
        '"--hostname", "github.com"',
        '"--method", "GET"',
        '"ref" -notin $properties',
        '"object" -notin $properties',
        '$response.ref -cne "refs/heads/main"',
        '$response.object.type -cne "commit"',
        "$remoteCommit = ([string]$response.object.sha).Trim().ToLowerInvariant()",
        "$remoteCommit -cne $commit",
    ):
        assert token in contract, token

    assert stage.count("Assert-RemoteMainCommit `") == 3
    draft_guard = stage.index('-Description "VERIFY CANONICAL REMOTE MAIN BEFORE DRAFT"')
    draft_mutation = stage.index("-Description $draftMutationDescription")
    upload_guard = stage.index('-Description "VERIFY CANONICAL REMOTE MAIN BEFORE UPLOAD"')
    upload = stage.index('-Description "UPLOAD VERIFIED RELEASE ASSETS"')
    publish_guard = stage.index('-Description "VERIFY CANONICAL REMOTE MAIN BEFORE PUBLISH"')
    publish = stage.index('-Description "PUBLISH VERIFIED RELEASE"')

    assert draft_guard < draft_mutation < upload_guard < upload
    assert upload < publish_guard < publish
    for gap in (
        stage[draft_guard:draft_mutation],
        stage[upload_guard:upload],
        stage[publish_guard:publish],
    ):
        # The only following command is the mutation whose Description token
        # closes this slice; no independent check or mutation may intervene.
        assert gap.count("Invoke-Checked") == 1
        assert "Assert-RemoteMainCommit" not in gap


def test_stage_hardware_evidence_contract_is_executable():
    import os
    import subprocess

    stage = _read("scripts/stage_release.ps1")
    assert '$Repository -cne "GrihmLord/DupeZ"' in stage
    assert '[string]$run.status -cne "completed"' in stage
    assert '[string]$run.conclusion -cne "success"' in stage
    assert '[string]$run.head_branch -cne "main"' in stage
    assert '[string]$run.name -cne "Hardware Smoketest"' in stage
    assert "$runWorkflowFile -cne $expectedWorkflowPath" in stage
    assert "[string]$workflow.path -cne $expectedWorkflowPath" in stage
    assert '[string]$run.event -cnotin @("schedule", "workflow_dispatch")' in stage
    assert "New-PrivateStageDirectory" in stage
    assert "Invoke-GhArtifactArchiveDownload" in stage
    assert "actions/artifacts/$ArtifactId/zip" in stage
    assert "artifact_archive_sha256" in stage
    assert '"run", "download", $runIdText' not in stage
    assert "Copy-ReleaseAssetSnapshot" in stage
    assert "Get-ReleaseAssetBinding" in stage
    assert "Assert-ReleaseAssetBinding" in stage
    assert "Remove-Item" in stage

    if os.name != "nt":
        return
    powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    completed = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "tests" / "ci" / "stage_hardware_evidence_contract_test.ps1"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        shell=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_release_attests_measured_update_signer_and_v58_recovery_policy():
    finalizer = _read("scripts/finalize_release.ps1")
    staging = _read("scripts/stage_release.ps1")

    assert "verified_key_fingerprint = $UpdaterSignerFingerprint" in finalizer
    assert "[System.IO.File]::ReadAllBytes($signaturePath)" in finalizer
    assert "$envelope[0..7]" in finalizer
    assert "pinned_key_fingerprint =" not in finalizer
    assert finalizer.index("FINAL DIST RELEASE PREFLIGHT") < finalizer.index(
        "Get-VerifiedUpdaterSignerFingerprint -ReleaseVersion $Version"
    )
    assert "verified_key_fingerprint" in staging
    assert "required v5.8 recovery " in staging
    assert '"update signer."' in staging


def test_manual_gate_contract_is_exact_and_executable():
    import os
    import subprocess

    contract = _read("scripts/manual_release_gate_contract.ps1")
    staging = _read("scripts/stage_release.ps1")
    assert "$actual.Count -ne $expectedUnique.Count" in contract
    assert "$missing.Count -gt 0" in contract
    assert "$extra.Count -gt 0" in contract
    assert "$gate.Value -isnot [bool]" in contract
    assert "Assert-ExactManualReleaseGates" in staging

    if os.name != "nt":
        return
    powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    completed = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "tests" / "ci" / "manual_release_gate_contract_test.ps1"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        shell=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_release_consumers_share_hardened_git_provenance():
    contract = _read("scripts/release_git_contract.ps1")
    for token in (
        "Resolve-TrustedReleaseGit",
        "Git\\cmd\\git.exe",
        "--no-replace-objects",
        'GIT_CONFIG_NOSYSTEM = "1"',
        'GIT_CONFIG_GLOBAL = "NUL"',
        "core.excludesFile=NUL",
        "core.attributesFile=NUL",
        "refs/replace",
        "extensions\\.worktreeconfig",
        "skip-worktree or assume-unchanged",
        "hash-object",
        "--untracked-files=all",
        "Assert-ReleaseGitIdentityUnchanged",
    ):
        assert token in contract, token

    for relative in (
        "scripts/finalize_release.ps1",
        "scripts/record_manual_release_validation.ps1",
        "scripts/stage_release.ps1",
        "scripts/release_gate_launcher.ps1",
        "scripts/blocked_release_gates_sequence.ps1",
    ):
        consumer = _read(relative)
        assert '"release_git_contract.ps1"' in consumer, relative
        assert "Get-ReleaseGitIdentity" in consumer, relative
        assert "Get-Command git" not in consumer, relative


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell contract is Windows-only")
def test_release_git_contract_is_executable():
    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
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
            str(ROOT / "tests" / "ci" / "release_git_contract_test.ps1"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        shell=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_fresh_release_workflows_install_exact_hashed_runtime_dependencies():
    for relative in (
        ".github/workflows/source-preflight.yml",
        ".github/workflows/release.yml",
        ".github/workflows/unsigned-public-release.yml",
    ):
        workflow = _read(relative)
        for token in (
            "--require-hashes",
            "--only-binary=:all:",
            "--no-deps",
            "requirements-locked.txt",
            "pip --isolated check",
        ):
            assert token in workflow, f"{relative}: {token}"


def test_manual_gate_names_and_unsigned_public_notice_are_unambiguous():
    recorder = _read("scripts/record_manual_release_validation.ps1")
    gate_contract = _read("scripts/manual_release_gate_contract.ps1")
    stage = _read("scripts/stage_release.ps1")

    assert "$gateDescriptions = [ordered]@{" in recorder
    assert "$gateDescriptions.GetEnumerator()" in recorder
    assert "\\$gateDescriptions" in gate_contract
    assert "(UNSIGNED WINDOWS BUILD)" in stage
    assert "Distribution signing: UNSIGNED WINDOWS BUILD" in stage
    assert '"--title", $releaseTitle' in stage
    assert '"--notes-file", $releaseNotesSnapshot.FullName' in stage
    assert "Staged release signing-mode title or notice is incorrect." in stage


def test_unsigned_manifest_mode_is_explicit_and_not_the_build_default():
    build = _read("packaging/build_variants.bat")
    finalizer = _read("scripts/finalize_release.ps1")

    assert 'if not defined DUPEZ_ALLOW_UNSIGNED set "DUPEZ_ALLOW_UNSIGNED=0"' in build
    assert 'if "%DUPEZ_ALLOW_UNSIGNED%"=="1"' in build
    assert "--allow-unsigned" in build
    assert '$env:DUPEZ_ALLOW_UNSIGNED = "1"' in finalizer
    assert '$env:DUPEZ_ALLOW_UNSIGNED = "0"' in finalizer


def test_variant_build_wires_exact_measured_native_stage_into_both_specs():
    build = _read("packaging/build_variants.bat")

    mode_default = build.index('set "DUPEZ_RELEASE_MODE=standard-authenticode"')
    stage_export = build.index('set "DUPEZ_RELEASE_NATIVE_STAGE=%CD%\\build\\release-native"')
    prepare = build.index("packaging\\release_data.py prepare")
    staged_clumsy = build.index('call :sign_file "%DUPEZ_RELEASE_NATIVE_STAGE%' '\\app\\firewall\\clumsy.exe"')
    finalize = build.index('packaging\\release_data.py finalize --mode "%DUPEZ_RELEASE_MODE%"')
    verify = build.index('packaging\\release_data.py verify --mode "%DUPEZ_RELEASE_MODE%"')
    gpu_spec = build.index("PyInstaller packaging\\dupez_gpu.spec --noconfirm")
    compat_spec = build.index("PyInstaller packaging\\dupez_compat.spec --noconfirm")
    emit = build.index("packaging\\release_data.py emit-provenance")

    assert mode_default < stage_export < prepare < staged_clumsy < finalize < verify < gpu_spec < compat_spec < emit
    assert '--mode "%DUPEZ_RELEASE_MODE%" ^' in build[emit:]
    assert "--out dist\\binary-provenance.json" in build[emit:]
    assert ("copy /y packaging\\binary-provenance.json " "dist\\binary-provenance.json") not in build.lower()


def test_variant_build_native_mode_is_derived_and_standard_fails_closed():
    build = _read("packaging/build_variants.bat")

    assert ('if "%DUPEZ_PORTABLE_ONLY%"=="1" ' 'set "DUPEZ_RELEASE_MODE=explicit-unsigned"') in build
    assert ('if "%DUPEZ_ALLOW_UNSIGNED%"=="1" ' 'set "DUPEZ_RELEASE_MODE=explicit-unsigned"') in build

    prerequisite_start = build.index('if "%DUPEZ_RELEASE_MODE%"=="standard-authenticode" (')
    prerequisite_end = build.index('if exist "%DUPEZ_BUILD_VENV%"', prerequisite_start)
    prerequisites = build[prerequisite_start:prerequisite_end]
    for token in (
        "Standard distribution builds require Windows SDK SignTool",
        "Standard distribution builds require DUPEZ_SIGN_CERT",
        "DUPEZ_SIGN_CERT points at a missing certificate file",
    ):
        assert token in prerequisites, token
    assert prerequisites.count("exit /b 1") >= 3

    staged_sign = build.index('call :sign_file "%DUPEZ_RELEASE_NATIVE_STAGE%' '\\app\\firewall\\clumsy.exe"')
    assert (
        build.rfind(
            'if not "%DUPEZ_RELEASE_MODE%"=="standard-authenticode" ' "goto :finalize_native_stage",
            0,
            staged_sign,
        )
        != -1
    )
    assert 'if not "%DUPEZ_LAST_SIGNED%"=="1" (' in build[staged_sign:]
    assert "Standard staged Clumsy signing did not complete" in build
    assert "Standard Authenticode release preflight remains blocked" not in build


def test_unsigned_mode_is_propagated_through_staging_and_runbooks():
    sequence = _read("scripts/blocked_release_gates_sequence.ps1")
    blocked_runbook = _read("docs/release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md")
    release_runbook = _read("docs/RELEASE_VALIDATION_V5.8.0.md")

    stage_propagation = 'if ($AllowUnsigned) { $stageArgs += "-AllowUnsigned" }'
    assert sequence.count(stage_propagation) == 2
    for phase in ("admin-stage-draft", "admin-stage-publish"):
        expected = f"-Phase {phase} -Version 5.8.0 -AllowUnsigned"
        assert expected in blocked_runbook
    for mode in ("Draft", "Publish"):
        expected = f"stage_release.ps1 -Mode {mode} -Version 5.8.0 " "-Repository GrihmLord/DupeZ -AllowUnsigned"
        assert expected in release_runbook


def test_release_workflow_keeps_keys_on_protected_nonpublishing_runner():
    workflow = _read(".github/workflows/release.yml")

    assert "runs-on: [self-hosted, windows, release-signing]" in workflow
    assert "environment: production-release" in workflow
    assert "Mask signing-host identity in release logs" in workflow
    assert 'Write-Output "::add-mask::$value"' in workflow
    assert "$env:USERPROFILE" in workflow
    assert "$env:COMPUTERNAME" in workflow
    assert "DUPEZ_RELEASE_REF: ${{ github.ref }}" in workflow
    assert "$env:DUPEZ_RELEASE_REF -ne 'refs/heads/main'" in workflow
    assert "'${{ github.ref }}' -ne 'refs/heads/main'" not in workflow
    assert ("DUPEZ_RELEASE_GOVERNANCE_READY: " "${{ vars.DUPEZ_RELEASE_GOVERNANCE_READY }}") in workflow
    assert "$env:DUPEZ_RELEASE_GOVERNANCE_READY -ne" in workflow
    assert "protected-main-solo-maintainer-environment" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "scripts\\finalize_release.ps1" in workflow
    assert ".\\scripts\\stage_release.ps1" not in workflow
    assert "dist\\DupeZ-GPU.exe" in workflow
    assert "dist\\DupeZ-Compat.exe" in workflow
    assert workflow.count("--verify-runtime-imports") == 1
    assert "secrets.DUPEZ_SIGN_CERT" not in workflow
    assert "secrets.DUPEZ_SIGN_PRIVKEY" not in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d" in workflow
    assert "subject-checksums: dist/SHA256SUMS.txt" in workflow
    assert "sbom-path: dist/DupeZ.sbom.json" in workflow
    assert "release create" not in workflow
    assert "release edit" not in workflow


def test_unsigned_release_build_is_bound_to_exact_main_sha():
    workflow = _read(".github/workflows/unsigned-public-release.yml")

    assert "DUPEZ_RELEASE_REF: ${{ github.ref }}" in workflow
    assert "$env:DUPEZ_RELEASE_REF -ne 'refs/heads/main'" in workflow
    assert "'${{ github.ref }}' -ne 'refs/heads/main'" not in workflow
    assert ("DUPEZ_RELEASE_GOVERNANCE_READY: " "${{ vars.DUPEZ_RELEASE_GOVERNANCE_READY }}") in workflow
    assert "$env:DUPEZ_RELEASE_GOVERNANCE_READY -ne" in workflow
    assert "protected-main-solo-maintainer-environment" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "persist-credentials: false" in workflow


def test_protected_release_workflows_keep_contexts_out_of_all_run_blocks():
    assert _check_workflow_run_context_policy() == []

    for relative in (
        ".github/workflows/release.yml",
        ".github/workflows/unsigned-public-release.yml",
    ):
        workflow = _read(relative)
        assert "DUPEZ_RELEASE_VERSION: ${{ inputs.version }}" in workflow
        assert "-Version $env:DUPEZ_RELEASE_VERSION" in workflow


@pytest.mark.parametrize(
    "payload",
    (
        "5.8.0'\"; Write-Output DUPEZ_INJECTION_SENTINEL; #",
        "5.8.0\nWrite-Output DUPEZ_INJECTION_SENTINEL",
        "5.8.0; Write-Output DUPEZ_INJECTION_SENTINEL",
        "$(Write-Output DUPEZ_INJECTION_SENTINEL)",
    ),
    ids=("quotes", "newline", "semicolon", "powershell-subexpression"),
)
def test_release_run_context_gate_blocks_adversarial_dispatch_values(
    tmp_path: Path,
    payload: str,
):
    direct_run = "Write-Output '${{ inputs.version }}'"
    env_run = "Write-Output $env:DUPEZ_RELEASE_VERSION"
    assert "DUPEZ_INJECTION_SENTINEL" in direct_run.replace(
        "${{ inputs.version }}",
        payload,
    )
    assert env_run.replace("${{ inputs.version }}", payload) == env_run

    unsafe = tmp_path / "adversarial.yml"
    unsafe.write_text(
        "jobs:\n" "  release:\n" "    steps:\n" "      - shell: pwsh\n" "        run: |\n" f"          {direct_run}\n",
        encoding="utf-8",
    )

    errors = _check_workflow_run_context_policy((unsafe,))

    assert len(errors) == 1
    assert "unsafe GitHub context interpolation" in errors[0]
    assert "adversarial.yml" in errors[0]


def test_release_run_context_gate_covers_every_yaml_run_scalar(tmp_path: Path):
    workflow = tmp_path / "run-scalars.yaml"
    workflow.write_text(
        "jobs:\n"
        "  release:\n"
        "    steps:\n"
        "      - run: echo ${{ inputs.inline }}\n"
        "      - run: |\n"
        "          echo ${{ github.ref }}\n"
        "      - run: >-\n"
        "          echo ${{ vars.FOLDED }}\n",
        encoding="utf-8",
    )

    errors = _check_workflow_run_context_policy((workflow,))

    assert len(errors) == 3
    assert all("run-scalars.yaml" in error for error in errors)


def test_release_driver_delegates_to_canonical_gate_launcher_without_bypasses():
    script = _read("scripts/release.ps1")
    cmd = _read("scripts/release_gate_launcher.cmd")
    preflight = _read("scripts/release_preflight.py")

    assert '"release_gate_launcher.ps1"' in script
    assert '[string]$Phase = "status"' in script
    assert '"admin-stage-publish"' in script
    assert "& $launcherPath @launcherArguments" in script
    assert "AllowUnsigned" in script
    assert "AllowNonMainValidation" in script
    assert "gh release create" not in script
    assert "git tag" not in script
    assert "git push" not in script
    assert "SkipBuild" not in script
    assert "SkipHooks" not in script
    assert '"scripts/release.ps1": _match_version(' in preflight
    assert '"scripts\\release.ps1"' in cmd
    assert "%*" in cmd
    assert "-Phase auto" not in cmd


def test_v580_runbook_uses_canonical_launcher_and_valid_operator_example():
    runbook = _read(
        "docs/release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md"
    )

    assert "scripts/release.ps1" in runbook
    assert "scripts/blocked_release_gates_sequence.ps1" not in runbook
    assert 'Operator "YOUR_NAME"' in runbook
    assert "<YOUR_NAME>" not in runbook
    assert "Publication is never automatic" in _read(
        "scripts/release_gate_launcher.ps1"
    )


def test_public_docs_and_automation_do_not_embed_owner_host_paths():
    text_suffixes = {
        ".bat",
        ".cmd",
        ".iss",
        ".json",
        ".md",
        ".ps1",
        ".py",
        ".txt",
        ".yaml",
        ".yml",
    }
    roots = (
        ROOT / ".github",
        ROOT / "app",
        ROOT / "docs",
        ROOT / "packaging",
        ROOT / "scripts",
    )
    forbidden = ("c:/users/owner/", "c:\\users\\owner\\")

    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in text_suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="replace").casefold()
            assert not any(marker in text for marker in forbidden), path


def test_current_release_governance_docs_use_solo_maintainer_contract():
    current_docs = (
        "ROADMAP.md",
        "docs/RELEASE_VALIDATION_V5.8.0.md",
        "docs/release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md",
    )

    for relative in current_docs:
        text = _read(relative)
        assert "protected-main-reviewed-environment" not in text, relative

    assert "one write-capable maintainer" in _read("ROADMAP.md")
    assert "protected-main-solo-maintainer-environment" in _read(
        "ROADMAP.md"
    )
    assert "solo-maintainer repository" in _read(
        "docs/RELEASE_VALIDATION_V5.8.0.md"
    )
    assert "one write-capable maintainer" in _read(
        "docs/release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md"
    )


def test_saved_current_github_governance_audit_matches_release_contract():
    audit = json.loads(
        _read(
            "assessment/evidence/"
            "GITHUB_GOVERNANCE_AUDIT_2026-09-04.json"
        )
    )
    results = audit["results"]
    ruleset = results["repository_rulesets"][
        "active_default_branch_ruleset"
    ]
    checks = ruleset["required_status_checks"]
    environment = results["production_release_environment"]
    variable = results["governance_ready_variable"]
    collaborators = results["direct_collaborators"]
    observed_checks = results["pull_request_84_exact_head_checks"]

    assert ruleset["name"] == "main-release-integrity"
    assert ruleset["enforcement"] == "active"
    assert ruleset["include"] == ["~DEFAULT_BRANCH"]
    assert ruleset["bypass_actor_count"] == 0
    assert ruleset["current_user_can_bypass"] == "never"
    assert ruleset["pull_request"]["required_approving_review_count"] == 0
    assert ruleset["pull_request"]["required_review_thread_resolution"]
    assert checks["strict"]
    assert checks["count"] == 14
    assert len(checks["contexts"]) == len(set(checks["contexts"])) == 14
    assert environment["required_reviewer_count"] == 0
    assert environment["deployment_branch_policy"]["allowed_branches"] == [
        "main"
    ]
    assert variable["value"] == (
        "protected-main-solo-maintainer-environment"
    )
    assert collaborators["write_capable_count"] == 1
    assert observed_checks["required_check_count"] == 14
    assert observed_checks["job_count"] == 14
    assert observed_checks["completed_failure_count"] == 14
    assert observed_checks["assigned_runner_count"] == 0
    assert observed_checks["executed_step_count"] == 0


def test_installer_alias_is_copied_after_versioned_signing():
    build = _read("packaging/build_variants.bat")
    sign_index = build.index('call :sign_file "dist\\%DUPEZ_INSTALLER%"')
    copy_index = build.index('copy /Y "dist\\%DUPEZ_INSTALLER%" "dist\\DupeZ_Setup.exe"')

    assert sign_index < copy_index
    assert 'call :sign_file "dist\\DupeZ_Setup.exe"' not in build
    assert "DUPEZ_SIGNTOOL" in build
    assert "DUPEZ_SIGN_TIMESTAMP_URL" in build


def test_frozen_verifier_diagnostics_are_opt_in_and_path_free():
    launcher = _read("dupez.py")
    build = _read("packaging/build_variants.bat")

    assert 'os.environ.get("DUPEZ_VERIFY_REPORT")' in launcher
    assert '"error_type"' in launcher
    assert '"missing_module"' in launcher
    assert "str(error)" not in launcher
    assert "--verify-runtime-imports failed: {e}" not in launcher
    assert "--verify-self failed: {e}" not in launcher
    assert "DUPEZ_VERIFY_REPORT" in build


def test_renderer_bootstrap_reads_canonical_user_config_first():
    launcher = _read("dupez.py")

    canonical = launcher.index("config_dir as _config_dir")
    legacy = launcher.index("os.path.dirname(sys.executable)", canonical)
    assert canonical < legacy
    assert '_mr in {"gpu", "software"}' in launcher
    assert 'if _mr == "swiftshader":' in launcher


def test_frozen_runtime_has_deterministic_webengine_health_signals():
    map_gui = _read("app/gui/dayz_map_gui_new.py")
    lazy_map = _read("app/gui/lazy_dayz_map.py")
    dashboard = _read("app/gui/dashboard.py")

    assert 'log_info("Map: WebEngine navigation ready")' in map_gui
    assert "renderProcessTerminated.connect" in map_gui
    assert 'log_error("Map: WebEngine navigation failed")' in map_gui
    signal = 'log_info("Map: dashboard view active with WebEngine ready")'
    assert signal in dashboard
    assert signal in lazy_map


def test_variant_build_failures_are_noninteractive():
    build = _read("packaging/build_variants.bat")
    workflow = _read(".github/workflows/frozen-smoke.yml")

    assert all(line.strip().lower() != "pause" for line in build.splitlines())
    assert "echo. | call packaging\\build_variants.bat" not in workflow
    assert "run: call packaging\\build_variants.bat" in workflow


def test_variant_build_requires_installer_except_frozen_archive_ci():
    build = _read("packaging/build_variants.bat")
    frozen = _read(".github/workflows/frozen-smoke.yml")
    finalizer = _read("scripts/finalize_release.ps1")

    assert 'if not defined DUPEZ_PORTABLE_ONLY set "DUPEZ_PORTABLE_ONLY=0"' in build
    assert 'if "%DUPEZ_PORTABLE_ONLY%"=="1"' in build
    installer_start = build.index(":: The finalizer resolves and verifies the pinned absolute compiler")
    installer = build[installer_start : build.index("\n:skip_installer", installer_start)]
    assert "goto :skip_installer" not in installer
    assert installer.count("exit /b 1") >= 4
    assert "skipping installer build" not in build
    assert "ship without installer" not in build
    assert "Portable-only output is CI evidence" in build
    assert "No release staging is permitted for portable-only output" in build

    assert "DUPEZ_PORTABLE_ONLY: '1'" in frozen
    enabled_workflows = [
        path.name
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
        if "DUPEZ_PORTABLE_ONLY: '1'" in path.read_text(encoding="utf-8")
    ]
    assert enabled_workflows == ["frozen-smoke.yml"]

    force_release = finalizer.index('$env:DUPEZ_PORTABLE_ONLY = "0"')
    build_release = finalizer.index('-Description "BUILD RELEASE ARTIFACTS"')
    assert force_release < build_release


def test_nonportable_variant_build_requires_signed_updater_sidecars():
    build = _read("packaging/build_variants.bat")

    portable_guard = build.index(
        'if "%DUPEZ_PORTABLE_ONLY%"=="1" (',
        build.index("[Signing] Signing update manifest"),
    )
    key_guard = build.index("if not defined DUPEZ_SIGN_PRIVKEY", portable_guard)
    section_end = build.index("\n:skip_sign_manifest", key_guard)
    signing_section = build[key_guard:section_end]

    assert portable_guard < key_guard
    assert build.count("goto :skip_sign_manifest") == 1
    assert "goto :skip_sign_manifest" not in signing_section
    for token in (
        "DUPEZ_SIGN_PRIVKEY is required for non-portable builds",
        "DUPEZ_SIGN_PRIVKEY points at a missing file",
        "sign-release.py failed",
        "sign-release.py did not create the update manifest",
        "sign-release.py did not create the update signature",
    ):
        assert token in signing_section, token
    assert signing_section.count("exit /b 1") >= 5
    assert "WARNING: sign-release.py" not in signing_section


def test_variant_build_summary_is_artifact_status_not_release_approval():
    build = _read("packaging/build_variants.bat")
    summary = build[build.index("echo [5/5] Build summary") : build.index("\npopd")]

    assert "artifact generation complete" in summary.lower()
    assert "authenticode status:" in summary.lower()
    assert "artifact generation is not release approval" in summary.lower()
    assert "mandatory gates remain" in summary.lower()
    assert "ship" not in summary.lower()
    assert "release-ready" not in summary.lower()

    signing_helper = build[build.index("\n:sign_file") :]
    assert 'set "DUPEZ_LAST_SIGNED=0"' in signing_helper
    assert 'set "DUPEZ_LAST_SIGNED=1"' in signing_helper
    assert summary.count('if "%DUPEZ_LAST_SIGNED%"=="1"') == 0
    status_updates = [line.strip() for line in build.splitlines() if "DUPEZ_AUTHENTICODE_STATUS=SIGNED" in line]
    assert status_updates
    assert all(line.startswith('if "%DUPEZ_LAST_SIGNED%"=="1"') for line in status_updates)


def test_clean_release_uses_review_and_omits_vex_artifact():
    build = _read("packaging/build_variants.bat")
    review_call = "scripts\\vulnerability_review.py --out " "dist\\DupeZ.vulnerability-review.json"
    assert review_call in build
    assert build.count("scripts\\vex.py") == 1
    assert 'if "%_VULNERABILITY_REVIEW_EXIT%"=="1" (' in build
    assert "A zero-finding review must not produce dist\\DupeZ.vex.json" in build

    for relative in (
        "scripts/finalize_release.ps1",
        "scripts/stage_release.ps1",
        ".github/workflows/frozen-smoke.yml",
        ".github/workflows/release.yml",
        ".github/workflows/unsigned-public-release.yml",
    ):
        artifact_contract = _read(relative)
        assert "DupeZ.vulnerability-review.json" in artifact_contract, relative
        assert "DupeZ.vex.json" not in artifact_contract, relative

    preflight = _read("scripts/release_preflight.py")
    from scripts.release_preflight import required_distribution_artifacts

    required = required_distribution_artifacts("5.8.0")
    assert "required = required_distribution_artifacts(version)" in preflight
    assert "DupeZ.vulnerability-review.json" in required
    assert "DupeZ.vex.json" not in required
    assert "zero-finding release must omit" in preflight
    assert "must contain at least one statement" in preflight


def test_frozen_runtime_validator_enforces_architecture_and_profiles():
    wrapper = _read("scripts/validate_frozen_runtime.ps1")
    implementation = _read("scripts/validate_frozen_runtime.py")

    for token in (
        'ValidateSet("GPU", "Compat")',
        "GPU validation must run from a standard, non-Administrator",
        "Compat validation must run from Administrator PowerShell",
        "scripts\\validate_frozen_runtime.py",
    ):
        assert token in wrapper, token

    for token in (
        "DUPEZ_LOW_RESOURCE",
        "DUPEZ_MAP_PREWARM",
        "DupeZ started successfully",
        "Map: WebEngine boundary initialized; awaiting navigation",
        "Map: WebEngine navigation ready",
        "Map: dashboard view active with WebEngine ready",
        "RELEASE_SENSITIVE_ENVIRONMENT_NAMES",
        "DUPEZ_DISABLE_CERT_PIN",
        "_is_ambient_secret_environment_name",
        "_log_text_since",
        "frozen-runtime-evidence-",
        "Architecture: split | Admin: False",
        "Architecture: inproc | Admin: True",
        "_git_source_identity",
        "dirty-validation",
        "_remove_private_runtime_root",
    ):
        assert token in implementation, token

    assert '"computer"' not in implementation
    assert '"command_line"' not in implementation
    assert '"runtime_root": str(runtime_root)' not in implementation

    ast.parse(implementation, filename="scripts/validate_frozen_runtime.py")


def test_manual_recorder_requires_all_exact_artifact_gates():
    script = _read("scripts/record_manual_release_validation.ps1")

    required = (
        "dupez.manual-release-validation.v1",
        "frozen-runtime-evidence-gpu.json",
        "frozen-runtime-evidence-compat.json",
        "hardware-smoketest-evidence.json",
        "scripts\\hardware_evidence.py validate",
        "source_native_artifacts",
        "hidden_clumsy_no_flash",
        "gpu_diagnostic_restore",
        "compat_diagnostic_restore",
        "map_failure_retry",
        "installer_fresh_install",
        "installer_upgrade",
        "installer_uninstall",
        "manual-release-validation.json",
        "Type YES for each gate",
        "AllowUnsigned",
        "distribution_signing_mode",
        "Authorized unsigned release installer",
        "Authenticode-signed release installer",
    )
    for token in required:
        assert token in script, token

    assert 'installer_fresh_install = "Signed installer' not in script

    sequence = _read("scripts/blocked_release_gates_sequence.ps1")
    assert 'if ($AllowUnsigned) { $manualArgs += "-AllowUnsigned" }' in sequence


def test_hardware_workflow_includes_full_and_hidden_clumsy_gates():
    workflow = _read(".github/workflows/hardware-smoketest.yml")

    assert "tests/test_clumsy_full_controls_hardware.py" in workflow
    assert "tests/test_clumsy_hidden_window_hardware.py" in workflow
    assert "DUPEZ_SMOKETEST_FULL_TIMER_SECONDS: '4'" in workflow
    assert "Assert no owned Clumsy process leaked" in workflow
    assert "if: always()" in workflow
    assert "Stop-Process -Id $process.ProcessId -Force" in workflow
    assert "$remainingCount = $remaining.Count" in workflow
    assert "DUPEZ_CLUMSY_PROCESSES_REMAINING" not in workflow
    assert '"--junitxml=$junitPath"' in workflow
    assert "scripts/hardware_evidence.py create" in workflow
    assert "--clumsy-processes-remaining" in workflow
    assert '"$remainingCount"' in workflow
    assert '"$env:DUPEZ_CLUMSY_PROCESSES_REMAINING"' not in workflow
    assert "--clumsy-processes-remaining 0" not in workflow
    assert "hardware-smoketest-evidence.json" in workflow
    assert "if-no-files-found: error" in workflow
    leak_index = workflow.index("Assert no owned Clumsy process leaked")
    evidence_index = workflow.index("Create privacy-safe hardware evidence")
    assert leak_index < evidence_index
    assert "github.event.inputs" not in workflow
    assert "secrets.DUPEZ_SMOKETEST_TARGET_IP" in workflow
    assert "secrets.DUPEZ_SMOKETEST_TARGET_MAC" in workflow
    assert "secrets.DUPEZ_SMOKETEST_CIDR" in workflow
    assert "Tee-Object" not in workflow
    assert "$tests *> $smoketestLog" in workflow
    assert "scripts/redact_hardware_diagnostics.py" in workflow
    assert "id: sanitize_diagnostics" in workflow
    assert "steps.sanitize_diagnostics.outcome == 'success'" in workflow
    assert "/redacted/" in workflow
    assert "retention-days: 7" in workflow
    diagnostics_upload = workflow.index("Upload hardware diagnostics")
    assert "smoketest.log\n" not in workflow[diagnostics_upload:]
    assert "hardware-smoketest.junit.xml\n" not in workflow[diagnostics_upload:]
    assert "logs/**/*.log" not in workflow[diagnostics_upload:]


def test_hardware_workflow_is_main_only_private_and_fail_closed():
    workflow = _read(".github/workflows/hardware-smoketest.yml")

    for token in (
        "name: hardware-smoketest",
        "'${{ github.ref }}' -cne 'refs/heads/main'",
        "'${{ github.workflow_ref }}' -cne $expectedWorkflowRef",
        "ref: ${{ github.sha }}",
        "persist-credentials: false",
        "DUPEZ_FORCE_USER_DATA: '1'",
        "DUPEZ_HARDWARE_DIAGNOSTIC_ROOT",
        "Per-run private hardware workspace already exists",
        "Private hardware diagnostics contain a reparse point",
        "steps.sanitize_diagnostics.outcome == 'success'",
        "Get-CimInstance Win32_Process",
        "-ErrorAction Stop",
        "refusing ambiguous process ownership",
        "Remove-VerifiedRunnerTempTree",
        "requirements-hardware-test-locked.txt",
        "--only-binary=:all: --require-hashes",
        "DUPEZ_SMOKETEST_CIDR is required; refusing an unbounded scan",
    ):
        assert token in workflow, token

    job_prefix = workflow[workflow.index("  hardware-smoketest:") : workflow.index("    steps:")]
    for secret in (
        "DUPEZ_SMOKETEST_CIDR",
        "DUPEZ_SMOKETEST_TARGET_IP",
        "DUPEZ_SMOKETEST_TARGET_MAC",
    ):
        assert secret not in job_prefix

    assert "Format-Table" not in workflow
    assert "Get-CimInstance Win32_Process `\n                  -Filter" in workflow
    assert "-ErrorAction SilentlyContinue |\n                  Where-Object" not in workflow
    assert "network.prefixlen < 24 or target not in network" in workflow
    assert "isinstance(target, ipaddress.IPv4Address)" in workflow


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="PowerShell parser is Windows-only",
)
def test_hardware_workflow_powershell_blocks_parse(tmp_path):
    import yaml

    payload = yaml.load(
        _read(".github/workflows/hardware-smoketest.yml"),
        Loader=yaml.BaseLoader,
    )
    steps = payload["jobs"]["hardware-smoketest"]["steps"]
    blocks = [(step["name"], step["run"]) for step in steps if step.get("shell") == "pwsh" and "run" in step]
    assert blocks

    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    assert powershell.is_file()
    for index, (name, script) in enumerate(blocks):
        script_path = tmp_path / f"hardware-step-{index}.ps1"
        script_path.write_text(script, encoding="utf-8")
        escaped = str(script_path).replace("'", "''")
        command = (
            "$tokens=$null; $errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
            "[ref]$tokens,[ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { "
            "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )
        completed = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
            shell=False,
        )
        assert completed.returncode == 0, f"{name}: {completed.stdout}{completed.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell parser is Windows-only")
@pytest.mark.parametrize(
    "relative",
    (
        "scripts/finalize_release.ps1",
        "scripts/release.ps1",
        "scripts/validate_frozen_runtime.ps1",
        "scripts/record_manual_release_validation.ps1",
        "scripts/stage_release.ps1",
        "scripts/release_git_contract.ps1",
        "scripts/manual_release_gate_contract.ps1",
        "scripts/frozen_runtime_evidence_contract.ps1",
        "scripts/release_gate_launcher.ps1",
        "scripts/lock-requirements.ps1",
        "scripts/blocked_release_gates_sequence.ps1",
    ),
)
def test_release_powershell_scripts_parse_under_windows_powershell(relative):
    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    assert powershell.is_file()
    path = (ROOT / relative).resolve()
    escaped = str(path).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
        "[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
