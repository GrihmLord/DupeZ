"""Explicit release payloads and source-preserving native staging.

``packaging/binary-provenance.json`` pins the tracked upstream bytes.  A
standard release never signs those tracked files in place: this module first
verifies every source byte, copies the exact managed native inventory into the
ignored ``build/release-native`` tree, and then verifies the staged tree after
the build driver signs only its ``clumsy.exe`` copy. PyInstaller consumes a
verified snapshot, and the Inno Setup compiler receives a separate private,
read-only snapshot only for the duration of compilation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "release-data.json"
SOURCE_PROVENANCE_PATH = HERE / "binary-provenance.json"
RELEASE_TOOL_MANIFEST_PATH = HERE / "release-tools.json"
MANIFEST_SCHEMA = "dupez.release-data.v1"
SOURCE_PROVENANCE_SCHEMA = "dupez.bundled-binaries.v1"
DIST_PROVENANCE_SCHEMA = "dupez.distribution-binaries.v1"
NATIVE_STAGE_RELATIVE = Path("build") / "release-native"
NATIVE_STAGE_MANIFEST = ".dupez-native-provenance.json"
STANDARD_MODE = "standard-authenticode"
UNSIGNED_MODE = "explicit-unsigned"
RELEASE_MODES = frozenset({STANDARD_MODE, UNSIGNED_MODE})
CLUMSY_PATH = "app/firewall/clumsy.exe"
EXPECTED_SIGNER_ENV = "DUPEZ_EXPECTED_SIGNER_CERT_SHA256"
INSTALLER_NATIVE_SNAPSHOT_ENV = "DUPEZ_INSTALLER_NATIVE_SNAPSHOT"
AUTHENTICODE_TRANSFORM = "pe-authenticode-certificate-table-v1"
DATA_ROOTS = (
    PurePosixPath("app/assets"),
    PurePosixPath("app/config"),
    PurePosixPath("app/resources"),
    PurePosixPath("app/themes"),
)
BINARY_ROOT = PurePosixPath("app/firewall")
BINARY_SUFFIXES = {".dll", ".exe", ".sys"}
_REPARSE_POINT_ATTRIBUTE = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x400,
)
_NATIVE_SNAPSHOTS: list[tempfile.TemporaryDirectory] = []


def _manifest_paths(
    key: str,
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[str, ...]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unsupported release-data manifest schema")
    files = payload.get(key)
    if not isinstance(files, list) or not files:
        raise ValueError(f"release-data manifest has no {key}")

    normalised: list[str] = []
    for value in files:
        if not isinstance(value, str):
            raise TypeError(f"release-data {key} paths must be strings")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or path.as_posix() != value
        ):
            raise ValueError(f"unsafe release-data {key} path: {value!r}")
        if key == "files":
            lowered_parts = {part.casefold() for part in path.parts}
            lowered_name = path.name.casefold()
            if not any(root in path.parents for root in DATA_ROOTS):
                raise ValueError(
                    f"release-data path outside managed roots: {value!r}"
                )
            if (
                "__pycache__" in lowered_parts
                or lowered_name.endswith(
                    (".py", ".pyc", ".pyo", ".hmac")
                )
                or lowered_name.startswith("patch_monitor_state")
            ):
                raise ValueError(
                    f"forbidden runtime/source release data: {value!r}"
                )
        elif key == "binaries" and (
            path.parent != BINARY_ROOT
            or path.suffix.casefold() not in BINARY_SUFFIXES
        ):
            raise ValueError(
                "release binary must be a direct DLL/EXE/SYS child of "
                f"app/firewall: {value!r}"
            )
        normalised.append(path.as_posix())
    if len(normalised) != len(
        {value.casefold() for value in normalised}
    ):
        raise ValueError(
            f"release-data manifest contains duplicate {key} paths"
        )
    return tuple(normalised)


def release_data_files(
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[str, ...]:
    return _manifest_paths("files", manifest_path)


def release_binary_files(
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[str, ...]:
    return _manifest_paths("binaries", manifest_path)


def pyinstaller_datas(root: str) -> list[tuple[str, str]]:
    root_path = Path(root).resolve()
    datas: list[tuple[str, str]] = []
    for relative in release_data_files():
        source = (root_path / PurePosixPath(relative)).resolve()
        if root_path not in source.parents or not source.is_file():
            raise FileNotFoundError(
                f"required release data file missing: {relative}"
            )
        destination = str(PurePosixPath(relative).parent).replace(
            "/",
            os.sep,
        )
        datas.append((str(source), destination))
    return datas


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _absolute_without_resolving(path: str | Path) -> Path:
    """Return an absolute lexical path without following reparse points."""
    return Path(os.path.abspath(os.fspath(path)))


def _exists_without_following(path: Path) -> bool:
    return os.path.lexists(path)


def _is_reparse_point(path: Path) -> bool:
    """Recognise symlinks and Windows junction/other reparse points."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as exc:
        raise ValueError(f"cannot inspect release path safely: {path}: {exc}") from exc
    return bool(attributes & _REPARSE_POINT_ATTRIBUTE)


def _assert_no_reparse_components(root: Path, target: Path) -> None:
    """Reject an existing reparse component between ``root`` and ``target``."""
    lexical_root = _absolute_without_resolving(root)
    lexical_target = _absolute_without_resolving(target)
    try:
        relative = lexical_target.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError(f"release path escapes repository root: {target}") from exc

    current = lexical_root
    for part in relative.parts:
        current /= part
        if _exists_without_following(current) and _is_reparse_point(current):
            raise ValueError(
                "reparse point is forbidden in native release path: "
                f"{current}"
            )


