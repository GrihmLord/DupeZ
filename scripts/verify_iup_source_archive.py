#!/usr/bin/env python3
"""Compare every retained IUP 3.30 source file with pinned SVN r5892 reports.

Offline and bounded: inspect source as data, never extract or execute it. Exact
bytes and CRLF/LF-only correspondence remain separate observations. Neither
establishes the compiler inputs or reproducibility of the shipped native DLL.
"""
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET
import zipfile

REVISION = 5892
SOURCE_PIN = (14226631, "92e1b56a6c78eeaca7cce3897536d333787e27e3ec25f94487dd0ab1d8d053e6")
ACQUISITION_PIN = (15048, "05946fd01c3dc7e6dc1e42e4d592a984e684c4506bf953c3c099827d0809f5ad")
REPORT_URL = "https://svn.code.sf.net/p/iup/iup/!svn/vcc/default"
SOURCE_URL = "https://svn.code.sf.net/p/iup/iup/trunk/iup"
S, D, V = "{svn:}", "{DAV:}", "{http://subversion.tigris.org/xmlns/dav/}"
MAX_FILE = 8 * 1024 * 1024
MAX_REPORT = 128 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_ENTRIES = 4000


def require(value, message: str) -> None:
    if not value:
        raise ValueError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pin(data: bytes) -> dict:
    return {"size": len(data), "sha256": digest(data)}


def safe_name(name: str) -> str:
    require(isinstance(name, str) and 0 < len(name) <= 512, "Invalid source name")
    require(not any(ord(c) < 32 or c in "\\:%" for c in name), "Unsafe source name")
    parts = name.split("/")
    require(all(p not in {"", ".", ".."} and not p.endswith((".", " "))
                and not re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?", p, re.I)
                for p in parts), "Unsafe source path component")
    return name


def ordinary(path: Path, *, missing=False) -> Path:
    path = Path(os.path.abspath(path))
    for item in (*reversed(path.parents), path):
        if missing and item == path and not os.path.lexists(item):
            continue
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "Links and reparse paths are not source evidence")
        require(stat.S_ISDIR(info.st_mode) if item != path else stat.S_ISREG(info.st_mode),
                "Unexpected source evidence path type")
        if item == path:
            require(info.st_nlink == 1, "Hardlinked source evidence is not accepted")
    return path


def snapshot(path: Path, expected: dict, limit: int) -> bytes:
    require(type(expected.get("size")) is int and 0 <= expected["size"] <= limit
            and re.fullmatch(r"[a-f0-9]{64}", str(expected.get("sha256", ""))), "Invalid input pin")
    path = ordinary(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        require(before.st_size == expected["size"], "Pinned input size differs")
        data = stream.read(expected["size"] + 1)
        after = os.fstat(stream.fileno())
    current = ordinary(path).stat()
    identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_nlink)
    require(identity(before) == identity(after) == identity(current) and pin(data) == expected,
            "Pinned input changed or differs")
    return data


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate acquisition JSON key")
        result[key] = value
    return result


def xml(data: bytes):
    require(len(data) <= MAX_REPORT, "Unreviewed XML bound")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Source reports must use UTF-8 XML") from error
    require("\x00" not in text and "<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(),
            "Unreviewed XML declaration or encoding")
    try:
        return ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError("Invalid source report XML") from error


