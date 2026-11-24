"""Source correspondence must not become a native rebuild attestation."""
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

from scripts import verify_qt_source_correspondence as review


REVISION = "a" * 40


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:xz") as tar:
        for name, body, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(body)
            if kind == tarfile.SYMTYPE:
                member.linkname = "elsewhere"
                tar.addfile(member)
            else:
                tar.addfile(member, io.BytesIO(body))
    return output.getvalue()


def source(*extra):
    return archive([(".tag", REVISION.encode() + b"\n", tarfile.REGTYPE), *extra])


def test_raw_and_line_ending_matches_are_distinct_and_gaps_remain_visible():
    records, revision = review.source_inventory(source(
        ("raw.cpp", b"raw\n", tarfile.REGTYPE), ("eol.cpp", b"eol\n", tarfile.REGTYPE),
        ("changed.cpp", b"current", tarfile.REGTYPE), ("unrecorded", b"extra", tarfile.REGTYPE)))
    assert revision == REVISION
    checksums = {"raw.cpp": review.digest(b"raw\n", "sha1"),
                 "eol.cpp": review.digest(b"eol\r\n", "sha1"),
                 "changed.cpp": review.digest(b"old", "sha1"), "absent": "0" * 40}
    result = review.compare_sources(records, checksums)
    assert result["raw_matches"] == result["crlf_matches"] == 1
    assert result["mismatched"] == ["changed.cpp"]
    assert result["missing"] == ["absent"]
    assert result["archive_files_without_spdx_record"] == 2
    assert not result["all_recorded_files_match_raw_or_crlf"]
    assert "native_rebuild_proven" not in result


@pytest.mark.parametrize("entries", [
    [(".tag", REVISION.encode() + b"\n", tarfile.REGTYPE)],
    [("../escape", b"x", tarfile.REGTYPE)],
    [("alias", b"", tarfile.SYMTYPE)],
    [("alias", b"", tarfile.LNKTYPE)],
])
def test_source_archive_rejects_duplicates_traversal_and_links(entries):
    with pytest.raises(ValueError):
        review.source_inventory(source(*entries))


@pytest.mark.parametrize("body", [b"", b"a" * 40, b"a" * 40 + b"\r\n", b"not a revision\n"])
def test_source_revision_is_canonical(body):
    with pytest.raises(ValueError):
        review.source_inventory(archive([(".tag", body, tarfile.REGTYPE)]))


def test_source_archive_requires_revision_and_enforces_expansion_bounds(monkeypatch):
    with pytest.raises(ValueError, match="absent"):
        review.source_inventory(archive([("plain", b"x", tarfile.REGTYPE)]))
    data = source(("plain", b"x" * 50, tarfile.REGTYPE))
    monkeypatch.setattr(review, "MAX_TOTAL", 60)
    with pytest.raises(ValueError, match="expansion"):
        review.source_inventory(data)
    monkeypatch.setattr(review, "MAX_MEMBER", 40)
    with pytest.raises(ValueError, match="oversized"):
        review.source_inventory(data)


def test_source_spdx_requires_one_checksum_per_safe_unique_path():
    block = f"FileName: .\\src\\file.cpp\nFileChecksum: SHA1: {'b' * 40}\n".encode()
    assert review.source_checksums(block) == {"src/file.cpp": "b" * 40}
    for bad in (block + block, block.replace(b".\\src\\file.cpp", b"../bad"),
                block + f"FileChecksum: SHA1: {'c' * 40}\n".encode(), b"unrelated"):
        with pytest.raises(ValueError):
            review.source_checksums(bad)


def package(name="qtbase", revision=REVISION):
    return {"name": name, "downloadLocation": "git://code.qt.io/qt/qtbase.git@" + revision}


def test_declared_core_revision_is_not_collapsed_into_root_package_revision():
    document = {"packages": [package(), package("Core", "b" * 40),
                              {"name": "Other", "downloadLocation": "NOASSERTION"}]}
    result = review.declared_revisions(json.dumps(document).encode(), "qtbase")
    assert result == {"qtbase": REVISION, "Core": "b" * 40}
    assert set(result.values()) != {REVISION}


@pytest.mark.parametrize("packages", [[], [package("Core")], [package(), package()],
                                      [package(revision="invalid")], [package(), None]])
def test_missing_duplicate_or_malformed_declared_revisions_are_rejected(packages):
    with pytest.raises(ValueError):
        review.declared_revisions(json.dumps({"packages": packages}).encode(), "qtbase")


def test_duplicate_json_keys_cannot_hide_a_different_revision():
    with pytest.raises(ValueError, match="Duplicate"):
        review.declared_revisions(b'{"packages":[],"packages":[]}', "qtbase")


def test_repository_url_without_revision_is_explicit_missing_evidence():
    document = {"packages": [{"name": "qtimageformats", "versionInfo": "6.12.1",
                               "downloadLocation": "git://code.qt.io/qt/qtimageformats.git"}]}
    result = review.declared_revisions(json.dumps(document).encode(), "qtimageformats")
    assert result == {"qtimageformats": None}
    assert set(result.values()) != {REVISION}


def test_pinned_snapshot_cannot_be_replaced_between_hash_and_source_parsing(tmp_path):
    path = tmp_path / "source.tar.xz"
    original = source()
    pin = {"size": len(original), "sha256": review.digest(original)}
    path.write_bytes(original)
    captured = review.snapshot(path, pin)
    path.write_bytes(b"changed")
    assert review.source_inventory(captured)[1] == REVISION
    with pytest.raises(ValueError, match="size"):
        review.snapshot(path, pin)
    path.write_bytes(b"x" * len(original))
    with pytest.raises(ValueError, match="differs"):
        review.snapshot(path, pin)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing contract")
@pytest.mark.parametrize("has_source", [True, False])
def test_binary_metadata_holds_verified_read_lock_until_all_tar_reads_finish(tmp_path, monkeypatch, has_source):
    path = tmp_path / "archive.7z"
    original = b"inert archive fixture"
    path.write_bytes(original)
    pin = {"size": len(original), "sha256": review.digest(original)}
    events = []

    def inspect(*_args):
        with pytest.raises(OSError):
            path.write_bytes(b"replaced")
        with pytest.raises(OSError):
            path.unlink()
        events.append("listing")
        return {"sbom/qtbase-6.12.1.source.spdx": "-"} if has_source else {}

    def read(_tar, actual, member, _env):
        assert actual == path and path.read_bytes() == original
        with pytest.raises(OSError):
            path.write_bytes(b"substitute and restore")
        events.append(member)
        return member.encode()

    monkeypatch.setattr(review.candidate, "inspect_7z", inspect)
    monkeypatch.setattr(review, "archive_member", read)
    source_spdx, binary_spdx = review.binary_metadata(Path("tar.exe"), path, pin, "qtbase", "6.12.1", {})
    assert source_spdx == (b"sbom/qtbase-6.12.1.source.spdx" if has_source else None)
    assert binary_spdx == b"sbom/qtbase-6.12.1.spdx.json"
    assert events[0] == "listing" and len(events) == (3 if has_source else 2)
    path.write_bytes(b"changed after release")
    with pytest.raises(RuntimeError, match="identity|bytes"):
        review.binary_metadata(Path("tar.exe"), path, pin, "qtbase", "6.12.1", {})
