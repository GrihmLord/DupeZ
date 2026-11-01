#requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
. (Join-Path $repoRoot "scripts\manual_release_gate_contract.ps1")
$testRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("dupez-manual-gate-contract-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $testRoot | Out-Null
try {
    $recorderPath = Join-Path $testRoot "recorder.ps1"
    $lines = @('$gateDescriptions = [ordered]@{')
    foreach ($number in 1..16) {
        $lines += ("    gate{0:d2} = 'fixture'" -f $number)
    }
    $lines += '}'
    Set-Content -LiteralPath $recorderPath -Encoding UTF8 -Value $lines

    $exact = [ordered]@{}
    foreach ($number in 1..16) {
        $exact[("gate{0:d2}" -f $number)] = $true
    }
    $result = @(
        Assert-ExactManualReleaseGates `
            -Gates ([pscustomobject]$exact) `
            -RecorderPath $recorderPath
    )
    if ($result.Count -ne 16) {
        throw "Exact gate contract did not return 16 gates."
    }

    foreach ($mutation in @("extra", "missing", "nonboolean")) {
        $candidate = [ordered]@{}
        foreach ($entry in $exact.GetEnumerator()) {
            $candidate[$entry.Key] = $entry.Value
        }
        if ($mutation -eq "extra") { $candidate["attacker_extra"] = $true }
        if ($mutation -eq "missing") { $candidate.Remove("gate16") }
        if ($mutation -eq "nonboolean") { $candidate["gate16"] = "true" }
        $rejected = $false
        try {
            Assert-ExactManualReleaseGates `
                -Gates ([pscustomobject]$candidate) `
                -RecorderPath $recorderPath | Out-Null
        }
        catch {
            $rejected = $true
        }
        if (-not $rejected) {
            throw "Manual gate contract accepted $mutation evidence."
        }
    }
}
finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "PASS: manual release gate contract is exact and boolean."
