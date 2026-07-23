#requires -Version 5.1
<#
.SYNOPSIS
Exercise a built DupeZ frozen variant through its real Windows GUI lifecycle.

.DESCRIPTION
GPU must run from a standard desktop PowerShell session so its GUI remains at
Medium Integrity and its helper owns elevation. Compat must run from an
Administrator PowerShell session because it intentionally uses the in-process
packet-engine architecture.

For the selected variant this script runs both normal and forced-low-resource
profiles, waits for the real dashboard, opens the Map through DupeZ's Ctrl+2
shortcut, exits through DupeZ's Ctrl+Q force-quit action, checks helper/child
cleanup, rejects crash dumps, and writes hash-bound JSON evidence to dist/.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("GPU", "Compat")]
    [string]$Variant,

    [string]$DistDirectory = "dist",

    [ValidateRange(1, 5)]
    [int]$CyclesPerProfile = 1,

    [ValidateRange(30, 300)]
    [int]$StartupTimeoutSeconds = 150,

    [ValidateRange(15, 180)]
    [int]$MapTimeoutSeconds = 60,

    [ValidateRange(10, 120)]
    [int]$ShutdownTimeoutSeconds = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot
$distRoot = (Resolve-Path -LiteralPath $DistDirectory).Path

$isAdmin = (
    New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($Variant -eq "GPU" -and $isAdmin) {
    throw (
        "GPU validation must run from a standard, non-Administrator desktop " +
        "PowerShell session so the split GUI remains Medium Integrity."
    )
}
if ($Variant -eq "Compat" -and -not $isAdmin) {
    throw "Compat validation must run from Administrator PowerShell."
}

$exeName = if ($Variant -eq "GPU") {
    "DupeZ-GPU.exe"
}
else {
    "DupeZ-Compat.exe"
}
$exePath = Join-Path $distRoot $exeName
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "Frozen executable missing: $exePath"
}
$exePath = (Resolve-Path -LiteralPath $exePath).Path

if (-not ("DupeZ.ReleaseWindowApi" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

namespace DupeZ {
    public static class ReleaseWindowApi {
        public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hwnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowTextW(IntPtr hwnd, StringBuilder text, int count);

        [DllImport("user32.dll")]
        private static extern int GetWindowTextLengthW(IntPtr hwnd);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hwnd);

        [DllImport("user32.dll")]
        private static extern bool PostMessageW(IntPtr hwnd, uint message, UIntPtr wParam, IntPtr lParam);

        private const uint WM_KEYDOWN = 0x0100;
        private const uint WM_KEYUP = 0x0101;
        private const uint VK_CONTROL = 0x11;

        public static IntPtr FindDashboard(uint processId) {
            IntPtr found = IntPtr.Zero;
            EnumWindows(delegate (IntPtr hwnd, IntPtr lParam) {
                uint owner;
                GetWindowThreadProcessId(hwnd, out owner);
                if (owner != processId || !IsWindowVisible(hwnd)) {
                    return true;
                }
                int length = GetWindowTextLengthW(hwnd);
                StringBuilder title = new StringBuilder(Math.Max(length + 1, 64));
                GetWindowTextW(hwnd, title, title.Capacity);
                string value = title.ToString();
                if (value.IndexOf("DupeZ v", StringComparison.OrdinalIgnoreCase) >= 0) {
                    found = hwnd;
                    return false;
                }
                return true;
            }, IntPtr.Zero);
            return found;
        }

        public static bool SendCtrlKey(IntPtr hwnd, uint virtualKey) {
            if (hwnd == IntPtr.Zero) return false;
            SetForegroundWindow(hwnd);
            bool ok = true;
            ok &= PostMessageW(hwnd, WM_KEYDOWN, new UIntPtr(VK_CONTROL), IntPtr.Zero);
            ok &= PostMessageW(hwnd, WM_KEYDOWN, new UIntPtr(virtualKey), IntPtr.Zero);
            ok &= PostMessageW(hwnd, WM_KEYUP, new UIntPtr(virtualKey), IntPtr.Zero);
            ok &= PostMessageW(hwnd, WM_KEYUP, new UIntPtr(VK_CONTROL), IntPtr.Zero);
            return ok;
        }
    }
}
"@
}

function Get-LogText {
    param([string]$RuntimeRoot)

    $logRoot = Join-Path $RuntimeRoot "DupeZ\logs"
    if (-not (Test-Path -LiteralPath $logRoot -PathType Container)) {
        return ""
    }
    $parts = @()
    foreach ($file in @(
        Get-ChildItem -LiteralPath $logRoot -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc
    )) {
        try {
            $parts += Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop
        }
        catch {
            continue
        }
    }
    return ($parts -join "`n")
}

function Wait-ForLogPattern {
    param(
        [string]$RuntimeRoot,
        [string[]]$Patterns,
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $text = Get-LogText -RuntimeRoot $RuntimeRoot
        foreach ($pattern in $Patterns) {
            if ($text.Contains($pattern)) {
                return [ordered]@{
                    matched = $pattern
                    text = $text
                }
            }
        }
        Start-Sleep -Milliseconds 250
    }
    return [ordered]@{
        matched = $null
        text = Get-LogText -RuntimeRoot $RuntimeRoot
    }
}

