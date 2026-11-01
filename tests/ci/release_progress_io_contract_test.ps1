#requires -Version 5.1
param([Parameter(Mandatory = $true)][string]$FixtureRoot)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $repositoryRoot "scripts\release_gate_launcher.ps1"),
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) { throw "Launcher parse errors." }
foreach ($name in @(
    "Enter-ReleaseProgressLock", "New-DefaultState", "Read-State",
    "Write-State", "Invoke-Phase"
)) {
    $definitions = @($ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq $name
    }, $true))
    if ($definitions.Count -ne 1) { throw "Expected one $name function." }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}

[IO.Directory]::CreateDirectory($FixtureRoot) | Out-Null
$statePath = Join-Path $FixtureRoot "progress.json"
$stateSchema = "fixture.v1"
$Version = "5.8.0"
$repositoryIdentity = @{ commit = "fixture" }
$releaseMode = "unsigned"
$validationPolicy = "main-only"
$sequence = @("fixture")
$Phase = "fixture"
$phaseMeta = @{ fixture = @{ requiresAdmin = $false } }

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

# Initial publication, replacement and JSON round-trip.
$state = New-DefaultState
Write-State -state $state
$state.phases["fixture"] = "DONE"
Write-State -state $state
$loaded = Read-State
Assert-True ($loaded.phases["fixture"] -ceq "DONE") "Replacement did not round-trip."
$original = [IO.File]::ReadAllText($statePath)

# Windows sharing denies replacement, without damaging the old checkpoint.
$reader = [IO.File]::Open(
    $statePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read
)
$rejected = $false
try {
    $state.phases["fixture"] = "FAILED"
    try { Write-State -state $state } catch { $rejected = $true }
}
finally { $reader.Dispose() }
Assert-True $rejected "Sharing violation did not reject publication."
Assert-True ([IO.File]::ReadAllText($statePath) -ceq $original) "Old checkpoint changed."
Assert-True (@([IO.Directory]::GetFiles($FixtureRoot, ".release-progress-*.tmp")).Count -eq 0) "Stage leaked."

# A second process cannot acquire the handle, and can after normal disposal.
$powershell = Join-Path ([Environment]::GetFolderPath("System")) "WindowsPowerShell\v1.0\powershell.exe"
$escapedLockPath = "$statePath.lock".Replace("'", "''")
$probe = @"
try {
    `$handle = [IO.File]::Open('$escapedLockPath', 'OpenOrCreate', 'ReadWrite', 'None')
    `$handle.Dispose()
    exit 0
} catch { exit 23 }
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($probe))
$lock = Enter-ReleaseProgressLock
try {
    & $powershell -NoProfile -NonInteractive -EncodedCommand $encoded
    Assert-True ($LASTEXITCODE -eq 23) "Another process acquired an owned lock."
}
finally { $lock.Dispose() }
& $powershell -NoProfile -NonInteractive -EncodedCommand $encoded
Assert-True ($LASTEXITCODE -eq 0) "Lock remained held after disposal."
Assert-True ([IO.File]::Exists("$statePath.lock")) "Lock path must not be deleted."

# The real phase orchestrator must own the lock throughout work and release
# it on failures. Only the external side-effecting command is mocked.
function Assert-PhasePredecessorsDone { param($phaseName, $state) }
function Require-OperatorForPhase { param($phaseName) }
function Test-IsAdmin { return $false }
$script:commandCalls = 0
function Invoke-PhaseCommand {
    param($phaseName, $state)
    $script:commandCalls++
    $contender = $null
    $blocked = $false
    try { $contender = Enter-ReleaseProgressLock } catch { $blocked = $true }
    if ($null -ne $contender) { $contender.Dispose() }
    Assert-True $blocked "Phase command did not own exclusive progress access."
    throw "injected phase failure"
}
$state = Read-State
$message = ""
try { Invoke-Phase -phaseName "fixture" -state $state } catch { $message = $_.Exception.Message }
Assert-True ($message -ceq "injected phase failure") "Phase error not propagated: $message"
Assert-True ($script:commandCalls -eq 1) "Phase command was not invoked once."
$lock = Enter-ReleaseProgressLock
$lock.Dispose()

# Selection cannot reuse a checkpoint changed before it acquired ownership.
$stale = New-DefaultState
$message = ""
try { Invoke-Phase -phaseName "fixture" -state $stale } catch { $message = $_.Exception.Message }
Assert-True ($message -like "Release progress changed*") "Stale selection was not rejected."
Assert-True ($script:commandCalls -eq 1) "Stale selection executed a phase."

# Read-only status recovery must not rewrite malformed data.
[IO.File]::WriteAllText($statePath, "invalid-json")
$fresh = Read-State
Assert-True ($fresh.phases.Count -eq 0) "Malformed progress was trusted."
Assert-True ([IO.File]::ReadAllText($statePath) -ceq "invalid-json") "Read-State mutated corrupt data."
Write-Host "Release progress I/O contracts passed."
