"""Windows native TLS collection policy shared by PyInstaller and tests.

Qt's Windows OpenSSL hook probes the host PATH and can collect unrelated DLLs.
Legacy/raster Qt payloads use only Windows Schannel. The explicit profile that
excludes Qt Network admits no Qt TLS plugins. CPython's independently patched
OpenSSL remains present for Python HTTPS and cryptography is untouched.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys


_QT_TLS_PREFIX = "pyqt6/qt6/plugins/tls/"
_EXCLUDED_QT_TLS_PLUGINS = frozenset({"qopensslbackend.dll", "qcertonlybackend.dll"})
_PYTHON_OPENSSL_DLLS = frozenset({"libssl-3.dll", "libcrypto-3.dll"})

# Embedded browsing is unavailable in both frozen variants. These modules
# must not re-enter through another PyInstaller hook or a developer install.
FROZEN_BROWSER_EXCLUDES = (
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick",
    "PyQt6.QtWebChannel", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuickWidgets",
    "PyQt6.QtQuick3D", "app.gui.map_host.host", "app.gui.map_host.request_policy",
)
_DISABLED_BROWSER_UIC_PLUGINS = frozenset({
    "pyqt6/uic/widget-plugins/qtquickwidgets.py",
    "pyqt6/uic/widget-plugins/qtwebenginewidgets.py",
})
QT_BUILD_PROFILES = ("legacy", "frozen-raster", "frozen-raster-no-qtnetwork")
NO_QTNETWORK_PROFILE = "frozen-raster-no-qtnetwork"
FROZEN_QTNETWORK_EXCLUDES = ("PyQt6.QtNetwork",)
FROZEN_RASTER_EXCLUDES = ("PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets")
_FROZEN_RASTER_NATIVE_NAMES = frozenset({
    "qt6opengl.dll", "qt6openglwidgets.dll", "opengl32sw.dll", "d3dcompiler_47.dll",
})


def validate_qt_build_profile(profile: str) -> str:
    if profile not in QT_BUILD_PROFILES:
        raise ValueError("Unknown Qt build profile; expected " + ", ".join(QT_BUILD_PROFILES))
    return profile


def configured_qt_build_profile() -> str:
    """Read a build-only selector; runtime environment cannot change this policy."""
    return validate_qt_build_profile(os.environ.get("DUPEZ_QT_BUILD_PROFILE", "legacy"))


def _normalized_path(value: object) -> str:
    return str(value).replace("\\", "/").strip("/").casefold()


def without_disabled_browser_uic_plugins(datas: list) -> list:
    """Omit the two unused browser designer plugins collected as data by uic.

    Module exclusions do not affect these hook-added source files. Keep all
    other entries for the strict browser/QML rejection that follows; never
    turn an unexpected browser DLL or resource into a silently removed input.
    """
    return [entry for entry in datas if _normalized_path(entry[0]) not in _DISABLED_BROWSER_UIC_PLUGINS]


def excluded_browser_payloads(names) -> list[str]:
    """Find browser/QML bytes in Analysis or final outer/PYZ archive names.

    Inspect all payload kinds, including data; native DLL filtering alone
    would miss Chromium resources and QML code. This is a scope boundary,
    not a general native vulnerability or corresponding-source clearance.
    """
    found = set()
    for value in names:
        path = _normalized_path(value)
        module = path.replace("/", ".")
        basename = path.rsplit("/", 1)[-1]
        if (
            any(module == excluded.casefold() or module.startswith(excluded.casefold() + ".")
                for excluded in FROZEN_BROWSER_EXCLUDES)
            or basename.startswith(("qt6webengine", "qt6webchannel", "qt6qml", "qt6quick",
                                    "qtwebengine", "qtwebchannel", "qtqml", "qtquick", "qmldbg_"))
            or any(part.startswith("qtwebengine") for part in path.split("/"))
            or "/qml/" in "/" + path
            or "/qmltooling/" in "/" + path
            or basename.endswith((".qml", ".qmltypes"))
            or basename in {"icudtl.dat", "v8_context_snapshot.bin"}
        ):
            found.add(path)
    return sorted(found)


def validate_no_embedded_browser_payload(names) -> None:
    unexpected = excluded_browser_payloads(names)
    if unexpected:
        raise RuntimeError("Excluded embedded browser/QML payload: " + ", ".join(unexpected[:10]))


def excluded_frozen_raster_payloads(names) -> list[str]:
    """Find GL bindings, definitions and native helpers in any archive section."""
    found = set()
    for value in names:
        path = _normalized_path(value)
        module = path.replace("/", ".")
        basename = path.rsplit("/", 1)[-1]
        if (
            any(module == excluded.casefold() or module.startswith(excluded.casefold() + ".")
                for excluded in FROZEN_RASTER_EXCLUDES)
            or basename in _FROZEN_RASTER_NATIVE_NAMES
            or any(basename == name or basename.startswith(name + ".")
                   for name in ("qtopengl", "qtopenglwidgets"))
            or any("/bindings/" + name + "/" in "/" + path + "/"
                   for name in ("qtopengl", "qtopenglwidgets"))
        ):
            found.add(path)
    return sorted(found)


def validate_frozen_raster_payload(names, *, qt_profile: str) -> None:
    """Reject raster-profile contamination without silently deleting payloads."""
    if validate_qt_build_profile(qt_profile) == "legacy":
        return
    names = list(names)
    unexpected = excluded_frozen_raster_payloads(names)
    if unexpected:
        raise RuntimeError("Excluded frozen-raster payload: " + ", ".join(unexpected[:10]))
    if qt_profile == NO_QTNETWORK_PROFILE:
        unexpected = excluded_qtnetwork_payloads(names)
        if unexpected:
            raise RuntimeError("Excluded Qt Network payload: " + ", ".join(unexpected[:10]))


def excluded_qtnetwork_payloads(names) -> list[str]:
    """Reject Network bindings, native code, and all dependent plugin families."""
    found = set()
    for value in names:
        path = _normalized_path(value)
        module = path.replace("/", ".")
        basename = path.rsplit("/", 1)[-1]
        if (
            any(module == excluded.casefold() or module.startswith(excluded.casefold() + ".")
                for excluded in FROZEN_QTNETWORK_EXCLUDES)
            or basename in {"qt6network.dll", "qnetworklistmanager.dll", "qschannelbackend.dll",
                            "qopensslbackend.dll", "qcertonlybackend.dll", "qtuiotouchplugin.dll"}
            or basename == "qtnetwork" or basename.startswith("qtnetwork.")
            or "/bindings/qtnetwork/" in "/" + path + "/"
            or "/plugins/tls/" in "/" + path + "/"
            or "/plugins/networkinformation/" in "/" + path + "/"
        ):
            found.add(path)
    return sorted(found)


def validate_no_qtnetwork_pe(data: bytes) -> None:
    """Inspect bounded PE bytes without loading native code, including delay imports."""
    if not isinstance(data, bytes) or not 64 <= len(data) <= 256 * 1024 * 1024 or data[:2] != b"MZ":
        raise ValueError("Invalid or oversized native PE input for Qt Network exclusion")
    try:
        import pefile
    except ImportError as exc:
        raise RuntimeError("Qt Network native exclusion requires the locked pefile build dependency") from exc

    try:
        pe = pefile.PE(data=data, fast_load=True)
        try:
            initial_warnings = len(pe.get_warnings())
            pe.parse_data_directories(directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
            ], import_dllnames_only=True)
            if len(pe.get_warnings()) != initial_warnings:
                raise ValueError("Cannot validate incomplete native PE import directories")
            names = [entry.dll for section in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                     for entry in getattr(pe, section, ())]
            if len(names) > 4096 or any(not name or name == b"*invalid*" or len(name) >= 512 for name in names):
                raise ValueError("Invalid or excessive native PE dependency names")
            # Only the export directory's DLL name is relevant here. Enumerating
            # symbols hits pefile's 8192-symbol cap for valid Qt/OpenBLAS DLLs.
            directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]]
            if directory.VirtualAddress:
                header = pe.get_data(directory.VirtualAddress, 40)
                if len(header) != 40:
                    raise ValueError("Invalid native PE export directory")
                name_rva = struct.unpack_from("<I", header, 12)[0]
                name = pe.get_string_at_rva(name_rva, 512)
                if not name_rva or not name or len(name) >= 512:
                    raise ValueError("Invalid native PE export identity")
                names.append(name)
            if any(name.decode("ascii", errors="strict").casefold().replace("\\", "/").rsplit("/", 1)[-1]
                   == "qt6network.dll" for name in names):
                raise ValueError("Native PE contains Qt6Network identity or import")
        finally:
            pe.close()
    except (pefile.PEFormatError, UnicodeError, AttributeError, TypeError, IndexError, struct.error) as exc:
        raise ValueError("Cannot validate native PE Qt Network exclusion") from exc


def validate_compiled_qt_profile(embedded, *, qt_profile: str) -> None:
    """Read a literal compiled profile without executing archived Python code."""
    import dis
    from types import CodeType

    validate_qt_build_profile(qt_profile)
    keys = [name for name in embedded.toc
            if _normalized_path(name).replace("/", ".") == "app.firewall_helper._build_default"]
    if not keys:
        if qt_profile == NO_QTNETWORK_PROFILE:
            raise ValueError("Frozen archive is missing the compiled Qt build profile")
        return  # Historical archives predate the compiled Qt profile field.
    if len(keys) != 1:
        raise ValueError("Frozen archive contains ambiguous compiled Qt profiles")
    code = embedded.extract(keys[0])
    if not isinstance(code, CodeType):
        raise ValueError("Frozen build default is not compiled Python code")
    instructions = list(dis.get_instructions(code))
    values = []
    for index, instruction in enumerate(instructions):
        if instruction.opname in {"STORE_NAME", "STORE_GLOBAL"} and instruction.argval == "_BUILD_QT_PROFILE":
            if not index or instructions[index - 1].opname != "LOAD_CONST":
                raise ValueError("Frozen Qt build profile is not a literal constant")
            values.append(instructions[index - 1].argval)
    if not values and qt_profile != NO_QTNETWORK_PROFILE:
        return
    if values != [qt_profile]:
        raise ValueError("Frozen compiled Qt profile differs from requested validation profile")


def validate_msvc_redist_rows(rows: list[dict], manifest_path: Path) -> str:
    """Require exactly the three reviewed System32 redistributable bytes."""
    with manifest_path.open("rb") as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("MSVC redistributable manifest exceeds size limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate MSVC redistributable manifest key")
            result[key] = value
        return result

    manifest = json.loads(data, object_pairs_hook=unique)
    if manifest.get("schema") != "dupez.msvc-redist-inputs.v1":
        raise ValueError("Unsupported MSVC redistributable manifest")
    pins = manifest.get("binaries", [])
    expected_names = {"msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll"}
    if len(pins) != 3 or {pin["name"].casefold() for pin in pins} != expected_names:
        raise ValueError("Unexpected MSVC redistributable manifest inventory")
    if any(type(pin.get("size")) is not int or not 0 < pin["size"] <= 64 * 1024 * 1024
           or not re.fullmatch(r"[a-f0-9]{64}", str(pin.get("sha256"))) for pin in pins):
        raise ValueError("Invalid MSVC redistributable byte pins")
    expected = {pin["name"].casefold(): pin for pin in pins}
    system_rows = [row for row in rows if row["origin"] == "windows-system32"]
    if len(system_rows) != 3 or {_normalized_path(row["destination"]) for row in system_rows} != expected_names:
        raise ValueError("System32 native inventory differs from pinned MSVC redistributable")
    for row in system_rows:
        pin = expected[_normalized_path(row["destination"])]
        if row["sha256"] != pin["sha256"]:
            raise ValueError("System32 native bytes differ from pinned MSVC redistributable")
        if "size" in row:
            size = row["size"]
        else:
            with Path(row["source"]).open("rb") as stream:
                source_data = stream.read(pin["size"] + 1)
            size = len(source_data)
            if hashlib.sha256(source_data).hexdigest() != pin["sha256"]:
                raise ValueError("System32 source changed after native origin inspection")
        if size != pin["size"]:
            raise ValueError("System32 native size differs from pinned MSVC redistributable")
    return hashlib.sha256(data).hexdigest()


def configure_windows_analysis_environment() -> str | None:
    """Constrain only this build process and its children, never host settings."""
    if sys.platform != "win32":
        return
    buffer = ctypes.create_unicode_buffer(32768)
    get_system_directory = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    get_system_directory.restype = ctypes.c_uint
    length = get_system_directory(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise RuntimeError("Cannot establish the Windows system directory for native build isolation")
    paths = [Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs", Path(buffer.value)]
    # Do not reuse inherited PATH entries (e.g. Poppler, Git, or unrelated Qt).
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(str(path.resolve(strict=True)) for path in paths))
    for key in list(os.environ):
        folded = key.casefold()
        if folded in {"qt_plugin_path", "qt_qpa_platform_plugin_path", "qml_import_path", "qml2_import_path"} or folded.startswith("qtwebengine"):
            os.environ.pop(key, None)
    return str(Path(buffer.value).resolve(strict=True))


def filter_qt_network_hook_binaries(binaries: list) -> list:
    """Filter hook (source, destination-directory) pairs before bindepend."""
    result = []
    for source, destination in binaries:
        if _normalized_path(destination).endswith("/plugins/tls"):
            name = _normalized_path(source).rsplit("/", 1)[-1]
            if name in _EXCLUDED_QT_TLS_PLUGINS:
                continue
            if name != "qschannelbackend.dll":
                raise RuntimeError(f"Unreviewed Qt TLS plugin: {name}")
        result.append((source, destination))
    return result


def validate_windows_tls_binaries(binaries: list, *, python_base: Path, qt_root: Path,
                                  qt_profile: str = "legacy") -> list:
    """Require profile-specific Qt TLS and canonical Python OpenSSL sources.

    This validates actual source locations, not basenames or version strings.
    Exact runtime wheel/bootstrap hashes are enforced by the build bootstrap.
    """
    no_network = validate_qt_build_profile(qt_profile) == NO_QTNETWORK_PROFILE
    expected_openssl = {name: (python_base / "DLLs" / name).resolve(strict=True) for name in _PYTHON_OPENSSL_DLLS}
    expected_schannel = None if no_network else (qt_root / "plugins" / "tls" / "qschannelbackend.dll").resolve(strict=True)
    found_python_dlls = set()
    found_schannel = False
    result = []
    for entry in binaries:
        destination = _normalized_path(entry[0])
        basename = destination.rsplit("/", 1)[-1]
        if no_network:
            validate_frozen_raster_payload((destination, entry[1]), qt_profile=qt_profile)
            source = Path(entry[1]).resolve(strict=True)
            with source.open("rb") as stream:
                validate_no_qtnetwork_pe(stream.read(256 * 1024 * 1024 + 1))
        if destination.startswith(_QT_TLS_PREFIX):
            if basename in _EXCLUDED_QT_TLS_PLUGINS:
                continue
            if destination != _QT_TLS_PREFIX + "qschannelbackend.dll":
                raise RuntimeError(f"Unreviewed Qt TLS payload: {destination}")
            if Path(entry[1]).resolve(strict=True) != expected_schannel:
                raise RuntimeError("Qt Schannel plugin was collected outside the locked PyQt wheel")
            found_schannel = True
        elif basename in _EXCLUDED_QT_TLS_PLUGINS or basename == "qschannelbackend.dll":
            raise RuntimeError(f"Qt TLS plugin was collected at an unreviewed path: {destination}")
        if basename.startswith(("libssl", "libcrypto")) and basename.endswith(".dll"):
            if destination not in _PYTHON_OPENSSL_DLLS or Path(entry[1]).resolve(strict=True) != expected_openssl[destination]:
                raise RuntimeError(f"Unreviewed OpenSSL DLL in frozen payload: {destination}")
            found_python_dlls.add(destination)
        result.append(entry)
    if not no_network and not found_schannel:
        raise RuntimeError("Frozen Qt payload is missing the reviewed Windows Schannel plugin")
    if found_python_dlls != _PYTHON_OPENSSL_DLLS:
        raise RuntimeError("Frozen Python payload is missing its canonical PSF OpenSSL DLL pair")
    return result


def audit_native_binary_origins(
    binaries: list,
    *,
    approved_roots: dict[str, Path],
    managed_sources: list[Path],
) -> list[dict[str, str]]:
    """Fail closed on ambient DLL/PYD origins and hash the actual final TOC.

    Roots are restricted to the locked venv, verified base Python, and Windows
    System32. Managed native sources are individually verified by release_data;
    no broad checkout, temporary-directory, home, or inherited PATH is trusted.
    """
    roots = {label: root.resolve(strict=True) for label, root in approved_roots.items()}
    managed = {source.resolve(strict=True) for source in managed_sources}
    report = []
    for destination, source, kind in binaries:
        path = Path(source).resolve(strict=True)
        origin = "managed-native" if path in managed else next(
            (label for label, root in roots.items() if path.is_relative_to(root)), None,
        )
        if origin is None:
            raise RuntimeError(f"Unreviewed ambient native dependency: {destination} from {path}")
        if not path.is_file():
            raise RuntimeError(f"Native dependency is not a regular file: {destination}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        report.append({"destination": str(destination).replace("\\", "/"), "source": str(path),
                       "kind": str(kind), "origin": origin, "sha256": digest})
    return sorted(report, key=lambda row: row["destination"].casefold())
