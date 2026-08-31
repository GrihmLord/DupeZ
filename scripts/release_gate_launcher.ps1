#requires -Version 5.1
<#
Interactive/auto launcher for blocked release gates.

Purpose:
- Walk the blocked release gates in strict order.
- Persist progress to dist/blocked-release-gates-progress.json.
- Auto-elevate admin-required phases.
- Prompt for non-admin context where required (GPU validation).
#>

[CmdletBinding()]
param(
    [ValidateSet("auto", "admin-finalize", "gpu-validate", "admin-compat", "admin-stage-draft", "admin-stage-publish", "status", "reset")]
    [string]$Phase = "auto",

    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.8.0",

    [ValidateLength(0, 80)]
    [ValidatePattern('^$|^[\p{L}\p{M}\p{N}][\p{L}\p{M}\p{N} ._-]{0,79}$')]
    [string]$Operator = "",

    [switch]$AllowUnsigned,

    [switch]$AllowNonMainValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "release_git_contract.ps1")

function Resolve-InboxWindowsPowerShell {
    $systemDirectory = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::System
    )
    if (
        [string]::IsNullOrWhiteSpace($systemDirectory) -or
        -not [IO.Path]::IsPathRooted($systemDirectory)
    ) {
        throw "Could not resolve the absolute Windows system directory."
    }

    $candidate = [IO.Path]::GetFullPath((
        Join-Path $systemDirectory "WindowsPowerShell\v1.0\powershell.exe"
    ))
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Inbox Windows PowerShell executable is missing."
    }

    $resolved = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
    if (
        -not [IO.Path]::IsPathRooted($resolved) -or
        -not [string]::Equals(
            $resolved,
            $candidate,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Inbox Windows PowerShell executable resolved unexpectedly."
    }
    return $resolved
}

$inboxWindowsPowerShell = Resolve-InboxWindowsPowerShell

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$statePath = Join-Path $repoRoot "dist\blocked-release-gates-progress.json"
$stateSchema = "dupez.blocked-release-gates-progress.v3"
$releaseMode = if ($AllowUnsigned) { "unsigned" } else { "authenticode" }
$validationPolicy = if ($AllowNonMainValidation) {
    "allow-non-main"
}
else {
    "main-only"
}
$sequence = @(
    "admin-finalize",
    "gpu-validate",
    "admin-compat",
    "admin-stage-draft",
    "admin-stage-publish"
)

$phaseMeta = @{
    "admin-finalize" = @{ requiresAdmin = $true;  note = "Finalize + dist/signing gates" }
    "gpu-validate" = @{ requiresAdmin = $false; note = "GPU frozen runtime validation (must be non-admin)" }
    "admin-compat" = @{ requiresAdmin = $true;  note = "Compat validation + manual validation record" }
    "admin-stage-draft" = @{ requiresAdmin = $true;  note = "Stage draft release" }
    "admin-stage-publish" = @{ requiresAdmin = $true;  note = "Publish staged release" }
}

