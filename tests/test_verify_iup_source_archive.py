"""Bound historical fulltext comparisons without turning EOL matches into rebuild proof."""
import base64
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest

from scripts import verify_iup_source_archive as review


def integer(value):
    data = [value & 127]
    while value > 127:
        value >>= 7
        data.append(128 | (value & 127))
    return bytes(reversed(data))


def delta(body):
    if not body:
        return b"SVN\0"
    instructions = b"\x80" + integer(len(body))
    return b"SVN\0" + b"".join(integer(v) for v in (0, 0, len(body), len(instructions), len(body))) + instructions + body


def request(prefix):
    root = ET.Element(review.S + "update-report", {"send-all": "true"})
    ET.SubElement(root, review.S + "src-path").text = review.SOURCE_URL + ("/" + prefix if prefix else "")
    ET.SubElement(root, review.S + "target-revision").text = str(review.REVISION)
    depth = "infinity" if prefix else "files"
    ET.SubElement(root, review.S + "depth").text = depth
    ET.SubElement(root, review.S + "entry", {"rev": str(review.REVISION), "start-empty": "true", "depth": depth})
    return ET.tostring(root)


def report(files):
    root = ET.Element(review.S + "update-report", {"send-all": "true", "inline-props": "true"})
    ET.SubElement(root, review.S + "target-revision", {"rev": str(review.REVISION)})
    directory = ET.SubElement(root, review.S + "open-directory", {"rev": str(review.REVISION)})
    for name, body in files.items():
        file = ET.SubElement(directory, review.S + "add-file", {"name": name, "sha1-checksum": hashlib.sha1(body).hexdigest()})
        ET.SubElement(file, review.S + "txdelta").text = base64.b64encode(delta(body)).decode()
        props = ET.SubElement(file, review.S + "prop")
        ET.SubElement(props, review.V + "md5-checksum").text = hashlib.md5(body).hexdigest()
    return ET.tostring(root)


def source_zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return output.getvalue()


@pytest.mark.parametrize("body", [b"", b"x", b"line\n" * 50, b"\0\xff" * 10000],
                         ids=["empty", "small", "text", "binary"])
def test_empty_source_fulltext_and_checksums_preserve_exact_binary_bytes(body):
    assert review.decode_fulltext(delta(body)) == body
    assert review.report_files(report({"example.c": body}), "src") == {"src/example.c": body}


def test_multiwindow_fulltext_retains_order():
    assert review.decode_fulltext(delta(b"first") + delta(b"second")[4:]) == b"firstsecond"


@pytest.mark.parametrize("bad", [b"", b"SVN\x01", b"SVN\0\x80", b"SVN\0\x80\0", delta(b"body")[:-1],
                               b"SVN\0\1\0\1\1\1\x81x", b"SVN\0\0\0\1\1\1\x01x",
                               b"SVN\0\0\0\1\1\1\x41x", b"SVN\0\0\0\1\1\1\xc1x",
                               b"SVN\0\0\0\1\1\2\x81xy", b"SVN\0\0\0\2\1\1\x81x"])
def test_unreviewed_svndiff_sources_versions_instructions_and_bounds_fail(bad):
    with pytest.raises(ValueError):
        review.decode_fulltext(bad)


def test_eol_correspondence_is_separate_from_exact_and_other_normalization():
    original = {"exact": b"a\n", "eol": b"a\r\nb\r\n", "space": b"a \n", "missing": b"x", "binary": b"a\0\r\n"}
    remote = {"exact": b"a\n", "eol": b"a\nb\n", "space": b"a\n", "binary": b"a\0\n"}
    rows, counts = review.compare_files(original, remote)
    assert counts == {"exact": 1, "crlf-lf-only": 1, "content-differs": 2, "missing-from-svn": 1}
    eol = next(row for row in rows if row["comparison"] == "crlf-lf-only")
    assert eol["archive"] != eol["svn"]


@pytest.mark.parametrize("change", ["revision", "duplicate", "traversal", "checksum", "md5", "operation", "delta", "doctype"])
def test_report_rejects_ambiguous_or_unreviewed_inputs(change):
    data = report({"file.c": b"code\n"})
    root = ET.fromstring(data)
    directory = root[1]
    file = directory[0]
    if change == "revision":
        root[0].set("rev", "5893")
    elif change == "duplicate":
        directory.append(ET.fromstring(ET.tostring(file)))
    elif change == "traversal":
        file.set("name", "../escape")
    elif change == "checksum":
        file.set("sha1-checksum", "0" * 40)
    elif change == "md5":
        file.find(review.S + "prop/" + review.V + "md5-checksum").text = "0" * 32
    elif change == "operation":
        ET.SubElement(directory, review.S + "delete-entry", {"name": "other"})
    elif change == "delta":
        file.find(review.S + "txdelta").text = "@@@"
    data = ET.tostring(root)
    if change == "doctype":
        data = b"<!DOCTYPE injected>" + data
    with pytest.raises(ValueError):
        review.report_files(data, "src")


def test_request_binds_revision_source_and_depth():
    review.validate_request(request("src"), "src")
    with pytest.raises(ValueError):
        review.validate_request(request("src"), "include")
    with pytest.raises(ValueError):
        review.validate_request(request(""), "src")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-16-be", "utf-32"])
