"""The candidate workflow must preserve its bounded, isolated trust boundary."""
import hashlib
import base64
import csv
import io
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import prepare_qt_candidate as candidate


def test_reviewed_manifest_is_bounded_and_keeps_candidate_scope():
    manifest = candidate.load_manifest()
    assert len(manifest["inputs"]) == 16
    assert sum(item["size"] for item in manifest["inputs"]) == 123517354
    assert "QtQml" in manifest["excluded_bindings"]
    assert "QAxContainer" in manifest["excluded_bindings"]
    assert "QtWidgets" in manifest["retained_bindings"]
    assert "production lock" in manifest["scope"]
    assert [name for name in manifest["retained_plugins"] if name.startswith("tls/")] == ["tls/qschannelbackend.dll"]
    assert len(manifest["translation_locales"]) == 33


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/drive", "dir\\escape",
                                      "a/./b", "a//b", "NUL.dll", "dir/file.", "dir/file "])
def test_archive_paths_reject_windows_escape_and_aliases(name):
    with pytest.raises(ValueError):
        candidate.safe_member(name)


@pytest.mark.parametrize("url", ["http://download.qt.io/a", "https://localhost/a",
                                     "https://download.qt.io@evil.test/a", "https://download.qt.io/a?x=1",
                                     "https://download.qt.io:8443/a"])
def test_download_and_redirect_routes_are_restricted(url):
    with pytest.raises(ValueError):
        candidate.check_url(url)


def test_poisoned_cache_is_rejected_before_copy_or_network(tmp_path, monkeypatch):
    (tmp_path / "input.whl").write_bytes(b"bad")
    item = {"filename": "input.whl", "size": 3, "sha256": hashlib.sha256(b"yes").hexdigest()}
    monkeypatch.setattr(candidate.urllib.request, "build_opener", lambda *_: pytest.fail("network attempted"))
    with pytest.raises(ValueError, match="SHA256"):
        candidate.fetch(item, tmp_path / "destination.whl", tmp_path)
    assert not (tmp_path / "destination.whl").exists()


def test_7z_special_entries_rejected_before_extraction(tmp_path, monkeypatch):
    listing = b"bin/Qt6Core.dll\n"
    values = iter([listing, b"lrwxrwxrwx  0 0 0 100 Oct 20 12:00 bin/Qt6Core.dll\n"])
    monkeypatch.setattr(candidate.subprocess, "run", lambda *_a, **_k: SimpleNamespace(stdout=next(values)))
    item = {"members": 1, "member_listing_sha256": hashlib.sha256(listing).hexdigest()}
    with pytest.raises(ValueError, match="special entry"):
        candidate.inspect_7z(tmp_path / "binary.7z", item, Path("tar.exe"))


def test_wheel_symlinks_rejected(tmp_path):
    path = tmp_path / "bad.whl"
    with zipfile.ZipFile(path, "w") as archive:
        member = zipfile.ZipInfo("PyQt6/link")
        member.create_system = 3
        member.external_attr = 0o120777 << 16
        archive.writestr(member, "outside")
    with pytest.raises(ValueError, match="symlinks"):
        candidate.inspect_wheel(path)


def test_existing_output_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate, "ROOT", tmp_path)
    monkeypatch.setattr(candidate.sys, "platform", "win32")
    monkeypatch.setattr(candidate.sys, "version_info", (3, 13))
    output = tmp_path / "build" / "candidate"
    output.mkdir(parents=True)
    marker = output / "keep.txt"
    marker.write_text("preserve")
    with pytest.raises(ValueError, match="fresh directory"):
        candidate.prepare(output, None, True, False)
    assert marker.read_text() == "preserve"


@pytest.mark.parametrize("url", ["https://download.qt.io/a%2fb", "https://download.qt.io/a\\b",
                                     "https://download.qt.io/a\nb", " https://download.qt.io/a"])
def test_url_parser_cannot_normalize_away_encoded_or_control_inputs(url):
    with pytest.raises(ValueError):
        candidate.check_url(url)