function Test-IsAdmin {
    return (
        New-Object Security.Principal.WindowsPrincipal(
            [Security.Principal.WindowsIdentity]::GetCurrent()
        )
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RepositoryIdentity {
    $identity = Get-ReleaseGitIdentity `
        -RepositoryRoot $repoRoot `
        -RequiredBranch "main" `
        -AllowDirty
    return [ordered]@{
        commit = $identity.Commit
        clean = [bool]$identity.Clean
    }
}

$repositoryIdentity = Get-RepositoryIdentity

function New-DefaultState {
    return [ordered]@{
        schema = $stateSchema
        version = $Version
        commit = $repositoryIdentity.commit
        release_mode = $releaseMode
        validation_policy = $validationPolicy
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
        phases = [ordered]@{}
    }
}

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return New-DefaultState
    }
    try {
        $raw = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if (
            [string]$raw.schema -ne $stateSchema -or
            [string]$raw.version -ne $Version -or
            [string]$raw.commit -ne $repositoryIdentity.commit -or
            [string]$raw.release_mode -ne $releaseMode -or
            [string]$raw.validation_policy -ne $validationPolicy
        ) {
            Write-Warning (
                "Ignoring release progress for " +
                "schema/version/commit/release-mode/validation-policy " +
                "'{0}'/'{1}'/'{2}'/'{3}'/'{4}'; the active release is " +
                "'{5}'/'{6}'/'{7}'/'{8}'/'{9}'. " +
                "Reinitializing progress state."
            ) -f (
                $raw.schema,
                $raw.version,
                $raw.commit,
                $raw.release_mode,
                $raw.validation_policy,
                $stateSchema,
                $Version,
                $repositoryIdentity.commit,
                $releaseMode,
                $validationPolicy
            )
            $default = New-DefaultState
            Write-State -state $default
            return $default
        }
        $h = [ordered]@{
            schema = [string]$raw.schema
            version = [string]$raw.version
            commit = [string]$raw.commit
            release_mode = [string]$raw.release_mode
            validation_policy = [string]$raw.validation_policy
            updated_at_utc = [string]$raw.updated_at_utc
            phases = [ordered]@{}
        }
        foreach ($name in $sequence) {
            $prop = $null
            if ($null -ne $raw.phases) {
                $prop = $raw.phases.PSObject.Properties[$name]
            }
            if ($null -ne $prop -and $null -ne $prop.Value) {
                $h.phases[$name] = [string]$prop.Value
            }
        }
        return $h
    }
    catch {
        Write-Warning "Could not parse $statePath. Reinitializing progress state."
        $default = New-DefaultState
        Write-State -state $default
        return $default
    }
}

function Write-State([hashtable]$state) {
    $state.updated_at_utc = [DateTime]::UtcNow.ToString("o")
    $json = $state | ConvertTo-Json -Depth 6
    $dir = Split-Path -Parent $statePath
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    Set-Content -LiteralPath $statePath -Value $json -Encoding UTF8
}

function Show-Status([hashtable]$state) {
    Write-Host "\nBlocked release gates status (v$Version):"
    Write-Host "Commit: $($state.commit)"
    Write-Host "Release mode: $($state.release_mode)"
    Write-Host "Validation policy: $($state.validation_policy)"
    Write-Host "Working tree clean: $($repositoryIdentity.clean)"
    if (-not $repositoryIdentity.clean) {
        Write-Warning (
            "Release progress cannot be resumed until the working tree is clean."
        )
    }
    foreach ($name in $sequence) {
        $status = if ($state.phases.Contains($name)) { $state.phases[$name] } else { "PENDING" }
        Write-Host ("- {0}: {1}" -f $name, $status)
    }
    Write-Host "State file: $statePath"
}

function Next-Phase([hashtable]$state) {
    foreach ($name in $sequence) {
        $status = if ($state.phases.Contains($name)) { $state.phases[$name] } else { "PENDING" }
        if ($status -ne "DONE") {
            return $name
        }
    }
    return $null
}

function Get-PhaseIndex([string]$phaseName) {
    for ($index = 0; $index -lt $sequence.Count; $index++) {
        if ($sequence[$index] -eq $phaseName) {
            return $index
        }
    }
    return -1
}

function Assert-PhasePredecessorsDone(
    [string]$phaseName,
    [hashtable]$state
) {
    $phaseIndex = Get-PhaseIndex -phaseName $phaseName
    if ($phaseIndex -lt 0) {
        throw "Unknown phase: $phaseName"
    }

    for ($index = 0; $index -lt $phaseIndex; $index++) {
        $predecessor = $sequence[$index]
        $status = if ($state.phases.Contains($predecessor)) {
            [string]$state.phases[$predecessor]
        }
        else {
            "PENDING"
        }
        if ($status -ne "DONE") {
            throw (
                "Phase '$phaseName' requires predecessor '$predecessor' " +
                "status=DONE; found status=$status."
            )
        }
    }
}

function Invalidate-SuccessorDoneStates(
    [string]$phaseName,
    [hashtable]$state
) {
    $phaseIndex = Get-PhaseIndex -phaseName $phaseName
    if ($phaseIndex -lt 0) {
        throw "Unknown phase: $phaseName"
    }

    $changed = $false
    for ($index = $phaseIndex + 1; $index -lt $sequence.Count; $index++) {
        $successor = $sequence[$index]
        if (
            $state.phases.Contains($successor) -and
            [string]$state.phases[$successor] -eq "DONE"
        ) {
            $state.phases[$successor] = "PENDING"
            $changed = $true
            Write-Host (
                "Invalidated successor phase '$successor' because " +
                "'$phaseName' is being rerun."
            )
        }
    }
    if ($changed) {
        Write-State -state $state
    }
}

function Require-OperatorForPhase([string]$phaseName) {
    if ($phaseName -eq "admin-compat" -and [string]::IsNullOrWhiteSpace($Operator)) {
        throw "admin-compat requires -Operator <name> for manual validation record."
    }
}

function New-ElevatedLauncherEncodedCommand([string]$phaseName) {
    $launcherPath = (Resolve-Path -LiteralPath $PSCommandPath).Path
    $payload = [ordered]@{
        script_path = $launcherPath
        phase = $phaseName
        version = $Version
        operator = $Operator
        allow_unsigned = [bool]$AllowUnsigned
        allow_non_main_validation = [bool]$AllowNonMainValidation
    }
    $payloadJson = $payload | ConvertTo-Json -Compress
    $payloadToken = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($payloadJson)
    )
    $bootstrap = @'
$ErrorActionPreference = "Stop"
$payloadJson = [Text.Encoding]::UTF8.GetString(
    [Convert]::FromBase64String("__DUPEZ_RELEASE_PAYLOAD__")
)
$payload = $payloadJson | ConvertFrom-Json
$launcherArguments = @{
    Phase = [string]$payload.phase
    Version = [string]$payload.version
}
if (-not [string]::IsNullOrWhiteSpace([string]$payload.operator)) {
    $launcherArguments.Operator = [string]$payload.operator
}
if ([bool]$payload.allow_unsigned) {
    $launcherArguments.AllowUnsigned = $true
}
if ([bool]$payload.allow_non_main_validation) {
    $launcherArguments.AllowNonMainValidation = $true
}
try {
    & ([string]$payload.script_path) @launcherArguments
}
catch {
    Write-Error $_
    exit 1
}
'@
    $bootstrap = $bootstrap.Replace(
        "__DUPEZ_RELEASE_PAYLOAD__",
        $payloadToken
    )
    return [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($bootstrap)
    )
}

function Invoke-Phase([string]$phaseName, [hashtable]$state) {
    if (-not $phaseMeta.ContainsKey($phaseName)) {
        throw "Unknown phase: $phaseName"
    }

    Assert-PhasePredecessorsDone -phaseName $phaseName -state $state
    Require-OperatorForPhase -phaseName $phaseName

    $isAdmin = Test-IsAdmin
    $needsAdmin = [bool]$phaseMeta[$phaseName].requiresAdmin

    if ($needsAdmin -and -not $isAdmin) {
        Write-Host "\nPhase '$phaseName' requires Administrator PowerShell. Relaunching elevated..."
        $encodedCommand = New-ElevatedLauncherEncodedCommand -phaseName $phaseName
        $argList = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", $encodedCommand
        )
        Start-Process `
            -FilePath $inboxWindowsPowerShell `
            -Verb RunAs `
            -ArgumentList $argList
        return "RELAUNCHED_ELEVATED"
    }

    if (-not $needsAdmin -and $isAdmin) {
        throw "Phase '$phaseName' must run in a NON-admin desktop PowerShell session. Open a standard shell and rerun."
    }

    Invalidate-SuccessorDoneStates -phaseName $phaseName -state $state

    Write-Host "\n=== Running $phaseName ==="
    Write-Host "Context note: $($phaseMeta[$phaseName].note)"

    $seqArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "scripts/blocked_release_gates_sequence.ps1",
        "-Phase", $phaseName,
        "-Version", $Version
    )
    if (-not [string]::IsNullOrWhiteSpace($Operator)) {
        $seqArgs += @("-Operator", $Operator)
    }
    if ($AllowUnsigned) {
        $seqArgs += "-AllowUnsigned"
    }
    if ($AllowNonMainValidation) {
        $seqArgs += "-AllowNonMainValidation"
    }

    & $inboxWindowsPowerShell @seqArgs
    if ($LASTEXITCODE -ne 0) {
        $state.phases[$phaseName] = "FAILED"
        Write-State -state $state
        throw "Phase '$phaseName' failed with exit code $LASTEXITCODE."
    }

    $state.phases[$phaseName] = "DONE"
    Write-State -state $state
    return "DONE"
}

