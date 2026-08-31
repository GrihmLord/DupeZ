import zipfile
from pathlib import Path

from scripts.release_preflight import _check_source_archive


_REQUIRED = {
    "LICENSE.txt",
    "README.md",
    "requirements.in",
    "requirements-locked.txt",
    "packaging/build_variants.bat",
    "packaging/installer.iss",
    "packaging/license-policy.json",
    "packaging/requirements-build-locked.txt",
    "packaging/third-party-components.json",
    "scripts/finalize_release.ps1",
    "scripts/license_payload.py",
    "docs/legal/DISTRIBUTION_BASIS_V5.8.0.md",
    "docs/legal/SOURCE_AND_RELINK_V5.8.0.md",
}


def _write_archive(
    dist: Path,
    *,
    omit: str | None = None,
    unsafe: str | None = None,
    comment: bytes = b"1" * 40,
) -> Path:
    dist.mkdir(parents=True)
    archive_path = dist / "DupeZ-v5.8.0-source.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.comment = comment
        for relative in sorted(_REQUIRED - ({omit} if omit else set())):
            archive.writestr(f"DupeZ-v5.8.0/{relative}", b"source\n")
        if unsafe:
            archive.writestr(unsafe, b"escape\n")
    return archive_path


def test_source_archive_accepts_safe_exact_commit_shape(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)

    assert _check_source_archive(dist, "5.8.0") == []


def test_source_archive_rejects_missing_delivery_file(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist, omit="LICENSE.txt")

    errors = _check_source_archive(dist, "5.8.0")

    assert any("LICENSE.txt" in error for error in errors)


def test_source_archive_rejects_traversal_and_missing_commit_comment(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    _write_archive(
        dist,
        unsafe="DupeZ-v5.8.0/../escape.txt",
        comment=b"",
    )

    errors = _check_source_archive(dist, "5.8.0")

    assert any("unsafe entry" in error for error in errors)
    assert any("Git commit comment" in error for error in errors)