def test_unresolved_junction_ancestor_is_rejected(tmp_path, monkeypatch):
    junction = tmp_path / "junction"
    junction.mkdir()
    original = Path.lstat

    def lstat(path):
        if path == junction:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path)

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError, match="Reparse"):
        candidate.ordinary_path(junction / "not-created", missing=True)


def test_child_environment_does_not_inherit_secrets_or_os_overrides(tmp_path, monkeypatch):
    system, windows = tmp_path / "System32", tmp_path / "Windows"
    system.mkdir()
    windows.mkdir()
    monkeypatch.setattr(candidate, "system_directory", lambda name="GetSystemDirectoryW": system if name == "GetSystemDirectoryW" else windows)
    for name in ("GH_TOKEN", "AWS_SECRET_ACCESS_KEY", "DUPEZ_UPDATE_PRIVATE_KEY", "HTTPS_PROXY", "PYTHONPATH", "SystemRoot"):
        monkeypatch.setenv(name, "untrusted-parent-value")
    env = candidate.child_environment(tmp_path / "private")
    assert env["SystemRoot"] == str(windows)
    assert env["PIP_CONFIG_FILE"] == candidate.os.devnull
    assert "untrusted-parent-value" not in env.values()
    assert not any(name in env for name in ("GH_TOKEN", "AWS_SECRET_ACCESS_KEY", "DUPEZ_UPDATE_PRIVATE_KEY", "HTTPS_PROXY", "PYTHONPATH"))


@pytest.mark.parametrize("existing,new", [({"bin/a.dll": "-"}, {"bin/a.dll": "-"}),
                                            ({"bin": "-"}, {"bin/a.dll": "-"}),
                                            ({"bin/a.dll": "-"}, {"bin": "-"}),
                                            ({}, {"bin": "-", "bin/a.dll": "-"})])
def test_archive_namespaces_never_overlay_files(existing, new):
    with pytest.raises(ValueError):
        candidate.merge_namespace(existing, new)


@pytest.mark.parametrize("names,kind", [(["PyQt6/A", "PyQt6/a"], stat.S_IFREG),
                                          (["PyQt6/pipe"], stat.S_IFIFO)])
def test_wheel_case_collision_and_special_types_fail(tmp_path, names, kind):
    path = tmp_path / "bad.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (kind | 0o644) << 16
            archive.writestr(info, b"value")
    with pytest.raises(ValueError):
        candidate.inspect_wheel(path)


@pytest.mark.parametrize("field", ["qt_version", "binding_version"])
@pytest.mark.parametrize("value", ["../outside", "C:/outside", "6.11.3/child", "6.11.3\n", "06.11.3", "--help", 6113])
def test_versions_are_validated_before_constructing_paths(tmp_path, field, value):
    manifest = candidate.load_manifest()
    manifest[field] = value
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Non-canonical"):
        candidate.load_manifest(path)
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("field,value", [("excluded_bindings", ["--qt-dir", "../outside"]),
                                           ("retained_bindings", ["QtUnknownModule"]),
                                           ("excluded_bindings", ["QtXml", "QtXml"]),
                                           ("excluded_bindings", "QtXml")])
def test_module_names_and_partition_are_schema_checked(tmp_path, field, value):
    manifest = candidate.load_manifest()
    manifest[field] = value
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="module"):
        candidate.load_manifest(path)


def test_unknown_and_duplicate_manifest_fields_fail(tmp_path):
    path = tmp_path / "candidate.json"
    manifest = candidate.load_manifest()
    manifest["unexpected"] = "value"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unknown"):
        candidate.load_manifest(path)
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError, match="Duplicate"):
        candidate.load_manifest(path)