if ($Phase -eq "reset") {
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Remove-Item -LiteralPath $statePath -Force
        Write-Host "Reset progress state: $statePath"
    }
    else {
        Write-Host "No state file to reset."
    }
    exit 0
}

if (
    -not $repositoryIdentity.clean -and
    $Phase -ne "status"
) {
    throw (
        "Refusing to resume release progress from a dirty working tree. " +
        "Commit the reviewed source and restart from the exact clean HEAD."
    )
}

$state = Read-State

if ($Phase -eq "status") {
    Show-Status -state $state
    exit 0
}

$selected = $Phase
if ($Phase -eq "auto") {
    $selected = Next-Phase -state $state
    if ($null -eq $selected) {
        Show-Status -state $state
        Write-Host "\nAll blocked release gates are complete."
        exit 0
    }
}

$result = Invoke-Phase -phaseName $selected -state $state
if ($result -eq "RELAUNCHED_ELEVATED") {
    Write-Host "Elevated window launched for '$selected'. After it completes, rerun this launcher."
    exit 0
}

$state = Read-State
Show-Status -state $state
$next = Next-Phase -state $state
if ($null -ne $next) {
    Write-Host "\nNext phase: $next"
    if ($next -eq "gpu-validate") {
        Write-Host "Run next from NON-admin desktop PowerShell."
    }
    elseif ([bool]$phaseMeta[$next].requiresAdmin) {
        Write-Host "Run next from ADMIN PowerShell (or use -Phase auto and allow elevation)."
    }
}
else {
    Write-Host "\nAll blocked release gates complete."
}