function Get-DescendantProcessIds {
    param([int]$RootPid)

    $all = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine
    )
    $known = New-Object System.Collections.Generic.HashSet[int]
    [void]$known.Add($RootPid)
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($process in $all) {
            if (
                $known.Contains([int]$process.ParentProcessId) -and
                -not $known.Contains([int]$process.ProcessId)
            ) {
                [void]$known.Add([int]$process.ProcessId)
                $changed = $true
            }
        }
    }
    return @(
        $all | Where-Object {
            $_.ProcessId -ne $RootPid -and
            $known.Contains([int]$_.ProcessId)
        }
    )
}

function Assert-NoFrozenProcesses {
    $names = @("DupeZ-GPU.exe", "DupeZ-Compat.exe", "dupez.exe")
    $running = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -in $names -and
                $_.ExecutablePath -and
                $_.ExecutablePath.StartsWith(
                    $distRoot,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            }
    )
    if ($running.Count -gt 0) {
        $running |
            Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine |
            Format-Table -AutoSize
        throw "A DupeZ frozen process from the dist directory is already running."
    }
}

function Write-Acknowledgement {
    param([string]$RuntimeRoot)

    $dupezRoot = Join-Path $RuntimeRoot "DupeZ"
    New-Item -ItemType Directory -Path $dupezRoot -Force | Out-Null
    $payload = [ordered]@{
        schema = "dupez.operator-acknowledgement.v1"
        policy_version = 1
        acknowledged = $true
        acknowledged_at = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    }
    $payload | ConvertTo-Json -Compress |
        Set-Content -LiteralPath (Join-Path $dupezRoot "operator-acknowledgement.json") -Encoding UTF8
}

$profiles = @(
    [ordered]@{
        name = "normal"
        environment = [ordered]@{
            DUPEZ_LOW_RESOURCE = "0"
            DUPEZ_MAP_PREWARM = "1"
            DUPEZ_STARTUP_TIMEOUT_MS = "180000"
        }
    },
    [ordered]@{
        name = "forced-low-resource"
        environment = [ordered]@{
            DUPEZ_LOW_RESOURCE = "1"
            DUPEZ_MAP_PREWARM = "0"
            DUPEZ_QT_MAX_THREADS = "2"
            DUPEZ_STARTUP_TIMEOUT_MS = "240000"
        }
    }
)

$commit = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $commit) {
    throw "Could not resolve the source commit."
}
$executableHash = (
    Get-FileHash -LiteralPath $exePath -Algorithm SHA256
).Hash.ToLowerInvariant()
$records = @()

Assert-NoFrozenProcesses

