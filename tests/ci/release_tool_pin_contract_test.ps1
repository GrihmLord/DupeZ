#requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$finalizerPath = Join-Path $repositoryRoot "scripts\finalize_release.ps1"
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $finalizerPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "finalize_release.ps1 has PowerShell parse errors."
}
$functionDefinitions = @(
    $ast.FindAll(
        {
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
        },
        $true
    )
)
foreach ($functionName in @(
    "Read-ReleaseToolPins",
    "Test-PinnedProductVersion"
)) {
    $definitions = @(
        $functionDefinitions | Where-Object { $_.Name -ceq $functionName }
    )
    if ($definitions.Count -ne 1) {
        throw "Expected exactly one $functionName function."
    }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}

foreach ($actualVersion in @("6.7.1", " 6.7.1", "6.7.1   ", "`t6.7.1`r`n")) {
    if (-not (Test-PinnedProductVersion `
        -ActualVersion $actualVersion `
        -PinnedVersion "6.7.1")) {
        throw "Padded exact product version was rejected."
    }
}
foreach ($actualVersion in @("", "   ", "6.7.1.0", "6.7.1 suffix")) {
    if (Test-PinnedProductVersion `
        -ActualVersion $actualVersion `
        -PinnedVersion "6.7.1") {
        throw "Non-exact product version was accepted."
    }
}
if (Test-PinnedProductVersion -ActualVersion $null -PinnedVersion "6.7.1") {
    throw "Null product version was accepted."
}

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempRoot = Join-Path $tempBase (
    "dupez-release-tool-pin-{0}" -f [Guid]::NewGuid().ToString("N")
)
$packagingRoot = Join-Path $tempRoot "packaging"
$manifestPath = Join-Path $packagingRoot "release-tools.json"
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.Directory]::CreateDirectory($packagingRoot) | Out-Null
$repoRoot = $tempRoot

function Write-FixtureManifest {
    param([string]$Payload)
    [IO.File]::WriteAllText($manifestPath, $Payload, $utf8)
}

function Assert-FixtureRejected {
    param([string]$Payload)
    Write-FixtureManifest -Payload $Payload
    $rejected = $false
    try {
        Read-ReleaseToolPins | Out-Null
    }
    catch {
        $rejected = $true
    }
    if (-not $rejected) {
        throw "Read-ReleaseToolPins accepted an invalid root payload."
    }
}

try {
    $valid = (
        '{"schema":"dupez.release-tools.v1",' +
        '"iscc":{},"signtool":{}}'
    )
    Write-FixtureManifest -Payload $valid
    $pins = Read-ReleaseToolPins
    if ($pins.schema -cne "dupez.release-tools.v1") {
        throw "Read-ReleaseToolPins rejected the valid object fixture."
    }

    Assert-FixtureRejected -Payload ("[$valid]")
    Assert-FixtureRejected -Payload (
        '{"schema":"dupez.release-tools.v1",' +
        '"iscc":{},"signtool":{},"unexpected":true}'
    )
    Assert-FixtureRejected -Payload '{}'
    Assert-FixtureRejected -Payload ''
    Assert-FixtureRejected -Payload '{malformed'
}
finally {
    $resolvedRoot = [IO.Path]::GetFullPath($tempRoot)
    $safePrefix = $tempBase.TrimEnd('\') + '\'
    if (-not $resolvedRoot.StartsWith(
        $safePrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to remove an unsafe fixture directory."
    }
    if ([IO.Directory]::Exists($resolvedRoot)) {
        [IO.Directory]::Delete($resolvedRoot, $true)
    }
}

Write-Output "PASS: release tool pin parser and product-version checks are fail closed."
