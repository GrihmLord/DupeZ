#requires -Version 5.1

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
. (Join-Path $repoRoot "scripts\frozen_runtime_evidence_contract.ps1")

$hash = "a" * 64
$commit = "b" * 40
$fingerprint = "c" * 64
$session = "11111111-1111-4111-8111-111111111111"
$nowUtc = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")

function New-TestEvidence {
    param(
        [ValidateSet("GPU", "Compat")]
        [string]$Variant
    )

    $executable = if ($Variant -ceq "GPU") {
        "DupeZ-GPU.exe"
    }
    else {
        "DupeZ-Compat.exe"
    }
    $administrator = $Variant -ceq "Compat"
    $architecture = if ($administrator) {
        "Architecture: inproc | Admin: True"
    }
    else {
        "Architecture: split | Admin: False"
    }
    $runs = @(
        [pscustomobject][ordered]@{
            variant = $Variant
            profile = "normal"
            cycle = 1
            executable = $executable
            executable_sha256 = $hash
            commit = $commit
            source_state = "clean"
            source_fingerprint = $fingerprint
            validation_session_id = $session
            started_at_utc = $nowUtc
            launched_from_admin = $administrator
            architecture_observed = $architecture
            network_validation_mode = "production-safety-dry-run"
            map_result = "Map: dashboard view active with WebEngine ready"
            webengine_helper_observed = $true
            process_names_observed = @("DupeZ-GPU.exe", "QtWebEngineProcess.exe")
            clean_exit = $true
            exit_code = 0
            crash_files = @()
        },
        [pscustomobject][ordered]@{
            variant = $Variant
            profile = "forced-low-resource"
            cycle = 1
            executable = $executable
            executable_sha256 = $hash
            commit = $commit
            source_state = "clean"
            source_fingerprint = $fingerprint
            validation_session_id = $session
            started_at_utc = $nowUtc
            launched_from_admin = $administrator
            architecture_observed = $architecture
            network_validation_mode = "production-safety-dry-run"
            map_result = "Map: dashboard view active with WebEngine ready"
            webengine_helper_observed = $true
            process_names_observed = @("DupeZ-GPU.exe", "QtWebEngineProcess.exe")
            clean_exit = $true
            exit_code = 0
            crash_files = @()
        }
    )
    return [pscustomobject][ordered]@{
        schema = "dupez.frozen-runtime-validation.v3"
        variant = $Variant
        executable = $executable
        executable_sha256 = $hash
        commit = $commit
        source_state = "clean"
        source_fingerprint = $fingerprint
        validation_session_id = $session
        generated_at_utc = $nowUtc
        cycles_per_profile = 1
        network_validation_mode = "production-safety-dry-run"
        validation_host = [pscustomobject]@{
            administrator = $administrator
            python = "3.13.17"
        }
        runs = $runs
    }
}

function Copy-TestEvidence {
    param([object]$Evidence)
    return $Evidence | ConvertTo-Json -Depth 10 | ConvertFrom-Json
}

