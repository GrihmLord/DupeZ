#requires -Version 5.1
<#
.SYNOPSIS
Retired legacy release entry point.

.DESCRIPTION
This script intentionally refuses to tag or publish a release. The protected
v5.7.9 process requires signed exact-artifact finalization, frozen and manual
validation, draft upload verification, and explicit publication through the
strict scripts listed in the error below.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [switch]$SkipBuild,

    [string]$SkipHooks = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

throw @"
scripts\release.ps1 is retired and cannot publish v$Version.

Use the fail-closed release sequence:
  1. scripts\finalize_release.ps1
  2. scripts\validate_frozen_runtime.ps1
  3. scripts\record_manual_release_validation.ps1
  4. scripts\stage_release.ps1 -Mode Draft
  5. scripts\stage_release.ps1 -Mode Publish

No tag or GitHub release was created.
"@
