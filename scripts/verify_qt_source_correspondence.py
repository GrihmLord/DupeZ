"""Compare pinned Qt source exports with the source records in binary archives.

This reads archives as data. Matching publisher metadata and source checksums
does not prove that a native compiler reproduced the shipped libraries.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile


if __package__:
    from . import prepare_qt_candidate as candidate
    from . import validate_frozen_runtime as runtime_validation
else:
    spec = importlib.util.spec_from_file_location(
        "prepare_qt_candidate", Path(__file__).with_name("prepare_qt_candidate.py"))
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    spec = importlib.util.spec_from_file_location(
        "validate_frozen_runtime", Path(__file__).with_name("validate_frozen_runtime.py"))
    runtime_validation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime_validation)

MAX_MEMBER = 64 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_RECORDS = 100000
MODULES = ("qtbase", "qtsvg", "qtimageformats", "qttranslations")


def digest(data: bytes, algorithm: str = "sha256") -> str:
    return hashlib.new(algorithm, data).hexdigest()


def snapshot(path: Path, pin: dict) -> bytes:
    candidate.ordinary_path(path, file=True)
    if path.stat().st_size != pin["size"] or not 0 < pin["size"] <= candidate.MAX_FILE:
        raise ValueError("Source review input size differs from pin")
    data = path.read_bytes()
    if len(data) != pin["size"] or digest(data) != pin["sha256"]:
        raise ValueError("Source review input differs from pin")
    return data


def source_inventory(data: bytes) -> tuple[dict, str]:
    """Hash bounded ordinary source members without writing archive paths."""
    records, seen = {}, set()
    total, revision = 0, None
    with tarfile.open(fileobj=io.BytesIO(data), mode="r|xz") as archive:
        for member in archive:
            candidate.safe_member(member.name)
            if member.name in seen or len(seen) >= MAX_RECORDS:
                raise ValueError("Duplicate or excessive source members")
            seen.add(member.name)
            if member.isdir():
                continue
            if not member.isfile() or not 0 <= member.size <= MAX_MEMBER:
                raise ValueError("Special or oversized source member")
            total += member.size
            if total > MAX_TOTAL:
                raise ValueError("Source expansion exceeds bound")
            stream = archive.extractfile(member)
            body = stream.read(MAX_MEMBER + 1)
            if len(body) != member.size:
                raise ValueError("Truncated source member")
            records[member.name] = {"sha1": digest(body, "sha1"), "sha256": digest(body),
                                    "crlf_sha1": digest(body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"), "sha1"),
                                    "size": len(body)}
            if member.name == ".tag":
                if not re.fullmatch(rb"[a-f0-9]{40}\n", body):
                    raise ValueError("Source export lacks a canonical revision")
                revision = body.decode("ascii").strip()
    if revision is None:
        raise ValueError("Source export revision is absent")
    return records, revision


def source_checksums(spdx: bytes) -> dict[str, str]:
    records = {}
    for block in re.split(r"(?=^FileName: )", spdx.decode("utf-8"), flags=re.M):
        match = re.match(r"FileName: ([^\r\n]+)", block)
        if match is None:
            continue
        name = match[1].replace("\\", "/").removeprefix("./")
        candidate.safe_member(name)
        sums = re.findall(r"^FileChecksum: SHA1: ([a-f0-9]{40})\r?$", block, re.M)
        if name in records or len(sums) != 1 or len(records) >= MAX_RECORDS:
            raise ValueError("Ambiguous or excessive source SPDX checksums")
        records[name] = sums[0]
    if not records:
        raise ValueError("Source SPDX has no file checksums")
    return records


def compare_sources(records: dict, checksums: dict) -> dict:
    raw, crlf, missing, mismatched = [], [], [], []
    for name, expected in sorted(checksums.items()):
        if name not in records:
            missing.append(name)
        elif records[name]["sha1"] == expected:
            raw.append(name)
        elif records[name]["crlf_sha1"] == expected:
            crlf.append(name)
        else:
            mismatched.append(name)
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return {"archive_files": len(records), "source_inventory_sha256": digest(canonical),
            "spdx_records": len(checksums), "raw_matches": len(raw), "crlf_matches": len(crlf),
            "missing": missing, "mismatched": mismatched,
            "archive_files_without_spdx_record": len(set(records) - set(checksums)),
            "all_recorded_files_match_raw_or_crlf": not missing and not mismatched}


def declared_revisions(spdx: bytes, module: str) -> dict[str, str | None]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate binary SPDX JSON key")
            result[key] = value
        return result

    document = json.loads(spdx, object_pairs_hook=unique)
    packages = document.get("packages")
    if not isinstance(packages, list):
        raise ValueError("Binary SPDX package inventory is absent")
    result = {}
    pattern = re.compile(r"git://code\.qt\.io/qt/" + re.escape(module) + r"\.git@([a-f0-9]{40})\Z")
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("Invalid binary SPDX package")
        location = package.get("downloadLocation", "")
        if not isinstance(location, str):
            raise ValueError("Invalid binary SPDX download location")
        repository = "git://code.qt.io/qt/" + module + ".git"
        if location != repository and not location.startswith(repository + "@"):
            continue
        match = pattern.fullmatch(location)
        name = package.get("name")
        if ((match is None and location != repository)
                or not isinstance(name, str) or not name or name in result):
            raise ValueError("Ambiguous binary SPDX revision")
        result[name] = match[1] if match else None
    if module not in result:
        raise ValueError("Binary SPDX lacks the module revision")
    return result


def archive_member(tar: Path, archive: Path, member: str, environment: dict) -> bytes:
    candidate.safe_member(member)
    result = subprocess.run([str(tar), "-xOf", str(archive), member], env=environment,
                            capture_output=True, check=True, timeout=90)
    if not result.stdout or len(result.stdout) > MAX_MEMBER:
        raise ValueError("Missing or oversized source review metadata")
    return result.stdout


def binary_metadata(tar: Path, archive: Path, pin: dict, module: str,
                    version: str, environment: dict) -> tuple[bytes | None, bytes]:
    # libarchive's 7z reader needs a seekable path. Hold the existing reviewed
    # Windows read lock (no launch occurs) so tar cannot observe replacement
    # bytes between the pin check, directory inspection and metadata reads.
    candidate.ordinary_path(archive, file=True)
    with runtime_validation._locked_release_executable(
            archive, expected_hash=pin["sha256"], expected_size=pin["size"]):
        entries = candidate.inspect_7z(archive, pin, tar, environment)
        source_member = f"sbom/{module}-{version}.source.spdx"
        source_spdx = (archive_member(tar, archive, source_member, environment)
                       if source_member in entries else None)
        binary_spdx = archive_member(tar, archive, f"sbom/{module}-{version}.spdx.json", environment)
        return source_spdx, binary_spdx


def review(manifest_path: Path, inputs: Path, output: Path) -> dict:
    manifest, manifest_hash = candidate.load_manifest_snapshot(manifest_path)
    version = manifest["qt_version"]
    if version != "6.12.1":
        raise ValueError("This source correspondence review is scoped to Qt 6.12.1")
    inputs = candidate.ordinary_path(inputs)
    output = candidate.ordinary_path(output, missing=True)
    if output.exists() or not output.is_relative_to(candidate.ROOT / "build"):
        raise ValueError("Use a fresh review directory under repository build/")
    pins = {row["id"]: row for row in manifest["inputs"]}
    paths = {key: inputs / pins[key]["filename"] for module in MODULES
             for key in (module + "-source", module + "-binary")}
    for key, path in paths.items():
        candidate.verified(path, pins[key])
    output.mkdir(parents=True)
    environment = candidate.child_environment(output / "private")
    tar = candidate.ordinary_path(candidate.system_directory() / "tar.exe", file=True)
    results = {}
    for module in MODULES:
        source_key, binary_key = module + "-source", module + "-binary"
        source = snapshot(paths[source_key], pins[source_key])
        records, revision = source_inventory(source)
        source_spdx, binary_spdx = binary_metadata(
            tar, paths[binary_key], pins[binary_key], module, version, environment)
        declared = declared_revisions(binary_spdx, module)
        results[module] = {"source_input": pins[source_key], "binary_input": pins[binary_key],
                           "exported_revision": revision, "declared_binary_revisions": declared,
                           "all_binary_revision_values_present": all(declared.values()),
                           "all_declared_revisions_match_export": set(declared.values()) == {revision},
                           "source_spdx": ({"size": len(source_spdx), "sha256": digest(source_spdx)}
                                           if source_spdx is not None else None),
                           "source_spdx_status": "present" if source_spdx is not None else "absent-from-pinned-binary-archive",
                           "source_archive_files": len(records),
                           "binary_spdx": {"size": len(binary_spdx), "sha256": digest(binary_spdx)},
                           "source_comparison": (compare_sources(records, source_checksums(source_spdx))
                                                 if source_spdx is not None else None)}
    for key, path in paths.items():
        candidate.verified(path, pins[key])
    if candidate.load_manifest_snapshot(manifest_path)[1] != manifest_hash:
        raise ValueError("Source review manifest changed during inspection")
    result = {"schema": "dupez.qt-source-correspondence.v1", "qt_version": version,
              "manifest_sha256": manifest_hash, "modules": results,
              "all_declared_revisions_match_exports": all(r["all_declared_revisions_match_export"] for r in results.values()),
              "native_compiler_executed": False, "native_rebuild_proven": False,
              "complete_corresponding_source_proven": False, "release_approved": False,
              "limitations": ["Publisher source/checksum and revision comparisons, not native binary reconstruction.",
                              "Line-ending-equivalent matches are separately counted and are not raw-byte matches.",
                              "Missing, mismatched and unrecorded source files remain explicit; no licensing approval is inferred."]}
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=candidate.NO_NETWORK_MANIFEST)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(args.manifest, args.inputs, args.output)
    print(json.dumps({"qt_version": result["qt_version"],
                      "all_declared_revisions_match_exports": result["all_declared_revisions_match_exports"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