foreach ($profile in $profiles) {
    for ($cycle = 1; $cycle -le $CyclesPerProfile; $cycle++) {
        $runId = "{0}-{1}-{2}-{3}" -f (
            $Variant.ToLowerInvariant(),
            $profile.name,
            $cycle,
            [DateTime]::UtcNow.ToString("yyyyMMddHHmmssfff")
        )
        $runtimeRoot = Join-Path $env:TEMP "dupez-release-smoke\$runId"
        Remove-Item -LiteralPath $runtimeRoot -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
        Write-Acknowledgement -RuntimeRoot $runtimeRoot

        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $exePath
        $psi.WorkingDirectory = $distRoot
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $false
        $psi.EnvironmentVariables["LOCALAPPDATA"] = $runtimeRoot
        $psi.EnvironmentVariables["APPDATA"] = $runtimeRoot
        $psi.EnvironmentVariables["TEMP"] = (Join-Path $runtimeRoot "temp")
        $psi.EnvironmentVariables["TMP"] = (Join-Path $runtimeRoot "temp")
        $psi.EnvironmentVariables["DUPEZ_RELEASE_VALIDATION"] = "1"
        foreach ($key in $profile.environment.Keys) {
            $psi.EnvironmentVariables[$key] = [string]$profile.environment[$key]
        }
        New-Item -ItemType Directory -Path $psi.EnvironmentVariables["TEMP"] -Force | Out-Null

        Write-Host "`n=== $Variant / $($profile.name) / cycle $cycle ==="
        $startedUtc = [DateTime]::UtcNow
        $process = [System.Diagnostics.Process]::Start($psi)
        if ($null -eq $process) {
            throw "Failed to start $exeName."
        }

        $dashboard = [IntPtr]::Zero
        $startupDeadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
        while ([DateTime]::UtcNow -lt $startupDeadline) {
            if ($process.HasExited) {
                throw "$exeName exited before dashboard creation with code $($process.ExitCode)."
            }
            $dashboard = [DupeZ.ReleaseWindowApi]::FindDashboard([uint32]$process.Id)
            if ($dashboard -ne [IntPtr]::Zero) {
                break
            }
            Start-Sleep -Milliseconds 200
            $process.Refresh()
        }
        if ($dashboard -eq [IntPtr]::Zero) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
            throw "$exeName did not create its dashboard within $StartupTimeoutSeconds seconds."
        }

        $startupLog = Wait-ForLogPattern `
            -RuntimeRoot $runtimeRoot `
            -Patterns @("DupeZ started successfully") `
            -TimeoutSeconds 20
        if (-not $startupLog.matched) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
            throw "Dashboard appeared but the successful-start log was not observed."
        }

        $process.Refresh()
        $descendants = @(Get-DescendantProcessIds -RootPid $process.Id)
        $startupDurationMs = [int](
            ([DateTime]::UtcNow - $startedUtc).TotalMilliseconds
        )

        if (-not [DupeZ.ReleaseWindowApi]::SendCtrlKey($dashboard, 0x32)) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
            throw "Could not send Ctrl+2 to the exact DupeZ dashboard HWND."
        }

        $mapPatterns = if ($profile.name -eq "forced-low-resource") {
            @(
                "Map: lazy DayZMapGUI initialized on first tab open",
                "Lazy map initialization failed"
            )
        }
        else {
            @(
                "Map: prewarmed DayZMapGUI after controller startup",
                "Map: lazy DayZMapGUI initialized on first tab open",
                "Lazy map initialization failed"
            )
        }
        $mapLog = Wait-ForLogPattern `
            -RuntimeRoot $runtimeRoot `
            -Patterns $mapPatterns `
            -TimeoutSeconds $MapTimeoutSeconds
        if (-not $mapLog.matched) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
            throw "No map initialization result was observed."
        }
        if ($mapLog.matched -eq "Lazy map initialization failed") {
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
            throw "The real frozen Map failed to initialize; inspect $runtimeRoot."
        }

        if (-not [DupeZ.ReleaseWindowApi]::SendCtrlKey($dashboard, 0x51)) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
            throw "Could not send Ctrl+Q to the exact DupeZ dashboard HWND."
        }

        if (-not $process.WaitForExit($ShutdownTimeoutSeconds * 1000)) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
            throw "$exeName did not complete its normal force-quit path in time."
        }
        if ($process.ExitCode -ne 0) {
            throw "$exeName exited with code $($process.ExitCode)."
        }

        $childDeadline = [DateTime]::UtcNow.AddSeconds(15)
        $leakedChildren = @()
        do {
            $leakedChildren = @(
                foreach ($child in $descendants) {
                    if (Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue) {
                        $child
                    }
                }
            )
            if ($leakedChildren.Count -eq 0) {
                break
            }
            Start-Sleep -Milliseconds 250
        } while ([DateTime]::UtcNow -lt $childDeadline)
        if ($leakedChildren.Count -gt 0) {
            $leakedChildren |
                Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine |
                Format-Table -AutoSize
            throw "Frozen shutdown leaked one or more child/helper processes."
        }

        $crashes = @(
            Get-ChildItem -LiteralPath $runtimeRoot -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -in @("FATAL_CRASH.txt", "DupeZ.dmp") }
        )
        if ($crashes.Count -gt 0) {
            throw "Frozen run produced crash evidence under $runtimeRoot."
        }

        $records += [ordered]@{
            variant = $Variant
            profile = $profile.name
            cycle = $cycle
            executable = $exeName
            executable_sha256 = $executableHash
            commit = $commit
            started_at_utc = $startedUtc.ToString("o")
            startup_duration_ms = $startupDurationMs
            gui_pid = $process.Id
            dashboard_hwnd = [int64]$dashboard
            architecture_expectation = if ($Variant -eq "GPU") {
                "split-medium-integrity-gui"
            }
            else {
                "inproc-high-integrity"
            }
            launched_from_admin = $isAdmin
            working_set_bytes = [int64]$process.PeakWorkingSet64
            child_processes_observed = @(
                $descendants | ForEach-Object {
                    [ordered]@{
                        pid = [int]$_.ProcessId
                        parent_pid = [int]$_.ParentProcessId
                        name = [string]$_.Name
                        command_line = [string]$_.CommandLine
                    }
                }
            )
            map_result = $mapLog.matched
            clean_exit = $true
            exit_code = $process.ExitCode
            crash_files = @()
            runtime_root = $runtimeRoot
        }

        Write-Host "$Variant $($profile.name) cycle $cycle: PASS" -ForegroundColor Green
        Assert-NoFrozenProcesses
    }
}

$evidence = [ordered]@{
    schema = "dupez.frozen-runtime-validation.v1"
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    variant = $Variant
    executable = $exeName
    executable_sha256 = $executableHash
    commit = $commit
    validation_host = [ordered]@{
        computer = $env:COMPUTERNAME
        windows = [Environment]::OSVersion.VersionString
        administrator = $isAdmin
        powershell = $PSVersionTable.PSVersion.ToString()
    }
    runs = $records
}
$evidencePath = Join-Path $distRoot (
    "frozen-runtime-evidence-{0}.json" -f $Variant.ToLowerInvariant()
)
$evidence | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $evidencePath -Encoding UTF8

Write-Host "`nFROZEN $Variant RUNTIME VALIDATION: PASS" -ForegroundColor Green
Write-Host "Evidence: $evidencePath"