def number(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for count in range(5):
        require(position < len(data), "Truncated svndiff integer")
        byte = data[position]
        position += 1
        require(count or byte != 0x80, "Noncanonical svndiff integer")
        value = value * 128 + (byte & 127)
        require(value <= MAX_FILE, "Oversized svndiff integer")
        if not byte & 128:
            return value, position
    raise ValueError("Overlong svndiff integer")


def decode_fulltext(data: bytes) -> bytes:
    """Accept only svndiff0 new-data windows against an empty source view."""
    require(data[:4] == b"SVN\x00" and len(data) <= MAX_FILE + 65536, "Unreviewed svndiff format or size")
    position, output, windows = 4, bytearray(), 0
    while position < len(data):
        windows += 1
        require(windows <= 1024, "Too many svndiff windows")
        values = []
        for _ in range(5):
            value, position = number(data, position)
            values.append(value)
        source_offset, source_length, target_length, instruction_length, new_length = values
        require(source_offset == source_length == 0 and target_length > 0
                and len(output) + target_length <= MAX_FILE, "Nonempty source view or invalid target bound")
        end = position + instruction_length + new_length
        require(end <= len(data), "Truncated svndiff sections")
        instructions = data[position:position + instruction_length]
        fresh = data[position + instruction_length:end]
        position = end
        offset, used, target = 0, 0, bytearray()
        while offset < len(instructions):
            code = instructions[offset]
            offset += 1
            length = code & 63
            if not length:
                length, offset = number(instructions, offset)
            require(code >> 6 == 2 and length > 0, "Only new-data fulltext instructions are accepted")
            require(used + length <= len(fresh) and len(target) + length <= target_length,
                    "Fulltext instruction exceeds a section bound")
            target.extend(fresh[used:used + length])
            used += length
        require(used == new_length and len(target) == target_length, "Unconsumed or incomplete fulltext sections")
        output.extend(target)
    return bytes(output)


def validate_request(data: bytes, prefix: str) -> None:
    root = xml(data)
    depth = "infinity" if prefix else "files"
    require(root.tag == S + "update-report" and root.attrib == {"send-all": "true"}, "Unexpected request root")
    require([c.tag for c in root] == [S + key for key in ("src-path", "target-revision", "depth", "entry")],
            "Unexpected request fields")
    require(root[0].text == SOURCE_URL + ("/" + prefix if prefix else "")
            and root[1].text == str(REVISION) and root[2].text == depth
            and root[3].attrib == {"rev": str(REVISION), "start-empty": "true", "depth": depth}
            and root[3].text in (None, ""), "Unexpected request source, revision or scope")


def report_files(data: bytes, prefix: str) -> dict[str, bytes]:
    root = xml(data)
    require(root.tag == S + "update-report" and root.attrib == {"send-all": "true", "inline-props": "true"},
            "Unexpected source report root")
    require([c.tag for c in root] == [S + "target-revision", S + "open-directory"]
            and root[0].attrib == {"rev": str(REVISION)} and root[1].attrib == {"rev": str(REVISION)},
            "Unexpected source report revision")
    files, seen, total = {}, set(), 0

    def walk(directory, path: str, level: int):
        nonlocal total
        require(level <= 20, "Source report nesting exceeds bound")
        for entry in directory:
            if entry.tag in {D + "checked-in", S + "set-prop", S + "prop"}:
                continue
            require(entry.tag in {S + "add-file", S + "add-directory"}, "Unexpected source tree operation")
            name = entry.get("name", "")
            require("/" not in name, "Source report entry is not an immediate child")
            relative = safe_name(path + name)
            require(relative.casefold() not in seen and len(seen) < MAX_ENTRIES, "Duplicate or excessive source entries")
            seen.add(relative.casefold())
            if entry.tag == S + "add-directory":
                require(bool(prefix), "Root-files report contains a directory")
                walk(entry, relative + "/", level + 1)
                continue
            require(set(entry.attrib) == {"name", "sha1-checksum"}, "Unexpected source file attributes")
            require(all(c.tag in {D + "checked-in", S + "set-prop", S + "prop", S + "txdelta"} for c in entry),
                    "Unexpected source file child")
            deltas = entry.findall(S + "txdelta")
            require(len(deltas) == 1 and not deltas[0].attrib and not list(deltas[0]), "Missing or ambiguous fulltext")
            encoded = "".join((deltas[0].text or "").split())
            require(len(encoded) <= 2 * MAX_FILE, "Encoded source file exceeds bound")
            try:
                body = decode_fulltext(base64.b64decode(encoded, validate=True))
            except (ValueError, TypeError) as error:
                raise ValueError("Invalid source fulltext encoding") from error
            require(hashlib.sha1(body).hexdigest() == entry.attrib["sha1-checksum"], "SVN SHA1 checksum differs")
            md5 = entry.findall(S + "prop/" + V + "md5-checksum")
            require(len(md5) == 1 and hashlib.md5(body).hexdigest() == md5[0].text, "SVN MD5 checksum differs")
            total += len(body)
            require(total <= MAX_TOTAL, "Source report decoded total exceeds bound")
            files[relative] = body

    walk(root[1], prefix + "/" if prefix else "", 0)
    return files


def source_files(data: bytes) -> dict[str, bytes]:
    files, seen, total = {}, set(), 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        require(len(archive.infolist()) <= MAX_ENTRIES, "Too many source archive entries")
        for entry in archive.infolist():
            name = safe_name(entry.filename.rstrip("/"))
            require(name == "iup" or name.startswith("iup/"), "Unexpected source archive root")
            require(entry.orig_filename == entry.filename and name.casefold() not in seen, "Duplicate or truncated archive name")
            seen.add(name.casefold())
            mode = stat.S_IFMT(entry.external_attr >> 16)
            require(mode in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG), "Nonordinary source archive member")
            require(not entry.flag_bits & 1 and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    and entry.file_size <= MAX_FILE, "Unreviewed source archive member")
            if entry.is_dir():
                require(entry.file_size == 0, "Nonempty directory entry")
                continue
            total += entry.file_size
            require(total <= MAX_TOTAL, "Source ZIP expanded total exceeds bound")
            with archive.open(entry) as stream:
                body = stream.read(entry.file_size + 1)
            require(len(body) == entry.file_size, "Source ZIP decoded size differs")
            files[name.removeprefix("iup/")] = body
    require(bool(files), "Empty source ZIP")
    return files


