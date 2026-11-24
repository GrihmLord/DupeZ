#!/usr/bin/env python3
"""Verify Qt 6.11.3 Git export metadata against pinned local source evidence.

Read-only inspection: no downloads, native execution, patching, or extraction.
The .tag template explanation does not establish binary/source revision identity.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import tarfile
from pathlib import Path

if __package__:
    from . import prepare_qt_candidate as candidate
else:
    spec = importlib.util.spec_from_file_location(
        "prepare_qt_candidate", Path(__file__).with_name("prepare_qt_candidate.py"))
    assert spec is not None and spec.loader is not None
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = b"$Format:%H$\n"
METADATA = {
    "qtbase": {
        "revision": "138f955f0b5e50e4a6c2ee1e78a2279db52ae9e3",
        "binary_revision": "b21f6a785516e898388cda2fe5d3e7dacd6d4b7d",
        "source_size": 50542228,
        "source_sha256": "bd60222ad79b3d88e7e45c6dd1cd738d34db0ceb159b6221316da7f884525f0b",
        "spdx_size": 10462208,
        "spdx_sha256": "7b5f29f47f11c529bfd3a6904de178fbab7b9a4ab3904ca7699ad45ed8e60cfe",
        "git_tag_file": "qtbase-source-git-tag.txt",
        "attributes_file": "qtbase-source-gitattributes.txt",
        "attributes_size": 227,
        "attributes_sha256": "edbe0427047f873216d84ab3335a2c78047510c07993f00963d7f2f23d5918b0",
    },
    "qtsvg": {
        "revision": "f5d99721911e4a1989965a087813cf1277519bc6",
        "binary_revision": "f5d99721911e4a1989965a087813cf1277519bc6",
        "source_size": 2338300,
        "source_sha256": "b712a27d4bc6ba510bc5c082f6eaac2ce38588d8a2d2eb771d08307735f9d44c",
        "spdx_size": 289834,
        "spdx_sha256": "118619a76c57ffe9023f3631d82145410e9187f52f922ee24b98a7582c02f118",
        "git_tag_file": "qtsvg-git-tag.txt",
        "attributes_file": "qtsvg-gitattributes.txt",
        "attributes_size": 89,
        "attributes_sha256": "0a9ab7cbb2935a5086f30fe7bc12bcbe4a9c8019d9f7c7570b046cd9417fa8ff",
    },
    "qttools": {
        "revision": "b0b5b911411ffb0da4f29643ab295b90c52dc26d",
        "source_size": 10273528,
        "source_sha256": "0a2da018a67ae081ab93d686fefce47e95eb8d82389151c476202ee8c4b375e4",
        "spdx_size": 2106689,
        "spdx_sha256": "11bb9d4cb0cd29d5ba9e03e7edb94e48fc4ee87e1560c4aad095024d3270d4c1",
        "git_tag_file": "qttools-git-tag.txt",
        "attributes_file": "qttools-gitattributes.txt",
        "attributes_size": 89,
        "attributes_sha256": "0a9ab7cbb2935a5086f30fe7bc12bcbe4a9c8019d9f7c7570b046cd9417fa8ff",
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pinned_bytes(path: Path, size: int, expected: str) -> bytes:
    candidate.ordinary_path(path, file=True)
    if path.stat().st_size != size:
        raise ValueError(f"Pinned size mismatch: {path.name}")
    body = path.read_bytes()
    if sha256(body) != expected:
        raise ValueError(f"Pinned SHA256 mismatch: {path.name}")
    return body


def archive_tag(data: bytes) -> bytes:
    # Parse the same captured bytes that the caller verified, never reopen the
    # mutable input path between authentication and inspection.
    found = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r|xz") as archive:
        for member in archive:
            if member.name == ".tag":
                if not member.isfile() or member.size != 41:
                    raise ValueError("Unexpected source .tag member")
                stream = archive.extractfile(member)
                assert stream is not None
                found.append(stream.read(42))
    if len(found) != 1:
        raise ValueError("Missing or duplicate source .tag")
    return found[0]


def metadata_checksums(spdx: bytes) -> dict[str, str]:
    result = {}
    for block in re.split(r"(?=FileName: )", spdx.decode("utf-8")):
        name = re.match(r"FileName: ([^\r\n]+)", block)
        if name is None:
            continue
        key = name[1].replace("\\", "/").removeprefix("./")
        if key not in {".tag", ".gitattributes"}:
            continue
        matches = re.findall(r"FileChecksum: SHA1: ([a-f0-9]{40})\b", block)
        if key in result or len(matches) != 1:
            raise ValueError("Ambiguous metadata SPDX record")
        result[key] = matches[0]
    if set(result) != {".tag", ".gitattributes"}:
        raise ValueError("Incomplete metadata SPDX records")
    return result


def explain_export(template: bytes, attributes: bytes, tag: bytes,
                   checksums: dict[str, str], revision: str) -> dict:
    if template != TEMPLATE or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Unreviewed tag template or revision")
    declarations = {tuple(line.split()) for line in attributes.decode("utf-8").splitlines()}
    if ((".tag", "export-subst") not in declarations
            or (".gitattributes", "export-ignore") not in declarations
            or (".gitignore", "export-ignore") not in declarations):
        raise ValueError("Missing explicit Git export declarations")
    for name, body in ((".tag", template), (".gitattributes", attributes)):
        crlf = body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if hashlib.sha1(crlf).hexdigest() != checksums[name]:
            raise ValueError(f"Git metadata differs from source SPDX: {name}")
    if tag != revision.encode("ascii") + b"\n":
        raise ValueError("Exported source tag differs from reviewed revision")
    return {"export_substitution_verified": True, "exported_revision": revision,
            "source_tag_sha256": sha256(tag), "git_tag_sha256": sha256(template),
            "attributes_sha256": sha256(attributes), "spdx_checksums": checksums,
            "root_git_metadata_exclusion_declared": True,
            "binary_source_revision_identity_proven": False}


def run(args: argparse.Namespace) -> dict:
    results = {}
    for module, pin in METADATA.items():
        if module == "qttools":
            source = args.qttools_root / "qttools-everywhere-src-6.11.3.tar.xz"
            spdx = args.qttools_root / "qttools.source.spdx"
        else:
            source = args.candidate_root / "inputs" / f"{module}-everywhere-src-6.11.3.tar.xz"
            spdx = args.candidate_root / "6.11.3/msvc2022_64/sbom" / f"{module}-6.11.3.source.spdx"
        source_snapshot = pinned_bytes(source, pin["source_size"], pin["source_sha256"])
        inventory = pinned_bytes(spdx, pin["spdx_size"], pin["spdx_sha256"])
        template = pinned_bytes(args.metadata_root / pin["git_tag_file"], len(TEMPLATE), sha256(TEMPLATE))
        attributes = pinned_bytes(args.metadata_root / pin["attributes_file"],
                                  pin["attributes_size"], pin["attributes_sha256"])
        results[module] = explain_export(template, attributes, archive_tag(source_snapshot),
                                         metadata_checksums(inventory), pin["revision"])
        results[module]["input_pins"] = pin
        results[module]["official_git_metadata_url"] = (
            f"https://code.qt.io/cgit/qt/{module}.git/plain/.gitattributes?id={pin['revision']}")
    return {"schema": "dupez.qt-export-metadata.v1", "reviewed_on": "2026-11-09",
            "modules": results, "all_export_substitutions_verified": True,
            "qtbase_binary_revision_discrepancy_resolved": False,
            "native_rebuild_proven": False, "release_approved": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--qttools-root", type=Path, required=True)
    parser.add_argument("--metadata-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
