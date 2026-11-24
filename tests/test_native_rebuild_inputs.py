"""Exercise native recipe trust boundaries without launching a native tool."""
import hashlib
import io
import os
from pathlib import Path
import zipfile

import pytest

from scripts.native_rebuild import acquire_toolchain as acquire
from scripts.native_rebuild import build_iup as iup
from scripts.native_rebuild import common


def digest(raw):
    return len(raw), hashlib.sha256(raw).hexdigest()


def container(names, *, mode=0o100644):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, b"fixed input")
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


@pytest.mark.parametrize("url", [
    "http://github.com/download", "https://example.invalid/download",
    "https://github.com.evil.invalid/download", "https://user@github.com/download",
    "https://github.com:444/download", "https://github.com/download#fragment",
    "file:///compiler.zip",
])
def test_download_rejects_unapproved_url(url):
    with pytest.raises(ValueError, match="HTTPS"):
        acquire.approved(url)


@pytest.mark.parametrize("host", ["github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"])
def test_download_approved_https_hosts(host):
    assert acquire.approved("https://" + host + "/fixed.zip").hostname == host


@pytest.mark.parametrize("tail", [
    "../escape", "/absolute", "a/../b", "a//b", "C:/drive", "NUL", "a/CON.txt",
    "a/trailing.", "a/trailing ", "a/\x01b", "a/file:stream",
])
def test_toolchain_archive_rejects_unsafe_paths(tail):
    with container([acquire.NAME[:-4] + "/" + tail]) as archive:
        with pytest.raises(ValueError, match="Unsafe"):
            acquire.validated_members(archive)


def test_toolchain_archive_requires_fixed_root():
    with container(["another-root/source.c"]) as archive:
        with pytest.raises(ValueError, match="Unsafe"):
            acquire.validated_members(archive)


def test_toolchain_archive_rejects_case_aliases():
    prefix = acquire.NAME[:-4] + "/"
    with container([prefix + "Bin/clang.exe", prefix + "bin/CLANG.EXE"]) as archive:
        with pytest.raises(ValueError, match="Duplicate"):
            acquire.validated_members(archive)


@pytest.mark.parametrize("mode", [0o120777, 0o060600, 0o020600])
def test_toolchain_archive_rejects_nonregular_types(mode):
    with container([acquire.NAME[:-4] + "/file"], mode=mode) as archive:
        with pytest.raises(ValueError, match="type"):
            acquire.validated_members(archive)


def test_toolchain_archive_accepts_ordinary_pinned_root_file():
    with container([acquire.NAME[:-4] + "/bin/tool.exe"]) as archive:
        members, expanded = acquire.validated_members(archive)
    assert len(members) == 1 and expanded == len(b"fixed input")


@pytest.fixture
def patch_fixture(monkeypatch):
    before = b"    HDC hDC;\n    BITMAPINFOHEADER* bmih\nDIB_RGB_COLORS, &bits, NULL, 0x0);\n"
    after = b"    HDC hDC;\n    void* dib_bits = NULL;\n    BITMAPINFOHEADER* bmih\nDIB_RGB_COLORS, &dib_bits, NULL, 0x0);\n    bits = (BYTE*)dib_bits;\n"
    patch = b"reviewed fixture patch"
    monkeypatch.setattr(iup, "PATCH_PIN", digest(patch))
    monkeypatch.setattr(iup, "PATCH_BEFORE", digest(before))
    monkeypatch.setattr(iup, "PATCH_AFTER", digest(after))
    return {iup.PATCH_TARGET: before, "unrelated.c": b"unchanged"}, patch, after


def test_iup_patch_changes_only_the_reviewed_target(patch_fixture):
    files, patch, after = patch_fixture
    result = iup.patched_files(files, patch)
    assert result[iup.PATCH_TARGET] == after
    assert result["unrelated.c"] == files["unrelated.c"]
    assert files[iup.PATCH_TARGET] != after


def test_iup_patch_rejects_changed_patch_bytes(patch_fixture):
    files, patch, _ = patch_fixture
    with pytest.raises(ValueError, match="patch changed"):
        iup.patched_files(files, patch + b"changed")


