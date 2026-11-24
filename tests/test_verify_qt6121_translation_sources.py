"""Keep the versioned compiler recipe pinned and its execution scope explicit."""
import argparse
from contextlib import ExitStack
import io
import json
import tarfile
import sys
from types import SimpleNamespace

import pytest

from scripts import verify_qt6121_translation_sources as review


def signature_rows():
    return [{"name": name, "status": "Valid", "thumbprint": thumbprint,
             "file_version": "6.12.1.0" if name in {"lrelease.exe", "Qt6Core.dll"} else "14.51.36247.0",
             "subject": "O=The QT Company Oy" if name in {"lrelease.exe", "Qt6Core.dll"} else "O=Microsoft Corporation"}
            for name, thumbprint in review.SIGNERS.items()]


def test_exact_signatures_cover_all_seven_files():
    assert {row["name"] for row in review.validate_signatures(signature_rows())} == set(review.SIGNERS)


@pytest.mark.parametrize("field,value", [
    ("status", "NotSigned"), ("thumbprint", "0" * 40), ("subject", "O=Unknown Publisher"),
    ("file_version", "6.11.3.0"), ("name", "unexpected.dll"),
])
def test_signature_identity_changes_are_rejected(field, value):
    rows = signature_rows()
    rows[0][field] = value
    with pytest.raises(ValueError):
        review.validate_signatures(rows)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "extra", "object"])
def test_signature_set_cannot_hide_unverified_tool_files(kind):
    rows = signature_rows()
    if kind == "missing":
        rows.pop()
    elif kind == "duplicate":
        rows[-1] = rows[0]
    elif kind == "extra":
        rows.append(rows[0])
    else:
        rows = {"rows": rows}
    with pytest.raises(ValueError):
        review.validate_signatures(rows)


def catalog_document():
    return {"files": [{"fileName": f"./translations/catalog_{index}.qm", "checksums": [
        {"algorithm": "SHA1", "checksumValue": "a" * 40}]} for index in range(314)]}


def test_matching_debug_release_rows_coalesce_and_conflicts_fail():
    document = catalog_document()
    document["files"].append(json.loads(json.dumps(document["files"][0])))
    assert len(review.catalog_checksums(document)) == 314
    document["files"][-1]["checksums"][0]["checksumValue"] = "b" * 40
    with pytest.raises(ValueError, match="Conflicting"):
        review.catalog_checksums(document)


@pytest.mark.parametrize("name", ["./translations/../escape.qm", "./translations/nested/catalog.qm", "./translations/NUL.qm"])
def test_catalog_paths_cannot_escape_reference_directory(name):
    document = catalog_document()
    document["files"][0]["fileName"] = name
    with pytest.raises(ValueError):
        review.catalog_checksums(document)


def test_missing_catalog_and_ambiguous_checksum_fail():
    document = catalog_document()
    document["files"].pop()
    with pytest.raises(ValueError, match="catalog set"):
        review.catalog_checksums(document)
    document = catalog_document()
    document["files"][0]["checksums"].append(document["files"][0]["checksums"][0])
    with pytest.raises(ValueError, match="checksum"):
        review.catalog_checksums(document)


def test_native_tool_directory_is_closed_and_pinned(tmp_path):
    path = tmp_path / "lrelease.exe"
    path.write_bytes(b"inert compiler fixture")
    pins = {path.name: review.pin_bytes(path.read_bytes())}
    review.validate_tool(tmp_path, pins)
    (tmp_path / "qt.conf").write_bytes(b"unreviewed configuration")
    with pytest.raises(ValueError, match="extra"):
        review.validate_tool(tmp_path, pins)
    (tmp_path / "qt.conf").unlink()
    path.write_bytes(b"changed compiler")
    with pytest.raises(ValueError, match="byte pin"):
        review.validate_tool(tmp_path, pins)


def test_native_tool_hardlink_is_rejected(tmp_path):
    original = tmp_path / "original"
    original.write_bytes(b"inert native fixture")
    tool = tmp_path / "tool"
    tool.mkdir()
    linked = tool / "lrelease.exe"
    try:
        linked.hardlink_to(original)
    except OSError:
        pytest.skip("Host denies the hardlink fixture")
    with pytest.raises(ValueError, match="hard links"):
        review.validate_tool(tool, {linked.name: review.pin_bytes(original.read_bytes())})


def test_source_declared_revision_must_match_version_repository_and_tag():
    tag = "a" * 40
    document = {"packages": [{"name": "lrelease", "versionInfo": "6.12.1",
                              "downloadLocation": "git://code.qt.io/qt/qttools.git@" + tag}]}
    assert review.verify_declared_revision(document, "lrelease", "qttools", tag)["source_commit"] == tag
    with pytest.raises(ValueError, match="declared revision"):
        review.verify_declared_revision(document, "lrelease", "qtbase", tag)
    document["packages"].append(document["packages"][0])
    with pytest.raises(ValueError, match="declared revision"):
        review.verify_declared_revision(document, "lrelease", "qttools", tag)


@pytest.mark.parametrize("body", [b"not-a-revision", b"A" * 40, b"a" * 40 + b"/path"])
def test_source_tag_rejects_noncanonical_revision(tmp_path, body):
    path = tmp_path / "source.tar.xz"
    with tarfile.open(path, "w:xz") as archive:
        member = tarfile.TarInfo(".tag")
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))
    with pytest.raises(ValueError, match="source revision"):
        review.source_tag(path)


def test_elevated_execution_stops_before_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(review.sys, "platform", "win32")
    monkeypatch.setattr(review.ctypes, "windll", SimpleNamespace(
        shell32=SimpleNamespace(IsUserAnAdmin=lambda: True)), raising=False)
    monkeypatch.setattr(review.candidate, "ordinary_path", lambda *_a, **_k: pytest.fail("inputs accessed"))
    with pytest.raises(ValueError, match="without elevation"):
        review.run(argparse.Namespace(run_compiler=True))


def test_existing_output_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(review.sys, "platform", "win32")
    monkeypatch.setattr(review, "ROOT", tmp_path)
    output = tmp_path / "build" / "result"
    output.mkdir(parents=True)
    (output / "keep").write_bytes(b"preserve")
    with pytest.raises(ValueError, match="new directory"):
        review.run(argparse.Namespace(run_compiler=False, inputs=tmp_path, output=output))
    assert (output / "keep").read_bytes() == b"preserve"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing-lock contract")
def test_held_input_lock_allows_read_but_rejects_write_delete_and_swap(tmp_path):
    path = tmp_path / "inert-input.bin"
    path.write_bytes(b"expected immutable bytes")
    pin = review.pin_bytes(path.read_bytes())
    with ExitStack() as locks:
        review.lock_input(locks, path, pin)
        assert path.read_bytes() == b"expected immutable bytes"
        with pytest.raises(OSError):
            path.write_bytes(b"replaced")
        with pytest.raises(OSError):
            path.unlink()
        with pytest.raises(OSError):
            path.rename(tmp_path / "moved.bin")
    path.write_bytes(b"write permitted after close")
    assert path.read_bytes() == b"write permitted after close"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing-lock contract")
def test_lock_rejects_wrong_bytes_before_consumer_runs(tmp_path):
    path = tmp_path / "input.bin"
    path.write_bytes(b"wrong")
    with ExitStack() as locks, pytest.raises(RuntimeError):
        review.lock_input(locks, path, review.pin_bytes(b"right"))
