[CmdletBinding()]
param(
	[ValidatePattern("^\d+\.\d+\.\d+$")]
	[string]$Version = "5.7.9"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Test-IsAdmin {
	return (
		New-Object Security.Principal.WindowsPrincipal(
			[Security.Principal.WindowsIdentity]::GetCurrent()
		)
	).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-MainClean {
	$git = (Get-Command git -ErrorAction Stop).Source
	$branch = (& $git branch --show-current).Trim()
	if ($branch -ne "main") {
		throw "This helper must run from main. Current branch: $branch"
	}
	$statusLines = @(& $git status --porcelain)
	$allowed = "?? scripts/complete_admin_finalize_then_gpu_validate.ps1"
	$blocking = @($statusLines | Where-Object { $_ -ne $allowed })
	if ($blocking.Count -ne 0) {
		& $git status --short
		throw "This helper requires a clean working tree."
	}
}

function Read-GateState([string]$path) {
	if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
		return $null
	}
	return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
}

function Resolve-EnvValue([string]$name) {
	$processValue = [Environment]::GetEnvironmentVariable($name, "Process")
	if (-not [string]::IsNullOrWhiteSpace($processValue)) {
		return $processValue
	}
	$userValue = [Environment]::GetEnvironmentVariable($name, "User")
	if (-not [string]::IsNullOrWhiteSpace($userValue)) {
		return $userValue
	}
	$machineValue = [Environment]::GetEnvironmentVariable($name, "Machine")
	if (-not [string]::IsNullOrWhiteSpace($machineValue)) {
		return $machineValue
	}
	return ""
}

function Write-GateState([string]$path, [pscustomobject]$state) {
	$state.updated_at_utc = [DateTime]::UtcNow.ToString("o")
	$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $path -Encoding UTF8
}

Assert-MainClean

$launcherPath = Join-Path $repoRoot "scripts\release_gate_launcher.ps1"
$finalizePath = Join-Path $repoRoot "scripts\finalize_release.ps1"
$statePath = Join-Path $repoRoot "dist\blocked-release-gates-progress.json"
$logPath = Join-Path $repoRoot "dist\admin-finalize-elevated.log"
$elevatedRunnerPath = Join-Path $repoRoot "dist\run_admin_finalize_elevated.ps1"

$resolvedPrivKeyPath = Resolve-EnvValue -name "DUPEZ_SIGN_PRIVKEY"
if ([string]::IsNullOrWhiteSpace($resolvedPrivKeyPath)) {
	throw "DUPEZ_SIGN_PRIVKEY is not configured in Process/User/Machine environment."
}
if (-not (Test-Path -LiteralPath $resolvedPrivKeyPath -PathType Leaf)) {
	throw "DUPEZ_SIGN_PRIVKEY does not reference an existing file: $resolvedPrivKeyPath"
}
$escapedPrivKeyPath = $resolvedPrivKeyPath.Replace("`"", "``\"")

$elevatedRunner = @"
Set-StrictMode -Version Latest
`$ErrorActionPreference = "Stop"
Set-Location "$repoRoot"
Remove-Item -LiteralPath "$logPath" -Force -ErrorAction SilentlyContinue
Start-Transcript -LiteralPath "$logPath" -Force | Out-Null
try {
	Write-Host "BEGIN elevated admin-finalize run"
	$env:DUPEZ_SIGN_PRIVKEY = "$escapedPrivKeyPath"
	Write-Host "DUPEZ_SIGN_PRIVKEY configured in elevated process."
	powershell -NoProfile -ExecutionPolicy Bypass -File "$finalizePath" -Version $Version -AllowUnsigned *>&1 | Tee-Object -LiteralPath "$logPath" -Append
	`$ec = `$LASTEXITCODE
	Write-Host "END elevated admin-finalize run (exit=`$ec)"
	exit `$ec
}
catch {
	Write-Error `$_
	exit 1
}
finally {
	Stop-Transcript | Out-Null
}
"@

Set-Content -LiteralPath $elevatedRunnerPath -Value $elevatedRunner -Encoding UTF8

Write-Host "Launching elevated admin-finalize..."
try {
	$proc = Start-Process -FilePath "powershell" -Verb RunAs -Wait -PassThru -ArgumentList @(
		"-NoProfile",
		"-ExecutionPolicy", "Bypass",
		"-File", ('"' + $elevatedRunnerPath + '"')
	) -WindowStyle Hidden
}
catch {
	Write-Error "Elevation was canceled or failed to start."
	throw
}
finally {
	Remove-Item -LiteralPath $elevatedRunnerPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Elevated exit code: $($proc.ExitCode)"

if ($proc.ExitCode -eq 0) {
	$stateForWrite = Read-GateState -path $statePath
	if ($null -eq $stateForWrite) {
		$stateForWrite = [pscustomobject]@{
			schema = "dupez.blocked-release-gates-progress.v1"
			version = $Version
			updated_at_utc = [DateTime]::UtcNow.ToString("o")
			phases = [pscustomobject]@{}
		}
	}
	if ($null -eq $stateForWrite.phases) {
		$stateForWrite | Add-Member -NotePropertyName phases -NotePropertyValue ([pscustomobject]@{})
	}
	$existing = $stateForWrite.phases.PSObject.Properties["admin-finalize"]
	if ($null -eq $existing) {
		$stateForWrite.phases | Add-Member -NotePropertyName "admin-finalize" -NotePropertyValue "DONE"
	}
	else {
		$stateForWrite.phases."admin-finalize" = "DONE"
	}
	Write-GateState -path $statePath -state $stateForWrite
}

$state = Read-GateState -path $statePath
$phaseStatus = $null
if ($null -ne $state -and $null -ne $state.phases) {
	$prop = $state.phases.PSObject.Properties["admin-finalize"]
	if ($null -ne $prop) {
		$phaseStatus = [string]$prop.Value
	}
}

if ($phaseStatus -ne "DONE") {
	Write-Host "admin-finalize did not complete successfully."
	if (Test-Path -LiteralPath $logPath -PathType Leaf) {
		Write-Host "\nLast error lines from elevated run:"
		Get-Content -LiteralPath $logPath -Tail 120
	}
	exit 1
}

if (Test-IsAdmin) {
	Write-Host "admin-finalize is DONE, but this shell is elevated."
	Write-Host "Run gpu-validate from a non-admin shell:"
	Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release_gate_launcher.ps1 -Phase auto -Version $Version -AllowUnsigned"
	exit 0
}

Write-Host "admin-finalize is DONE. Advancing to next phase..."
powershell -NoProfile -ExecutionPolicy Bypass -File $launcherPath -Phase auto -Version $Version -AllowUnsigned
exit $LASTEXITCODE
