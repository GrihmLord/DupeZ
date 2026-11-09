"""Engineering adoption keeps real distribution identities and bounded inputs."""
from dataclasses import replace
import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

from scripts import prepare_qt_adoption as adoption
from scripts.verify_requirements_lock import LockedEntry, parse_release_lock_entries


def entry(name, version="1.0", checksum="a" * 64, marker=""):
    return LockedEntry(name, version, marker, (checksum,), 1)


def source_archive(path, members):
    with tarfile.open(path, "w:xz") as archive:
        for name, body, kind in members:
            member = tarfile.TarInfo(name)
            if kind == "link":
                member.type = tarfile.SYMTYPE
                member.linkname = "outside"
                archive.addfile(member)
            else:
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))


def test_effective_lock_only_changes_reviewed_qt_boundary(tmp_path):
    entries = [entry("pyqt6", "6.11.0"), entry("pyqt6-sip", "13.11.1"),
               entry("unchanged", marker="sys_platform == 'win32'"),
               *(entry(name) for name in sorted(adoption.REMOVED))]
    transformed = adoption.effective_runtime(entries, "6.11.0", "b" * 64)
    assert transformed == [replace(entries[0], hashes=("b" * 64,)), *entries[1:3]]
    path = tmp_path / "profile-lock.txt"
    adoption.write_lock(path, transformed)
    parsed = parse_release_lock_entries(path)
    assert [(x.name, x.version, x.hashes) for x in parsed] == [(x.name, x.version, x.hashes) for x in transformed]
    assert parsed[2].marker == 'sys_platform == "win32"'
    assert entries[0].hashes == ("a" * 64,)


@pytest.mark.parametrize("kind", ["hash", "binding", "missing-distribution"])
def test_effective_lock_rejects_unreviewed_inputs(kind):
    entries = [entry("pyqt6", "6.11.0"), *(entry(name) for name in adoption.REMOVED)]
    if kind == "missing-distribution":
        entries.pop()
    with pytest.raises(ValueError):
        adoption.effective_runtime(entries, "6.12.0" if kind == "binding" else "6.11.0",
                                   "invalid" if kind == "hash" else "b" * 64)


def test_notice_collection_preserves_source_bytes_and_labels_namespace(tmp_path):
    archive = tmp_path / "source.tar.xz"
    members = [("LICENSES/MIT.txt", b"MIT license\r\n", "file"),
               ("src/3rdparty/library/COPYING", b"Copyright text\n", "file"),
               ("src/3rdparty/library/qt_attribution.json", b'{"LicenseId":"MIT"}\n', "file"),
               ("REUSE.toml", b"version = 1\n", "file"),
               ("src/code.cpp", b"not a license", "file")]
    source_archive(archive, members)
    output = tmp_path / "profile"
    records = adoption.collect_source_notices(archive, output, "qtbase-native")
    assert len(records) == 4
    assert not (output / "src/code.cpp").exists()
    for record in records:
        assert record["path"].startswith("packaging/licenses/qtbase-native/")
        assert adoption.sha256(output / record["path"]) == record["sha256"]
        assert (output / record["path"]).read_bytes() == next(body for name, body, _ in members if name == record["archive_member"])


@pytest.mark.parametrize("members", [
    [("../outside", b"text", "file")],
    [("LICENSES/MIT.txt", b"", "link")],
    [("LICENSES/MIT.txt", b"text", "file"), ("LICENSES/mit.txt", b"other", "file")],
    [("LICENSES/MIT.txt", b"nul\x00text", "file")],
    [("README.md", b"no LICENSES", "file")],
])
def test_notice_collection_rejects_unsafe_or_incomplete_sources(tmp_path, members):
    archive = tmp_path / "source.tar.xz"
    source_archive(archive, members)
    with pytest.raises((ValueError, adoption.license_payload.LicensePayloadError)):
        adoption.collect_source_notices(archive, tmp_path / "profile", "qtbase-native")
    assert not (tmp_path / "outside").exists()