def test_iup_patch_rejects_changed_preimage(patch_fixture):
    files, patch, _ = patch_fixture
    files[iup.PATCH_TARGET] += b"changed"
    with pytest.raises(ValueError, match="preimage"):
        iup.patched_files(files, patch)


def test_iup_patch_rejects_changed_postimage_pin(patch_fixture, monkeypatch):
    files, patch, _ = patch_fixture
    monkeypatch.setattr(iup, "PATCH_AFTER", (1, "0" * 64))
    with pytest.raises(ValueError, match="postimage"):
        iup.patched_files(files, patch)


def test_iup_source_selection_requires_reviewed_makefiles():
    with pytest.raises(ValueError, match="recipe changed"):
        iup.source_selection({"src/config.mak": b"SRC = malicious.c", "tecmakewin.mak": b"changed"})


def test_input_pin_is_derived_from_snapshot_not_later_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(iup, "ROOT", tmp_path)
    path = tmp_path / "input.c"
    path.write_bytes(b"later content")
    row = iup.snapshot_row(path, b"verified snapshot")
    assert row == {"path": "input.c", "size": 17, "sha256": hashlib.sha256(b"verified snapshot").hexdigest()}


def test_toolchain_additional_file_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "TOOLCHAIN", tmp_path / "tools")
    common.TOOLCHAIN.mkdir()
    expected = common.TOOLCHAIN / "tool.exe"
    expected.write_bytes(b"compiler")
    rows = [common.pin(expected)]
    common.verify_toolchain_tree(rows)
    (common.TOOLCHAIN / "ambient.cfg").write_bytes(b"changed flags")
    with pytest.raises(ValueError, match="unexpected"):
        common.verify_toolchain_tree(rows)


def test_hardlinked_input_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    source = tmp_path / "source"
    source.write_bytes(b"input")
    os.link(source, tmp_path / "alias")
    with pytest.raises(ValueError, match="Hardlinked"):
        common.pin(source)


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing modes")
def test_held_input_blocks_write_and_rename_then_releases(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    source = tmp_path / "source"
    source.write_bytes(b"input")
    with common.held_file(common.pin(source)):
        with pytest.raises(PermissionError):
            source.write_bytes(b"changed")
        with pytest.raises(PermissionError):
            source.rename(tmp_path / "moved")
    source.write_bytes(b"changed")
    assert source.read_bytes() == b"changed"


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing modes")
def test_held_input_rejects_stale_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    source = tmp_path / "source"
    source.write_bytes(b"input")
    row = common.pin(source)
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="pin differs"):
        with common.held_file(row):
            pytest.fail("Changed input was accepted")


def test_compiler_default_configs_disabled_and_no_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(common, "TOOLCHAIN", tmp_path / "tools")
    binary = common.TOOLCHAIN / "bin/x86_64-w64-mingw32-clang.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"inert placeholder")
    observed = {}

    def fake_run(command, **kwargs):
        observed.update(command=command, **kwargs)
        return 0

    monkeypatch.setattr(common.process, "run_owned", fake_run)
    result = common.run_tool(binary.name, ["-c", "input.c"], cwd=tmp_path, env={}, log=tmp_path / "log")
    assert observed["command"][1] == "--no-default-config"
    assert observed["timeout"] == 120
    assert result["process_ownership"]["active_processes_after_cleanup"] == 0


def test_unknown_tool_rejected_before_process_creation(tmp_path):
    with pytest.raises(ValueError, match="Unreviewed"):
        common.run_tool("cmd.exe", [], cwd=tmp_path, env={}, log=tmp_path / "log")


@pytest.mark.skipif(os.name != "nt", reason="Windows directory API")
def test_closed_environment_does_not_inherit_compiler_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setenv("CFLAGS", "untrusted flags")
    monkeypatch.setenv("SECRET_FIXTURE", "not-for-child")
    environment = common.closed_environment(tmp_path / "private")
    assert "CFLAGS" not in environment and "SECRET_FIXTURE" not in environment
    assert environment["SOURCE_DATE_EPOCH"] == "0"
    assert Path(environment["TEMP"]).is_relative_to(tmp_path)
