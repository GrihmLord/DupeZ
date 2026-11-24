"""Engineering adoption keeps real distribution identities and bounded inputs."""
from dataclasses import replace
import io
import importlib.metadata
import json
from pathlib import Path
from types import SimpleNamespace
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
                                   {"qt_version": "6.11.3", "profile": "frozen-raster"}, "b" * 64, "5.8.0")
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


def test_clean_checkout_without_build_directory_can_prepare_profile(tmp_path, monkeypatch):
    source, checksum, output, _wheel = _preparation_fixture(tmp_path, monkeypatch)
    (tmp_path / "build").rmdir()
    result = adoption.prepare(source, checksum, output, [])
    assert output.is_dir()
    assert (output / "engineering-profile.json").is_file()
    assert result["profile"] == "frozen-raster"


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


def _no_network_preparation_fixture(tmp_path, monkeypatch):
    msvc_manifest = json.loads((adoption.ROOT / "packaging/msvc-redist-inputs.json").read_bytes())
    source, checksum, output, _wheel = _preparation_fixture(tmp_path, monkeypatch)
    redist = tmp_path / "verified-redist"
    (redist / "dlls").mkdir(parents=True)
    for row in msvc_manifest["binaries"]:
        path = redist / "dlls" / row["cabinet_member"]
        path.write_bytes(("Inert fixture: " + row["name"]).encode())
        row.update(size=path.stat().st_size, sha256=adoption.sha256(path))
    adoption.write_json(tmp_path / "packaging/msvc-redist-inputs.json", msvc_manifest)
    upstream = {
        "schema": "dupez.msvc-redist-provenance.v1", "status": "exact-upstream-package-bytes-verified",
        "manifest": adoption.input_pin(tmp_path / "packaging/msvc-redist-inputs.json"),
        "package": msvc_manifest["package"],
        "binaries": [{**row, "origin": "pinned-microsoft-redist-minimum-x64-cabinet"}
                     for row in msvc_manifest["binaries"]],
        **{key: False for key in ("release_approved", "distribution_approved", "installer_executed",
                                 "global_installation_performed", "elevation_requested")},
        "signature_observations": [
            {"name": name, "status": "Valid", "subject": "O=Microsoft Corporation",
             "file_version": msvc_manifest["package"]["version"],
             "thumbprint": msvc_manifest["package"]["signer_thumbprint"]}
            for name in ["package", *(row["name"] for row in msvc_manifest["binaries"])]] ,
        "consumed_artifacts": [
            {"path": "dlls/" + row["cabinet_member"], "size": row["size"], "sha256": row["sha256"]}
            for row in msvc_manifest["binaries"]],
    }
    adoption.write_json(redist / "receipt.json", upstream)
    manifest_path = tmp_path / "packaging/qt-raster-no-network-inputs.json"
    manifest = json.loads((tmp_path / "packaging/qt-raster-inputs.json").read_bytes())
    manifest.update(profile=adoption.candidate.NO_NETWORK_PROFILE, schema="dupez.qt-candidate-inputs.v4")
    adoption.write_json(manifest_path, manifest)
    receipt_path = source / "preparation-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt.update(profile=adoption.candidate.NO_NETWORK_PROFILE, schema="dupez.qt-candidate-preparation.v4",
                   manifest_sha256=adoption.sha256(manifest_path))
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return source, checksum, output, redist, manifest_path, msvc_manifest


def test_no_network_adoption_binds_v4_receipt_and_records_exclusion_not_patch(tmp_path, monkeypatch):
    source, checksum, output, redist, manifest_path, msvc_manifest = _no_network_preparation_fixture(tmp_path, monkeypatch)
    result = adoption.prepare(source, checksum, output, [], profile=adoption.candidate.NO_NETWORK_PROFILE,
                              msvc_redist_root=redist)
    assert result["profile"] == adoption.candidate.NO_NETWORK_PROFILE
    assert result["candidate_manifest_sha256"] == adoption.sha256(manifest_path)
    assert "excluded, not patched" in result["limitations"][1]
    sbom = json.loads((output / "engineering.sbom.json").read_bytes())
    assert {"name": "dupez:qt-network-payload", "value": "excluded-not-patched"} in sbom["metadata"]["properties"]
    native = [row for row in sbom["components"] if row["type"] == "file"]
    assert {row["name"]: row["hashes"][0]["content"] for row in native} == {
        row["name"]: row["sha256"] for row in msvc_manifest["binaries"]}
    assert all(any(p["value"] == "unresolved-owner-entitlement-and-applicable-terms" for p in row["properties"])
               for row in native)
    assert result["msvc_runtime_mapping"]["distribution_approved"] is False
    assert result["msvc_runtime_stage"]["path"] == "msvc-runtime"
    assert result["msvc_runtime_stage"]["stage_receipt_sha256"] == adoption.sha256(output / "msvc-runtime/stage-receipt.json")
    assert all(set(row) == {"name", "size", "sha256"} for row in result["msvc_runtime_stage"]["binaries"])