def test_notice_size_bound_precedes_output_write(tmp_path, monkeypatch):
    archive = tmp_path / "source.tar.xz"
    source_archive(archive, [("LICENSES/MIT.txt", b"longer than limit", "file")])
    monkeypatch.setattr(adoption, "MAX_DOCUMENT", 3)
    with pytest.raises(ValueError, match="oversized"):
        adoption.collect_source_notices(archive, tmp_path / "profile", "qtbase-native")
    assert not (tmp_path / "profile").exists()


def wheel(path, content=b"fixture"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("package/payload.txt", content)
    return adoption.sha256(path)


def test_wheelhouse_admits_only_hash_locked_target_wheels(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    output = tmp_path / "wheels"
    output.mkdir()
    approved = cache / "example-1.0-cp313-cp313-win_amd64.whl"
    checksum = wheel(approved)
    wrong_platform = cache / "other-1.0-cp313-cp313-manylinux_2_34_x86_64.whl"
    wrong_hash = cache / "untrusted-1.0-py3-none-any.whl"
    wheel(wrong_hash)
    bad_platform_hash = wheel(wrong_platform)
    staged, missing = adoption.stage_wheels([
        entry("example", checksum=checksum), entry("other", checksum=bad_platform_hash), entry("untrusted"),
    ], [cache], output)
    assert [row["name"] for row in staged] == ["example"]
    assert missing == ["other", "untrusted"]
    assert list(output.iterdir()) == [output / approved.name]
    assert approved.read_bytes() == (output / approved.name).read_bytes()


def test_runtime_build_conflict_is_not_silently_overlaid(tmp_path):
    with pytest.raises(ValueError, match="Conflicting"):
        adoption.stage_wheels([entry("packaging", "26.2"), entry("packaging", "26.3")], [], tmp_path)


def test_installer_is_offline_and_checks_metadata_and_dependency_closure(tmp_path, monkeypatch):
    monkeypatch.setattr(adoption.sys, "platform", "win32")
    monkeypatch.setattr(adoption.sys, "version_info", (3, 13, 17))
    monkeypatch.setattr(adoption.candidate, "child_environment", lambda _path: {"PATH": "trusted-system"})
    commands = []

    def record(command, **kwargs):
        commands.append(command)
        assert kwargs["env"] == {"PATH": "trusted-system"}
        assert kwargs["check"] is True
        kwargs["stdout"].write(b"mocked command completed\n")

    monkeypatch.setattr(adoption.subprocess, "run", record)
    result = adoption.install_environment(tmp_path, "5.8.0")
    pip = commands[1]
    assert "--no-index" in pip and "--require-hashes" in pip and "--only-binary=:all:" in pip
    assert "--no-deps" not in pip
    assert commands[2][-2:] == ["pip", "check"]
    assert "Unexpected Qt distribution identities" in commands[3][3]
    assert "Installed candidate payload differs" in commands[3][3]
    assert "validate_license_payload" in commands[4][3]
    assert result["notice_payload"] == "verified"


def test_profile_sbom_distinguishes_derived_wheel_and_native_modules():
    result = adoption.profile_sbom([entry("pyqt6", "6.11.0", "b" * 64)],
                                   {"qt_version": "6.11.3"}, "b" * 64, "5.8.0")
    python = result["components"][0]
    assert python["version"] == "6.11.0"
    assert python["hashes"] == [{"alg": "SHA-256", "content": "b" * 64}]
    assert all(reference["type"] != "distribution" for reference in python["externalReferences"])
    assert len(result["components"]) == 5
    assert {row["version"] for row in result["components"][1:]} == {"6.11.3"}
    assert {"name": "dupez:engineering-only", "value": "true"} in result["metadata"]["properties"]


@pytest.mark.parametrize("mismatch", ["receipt-hash", "manifest-hash", "profile", "wheel-hash"])
def test_preparation_identity_is_checked_before_profile_creation(tmp_path, monkeypatch, mismatch):
    monkeypatch.setattr(adoption, "ROOT", tmp_path)
    source = tmp_path / "candidate"
    source.mkdir()
    candidate_wheel = source / "candidate.whl"
    candidate_wheel.write_bytes(b"reviewed")
    checksum = adoption.sha256(candidate_wheel)
    manifest = {"profile": "frozen-raster"}
    receipt = {"schema": "dupez.qt-candidate-preparation.v3", "profile": "frozen-raster",
               "status": "candidate-wheel-prepared", "manifest_sha256": "a" * 64,
               "wheel": {"path": "candidate.whl", "sha256": checksum}}
    if mismatch == "receipt-hash":
        receipt["wheel"]["sha256"] = "c" * 64
    elif mismatch == "manifest-hash":
        receipt["manifest_sha256"] = "c" * 64
    elif mismatch == "profile":
        receipt["profile"] = "full-opengl"
    else:
        candidate_wheel.write_bytes(b"altered")
    adoption.write_json(source / "preparation-receipt.json", receipt)
    monkeypatch.setattr(adoption.candidate, "load_manifest_snapshot", lambda _path: (manifest, "a" * 64))
    output = tmp_path / "build/profile"
    with pytest.raises(ValueError, match="receipt|digest"):
        adoption.prepare(source, checksum, output, [])
    assert not output.exists()


def _preparation_fixture(tmp_path, monkeypatch):
    """Inert orchestration inputs; retain real file/hash and notice operations."""
    monkeypatch.setattr(adoption, "ROOT", tmp_path)
    (tmp_path / "packaging").mkdir()
    (tmp_path / "build").mkdir()
    source = tmp_path / "candidate"
    (source / "inputs").mkdir(parents=True)
    archive_wheel = source / "PyQt6-6.11.0-cp310-abi3-win_amd64.whl"
    checksum = wheel(archive_wheel)
    manifest = {"profile": "frozen-raster", "binding_version": "6.11.0", "qt_version": "6.11.3", "inputs": []}
    for source_id in adoption.SOURCE_IDS:
        path = source / "inputs" / (source_id + ".tar.xz")
        source_archive(path, [("LICENSES/MIT.txt", b"Original upstream notice\n", "file")])
        manifest["inputs"].append({"id": source_id, "filename": path.name, "size": path.stat().st_size,
                                   "sha256": adoption.sha256(path), "url": "https://download.qt.io/inert-source"})
    manifest_path = tmp_path / "packaging/qt-raster-inputs.json"
    adoption.write_json(manifest_path, manifest)
    monkeypatch.setattr(adoption.candidate, "load_manifest_snapshot",
                        lambda path: (json.loads(path.read_bytes()), adoption.sha256(path)))
    adoption.write_json(source / "preparation-receipt.json", {
        "schema": "dupez.qt-candidate-preparation.v3", "profile": "frozen-raster",
        "status": "candidate-wheel-prepared", "manifest_sha256": adoption.sha256(manifest_path),
        "wheel": {"path": archive_wheel.name, "sha256": checksum},
    })
    runtime = [entry("pyqt6", "6.11.0"), entry("pyqt6-sip"), *(entry(name) for name in adoption.REMOVED)]
    adoption.write_lock(tmp_path / "requirements-locked.txt", runtime)
    adoption.write_lock(tmp_path / "packaging/requirements-build-locked.txt", [])
    adoption.write_json(tmp_path / "packaging/third-party-components.json", {
        "runtime_components": [{"name": row.name, "version": row.version} for row in runtime],
        "additional_components": [],
    })
    (tmp_path / "LICENSE.txt").write_text("Local project license\n")
    # These fixtures test consumed-input provenance, not wheel generation or
    # the separate installed-distribution license collector.
    monkeypatch.setattr(adoption.candidate, "validate_candidate_wheel", lambda *_a: {})
    monkeypatch.setattr(adoption, "copy_inventory_documents", lambda *_a: None)
    monkeypatch.setattr(adoption.license_payload, "_load_inventory", lambda *_a: None)
    monkeypatch.setattr(adoption, "stage_wheels", lambda *_a: ([], []))
    return source, checksum, tmp_path / "build/profile", archive_wheel


@pytest.mark.parametrize("changed", ["source", "runtime-lock", "build-lock", "inventory", "license", "manifest", "receipt", "wheel"])
def test_consumed_input_mutation_cannot_publish_adoption_profile(tmp_path, monkeypatch, changed):
    source, checksum, output, archive_wheel = _preparation_fixture(tmp_path, monkeypatch)
    paths = {
        "source": source / "inputs/qtbase-source.tar.xz",
        "runtime-lock": tmp_path / "requirements-locked.txt",
        "build-lock": tmp_path / "packaging/requirements-build-locked.txt",
        "inventory": tmp_path / "packaging/third-party-components.json",
        "license": tmp_path / "LICENSE.txt",
        "manifest": tmp_path / "packaging/qt-raster-inputs.json",
        "receipt": source / "preparation-receipt.json",
        "wheel": archive_wheel,
    }
    collector = adoption.collect_source_notices
    mutated = False

    def mutate_after_input_validation(*args):
        nonlocal mutated
        if not mutated:
            if changed == "source":
                source_archive(paths[changed], [("LICENSES/MIT.txt", b"Substituted notice\n", "file")])
            else:
                with paths[changed].open("ab") as stream:
                    stream.write(b"\n")
            mutated = True
        return collector(*args)

    monkeypatch.setattr(adoption, "collect_source_notices", mutate_after_input_validation)
    with pytest.raises(ValueError, match="Engineering input changed during preparation"):
        adoption.prepare(source, checksum, output, [])
    assert mutated
    assert not (output / "engineering-profile.json").exists()


def test_stable_preparation_records_consumed_input_identities(tmp_path, monkeypatch):
    source, checksum, output, _wheel = _preparation_fixture(tmp_path, monkeypatch)
    result = adoption.prepare(source, checksum, output, [])
    assert result["base_inputs"] == {
        relative: adoption.sha256(tmp_path / relative)
        for relative in ("requirements-locked.txt", "packaging/requirements-build-locked.txt",
                         "packaging/third-party-components.json", "LICENSE.txt")
    }
    assert result["preparation_receipt_sha256"] == adoption.sha256(source / "preparation-receipt.json")
    assert result["candidate_manifest_sha256"] == adoption.sha256(tmp_path / "packaging/qt-raster-inputs.json")
    assert result["release_approved"] is False
    assert result["source_delivery_approved"] is False


@pytest.mark.parametrize("relative", [
    "requirements-locked.txt", "packaging/requirements-build-locked.txt",
    "packaging/third-party-components.json", "engineering-profile.json", "engineering.sbom.json",
    "wheelhouse/PyQt6-6.11.0-cp310-abi3-win_amd64.whl",
])
def test_installation_receipt_requires_unchanged_generated_inputs(tmp_path, monkeypatch, relative):
    source, checksum, output, _wheel = _preparation_fixture(tmp_path, monkeypatch)

    def mutate_during_installation(profile, _product_version):
        with (profile / relative).open("ab") as stream:
            stream.write(b"\n")
        return {"pip_check": "passed", "installed_wheel_payload": "verified", "notice_payload": "verified"}

    monkeypatch.setattr(adoption, "install_environment", mutate_during_installation)
    with pytest.raises(ValueError, match="Engineering input changed during preparation"):
        adoption.prepare(source, checksum, output, [], install=True)
    assert (output / "engineering-profile.json").is_file()
    assert not (output / "installation-receipt.json").exists()
