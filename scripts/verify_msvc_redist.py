"""Offline proof of three MSVC DLLs in a pinned Microsoft redistributable.

The installer and DLLs are never executed. Only Windows expand.exe, a read-only
MSI database query, and Authenticode inspection are used. No installation,
elevation, networking, licensing approval, or production build change occurs.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packaging/msvc-redist-inputs.json"
MAX_INPUT = 64 * 1024 * 1024
NAMES = frozenset({"msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll"})
HASH = re.compile(r"[a-f0-9]{64}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,199}\Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ordinary(path: Path, *, file: bool = True) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        item = part.lstat()
        require(not stat.S_ISLNK(item.st_mode) and not getattr(item, "st_file_attributes", 0) & 0x400,
                "Links and reparse points are not accepted")
    require(path.is_file() if file else path.is_dir(), "Unexpected input path type")
    return path


def identity(path: Path) -> dict:
    path = ordinary(path)
    before = path.stat()
    require(before.st_size <= MAX_INPUT, "Input exceeds the size limit")
    with path.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    require((before.st_size, before.st_mtime_ns, before.st_ino)
            == (after.st_size, after.st_mtime_ns, after.st_ino), "Input changed while hashing")
    return {"name": path.name, "size": after.st_size, "sha256": sha256}


def verify(path: Path, pin: dict) -> dict:
    actual = identity(path)
    require(actual["sha256"] == pin["sha256"] and actual["size"] == pin["size"], "Input does not match its pin")
    return actual


def verify_unchanged(pins: dict[Path, dict]) -> None:
    for path, pin in pins.items():
        require(identity(path) == pin, "A consumed input changed during verification")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    require(identity(path)["size"] <= 1024 * 1024, "JSON input exceeds the size limit")
    result = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    require(isinstance(result, dict), "JSON input must be an object")
    return result


def validate_manifest(data: dict) -> None:
    require(data.get("schema") == "dupez.msvc-redist-inputs.v1", "Unsupported MSVC input schema")
    require(data.get("distribution_approved") is False and data.get("release_approved") is False,
            "Technical input pins cannot authorize distribution")
    rows = data["binaries"]
    require(len(rows) == 3 and {row["name"].casefold() for row in rows} == NAMES,
            "Exactly the reviewed three runtime DLLs must be pinned")
    for item in [data["package"], *data["containers"].values(),
                 data["minimum_runtime"]["msi"], data["minimum_runtime"]["cabinet"], *rows]:
        require(type(item["size"]) is int and 0 < item["size"] <= MAX_INPUT
                and bool(HASH.fullmatch(item["sha256"])), "Invalid size or hash pin")
    for row in rows:
        safe_token(row["cabinet_member"])
        require(row["cabinet_member"].casefold() == row["name"].casefold() + "_amd64", "Invalid CAB file identity")


def safe_token(value: str) -> str:
    require(isinstance(value, str) and bool(TOKEN.fullmatch(value)), "Unsafe cabinet member name")
    stem = value.split(".", 1)[0].casefold()
    require(stem not in {"con", "prn", "aux", "nul", *{f"com{i}" for i in range(10)}, *{f"lpt{i}" for i in range(10)}},
            "Reserved cabinet member name")
    return value


def unpack(fmt: str, data: bytes, offset: int) -> tuple:
    require(type(offset) is int and 0 <= offset <= len(data) - struct.calcsize(fmt), "Truncated binary structure")
    return struct.unpack_from(fmt, data, offset)


def burn_containers(data: bytes) -> dict[str, dict]:
    """Read the documented WiX Burn v2 PE section, without loading the image."""
    require(len(data) <= MAX_INPUT and data[:2] == b"MZ", "Not a bounded PE image")
    pe, = unpack("<I", data, 60)
    require(data[pe:pe + 4] == b"PE\0\0", "Missing PE signature")
    sections, = unpack("<H", data, pe + 6)
    optional_size, = unpack("<H", data, pe + 20)
    optional = pe + 24
    require(0 < sections <= 32 and optional_size >= 136 and unpack("<H", data, optional)[0] == 0x10B,
            "Unsupported Burn PE header")
    found = []
    for index in range(sections):
        position = optional + optional_size + index * 40
        unpack("<40s", data, position)
        if data[position:position + 8] == b".wixburn":
            size, offset = unpack("<II", data, position + 16)
            require(size >= 56 and offset + size <= len(data), "Truncated Burn section")
            found.append(offset)
    require(len(found) == 1, "Burn section is missing or duplicated")
    offset = found[0]
    require(unpack("<II", data, offset) == (0x00F14300, 2), "Unsupported Burn section version")
    stub, _checksum, original_signature, original_size, cabinet_format, count = unpack("<6I", data, offset + 24)
    require(cabinet_format == 1 and count == 2 and original_signature > 0 and original_size > 0,
            "Unsupported Burn container layout")
    ux_size, attached_size = unpack("<2I", data, offset + 48)
    signature, signature_size = unpack("<II", data, optional + 128)
    attached = original_signature + original_size
    require(stub > offset and stub + ux_size <= original_signature and attached + attached_size <= signature
            and signature + signature_size == len(data), "Burn container/certificate ranges overlap or escape the package")
    return {name: {"offset": start, "size": size, "sha256": digest(data[start:start + size])}
            for name, start, size in (("ux", stub, ux_size), ("attached", attached, attached_size))}


def cabinet_members(data: bytes) -> dict[str, int]:
    require(len(data) <= MAX_INPUT and data[:4] == b"MSCF", "Not a bounded cabinet")
    cabinet_size, = unpack("<I", data, 8)
    require(36 <= cabinet_size <= len(data), "Cabinet length mismatch")
    position, = unpack("<I", data, 16)
    minor, major, folders, files, flags = unpack("<BBHHH", data, 24)
    require((minor, major) == (3, 1) and 0 < folders <= 16 and 0 < files <= 256 and flags in (0, 4),
            "Unsupported cabinet format or continuation")
    header_size = 36
    if flags == 4:
        # Support the exact signed-CAB reserve layout used by this pinned input.
        reserve, folder_reserve, data_reserve = unpack("<HBB", data, 36)
        marker, signature_offset, signature_size, reserved_a, reserved_b = unpack("<5I", data, 40)
        require((reserve, folder_reserve, data_reserve, marker, reserved_a, reserved_b)
                == (20, 0, 0, 0x00100000, 0, 0)
                and signature_offset == cabinet_size and signature_size > 0
                and signature_offset + signature_size == len(data), "Unsupported signed cabinet reserve/trailer")
        header_size = 60
    else:
        require(cabinet_size == len(data), "Unsigned cabinet contains unaccounted trailing bytes")
    data = data[:cabinet_size]
    require(position >= header_size + folders * 8, "Cabinet file table overlaps its header")
    result, seen, total = {}, set(), 0
    for _ in range(files):
        size, _folder_offset, folder, _date, _time, _attributes = unpack("<IIHHHH", data, position)
        require(folder < folders and size <= MAX_INPUT, "Invalid cabinet file size or folder")
        end = data.find(b"\0", position + 16, min(len(data), position + 217))
        require(end >= position + 17, "Missing cabinet filename terminator")
        try:
            name = safe_token(data[position + 16:end].decode("ascii"))
        except UnicodeDecodeError as error:
            raise ValueError("Non-ASCII cabinet filename") from error
        require(name.casefold() not in seen, "Duplicate cabinet filename")
        seen.add(name.casefold())
        result[name] = size
        total += size
        require(total <= MAX_INPUT, "Cabinet expansion exceeds the limit")
        position = end + 1
    return result


def system_directory() -> Path:
    require(sys.platform == "win32", "Actual extraction requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.GetSystemDirectoryW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    function.restype = ctypes.c_uint
    value = ctypes.create_unicode_buffer(32768)
    length = function(value, len(value))
    require(0 < length < len(value), "Cannot identify the Windows system directory")
    return ordinary(Path(value.value), file=False)


def run(command: list[str], *, env: dict, input_text: str | None = None) -> str:
    result = subprocess.run(command, input=input_text, text=True, encoding="utf-8", errors="replace",
                            capture_output=True, env=env, timeout=60, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    require(result.returncode == 0, "A read-only Windows inspection/extraction command failed")
    return result.stdout


def signatures(paths: dict[str, Path], system: Path, env: dict) -> list[dict]:
    script = r"""$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new();
