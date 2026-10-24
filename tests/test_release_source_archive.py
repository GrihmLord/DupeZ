import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from scripts.release_preflight import _check_source_archive


_REQUIRED = {
    "LICENSE.txt",
    "README.md",
    "dupez.py",
    "dupez_helper.py",
    "app/__init__.py",
    "app/__version__.py",
    "app/main.py",
    "app/firewall_helper/feature_flag.py",
    "app/firewall/clumsy_src/LICENSE",
    "app/firewall/clumsy_src/build.zig",
    "app/firewall/clumsy_src/src/main.c",
    "requirements.in",
    "requirements-locked.txt",
    "packaging/build_common.py",
    "packaging/build_variants.bat",
    "packaging/native_runtime_policy.py",
    "packaging/hooks/hook-PyQt6.QtNetwork.py",
    "packaging/dupez_gpu.spec",
    "packaging/dupez_compat.spec",
    "packaging/dupez.manifest",
    "packaging/dupez_compat.manifest",
    "packaging/installer.iss",
    "packaging/license-policy.json",
    "packaging/release_data.py",
    "packaging/release-data.json",
    "packaging/binary-provenance.json",
    "packaging/release-tools.json",
    "packaging/requirements-build.in",
    "packaging/requirements-build-locked.txt",
    "packaging/third-party-components.json",
    "packaging/source-inputs.json",
    "packaging/recipient-validation/application-marker.patch",
    "packaging/recipient-validation/zeroconf-marker.patch",
    "packaging/version_info.py",
    "scripts/finalize_release.ps1",
    "scripts/license_payload.py",
    "scripts/corresponding_source.py",
    "scripts/recipient_rebuild_evidence.py",
    "scripts/native_build_evidence.py",
    "scripts/release_preflight.py",
    "scripts/verify_requirements_lock.py",
    "scripts/sbom.py",
    "docs/legal/DISTRIBUTION_BASIS_V5.8.0.md",
    "docs/legal/SOURCE_AND_RELINK_V5.8.0.md",
}
_RELEASE_DATA = json.loads(
    (Path(__file__).resolve().parents[1] / "packaging/release-data.json").read_text(
        encoding="utf-8"
    )
)
_REQUIRED.update(_RELEASE_DATA["files"] + _RELEASE_DATA["binaries"])


def _write_archive(
    dist: Path,
    *,
    omit: str | None = None,
    unsafe: str | None = None,
    comment: bytes = b"1" * 40,
    directories: bool = False,
) -> Path:
    dist.mkdir(parents=True)
    archive_path = dist / "DupeZ-v5.8.0-source.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.comment = comment
        if directories:
            directory_names = {"DupeZ-v5.8.0/"}
            for relative in _REQUIRED:
                directory_names.update(
                    f"DupeZ-v5.8.0/{parent.as_posix()}/"
                    for parent in PurePosixPath(relative).parents
                    if parent != PurePosixPath(".")
                )
            for directory in sorted(directory_names):
                archive.writestr(directory, b"")
        for relative in sorted(_REQUIRED - ({omit} if omit else set())):
            archive.writestr(f"DupeZ-v5.8.0/{relative}", b"source\n")
        if unsafe:
            archive.writestr(unsafe, b"escape\n")
    return archive_path


def test_source_archive_accepts_safe_exact_commit_shape(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)

    assert _check_source_archive(dist, "5.8.0") == []


@pytest.mark.parametrize("required", sorted(_REQUIRED))
def test_source_archive_rejects_missing_delivery_or_build_input(
    tmp_path: Path, required: str
) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist, omit=required)

    errors = _check_source_archive(dist, "5.8.0")

    assert any(required.casefold() in error.casefold() for error in errors)


def test_source_archive_accepts_real_git_directory_entries(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist, directories=True)

    assert _check_source_archive(dist, "5.8.0", expected_commit="1" * 40) == []


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


@pytest.mark.parametrize("comment", [b"1" * 40, b"1" * 64])
def test_source_archive_binds_explicit_expected_commit(
    tmp_path: Path, comment: bytes
) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist, comment=comment)

    assert _check_source_archive(
        dist, "5.8.0", expected_commit=comment.decode("ascii")
    ) == []
    errors = _check_source_archive(
        dist, "5.8.0", expected_commit="2" * len(comment)
    )
    assert any("expected source identity" in error for error in errors)