def test_no_network_adoption_requires_private_runtime_input_before_output(tmp_path, monkeypatch):
    source, checksum, output, _redist, _manifest, _msvc = _no_network_preparation_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="requires --msvc-redist-root"):
        adoption.prepare(source, checksum, output, [], profile=adoption.candidate.NO_NETWORK_PROFILE)
    assert not output.exists()


def test_old_profile_cannot_silently_ignore_private_runtime_input(tmp_path, monkeypatch):
    source, checksum, output, _wheel = _preparation_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="requires the QtNetwork-free profile"):
        adoption.prepare(source, checksum, output, [], msvc_redist_root=tmp_path)
    assert not output.exists()


@pytest.mark.parametrize("relative", ["MSVCP140.dll", "upstream-receipt.json", "stage-receipt.json"])
def test_private_runtime_mutation_during_installation_cannot_issue_receipt(tmp_path, monkeypatch, relative):
    source, checksum, output, redist, _manifest, _msvc = _no_network_preparation_fixture(tmp_path, monkeypatch)

    def corrupt_stage(profile, _version):
        with (profile / "msvc-runtime" / relative).open("ab") as stream:
            stream.write(b"changed after stage validation")
        return {"pip_check": "passed"}

    monkeypatch.setattr(adoption, "install_environment", corrupt_stage)
    with pytest.raises(ValueError, match="Engineering input changed during preparation"):
        adoption.prepare(source, checksum, output, [], profile=adoption.candidate.NO_NETWORK_PROFILE,
                         msvc_redist_root=redist, install=True)
    assert not (output / "installation-receipt.json").exists()


def test_private_runtime_mutation_before_profile_receipt_is_rejected(tmp_path, monkeypatch):
    source, checksum, output, redist, _manifest, _msvc = _no_network_preparation_fixture(tmp_path, monkeypatch)

    def corrupt_stage(*_args):
        (output / "msvc-runtime/MSVCP140.dll").write_bytes(b"corrupt")
        return [], []

    monkeypatch.setattr(adoption, "stage_wheels", corrupt_stage)
    with pytest.raises(ValueError):
        adoption.prepare(source, checksum, output, [], profile=adoption.candidate.NO_NETWORK_PROFILE,
                         msvc_redist_root=redist)
    assert not (output / "engineering-profile.json").exists()


def test_no_network_adoption_rejects_old_raster_receipt_before_output(tmp_path, monkeypatch):
    source, checksum, output, _wheel = _preparation_fixture(tmp_path, monkeypatch)
    old = tmp_path / "packaging/qt-raster-inputs.json"
    (tmp_path / "packaging/qt-raster-no-network-inputs.json").write_bytes(old.read_bytes())
    with pytest.raises(ValueError, match="receipt"):
        adoption.prepare(source, checksum, output, [], profile=adoption.candidate.NO_NETWORK_PROFILE)
    assert not output.exists()


def _coordinated_preparation_fixture(tmp_path, monkeypatch):
    source, checksum, output, redist, manifest_path, _msvc = _no_network_preparation_fixture(tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(schema=adoption.candidate.COORDINATED_SCHEMA, qt_version="6.12.1", binding_version="6.12.1",
                    binding_sip_requirement=adoption.candidate.COORDINATED_SIP_REQUIREMENT)
    for source_id, filename in (("binding-source", "pyqt6-6.12.1.tar.gz"), ("sip-source", "pyqt6_sip-13.13.1.tar.gz")):
        path = source / "inputs" / filename
        path.write_bytes(b"Inert source archive, copied only, never executed")
        manifest["inputs"].append({"id": source_id, "role": "source", "filename": filename,
                                   "url": "https://files.pythonhosted.org/" + filename, **adoption.input_pin(path)})
    sip = source / "inputs/pyqt6_sip-13.13.1-cp313-cp313-win_amd64.whl"
    wheel(sip)
    manifest["inputs"].append({"id": "sip-runtime", "role": "runtime-wheel", "package": "PyQt6-sip",
                               "version": "13.13.1", "filename": sip.name, "url": "https://files.pythonhosted.org/" + sip.name,
                               **adoption.input_pin(sip)})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    receipt_path = source / "preparation-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt.update(schema=adoption.candidate.COORDINATED_SCHEMA.replace("inputs", "preparation"),
                   manifest_sha256=adoption.sha256(manifest_path))
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return source, checksum, output, redist, manifest