$items=[Console]::In.ReadToEnd() | ConvertFrom-Json;
$results=@(foreach($item in $items) {
 $s=Get-AuthenticodeSignature -LiteralPath $item.path;
 $v=(Get-Item -LiteralPath $item.path).VersionInfo;
 [pscustomobject]@{name=$item.name;status=$s.Status.ToString();subject=$s.SignerCertificate.Subject;
 thumbprint=$s.SignerCertificate.Thumbprint;file_version=$v.FileVersion;product_version=$v.ProductVersion}
}); ConvertTo-Json -InputObject $results -Depth 3 -Compress"""
    raw = run([str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoLogo", "-NoProfile", "-NonInteractive",
               "-Command", script], env=env,
              input_text=json.dumps([{"name": name, "path": str(path)} for name, path in paths.items()]))
    results = json.loads(raw)
    require(len(results) == len(paths) and {item["name"] for item in results} == set(paths), "Signature inventory mismatch")
    require(all(item["status"] == "Valid" and "O=Microsoft Corporation" in item["subject"] for item in results),
            "A reviewed input/tool lacks a valid Microsoft signature")
    return results


def extract(cabinet: Path, tokens: list[str], destination: Path, expand: Path, env: dict) -> dict[str, Path]:
    members = cabinet_members(cabinet.read_bytes())
    destination.mkdir()
    result = {}
    for token in tokens:
        safe_token(token)
        require(token in members, "Requested cabinet member is missing")
        run([str(expand), str(cabinet), "-F:" + token, str(destination)], env=env)
        target = ordinary(destination / token)
        require(target.stat().st_size == members[token], "Expanded member size mismatch")
        result[token] = target
    require({path.name for path in destination.iterdir()} == set(tokens), "Unexpected extracted member")
    return result


def read_msi_tables(path: Path, system: Path) -> dict[str, list[list[str]]]:
    """Use MSIDBOPEN_READONLY; no MSI install/action API is called."""
    msi = ctypes.WinDLL(str(system / "msi.dll"))
    handle = ctypes.c_uint
    specifications = {
        "MsiOpenDatabaseW": ([ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(handle)], ctypes.c_uint),
        "MsiDatabaseOpenViewW": ([handle, ctypes.c_wchar_p, ctypes.POINTER(handle)], ctypes.c_uint),
        "MsiViewExecute": ([handle, handle], ctypes.c_uint),
        "MsiViewFetch": ([handle, ctypes.POINTER(handle)], ctypes.c_uint),
        "MsiRecordGetStringW": ([handle, ctypes.c_uint, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint)], ctypes.c_uint),
        "MsiCloseHandle": ([handle], ctypes.c_uint),
    }
    for name, (arguments, result) in specifications.items():
        getattr(msi, name).argtypes, getattr(msi, name).restype = arguments, result
    database = handle()
    require(msi.MsiOpenDatabaseW(str(path), None, ctypes.byref(database)) == 0, "Cannot open MSI read-only")
    tables = {}
    try:
        for table, columns in (("Property", ("Property", "Value")), ("File", ("File", "FileName", "FileSize", "Version")),
                               ("Media", ("DiskId", "Cabinet"))):
            view = handle()
            query = "SELECT " + ",".join("`" + item + "`" for item in columns) + " FROM `" + table + "`"
            require(msi.MsiDatabaseOpenViewW(database, query, ctypes.byref(view)) == 0, "Cannot query MSI metadata")
            rows = []
            try:
                require(msi.MsiViewExecute(view, 0) == 0, "Cannot read MSI metadata")
                while True:
                    record = handle()
                    status = msi.MsiViewFetch(view, ctypes.byref(record))
                    if status == 259:
                        break
                    require(status == 0 and len(rows) < 512, "Invalid/oversized MSI result")
                    try:
                        fields = []
                        for index in range(1, len(columns) + 1):
                            buffer, size = ctypes.create_unicode_buffer(4096), ctypes.c_uint(4096)
                            require(msi.MsiRecordGetStringW(record, index, buffer, ctypes.byref(size)) == 0,
                                    "Invalid/oversized MSI metadata field")
                            fields.append(buffer.value)
                        rows.append(fields)
                    finally:
                        msi.MsiCloseHandle(record)
            finally:
                msi.MsiCloseHandle(view)
            tables[table] = rows
    finally:
        msi.MsiCloseHandle(database)
    return tables


def msi_mapping(tables: dict, manifest: dict) -> dict:
    properties = dict(tables["Property"])
    require(properties["ProductCode"] == manifest["minimum_runtime"]["product_code"]
            and properties["ProductVersion"] == manifest["minimum_runtime"]["product_version"], "MSI product identity mismatch")
    require(tables["Media"] == [["1", "cab1.cab"]], "MSI cabinet mapping differs")
    rows = {row[0]: row for row in tables["File"]}
    selected = []
    for item in manifest["binaries"]:
        row = rows[item["cabinet_member"]]
        require(row[1].split("|")[-1].casefold() == item["name"].casefold()
                and int(row[2]) == item["size"] and row[3] == manifest["package"]["version"], "MSI DLL identity mismatch")
        selected.append({"file_key": row[0], "filename": row[1], "size": int(row[2]), "version": row[3]})
    return {"product_name": properties["ProductName"], "product_code": properties["ProductCode"],
            "product_version": properties["ProductVersion"], "media": tables["Media"], "files": selected}


def verify_observation(observation: dict, binaries: list[dict]) -> None:
    rows = observation["binaries"]
    require(len(rows) == 3 and {(r["name"].casefold(), r["size"], r["sha256"]) for r in rows}
            == {(r["name"].casefold(), r["size"], r["sha256"]) for r in binaries}, "Previous System32 observation differs")


def word_text(document_xml: bytes) -> str:
    root = ET.fromstring(document_xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return " ".join("".join(node.text or "" for node in paragraph.iter(namespace + "t"))
                    for paragraph in root.iter(namespace + "p"))


def prepare(package: Path, license_doc: Path, observation_path: Path, output: Path,
            manifest_path: Path = MANIFEST) -> dict:
    inputs = {path: identity(path) for path in (package, license_doc, observation_path, manifest_path, Path(__file__))}
    manifest, observation = read_json(manifest_path), read_json(observation_path)
    validate_manifest(manifest)
    verify_observation(observation, manifest["binaries"])
    verify(package, manifest["package"])
    license_pin = {"size": manifest["license_reference"]["document_size"], "sha256": manifest["license_reference"]["document_sha256"]}
    verify(license_doc, license_pin)
    output = Path(os.path.abspath(output))
    require(output.is_relative_to(ROOT) and not output.exists(), "Output must be a new workspace directory")
    ordinary(output.parent, file=False)
    system = system_directory()
    expand = ordinary(system / "expand.exe")
    consumed = {expand: identity(expand)}
    output.mkdir()
    temporary = output / "temp"
    temporary.mkdir()
    env = dict(os.environ)
    for key in ("TEMP", "TMP", "TMPDIR"):
        env[key] = str(temporary)
    # PowerShell 7 parents can export a module path incompatible with inbox 5.1.
    # Load inspection cmdlets only from the corresponding Windows installation.
    env["PSModulePath"] = str(system / "WindowsPowerShell/v1.0/Modules")
    env["PSModuleAnalysisCachePath"] = str(temporary / "module-analysis-cache")
    before_signatures = signatures({"package": package, "expand.exe": expand}, system, env)
    package_signature = next(item for item in before_signatures if item["name"] == "package")
    require(package_signature["thumbprint"] == manifest["package"]["signer_thumbprint"]
            and package_signature["file_version"] == manifest["package"]["version"], "Unexpected package signer/version")
    with package.open("rb") as stream:
        data = stream.read(MAX_INPUT + 1)
    require(len(data) == manifest["package"]["size"] and digest(data) == manifest["package"]["sha256"],
            "Consumed package snapshot differs from its pin")
    containers = burn_containers(data)
    require(containers == manifest["containers"], "Burn container recipe differs from pins")
    for name, item in containers.items():
        content = data[item["offset"]:item["offset"] + item["size"]]
        cabinet_members(content)
        container_path = output / (name + ".cab")
        container_path.write_bytes(content)
        consumed[container_path] = verify(container_path, item)
    ux = extract(output / "ux.cab", ["0", "u17"], output / "ux", expand, env)
    consumed.update({path: identity(path) for path in ux.values()})
    burn = ET.parse(ux["0"]).getroot()
    payloads = {item.attrib["Id"]: item.attrib for item in burn.iter() if item.tag.rsplit("}", 1)[-1] == "Payload"}
    minimum = manifest["minimum_runtime"]
    attached = extract(output / "attached.cab", [minimum[k]["source_path"] for k in ("msi", "cabinet")],
                       output / "minimum-runtime", expand, env)
    for key in ("msi", "cabinet"):
        item = minimum[key]
        declared = payloads[item["payload_id"]]
        require(declared["SourcePath"] == item["source_path"] and declared["FilePath"].replace("\\", "/") == item["file_path"]
                and int(declared["FileSize"]) == item["size"] and declared["Container"] == "WixAttachedContainer",
                "Burn payload mapping differs from pinned package")
        actual = attached[item["source_path"]]
        consumed[actual] = verify(actual, item)
        require(hashlib.sha1(actual.read_bytes()).hexdigest() == declared["Hash"].lower(), "Burn payload SHA1 differs")
    license_urls = [item.attrib["LicenseUrl"] for item in ET.parse(ux["u17"]).getroot().iter() if "LicenseUrl" in item.attrib]
    require(license_urls == [manifest["license_reference"]["package_license_url"]], "Package license link mismatch")
    with zipfile.ZipFile(license_doc) as archive:
        require(archive.getinfo("word/document.xml").file_size <= 1024 * 1024, "License text too large")
        license_text = word_text(archive.read("word/document.xml"))
    require("Cpp_v14_ENU.1033" in license_text and "Last Updated: October 1, 2025" in license_text,
            "Unexpected versioned runtime license content")
    dlls = extract(attached[minimum["cabinet"]["source_path"]], [item["cabinet_member"] for item in manifest["binaries"]],
                   output / "dlls", expand, env)
    for item in manifest["binaries"]:
        path = dlls[item["cabinet_member"]]
        consumed[path] = verify(path, item)
    msi = attached[minimum["msi"]["source_path"]]
    mapping = msi_mapping(read_msi_tables(msi, system), manifest)
    final_signatures = signatures({"minimum-runtime.msi": msi, "minimum-runtime.cab": attached[minimum["cabinet"]["source_path"]],
                                  **{r["name"]: dlls[r["cabinet_member"]] for r in manifest["binaries"]}}, system, env)
    verify_unchanged({**inputs, **consumed})
    binaries = [{**item, "origin": "pinned-microsoft-redist-minimum-x64-cabinet"} for item in manifest["binaries"]]
    record = {
        "schema": "dupez.msvc-redist-provenance.v1", "status": "exact-upstream-package-bytes-verified",
        "reviewed_on": "2026-11-09", "manifest": inputs[manifest_path], "package": manifest["package"],
        "containers": containers, "minimum_runtime": minimum, "msi_database": mapping,
        "burn_manifest": identity(ux["0"]), "bootstrapper_application_data": identity(ux["u17"]),
        "binaries": binaries, "previous_system_observation": inputs[observation_path],
        "license_reference": manifest["license_reference"], "license_document": inputs[license_doc],
        "signature_observations": before_signatures + final_signatures,
        "extraction_tool": consumed[expand], "verifier": inputs[Path(__file__)],
        "consumed_artifacts": [{"path": path.relative_to(output).as_posix(), **pin} for path, pin in consumed.items() if path != expand],
        "installer_executed": False, "global_installation_performed": False, "elevation_requested": False,
        "release_approved": False, "distribution_approved": False,
        "limitations": [
            "Exact upstream package/three-DLL mapping closes the recorded host-origin ambiguity, not all native SBOM or source/relink requirements.",
            "This verifier covers only the three named x64 runtime DLLs; it does not authorize other System32 dependencies.",
            "The package-linked runtime use license is not a redistribution grant; owner Visual Studio entitlement and applicable distribution terms remain unresolved.",
            "Matching signatures and bytes do not establish freedom from vulnerabilities or a native compiler/source rebuild.",
            "Existing prior runtime/build observations are not rerun or replaced by this offline package verification.",
        ],
    }
    verify_unchanged({**inputs, **consumed})
    (output / "receipt.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--license-document", required=True, type=Path)
    parser.add_argument("--system-observation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.package, args.license_document, args.system_observation, args.output)
    print(json.dumps({"status": result["status"], "binaries": len(result["binaries"]), "distribution_approved": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