@pytest.mark.parametrize("expected_commit", ["main", "a" * 39, "A" * 40, 42])
def test_source_archive_rejects_invalid_expected_commit(
    tmp_path: Path, expected_commit
) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)

    errors = _check_source_archive(dist, "5.8.0", expected_commit=expected_commit)

    assert any("expected commit is invalid" in error for error in errors)


def _write_attestation(dist: Path, **changes) -> dict:
    archive_path = dist / "DupeZ-v5.8.0-source.zip"
    payload = {
        "schema": "dupez.release-attestation.v1",
        "product": "DupeZ",
        "version": "5.8.0",
        "commit": "1" * 40,
        "artifacts": [{
            "name": archive_path.name,
            "size": archive_path.stat().st_size,
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        }],
    }
    payload.update(changes)
    (dist / "release-attestation.json").write_text(
        json.dumps(payload), encoding="utf-8-sig"
    )
    return payload


def test_source_archive_binds_attested_commit_and_bytes(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)
    _write_attestation(dist)

    assert _check_source_archive(dist, "5.8.0") == []


def test_source_archive_rejects_attested_commit_mismatch(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)
    _write_attestation(dist, commit="2" * 40)

    errors = _check_source_archive(dist, "5.8.0")

    assert any("expected source identity" in error for error in errors)


def test_source_archive_rejects_attestation_expected_commit_mismatch(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)
    _write_attestation(dist)

    errors = _check_source_archive(dist, "5.8.0", expected_commit="2" * 40)

    assert any("attestation differs from the expected commit" in error for error in errors)


@pytest.mark.parametrize("field,value", [("size", 1), ("size", True), ("sha256", "2" * 64)])
def test_source_archive_rejects_attested_bytes_mismatch(
    tmp_path: Path, field: str, value
) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)
    payload = _write_attestation(dist)
    payload["artifacts"][0][field] = value
    _write_attestation(dist, artifacts=payload["artifacts"])

    errors = _check_source_archive(dist, "5.8.0")

    assert any("differs from attested bytes" in error for error in errors)


@pytest.mark.parametrize("changes", [
    {"schema": "other"},
    {"version": "5.7.9"},
    {"product": "other"},
    {"commit": "main"},
    {"artifacts": []},
    {"artifacts": {}},
])
def test_source_archive_rejects_invalid_existing_attestation(
    tmp_path: Path, changes: dict
) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)
    _write_attestation(dist, **changes)

    errors = _check_source_archive(dist, "5.8.0")

    assert any("source attestation is invalid" in error for error in errors)


def test_source_archive_rejects_duplicate_attested_source_records(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)
    payload = _write_attestation(dist)
    _write_attestation(dist, artifacts=payload["artifacts"] * 2)

    errors = _check_source_archive(dist, "5.8.0")

    assert any("one attestation record" in error for error in errors)


def test_source_archive_rejects_git_metadata(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist, unsafe="DupeZ-v5.8.0/.git/config")

    errors = _check_source_archive(dist, "5.8.0")

    assert any("must not contain Git metadata" in error for error in errors)


def test_rejected_oversized_member_is_never_decompressed(tmp_path: Path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)
    original = zipfile.ZipFile.infolist

    def oversized_member(archive):
        entries = original(archive)
        entries[0].file_size = 256 * 1024 * 1024 + 1
        return entries

    def forbidden_crc_scan(archive):
        pytest.fail("Rejected oversized archives must not be decompressed")

    monkeypatch.setattr(zipfile.ZipFile, "infolist", oversized_member)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", forbidden_crc_scan)

    errors = _check_source_archive(dist, "5.8.0")

    assert any("entry has an invalid size" in error for error in errors)


def test_rejected_entry_count_is_never_decompressed(tmp_path: Path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    _write_archive(dist)
    original = zipfile.ZipFile.infolist

    def excessive_members(archive):
        entries = original(archive)
        return entries + [entries[0]] * 20001

    def forbidden_crc_scan(archive):
        pytest.fail("Rejected entry counts must not trigger decompression")

    monkeypatch.setattr(zipfile.ZipFile, "infolist", excessive_members)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", forbidden_crc_scan)

    errors = _check_source_archive(dist, "5.8.0")

    assert any("entry count is invalid" in error for error in errors)