def test_non_utf8_or_entity_encoded_xml_cannot_bypass_declaration_guard(encoding):
    data = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY value "expanded">]><r>&value;</r>'.encode(encoding)
    with pytest.raises(ValueError):
        review.xml(data)


@pytest.mark.parametrize("name", ["iup/../escape", "iup/CON.c", "iup//double.c", "iup/trailing./file", "outside.c"])
def test_source_zip_rejects_unsafe_names(name):
    with pytest.raises(ValueError):
        review.source_files(source_zip({name: b"data"}))


def test_source_zip_rejects_link_and_case_collisions():
    output = io.BytesIO()
    member = zipfile.ZipInfo("iup/link")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(member, b"other")
    with pytest.raises(ValueError):
        review.source_files(output.getvalue())
    with pytest.raises(ValueError):
        review.source_files(source_zip({"iup/a": b"one", "iup/A": b"two"}))


def fixture_inputs(tmp_path, monkeypatch):
    source = tmp_path / "source.zip"
    source.write_bytes(source_zip({"iup/README": b"root\n", "iup/src/example.c": b"line\r\n"}))
    monkeypatch.setattr(review, "SOURCE_PIN", (source.stat().st_size, review.digest(source.read_bytes())))
    reports = tmp_path / "reports"
    reports.mkdir()
    rows = []
    for prefix, files in (("", {"README": b"root\n", "extra.txt": b"omitted"}), ("src", {"example.c": b"line\n"})):
        name = prefix or "root"
        row = {"prefix": prefix, "method": "REPORT", "url": review.REPORT_URL, "http_status": 200}
        for field, suffix, body in (("request", "-request.xml", request(prefix)), ("response", ".xml", report(files))):
            filename = name + suffix
            (reports / filename).write_bytes(body)
            row[field] = {"path": filename, **review.pin(body)}
        rows.append(row)
    acquisition = {"schema": "dupez.iup-svn-report-acquisition.v1", "revision": review.REVISION,
                   "source_zip_sha256": review.SOURCE_PIN[1], "requests": rows, "native_execution": False,
                   "native_rebuild_performed": False, "release_approval": False}
    path = reports / "acquisition.json"
    path.write_text(json.dumps(acquisition), encoding="utf-8")
    monkeypatch.setattr(review, "ACQUISITION_PIN", (path.stat().st_size, review.digest(path.read_bytes())))
    return source, reports


def test_full_scope_receipt_distinguishes_conversion_and_native_identity(tmp_path, monkeypatch):
    source, reports = fixture_inputs(tmp_path, monkeypatch)
    result, inventory = review.run(source, reports)
    assert result["counts"] == {"exact": 1, "crlf-lf-only": 1, "content-differs": 0, "missing-from-svn": 0}
    assert result["all_archive_files_correspond_after_explicit_crlf_lf_conversion"] is True
    for key in ("all_archive_files_exact", "whole_svn_repository_exported", "dll_build_source_identity_proven",
                "native_rebuild_performed", "native_execution_performed", "complete_corresponding_source", "release_approval"):
        assert result[key] is False
    assert inventory["svn_extra_files_within_requested_scopes"][0]["path"] == "extra.txt"
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize("change", ["partial", "duplicate", "escape", "revision-bool", "approval", "path-alias"])
def test_invalid_acquisition_scope_cannot_publish_positive_result(tmp_path, monkeypatch, change):
    source, reports = fixture_inputs(tmp_path, monkeypatch)
    path = reports / "acquisition.json"
    data = json.loads(path.read_text())
    if change == "partial":
        data["requests"].pop()
    elif change == "duplicate":
        data["requests"][1] = data["requests"][0]
    elif change == "escape":
        data["requests"][0]["response"]["path"] = "../root.xml"
    elif change == "revision-bool":
        data["revision"] = True
    elif change == "approval":
        data["release_approval"] = True
    else:
        data["requests"][1]["prefix"] = "SRC"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(review, "ACQUISITION_PIN", (path.stat().st_size, review.digest(path.read_bytes())))
    with pytest.raises(ValueError):
        review.run(source, reports)


def test_input_mutation_during_comparison_fails_before_receipt(tmp_path, monkeypatch):
    source, reports = fixture_inputs(tmp_path, monkeypatch)
    compare = review.compare_files

    def mutate(*args):
        (reports / "src.xml").write_bytes(b"replaced")
        return compare(*args)

    monkeypatch.setattr(review, "compare_files", mutate)
    with pytest.raises(ValueError, match="Pinned input"):
        review.run(source, reports)


def test_cli_refuses_existing_receipts(tmp_path, monkeypatch):
    output = tmp_path / "receipt.json"
    output.write_bytes(b"existing")
    monkeypatch.setattr(sys, "argv", ["verify", "--source", "unused", "--reports", "unused", "--output", str(output),
                                    "--inventory", str(tmp_path / "inventory.json")])
    with pytest.raises(ValueError, match="Refusing to replace"):
        review.main()
    assert output.read_bytes() == b"existing"


def test_file_hardlink_is_not_an_independent_input(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"value")
    link = tmp_path / "linked"
    try:
        link.hardlink_to(source)
    except OSError:
        pytest.skip("Host does not allow hardlink fixtures")
    with pytest.raises(ValueError, match="Hardlinked"):
        review.snapshot(source, review.pin(b"value"), 100)
