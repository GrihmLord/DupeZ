#!/usr/bin/env python3
"""Prepare an offline, engineering-only Windows Qt adoption profile.

The profile is separate from canonical production locks and distribution gates.
Its wheel remains the real self-contained PyQt6 distribution; no synthetic Qt
dist-info or native-library overlay is created. Optional environment installation
uses only a complete hash-verified wheelhouse and never starts Qt or DupeZ.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

from scripts import license_payload, prepare_qt_candidate as candidate, sbom
from scripts.verify_requirements_lock import LockedEntry, parse_release_lock_entries

REMOVED = frozenset({"pyqt6-qt6", "pyqt6-webengine", "pyqt6-webengine-qt6"})
SOURCE_IDS = ("qtbase-source", "qtsvg-source", "qtimageformats-source", "qttranslations-source")
MAX_DOCUMENT = 2 * 1024 * 1024
MAX_DOCUMENT_TOTAL = 16 * 1024 * 1024
MAX_SOURCE_TOTAL = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 100000
HASH = re.compile(r"[a-f0-9]{64}\Z")
LIMITATIONS = [
    "Engineering profile only; no release, distribution, or source-delivery approval.",
    "Qt 6.11.3 is not a complete security remediation; current QtNetwork advisory and native-source gaps remain open.",
    "Qt source archive notices are reproduced conservatively, including modules/files not necessarily linked into retained binaries.",
    "Source notice collection does not prove exact native compilation or complete corresponding-source delivery.",
    "Upstream SPDX/license identifiers are reproduced records, not an owner licensing determination.",
]


def sha256(path: Path) -> str:
    candidate.ordinary_path(path, file=True)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def input_pin(path: Path) -> dict:
    candidate.ordinary_path(path, file=True)
    with path.open("rb") as stream:
        metadata = os.fstat(stream.fileno())
        return {"size": metadata.st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def verify_unchanged_inputs(pins: dict[Path, dict]) -> None:
    """Do not label consumed bytes using a later or stale input identity."""
    for path, pin in pins.items():
        try:
            candidate.verified(path, pin)
        except (OSError, ValueError) as error:
            raise ValueError(f"Engineering input changed during preparation: {path.name}") from error


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def effective_runtime(entries: list[LockedEntry], version: str, wheel_hash: str) -> list[LockedEntry]:
    if not HASH.fullmatch(wheel_hash):
        raise ValueError("Invalid independent wheel SHA256")
    by_name = {entry.name: entry for entry in entries}
    if not REMOVED <= by_name.keys() or by_name.get("pyqt6") is None:
        raise ValueError("Canonical runtime Qt distribution set changed")
    if by_name["pyqt6"].version != version:
        raise ValueError("Candidate binding version differs from the reviewed runtime")
    return [replace(entry, hashes=(wheel_hash,)) if entry.name == "pyqt6" else entry
            for entry in entries if entry.name not in REMOVED]


def write_lock(path: Path, entries: list[LockedEntry]) -> None:
    lines = ["# Generated engineering profile; canonical production lock remains unchanged."]
    for entry in entries:
        marker = f" ; {entry.marker}" if entry.marker else ""
        hashes = " ".join(f"--hash=sha256:{value}" for value in entry.hashes)
        lines.append(f"{entry.name}=={entry.version}{marker} {hashes}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect_source_notices(archive_path: Path, output: Path, component_id: str) -> list[dict]:
    """Copy selected ordinary source documents, never extract archive paths."""
    records, seen = [], set()
    total, document_total, count = 0, 0, 0
    with tarfile.open(archive_path, "r|xz") as archive:
        for member in archive:
            count += 1
            candidate.safe_member(member.name)
            if count > MAX_MEMBERS:
                raise ValueError("Too many source archive members")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Special source archive member")
            total += member.size
            if total > MAX_SOURCE_TOTAL:
                raise ValueError("Oversized source archive")
            name = Path(member.name).name
            selected = (member.name.startswith("LICENSES/") or name == "REUSE.toml"
                        or name == "qt_attribution.json"
                        or bool(re.fullmatch(r"(?:LICENSE|LICENCE|COPYING|COPYRIGHT|NOTICE)(?:[.-].*)?", name, re.I)))
            if not selected:
                continue
            if member.name.casefold() in seen or not 0 < member.size <= MAX_DOCUMENT:
                raise ValueError("Duplicate or oversized source notice")
            seen.add(member.name.casefold())
            document_total += member.size
            if document_total > MAX_DOCUMENT_TOTAL:
                raise ValueError("Oversized source notice set")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Unreadable source notice")
            body = stream.read(MAX_DOCUMENT + 1)
            if len(body) != member.size:
                raise ValueError("Truncated source notice")
            license_payload._normalize_text(body, label=member.name)
            relative = f"packaging/licenses/{component_id}/{member.name}"
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as target:
                target.write(body)
            records.append({"path": relative, "archive_member": member.name,
                            "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)})
    if not any("/LICENSES/" in row["path"] for row in records):
        raise ValueError("Source archive lacks its reviewed LICENSES namespace")
    return sorted(records, key=lambda row: row["path"])


def copy_inventory_documents(inventory: dict, source: Path, output: Path) -> None:
    paths = {"LICENSE.txt"}
    for component in inventory["runtime_components"]:
        paths.update(component["fallback_files"])
        paths.update(component["supplemental_files"])
    for component in inventory["additional_components"]:
        paths.update(component["supplemental_files"])
        if component["source"]["type"] == "repository-files":
            paths.update(component["source"]["paths"])
    for relative in sorted(paths):
        candidate.safe_member(relative)
        original = candidate.ordinary_path(source / relative, file=True)
        if original.stat().st_size > MAX_DOCUMENT:
            raise ValueError("Oversized repository notice")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as target:
            target.write(original.read_bytes())


def stage_wheels(entries: list[LockedEntry], caches: list[Path], wheelhouse: Path) -> tuple[list[dict], list[str]]:
    """Admit one compatible, hash-locked wheel per distribution; never resolve online."""
    expected = {}
    for entry in entries:
        if entry.name in expected and entry != expected[entry.name]:
            prior = expected[entry.name]
            if (entry.version, entry.hashes) != (prior.version, prior.hashes):
                raise ValueError(f"Conflicting runtime/build locks for {entry.name}")
        expected[entry.name] = entry
    tags = set(cpython_tags((3, 13), abis=["cp313"], platforms=["win_amd64"]))
    tags.update(compatible_tags((3, 13), interpreter="cp313", platforms=["win_amd64"]))
    staged = {}
    for directory in [wheelhouse, *caches]:
        candidate.ordinary_path(directory)
        for path in sorted(directory.glob("*.whl")):
            name, version, _, wheel_tags = parse_wheel_filename(path.name)
            name = canonicalize_name(name)
            entry = expected.get(name)
            if entry is None or name in staged or str(version) != entry.version or not tags & wheel_tags:
                continue
            checksum = sha256(path)
            if checksum not in entry.hashes:
                continue
            candidate.inspect_wheel(path)
            destination = wheelhouse / path.name
            if path != destination:
                with destination.open("xb") as target, path.open("rb") as source:
                    shutil.copyfileobj(source, target)
                if sha256(destination) != checksum:
                    raise ValueError("Wheel changed during staging")
            staged[name] = {"name": name, "version": str(version), "filename": path.name,
                            "sha256": checksum, "size": destination.stat().st_size}
    return [staged[name] for name in sorted(staged)], sorted(set(expected) - staged.keys())


def profile_sbom(entries: list[LockedEntry], manifest: dict, wheel_hash: str, product_version: str) -> dict:
    result = sbom.build_sbom(entries, product_version=product_version)
    result["metadata"]["properties"].append({"name": "dupez:engineering-only", "value": "true"})
    for component in result["components"]:
        if component["name"] == "pyqt6":
            component["externalReferences"] = [{"type": "build-meta", "url": "https://github.com/GrihmLord/DupeZ"}]
            component.setdefault("properties", []).extend([
                {"name": "dupez:distribution-origin", "value": "locally-derived-self-contained-wheel"},
                {"name": "dupez:derived-wheel-sha256", "value": wheel_hash},
                {"name": "dupez:bundled-qt-version", "value": manifest["qt_version"]},
            ])
    for source_id in SOURCE_IDS:
        name = source_id.removesuffix("-source")
        result["components"].append({"type": "library", "name": name, "version": manifest["qt_version"],
            "bom-ref": f"pkg:generic/qt/{name}@{manifest['qt_version']}",
            "purl": f"pkg:generic/qt/{name}@{manifest['qt_version']}",
            "properties": [{"name": "dupez:scope", "value": "source module for bundled native payload; transitive inventory incomplete"}]})
    return result


def install_environment(output: Path, product_version: str) -> dict:
    if sys.platform != "win32" or sys.version_info[:3] != (3, 13, 17) or sys.maxsize <= 2**32:
        raise ValueError("Installation requires the reviewed Windows x64 CPython 3.13.17 interpreter")
    environment = candidate.child_environment(output / "private")
    build = output / "build-venv"
    log = output / "install.log"
    commands = [
        [sys.executable, "-I", "-m", "venv", str(build)],
        [str(build / "Scripts/python.exe"), "-I", "-m", "pip", "install", "--no-index", "--no-cache-dir",
         "--only-binary=:all:", "--require-hashes", "--find-links", str(output / "wheelhouse"),
         "-r", str(output / "requirements-locked.txt"), "-r", str(output / "packaging/requirements-build-locked.txt")],
        [str(build / "Scripts/python.exe"), "-I", "-m", "pip", "check"],
    ]
    metadata_check = """import hashlib, importlib.metadata as m, json, pathlib, sys, zipfile