def test_receipt_binds_initial_manifest_bytes_even_if_file_changes(tmp_path, monkeypatch):
    manifest = candidate.load_manifest()
    manifest_path = tmp_path / "candidate.json"
    original = (json.dumps(manifest, indent=3) + "\n").encode()
    manifest_path.write_bytes(original)
    monkeypatch.setattr(candidate, "ROOT", tmp_path)
    monkeypatch.setattr(candidate, "MANIFEST", manifest_path)
    monkeypatch.setattr(candidate.sys, "platform", "win32")
    monkeypatch.setattr(candidate.sys, "version_info", (3, 13))

    def fake_fetch(_item, destination, _cache):
        manifest_path.write_text("{}")
        destination.write_bytes(b"test-only fetch stub")

    monkeypatch.setattr(candidate, "fetch", fake_fetch)
    receipt = candidate.prepare(tmp_path / "build" / "candidate", None, True, False)
    assert receipt["manifest_sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["manifest_sha256"] != hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert receipt["inputs"] == manifest["inputs"]


def _profile_payloads(manifest):
    names = {f"PyQt6/{name}.pyd" for name in manifest["retained_bindings"]}
    names |= {f"PyQt6/Qt6/bin/Qt6{name[2:]}.dll" for name in manifest["retained_bindings"]}
    names |= {"PyQt6/Qt6/bin/d3dcompiler_47.dll", "PyQt6/Qt6/bin/opengl32sw.dll"}
    names |= {"PyQt6/Qt6/plugins/" + name for name in manifest["retained_plugins"]}
    names |= {f"PyQt6/Qt6/translations/qtbase_{name}.qm" for name in manifest["translation_locales"]}
    payloads = {name: b"test-only payload, never executed" for name in names}
    payloads["pyqt6-6.11.0.dist-info/METADATA"] = b"Name: PyQt6\nVersion: 6.11.0\nRequires-Dist: PyQt6-sip (>=13.8, <14)\n"
    payloads["pyqt6-6.11.0.dist-info/WHEEL"] = b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp310-abi3-win_amd64\n"
    payloads["pyqt6-6.11.0.dist-info/licenses/LICENSE"] = b"license preserved"
    return payloads


def _write_recorded_wheel(path, payloads, *, corrupt_record=False):
    record = "pyqt6-6.11.0.dist-info/RECORD"
    content = io.StringIO(newline="")
    writer = csv.writer(content, lineterminator="\n")
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
            digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
            writer.writerow([name, "sha256=" + digest, len(payload) + int(corrupt_record)])
        writer.writerow([record, "", ""])
        archive.writestr(record, content.getvalue())


def test_restriction_removes_unsupported_bindings_and_backends_preserving_metadata(tmp_path):
    manifest = candidate.load_manifest()
    payloads = _profile_payloads(manifest)
    omitted = {"PyQt6/QtQml.pyd", "PyQt6/QtQml.pyi", "PyQt6/bindings/QtQml/QtQml.toml",
               "PyQt6/Qt6/plugins/tls/qopensslbackend.dll", "PyQt6/Qt6/plugins/tls/qcertonlybackend.dll",
               "PyQt6/Qt6/plugins/sqldrivers/qsqlite.dll", "PyQt6/uic/widget-plugins/qtquickwidgets.py",
               "PyQt6/Qt6/translations/qtdeclarative_en.qm"}
    payloads.update({name: b"unsupported" for name in omitted})
    source, output = tmp_path / "input.whl", tmp_path / "output.whl"
    _write_recorded_wheel(source, payloads)
    receipt = candidate.restrict_candidate_wheel(source, output, manifest)
    assert set(receipt["removed_members"]) == omitted
    assert receipt["inventory"]["wheel_record_verified"]
    assert len(receipt["inventory"]["native_members"]) == 39
    with zipfile.ZipFile(output) as archive:
        for name, payload in payloads.items():
            if name not in omitted:
                assert archive.read(name) == payload


@pytest.mark.parametrize("name", ["PyQt6/Qt6/bin/Qt6Qml.dll", "PyQt6/Qt6/bin/unknown.exe",
                                  "PyQt6/Qt6/plugins/tls/qopensslbackend.dll", "PyQt6/QtQml.pyd",
                                  "PyQt6/Qt6/qml/unsafe.qml", "PyQt6/uic/widget-plugins/qtquickwidgets.py",
                                  "PyQt6/Qt6/translations/qtbase_unknown.qm"])
def test_candidate_inventory_rejects_unreviewed_or_disabled_payload(tmp_path, name):
    manifest = candidate.load_manifest()
    payloads = _profile_payloads(manifest)
    payloads[name] = b"unexpected"
    wheel = tmp_path / "candidate.whl"
    _write_recorded_wheel(wheel, payloads)
    with pytest.raises(ValueError):
        candidate.validate_candidate_wheel(wheel, manifest)


def test_required_native_plugin_cannot_silently_disappear(tmp_path):
    manifest = candidate.load_manifest()
    payloads = _profile_payloads(manifest)
    del payloads["PyQt6/Qt6/plugins/imageformats/qwebp.dll"]
    wheel = tmp_path / "candidate.whl"
    _write_recorded_wheel(wheel, payloads)
    with pytest.raises(ValueError, match="native inventory"):
        candidate.validate_candidate_wheel(wheel, manifest)


def test_restriction_does_not_repair_or_hide_invalid_original_record(tmp_path):
    manifest = candidate.load_manifest()
    source, output = tmp_path / "input.whl", tmp_path / "output.whl"
    _write_recorded_wheel(source, _profile_payloads(manifest), corrupt_record=True)
    with pytest.raises(ValueError, match="RECORD mismatch"):
        candidate.restrict_candidate_wheel(source, output, manifest)
    assert not output.exists()


def test_unknown_native_is_rejected_instead_of_silently_pruned(tmp_path):
    manifest = candidate.load_manifest()
    payloads = _profile_payloads(manifest)
    payloads["PyQt6/Qt6/plugins/tls/unreviewed.dll"] = b"unknown"
    source, output = tmp_path / "input.whl", tmp_path / "output.whl"
    _write_recorded_wheel(source, payloads)
    with pytest.raises(ValueError, match="native inventory"):
        candidate.restrict_candidate_wheel(source, output, manifest)


def test_external_qt_metadata_is_not_fabricated_away(tmp_path):
    manifest = candidate.load_manifest()
    payloads = _profile_payloads(manifest)
    payloads["pyqt6-6.11.0.dist-info/METADATA"] += b"Requires-Dist: PyQt6-Qt6 (>=6.11.0)\n"
    source, output = tmp_path / "input.whl", tmp_path / "output.whl"
    _write_recorded_wheel(source, payloads)
    with pytest.raises(ValueError, match="metadata"):
        candidate.restrict_candidate_wheel(source, output, manifest)


def test_upstream_windows_record_self_path_is_canonicalized_only_for_self(tmp_path):
    manifest = candidate.load_manifest()
    path = tmp_path / "candidate.whl"
    _write_recorded_wheel(path, _profile_payloads(manifest))
    with zipfile.ZipFile(path) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    record = "pyqt6-6.11.0.dist-info/RECORD"
    payloads[record] = payloads[record].replace((record + ",,\n").encode(), (record.replace("/", "\\") + ",,\n").encode())
    alternate = tmp_path / "upstream.whl"
    with zipfile.ZipFile(alternate, "w") as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    assert candidate.validate_candidate_wheel(alternate, manifest)["wheel_record_verified"]
    payloads[record] = payloads[record].replace(b"PyQt6/QtCore.pyd", b"PyQt6\\QtCore.pyd")
    invalid = tmp_path / "invalid.whl"
    with zipfile.ZipFile(invalid, "w") as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="RECORD"):
        candidate.validate_candidate_wheel(invalid, manifest)


