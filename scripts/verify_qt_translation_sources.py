#!/usr/bin/env python3
"""Map and reproduce pinned Qt 6.11.3 catalogs with the reviewed Qt compiler.

This local-only review does not install Qt or alter production dependency locks.
The native compiler runs only with --run-compiler, a standard user token, a new
output directory, two hash-pinned native files, and the candidate's private env.
It is an artifact rebuild using Qt's compiler, not a rebuild of that compiler.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
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
EXTRA_INPUTS = {
    "qttools-binary": {
        "filename": "qttools-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z",
        "url": "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6113/qt6_6113_msvc2022_64/qt.qt6.6113.win64_msvc2022_64/6.11.3-0-202610220312qttools-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z",
        "size": 27042501,
        "sha256": "b519f552424d8c748ed37c6b3a7615d29a1e3920383ee8ccf9b2066998341c2c",
        "members": 633,
        "member_listing_sha256": "7fe18b56e499ca212f0bf463ae10b6e0952a9cb77255505f7d4d336a755a24c0",
    },
    "qttools-source": {
        "filename": "qttools-everywhere-src-6.11.3.tar.xz",
        "url": "https://download.qt.io/online/qtsdkrepository/all_os/qt/qt6_6113_unix_line_endings_src/qt.qt6.6113.src/6.11.3-0-202610220312qttools-everywhere-src-6.11.3.tar.xz",
        "size": 10273528,
        "sha256": "0a2da018a67ae081ab93d686fefce47e95eb8d82389151c476202ee8c4b375e4",
    },
}
NATIVE_PINS = {
    "lrelease.exe": "896e5134448612c8bc2fd4a9384d17929d0dca16b59f01f699ad931e96ff676e",
    "Qt6Core.dll": "3b088187284c91250fbb696b1779459ca1ab1ad14295e71ee9b12d71767c9501",
}
ENGLISH_TS = b'<TS language="en_US"></TS>'
ENGLISH_CATALOGS = frozenset({
    "qt", "qtbase", "qtdeclarative", "qtmultimedia", "qtconnectivity", "qtlocation",
    "qtwebsockets", "qtserialport", "qtwebengine", "designer", "linguist", "assistant", "qt_help",
})
RECIPE_SHA256 = "1c464f57b5b8878b81972fdd4f6e56f3d9f4f8f074ef9396e7afbc9a6c35a2e4"
MAX_MEMBER = 32 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024 * 1024


def digest(data: bytes, algorithm: str = "sha256") -> str:
    return hashlib.new(algorithm, data).hexdigest()


def pinned_file(path: Path, pin: dict) -> Path:
    candidate.ordinary_path(path, file=True)
    if path.stat().st_size != pin["size"] or digest(path.read_bytes()) != pin["sha256"]:
        raise ValueError(f"Pinned input mismatch: {path.name}")
    return path


def source_files(path: Path) -> dict[str, bytes]:
    """Read ordinary bounded members without extracting archive paths."""
    result: dict[str, bytes] = {}
    total = 0
    with tarfile.open(path, "r|xz") as archive:
        for member in archive:
            candidate.safe_member(member.name)
            if member.isdir():
                continue
            if not member.isfile() or member.size > MAX_MEMBER or member.name in result:
                raise ValueError("Duplicate, special, or oversized source member")
            total += member.size
            if total > MAX_SOURCE_BYTES or len(result) >= 10000:
                raise ValueError("Oversized source archive")
            stream = archive.extractfile(member)
            assert stream is not None
            body = stream.read(MAX_MEMBER + 1)
            if len(body) != member.size:
                raise ValueError("Truncated source member")
            result[member.name] = body
    return result


def english_recipe(sources: dict[str, bytes]) -> dict[str, bytes]:
    recipe = sources["translations/CMakeLists.txt"]
    if digest(recipe) != RECIPE_SHA256:
        raise ValueError("Unreviewed English translation generation recipe")
    return {f"{catalog}_en.ts": ENGLISH_TS for catalog in sorted(ENGLISH_CATALOGS)}


def correlate_sources(sources: dict[str, bytes], spdx: bytes) -> dict:
    records = {}
    for block in re.split(r"(?=FileName: )", spdx.decode("utf-8")):
        name = re.match(r"FileName: ([^\r\n]+)", block)
        checksum = re.search(r"FileChecksum: SHA1: ([a-f0-9]{40})\b", block)
        if not name or not checksum:
            continue
        normalized = name[1].replace("\\", "/").removeprefix("./")
        candidate.safe_member(normalized)
        if normalized in records:
            raise ValueError("Duplicate source SPDX file")
        records[normalized] = checksum[1]
    if not records:
        raise ValueError("No source SPDX checksums")
    raw, crlf, missing, mismatched = [], [], [], []
    for name, checksum in sorted(records.items()):
        if name not in sources:
            missing.append(name)
        elif digest(sources[name], "sha1") == checksum:
            raw.append(name)
        elif digest(sources[name].replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"), "sha1") == checksum:
            crlf.append(name)
        else:
            mismatched.append(name)
    compiler = sorted(name for name in sources if name.startswith("src/linguist/"))
    compiler_unmatched = sorted(set(compiler) - set(raw) - set(crlf))
    return {"records": len(records), "raw_matches": len(raw), "crlf_matches": len(crlf),
            "missing": missing, "mismatched": mismatched,
            "linguist_source_files": len(compiler), "linguist_unmatched": compiler_unmatched,
            "source_tag": sources[".tag"].decode("ascii").strip()}


def archive_bytes(tar: Path, archive: Path, member: str, env: dict) -> bytes:
    candidate.safe_member(member)
    result = subprocess.run([str(tar), "-xOf", str(archive), member], check=True,
                            capture_output=True, env=env, timeout=60)
    if len(result.stdout) > MAX_MEMBER:
        raise ValueError("Oversized binary archive member")
    return result.stdout


def match_catalogs(sources: dict[str, bytes], compiled: dict[str, bytes],
                   generated: dict[str, bytes]) -> list[dict]:
    records = []
    for name, body in sorted(compiled.items()):
        if not re.fullmatch(r"[A-Za-z0-9_]+\.qm", name):
            raise ValueError("Unexpected catalog basename")
        ts_name = name.removesuffix(".qm") + ".ts"
        source_path = "translations/" + ts_name
        if source_path in sources:
            source = sources[source_path]
            kind = "source-ts"
        elif ts_name in generated:
            source = generated[ts_name]
            source_path = "translations/CMakeLists.txt:generate_empty_ts_file"
            kind = "generated-english-ts"
        else:
            raise ValueError(f"Unmapped compiled catalog: {name}")
        records.append({"catalog": name, "source_kind": kind, "source_path": source_path,
                        "ts_sha256": digest(source), "qm_sha256": digest(body), "qm_size": len(body)})
    return records


def run(args: argparse.Namespace) -> dict:
    if sys.platform != "win32":
        raise ValueError("This reviewed compiler is Windows x64 only")
    if args.run_compiler and ctypes.windll.shell32.IsUserAnAdmin():
        raise ValueError("Run the compiler review as a standard user, without elevation")
    root = candidate.ordinary_path(args.candidate_root)
    extra = candidate.ordinary_path(args.tools_inputs)
    output = candidate.ordinary_path(args.output, missing=True)
    if not output.is_relative_to(ROOT / "build") or output.exists():
        raise ValueError("Output must be a new directory under repository build/")
    manifest, manifest_sha = candidate.load_manifest_snapshot()
    if manifest["qt_version"] != "6.11.3":
        raise ValueError("Unreviewed candidate version")
    pins = {item["id"]: item for item in manifest["inputs"]}
    inputs = {}
    for key in ("qtbase-binary", "qttranslations-binary", "qttranslations-source"):
        inputs[key] = pinned_file(root / "inputs" / pins[key]["filename"], pins[key])
    for key, pin in EXTRA_INPUTS.items():
        inputs[key] = pinned_file(extra / pin["filename"], pin)
    sources = source_files(inputs["qttranslations-source"])
    generated = english_recipe(sources)
    compiler_sources = source_files(inputs["qttools-source"])
    output.mkdir()
    env = candidate.child_environment(output / "private")
    tar = candidate.ordinary_path(candidate.system_directory() / "tar.exe", file=True)
    for key in ("qtbase-binary", "qttranslations-binary", "qttools-binary"):
        candidate.inspect_7z(inputs[key], EXTRA_INPUTS.get(key, pins.get(key)), tar, env)
    compiler_spdx = archive_bytes(tar, inputs["qttools-binary"], "sbom/qttools-6.11.3.source.spdx", env)
    correlation = correlate_sources(compiler_sources, compiler_spdx)
    if correlation["linguist_unmatched"]:
        raise ValueError("Compiler source subset does not match source SPDX")
    compiled = {}
    # Compare to a fresh extraction of the exact pinned archive, not a mutable
    # installed Qt prefix. inspect_7z above rejects links and unsafe namespaces.
    reference = output / "reference"
    reference.mkdir()
    subprocess.run([str(tar), "-xf", str(inputs["qttranslations-binary"]), "-C", str(reference)],
                   check=True, capture_output=True, env=env, timeout=60)
    prefix = reference / "translations"
    sbom = json.loads(archive_bytes(tar, inputs["qttranslations-binary"],
                                  "sbom/qttranslations-6.11.3.spdx.json", env))
    for item in sbom["files"]:
        name = item["fileName"].replace("\\", "/").removeprefix("./")
        if not name.startswith("translations/") or not name.endswith(".qm"):
            continue
        candidate.safe_member(name)
        base = name.removeprefix("translations/")
        if "/" in base:
            raise ValueError("Unexpected nested catalog")
        path = candidate.ordinary_path(prefix / base, file=True)
        if path.stat().st_size > MAX_MEMBER:
            raise ValueError("Oversized catalog")
        body = path.read_bytes()
        checksums = {item["algorithm"]: item["checksumValue"] for item in item["checksums"]}
        if digest(body, "sha1") != checksums.get("SHA1"):
            raise ValueError(f"Catalog differs from pinned binary SPDX: {base}")
        compiled[base] = body
    records = match_catalogs(sources, compiled, generated)
    if len(records) != 314 or sum(r["source_kind"] == "generated-english-ts" for r in records) != 13:
        raise ValueError("Unexpected reviewed catalog set")
    result = {"schema": "dupez.qt-translation-rebuild.v1", "qt_version": "6.11.3",
              "candidate_manifest_sha256": manifest_sha, "compiler_run": args.run_compiler,
              "scope": "Translation artifact rebuild using official binary compiler; no native compiler rebuild or release approval",
              "compiler_inputs": EXTRA_INPUTS, "compiler_source_correlation": correlation,
              "recipe_sha256": RECIPE_SHA256, "catalogs": records}
    if args.run_compiler:
        tool_dir, ts_dir, qm_dir = output / "tool", output / "ts", output / "qm"
        for path in (tool_dir, ts_dir, qm_dir):
            path.mkdir()
        for name, archive_key in (("lrelease.exe", "qttools-binary"), ("Qt6Core.dll", "qtbase-binary")):
            body = archive_bytes(tar, inputs[archive_key], "bin/" + name, env)
            if digest(body) != NATIVE_PINS[name]:
                raise ValueError("Unreviewed native compiler dependency")
            (tool_dir / name).write_bytes(body)
        for record in records:
            name = record["catalog"].removesuffix(".qm") + ".ts"
            body = generated[name] if record["source_kind"] == "generated-english-ts" else sources[record["source_path"]]
            (ts_dir / name).write_bytes(body)
            command = [str(tool_dir / "lrelease.exe"), "-silent", str(ts_dir / name),
                       "-qm", str(qm_dir / record["catalog"])]
            subprocess.run(command, check=True, capture_output=True, cwd=tool_dir, env=env, timeout=30)
            rebuilt = (qm_dir / record["catalog"]).read_bytes()
            record["rebuilt_sha256"] = digest(rebuilt)
            record["byte_identical"] = rebuilt == compiled[record["catalog"]]
        result["native_pins"] = NATIVE_PINS
        result["all_byte_identical"] = all(item["byte_identical"] for item in records)
        if not result["all_byte_identical"]:
            result["mismatched_catalogs"] = [r["catalog"] for r in records if not r["byte_identical"]]
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--tools-inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-compiler", action="store_true")
    result = run(parser.parse_args())
    print(json.dumps({"catalogs": len(result["catalogs"]), "compiler_run": result["compiler_run"],
                      "all_byte_identical": result.get("all_byte_identical")}))
    return 0 if result.get("all_byte_identical", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
