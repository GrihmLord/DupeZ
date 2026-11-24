#!/usr/bin/env python3
"""Rebuild pinned Qt 6.12.1 catalogs using a private, verified lrelease.

This reproduces translation artifacts, not the native compiler or Qt library.
No installation, administrator token, Compat launch or production lock change
is part of this recipient recipe. Compiler execution requires --run-compiler.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import msvc_runtime_stage, prepare_qt_candidate as candidate
from scripts import validate_frozen_runtime as runtime_validation
from scripts import verify_qt_translation_sources as previous

EXTRA_INPUTS = {
    "qttools-binary": {
        "filename": "qttools-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z",
        "url": "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6121/qt6_6121_msvc2022_64/qt.qt6.6121.win64_msvc2022_64/6.12.1-0-202611180427qttools-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z",
        "size": 27361239,
        "sha256": "38870d9905d612d6801d2b2e0d2a1e48dc84a641f0674ee7106df3a80f820215",
        "members": 641,
        "member_listing_sha256": "e500de9d900247dd9c36c4eed35586f2fb3ee167f929c0c5907020214e0ff09c",
    },
    "qttools-source": {
        "filename": "qttools-everywhere-src-6.12.1.tar.xz",
        "url": "https://download.qt.io/online/qtsdkrepository/all_os/qt/qt6_6121_unix_line_endings_src/qt.qt6.6121.src/6.12.1-0-202611180426qttools-everywhere-src-6.12.1.tar.xz",
        "size": 10974184,
        "sha256": "d8e677228c9dd0b14801330c273bd0d4b41980a0b2e1fb498ca0bad266018a56",
    },
}
NATIVE_PINS = {
    "lrelease.exe": {"size": 687416, "sha256": "5608cc3db263d7d000faee8808a4e93cc64b46260f052feabaa62ba83030ef59"},
    "Qt6Core.dll": {"size": 10501944, "sha256": "3b803976495efa3f9e53b95d1dbdeec78504d6a6c9136665f119f8c6f37602a2"},
    "vcruntime140.dll": {"size": 178616, "sha256": "d1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7"},
    "vcruntime140_1.dll": {"size": 50112, "sha256": "a7146c08f89fe5b04541ab507cdb59ff7b44534d4ba3c668a426c6450a03434e"},
}
SIGNERS = {
    "lrelease.exe": "3D89F77A33C5AD89F45F681848958E755B727C5A",
    "Qt6Core.dll": "3D89F77A33C5AD89F45F681848958E755B727C5A",
    "vcruntime140.dll": "667BBA1E1F478221AA65DE4F75187A751B03A453",
    "vcruntime140_1.dll": "667BBA1E1F478221AA65DE4F75187A751B03A453",
    "MSVCP140.dll": "667BBA1E1F478221AA65DE4F75187A751B03A453",
    "MSVCP140_1.dll": "2650247AC56048BC7928663C02733D25898A1D6E",
    "MSVCP140_2.dll": "2650247AC56048BC7928663C02733D25898A1D6E",
}
SIGNATURE_SCRIPT = r"""param([string]$ToolDirectory)
$ErrorActionPreference = 'Stop'
$rows = foreach ($item in Get-ChildItem -LiteralPath $ToolDirectory -File) {
    $sig = Get-AuthenticodeSignature -LiteralPath $item.FullName
    [pscustomobject]@{name=$item.Name;status=[string]$sig.Status;
        subject=$sig.SignerCertificate.Subject;thumbprint=$sig.SignerCertificate.Thumbprint;
        file_version=$item.VersionInfo.FileVersion}
}
$rows | ConvertTo-Json -Depth 4
"""


def snapshot(path: Path) -> bytes:
    return msvc_runtime_stage._snapshot(path)


def pin_bytes(data: bytes) -> dict:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def require_pin(data: bytes, expected: dict) -> None:
    if pin_bytes(data) != {key: expected[key] for key in ("size", "sha256")}:
        raise ValueError("Translation input differs from its exact byte pin")


def validate_tool(directory: Path, pins: dict) -> None:
    candidate.ordinary_path(directory)
    if {entry.name for entry in directory.iterdir()} != set(pins):
        raise ValueError("Private compiler directory contains missing or extra entries")
    for name, expected in pins.items():
        require_pin(snapshot(directory / name), expected)


def validate_signatures(rows: object) -> list[dict]:
    if not isinstance(rows, list) or len(rows) != len(SIGNERS):
        raise ValueError("Incomplete compiler signature observations")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("name") not in SIGNERS or row["name"] in seen:
            raise ValueError("Ambiguous compiler signature observation")
        name = row["name"]
        seen.add(name)
        qt = name in {"lrelease.exe", "Qt6Core.dll"}
        publisher = "O=The QT Company Oy" if qt else "O=Microsoft Corporation"
        version_parts = (6, 12, 1, 0) if qt else (14, 51, 36247, 0)
        version = ".".join(map(str, version_parts))
        if (row.get("status") != "Valid" or row.get("thumbprint") != SIGNERS[name]
                or publisher not in str(row.get("subject", "")) or row.get("file_version") != version):
            raise ValueError("Unreviewed compiler signature, publisher or version")
    return sorted(rows, key=lambda row: row["name"])


def source_tag(path: Path) -> str:
    with tarfile.open(path, "r|xz") as archive:
        for member in archive:
            candidate.safe_member(member.name)
            if member.name == ".tag":
                if not member.isfile() or not 0 < member.size <= 128:
                    raise ValueError("Invalid source tag member")
                stream = archive.extractfile(member)
                assert stream is not None
                value = stream.read(129).decode("ascii").strip()
                if not re.fullmatch(r"[a-f0-9]{40}", value):
                    raise ValueError("Invalid source revision")
                return value
    raise ValueError("Source export lacks its revision")


def verify_declared_revision(document: dict, name: str, repository: str, tag: str) -> dict:
    rows = [row for row in document["packages"] if row.get("name") == name]
    expected = "git://code.qt.io/qt/" + repository + ".git@" + tag
    if len(rows) != 1 or rows[0].get("versionInfo") != "6.12.1" or rows[0].get("downloadLocation") != expected:
        raise ValueError("Compiler/library declared revision differs from source export")
    return {"package": name, "version": "6.12.1", "repository": repository, "source_commit": tag}


def catalog_checksums(document: dict) -> dict[str, str]:
    result = {}
    for row in document["files"]:
        name = row["fileName"].replace("\\", "/").removeprefix("./")
        if not name.startswith("translations/") or not name.endswith(".qm"):
            continue
        candidate.safe_member(name)
        basename = name.removeprefix("translations/")
        if not re.fullmatch(r"[A-Za-z0-9_]+\.qm", basename):
            raise ValueError("Unexpected catalog basename")
        checksums = [item["checksumValue"] for item in row["checksums"] if item["algorithm"] == "SHA1"]
        if len(checksums) != 1 or not re.fullmatch(r"[a-f0-9]{40}", checksums[0]):
            raise ValueError("Invalid catalog SPDX checksum")
        if basename in result and result[basename] != checksums[0]:
            raise ValueError("Conflicting Debug/Release catalog checksum")
        result[basename] = checksums[0]
    if len(result) != 314:
        raise ValueError("Unexpected reviewed catalog set")
    return result


def lock_input(stack: ExitStack, path: Path, pin: dict) -> None:
    candidate.ordinary_path(path, file=True)
    stack.enter_context(runtime_validation._locked_release_executable(
        path, expected_hash=pin["sha256"], expected_size=pin["size"]))


def _run_locked(args: argparse.Namespace, locks: ExitStack) -> dict:
    if sys.platform != "win32" or args.run_compiler and ctypes.windll.shell32.IsUserAnAdmin():
        raise ValueError("Run this Windows review as a standard user without elevation")
    cache = candidate.ordinary_path(args.inputs)
    output = candidate.ordinary_path(args.output, missing=True)
    if not output.is_relative_to(ROOT / "build") or output.exists():
        raise ValueError("Output must be a new directory under repository build/")
    manifest_path = ROOT / "packaging/qt-raster-no-network-inputs.json"
    manifest_data = snapshot(manifest_path)
    manifest, manifest_sha = candidate.load_manifest_snapshot(manifest_path)
    if manifest["qt_version"] != "6.12.1" or manifest["schema"] != "dupez.qt-candidate-inputs.v5":
        raise ValueError("Unreviewed translation candidate")
    if hashlib.sha256(manifest_data).hexdigest() != manifest_sha:
        raise ValueError("Candidate manifest changed during inspection")
    pins = {row["id"]: row for row in manifest["inputs"]}
    pins = {key: pins[key] for key in ("qtbase-binary", "qtbase-source", "qttranslations-binary", "qttranslations-source")}
    pins.update(EXTRA_INPUTS)
    inputs = {key: cache / row["filename"] for key, row in pins.items()}
    for key, path in inputs.items():
        lock_input(locks, path, pins[key])
    recipe_inputs = {path: pin_bytes(snapshot(path)) for path in (Path(__file__), Path(previous.__file__),
                     Path(candidate.__file__), Path(msvc_runtime_stage.__file__), Path(runtime_validation.__file__), manifest_path)}
    source = previous.source_files(inputs["qttranslations-source"])
    generated = previous.english_recipe(source)
    compiler_source = previous.source_files(inputs["qttools-source"])
    output.mkdir()
    env = candidate.child_environment(output / "private")
    tar = candidate.ordinary_path(candidate.system_directory() / "tar.exe", file=True)
    for key in ("qtbase-binary", "qttranslations-binary", "qttools-binary"):
        candidate.inspect_7z(inputs[key], pins[key], tar, env)
    get = lambda key, member: previous.archive_bytes(tar, inputs[key], member, env)
    compiler_spdx = get("qttools-binary", "sbom/qttools-6.12.1.source.spdx")
    correlation = previous.correlate_sources(compiler_source, compiler_spdx)
    if correlation["linguist_unmatched"]:
        raise ValueError("Compiler source subset differs from source SPDX")
    documents = {key: json.loads(get(key, member), object_pairs_hook=candidate._unique_object) for key, member in (
        ("qttools-binary", "sbom/qttools-6.12.1.spdx.json"), ("qtbase-binary", "sbom/qtbase-6.12.1.spdx.json"),
        ("qttranslations-binary", "sbom/qttranslations-6.12.1.spdx.json"))}
    revisions = [verify_declared_revision(documents["qttools-binary"], "lrelease", "qttools", source_tag(inputs["qttools-source"])),
                 verify_declared_revision(documents["qtbase-binary"], "Core", "qtbase", source_tag(inputs["qtbase-source"]))]
    checksums = catalog_checksums(documents["qttranslations-binary"])
    reference = output / "reference"
    reference.mkdir()
    previous.pinned_file(inputs["qttranslations-binary"], pins["qttranslations-binary"])
    subprocess.run([str(tar), "-xf", str(inputs["qttranslations-binary"]), "-C", str(reference)],
                   check=True, capture_output=True, env=env, timeout=60)
    compiled = {}
    for name, checksum in checksums.items():
        body = snapshot(reference / "translations" / name)
        if previous.digest(body, "sha1") != checksum:
            raise ValueError("Catalog differs from upstream binary SPDX")
        compiled[name] = body
    records = previous.match_catalogs(source, compiled, generated)
    retained = {"qtbase_" + locale + ".qm" for locale in manifest["translation_locales"]}
    if len(retained) != 33 or not retained <= compiled.keys() or sum(r["source_kind"] == "generated-english-ts" for r in records) != 13:
        raise ValueError("Unexpected retained catalog or generated-source set")
    result = {"schema": "dupez.qt6121-translation-rebuild.v1", "qt_version": "6.12.1", "candidate_manifest_sha256": manifest_sha,
              "scope": "Translation artifact rebuild using official native compiler; not a native compiler/library rebuild",
              "compiler_run": args.run_compiler, "input_archives": pins, "source_declared_revisions": revisions,
              "compiler_source_correlation": correlation, "english_recipe_sha256": previous.RECIPE_SHA256,
              "retained_catalogs": sorted(retained), "catalogs": records, "native_compiler_rebuilt": False,
              "compat_runtime_tested": False, "release_approved": False, "distribution_approved": False}
    if args.run_compiler:
        if args.msvc_stage is None or args.python_base is None:
            raise ValueError("Compiler execution requires the verified MSVC stage and Python base")
        stage = msvc_runtime_stage.validate_stage(args.msvc_stage, ROOT / "packaging/msvc-redist-inputs.json")
        python_base = candidate.ordinary_path(args.python_base)
        tool, ts_dir, qm_dir = output / "tool", output / "ts", output / "qm"
        for directory in (tool, ts_dir, qm_dir):
            directory.mkdir()
        native = dict(NATIVE_PINS)
        for name, key in (("lrelease.exe", "qttools-binary"), ("Qt6Core.dll", "qtbase-binary")):
            data = get(key, "bin/" + name)
            require_pin(data, NATIVE_PINS[name])
            (tool / name).write_bytes(data)
        for name in ("vcruntime140.dll", "vcruntime140_1.dll"):
            data = snapshot(python_base / name)
            require_pin(data, NATIVE_PINS[name])
            recipe_inputs[python_base / name] = NATIVE_PINS[name]
            (tool / name).write_bytes(data)
        for row in stage["binaries"]:
            data = snapshot(Path(row["source"]))
            require_pin(data, row)
            native[row["name"]] = {key: row[key] for key in ("size", "sha256")}
            (tool / row["name"]).write_bytes(data)
        # Hash through held read-only Windows handles. Denying both write and
        # delete sharing prevents a swap/restore between inspection and use.
        for name, expected in native.items():
            lock_input(locks, tool / name, expected)
        validate_tool(tool, native)
        signature_script = output / "check-signatures.ps1"
        signature_script.write_text(SIGNATURE_SCRIPT, encoding="utf-8", newline="\n")
        signature_pin = pin_bytes(SIGNATURE_SCRIPT.encode("utf-8"))
        lock_input(locks, signature_script, signature_pin)
        system = candidate.system_directory()
        signature_env = {**env, "PSModulePath": str(system / "WindowsPowerShell/v1.0/Modules")}
        observed = subprocess.run([str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive",
                                   "-File", str(signature_script), "-ToolDirectory", str(tool)],
                                  check=True, capture_output=True, env=signature_env, timeout=120)
        signatures = validate_signatures(json.loads(observed.stdout.decode("utf-8-sig")))
        for record in records:
            name = record["catalog"].removesuffix(".qm") + ".ts"
            body = generated[name] if record["source_kind"] == "generated-english-ts" else source[record["source_path"]]
            (ts_dir / name).write_bytes(body)
            validate_tool(tool, native)
            with ExitStack() as source_lock:
                lock_input(source_lock, ts_dir / name, pin_bytes(body))
                subprocess.run([str(tool / "lrelease.exe"), "-silent", str(ts_dir / name), "-qm", str(qm_dir / record["catalog"])],
                               check=True, capture_output=True, cwd=tool, env=env, timeout=30)
            require_pin(snapshot(ts_dir / name), {"size": len(body), "sha256": record["ts_sha256"]})
            rebuilt = snapshot(qm_dir / record["catalog"])
            record.update(rebuilt_sha256=previous.digest(rebuilt), byte_identical=rebuilt == compiled[record["catalog"]])
        validate_tool(tool, native)
        if msvc_runtime_stage.validate_stage(args.msvc_stage, ROOT / "packaging/msvc-redist-inputs.json") != stage:
            raise ValueError("MSVC stage changed during compilation")
        result.update(native_pins=native, signature_observations=signatures,
                      signature_script=signature_pin,
                      execution_input_lock_policy="Archive, native tool and signature-script reads deny write/delete through use; each TS is locked through compilation",
                      msvc_stage={key: value for key, value in stage.items() if key != "binaries"},
                      os_dependency_scope="Windows API DLLs, including ICU, remain OS-loaded; not bundled source inputs",
                      all_byte_identical=all(row["byte_identical"] for row in records),
                      retained_all_byte_identical=all(row["byte_identical"] for row in records if row["catalog"] in retained))
    for key, path in inputs.items():
        previous.pinned_file(path, pins[key])
    for path, expected in recipe_inputs.items():
        require_pin(snapshot(path), expected)
    result["recipes"] = [{"name": path.name, **expected} for path, expected in recipe_inputs.items()]
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def run(args: argparse.Namespace) -> dict:
    with ExitStack() as locks:
        return _run_locked(args, locks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--msvc-stage", type=Path)
    parser.add_argument("--python-base", type=Path)
    parser.add_argument("--run-compiler", action="store_true")
    result = run(parser.parse_args())
    print(json.dumps({"catalogs": len(result["catalogs"]), "retained_catalogs": len(result["retained_catalogs"]),
                      "compiler_run": result["compiler_run"], "all_byte_identical": result.get("all_byte_identical")}))
    return 0 if result.get("all_byte_identical", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
