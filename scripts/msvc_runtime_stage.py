"""Stage the three pinned Microsoft runtime files without installing or loading them.

The stage binds exact DLL bytes to the reviewed package manifest and a prior
package-verification receipt. It conveys no redistribution or release approval.
Only the three explicit files are build inputs; the directory is not a DLL
search-path root and no host System32 installation is required.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat


SCHEMA = "dupez.msvc-runtime-stage.v1"
NAMES = ("MSVCP140.dll", "MSVCP140_1.dll", "MSVCP140_2.dll")
ORIGIN = "pinned-msvc-redist"
MAX_JSON = 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
HASH = re.compile(r"[a-f0-9]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _ordinary(path: Path, *, directory: bool = False) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        metadata = part.lstat()
        _require(not stat.S_ISLNK(metadata.st_mode) and not getattr(metadata, "st_file_attributes", 0) & 0x400,
                 "MSVC stage paths must not contain links or reparse points")
    metadata = path.lstat()
    _require(stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode),
             "MSVC stage input has an unexpected path type")
    if not directory:
        _require(metadata.st_nlink == 1, "MSVC stage files must not have hard links")
    return path


def _snapshot(path: Path, limit: int = MAX_FILE) -> bytes:
    path = _ordinary(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        _require(0 < before.st_size <= limit, "MSVC stage input exceeds its size bound")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = _ordinary(path).stat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_nlink)
    _require(identity(before) == identity(after) == identity(current) and len(data) == before.st_size,
             "MSVC stage input changed while reading")
    return data


def _pin(data: bytes) -> dict:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate MSVC stage JSON key")
        result[key] = value
    return result


def _object(data: bytes) -> dict:
    value = json.loads(data, object_pairs_hook=_unique)
    _require(isinstance(value, dict), "MSVC stage JSON must be an object")
    return value


def _valid_pin(value: dict) -> bool:
    return (isinstance(value, dict) and type(value.get("size")) is int and 0 < value["size"] <= MAX_FILE
            and isinstance(value.get("sha256"), str) and bool(HASH.fullmatch(value["sha256"])))


def _same_json(left, right) -> bool:
    # Python equality alone treats false/0 and integer/float values as equal.
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(right, sort_keys=True, separators=(",", ":"))


def _manifest(data: bytes) -> dict:
    manifest = _object(data)
    _require(manifest.get("schema") == "dupez.msvc-redist-inputs.v1"
             and manifest.get("release_approved") is False and manifest.get("distribution_approved") is False,
             "Unsupported or approving MSVC input manifest")
    rows = manifest.get("binaries")
    _require(isinstance(rows, list) and len(rows) == 3
             and all(isinstance(row, dict) for row in rows)
             and {row.get("name") for row in rows} == set(NAMES), "MSVC manifest must pin exactly three canonical DLLs")
    for row in rows:
        _require(set(row) == {"name", "size", "sha256", "cabinet_member"} and _valid_pin(row)
                 and row["cabinet_member"] == row["name"].lower() + "_amd64", "Invalid MSVC binary pin or CAB member")
    package = manifest.get("package")
    _require(_valid_pin(package) and package.get("filename") == "VC_redist.x64.exe"
             and isinstance(package.get("version"), str) and isinstance(package.get("signer_thumbprint"), str),
             "Invalid Microsoft package identity")
    return manifest


def _upstream(receipt: dict, manifest: dict, manifest_pin: dict) -> None:
    _require(receipt.get("schema") == "dupez.msvc-redist-provenance.v1"
             and receipt.get("status") == "exact-upstream-package-bytes-verified", "Unsupported upstream MSVC receipt")
    _require(all(receipt.get(key) is False for key in (
        "release_approved", "distribution_approved", "installer_executed", "global_installation_performed", "elevation_requested")),
        "Upstream MSVC receipt has an unreviewed execution or approval scope")
    _require(isinstance(receipt.get("manifest"), dict)
             and all(receipt["manifest"].get(key) == value for key, value in manifest_pin.items())
             and _same_json(receipt.get("package"), manifest["package"]), "MSVC receipt differs from exact manifest/package pins")
    expected = [{**row, "origin": "pinned-microsoft-redist-minimum-x64-cabinet"} for row in manifest["binaries"]]
    _require(_same_json(receipt.get("binaries"), expected), "MSVC receipt binary mapping differs from manifest")
    signatures = receipt.get("signature_observations")
    _require(isinstance(signatures, list) and all(isinstance(row, dict) for row in signatures),
             "MSVC receipt lacks signature observations")
    by_name = {}
    for row in signatures:
        name = row.get("name")
        _require(isinstance(name, str) and name not in by_name, "Ambiguous MSVC signature observations")
        by_name[name] = row
    for name in ("package", *NAMES):
        row = by_name.get(name, {})
        _require(row.get("status") == "Valid" and "O=Microsoft Corporation" in str(row.get("subject", ""))
                 and row.get("file_version") == manifest["package"]["version"], "Missing reviewed Microsoft signature/version")
    _require(by_name["package"].get("thumbprint") == manifest["package"]["signer_thumbprint"],
             "Microsoft package signer differs from manifest")
    consumed = receipt.get("consumed_artifacts")
    _require(isinstance(consumed, list) and all(isinstance(row, dict) for row in consumed),
             "MSVC receipt lacks extracted artifact identities")
    by_path = {}
    for row in consumed:
        path = row.get("path")
        _require(isinstance(path, str) and path not in by_path, "Ambiguous MSVC consumed artifact identities")
        by_path[path] = row
    for row in manifest["binaries"]:
        recorded = by_path.get("dlls/" + row["cabinet_member"], {})
        _require(all(recorded.get(key) == row[key] for key in ("size", "sha256")),
                 "MSVC extracted member differs from pinned receipt")


def _stage_receipt(manifest: dict, manifest_data: bytes, upstream_data: bytes) -> dict:
    return {"schema": SCHEMA, "origin": ORIGIN, "manifest_sha256": _pin(manifest_data)["sha256"],
            "package": manifest["package"], "binaries": manifest["binaries"],
            "upstream_receipt": {"name": "upstream-receipt.json", **_pin(upstream_data)},
            "release_approved": False, "distribution_approved": False,
            "installer_executed": False, "global_installation_performed": False}


def validate_stage(stage: Path, manifest_path: Path) -> dict:
    """Verify a closed stage inventory; return exact local file mappings only."""
    stage = _ordinary(stage, directory=True)
    manifest_data = _snapshot(manifest_path, MAX_JSON)
    manifest = _manifest(manifest_data)
    expected_names = {*NAMES, "stage-receipt.json", "upstream-receipt.json"}
    _require({item.name for item in stage.iterdir()} == expected_names, "MSVC stage contains missing or extra entries")
    receipt_data = _snapshot(stage / "stage-receipt.json", MAX_JSON)
    upstream_data = _snapshot(stage / "upstream-receipt.json", MAX_JSON)
    _upstream(_object(upstream_data), manifest, _pin(manifest_data))
    receipt = _object(receipt_data)
    _require(_same_json(receipt, _stage_receipt(manifest, manifest_data, upstream_data)), "MSVC stage receipt differs from pinned inputs")
    binaries = []
    pins = {}
    for row in manifest["binaries"]:
        source = stage / row["name"]
        data = _snapshot(source)
        _require(_pin(data) == {key: row[key] for key in ("size", "sha256")}, "MSVC staged DLL differs from manifest")
        pins[source] = _pin(data)
        binaries.append({"name": row["name"], **_pin(data), "source": str(source)})
    pins.update({Path(os.path.abspath(manifest_path)): _pin(manifest_data), stage / "stage-receipt.json": _pin(receipt_data),
                 stage / "upstream-receipt.json": _pin(upstream_data)})
    for path, pin in pins.items():
        _require(_pin(_snapshot(path)) == pin, "MSVC stage changed during validation")
    _require({item.name for item in stage.iterdir()} == expected_names, "MSVC stage inventory changed during validation")
    return {"manifest_sha256": receipt["manifest_sha256"], "package_sha256": manifest["package"]["sha256"],
            "stage_receipt_sha256": _pin(receipt_data)["sha256"],
            "upstream_receipt_sha256": _pin(upstream_data)["sha256"], "binaries": binaries}


def prepare_stage(verified_root: Path, output: Path, manifest_path: Path) -> dict:
    """Copy only receipt-verified DLL snapshots to a fresh private build stage."""
    verified_root = _ordinary(verified_root, directory=True)
    manifest_data = _snapshot(manifest_path, MAX_JSON)
    manifest = _manifest(manifest_data)
    upstream_path = verified_root / "receipt.json"
    upstream_data = _snapshot(upstream_path, MAX_JSON)
    _upstream(_object(upstream_data), manifest, _pin(manifest_data))
    inputs = {Path(os.path.abspath(manifest_path)): manifest_data, upstream_path: upstream_data}
    binary_data = {}
    for row in manifest["binaries"]:
        source = verified_root / "dlls" / row["cabinet_member"]
        data = _snapshot(source)
        _require(_pin(data) == {key: row[key] for key in ("size", "sha256")}, "MSVC extracted DLL differs from manifest")
        inputs[source] = data
        binary_data[row["name"]] = data
    output = Path(os.path.abspath(output))
    _ordinary(output.parent, directory=True)
    _require(not os.path.lexists(output), "MSVC output stage must be new")
    output.mkdir()
    for name, data in {**binary_data, "upstream-receipt.json": upstream_data}.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    for path, data in inputs.items():
        _require(_snapshot(path) == data, "MSVC source changed during staging")
    receipt = _stage_receipt(manifest, manifest_data, upstream_data)
    with (output / "stage-receipt.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return validate_stage(output, manifest_path)
