"""The candidate workflow must preserve its bounded, isolated trust boundary."""
import hashlib
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import prepare_qt_candidate as candidate


def test_reviewed_manifest_is_bounded_and_keeps_candidate_scope():
    manifest = candidate.load_manifest()
    assert len(manifest["inputs"]) == 12
    assert sum(item["size"] for item in manifest["inputs"]) == 116873486
    assert "QtQml" in manifest["excluded_bindings"]
    assert "QAxContainer" in manifest["excluded_bindings"]
    assert "QtWidgets" in manifest["retained_bindings"]
    assert "production lock" in manifest["scope"]


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