def test_restriction_produces_stable_bytes_for_identical_payload(tmp_path):
    manifest = candidate.load_manifest()
    source = tmp_path / "input.whl"
    _write_recorded_wheel(source, _profile_payloads(manifest))
    first, second = tmp_path / "first.whl", tmp_path / "second.whl"
    candidate.restrict_candidate_wheel(source, first, manifest)
    candidate.restrict_candidate_wheel(source, second, manifest)
    assert first.read_bytes() == second.read_bytes()


def test_other_distribution_metadata_cannot_be_smuggled_in(tmp_path):
    manifest = candidate.load_manifest()
    payloads = _profile_payloads(manifest)
    payloads["pyqt6_qt6-6.11.3.dist-info/METADATA"] = b"Name: PyQt6-Qt6\nVersion: 6.11.3\n"
    wheel = tmp_path / "candidate.whl"
    _write_recorded_wheel(wheel, payloads)
    with pytest.raises(ValueError, match="distribution root"):
        candidate.validate_candidate_wheel(wheel, manifest)


def test_manifest_cannot_reenable_a_browser_binding(tmp_path):
    manifest = candidate.load_manifest()
    manifest["retained_bindings"].append("QtQml")
    manifest["excluded_bindings"].remove("QtQml")
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="module partition"):
        candidate.load_manifest(path)


