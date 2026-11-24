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
    [string]$Phase = "status",

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
$statePath = Join-Path $repoRoot "dist\blocked-release-gates-progress.json"
$sequenceScriptPath = Join-Path $PSScriptRoot "blocked_release_gates_sequence.ps1"
if (-not (Test-Path -LiteralPath $sequenceScriptPath -PathType Leaf)) {
    throw "Blocked release gate sequencer is missing: $sequenceScriptPath"
}
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
    $requiredBranch = if ($AllowNonMainValidation -or $Phase -eq "status") {
        ""
    }
    else {
        "main"
    }
    $identity = Get-ReleaseGitIdentity `
        -RepositoryRoot $repoRoot `
        -RequiredBranch $requiredBranch `
        -AllowDirty
    return [ordered]@{
        branch = $identity.Branch
        commit = $identity.Commit
        clean = [bool]$identity.Clean
    }
}

function Enter-ReleaseProgressLock {
    $dir = Split-Path -Parent $statePath
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    try {
        # Keep the file after closing: ownership is the OS handle, not file
        # existence. A terminated process releases it without manual cleanup.
        return [IO.File]::Open(
            "$statePath.lock",
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch {
        throw (
            "Cannot acquire exclusive release progress access. Another " +
            "launcher may be running, or the progress directory is not " +
            "writable. No phase was started: " + $_.Exception.Message
        )
    }
}

if ($Phase -eq "reset") {
    $progressLock = Enter-ReleaseProgressLock
    try {
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            Remove-Item -LiteralPath $statePath -Force
            Write-Host "Reset progress state: $statePath"
        }
        else {
            Write-Host "No state file to reset."
        }
    }
    finally {
        $progressLock.Dispose()
    }
    return
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
            Write-Warning ((
                "Ignoring release progress for " +
                "schema/version/commit/release-mode/validation-policy " +
                "'{0}'/'{1}'/'{2}'/'{3}'/'{4}'; the active release is " +
                "'{5}'/'{6}'/'{7}'/'{8}'/'{9}'. Using fresh in-memory " +
                "state; the file is unchanged until a phase result is recorded."
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
            ))
            return New-DefaultState
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
        Write-Warning (
            "Could not parse $statePath. Using fresh in-memory state; " +
            "the file is unchanged until a phase result is recorded."
        )
        return New-DefaultState
    }
}

function Write-State([hashtable]$state) {
    $state.updated_at_utc = [DateTime]::UtcNow.ToString("o")
    $json = $state | ConvertTo-Json -Depth 6
    $dir = Split-Path -Parent $statePath
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    $temporaryPath = Join-Path $dir (
        ".release-progress-{0}.tmp" -f [Guid]::NewGuid().ToString("N")
    )
    $stream = $null
    try {
        $stream = [IO.File]::Open(
            $temporaryPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        $bytes = [Text.Encoding]::UTF8.GetBytes($json)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $stream.Dispose()
        $stream = $null
        # Publish only complete, flushed JSON on the same volume. Do not
        # fall back to truncating the live checkpoint if replacement fails.
        if ([IO.File]::Exists($statePath)) {
            [IO.File]::Replace($temporaryPath, $statePath, [NullString]::Value)
        }
        else {
            [IO.File]::Move($temporaryPath, $statePath)
        }
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ([IO.File]::Exists($temporaryPath)) {
            [IO.File]::Delete($temporaryPath)
        }
    }
}

function Show-Status([hashtable]$state) {
    Write-Host "`nBlocked release gates status (v$Version):"
    Write-Host "Branch: $($repositoryIdentity.branch)"
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
        # Re-select automatic work after UAC, which can remain pending while
        # another launcher advances progress. Explicit phases stay explicit.
        phase = $(if ($Phase -eq "auto") { "auto" } else { $phaseName })
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
        Write-Host "`nPhase '$phaseName' requires Administrator PowerShell. Relaunching elevated..."
        $encodedCommand = New-ElevatedLauncherEncodedCommand -phaseName $phaseName
        $argList = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", $encodedCommand
        )
        $elevatedProcess = Start-Process `
            -FilePath $inboxWindowsPowerShell `
            -Verb RunAs `
            -ArgumentList $argList `
            -Wait `
            -PassThru
        if ($elevatedProcess.ExitCode -ne 0) {
            throw (
                "Elevated phase '$phaseName' failed with exit code " +
                "$($elevatedProcess.ExitCode)."
            )
        }
        return
    }

    if (-not $needsAdmin -and $isAdmin) {
        throw "Phase '$phaseName' must run in a NON-admin desktop PowerShell session. Open a standard shell and rerun."
    }

    # Only the process doing the work owns the lock; an unelevated parent
    # must never hold it while waiting for its elevated child.
    $progressLock = Enter-ReleaseProgressLock
    try {
        $currentState = Read-State
        foreach ($name in $sequence) {
            if (
                $state.phases.Contains($name) -ne $currentState.phases.Contains($name) -or
                [string]$state.phases[$name] -cne [string]$currentState.phases[$name]
            ) {
                throw (
                    "Release progress changed while selecting a phase. " +
                    "Review -Phase status and retry; no phase was started."
                )
            }
        }
        Assert-PhasePredecessorsDone -phaseName $phaseName -state $currentState
        Invoke-PhaseCommand -phaseName $phaseName -state $currentState
    }
    finally {
        $progressLock.Dispose()
    }
}

function Invoke-PhaseCommand([string]$phaseName, [hashtable]$state) {
    Invalidate-SuccessorDoneStates -phaseName $phaseName -state $state

    Write-Host "`n=== Running $phaseName ==="
    Write-Host "Context note: $($phaseMeta[$phaseName].note)"

    $seqArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $sequenceScriptPath,
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
    $phaseExitCode = $LASTEXITCODE
    if ($phaseExitCode -ne 0) {
        $state.phases[$phaseName] = "FAILED"
        try {
            Write-State -state $state
        }
        catch {
            throw (
                "Phase '$phaseName' failed with exit code $phaseExitCode; " +
                "the FAILED state also could not be persisted: " +
                $_.Exception.Message
            )
        }
        throw "Phase '$phaseName' failed with exit code $phaseExitCode."
    }

    $state.phases[$phaseName] = "DONE"
    try {
        Write-State -state $state
    }
    catch {
        throw (
            "Phase '$phaseName' completed successfully, but its DONE state " +
            "could not be persisted. Verify external effects before " +
            "rerunning the phase: " + $_.Exception.Message
        )
    }
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
    return
}

$selected = $Phase
if ($Phase -eq "auto") {
    $selected = Next-Phase -state $state
    if ($null -eq $selected) {
        Show-Status -state $state
        Write-Host "`nAll blocked release gates are complete."
        return
    }
    if ($selected -eq "admin-stage-publish") {
        Show-Status -state $state
        Write-Host (
            "`nPublication is never automatic. Run again with " +
            "-Phase admin-stage-publish after reviewing the verified draft."
        )
        return
    }
}

Invoke-Phase -phaseName $selected -state $state

$state = Read-State
Show-Status -state $state
$next = Next-Phase -state $state
if ($null -ne $next) {
    Write-Host "`nNext phase: $next"
    if ($next -eq "gpu-validate") {
        Write-Host "Run next from NON-admin desktop PowerShell."
    }
    elseif ($next -eq "admin-stage-publish") {
        Write-Host (
            "Review the verified draft, then run explicit " +
            "-Phase admin-stage-publish. Auto mode will not publish."
        )
    }
    elseif ([bool]$phaseMeta[$next].requiresAdmin) {
        Write-Host "Run next from ADMIN PowerShell (or use -Phase auto and allow elevation)."
    }
}
else {
    Write-Host "`nAll blocked release gates complete."
}
