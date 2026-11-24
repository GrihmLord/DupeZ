"""Keep the catalog rebuild review pinned, local, and honest about its scope."""
import argparse
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_qt_translation_sources as review


def test_changed_archive_is_rejected_before_native_inspection(tmp_path):
    archive = tmp_path / "input.7z"
    archive.write_bytes(b"other")
    with pytest.raises(ValueError, match="Pinned input"):
        review.pinned_file(archive, {"size": 5, "sha256": review.digest(b"right")})


@pytest.mark.parametrize("name", ["../escape.ts", "/absolute.ts", "C:/drive.ts", "NUL.ts"])
def test_source_archive_does_not_extract_or_accept_unsafe_names(tmp_path, name):
    path = tmp_path / "source.tar.xz"
    with tarfile.open(path, "w:xz") as archive:
        member = tarfile.TarInfo(name)
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="Unsafe"):
        review.source_files(path)
    assert not (tmp_path / "escape.ts").exists()


@pytest.mark.parametrize("kind", ["symlink", "duplicate", "oversized"])
def test_source_archive_rejects_special_duplicate_and_oversized_members(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(review, "MAX_MEMBER", 2)
    path = tmp_path / "source.tar.xz"
    with tarfile.open(path, "w:xz") as archive:
        member = tarfile.TarInfo("translations/qtbase_en.ts")
        if kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "outside"
            archive.addfile(member)
        else:
            member.size = 3 if kind == "oversized" else 1
            archive.addfile(member, io.BytesIO(b"xxx"))
            if kind == "duplicate":
                archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="Duplicate, special, or oversized"):
        review.source_files(path)


def test_generated_input_requires_reviewed_cmake_recipe(monkeypatch):
    with pytest.raises(ValueError, match="Unreviewed English"):
        review.english_recipe({"translations/CMakeLists.txt": b"unreviewed"})
    monkeypatch.setattr(review, "RECIPE_SHA256", review.digest(b"reviewed"))
    result = review.english_recipe({"translations/CMakeLists.txt": b"reviewed"})
    assert len(result) == 13
    assert result["qtbase_en.ts"] == b'<TS language="en_US"></TS>'


def test_catalog_mapping_distinguishes_generated_and_archived_inputs():
    source = {"translations/qtbase_fr.ts": b"French source"}
    generated = {"qtbase_en.ts": review.ENGLISH_TS}
    result = review.match_catalogs(source, {"qtbase_en.qm": b"english", "qtbase_fr.qm": b"french"}, generated)
    assert [r["source_kind"] for r in result] == ["generated-english-ts", "source-ts"]
    assert result[0]["ts_sha256"] == review.digest(review.ENGLISH_TS)
    assert "byte_identical" not in result[0]
    with pytest.raises(ValueError, match="Unmapped"):
        review.match_catalogs(source, {"qtbase_unknown.qm": b"x"}, generated)
    with pytest.raises(ValueError, match="Unexpected catalog"):
        review.match_catalogs(source, {"../escape.qm": b"x"}, generated)


def test_source_spdx_windows_paths_and_crlf_are_explicitly_correlated():
    sources = {".tag": b"tag\n", "src/linguist/main.cpp": b"code\n", "extra": b"extra"}
    spdx = ("FileName: ./src\\linguist\\main.cpp\nFileChecksum: SHA1: "
            + review.digest(b"code\r\n", "sha1") + "\n"
            + "FileName: ./.tag\nFileChecksum: SHA1: " + review.digest(b"different", "sha1") + "\n"
            + "FileName: ./.gitignore\nFileChecksum: SHA1: " + review.digest(b"missing", "sha1") + "\n")
    result = review.correlate_sources(sources, spdx.encode())
    assert result["crlf_matches"] == 1
    assert result["missing"] == [".gitignore"]
    assert result["mismatched"] == [".tag"]
    assert result["linguist_unmatched"] == []
    with pytest.raises(ValueError, match="Duplicate"):
        review.correlate_sources(sources, (spdx + spdx).encode())


def test_elevated_compiler_run_fails_before_loading_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(review.sys, "platform", "win32")
    monkeypatch.setattr(review.ctypes, "windll", SimpleNamespace(
        shell32=SimpleNamespace(IsUserAnAdmin=lambda: True)), raising=False)
    monkeypatch.setattr(review.candidate, "ordinary_path", lambda *_a, **_k: pytest.fail("inputs accessed"))
    with pytest.raises(ValueError, match="without elevation"):
        review.run(argparse.Namespace(run_compiler=True, output=tmp_path))


def test_existing_output_is_never_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(review.sys, "platform", "win32")
    monkeypatch.setattr(review, "ROOT", tmp_path)
    output = tmp_path / "build" / "review"
    output.mkdir(parents=True)
    marker = output / "keep.txt"
    marker.write_text("original")
    args = argparse.Namespace(run_compiler=False, candidate_root=tmp_path, tools_inputs=tmp_path, output=output)
    with pytest.raises(ValueError, match="new directory"):
        review.run(args)
    assert marker.read_text() == "original"


def test_extra_compiler_sources_and_native_files_are_fixed_pins():
    assert set(review.NATIVE_PINS) == {"lrelease.exe", "Qt6Core.dll"}
    assert len(review.EXTRA_INPUTS) == 2
    for value in review.EXTRA_INPUTS.values():
        assert value["url"].startswith("https://download.qt.io/")
        assert len(value["sha256"]) == 64
    assert Path(review.__file__).name == "verify_qt_translation_sources.py"
