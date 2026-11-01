#requires -Version 5.1

function Assert-ExactManualReleaseGates {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Gates,

        [Parameter(Mandatory = $true)]
        [string]$RecorderPath
    )

    if (-not (Test-Path -LiteralPath $RecorderPath -PathType Leaf)) {
        throw "Manual release recorder is missing: $RecorderPath"
    }
    $recorder = Get-Content -LiteralPath $RecorderPath -Raw
    $contractMatch = [regex]::Match(
        $recorder,
        '(?ms)^\s*\$gateDescriptions\s*=\s*\[ordered\]@\{\s*(?<body>.*?)^\s*\}'
    )
    if (-not $contractMatch.Success) {
        throw "Could not derive the manual gate contract from the recorder."
    }
    $expected = @(
        [regex]::Matches(
            $contractMatch.Groups['body'].Value,
            '(?m)^\s*(?<name>[A-Za-z_][A-Za-z0-9_]*)\s*='
        ) | ForEach-Object { $_.Groups['name'].Value }
    )
    $expectedUnique = @($expected | Sort-Object -Unique)
    if ($expected.Count -ne 16 -or $expectedUnique.Count -ne 16) {
        throw (
            "Manual gate recorder contract must define exactly 16 unique " +
            "keys; found $($expected.Count) entries and " +
            "$($expectedUnique.Count) unique keys."
        )
    }

    $actualProperties = @($Gates.PSObject.Properties)
    $actual = @($actualProperties | ForEach-Object { $_.Name })
    $missing = @($expectedUnique | Where-Object { $_ -notin $actual })
    $extra = @($actual | Where-Object { $_ -notin $expectedUnique })
    if (
        $actual.Count -ne $expectedUnique.Count -or
        $missing.Count -gt 0 -or
        $extra.Count -gt 0
    ) {
        throw (
            "Manual release gate key set mismatch. Missing: " +
            "$(($missing | Sort-Object) -join ', '); extra: " +
            "$(($extra | Sort-Object) -join ', ')."
        )
    }
    foreach ($gate in $actualProperties) {
        if ($gate.Value -isnot [bool] -or $gate.Value -ne $true) {
            throw "Manual release gate not completed as boolean true: $($gate.Name)"
        }
    }
    return $actualProperties
}