def test_coordinated_profile_updates_only_binding_and_sip_and_stages_exact_sources(tmp_path, monkeypatch):
    source, checksum, output, redist, manifest = _coordinated_preparation_fixture(tmp_path, monkeypatch)
    canonical = {path: path.read_bytes() for path in (tmp_path / "requirements-locked.txt",
                 tmp_path / "packaging/third-party-components.json", tmp_path / "packaging/requirements-build-locked.txt")}
    result = adoption.prepare(source, checksum, output, [], profile=adoption.candidate.NO_NETWORK_PROFILE,
                              msvc_redist_root=redist)
    entries = {row.name: row for row in parse_release_lock_entries(output / "requirements-locked.txt")}
    assert entries["pyqt6"].version == "6.12.1" and entries["pyqt6"].hashes == (checksum,)
    sip = adoption.candidate.coordinated_runtime(manifest)
    assert entries["pyqt6-sip"].version == "13.13.1" and entries["pyqt6-sip"].hashes == (sip["sha256"],)
    assert all(path.read_bytes() == data for path, data in canonical.items())
    inventory = json.loads((output / "packaging/third-party-components.json").read_bytes())
    assert {row["name"]: row["version"] for row in inventory["runtime_components"]} == {name: row.version for name, row in entries.items()}
    assert all(row["version"] in row["homepage"] for row in inventory["runtime_components"])
    assert result["binding_sip_requirement"] == "PyQt6-sip (>=13.13, <14)"
    assert "6.12.1" in result["limitations"][1]
    for row in result["python_source_inputs"].values():
        assert (output / row["path"]).read_bytes() == (source / "inputs" / row["filename"]).read_bytes()
    assert (output / "wheelhouse" / sip["filename"]).read_bytes() == (source / "inputs" / sip["filename"]).read_bytes()


@pytest.mark.parametrize("relative", ["source-inputs/pyqt6-6.12.1.tar.gz", "source-inputs/pyqt6_sip-13.13.1.tar.gz",
                                       "wheelhouse/pyqt6_sip-13.13.1-cp313-cp313-win_amd64.whl"])
@pytest.mark.parametrize("phase", ["preparation", "installation"])
def test_coordinated_copied_sources_and_sip_are_rechecked_before_receipts(tmp_path, monkeypatch, relative, phase):
    source, checksum, output, redist, _manifest = _coordinated_preparation_fixture(tmp_path, monkeypatch)
    def mutate(*_args):
        (output / relative).write_bytes(b"changed staged input")
        return ([], []) if phase == "preparation" else {"pip_check": "passed"}
    monkeypatch.setattr(adoption, "stage_wheels" if phase == "preparation" else "install_environment", mutate)
    with pytest.raises(ValueError):
        adoption.prepare(source, checksum, output, [], profile=adoption.candidate.NO_NETWORK_PROFILE,
                         msvc_redist_root=redist, install=phase == "installation")
    assert not (output / ("engineering-profile.json" if phase == "preparation" else "installation-receipt.json")).exists()


def test_coordinated_inventory_cannot_silently_relabel_changed_canonical_metadata(tmp_path, monkeypatch):
    source, checksum, output, redist, _manifest = _coordinated_preparation_fixture(tmp_path, monkeypatch)
    path = tmp_path / "packaging/third-party-components.json"
    inventory = json.loads(path.read_bytes())
    inventory["runtime_components"][0]["version"] = "unreviewed"
    path.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ValueError, match="Canonical inventory"):
        adoption.prepare(source, checksum, output, [], profile=adoption.candidate.NO_NETWORK_PROFILE,
                         msvc_redist_root=redist)
    assert not output.exists()


@pytest.mark.parametrize("tamper", [None, "payload", "version", "wheel"])
def test_installed_sip_check_rejects_changed_bytes_or_version(tmp_path, monkeypatch, tamper):
    monkeypatch.setattr(adoption.sys, "platform", "win32")
    monkeypatch.setattr(adoption.sys, "version_info", (3, 13, 17))
    monkeypatch.setattr(adoption.candidate, "child_environment", lambda _path: {})
    commands = []
    monkeypatch.setattr(adoption.subprocess, "run", lambda args, **_kwargs: commands.append(args))
    adoption.install_environment(tmp_path, "5.8.0")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    target = tmp_path / "installed"
    target.mkdir()
    with zipfile.ZipFile(wheelhouse / "binding.whl", "w") as archive:
        archive.writestr("binding.bin", b"binding fixture")
    (target / "binding.bin").write_bytes(b"binding fixture")
    with zipfile.ZipFile(wheelhouse / "sip.whl", "w") as archive:
        archive.writestr("sip.bin", b"SIP fixture")
    (target / "sip.bin").write_bytes(b"changed" if tamper == "payload" else b"SIP fixture")
    adoption.write_json(tmp_path / "engineering-profile.json", {
        "candidate_wheel": {"path": "wheelhouse/binding.whl"},
        "sip_runtime_input": {"filename": "sip.whl", "version": "13.13.1", "sha256": adoption.sha256(wheelhouse / "sip.whl")},
    })
    if tamper == "wheel":
        with (wheelhouse / "sip.whl").open("ab") as stream:
            stream.write(b"substitution")
    distributions = {name: SimpleNamespace(metadata={"Name": name}, version="13.11.1" if tamper == "version" else "13.13.1",
                    locate_file=lambda name: target / name) for name in ("PyQt6", "PyQt6-sip")}
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: list(distributions.values()))
    monkeypatch.setattr(importlib.metadata, "distribution", lambda name: distributions[name])
    monkeypatch.setattr(adoption.sys, "argv", ["metadata-check", str(tmp_path)])
    if tamper:
        with pytest.raises(RuntimeError, match="SIP .*differs"):
            exec(commands[3][3], {})
    else:
        exec(commands[3][3], {})