def compare_files(archive: dict[str, bytes], historical: dict[str, bytes]) -> tuple[list[dict], dict]:
    rows, counts = [], collections.Counter()
    for name, body in sorted(archive.items()):
        svn = historical.get(name)
        if svn is None:
            kind = "missing-from-svn"
        elif body == svn:
            kind = "exact"
        elif b"\x00" not in body and b"\x00" not in svn and body.replace(b"\r\n", b"\n") == svn.replace(b"\r\n", b"\n"):
            kind = "crlf-lf-only"
        else:
            kind = "content-differs"
        counts[kind] += 1
        rows.append({"archive_member": "iup/" + name, "comparison": kind, "archive": pin(body),
                     "svn": pin(svn) if svn is not None else None})
    return rows, {name: counts[name] for name in ("exact", "crlf-lf-only", "content-differs", "missing-from-svn")}


def run(source: Path, reports: Path) -> tuple[dict, dict]:
    seen_inputs = {}

    def read(path, expected, limit):
        body = snapshot(path, expected, limit)
        seen_inputs[path] = (expected, limit)
        return body

    source_bytes = read(source, dict(zip(("size", "sha256"), SOURCE_PIN)), MAX_REPORT)
    archive = source_files(source_bytes)
    acquisition_bytes = read(reports / "acquisition.json", dict(zip(("size", "sha256"), ACQUISITION_PIN)), 1024 * 1024)
    acquisition = json.loads(acquisition_bytes, object_pairs_hook=unique)
    require(acquisition.get("schema") == "dupez.iup-svn-report-acquisition.v1"
            and type(acquisition.get("revision")) is int and acquisition["revision"] == REVISION
            and acquisition.get("source_zip_sha256") == SOURCE_PIN[1]
            and all(acquisition.get(k) is False for k in ("native_execution", "native_rebuild_performed", "release_approval")),
            "Unexpected acquisition identity or scope")
    expected_prefixes = {"", *(name.split("/", 1)[0] for name in archive if "/" in name)}
    rows = acquisition.get("requests", [])
    require(isinstance(rows, list) and len(rows) == len(expected_prefixes)
            and all(isinstance(row, dict) for row in rows)
            and {row.get("prefix") for row in rows} == expected_prefixes, "Incomplete or duplicate report scope")
    historical, consumed, total = {}, [], 0
    for row in rows:
        prefix = row["prefix"]
        require(row.get("method") == "REPORT" and row.get("url") == REPORT_URL
                and type(row.get("http_status")) is int and row["http_status"] == 200, "Unexpected acquisition route")
        name = prefix or "root"
        inputs = []
        for field, suffix in (("request", "-request.xml"), ("response", ".xml")):
            item = row[field]
            require(item.get("path") == name + suffix, "Unexpected report artifact name")
            expected = {key: item[key] for key in ("size", "sha256")}
            total += expected["size"]
            require(total <= MAX_TOTAL, "Acquired reports exceed total bound")
            inputs.append(read(reports / item["path"], expected, 65536 if field == "request" else MAX_REPORT))
        validate_request(inputs[0], prefix)
        files = report_files(inputs[1], prefix)
        require(not set(historical).intersection(files), "Overlapping report member scopes")
        historical.update(files)
        require(len(historical) <= MAX_ENTRIES and sum(map(len, historical.values())) <= MAX_TOTAL,
                "Historical export inventory exceeds bounds")
        consumed.append(row)
    members, counts = compare_files(archive, historical)
    extras = [{"path": name, **pin(historical[name])} for name in sorted(set(historical) - set(archive))]
    by_root = {}
    for row in members:
        name = row["archive_member"].removeprefix("iup/").split("/", 1)[0]
        group = by_root.setdefault(name, collections.Counter())
        group[row["comparison"]] += 1
    inventory = {"schema": "dupez.iup-source-file-comparisons.v1", "revision": REVISION,
                 "source_archive": pin(source_bytes), "members": members, "svn_extra_files_within_requested_scopes": extras}
    for path, (expected, limit) in seen_inputs.items():
        snapshot(path, expected, limit)
    receipt = {
        "schema": "dupez.iup-source-archive-comparison.v1", "status": "all-archive-files-compared",
        "revision": REVISION, "source_archive": {"name": source.name, **pin(source_bytes)},
        "acquisition": pin(acquisition_bytes), "report_count": len(rows), "report_inputs": consumed,
        "archive_file_count": len(archive), "historical_file_count_within_requested_scopes": len(historical),
        "counts": counts, "counts_by_archive_root": {key: dict(value) for key, value in sorted(by_root.items())},
        "svn_extra_files_within_requested_scopes": extras,
        "all_archive_files_exact": counts["exact"] == len(archive),
        "all_archive_files_correspond_after_explicit_crlf_lf_conversion": not counts["content-differs"] and not counts["missing-from-svn"],
        "whole_svn_repository_exported": False, "dll_build_source_identity_proven": False,
        "native_rebuild_performed": False, "native_execution_performed": False, "complete_corresponding_source": False,
        "release_approval": False,
        "limits": [
            "Exact byte matches and CRLF/LF-only matches are distinct; original ZIP and SVN bytes are never rewritten.",
            "Reports cover the retained ZIP's top-level directories plus root files, not all upstream documentation or the entire repository.",
            "Revision 5892 is selected by previously reviewed date metadata, not a discovered release tag or DLL build attestation.",
            "A complete source-file comparison does not establish compiler/SDK inputs, DLL reproduction, redistribution entitlement or public delivery.",
        ],
    }
    return receipt, inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.output, args.inventory):
        ordinary(path, missing=True)
        require(not os.path.lexists(path), "Refusing to replace source evidence")
    require(os.path.abspath(args.output) != os.path.abspath(args.inventory), "Evidence outputs must be distinct")
    receipt, inventory = run(args.source, args.reports)
    payload = (json.dumps(inventory, indent=2, sort_keys=True) + "\n").encode()
    receipt["comparison_inventory"] = {"name": args.inventory.name, **pin(payload)}
    for path, data in ((args.inventory, payload), (args.output, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())):
        ordinary(path, missing=True)
        with path.open("xb") as stream:
            stream.write(data)
    print(json.dumps({"status": receipt["status"], "counts": receipt["counts"], "native_rebuild_performed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