function Invoke-Contract {
    param(
        [object]$Evidence,
        [ValidateSet("GPU", "Compat")]
        [string]$Variant
    )
    $executable = if ($Variant -ceq "GPU") {
        "DupeZ-GPU.exe"
    }
    else {
        "DupeZ-Compat.exe"
    }
    Assert-FrozenRuntimeEvidenceContract `
        -Evidence $Evidence `
        -ExpectedVariant $Variant `
        -ExpectedExecutable $executable `
        -ExpectedHash $hash `
        -ExpectedCommit $commit
}

function Assert-Rejected {
    param(
        [object]$Evidence,
        [ValidateSet("GPU", "Compat")]
        [string]$Variant,
        [string]$Case
    )
    $accepted = $false
    try {
        Invoke-Contract -Evidence $Evidence -Variant $Variant
        $accepted = $true
    }
    catch {
        # Rejection is the expected result. Do not print evidence or host data.
    }
    if ($accepted) {
        throw "Frozen evidence contract accepted invalid case: $Case"
    }
}

foreach ($variant in @("GPU", "Compat")) {
    $valid = New-TestEvidence -Variant $variant
    Invoke-Contract -Evidence $valid -Variant $variant

    $mutations = @(
        @{ Name = "top executable"; Apply = { param($e) $e.executable = "other.exe" } },
        @{ Name = "top hash"; Apply = { param($e) $e.executable_sha256 = "d" * 64 } },
        @{ Name = "top commit"; Apply = { param($e) $e.commit = "e" * 40 } },
        @{ Name = "top source state"; Apply = { param($e) $e.source_state = "dirty" } },
        @{ Name = "top fingerprint"; Apply = { param($e) $e.source_fingerprint = "C" * 64 } },
        @{ Name = "top session"; Apply = { param($e) $e.validation_session_id = "not-a-session" } },
        @{ Name = "stale evidence"; Apply = { param($e) $e.generated_at_utc = "2000-01-01T00:00:00Z" } },
        @{ Name = "zero cycles"; Apply = { param($e) $e.cycles_per_profile = 0 } },
        @{ Name = "string cycles"; Apply = { param($e) $e.cycles_per_profile = "1" } },
        @{ Name = "top administrator"; Apply = { param($e) $e.validation_host.administrator = -not [bool]$e.validation_host.administrator } },
        @{ Name = "top network mode"; Apply = { param($e) $e.network_validation_mode = "privileged" } },
        @{ Name = "run variant"; Apply = { param($e) $e.runs[0].variant = "Other" } },
        @{ Name = "run executable"; Apply = { param($e) $e.runs[0].executable = "other.exe" } },
        @{ Name = "run hash"; Apply = { param($e) $e.runs[0].executable_sha256 = "d" * 64 } },
        @{ Name = "run commit"; Apply = { param($e) $e.runs[0].commit = "e" * 40 } },
        @{ Name = "run source state"; Apply = { param($e) $e.runs[0].source_state = "dirty" } },
        @{ Name = "run fingerprint"; Apply = { param($e) $e.runs[0].source_fingerprint = "d" * 64 } },
        @{ Name = "run session"; Apply = { param($e) $e.runs[0].validation_session_id = "22222222-2222-4222-8222-222222222222" } },
        @{ Name = "run time"; Apply = { param($e) $e.runs[0].started_at_utc = "2000-01-01T00:00:00Z" } },
        @{ Name = "run administrator"; Apply = { param($e) $e.runs[0].launched_from_admin = -not [bool]$e.runs[0].launched_from_admin } },
        @{ Name = "run administrator string"; Apply = { param($e) $e.runs[0].launched_from_admin = "False" } },
        @{ Name = "run network mode"; Apply = { param($e) $e.runs[0].network_validation_mode = "privileged" } },
        @{ Name = "missing WebEngine helper boolean"; Apply = { param($e) $e.runs[0].webengine_helper_observed = $false } },
        @{ Name = "missing WebEngine helper process"; Apply = { param($e) $e.runs[0].process_names_observed = @("DupeZ-GPU.exe") } },
        @{ Name = "duplicate profile cycle"; Apply = { param($e) $e.runs[1].profile = "normal" } },
        @{ Name = "unexpected cycle"; Apply = { param($e) $e.runs[1].cycle = 2 } },
        @{ Name = "string cycle"; Apply = { param($e) $e.runs[1].cycle = "1" } },
        @{ Name = "missing run"; Apply = { param($e) $e.runs = @($e.runs[0]) } },
        @{ Name = "extra run"; Apply = { param($e) $e.runs = @($e.runs) + @(Copy-TestEvidence $e.runs[0]) } }
    )
    foreach ($mutation in $mutations) {
        $candidate = Copy-TestEvidence $valid
        & $mutation.Apply $candidate
        Assert-Rejected `
            -Evidence $candidate `
            -Variant $variant `
            -Case ([string]$mutation.Name)
    }

    $twoCycles = Copy-TestEvidence $valid
    $twoCycles.cycles_per_profile = 2
    $normalCycleTwo = Copy-TestEvidence $twoCycles.runs[0]
    $normalCycleTwo.cycle = 2
    $lowCycleTwo = Copy-TestEvidence $twoCycles.runs[1]
    $lowCycleTwo.cycle = 2
    $twoCycles.runs = @($twoCycles.runs) + @($normalCycleTwo, $lowCycleTwo)
    Invoke-Contract -Evidence $twoCycles -Variant $variant
}

Write-Output "Frozen runtime evidence consumer contract: PASS"