def _safe_source(root: Path, relative: str) -> Path:
    root = _absolute_without_resolving(root)
    if _exists_without_following(root) and _is_reparse_point(root):
        raise ValueError(f"reparse point is forbidden as a release root: {root}")
    source = root.joinpath(*PurePosixPath(relative).parts)
    _assert_no_reparse_components(root, source)
    if not source.is_file():
        raise FileNotFoundError(f"required release binary missing: {relative}")
    return source


def _source_provenance_entries(
    root: Path,
    *,
    manifest_path: Path = MANIFEST_PATH,
    provenance_path: Path = SOURCE_PROVENANCE_PATH,
) -> dict[str, dict]:
    """Verify tracked native bytes and return their pinned source records."""
    root = root.resolve()
    expected = set(release_binary_files(manifest_path))
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    if payload.get("schema") != SOURCE_PROVENANCE_SCHEMA:
        raise ValueError("unsupported source binary provenance schema")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("source binary provenance contains no artifacts")

    entries: dict[str, dict] = {}
    for raw in artifacts:
        if not isinstance(raw, dict):
            raise ValueError("source binary provenance artifact must be an object")
        relative = raw.get("path")
        if not isinstance(relative, str) or relative not in expected:
            raise ValueError(f"unexpected source binary provenance path: {relative!r}")
        canonical = relative.casefold()
        if canonical in {path.casefold() for path in entries}:
            raise ValueError(f"duplicate source binary provenance path: {relative}")
        size = raw.get("size")
        digest = str(raw.get("sha256") or "").casefold()
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError(f"invalid source binary size: {relative}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"invalid source binary SHA-256: {relative}")
        source = _safe_source(root, relative)
        if source.stat().st_size != size:
            raise ValueError(f"tracked source binary size mismatch: {relative}")
        if _sha256(source) != digest:
            raise ValueError(f"tracked source binary SHA-256 mismatch: {relative}")
        if not str(raw.get("source") or "").startswith("https://"):
            raise ValueError(f"source binary provenance URL is invalid: {relative}")
        if not str(raw.get("version") or "").strip():
            raise ValueError(f"source binary provenance version is missing: {relative}")
        record = dict(raw)
        record["sha256"] = digest
        entries[relative] = record

    if set(entries) != expected:
        missing = sorted(expected - set(entries))
        extra = sorted(set(entries) - expected)
        raise ValueError(
            "source binary provenance inventory mismatch; "
            f"missing={missing!r}, extra={extra!r}"
        )
    return entries


def native_stage_root(root: str | Path) -> Path:
    return Path(root).resolve() / NATIVE_STAGE_RELATIVE


def _validated_stage_root(
    root: Path,
    stage_root: str | Path | None,
) -> Path:
    expected = native_stage_root(root)
    stage = (
        _absolute_without_resolving(stage_root)
        if stage_root is not None
        else expected
    )
    if stage != expected:
        raise ValueError(
            "native release stage must be the fixed ignored build/release-native tree"
        )
    _assert_no_reparse_components(root, stage)
    return stage


def _stage_inventory(stage: Path) -> set[str]:
    inventory: set[str] = set()
    if not _exists_without_following(stage) or not stage.is_dir():
        raise FileNotFoundError(f"native release stage is missing: {stage}")
    if _is_reparse_point(stage):
        raise ValueError(
            f"reparse point is forbidden in native release stage: {stage}"
        )

    pending = [stage]
    while pending:
        directory = pending.pop()
        try:
            children = list(os.scandir(directory))
        except OSError as exc:
            raise ValueError(
                f"cannot inspect native release stage safely: {directory}: {exc}"
            ) from exc
        for child in children:
            path = Path(child.path)
            if _is_reparse_point(path):
                raise ValueError(
                    "reparse point is forbidden in native release stage: "
                    f"{path}"
                )
            if child.is_dir(follow_symlinks=False):
                pending.append(path)
                continue
            if not child.is_file(follow_symlinks=False):
                raise ValueError(
                    f"special file is forbidden in native release stage: {path}"
                )
            relative = path.relative_to(stage).as_posix()
            if relative != NATIVE_STAGE_MANIFEST:
                inventory.add(relative)
    return inventory


def prepare_native_stage(
    root: str | Path,
    *,
    stage_root: str | Path | None = None,
    manifest_path: Path = MANIFEST_PATH,
    provenance_path: Path = SOURCE_PROVENANCE_PATH,
) -> Path:
    """Create a clean exact-byte stage after verifying tracked provenance."""
    root_path = Path(root).resolve()
    stage = _validated_stage_root(root_path, stage_root)
    entries = _source_provenance_entries(
        root_path,
        manifest_path=manifest_path,
        provenance_path=provenance_path,
    )
    if _exists_without_following(stage):
        # ``shutil.rmtree`` must never see an uninspected junction/reparse
        # tree.  In particular, a hostile ``build`` junction could otherwise
        # redirect cleanup outside the repository before any source hashes are
        # considered.
        _stage_inventory(stage)
        _assert_no_reparse_components(root_path, stage)
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=False)
    _assert_no_reparse_components(root_path, stage)

    for relative, entry in entries.items():
        source = _safe_source(root_path, relative)
        destination = stage.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_reparse_components(stage, destination.parent)
        with source.open("rb") as source_handle, destination.open("xb") as target:
            shutil.copyfileobj(source_handle, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if (
            destination.stat().st_size != entry["size"]
            or _sha256(destination) != entry["sha256"]
        ):
            raise ValueError(f"native staging copy mismatch: {relative}")

    if _stage_inventory(stage) != set(entries):
        raise ValueError("native release stage inventory is not exact")
    return stage


def _windows_powershell() -> Path:
    if os.name != "nt":
        raise RuntimeError("Authenticode measurement requires Windows")
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    get_system_directory.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = int(get_system_directory(buffer, len(buffer)))
    if length == 0 or length >= len(buffer):
        raise RuntimeError("cannot resolve the trusted Windows system directory")
    powershell = (
        Path(buffer.value)
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        raise RuntimeError("inbox Windows PowerShell is unavailable")
    return powershell


def inspect_authenticode(path: Path) -> tuple[str, str | None]:
    """Measure Windows trust status and signer DER SHA-256 for one file."""
    target = path.resolve()
    if not target.is_file():
        raise FileNotFoundError(f"Authenticode target is missing: {target}")
    env = os.environ.copy()
    env["DUPEZ_AUTHENTICODE_TARGET"] = str(target)
    script = r"""
$ErrorActionPreference = 'Stop'
$securityModule = Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1'
Import-Module -Name $securityModule -ErrorAction Stop
$signature = Get-AuthenticodeSignature -LiteralPath $env:DUPEZ_AUTHENTICODE_TARGET
$fingerprint = $null
if ($null -ne $signature.SignerCertificate) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($signature.SignerCertificate.RawData)
        $fingerprint = ([System.BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha256.Dispose() }
}
[pscustomobject]@{
    status = $signature.Status.ToString()
    signer_certificate_sha256 = $fingerprint
} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [
            str(_windows_powershell()),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        shell=False,
        env=env,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Windows signature query failed"
        raise RuntimeError(f"Authenticode measurement failed: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Authenticode measurement returned invalid JSON") from exc
    status = str(payload.get("status") or "")
    fingerprint_value = payload.get("signer_certificate_sha256")
    fingerprint = (
        str(fingerprint_value).casefold()
        if fingerprint_value is not None
        else None
    )
    if not status:
        raise RuntimeError("Authenticode measurement returned no status")
    if fingerprint is not None and not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise RuntimeError("Authenticode measurement returned an invalid signer")
    return status, fingerprint


def _release_tool_pin(
    name: str,
    manifest_path: Path = RELEASE_TOOL_MANIFEST_PATH,
) -> dict[str, str]:
    """Load one strictly structured tool pin from the reviewed manifest."""

    manifest = _absolute_without_resolving(manifest_path)
    if (
        not _exists_without_following(manifest)
        or _is_reparse_point(manifest)
        or not manifest.is_file()
    ):
        raise ValueError("release tool pin manifest is unavailable or unsafe")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "iscc",
        "signtool",
    }:
        raise ValueError("release tool pin manifest structure is invalid")
    if payload.get("schema") != "dupez.release-tools.v1":
        raise ValueError("release tool pin manifest schema is invalid")
    expected_fields = {
        "iscc": {
            "version",
            "default_base",
            "relative_path",
            "sha256",
            "signer_certificate_sha256",
            "signer_subject",
            "signer_thumbprint",
        },
        "signtool": {
            "version",
            "sdk_version",
            "default_base",
            "relative_path",
            "sha256",
            "signer_certificate_sha256",
            "signer_subject",
            "signer_thumbprint",
        },
    }
    if name not in expected_fields:
        raise ValueError("unknown pinned release tool")
    pin = payload.get(name)
    if not isinstance(pin, dict) or set(pin) != expected_fields[name]:
        raise ValueError(f"{name} release tool pin structure is invalid")
    if not all(isinstance(value, str) and value for value in pin.values()):
        raise ValueError(f"{name} release tool pin values are invalid")
    if pin["default_base"] != "ProgramFilesX86":
        raise ValueError(f"{name} release tool base pin is invalid")
    for field, length in (
        ("sha256", 64),
        ("signer_certificate_sha256", 64),
        ("signer_thumbprint", 40),
    ):
        if not re.fullmatch(rf"[0-9a-f]{{{length}}}", pin[field]):
            raise ValueError(f"{name} release tool {field} pin is invalid")
    relative = PureWindowsPath(pin["relative_path"])
    if (
        relative.is_absolute()
        or any(part in {".", ".."} for part in relative.parts)
        or "*" in pin["relative_path"]
        or "?" in pin["relative_path"]
    ):
        raise ValueError(f"{name} release tool path pin is invalid")
    if name == "iscc":
        if (
            not re.fullmatch(r"\d+\.\d+\.\d+", pin["version"])
            or pin["relative_path"] != r"Inno Setup 6\ISCC.exe"
        ):
            raise ValueError("iscc release tool version/path binding is invalid")
    else:
        sdk_version = pin["sdk_version"]
        if (
            not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", pin["version"])
            or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", sdk_version)
            or pin["relative_path"]
            != rf"Windows Kits\10\bin\{sdk_version}\x64\signtool.exe"
        ):
            raise ValueError(
                "signtool release tool version/path binding is invalid"
            )
    return pin


def verify_release_tool(
    name: str,
    path: str | Path,
    *,
    manifest_path: Path = RELEASE_TOOL_MANIFEST_PATH,
    program_files_x86: str | Path | None = None,
    signature_inspector: Callable[
        [Path], tuple[str, str | None]
    ] = inspect_authenticode,
) -> Path:
    """Revalidate exact tool bytes and signer immediately before execution."""

    pin = _release_tool_pin(name, manifest_path)
    requested = Path(path)
    if not requested.is_absolute():
        raise ValueError("release tool path must be absolute")
    tool = _absolute_without_resolving(requested)
    base_value = (
        program_files_x86
        if program_files_x86 is not None
        else os.environ.get("ProgramFiles(x86)")
    )
    if not base_value:
        raise ValueError("Program Files (x86) release tool base is unavailable")
    base = _absolute_without_resolving(base_value)
    relative = PureWindowsPath(pin["relative_path"])
    expected = _absolute_without_resolving(base.joinpath(*relative.parts))
    if os.path.normcase(str(tool)) != os.path.normcase(str(expected)):
        raise ValueError("release tool path does not match the repository pin")
    if not _exists_without_following(tool) or _is_reparse_point(tool):
        raise ValueError("pinned release tool is unavailable or unsafe")
    _assert_no_reparse_components(base, tool)
    if not tool.is_file():
        raise ValueError("pinned release tool is not a regular file")

    expected_filename = "signtool.exe" if name == "signtool" else "ISCC.exe"
    if tool.name != expected_filename:
        raise ValueError("pinned release tool filename is invalid")
    if _sha256(tool) != pin["sha256"]:
        raise ValueError("release tool hash does not match the repository pin")
    status, signer = signature_inspector(tool)
    if status != "Valid" or signer != pin["signer_certificate_sha256"]:
        raise ValueError(
            "release tool Authenticode signer does not match the repository pin"
        )
    return tool


def _pe_authenticode_layout(
    payload: bytes,
    *,
    label: str,
) -> tuple[int, int, int, int]:
    """Return checksum/security offsets and certificate table bounds."""
    if len(payload) < 64 or payload[:2] != b"MZ":
        raise ValueError(f"{label} is not a valid PE image")
    pe_offset = struct.unpack_from("<I", payload, 0x3C)[0]
    if pe_offset > len(payload) - 24 or payload[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError(f"{label} has an invalid PE header")
    optional_size = struct.unpack_from("<H", payload, pe_offset + 20)[0]
    optional_offset = pe_offset + 24
    optional_end = optional_offset + optional_size
    if optional_end > len(payload) or optional_size < 120:
        raise ValueError(f"{label} has a truncated PE optional header")
    magic = struct.unpack_from("<H", payload, optional_offset)[0]
    if magic == 0x10B:
        directory_offset = optional_offset + 96
        directory_count_offset = optional_offset + 92
    elif magic == 0x20B:
        directory_offset = optional_offset + 112
        directory_count_offset = optional_offset + 108
    else:
        raise ValueError(f"{label} has an unsupported PE optional-header format")
    if struct.unpack_from("<I", payload, directory_count_offset)[0] <= 4:
        raise ValueError(f"{label} has no Authenticode security directory")
    checksum_offset = optional_offset + 64
    security_offset = directory_offset + (4 * 8)
    if checksum_offset + 4 > optional_end or security_offset + 8 > optional_end:
        raise ValueError(f"{label} has a truncated Authenticode header")
    certificate_offset, certificate_size = struct.unpack_from(
        "<II",
        payload,
        security_offset,
    )
    return (
        checksum_offset,
        security_offset,
        certificate_offset,
        certificate_size,
    )


def _validate_certificate_table(
    payload: bytes,
    offset: int,
    size: int,
) -> None:
    if offset <= 0 or size <= 0 or offset % 8:
        raise ValueError("signed staged clumsy.exe has an invalid certificate table")
    end = offset + size
    if end != len(payload):
        raise ValueError(
            "signed staged clumsy.exe certificate table must be the final PE data"
        )
    cursor = offset
    while cursor < end:
        if end - cursor < 8:
            raise ValueError("signed staged clumsy.exe has a truncated certificate")
        length, revision, certificate_type = struct.unpack_from(
            "<IHH",
            payload,
            cursor,
        )
        if (
            length < 8
            or cursor + length > end
            or revision not in {0x100, 0x200}
            or certificate_type != 0x0002
        ):
            raise ValueError("signed staged clumsy.exe has an invalid certificate")
        aligned_length = (length + 7) & ~7
        aligned_end = cursor + aligned_length
        if aligned_end > end:
            raise ValueError("signed staged clumsy.exe certificate alignment is invalid")
        if any(payload[cursor + length:aligned_end]):
            raise ValueError("signed staged clumsy.exe has nonzero certificate padding")
        cursor = aligned_end


def verify_authenticode_source_equivalence(
    source_payload: bytes,
    signed_payload: bytes,
) -> None:
    """Prove a signed PE differs only by the Authenticode signing structure.

    SignTool is permitted to update the PE checksum and security-directory
    entry and to append an aligned WIN_CERTIFICATE table.  Every other byte is
    required to match the provenance-pinned unsigned source.
    """
    source_layout = _pe_authenticode_layout(
        source_payload,
        label="source clumsy.exe",
    )
    signed_layout = _pe_authenticode_layout(
        signed_payload,
        label="signed staged clumsy.exe",
    )
    source_checksum, source_security, source_cert_offset, source_cert_size = (
        source_layout
    )
    signed_checksum, signed_security, certificate_offset, certificate_size = (
        signed_layout
    )
    if source_cert_offset or source_cert_size:
        raise ValueError("provenance-pinned source clumsy.exe is already signed")
    if (source_checksum, source_security) != (signed_checksum, signed_security):
        raise ValueError("signed staged clumsy.exe changed the PE header layout")
    if certificate_offset < len(source_payload):
        raise ValueError(
            "signed staged clumsy.exe certificate overlaps source image bytes"
        )
    alignment = signed_payload[len(source_payload):certificate_offset]
    if len(alignment) > 7 or any(alignment):
        raise ValueError(
            "signed staged clumsy.exe contains data outside the Authenticode table"
        )
    _validate_certificate_table(
        signed_payload,
        certificate_offset,
        certificate_size,
    )

    normalised_source = bytearray(source_payload)
    normalised_signed = bytearray(signed_payload[:len(source_payload)])
    for payload, checksum_offset, security_offset in (
        (normalised_source, source_checksum, source_security),
        (normalised_signed, signed_checksum, signed_security),
    ):
        payload[checksum_offset:checksum_offset + 4] = b"\0" * 4
        payload[security_offset:security_offset + 8] = b"\0" * 8
    if normalised_signed != normalised_source:
        raise ValueError(
            "signed staged clumsy.exe is not source-equivalent outside "
            "Authenticode"
        )


def _expected_signer_fingerprint(
    mode: str,
    supplied: str | None,
) -> str | None:
    if mode != STANDARD_MODE:
        return None
    value = supplied or os.environ.get(EXPECTED_SIGNER_ENV)
    if value is None or not str(value).strip():
        return None
    fingerprint = str(value).casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError(
            f"{EXPECTED_SIGNER_ENV}, when supplied, must be a signer "
            "certificate SHA-256"
        )
    return fingerprint


def _inspect_authenticode_bytes(
    payload: bytes,
    signature_inspector: Callable[[Path], tuple[str, str | None]],
) -> tuple[str, str | None]:
    """Inspect the exact bytes already measured, not a mutable stage path."""
    with tempfile.TemporaryDirectory(prefix="dupez-authenticode-measure-") as temp:
        target = Path(temp) / "clumsy.exe"
        target.write_bytes(payload)
        return signature_inspector(target)


def _bound_file_bytes(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    label: str,
) -> bytes:
    payload = path.read_bytes()
    if len(payload) != expected_size or _sha256_bytes(payload) != expected_sha256:
        raise ValueError(f"{label} changed while it was being consumed")
    return payload


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _distribution_artifacts(payload: object) -> dict[str, dict]:
    if not isinstance(payload, dict) or payload.get("schema") != DIST_PROVENANCE_SCHEMA:
        raise ValueError("unsupported distribution binary provenance schema")
    mode = payload.get("release_mode")
    if mode not in RELEASE_MODES:
        raise ValueError("distribution binary provenance has an invalid release mode")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("distribution binary provenance contains no artifacts")
    entries: dict[str, dict] = {}
    for raw in artifacts:
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise ValueError("distribution binary provenance artifact is invalid")
        relative = raw["path"]
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or path.as_posix() != relative
            or path.parent != BINARY_ROOT
            or path.suffix.casefold() not in BINARY_SUFFIXES
        ):
            raise ValueError(
                f"unsafe distribution binary provenance path: {relative!r}"
            )
        if relative.casefold() in {path.casefold() for path in entries}:
            raise ValueError(f"duplicate distribution binary path: {relative}")
        entries[relative] = raw
    return entries


def _build_distribution_payload(
    root: Path,
    stage: Path,
    mode: str,
    source_entries: dict[str, dict],
    signature_inspector: Callable[[Path], tuple[str, str | None]],
    expected_signer_certificate_sha256: str | None = None,
) -> dict:
    if mode not in RELEASE_MODES:
        raise ValueError(f"unsupported native release mode: {mode}")
    if _stage_inventory(stage) != set(source_entries):
        raise ValueError("native release stage inventory is not exact")

    expected_signer = _expected_signer_fingerprint(
        mode,
        expected_signer_certificate_sha256,
    )
    artifacts: list[dict] = []
    for relative in sorted(source_entries, key=str.casefold):
        source_entry = source_entries[relative]
        source = _safe_source(root, relative)
        source_size = source_entry["size"]
        source_sha256 = source_entry["sha256"]
        source_payload = _bound_file_bytes(
            source,
            expected_size=source_size,
            expected_sha256=source_sha256,
            label=f"provenance-pinned source binary {relative}",
        )
        staged = _safe_source(stage, relative)
        staged_payload = staged.read_bytes()
        staged_size = len(staged_payload)
        staged_sha256 = _sha256_bytes(staged_payload)
        is_clumsy = relative.casefold() == CLUMSY_PATH
        exact_source = staged_payload == source_payload
        if not is_clumsy and not exact_source:
            raise ValueError(f"non-Clumsy staged binary changed: {relative}")
        if mode == UNSIGNED_MODE and not exact_source:
            raise ValueError(f"unsigned staged binary changed: {relative}")
        if mode == STANDARD_MODE and is_clumsy and exact_source:
            raise ValueError("standard staged clumsy.exe was not Authenticode-signed")
        if mode == STANDARD_MODE and is_clumsy:
            verify_authenticode_source_equivalence(
                source_payload,
                staged_payload,
            )

        artifact = {
            "path": relative,
            "size": staged_size,
            "sha256": staged_sha256,
            "source_size": source_size,
            "source_sha256": source_sha256,
            "version": source_entry["version"],
            "source": source_entry["source"],
            "transform": (
                "authenticode-signed-staged-copy"
                if is_clumsy and mode == STANDARD_MODE
                else "source-exact"
            ),
        }
        for key in (
            "source_commit",
            "release_asset",
            "release_asset_sha256",
        ):
            if key in source_entry:
                artifact[key] = source_entry[key]
        if is_clumsy and mode == STANDARD_MODE:
            artifact["source_equivalence"] = AUTHENTICODE_TRANSFORM
        if is_clumsy:
            status, fingerprint = _inspect_authenticode_bytes(
                staged_payload,
                signature_inspector,
            )
            fingerprint = (
                str(fingerprint).casefold()
                if fingerprint is not None
                else None
            )
            if mode == STANDARD_MODE:
                if status != "Valid" or fingerprint is None:
                    raise ValueError(
                        "standard staged clumsy.exe is not Authenticode-valid"
                    )
                if (
                    expected_signer is not None
                    and fingerprint != expected_signer
                ):
                    raise ValueError(
                        "standard staged clumsy.exe signer does not match the "
                        "pinned release signer"
                    )
                # A caller/host pin is optional at finalization because the
                # source-equivalence proof already prevents an unrelated
                # signed executable from becoming the measured subject.  The
                # measured valid signer becomes the immutable stage pin and is
                # later cross-checked by dist preflight against the
                # authenticated updater/outer release signer.
                expected_signer = fingerprint
            elif status != "NotSigned" or fingerprint is not None:
                raise ValueError(
                    "explicit unsigned staged clumsy.exe is not actually unsigned"
                )
            artifact["authenticode"] = {
                "status": status,
                "signer_certificate_sha256": fingerprint,
            }
        artifacts.append(artifact)

    if mode == STANDARD_MODE and expected_signer is None:
        raise ValueError("standard native stage contains no measured Clumsy signer")
    payload = {
        "schema": DIST_PROVENANCE_SCHEMA,
        "release_mode": mode,
        "source_provenance_schema": SOURCE_PROVENANCE_SCHEMA,
        "artifacts": artifacts,
    }
    if expected_signer is not None:
        payload["signer_certificate_sha256"] = expected_signer
    return payload


def finalize_native_stage(
    root: str | Path,
    mode: str,
    *,
    stage_root: str | Path | None = None,
    manifest_path: Path = MANIFEST_PATH,
    provenance_path: Path = SOURCE_PROVENANCE_PATH,
    signature_inspector: Callable[
        [Path], tuple[str, str | None]
    ] = inspect_authenticode,
    expected_signer_certificate_sha256: str | None = None,
) -> Path:
    """Measure a prepared stage and write its generated provenance."""
    root_path = Path(root).resolve()
    stage = _validated_stage_root(root_path, stage_root)
    source_entries = _source_provenance_entries(
        root_path,
        manifest_path=manifest_path,
        provenance_path=provenance_path,
    )
    payload = _build_distribution_payload(
        root_path,
        stage,
        mode,
        source_entries,
        signature_inspector,
        expected_signer_certificate_sha256,
    )
    output = stage / NATIVE_STAGE_MANIFEST
    _atomic_write(
        output,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return output


def verify_native_stage(
    root: str | Path,
    *,
    expected_mode: str | None = None,
    stage_root: str | Path | None = None,
    distribution_provenance_path: Path | None = None,
    manifest_path: Path = MANIFEST_PATH,
    provenance_path: Path = SOURCE_PROVENANCE_PATH,
    signature_inspector: Callable[[Path], tuple[str, str | None]] = inspect_authenticode,
    expected_signer_certificate_sha256: str | None = None,
) -> dict:
    """Recompute staged hashes and signature identity from actual bytes."""
    root_path = Path(root).resolve()
    stage = _validated_stage_root(root_path, stage_root)
    provenance = distribution_provenance_path or (
        stage / NATIVE_STAGE_MANIFEST
    )
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    entries = _distribution_artifacts(payload)
    mode = payload["release_mode"]
    if expected_mode is not None and mode != expected_mode:
        raise ValueError(
            f"native release mode mismatch: {mode!r} != {expected_mode!r}"
        )
    if payload.get("source_provenance_schema") != SOURCE_PROVENANCE_SCHEMA:
        raise ValueError("distribution provenance source schema is invalid")
    configured_signer = _expected_signer_fingerprint(
        mode,
        expected_signer_certificate_sha256,
    )
    provenance_signer = payload.get("signer_certificate_sha256")
    if mode == STANDARD_MODE:
        if not re.fullmatch(r"[0-9a-f]{64}", str(provenance_signer or "")):
            raise ValueError(
                "distribution provenance has no valid measured release signer"
            )
        if (
            configured_signer is not None
            and provenance_signer != configured_signer
        ):
            raise ValueError(
                "distribution provenance does not bind the pinned release signer"
            )
        expected_signer = str(provenance_signer)
    elif provenance_signer is not None:
        raise ValueError(
            "explicit unsigned distribution provenance unexpectedly binds a signer"
        )
    else:
        expected_signer = None
    source_entries = _source_provenance_entries(
        root_path,
        manifest_path=manifest_path,
        provenance_path=provenance_path,
    )
    if set(entries) != set(source_entries):
        raise ValueError("distribution provenance inventory is not exact")
    if _stage_inventory(stage) != set(entries):
        raise ValueError("native release stage inventory is not exact")

    for relative, source_entry in source_entries.items():
        entry = entries[relative]
        source = _safe_source(root_path, relative)
        source_payload = _bound_file_bytes(
            source,
            expected_size=source_entry["size"],
            expected_sha256=source_entry["sha256"],
            label=f"provenance-pinned source binary {relative}",
        )
        staged = _safe_source(stage, relative)
        staged_payload = staged.read_bytes()
        staged_size = len(staged_payload)
        staged_sha256 = _sha256_bytes(staged_payload)
        if entry.get("size") != staged_size or entry.get("sha256") != staged_sha256:
            raise ValueError(f"staged binary does not match provenance: {relative}")
        if (
            entry.get("source_size") != source_entry["size"]
            or entry.get("source_sha256") != source_entry["sha256"]
        ):
            raise ValueError(f"staged source binding is invalid: {relative}")
        for key in (
            "version",
            "source",
            "source_commit",
            "release_asset",
            "release_asset_sha256",
        ):
            if entry.get(key) != source_entry.get(key):
                raise ValueError(
                    f"staged source metadata binding is invalid: {relative}: {key}"
                )
        exact_source = staged_payload == source_payload
        is_clumsy = relative.casefold() == CLUMSY_PATH
        expected_transform = (
            "authenticode-signed-staged-copy"
            if is_clumsy and mode == STANDARD_MODE
            else "source-exact"
        )
        if entry.get("transform") != expected_transform:
            raise ValueError(f"staged transform is invalid: {relative}")
        if expected_transform == "source-exact" and not exact_source:
            raise ValueError(f"source-exact staged bytes changed: {relative}")
        if expected_transform != "source-exact" and exact_source:
            raise ValueError("signed staged clumsy.exe matches unsigned source bytes")
        if expected_transform != "source-exact":
            if entry.get("source_equivalence") != AUTHENTICODE_TRANSFORM:
                raise ValueError(
                    "signed staged Clumsy provenance has no source-equivalence proof"
                )
            verify_authenticode_source_equivalence(
                source_payload,
                staged_payload,
            )
        elif entry.get("source_equivalence") is not None:
            raise ValueError(
                f"source-exact staged binary has a transform proof: {relative}"
            )
        if is_clumsy:
            signature = entry.get("authenticode")
            if not isinstance(signature, dict):
                raise ValueError("staged Clumsy provenance has no signature measurement")
            status, fingerprint = _inspect_authenticode_bytes(
                staged_payload,
                signature_inspector,
            )
            fingerprint = (
                str(fingerprint).casefold()
                if fingerprint is not None
                else None
            )
            if (
                signature.get("status") != status
                or signature.get("signer_certificate_sha256") != fingerprint
            ):
                raise ValueError("staged Clumsy signature measurement changed")
            if mode == STANDARD_MODE and (
                status != "Valid" or fingerprint != expected_signer
            ):
                raise ValueError(
                    "standard staged Clumsy signature does not match the pinned signer"
                )
            if mode == UNSIGNED_MODE and (
                status != "NotSigned" or fingerprint is not None
            ):
                raise ValueError("explicit unsigned staged Clumsy is signed")
    return payload


def write_distribution_provenance(
    root: str | Path,
    output: Path,
    *,
    expected_mode: str,
    stage_root: str | Path | None = None,
    signature_inspector: Callable[[Path], tuple[str, str | None]] = inspect_authenticode,
    expected_signer_certificate_sha256: str | None = None,
) -> None:
    stage = _validated_stage_root(Path(root).resolve(), stage_root)
    source = stage / NATIVE_STAGE_MANIFEST
    payload = verify_native_stage(
        root,
        expected_mode=expected_mode,
        stage_root=stage,
        distribution_provenance_path=source,
        signature_inspector=signature_inspector,
        expected_signer_certificate_sha256=(
            expected_signer_certificate_sha256
        ),
    )
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    _atomic_write(output, encoded)


def _snapshot_native_binaries(
    source_root: Path,
    entries: dict[str, dict],
) -> Path:
    """Copy hash-validated bytes into a private build-lifetime snapshot."""
    holder = tempfile.TemporaryDirectory(prefix="dupez-native-snapshot-")
    snapshot = Path(holder.name)
    try:
        os.chmod(snapshot, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        for relative, entry in entries.items():
            source = _safe_source(source_root, relative)
            payload = _bound_file_bytes(
                source,
                expected_size=entry["size"],
                expected_sha256=entry["sha256"],
                label=f"verified native binary {relative}",
            )
            destination = snapshot.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if (
                destination.stat().st_size != entry["size"]
                or _sha256(destination) != entry["sha256"]
            ):
                raise ValueError(f"native binary snapshot mismatch: {relative}")
            os.chmod(destination, stat.S_IRUSR)
    except Exception:
        holder.cleanup()
        raise
    _NATIVE_SNAPSHOTS.append(holder)
    return snapshot


def _discard_native_snapshot(snapshot_root: Path) -> None:
    """Release a snapshot created by ``_snapshot_native_binaries`` immediately."""

    resolved = snapshot_root.resolve()
    for index in range(len(_NATIVE_SNAPSHOTS) - 1, -1, -1):
        holder = _NATIVE_SNAPSHOTS[index]
        if Path(holder.name).resolve() != resolved:
            continue
        _NATIVE_SNAPSHOTS.pop(index)
        holder.cleanup()
        return


def compile_installer(
    root: Path,
    *,
    expected_mode: str,
    iscc: str | Path,
    installer_definition: str | Path | None = None,
    runner=subprocess.run,
    stage_root: str | Path | None = None,
    manifest_path: Path = MANIFEST_PATH,
    provenance_path: Path = SOURCE_PROVENANCE_PATH,
    signature_inspector: Callable[
        [Path], tuple[str, str | None]
    ] = inspect_authenticode,
    expected_signer_certificate_sha256: str | None = None,
    tool_verifier: Callable[..., Path] = verify_release_tool,
) -> None:
    """Compile Inno Setup from a verified, private native-input snapshot.

    The mutable ``build/release-native`` directory is verified first and is never
    exposed to ISCC.  ``_snapshot_native_binaries`` re-checks every copied file
    against the signed provenance entries and makes the copies read-only.  The
    snapshot is checked again after ISCC returns and is then destroyed.
    """

    root = root.resolve()
    source_root = _validated_stage_root(root, stage_root)
    payload = verify_native_stage(
        root,
        expected_mode=expected_mode,
        stage_root=source_root,
        manifest_path=manifest_path,
        provenance_path=provenance_path,
        signature_inspector=signature_inspector,
        expected_signer_certificate_sha256=(
            expected_signer_certificate_sha256
        ),
    )
    entries = _distribution_artifacts(payload)
    snapshot_root = _snapshot_native_binaries(source_root, entries)
    verification_snapshot: Path | None = None
    try:
        definition = (
            Path(installer_definition).resolve()
            if installer_definition is not None
            else (root / "packaging" / "installer.iss").resolve()
        )
        environment = os.environ.copy()
        environment[INSTALLER_NATIVE_SNAPSHOT_ENV] = str(snapshot_root)
        verified_iscc = tool_verifier("iscc", iscc)
        completed = runner(
            [str(verified_iscc), str(definition)],
            cwd=str(root),
            env=environment,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"ISCC failed with exit code {completed.returncode}; "
                "installer was not accepted"
            )

        # Re-copying through the same verified snapshot primitive provides a
        # post-compile integrity check without trusting mutable source paths.
        verification_snapshot = _snapshot_native_binaries(snapshot_root, entries)
    finally:
        try:
            if verification_snapshot is not None:
                _discard_native_snapshot(verification_snapshot)
        finally:
            _discard_native_snapshot(snapshot_root)


def pyinstaller_binaries(
    root: str,
    *,
    stage_root: str | Path | None = None,
    manifest_path: Path = MANIFEST_PATH,
    provenance_path: Path = SOURCE_PROVENANCE_PATH,
    signature_inspector: Callable[[Path], tuple[str, str | None]] = inspect_authenticode,
    expected_signer_certificate_sha256: str | None = None,
) -> list[tuple[str, str]]:
    root_path = Path(root).resolve()
    configured_stage = stage_root or os.environ.get(
        "DUPEZ_RELEASE_NATIVE_STAGE"
    )
    if configured_stage:
        expected_mode = os.environ.get("DUPEZ_RELEASE_MODE")
        if expected_mode not in RELEASE_MODES:
            raise ValueError("DUPEZ_RELEASE_MODE is missing or invalid")
        source_root = _validated_stage_root(root_path, configured_stage)
        payload = verify_native_stage(
            root_path,
            expected_mode=expected_mode,
            stage_root=source_root,
            manifest_path=manifest_path,
            provenance_path=provenance_path,
            signature_inspector=signature_inspector,
            expected_signer_certificate_sha256=(
                expected_signer_certificate_sha256
            ),
        )
        entries = _distribution_artifacts(payload)
    else:
        source_root = root_path
        entries = _source_provenance_entries(
            root_path,
            manifest_path=manifest_path,
            provenance_path=provenance_path,
        )
    source_root = _snapshot_native_binaries(source_root, entries)
    binaries: list[tuple[str, str]] = []
    for relative in release_binary_files(manifest_path):
        source = _safe_source(source_root, relative)
        destination = str(PurePosixPath(relative).parent).replace(
            "/",
            os.sep,
        )
        binaries.append((str(source), destination))
    return binaries


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--mode", choices=sorted(RELEASE_MODES), required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--mode", choices=sorted(RELEASE_MODES), required=True)
    emit = subparsers.add_parser("emit-provenance")
    emit.add_argument("--mode", choices=sorted(RELEASE_MODES), required=True)
    emit.add_argument("--out", type=Path, required=True)
    verify_tool = subparsers.add_parser("verify-tool")
    verify_tool.add_argument("--name", choices=("iscc", "signtool"), required=True)
    verify_tool.add_argument("--path", type=Path, required=True)
    args = parser.parse_args()

    root = HERE.parent
    try:
        if args.command == "prepare":
            stage = prepare_native_stage(root)
            print(f"Prepared verified native release stage: {stage}")
        elif args.command == "finalize":
            output = finalize_native_stage(root, args.mode)
            print(f"Finalized measured native release stage: {output}")
        elif args.command == "verify":
            verify_native_stage(root, expected_mode=args.mode)
            print("Verified native release stage.")
        elif args.command == "emit-provenance":
            write_distribution_provenance(
                root,
                args.out,
                expected_mode=args.mode,
            )
            print(f"Wrote measured distribution provenance: {args.out}")
        else:
            verified_tool = verify_release_tool(args.name, args.path)
            print(f"Verified pinned release tool: {verified_tool.name}")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
