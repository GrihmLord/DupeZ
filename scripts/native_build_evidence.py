"""Offline comparison of a frozen native payload with local build provenance.

This never launches the executable. It records byte/origin observations, not
native ABI, vulnerability, licensing, or release approval.
"""

from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zlib


SCHEMA = "dupez.native-build-observation.v1"
_FORBIDDEN = {"qopensslbackend.dll", "qcertonlybackend.dll"}
_TLS_DLLS = {"libssl-3.dll", "libcrypto-3.dll"}
_SCHANNEL = "pyqt6/qt6/plugins/tls/qschannelbackend.dll"


def _regular(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        metadata = part.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("Evidence inputs must not use links or reparse points")
    if not path.is_file():
        raise ValueError("Evidence input is not a regular file")
    return path


def _fingerprint(path: Path) -> dict:
    path = _regular(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("Evidence input changed while hashing")
    return {"name": path.name, "size": after.st_size, "sha256": digest}


def _json(path: Path) -> dict:
    _regular(path)
    with path.open("rb") as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Evidence JSON exceeds the input limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Evidence JSON contains duplicate keys")
            result[key] = value
        return result

    result = json.loads(data, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("Evidence JSON must contain an object")
    return result


def _destination(value: object) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise ValueError("Invalid native archive destination")
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise ValueError("Unsafe native archive destination")
    return normalized.casefold()


def _system_directory() -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Windows native evidence requires the Windows system directory")
    buffer = ctypes.create_unicode_buffer(32768)
    function = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemDirectoryW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    function.restype = ctypes.c_uint
    length = function(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise RuntimeError("Cannot establish Windows system directory")
    return Path(buffer.value)


def _archive_prefix(artifact: Path, archive, metadata: tuple) -> bytes:
    """Read only two output bytes; Windows DATA entries can also have type b."""
    offset, length, _size, compressed, _kind = metadata
    start = getattr(archive, "_start_offset", None)
    if any(type(value) is not int or value < 0 for value in (start, offset, length)) or compressed not in (0, 1):
        raise ValueError("Invalid frozen archive offset metadata")
    if start + offset + length > artifact.stat().st_size:
        raise ValueError("Frozen archive entry extends beyond the artifact")
    with artifact.open("rb") as stream:
        stream.seek(start + offset)
        if not compressed:
            return stream.read(min(length, 2))
        decoder = zlib.decompressobj()
        prefix = b""
        while length and len(prefix) < 2:
            chunk = stream.read(min(length, 4096))
            if not chunk:
                raise ValueError("Truncated frozen archive entry")
            length -= len(chunk)
            prefix += decoder.decompress(chunk, 2 - len(prefix))
        return prefix


def inspect_native_build(
    *, artifact: Path, manifest: Path, source_root: Path, build_venv: Path,
    python_base: Path, system_directory: Path | None = None, archive_reader_cls=None,
) -> dict:
    """Compare every final native entry to its recorded and approved source."""
    initial_artifact = _fingerprint(artifact)
    initial_manifest = _fingerprint(manifest)
    payload = _json(manifest)
    if payload.get("schema") != "dupez.native-binary-origins.v1" or payload.get("qt_tls_policy") != "schannel-only":
        raise ValueError("Unsupported native collection manifest")
    rows = payload.get("binaries")
    if not isinstance(rows, list) or not rows or len(rows) > 10000:
        raise ValueError("Invalid native collection inventory")

    source_root = source_root.resolve(strict=True)
    provenance_path = source_root / "packaging/binary-provenance.json"
    release_path = source_root / "packaging/release-data.json"
    provenance_fingerprint = _fingerprint(provenance_path)
    release_fingerprint = _fingerprint(release_path)
    provenance = _json(provenance_path)
    release = _json(release_path)
    if provenance.get("schema") != "dupez.bundled-binaries.v1" or release.get("schema") != "dupez.release-data.v1":
        raise ValueError("Unsupported managed-native source provenance")
    declared_managed = {_destination(name) for name in release["binaries"]}
    managed = {}
    for row in provenance["artifacts"]:
        name = _destination(row["path"])
        if name in managed:
            raise ValueError("Duplicate managed-native provenance")
        managed[name] = row
    if declared_managed != set(managed):
        raise ValueError("Managed-native inventory differs from byte provenance")

    build_venv = build_venv.resolve(strict=True)
    python_base = python_base.resolve(strict=True)
    # A broad arbitrary directory must not masquerade as the build venv.
    config_path = _regular(build_venv / "pyvenv.cfg")
    config = dict(line.split("=", 1) for line in config_path.read_text(encoding="utf-8").splitlines() if "=" in line)
    configured_home = next((value.strip() for key, value in config.items() if key.strip() == "home"), "")
    if not configured_home or Path(configured_home).resolve(strict=True) != python_base:
        raise ValueError("Build venv does not reference the supplied base Python")
    _regular(build_venv / "Scripts/python.exe")
    _regular(python_base / "python.exe")
    roots = {
        "locked-build-venv": build_venv,
        "verified-base-python": python_base,
        "windows-system32": (system_directory or _system_directory()).resolve(strict=True),
    }

    if archive_reader_cls is None:
        from PyInstaller.archive.readers import CArchiveReader

        archive_reader_cls = CArchiveReader
    archive = archive_reader_cls(str(artifact))
    entries = {}
    for raw_name, metadata in archive.toc.items():
        name = _destination(raw_name)
        if name in entries:
            raise ValueError("Frozen archive contains case-colliding destinations")
        if not isinstance(metadata, tuple) or len(metadata) < 5:
            raise ValueError("Unrecognized frozen archive metadata")
        entries[name] = (raw_name, metadata)
    reported = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"destination", "source", "kind", "origin", "sha256"}:
            raise ValueError("Malformed native provenance row")
        name = _destination(row["destination"])
        if name in reported:
            raise ValueError("Duplicate native provenance destination")
        if row["kind"] not in {"BINARY", "EXTENSION"} or not re.fullmatch(r"[a-f0-9]{64}", str(row["sha256"])):
            raise ValueError("Invalid native provenance kind or digest")
        reported[name] = row
    # PyInstaller maps ordinary Windows DATA entries to type b when os.access
    # reports X_OK. A type-b test alone would incorrectly include fonts/QML/etc.
    # Include every recorded binary, known Windows native suffix, and any
    # additional extractable MZ payload (including a renamed native binary).
    native_entries = {}
    for name, entry in entries.items():
        metadata = entry[1]
        if name in reported or PurePosixPath(name).suffix in {".dll", ".pyd", ".exe", ".sys", ".ocx", ".cpl", ".drv"}:
            native_entries[name] = entry
        elif metadata[-1] in {"b", "x"} and _archive_prefix(artifact, archive, metadata) == b"MZ":
            native_entries[name] = entry
    if set(reported) != set(native_entries):
        raise ValueError("Final native archive inventory differs from provenance")
    if not declared_managed.issubset(reported) or not {_SCHANNEL, *_TLS_DLLS}.issubset(reported):
        raise ValueError("Frozen payload is missing a required managed or TLS dependency")

    origins = Counter()
    manifest_records = []
    for name, row in reported.items():
        basename = PurePosixPath(name).name
        if basename in _FORBIDDEN:
            raise ValueError("Forbidden Qt TLS plugin in final native payload")
        if "/plugins/tls/" in name and name != _SCHANNEL:
            raise ValueError("Unreviewed Qt TLS plugin in final native payload")
        raw_name, metadata = native_entries[name]
        if metadata[-1] != "b" or type(metadata[2]) is not int or metadata[2] < 0 or metadata[2] > 1024 * 1024 * 1024:
            raise ValueError("Native archive entry has an invalid type or size")
        extracted = archive.extract(raw_name)
        if not isinstance(extracted, bytes) or len(extracted) != metadata[2]:
            raise ValueError("Native archive extraction size mismatch")
        digest = hashlib.sha256(extracted).hexdigest()
        if digest != row["sha256"]:
            raise ValueError("Final native archive bytes differ from provenance")
        if name in managed:
            expected = managed[name]
            original = source_root / expected["path"]
            original_fingerprint = _fingerprint(original)
            if digest != expected["sha256"] or len(extracted) != expected["size"] or original_fingerprint["sha256"] != digest:
                raise ValueError("Managed native bytes differ from pinned source provenance")
            origin = "managed-native"
        else:
            if not isinstance(row["source"], str) or not Path(row["source"]).is_absolute():
                raise ValueError("Native source must be an absolute local path")
            source = _regular(Path(row["source"]))
            origin = next((label for label, root in roots.items() if source.is_relative_to(root)), None)
            if origin is None:
                raise ValueError("Ambient native source is outside approved build roots")
            if _fingerprint(source)["sha256"] != digest:
                raise ValueError("Current native source differs from archived build bytes")
            if basename.startswith(("libssl", "libcrypto")) and basename.endswith(".dll"):
                if name not in _TLS_DLLS or source != python_base / "DLLs" / name:
                    raise ValueError("OpenSSL was not collected from canonical base Python")
            if name == _SCHANNEL and source != build_venv / "Lib/site-packages/PyQt6/Qt6/plugins/tls/qschannelbackend.dll":
                raise ValueError("Qt Schannel plugin is outside the build venv wheel")
        if row["origin"] != origin:
            raise ValueError("Recorded native origin does not match inspected origin")
        origins[origin] += 1
        manifest_records.append({"destination": name, "sha256": digest, "size": len(extracted), "origin": origin})

    if _fingerprint(artifact) != initial_artifact or _fingerprint(manifest) != initial_manifest:
        raise ValueError("Artifact or provenance changed during inspection")
    if _fingerprint(provenance_path) != provenance_fingerprint or _fingerprint(release_path) != release_fingerprint:
        raise ValueError("Managed-native source provenance changed during inspection")
    inventory_bytes = json.dumps(sorted(manifest_records, key=lambda row: row["destination"]), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": SCHEMA,
        "disposition": "offline-local-byte-observation-not-release-approval",
        "artifact": initial_artifact,
        "collection_manifest": {"size": initial_manifest["size"], "sha256": initial_manifest["sha256"]},
        "managed_source_provenance_sha256": provenance_fingerprint["sha256"],
        "release_data_sha256": release_fingerprint["sha256"],
        "qt_tls_policy": "schannel-only",
        "native_entry_count": len(reported),
        "origin_counts": dict(sorted(origins.items())),
        "native_inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "limitations": [
            "No executable, renderer, socket, or packet engine was launched.",
            "Caller-supplied local build/source inputs are not independently authenticated.",
            "The PyInstaller reader is intended for these local builds, not bounded hostile-archive parsing.",
            "Managed snapshot bytes are checked against source pins; deleted snapshot origins cannot be revisited.",
            "No arbitrary DLL ABI, vulnerability freedom, complete source, license, or release approval is asserted.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifact", "manifest", "source-root", "build-venv", "python-base", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = inspect_native_build(artifact=args.artifact, manifest=args.manifest, source_root=args.source_root,
                                       build_venv=args.build_venv, python_base=args.python_base)
        output = Path(os.path.abspath(args.output))
        for parent in (output.parent, *output.parent.parents):
            metadata = parent.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise ValueError("Evidence output parents must be ordinary directories")
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, zlib.error):
        print("Native build inspection failed; no approval was recorded.")
        return 1
    print("Native archive bytes and approved local origins match; no release approval is asserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
