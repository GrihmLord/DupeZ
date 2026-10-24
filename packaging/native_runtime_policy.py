"""Windows native TLS collection policy shared by PyInstaller and tests.

Qt's Windows OpenSSL hook probes the host PATH and can collect unrelated DLLs.
Our Qt payload uses only the Windows Schannel backend. CPython's independently
patched OpenSSL remains present for Python HTTPS and cryptography is untouched.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import sys


_QT_TLS_PREFIX = "pyqt6/qt6/plugins/tls/"
_EXCLUDED_QT_TLS_PLUGINS = frozenset({"qopensslbackend.dll", "qcertonlybackend.dll"})
_PYTHON_OPENSSL_DLLS = frozenset({"libssl-3.dll", "libcrypto-3.dll"})


def _normalized_path(value: object) -> str:
    return str(value).replace("\\", "/").strip("/").casefold()


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


def validate_windows_tls_binaries(binaries: list, *, python_base: Path, qt_root: Path) -> list:
    """Return a Schannel-only Qt TOC; reject OpenSSL from ambient locations.

    This validates actual source locations, not basenames or version strings.
    Exact runtime wheel/bootstrap hashes are enforced by the build bootstrap.
    """
    expected_openssl = {name: (python_base / "DLLs" / name).resolve(strict=True) for name in _PYTHON_OPENSSL_DLLS}
    expected_schannel = (qt_root / "plugins" / "tls" / "qschannelbackend.dll").resolve(strict=True)
    found_python_dlls = set()
    found_schannel = False
    result = []
    for entry in binaries:
        destination = _normalized_path(entry[0])
        basename = destination.rsplit("/", 1)[-1]
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
    if not found_schannel:
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