root=pathlib.Path(sys.argv[1]); records=json.loads((root/'engineering-profile.json').read_text())
names={d.metadata['Name'].lower().replace('_','-') for d in m.distributions() if d.metadata['Name'].lower().startswith('pyqt6')}
if names != {'pyqt6','pyqt6-sip'}: raise RuntimeError('Unexpected Qt distribution identities')
wheel=root/records['candidate_wheel']['path']; dist=m.distribution('PyQt6')
with zipfile.ZipFile(wheel) as archive:
 for name in archive.namelist():
  if name.endswith('/') or name.endswith('.dist-info/RECORD'): continue
  if archive.read(name) != pathlib.Path(dist.locate_file(name)).read_bytes(): raise RuntimeError('Installed candidate payload differs')
print('Installed real PyQt6 metadata and wheel payload verified')
"""
    commands.append([str(build / "Scripts/python.exe"), "-I", "-c", metadata_check, str(output)])
    notices = """import pathlib,sys
sys.path.insert(0,sys.argv[1])
from scripts.license_payload import build_license_payload,validate_license_payload
root=pathlib.Path(sys.argv[2]); dist=root/'notices'
payload=build_license_payload(root=root,dist=dist,product_version=sys.argv[3])
errors=validate_license_payload(root=root,dist=dist,expected_version=sys.argv[3])
if errors: raise RuntimeError('; '.join(errors))
print('Engineering notice payload verified:',len(payload['documents']),'documents')
"""
    commands.append([str(build / "Scripts/python.exe"), "-I", "-c", notices, str(ROOT), str(output), product_version])
    with log.open("xb") as target:
        for command in commands:
            subprocess.run(command, cwd=output, env=environment, stdout=target, stderr=subprocess.STDOUT,
                           check=True, timeout=600)
    return {"build_venv": "build-venv", "pip_check": "passed", "installed_wheel_payload": "verified",
            "notice_payload": "verified", "log_sha256": sha256(log)}


def prepare(candidate_root: Path, expected_wheel_hash: str, output: Path, caches: list[Path],
            *, install: bool = False, product_version: str = "5.8.0") -> dict:
    candidate_root = candidate.ordinary_path(candidate_root)
    output = candidate.ordinary_path(output, missing=True)
    if not output.is_relative_to(ROOT / "build") or output.exists():
        raise ValueError("Output must be a new directory under repository build/")
    if not HASH.fullmatch(expected_wheel_hash):
        raise ValueError("Invalid independent wheel SHA256")
    if not re.fullmatch(r"\d+\.\d+\.\d+", product_version):
        raise ValueError("Invalid engineering product version")
    manifest_path = ROOT / "packaging/qt-raster-inputs.json"
    manifest, manifest_hash = candidate.load_manifest_snapshot(manifest_path)
    receipt_path = candidate.ordinary_path(candidate_root / "preparation-receipt.json", file=True)
    if receipt_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Oversized preparation receipt")
    receipt_bytes = receipt_path.read_bytes()
    receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()
    receipt = json.loads(receipt_bytes)
    if (manifest.get("profile") != "frozen-raster" or receipt.get("profile") != "frozen-raster"
            or receipt.get("schema") != "dupez.qt-candidate-preparation.v3"
            or receipt.get("status") != "candidate-wheel-prepared" or receipt.get("manifest_sha256") != manifest_hash
            or receipt.get("wheel", {}).get("sha256") != expected_wheel_hash):
        raise ValueError("Unreviewed frozen raster preparation receipt")
    candidate.safe_member(receipt["wheel"]["path"])
    wheel = candidate.ordinary_path(candidate_root / receipt["wheel"]["path"], file=True)
    if sha256(wheel) != expected_wheel_hash:
        raise ValueError("Candidate wheel differs from independent expected digest")
    candidate.validate_candidate_wheel(wheel, manifest)
    runtime_path = ROOT / "requirements-locked.txt"
    build_path = ROOT / "packaging/requirements-build-locked.txt"
    inventory_path = ROOT / "packaging/third-party-components.json"
    base_pins = {path: input_pin(path) for path in (runtime_path, build_path, inventory_path, ROOT / "LICENSE.txt")}
    input_pins = {
        **base_pins,
        manifest_path: {"size": manifest_path.stat().st_size, "sha256": manifest_hash},
        receipt_path: {"size": len(receipt_bytes), "sha256": receipt_hash},
        wheel: {"size": wheel.stat().st_size, "sha256": expected_wheel_hash},
    }
    runtime = effective_runtime(parse_release_lock_entries(runtime_path), manifest["binding_version"], expected_wheel_hash)
    build_entries = parse_release_lock_entries(build_path)
    inventory = json.loads(inventory_path.read_bytes())
    inventory["runtime_components"] = [row for row in inventory["runtime_components"] if row["name"] not in REMOVED]
    if {row["name"]: row["version"] for row in inventory["runtime_components"]} != {entry.name: entry.version for entry in runtime}:
        raise ValueError("Engineering runtime inventory differs from effective lock")
    pins = {item["id"]: item for item in manifest["inputs"]}
    for source_id in SOURCE_IDS:
        source = candidate.ordinary_path(candidate_root / "inputs" / pins[source_id]["filename"], file=True)
        candidate.verified(source, pins[source_id])
        input_pins[source] = pins[source_id]
    output.mkdir()
    (output / "packaging").mkdir()
    (output / "wheelhouse").mkdir()
    copy_inventory_documents(inventory, ROOT, output)
    write_lock(output / "requirements-locked.txt", runtime)
    (output / "packaging/requirements-build-locked.txt").write_bytes(build_path.read_bytes())
    shutil.copyfile(wheel, output / "wheelhouse" / wheel.name)
    if sha256(output / "wheelhouse" / wheel.name) != expected_wheel_hash:
        raise ValueError("Candidate wheel changed during staging")
    source_notices = {}
    for source_id in SOURCE_IDS:
        component_id = source_id.removesuffix("-source") + "-native"
        documents = collect_source_notices(candidate_root / "inputs" / pins[source_id]["filename"], output, component_id)
        source_notices[source_id] = {"input": pins[source_id], "documents": documents}
        inventory["additional_components"].append({
            "id": component_id, "name": source_id.removesuffix("-source"), "version": manifest["qt_version"],
            "declared_license": "LicenseRef-Qt-Source-Archive-Notices", "homepage": pins[source_id]["url"],
            "source": {"type": "repository-files", "paths": [row["path"] for row in documents]}, "supplemental_files": [],
        })
    write_json(output / "packaging/third-party-components.json", inventory)
    source_info = output / "docs/legal/SOURCE_AND_RELINK_V5.8.0.md"
    source_info.parent.mkdir(parents=True)
    source_info.write_text("# Engineering Qt source and notice review\n\n" + "\n".join(f"- {line}" for line in LIMITATIONS)
                           + "\n\nExact input archives and copied notice digests are recorded in engineering-profile.json.\n",
                           encoding="utf-8")
    license_payload._load_inventory(output, output / "packaging/third-party-components.json")
    staged, missing = stage_wheels([*runtime, *build_entries], caches, output / "wheelhouse")
    verify_unchanged_inputs(input_pins)
    result = {"schema": "dupez.qt-engineering-profile.v1", "profile": "frozen-raster",
              "production_locks_changed": False, "release_approved": False, "source_delivery_approved": False,
              "scope": "isolated engineering dependency/build/notices profile", "limitations": LIMITATIONS,
              "base_inputs": {path.relative_to(ROOT).as_posix(): pin["sha256"] for path, pin in base_pins.items()},
              "candidate_manifest_sha256": manifest_hash, "preparation_receipt_sha256": receipt_hash,
              "candidate_wheel": {"path": "wheelhouse/" + wheel.name, "sha256": expected_wheel_hash},
              "removed_distributions": sorted(REMOVED), "runtime_distribution_count": len(runtime),
              "effective_runtime_lock_sha256": sha256(output / "requirements-locked.txt"),
              "effective_inventory_sha256": sha256(output / "packaging/third-party-components.json"),
              "source_notices": source_notices, "wheelhouse": staged, "missing_wheels": missing}
    write_json(output / "engineering-profile.json", result)
    write_json(output / "engineering.sbom.json", profile_sbom(runtime, manifest, expected_wheel_hash, product_version))
    if install:
        if missing:
            raise ValueError("Offline wheel cache is incomplete: " + ", ".join(missing))
        generated_pins = {path: input_pin(path) for path in (
            output / "requirements-locked.txt", output / "packaging/requirements-build-locked.txt",
            output / "packaging/third-party-components.json", output / "engineering-profile.json",
            output / "engineering.sbom.json", output / "wheelhouse" / wheel.name,
        )}
        installed = install_environment(output, product_version)
        verify_unchanged_inputs({**input_pins, **generated_pins})
        write_json(output / "installation-receipt.json", installed)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--expected-wheel-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel-cache", type=Path, action="append", default=[])
    parser.add_argument("--install-build-env", action="store_true")
    parser.add_argument("--product-version", default="5.8.0")
    args = parser.parse_args()
    result = prepare(args.candidate_root, args.expected_wheel_sha256, args.output, args.wheel_cache,
                     install=args.install_build_env, product_version=args.product_version)
    print(json.dumps({"runtime_distributions": result["runtime_distribution_count"],
                      "missing_wheels": result["missing_wheels"], "release_approved": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
