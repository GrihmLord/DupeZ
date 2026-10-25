from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_installer_and_build_bind_the_verified_legal_payload() -> None:
    build = _read("packaging/build_variants.bat")
    installer = _read("packaging/installer.iss")
    preflight = _read("scripts/release_preflight.py")

    generator = build.index("scripts\\license_payload.py")
    compiler = build.index("packaging\\compile_installer.py")
    assert generator < compiler
    assert build.count("scripts\\license_payload.py") == 2
    assert "--verify" in build[generator:compiler]
    assert "LicenseFile=dist\\LICENSE.txt" in installer
    for name in (
        "LICENSE.txt",
        "SOURCE_AND_RELINK.txt",
        "THIRD_PARTY_NOTICES.txt",
        "license-payload.json",
    ):
        assert f'Source: "dist\\{name}"; DestDir: "{{app}}"' in installer
        assert f'"dist/{name.casefold()}"' in preflight


def test_finalizer_and_staging_carry_exact_commit_source_and_legal_assets() -> None:
    finalizer = _read("scripts/finalize_release.ps1")
    stage = _read("scripts/stage_release.ps1")
    archive_call = finalizer.index("$sourceArchive = New-ExactSourceArchive")
    artifact_collection = finalizer.index(
        "$artifacts = Get-RequiredArtifacts",
        archive_call,
    )
    assert archive_call < artifact_collection
    assert '"--format=zip"' in finalizer
    assert '"--prefix=DupeZ-v${ReleaseVersion}/"' in finalizer
    assert '"--output=$archivePath"' in finalizer

    legal_assets = (
        "LICENSE.txt",
        "SOURCE_AND_RELINK.txt",
        "THIRD_PARTY_NOTICES.txt",
        "license-payload.json",
    )
    for name in legal_assets:
        assert f'"{name}"' in finalizer
        assert f'"{name}"' in stage
    assert '"DupeZ-v${ReleaseVersion}-source.zip"' in finalizer
    assert '"DupeZ-v${Version}-source.zip"' in stage

    for workflow in (
        ".github/workflows/release.yml",
        ".github/workflows/unsigned-public-release.yml",
    ):
        text = _read(workflow)
        for name in (
            "LICENSE.txt",
            "SOURCE_AND_RELINK.txt",
            "THIRD_PARTY_NOTICES.txt",
            "license-payload.json",
            "DupeZ-v${{ inputs.version }}-source.zip",
        ):
            assert f"dist/{name}" in text