@pytest.mark.parametrize("field,value", [("retained_plugins", ["tls/qopensslbackend.dll"]),
                                           ("translation_locales", ["../outside"]),
                                           ("translation_locales", ["en", "en"])])
def test_plugin_and_translation_manifest_profiles_are_checked(tmp_path, field, value):
    manifest = candidate.load_manifest()
    manifest[field] = value
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        candidate.load_manifest(path)


def _origin_fixture(tmp_path, monkeypatch):
    """Real pinned files/ZIP plus a data-only stand-in for the system 7z reader."""
    manifest = candidate.load_manifest()
    payloads = _profile_payloads(manifest)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    grouped = {role: {} for role in ("binding-wheel", "qt-prefix", "qt-helper")}
    for name, value in payloads.items():
        if name.startswith("PyQt6/Qt6/"):
            member = name.removeprefix("PyQt6/Qt6/")
            role = "qt-prefix"
            if member in {"bin/opengl32sw.dll", "bin/d3dcompiler_47.dll"}:
                member, role = Path(member).name, "qt-helper"
        elif name.endswith(".pyd"):
            member, role = name, "binding-wheel"
        else:
            continue
        grouped[role][member] = value.decode()
    manifest["inputs"] = []
    for role, members in grouped.items():
        path = inputs / (role + (".whl" if role == "binding-wheel" else ".7z"))
        if role == "binding-wheel":
            with zipfile.ZipFile(path, "w") as archive:
                for name, value in members.items():
                    archive.writestr(name, value)
        else:
            path.write_text(json.dumps(members))
        manifest["inputs"].append({"id": role, "role": role, "filename": path.name,
                                   "size": path.stat().st_size,
                                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    monkeypatch.setattr(candidate, "inspect_7z", lambda path, *_args:
                        {name.casefold(): "-" for name in json.loads(path.read_text())})

    def read_archive(argv, **_kwargs):
        assert argv[:2] == ["tar.exe", "-xOf"]
        return SimpleNamespace(stdout=json.loads(Path(argv[2]).read_text())[argv[3]].encode())

    monkeypatch.setattr(candidate.subprocess, "run", read_archive)
    wheel = tmp_path / "candidate.whl"
    _write_recorded_wheel(wheel, payloads)
    return manifest, inputs, wheel, payloads


def test_candidate_origin_map_covers_every_native_and_catalog(tmp_path, monkeypatch):
    manifest, inputs, wheel, _ = _origin_fixture(tmp_path, monkeypatch)
    result = candidate.verify_candidate_origins(wheel, manifest, inputs, Path("tar.exe"))
    assert result["native_count"] == 39
    assert result["translation_count"] == 33
    assert len(result["members"]) == 72
    assert {entry["input_id"] for entry in result["members"]} == {"binding-wheel", "qt-prefix", "qt-helper"}
    assert not result["corresponding_source_rebuild_proven"]


@pytest.mark.parametrize("name", ["PyQt6/QtCore.pyd", "PyQt6/Qt6/bin/Qt6Core.dll",
                                  "PyQt6/Qt6/bin/opengl32sw.dll",
                                  "PyQt6/Qt6/plugins/tls/qschannelbackend.dll",
                                  "PyQt6/Qt6/translations/qtbase_en.qm"])
def test_recomputed_record_cannot_conceal_substituted_upstream_bytes(tmp_path, monkeypatch, name):
    manifest, inputs, wheel, payloads = _origin_fixture(tmp_path, monkeypatch)
    payloads[name] = b"substituted with a consistent new RECORD"
    _write_recorded_wheel(wheel, payloads)
    assert candidate.validate_candidate_wheel(wheel, manifest)["wheel_record_verified"]
    with pytest.raises(ValueError, match="bytes differ from pinned origin"):
        candidate.verify_candidate_origins(wheel, manifest, inputs, Path("tar.exe"))


@pytest.mark.parametrize("duplicate", [False, True])
def test_candidate_origins_must_be_present_and_unambiguous(tmp_path, monkeypatch, duplicate):
    manifest, inputs, wheel, _ = _origin_fixture(tmp_path, monkeypatch)
    prefix = next(item for item in manifest["inputs"] if item["role"] == "qt-prefix")
    if duplicate:
        manifest["inputs"].append({**prefix, "id": "duplicate-prefix"})
    else:
        manifest["inputs"].remove(prefix)
    with pytest.raises(ValueError, match="exactly one pinned origin"):
        candidate.verify_candidate_origins(wheel, manifest, inputs, Path("tar.exe"))


def test_corrupt_origin_input_fails_before_archive_reader(tmp_path, monkeypatch):
    manifest, inputs, wheel, _ = _origin_fixture(tmp_path, monkeypatch)
    (inputs / manifest["inputs"][0]["filename"]).write_bytes(b"bad")
    monkeypatch.setattr(candidate.subprocess, "run", lambda *_a, **_k: pytest.fail("read unpinned input"))
    with pytest.raises(ValueError, match="input size"):
        candidate.verify_candidate_origins(wheel, manifest, inputs, Path("tar.exe"))


def test_input_changed_during_origin_comparison_invalidates_receipt(tmp_path, monkeypatch):
    manifest, inputs, wheel, _ = _origin_fixture(tmp_path, monkeypatch)
    reader = candidate.subprocess.run

    def mutate_after_read(argv, **kwargs):
        result = reader(argv, **kwargs)
        # Whitespace preserves the fake archive's contents while changing its pin.
        with Path(argv[2]).open("a") as output:
            output.write(" ")
        return result

    monkeypatch.setattr(candidate.subprocess, "run", mutate_after_read)
    with pytest.raises(ValueError, match="input size"):
        candidate.verify_candidate_origins(wheel, manifest, inputs, Path("tar.exe"))


def test_candidate_changed_after_member_comparison_invalidates_origin_receipt(tmp_path, monkeypatch):
    manifest, inputs, wheel, payloads = _origin_fixture(tmp_path, monkeypatch)
    reader = candidate.subprocess.run
    reads = []
    member = "PyQt6/Qt6/bin/Qt6Core.dll"

    def change_already_compared_member(argv, **kwargs):
        result = reader(argv, **kwargs)
        reads.append(argv[3])
        if len(reads) == 2:
            # Qt6Core was already compared. Keep ZIP offsets and payload sizes
            # stable, and regenerate a valid RECORD: neither later member reads
            # nor a fresh internal-consistency check detects the stale proof.
            assert reads[0] == "bin/Qt6Core.dll"
            payloads[member] = b"X" * len(payloads[member])
            _write_recorded_wheel(wheel, payloads)
        return result

    monkeypatch.setattr(candidate.subprocess, "run", change_already_compared_member)
    with pytest.raises(ValueError, match="Candidate wheel changed"):
        candidate.verify_candidate_origins(wheel, manifest, inputs, Path("tar.exe"))
    assert len(reads) >= 2
    assert candidate.validate_candidate_wheel(wheel, manifest)["wheel_record_verified"]
