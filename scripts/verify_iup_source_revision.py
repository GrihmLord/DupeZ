#!/usr/bin/env python3
"""Compare seven pinned IUP source members with official historical SVN bytes.

Offline inspection only: no downloads, source extraction, native execution or
claim that these selected matches identify the complete DLL build source.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import stat
import xml.etree.ElementTree as ET
import zipfile

if __package__:
    from . import prepare_qt_candidate as candidate
else:
    spec = importlib.util.spec_from_file_location(
        "prepare_qt_candidate", Path(__file__).with_name("prepare_qt_candidate.py"))
    assert spec is not None and spec.loader is not None
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)

REVISION = 5892
REVISION_DATE = "2020-08-02T15:32:49.346111Z"
DATED_QUERY = "2020-08-02T23:59:59.000000Z"
REPOSITORY = "https://svn.code.sf.net/p/iup/iup/"
SOURCE_PIN = (14226631, "92e1b56a6c78eeaca7cce3897536d333787e27e3ec25f94487dd0ab1d8d053e6")
SELECTED = {
    "include/iup.h": (25641, "d8759727c248b27f3d0ff2093265d1540b0129b532b57a37aaab6b3758dae24d"),
    "src/config.mak": (8911, "635876c04c9cdbcff866fe2d0a80f5a92aaba6b6f79461eb4941aeac08e34cd2"),
    "src/iup.c": (6425, "7829eeef7649a630d0d1e68afcc5f67dd1ef04aae5636d303b143182bcf0a138"),
    "src/iup.def": (13059, "7b71f50f640bcf65adaa16b89774d4584444da6a53c857176f937455ec1d0717"),
    "src/win/iupwin_loop.c": (6147, "19f55d72547ed2e3e162d6c1755a061e6a38a12172e564d7d98105f506613a5d"),
    "src/win/iupwin_dialog.c": (64859, "de831b52f8ea5f1b2ea8e4b8f582d5f81e81f987be4e3a89fe9fa113cc1c627d"),
    "src/win/iupwin_text.c": (65264, "7675fed4cfc14f1bb9cc7aed5686837ef4d09d70b273025ddd944ec7da195865"),
}
METADATA = {
    "dated-revision.xml": (148, "0a6aff3d35aa43e83927a4dac53e994bb43ea96cecc332e0f3f5fa9056be737f"),
    "revision-log.xml": (3147, "7a59adddadd9933ceb946cedc21a91d05020f47b52bac72c72fde8f077cf7fa4"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pinned_bytes(path: Path, pin: tuple[int, str]) -> bytes:
    path = candidate.ordinary_path(path, file=True)
    size, expected = pin
    if not 0 < size <= 16 * 1024 * 1024:
        raise ValueError("Unreviewed input size bound")
    with path.open("rb") as stream:
        data = stream.read(size + 1)
    if len(data) != size or digest(data) != expected:
        raise ValueError(f"Pinned input differs: {path.name}")
    return data


def revision_metadata(dated: bytes, log: bytes) -> dict:
    for data in (dated, log):
        if len(data) > 64 * 1024 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ValueError("Unreviewed XML declaration or size")
    date_root, log_root = ET.fromstring(dated), ET.fromstring(log)
    if (date_root.tag != "{svn:}dated-rev-report"
            or [e.text for e in date_root.findall("{DAV:}version-name")] != [str(REVISION)]
            or log_root.tag != "{svn:}log-report"):
        raise ValueError("Unexpected SVN dated revision")
    rows = log_root.findall("{svn:}log-item")
    revisions = [row.findtext("{DAV:}version-name") for row in rows]
    if revisions != ["5892", "5891", "5890", "5889"] or rows[0].findtext("{svn:}date") != REVISION_DATE:
        raise ValueError("Unexpected SVN revision log")
    changes = [e.text for e in rows[0].findall("{svn:}modified-path")]
    if changes != ["/trunk/iup/html/en/history3.html"]:
        raise ValueError("Unexpected release-date revision changes")
    return {"revision": REVISION, "revision_date": REVISION_DATE, "dated_query": DATED_QUERY,
            "latest_revision_at_query_date": True, "revision_changed_paths": changes}


def compare_selected(source: bytes, selected: dict[str, bytes]) -> list[dict]:
    expected = {"iup/" + path: data for path, data in selected.items()}
    if set(selected) != set(SELECTED):
        raise ValueError("Selected source set differs from reviewed scope")
    found, seen = {}, set()
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        members = archive.infolist()
        if len(members) > 4000 or sum(item.file_size for item in members) > 100 * 1024 * 1024:
            raise ValueError("Source archive exceeds reviewed bounds")
        for item in members:
            path = PurePosixPath(item.filename)
            if (item.orig_filename != item.filename or "\\" in item.filename or path.is_absolute()
                    or ".." in path.parts or ":" in item.filename):
                raise ValueError("Unsafe source archive name")
            name = item.filename.casefold()
            if name in seen:
                raise ValueError("Duplicate source archive member")
            seen.add(name)
            if item.filename not in expected:
                continue
            mode = item.external_attr >> 16
            if (item.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or item.flag_bits & 1
                    or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or item.file_size != len(expected[item.filename]) or item.file_size > 1024 * 1024):
                raise ValueError("Unreviewed selected source member")
            with archive.open(item) as stream:
                data = stream.read(item.file_size + 1)
            if data != expected[item.filename]:
                raise ValueError("Historical SVN source differs from selected archive member")
            found[item.filename] = {"archive_member": item.filename, "size": len(data), "sha256": digest(data),
                                    "svn_url": REPOSITORY + f"!svn/rvr/{REVISION}/trunk/" + item.filename,
                                    "normalization": "none", "exact_match": True}
    if set(found) != set(expected):
        raise ValueError("Missing selected source archive member")
    return [found[name] for name in sorted(found)]


def run(source: Path, metadata_root: Path) -> dict:
    inputs = {source: SOURCE_PIN}
    inputs.update({metadata_root / "files" / name: pin for name, pin in SELECTED.items()})
    inputs.update({metadata_root / name: pin for name, pin in METADATA.items()})
    snapshots = {path: pinned_bytes(path, pin) for path, pin in inputs.items()}
    metadata = revision_metadata(snapshots[metadata_root / "dated-revision.xml"],
                                 snapshots[metadata_root / "revision-log.xml"])
    matches = compare_selected(snapshots[source], {name: snapshots[metadata_root / "files" / name] for name in SELECTED})
    # A receipt describes still-present inputs. Reject replacements made during
    # verification, while parsing only the originally authenticated snapshots.
    for path, pin in inputs.items():
        if pinned_bytes(path, pin) != snapshots[path]:
            raise ValueError("An input changed during verification")
    return {
        "schema": "dupez.iup-selected-source-revision.v1", "status": "selected-historical-source-bytes-match",
        "source_archive": {"name": source.name, "size": SOURCE_PIN[0], "sha256": SOURCE_PIN[1]},
        "revision_metadata": metadata, "selected_member_count": len(matches), "members": matches,
        "metadata_inputs": [{"name": name, "size": pin[0], "sha256": pin[1]} for name, pin in METADATA.items()],
        "official_repository_reference": "https://www.tecgraf.puc-rio.br/iup/en/svn.html",
        "whole_archive_revision_identity_proven": False, "dll_build_source_identity_proven": False,
        "native_rebuild_performed": False, "native_execution_performed": False, "release_approval": False,
        "limits": [
            "Only the seven listed source members were compared; all other archive members remain outside this match claim.",
            "Revision 5892 is the latest repository revision at the queried date, not a discovered release tag or a binary build attestation.",
            "The source ZIP re-upload date does not alter these seven exact matches, but full source/patch and compiler/SDK provenance remain unresolved.",
            "No complete corresponding-source, native DLL reproduction, distribution entitlement or public delivery is established.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = candidate.ordinary_path(args.output, missing=True, file=True)
    if output.exists():
        raise ValueError("Refusing to replace an existing source evidence receipt")
    result = run(args.source, args.metadata_root)
    candidate.ordinary_path(output, missing=True, file=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"selected_members": len(result["members"]), "native_rebuild_performed": False,
                      "release_approval": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
