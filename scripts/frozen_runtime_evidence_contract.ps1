#requires -Version 5.1

function Assert-FrozenRuntimeEvidenceContract {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Evidence,

        [Parameter(Mandatory = $true)]
        [ValidateSet("GPU", "Compat")]
        [string]$ExpectedVariant,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedExecutable,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedHash,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedCommit
    )

    $canonicalExecutable = if ($ExpectedVariant -ceq "GPU") {
        "DupeZ-GPU.exe"
    }
    else {
        "DupeZ-Compat.exe"
    }
    $expectedAdministrator = $ExpectedVariant -ceq "Compat"
    $expectedArchitecture = if ($expectedAdministrator) {
        "Architecture: inproc | Admin: True"
    }
    else {
        "Architecture: split | Admin: False"
    }

    if ($ExpectedExecutable -cne $canonicalExecutable) {
        throw "$ExpectedVariant frozen evidence expected executable is invalid."
    }
    if ($ExpectedHash -cnotmatch '^[0-9a-f]{64}$') {
        throw "$ExpectedVariant frozen evidence expected SHA-256 is invalid."
    }
    if ($ExpectedCommit -cnotmatch '^[0-9a-f]{40}$') {
        throw "$ExpectedVariant frozen evidence expected commit is invalid."
    }
    if ($Evidence.schema -cne "dupez.frozen-runtime-validation.v4") {
        throw "$ExpectedVariant frozen evidence schema mismatch."
    }
    if ($Evidence.variant -cne $ExpectedVariant) {
        throw "$ExpectedVariant frozen evidence variant mismatch."
    }
    if ($Evidence.executable -cne $ExpectedExecutable) {
        throw "$ExpectedVariant frozen evidence executable mismatch."
    }
    if ($Evidence.executable_sha256 -cne $ExpectedHash) {
        throw "$ExpectedVariant frozen evidence SHA-256 mismatch."
    }
    if ($Evidence.commit -cne $ExpectedCommit) {
        throw "$ExpectedVariant frozen evidence commit mismatch."
    }
    if ($Evidence.source_state -cne "clean") {
        throw "$ExpectedVariant frozen evidence is not from a clean source tree."
    }
    if ([string]$Evidence.source_fingerprint -cnotmatch '^[0-9a-f]{64}$') {
        throw "$ExpectedVariant frozen evidence source fingerprint is invalid."
    }
    if (
        [string]$Evidence.validation_session_id -cnotmatch
            '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    ) {
        throw "$ExpectedVariant frozen evidence session identifier is invalid."
    }
    $timestampStyles = (
        [Globalization.DateTimeStyles]::AssumeUniversal -bor
        [Globalization.DateTimeStyles]::AdjustToUniversal
    )
    $generatedAt = [DateTimeOffset]::MinValue
    if (
        $Evidence.generated_at_utc -isnot [string] -or
        -not [DateTimeOffset]::TryParseExact(
            [string]$Evidence.generated_at_utc,
            "yyyy-MM-ddTHH:mm:ssZ",
            [Globalization.CultureInfo]::InvariantCulture,
            $timestampStyles,
            [ref]$generatedAt
        )
    ) {
        throw "$ExpectedVariant frozen evidence generation time is invalid."
    }
    $now = [DateTimeOffset]::UtcNow
    if ($generatedAt -gt $now.AddMinutes(5) -or $generatedAt -lt $now.AddHours(-24)) {
        throw "$ExpectedVariant frozen evidence is stale or future-dated."
    }
    if (
        ($Evidence.cycles_per_profile -isnot [int] -and
            $Evidence.cycles_per_profile -isnot [long]) -or
        [int64]$Evidence.cycles_per_profile -lt 1 -or
        [int64]$Evidence.cycles_per_profile -gt 5
    ) {
        throw "$ExpectedVariant frozen evidence cycle count is invalid."
    }
    if (
        $Evidence.validation_host.administrator -isnot [bool] -or
        [bool]$Evidence.validation_host.administrator -ne $expectedAdministrator
    ) {
        throw "$ExpectedVariant frozen evidence host administrator state mismatch."
    }
    if ($Evidence.network_validation_mode -cne "production-safety-dry-run") {
        throw "$ExpectedVariant frozen evidence network validation mode mismatch."
    }

    $requiredRunKeys = @(
        foreach ($profile in @("normal", "forced-low-resource")) {
            foreach ($cycle in 1..([int64]$Evidence.cycles_per_profile)) {
                "$profile|$cycle"
            }
        }
    )
    $requiredRunKeySet = New-Object 'System.Collections.Generic.HashSet[string]' (
        [System.StringComparer]::Ordinal
    )
    foreach ($key in $requiredRunKeys) {
        $null = $requiredRunKeySet.Add($key)
    }
    $seenRunKeys = New-Object 'System.Collections.Generic.HashSet[string]' (
        [System.StringComparer]::Ordinal
    )

    $runs = @($Evidence.runs)
    if ($runs.Count -ne $requiredRunKeys.Count) {
        throw (
            "$ExpectedVariant frozen evidence must contain exactly one run for " +
            "each required profile/cycle combination."
        )
    }
    foreach ($run in $runs) {
        if ($run.variant -cne $ExpectedVariant -or $run.variant -cne $Evidence.variant) {
            throw "$ExpectedVariant frozen run variant binding mismatch."
        }
        if (
            $run.executable -cne $ExpectedExecutable -or
            $run.executable -cne $Evidence.executable
        ) {
            throw "$ExpectedVariant frozen run executable binding mismatch."
        }
        if (
            $run.executable_sha256 -cne $ExpectedHash -or
            $run.executable_sha256 -cne $Evidence.executable_sha256
        ) {
            throw "$ExpectedVariant frozen run SHA-256 binding mismatch."
        }
        if ($run.commit -cne $ExpectedCommit -or $run.commit -cne $Evidence.commit) {
            throw "$ExpectedVariant frozen run commit binding mismatch."
        }
        if ($run.source_state -cne "clean" -or $run.source_state -cne $Evidence.source_state) {
            throw "$ExpectedVariant frozen run source-state binding mismatch."
        }
        if (
            [string]$run.source_fingerprint -cnotmatch '^[0-9a-f]{64}$' -or
            $run.source_fingerprint -cne $Evidence.source_fingerprint
        ) {
            throw "$ExpectedVariant frozen run source-fingerprint binding mismatch."
        }
        if (
            $run.validation_session_id -cne $Evidence.validation_session_id
        ) {
            throw "$ExpectedVariant frozen run session binding mismatch."
        }
        $startedAt = [DateTimeOffset]::MinValue
        if (
            $run.started_at_utc -isnot [string] -or
            -not [DateTimeOffset]::TryParseExact(
                [string]$run.started_at_utc,
                "yyyy-MM-ddTHH:mm:ssZ",
                [Globalization.CultureInfo]::InvariantCulture,
                $timestampStyles,
                [ref]$startedAt
            ) -or
            $startedAt -gt $generatedAt.AddMinutes(1) -or
            $startedAt -lt $generatedAt.AddHours(-24)
        ) {
            throw "$ExpectedVariant frozen run time is invalid or stale."
        }
        if (
            $run.launched_from_admin -isnot [bool] -or
            [bool]$run.launched_from_admin -ne $expectedAdministrator -or
            [bool]$run.launched_from_admin -ne
                [bool]$Evidence.validation_host.administrator
        ) {
            throw "$ExpectedVariant frozen run administrator-state binding mismatch."
        }
        if ($run.architecture_observed -cne $expectedArchitecture) {
            throw "$ExpectedVariant frozen run architecture mismatch."
        }
        if (
            $run.network_validation_mode -cne "production-safety-dry-run" -or
            $run.network_validation_mode -cne $Evidence.network_validation_mode
        ) {
            throw "$ExpectedVariant frozen run network validation mode mismatch."
        }
        if ($run.clean_exit -isnot [bool] -or $run.clean_exit -ne $true) {
            throw "$ExpectedVariant frozen evidence includes a failed lifecycle."
        }
        if (
            $run.exit_code -isnot [int] -and
            $run.exit_code -isnot [long]
        ) {
            throw "$ExpectedVariant frozen run exit code is not an integer."
        }
        if ([int64]$run.exit_code -ne 0) {
            throw "$ExpectedVariant frozen evidence includes a failed lifecycle."
        }
        if ($run.map_result -cne "Map: dashboard view active with manual approved URL") {
            throw "$ExpectedVariant frozen evidence lacks exact manual Map URL proof."
        }
        if (
            $run.webengine_helper_observed -isnot [bool] -or
            $run.webengine_helper_observed -ne $false
        ) {
            throw "$ExpectedVariant frozen evidence contains an unexpected WebEngine helper claim."
        }
        $observedProcessNames = @($run.process_names_observed)
        if (-not ($observedProcessNames -contains $ExpectedExecutable)) {
            throw "$ExpectedVariant frozen evidence lacks the expected application process."
        }
        if ($observedProcessNames -contains "QtWebEngineProcess.exe") {
            throw "$ExpectedVariant frozen evidence contains an unexpected WebEngine helper process."
        }
        if (
            $run.PSObject.Properties.Name -notcontains "crash_files" -or
            @($run.crash_files).Count -ne 0
        ) {
            throw "$ExpectedVariant frozen evidence reports crash artifacts."
        }
        if ($run.profile -isnot [string]) {
            throw "$ExpectedVariant frozen run profile is not a string."
        }
        if ($run.cycle -isnot [int] -and $run.cycle -isnot [long]) {
            throw "$ExpectedVariant frozen run cycle is not an integer."
        }
        $runKey = "{0}|{1}" -f $run.profile, ([int64]$run.cycle)
        if (-not $requiredRunKeySet.Contains($runKey)) {
            throw "$ExpectedVariant frozen evidence contains an unexpected run: $runKey"
        }
        if (-not $seenRunKeys.Add($runKey)) {
            throw "$ExpectedVariant frozen evidence contains a duplicate run: $runKey"
        }
    }

    $missingRunKeys = @(
        $requiredRunKeys | Where-Object { -not $seenRunKeys.Contains($_) }
    )
    if ($missingRunKeys.Count -ne 0) {
        throw (
            "$ExpectedVariant frozen evidence is missing required runs: " +
            ($missingRunKeys -join ", ")
        )
    }
}
