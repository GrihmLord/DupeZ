#!/usr/bin/env python3
"""Architecture-correct lifecycle validation for signed DupeZ frozen builds.

The PowerShell wrapper enforces the operator's elevation context and invokes
this module with the repository Python. The validator follows PyInstaller's
one-file process tree, binds to the exact dashboard HWND, exercises the real
Ctrl+2 and Ctrl+Q shortcuts, checks map initialization and clean shutdown, and
writes private hash-bound evidence under ``dist``.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import BinaryIO, Iterable, Mapping, Optional
import uuid

import psutil

SCHEMA = "dupez.frozen-runtime-validation.v3"
NETWORK_VALIDATION_MODE = "production-safety-dry-run"
NETWORK_VALIDATION_SIGNAL = (
    "Safety dry-run controller started without scheduler, plugins, auto-scan, "
    "or packet engine"
)
SHUTDOWN_DIAGNOSTIC_MARKERS = (
    ("controller-started", "Controller shutting down"),
    ("controller-complete", "Controller shutdown complete"),
    ("controller-errors", "Controller shutdown completed with errors"),
    ("shutdown-step-failed", "Shutdown step failed"),
    ("network-tools-unconfirmed", "Network Tools shutdown completed with unconfirmed cleanup"),
    ("dashboard-cleanup-refused", "Application close refused"),
)
DUPEZ_PROCESS_NAMES = frozenset({"dupez-gpu.exe", "dupez-compat.exe", "dupez.exe"})
WEBENGINE_PROCESS_NAMES = frozenset({"qtwebengineprocess.exe"})
FILE_ATTRIBUTE_REPARSE_POINT = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
GIT_OVERRIDE_ENVIRONMENT_NAMES = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_EXEC_PATH",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_REPLACE_REF_BASE",
        "GIT_WORK_TREE",
    }
)
GIT_OVERRIDE_ENVIRONMENT_PREFIXES = (
    "GIT_CONFIG_",
    "GIT_OBJECT_DIRECTORY_",
)
RELEASE_SENSITIVE_ENVIRONMENT_NAMES = frozenset(
    {
        "DUPEZ_ARCH",
        "DUPEZ_BUILD_ANALYSIS",
        "DUPEZ_DISABLE_CERT_PIN",
        "DUPEZ_DISABLE_WEBENGINE",
        "DUPEZ_ELEVATION",
        "DUPEZ_FORCE_USER_DATA",
        "DUPEZ_LOW_RESOURCE",
        "DUPEZ_MAP_EMBED",
        "DUPEZ_MAP_PREWARM",
        "DUPEZ_MAP_RENDERER",
        "DUPEZ_MAP_RENDERER_TIER",
        "DUPEZ_PLUGIN_DEV_MODE",
        "DUPEZ_QT_MAX_THREADS",
        "DUPEZ_RELEASE_VALIDATION",
        "DUPEZ_STARTUP_TIMEOUT_MS",
        "DUPEZ_USER_ROOT",
        "QML2_IMPORT_PATH",
        "PYTHONHTTPSVERIFY",
        "PYTHONBREAKPOINT",
        "PYTHONHOME",
        "PYTHONINSPECT",
        "PYTHONPATH",
        "PYTHONPYCACHEPREFIX",
        "PYTHONSTARTUP",
        "PYTHONWARNINGS",
        "SSLKEYLOGFILE",
        "QT_DEBUG_PLUGINS",
        "QT_FATAL_WARNINGS",
        "QT_LOGGING_RULES",
        "QT_OPENGL",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM",
        "QT_SCALE_FACTOR",
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "QTWEBENGINE_DICTIONARIES_PATH",
        "QTWEBENGINE_DISABLE_SANDBOX",
        "QTWEBENGINE_LOCALES_PATH",
        "QTWEBENGINE_REMOTE_DEBUGGING",
        "QTWEBENGINE_RESOURCES_PATH",
        "QTWEBENGINEPROCESS_PATH",
    }
)
RELEASE_SENSITIVE_ENVIRONMENT_PREFIXES = (
    "_PYI_",
    "PYINSTALLER_",
    "QML",
    "QSG_",
    "QT_",
    "QTWEBENGINE_",
)
AMBIENT_SECRET_NAME_SEGMENTS = frozenset(
    {
        "CREDENTIAL",
        "CREDENTIALS",
        "PASSWD",
        "PASSWORD",
        "PRIVKEY",
        "SECRET",
        "SECRETS",
        "TOKEN",
        "TOKENS",
    }
)
AMBIENT_SECRET_NAME_SEQUENCES = frozenset(
    {
        ("API", "KEY"),
        ("PRIVATE", "KEY"),
    }
)
AMBIENT_SECRET_EXACT_NAMES = frozenset(
    {
        "DUPEZ_OFFSEC_OPERATOR_KEY",
    }
)
VALIDATOR_PROFILE_ENVIRONMENT_NAMES = frozenset(
    {
        "DUPEZ_LOW_RESOURCE",
        "DUPEZ_MAP_PREWARM",
        "DUPEZ_QT_MAX_THREADS",
        "DUPEZ_STARTUP_TIMEOUT_MS",
    }
)
WEBENGINE_INITIALIZED_SIGNAL = "Map: WebEngine boundary initialized; awaiting navigation"
MAP_LOAD_FINISHED_SIGNAL = "Map: WebEngine navigation ready"
MAP_DASHBOARD_ACTIVE_SIGNAL = "Map: dashboard view active with WebEngine ready"
MAP_POST_READY_STABILITY_SECONDS = 1.0
MAP_FAILURE_MARKERS = (
    "QtWebEngine disabled",
    "placeholder",
    "map_view is None",
    "WebEngine initialization failed",
    "dashboard view active without WebEngine",
    "renderer terminated",
    "render process terminated",
    "renderProcessTerminated",
    "navigation failed",
    "Map: inproc load failed",
    "Map: child host load failed",
    "Lazy map initialization failed",
)
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_CONTROL = 0x11
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
ULONG_PTR = wintypes.WPARAM


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]


_FOLDERID_LOCAL_APPDATA = _Guid(
    0xF1B32785,
    0x6FBA,
    0x4FCF,
    (ctypes.c_ubyte * 8)(0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91),
)
_FOLDERID_PROGRAM_FILES = _Guid(
    0x905E63B6,
    0xC1BF,
    0x494E,
    (ctypes.c_ubyte * 8)(0xB2, 0x9C, 0x65, 0xB7, 0x32, 0xD3, 0xD2, 0x1A),
)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    # INPUT is a native union. Omitting the largest MOUSEINPUT member makes
    # sizeof(INPUT) 32 instead of 40 on Win64, and SendInput rejects cbSize.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [
        ("file_attributes", ctypes.c_uint32),
        ("reparse_tag", ctypes.c_uint32),
    ]


if sys.platform == "win32":
    USER32 = ctypes.WinDLL("user32", use_last_error=True)
    KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    USER32.SendInput.argtypes = (
        wintypes.UINT,
        ctypes.POINTER(INPUT),
        ctypes.c_int,
    )
    USER32.SendInput.restype = wintypes.UINT
    USER32.IsWindow.argtypes = (wintypes.HWND,)
    USER32.IsWindow.restype = wintypes.BOOL
    USER32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    USER32.ShowWindow.restype = wintypes.BOOL
    USER32.GetForegroundWindow.restype = wintypes.HWND
    USER32.BringWindowToTop.argtypes = (wintypes.HWND,)
    USER32.BringWindowToTop.restype = wintypes.BOOL
    USER32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    USER32.SetForegroundWindow.restype = wintypes.BOOL
    USER32.SetActiveWindow.argtypes = (wintypes.HWND,)
    USER32.SetActiveWindow.restype = wintypes.HWND
    USER32.SetFocus.argtypes = (wintypes.HWND,)
    USER32.SetFocus.restype = wintypes.HWND
    USER32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
    USER32.AttachThreadInput.argtypes = (
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.BOOL,
    )
    USER32.AttachThreadInput.restype = wintypes.BOOL
    KERNEL32.GetCurrentThreadId.restype = wintypes.DWORD
    SHELL32 = ctypes.windll.shell32
else:  # pragma: no cover - the wrapper and runtime gate are Windows-only.
    USER32 = None
    KERNEL32 = None
    SHELL32 = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True, choices=("GPU", "Compat"))
    parser.add_argument("--dist-directory", default="dist")
    parser.add_argument("--cycles-per-profile", type=int, default=1)
    parser.add_argument("--startup-timeout", type=int, default=150)
    parser.add_argument("--map-timeout", type=int, default=60)
    parser.add_argument("--shutdown-timeout", type=int, default=45)
    parser.add_argument(
        "--allow-dirty-validation",
        action="store_true",
        help=(
            "permit explicitly non-release local evidence from a dirty tree; "
            "the PowerShell release wrapper intentionally does not expose this"
        ),
    )
    args = parser.parse_args()
    if not 1 <= args.cycles_per_profile <= 5:
        parser.error("--cycles-per-profile must be from 1 to 5")
    for name in ("startup_timeout", "map_timeout", "shutdown_timeout"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return args


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(SHELL32.IsUserAnAdmin())
    except OSError:
        return False


def _is_reparse_stat(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(metadata.st_mode) or int(getattr(metadata, "st_file_attributes", 0)) & FILE_ATTRIBUTE_REPARSE_POINT
    )


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _assert_regular_non_reparse_file(
    path: Path,
    *,
    require_single_link: bool = False,
) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise RuntimeError("Required validation file is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or _is_reparse_stat(metadata):
        raise RuntimeError("Validation requires a regular non-reparse file")
    if require_single_link and int(metadata.st_nlink) != 1:
        raise RuntimeError("Validation refuses a hard-linked release artifact")
    return metadata


def _sha256(path: Path, *, require_single_link: bool = False) -> str:
    """Hash one stable regular file without following a reparse-point leaf."""

    initial = _assert_regular_non_reparse_file(
        path,
        require_single_link=require_single_link,
    )
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOINHERIT", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags)
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if _file_identity(opened) != _file_identity(initial):
            raise RuntimeError("Validation file changed while it was opened")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        finished = os.fstat(descriptor)
        if _file_identity(finished) != _file_identity(initial):
            raise RuntimeError("Validation file changed while it was hashed")
    finally:
        os.close(descriptor)
    current = _assert_regular_non_reparse_file(
        path,
        require_single_link=require_single_link,
    )
    if _file_identity(current) != _file_identity(initial):
        raise RuntimeError("Validation file changed after it was hashed")
    return digest.hexdigest()


def _normalize_windows_handle_path(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return os.path.normcase(os.path.normpath(path))


def _locked_release_executable(
    path: Path,
    *,
    expected_hash: str,
    expected_size: int,
) -> BinaryIO:
    """Open and hash an EXE while denying path writes/deletes until close."""

    if sys.platform != "win32":
        raise RuntimeError("Frozen executable locking requires Windows")
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(path),
        0x80000000,  # GENERIC_READ
        0x00000001,  # FILE_SHARE_READ: deny write and delete while held
        None,
        3,  # OPEN_EXISTING
        0x00000080 | 0x00200000,  # NORMAL | OPEN_REPARSE_POINT
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in (None, invalid_handle):
        raise RuntimeError("Frozen executable could not be locked for launch")

    descriptor = -1
    stream: Optional[BinaryIO] = None
    try:
        get_file_type = kernel32.GetFileType
        get_file_type.argtypes = [ctypes.c_void_p]
        get_file_type.restype = ctypes.c_uint32
        if int(get_file_type(handle)) != 0x0001:  # FILE_TYPE_DISK
            raise RuntimeError("Frozen executable is not a disk file")

        get_information = kernel32.GetFileInformationByHandleEx
        get_information.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        get_information.restype = ctypes.c_int
        information = _FileAttributeTagInfo()
        if not get_information(
            handle,
            9,  # FileAttributeTagInfo
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            raise RuntimeError("Frozen executable handle could not be inspected")
        unsafe = 0x10 | FILE_ATTRIBUTE_REPARSE_POINT
        if int(information.file_attributes) & unsafe:
            raise RuntimeError("Frozen executable handle is a directory or reparse point")

        get_final_path = kernel32.GetFinalPathNameByHandleW
        get_final_path.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        get_final_path.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(32768)
        written = int(get_final_path(handle, buffer, len(buffer), 0))
        if written == 0 or written >= len(buffer):
            raise RuntimeError("Frozen executable final path is unavailable")
        if _normalize_windows_handle_path(buffer.value) != _normalize_windows_handle_path(os.path.abspath(path)):
            raise RuntimeError("Frozen executable resolved outside its expected path")

        flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
        descriptor = msvcrt.open_osfhandle(int(handle), flags)
        handle = None
        stream = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = -1
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or int(opened.st_nlink) != 1 or int(opened.st_size) != expected_size:
            raise RuntimeError("Locked frozen executable identity is invalid")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != expected_hash:
            raise RuntimeError("Frozen executable bytes changed before launch")
        stream.seek(0)
        return stream
    except BaseException:
        if stream is not None:
            stream.close()
        elif descriptor >= 0:
            os.close(descriptor)
        elif handle not in (None, invalid_handle):
            kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise


def _git_override_environment_names(
    environment: Mapping[str, str],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                name.upper()
                for name in environment
                if name.upper() in GIT_OVERRIDE_ENVIRONMENT_NAMES
                or name.upper().startswith(GIT_OVERRIDE_ENVIRONMENT_PREFIXES)
            }
        )
    )


def _assert_no_git_override_environment(
    environment: Optional[Mapping[str, str]] = None,
) -> None:
    inherited = _git_override_environment_names(os.environ if environment is None else environment)
    if inherited:
        raise RuntimeError(
            "Frozen validation refuses Git provenance overrides. "
            "Unset these names and retry: " + ", ".join(inherited)
        )


def _git_environment(
    environment: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    # The argument exists for adversarial tests; Git never receives the
    # validator's proxy, signing, cloud, agent, or credential environment.
    del environment
    cleaned = _windows_system_environment()
    local_appdata = _windows_local_appdata()
    temp_root = local_appdata / "Temp"
    _assert_non_reparse_directories(temp_root, allow_missing=False)
    cleaned.update(
        {
            "HOME": str(local_appdata / "DupeZ" / "release-validation"),
            "USERPROFILE": str(local_appdata / "DupeZ" / "release-validation"),
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "LC_ALL": "C",
        }
    )
    return cleaned


def _trusted_git_executable() -> Path:
    candidates = (
        _windows_program_files() / "Git" / "cmd" / "git.exe",
        _windows_program_files() / "Git" / "bin" / "git.exe",
    )
    for candidate in candidates:
        try:
            _assert_non_reparse_directories(candidate.parent, allow_missing=False)
            _assert_regular_non_reparse_file(candidate)
            return candidate
        except RuntimeError:
            continue
    raise RuntimeError("Trusted Git for Windows executable is unavailable")


def _git_run(
    repo_root: Path,
    arguments: list[str],
    *,
    allowed_returncodes: tuple[int, ...] = (0,),
    input_bytes: Optional[bytes] = None,
) -> bytes:
    git_executable = _trusted_git_executable()
    completed = subprocess.run(
        [
            str(git_executable),
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-C",
            str(repo_root),
            *arguments,
        ],
        cwd=git_executable.parent,
        env=_git_environment(),
        input=input_bytes,
        text=False,
        capture_output=True,
        check=False,
    )
    if completed.returncode not in allowed_returncodes:
        raise RuntimeError("Git provenance command failed")
    return bytes(completed.stdout)


def _assert_safe_git_configuration(repo_root: Path) -> None:
    git_directory = repo_root / ".git"
    _assert_non_reparse_directories(git_directory, allow_missing=False)
    info_directory = git_directory / "info"
    _assert_non_reparse_directories(info_directory, allow_missing=False)
    info_attributes = info_directory / "attributes"
    try:
        attributes_metadata = _assert_regular_non_reparse_file(
            info_attributes,
            require_single_link=True,
        )
    except RuntimeError:
        try:
            os.lstat(info_attributes)
        except FileNotFoundError:
            pass
        else:
            raise
    else:
        if int(attributes_metadata.st_size) != 0:
            raise RuntimeError("Frozen validation refuses .git/info attributes")

    info_exclude = info_directory / "exclude"
    try:
        exclude_before = _assert_regular_non_reparse_file(
            info_exclude,
            require_single_link=True,
        )
    except RuntimeError:
        try:
            os.lstat(info_exclude)
        except FileNotFoundError:
            pass
        else:
            raise
    else:
        if int(exclude_before.st_size) > 64 * 1024:
            raise RuntimeError("Git info exclude file is unexpectedly large")
        try:
            exclude_payload = info_exclude.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("Git info exclude file could not be inspected") from exc
        exclude_after = _assert_regular_non_reparse_file(
            info_exclude,
            require_single_link=True,
        )
        if _file_identity(exclude_before) != _file_identity(exclude_after):
            raise RuntimeError("Git info exclude file changed during inspection")
        if any(line.strip() and not line.lstrip().startswith("#") for line in exclude_payload.splitlines()):
            raise RuntimeError("Frozen validation refuses .git/info exclude patterns")

    unsafe_configuration = _git_run(
        repo_root,
        [
            "config",
            "--local",
            "--null",
            "--get-regexp",
            r"^(filter\.|core\.attributesfile$|core\.excludesfile$|include\.|includeif\.|extensions\.worktreeconfig$)",
        ],
        allowed_returncodes=(0, 1),
    )
    if unsafe_configuration:
        raise RuntimeError("Frozen validation refuses local Git filter/include/worktree configuration")


def _force_hash_tracked_worktree(repo_root: Path) -> tuple[bool, str]:
    """Compare normalized working bytes and index entries directly with HEAD."""

    tree_output = _git_run(
        repo_root,
        ["ls-tree", "-r", "-z", "--full-tree", "HEAD"],
    )
    head_entries: dict[bytes, tuple[bytes, bytes]] = {}
    for entry in filter(None, tree_output.split(b"\0")):
        try:
            header, encoded_path = entry.split(b"\t", 1)
            mode, object_type, object_id = header.split(b" ", 2)
        except ValueError as exc:
            raise RuntimeError("Git HEAD tree metadata is malformed") from exc
        if object_type != b"blob" or mode not in {b"100644", b"100755"}:
            raise RuntimeError("Frozen validation refuses symlinks, submodules, or special Git modes")
        if b"\n" in encoded_path or b"\r" in encoded_path:
            raise RuntimeError("Frozen validation refuses newline-bearing Git paths")
        if encoded_path in head_entries:
            raise RuntimeError("Git HEAD tree contains a duplicate path")
        head_entries[encoded_path] = (mode, object_id)

    index_output = _git_run(repo_root, ["ls-files", "-s", "-z"])
    index_entries: dict[bytes, tuple[bytes, bytes]] = {}
    index_clean = True
    for entry in filter(None, index_output.split(b"\0")):
        try:
            header, encoded_path = entry.split(b"\t", 1)
            mode, object_id, stage = header.split(b" ", 2)
        except ValueError as exc:
            raise RuntimeError("Git index entry is malformed") from exc
        if stage != b"0" or encoded_path in index_entries:
            index_clean = False
            continue
        index_entries[encoded_path] = (mode, object_id)
    if index_entries != head_entries:
        index_clean = False

    encoded_paths = tuple(head_entries)
    attribute_input = b"\0".join(encoded_paths) + (b"\0" if encoded_paths else b"")
    attribute_output = _git_run(
        repo_root,
        ["check-attr", "-z", "--stdin", "filter"],
        input_bytes=attribute_input,
    )
    attributes = attribute_output.split(b"\0")
    if attributes and attributes[-1] == b"":
        attributes.pop()
    if len(attributes) != len(encoded_paths) * 3:
        raise RuntimeError("Git filter-attribute output is malformed")
    for index in range(0, len(attributes), 3):
        path_name, attribute_name, attribute_value = attributes[index : index + 3]
        if (
            path_name not in head_entries
            or attribute_name != b"filter"
            or attribute_value not in {b"unspecified", b"unset"}
        ):
            raise RuntimeError("Frozen validation refuses custom Git clean filters")

    digest = hashlib.sha256()
    digest.update(b"head-tree\0" + tree_output)
    digest.update(b"index\0" + index_output)
    existing_paths: list[bytes] = []
    working_clean = True
    for encoded_path in encoded_paths:
        relative_name = os.fsdecode(encoded_path)
        candidate = repo_root / relative_name
        try:
            _assert_regular_non_reparse_file(candidate)
        except RuntimeError:
            try:
                os.lstat(candidate)
            except FileNotFoundError:
                working_clean = False
                digest.update(b"missing\0" + encoded_path)
                continue
            raise
        existing_paths.append(encoded_path)

    hash_input = b"\n".join(existing_paths) + (b"\n" if existing_paths else b"")
    observed_hashes = tuple(
        filter(
            None,
            _git_run(
                repo_root,
                ["hash-object", "--stdin-paths"],
                input_bytes=hash_input,
            ).splitlines(),
        )
    )
    if len(observed_hashes) != len(existing_paths):
        raise RuntimeError("Git worktree hash output is incomplete")
    for encoded_path, observed_hash in zip(existing_paths, observed_hashes):
        expected_hash = head_entries[encoded_path][1]
        digest.update(b"working\0" + encoded_path + b"\0" + observed_hash + b"\0")
        if observed_hash != expected_hash:
            working_clean = False
    return index_clean and working_clean, digest.hexdigest()


def _git_source_identity(
    repo_root: Path,
    *,
    allow_dirty: bool,
) -> tuple[str, str, str]:
    """Resolve HEAD and refuse to label dirty-tree output as release evidence."""

    _assert_no_git_override_environment()
    expected_root = os.path.normcase(os.path.abspath(repo_root))
    observed_root = os.path.normcase(
        os.path.abspath(os.fsdecode(_git_run(repo_root, ["rev-parse", "--show-toplevel"]).strip()))
    )
    if observed_root != expected_root:
        raise RuntimeError("Git provenance resolved a different repository root")
    commit = os.fsdecode(_git_run(repo_root, ["rev-parse", "--verify", "HEAD^{commit}"]).strip())
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", commit):
        raise RuntimeError("Could not resolve a canonical source commit")
    commit = commit.lower()
    sparse_checkout = (
        _git_run(
            repo_root,
            ["config", "--get", "core.sparseCheckout"],
            allowed_returncodes=(0, 1),
        )
        .strip()
        .lower()
    )
    if sparse_checkout in {b"1", b"true", b"yes", b"on"}:
        raise RuntimeError("Frozen validation refuses a sparse checkout")
    _assert_safe_git_configuration(repo_root)
    index_flags = _git_run(repo_root, ["ls-files", "-v", "-z"])
    for entry in filter(None, index_flags.split(b"\0")):
        if len(entry) < 3 or entry[1:2] != b" ":
            raise RuntimeError("Git index metadata is malformed")
        tag = entry[:1]
        if tag == b"S" or tag.islower():
            raise RuntimeError("Frozen validation refuses skip-worktree or assume-unchanged files")
    tracked_clean, tracked_fingerprint = _force_hash_tracked_worktree(repo_root)
    status = _git_run(
        repo_root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    )
    dirty = bool(status) or not tracked_clean
    if dirty and not allow_dirty:
        raise RuntimeError(
            "Frozen release validation requires a clean source tree. "
            "Local engineering checks may call the Python validator directly "
            "with --allow-dirty-validation; that evidence is marked non-release."
        )
    source_state = "dirty-validation" if dirty else "clean"
    fingerprint = hashlib.sha256()
    fingerprint.update(source_state.encode("ascii") + b"\0" + commit.encode("ascii"))
    fingerprint.update(b"\0index-flags\0" + index_flags)
    fingerprint.update(b"\0tracked\0" + tracked_fingerprint.encode("ascii"))
    fingerprint.update(b"\0status\0" + status)
    if dirty:
        diff = _git_run(
            repo_root,
            ["diff", "--binary", "--no-ext-diff", "--no-textconv", "HEAD", "--"],
        )
        fingerprint.update(b"\0diff\0" + diff)
        untracked = _git_run(
            repo_root,
            ["ls-files", "--others", "--exclude-standard", "-z"],
        )
        fingerprint.update(b"\0untracked-list\0" + untracked)
        for encoded_name in filter(None, untracked.split(b"\0")):
            relative_name = os.fsdecode(encoded_name)
            candidate = Path(os.path.abspath(repo_root / relative_name))
            try:
                if os.path.commonpath((expected_root, os.path.normcase(str(candidate)))) != expected_root:
                    raise RuntimeError("Untracked source path escaped the repository")
            except ValueError as exc:
                raise RuntimeError("Untracked source path escaped the repository") from exc
            fingerprint.update(b"\0untracked-file\0" + encoded_name + b"\0")
            file_hash = _sha256(candidate)
            fingerprint.update(file_hash.encode("ascii"))
    return commit, source_state, fingerprint.hexdigest()


def _release_sensitive_environment_names(
    environment: Mapping[str, str],
) -> tuple[str, ...]:
    """Return only canonical override names, never their possibly secret values."""

    return tuple(sorted({name.upper() for name in environment if _is_release_sensitive_environment_name(name)}))


def _is_release_sensitive_environment_name(name: str) -> bool:
    canonical = name.upper()
    if canonical in RELEASE_SENSITIVE_ENVIRONMENT_NAMES:
        return True
    if canonical.startswith(RELEASE_SENSITIVE_ENVIRONMENT_PREFIXES):
        return True
    return bool(
        canonical.startswith("DUPEZ_")
        and not canonical.startswith("DUPEZ_SIGN_")
        and canonical != "DUPEZ_OFFSEC_OPERATOR_KEY"
    )


def _assert_no_release_sensitive_environment(
    environment: Optional[Mapping[str, str]] = None,
) -> None:
    inherited = _release_sensitive_environment_names(os.environ if environment is None else environment)
    if inherited:
        raise RuntimeError(
            "Frozen validation refuses release-sensitive environment overrides. "
            "Unset these names and retry: " + ", ".join(inherited)
        )


def _is_ambient_secret_environment_name(name: str) -> bool:
    """Identify credential-bearing names without inspecting or reporting values."""

    canonical = name.upper()
    if canonical.startswith("DUPEZ_SIGN_"):
        return True
    if canonical in AMBIENT_SECRET_EXACT_NAMES:
        return True
    segments = tuple(segment for segment in canonical.split("_") if segment)
    if any(segment in AMBIENT_SECRET_NAME_SEGMENTS for segment in segments):
        return True
    return any(
        segments[index : index + len(sequence)] == sequence
        for sequence in AMBIENT_SECRET_NAME_SEQUENCES
        for index in range(len(segments) - len(sequence) + 1)
    )


def _validation_environment(
    *,
    runtime_root: Path,
    temp_root: Path,
    profile_environment: Mapping[str, str],
    inherited_environment: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Build a minimal deterministic child environment from trusted values."""

    unexpected = sorted(set(profile_environment) - VALIDATOR_PROFILE_ENVIRONMENT_NAMES)
    if unexpected:
        raise RuntimeError("Validator profile contains unsupported environment names: " + ", ".join(unexpected))

    # ``inherited_environment`` exists for adversarial tests; no parent value
    # is copied. Main separately refuses canonical runtime overrides.
    del inherited_environment
    environment = _windows_system_environment()
    runtime_drive, runtime_tail = os.path.splitdrive(os.path.abspath(runtime_root))
    environment.update(
        {
            "LOCALAPPDATA": str(runtime_root),
            "APPDATA": str(runtime_root),
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
            "TMPDIR": str(temp_root),
            "USERPROFILE": str(runtime_root),
            "HOME": str(runtime_root),
            "HOMEDRIVE": runtime_drive,
            "HOMEPATH": runtime_tail,
            "DUPEZ_RELEASE_VALIDATION": "1",
            **profile_environment,
        }
    )
    return environment


def _windows_system_environment() -> dict[str, str]:
    """Return only OS paths resolved independently of inherited environment."""

    if sys.platform != "win32":
        raise RuntimeError("Frozen child environment requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def directory(function_name: str) -> Path:
        function = getattr(kernel32, function_name)
        function.argtypes = [ctypes.c_wchar_p, wintypes.UINT]
        function.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        written = int(function(buffer, len(buffer)))
        if written == 0 or written >= len(buffer):
            raise RuntimeError("Trusted Windows system directory is unavailable")
        path = Path(os.path.abspath(buffer.value))
        if str(path).startswith("\\\\"):
            raise RuntimeError("Trusted Windows system directory is not local")
        _assert_non_reparse_directories(path, allow_missing=False)
        return path

    windows_directory = directory("GetWindowsDirectoryW")
    system_directory = directory("GetSystemDirectoryW")
    path_entries = (
        system_directory,
        windows_directory,
    )
    command_processor = system_directory / "cmd.exe"
    _assert_regular_non_reparse_file(command_processor)
    return {
        "SystemRoot": str(windows_directory),
        "WINDIR": str(windows_directory),
        "SystemDrive": windows_directory.drive,
        "ComSpec": str(command_processor),
        "OS": "Windows_NT",
        "PATH": os.pathsep.join(str(path) for path in path_entries),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "NUMBER_OF_PROCESSORS": str(max(1, os.cpu_count() or 1)),
    }


def _process_info(process: psutil.Process) -> dict:
    def safe(callable_, default):
        try:
            return callable_()
        except (psutil.Error, OSError):
            return default

    return {
        "pid": process.pid,
        "parent_pid": safe(process.ppid, 0),
        "name": safe(process.name, ""),
    }


def _windows_known_folder(identifier: _Guid, label: str) -> Path:
    if sys.platform != "win32":
        raise RuntimeError(f"Windows {label} is unavailable on this platform")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    get_known_folder = shell32.SHGetKnownFolderPath
    get_known_folder.argtypes = [
        ctypes.POINTER(_Guid),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    get_known_folder.restype = ctypes.c_long
    free_memory = ole32.CoTaskMemFree
    free_memory.argtypes = [ctypes.c_void_p]
    free_memory.restype = None

    path_pointer = ctypes.c_wchar_p()
    result = get_known_folder(
        ctypes.byref(identifier),
        0,
        None,
        ctypes.byref(path_pointer),
    )
    try:
        if result != 0 or not path_pointer.value:
            raise RuntimeError(f"Windows {label} known folder is unavailable")
        rendered = os.path.abspath(path_pointer.value)
        if not os.path.isabs(rendered) or rendered.startswith("\\\\"):
            raise RuntimeError(f"Windows {label} must be a local absolute path")
        return Path(rendered)
    finally:
        if path_pointer:
            free_memory(ctypes.cast(path_pointer, ctypes.c_void_p))


def _windows_local_appdata() -> Path:
    """Resolve LocalAppData through the Windows Known Folder API."""

    return _windows_known_folder(_FOLDERID_LOCAL_APPDATA, "LocalAppData")


def _windows_program_files() -> Path:
    """Resolve Program Files through the Windows Known Folder API."""

    return _windows_known_folder(_FOLDERID_PROGRAM_FILES, "Program Files")


def _assert_non_reparse_directories(path: Path, *, allow_missing: bool) -> None:
    """Reject reparse, non-directory, and inconsistent components."""

    absolute = Path(os.path.abspath(path))
    components: list[Path] = []
    current = absolute
    while True:
        components.append(current)
        if current.parent == current:
            break
        current = current.parent

    missing_parent = False
    for component in reversed(components):
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            if not allow_missing:
                raise RuntimeError("Trusted validation directory is missing") from None
            missing_parent = True
            continue
        if missing_parent:
            raise RuntimeError("Trusted validation path changed during inspection")
        if _is_reparse_stat(metadata):
            raise RuntimeError("Trusted validation path contains a reparse point")
        if not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("Trusted validation path contains a non-directory")


def _windows_current_user_sid() -> str:
    try:
        import win32api
        import win32con
        import win32security

        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_QUERY,
        )
        try:
            sid = win32security.GetTokenInformation(
                token,
                win32security.TokenUser,
            )[0]
            return str(win32security.ConvertSidToStringSid(sid))
        finally:
            close = getattr(token, "Close", None)
            if callable(close):
                close()
    except Exception as exc:
        raise RuntimeError("Current Windows user identity is unavailable") from exc


def _harden_private_directory(path: Path) -> None:
    """Protect a validator-owned leaf from other local non-admin users."""

    if os.name != "nt":
        os.chmod(path, 0o700)
        return
    try:
        import win32security

        descriptor = "D:P" f"(A;;FA;;;{_windows_current_user_sid()})" "(A;;FA;;;SY)" "(A;;FA;;;BA)"
        security_descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            descriptor,
            win32security.SDDL_REVISION_1,
        )
        win32security.SetFileSecurity(
            str(path),
            win32security.DACL_SECURITY_INFORMATION,
            security_descriptor,
        )
    except Exception as exc:
        raise RuntimeError("Private validation directory ACL could not be set") from exc


def _private_directory_permissions_are_restricted(path: Path) -> bool:
    if os.name != "nt":
        try:
            return not bool(stat.S_IMODE(os.lstat(path).st_mode) & 0o077)
        except OSError:
            return False
    try:
        import win32security

        user_sid = _windows_current_user_sid()
        allowed_sids = {
            user_sid,
            "S-1-5-18",  # LocalSystem
            "S-1-5-32-544",  # Builtin Administrators
        }
        descriptor = win32security.GetFileSecurity(
            str(path),
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
        )
        owner = descriptor.GetSecurityDescriptorOwner()
        owner_sid = str(win32security.ConvertSidToStringSid(owner))
        if owner_sid not in {user_sid, "S-1-5-32-544"}:
            return False
        control, _revision = descriptor.GetSecurityDescriptorControl()
        if not int(control) & int(getattr(win32security, "SE_DACL_PROTECTED", 0x1000)):
            return False
        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None:
            return False
        user_access = False
        for index in range(dacl.GetAceCount()):
            ace = dacl.GetAce(index)
            if int(ace[0][0]) != win32security.ACCESS_ALLOWED_ACE_TYPE:
                continue
            mask = int(ace[1])
            sid = str(win32security.ConvertSidToStringSid(ace[2]))
            if mask and sid not in allowed_sids:
                return False
            if mask and sid == user_sid:
                user_access = True
        return user_access
    except Exception:
        return False


def _release_validation_parent() -> Path:
    local_appdata = _windows_local_appdata()
    _assert_non_reparse_directories(local_appdata, allow_missing=False)
    parent = local_appdata
    for leaf in ("DupeZ", "release-validation"):
        parent = parent / leaf
        try:
            parent.mkdir()
        except FileExistsError:
            pass
        _assert_non_reparse_directories(parent, allow_missing=False)
    return parent


def _remove_tree_without_reparse(path: Path) -> None:
    metadata = os.lstat(path)
    if _is_reparse_stat(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("Refusing cleanup through a reparse or non-directory")
    with os.scandir(path) as entries:
        for entry in entries:
            entry_path = Path(entry.path)
            entry_metadata = entry.stat(follow_symlinks=False)
            if _is_reparse_stat(entry_metadata):
                raise RuntimeError("Private validation tree contains a reparse point")
            if stat.S_ISDIR(entry_metadata.st_mode):
                _remove_tree_without_reparse(entry_path)
            elif stat.S_ISREG(entry_metadata.st_mode):
                os.unlink(entry_path)
            else:
                raise RuntimeError("Private validation tree contains a special file")
    os.rmdir(path)


def _private_runtime_root(*, variant: str, profile: str, cycle: int) -> Path:
    """Create a collision-resistant, private runtime tree in LocalAppData."""

    smoke_root = _release_validation_parent()
    created: Optional[Path] = None
    try:
        created = Path(
            tempfile.mkdtemp(
                prefix=f"{variant.lower()}-{profile}-{cycle}-",
                dir=smoke_root,
            )
        )
        _assert_non_reparse_directories(created, allow_missing=False)
        _harden_private_directory(created)
        if not _private_directory_permissions_are_restricted(created):
            raise RuntimeError("Private validation directory ACL is not restricted")
        return created
    except BaseException as creation_error:
        cleanup_error: Optional[BaseException] = None
        if created is not None:
            try:
                _remove_tree_without_reparse(created)
            except BaseException as error:
                cleanup_error = error
        if cleanup_error is not None:
            raise RuntimeError(
                "Private runtime creation failed and cleanup could not be confirmed "
                f"({type(cleanup_error).__name__})"
            ) from creation_error
        raise


def _remove_private_runtime_root(runtime_root: Path) -> None:
    """Remove only one validator-owned, non-reparse child tree."""

    smoke_root = _release_validation_parent()
    lexical = Path(os.path.abspath(runtime_root))
    if lexical.parent != smoke_root:
        raise RuntimeError("Refusing cleanup outside the private smoke root")
    _assert_non_reparse_directories(smoke_root, allow_missing=False)
    try:
        _remove_tree_without_reparse(lexical)
    except FileNotFoundError:
        return
    try:
        os.lstat(lexical)
    except FileNotFoundError:
        return
    raise RuntimeError("Private frozen-runtime cleanup was not confirmed")


def _matching_dupez_processes() -> list[psutil.Process]:
    matches: list[psutil.Process] = []
    for process in psutil.process_iter(("pid", "name")):
        try:
            name = str(process.info.get("name") or "").lower()
        except (psutil.Error, OSError):
            continue
        if name in DUPEZ_PROCESS_NAMES:
            matches.append(process)
    return matches


def _assert_clean_process_baseline() -> None:
    running = _matching_dupez_processes()
    if running:
        detail = json.dumps([_process_info(item) for item in running], indent=2)
        raise RuntimeError(
            "Close every DupeZ GPU/Compat/installed session before frozen " f"validation. Active processes:\n{detail}"
        )


def _tree(root_pid: int) -> list[psutil.Process]:
    try:
        root = psutil.Process(root_pid)
    except psutil.NoSuchProcess:
        return []
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except (psutil.Error, OSError):
        pass
    unique: dict[int, psutil.Process] = {item.pid: item for item in processes}
    return list(unique.values())


ProcessIdentity = tuple[int, float]


def _process_identity(process: psutil.Process) -> ProcessIdentity:
    try:
        return process.pid, float(process.create_time())
    except (psutil.Error, OSError) as exc:
        raise RuntimeError("Started process identity could not be captured") from exc


def _remember_process_tree(
    root_pid: int,
    identities: set[ProcessIdentity],
) -> list[psutil.Process]:
    processes = _tree(root_pid)
    for process in processes:
        identities.add(_process_identity(process))
    return processes


def _identity_process(identity: ProcessIdentity) -> Optional[psutil.Process]:
    pid, created = identity
    try:
        process = psutil.Process(pid)
        if abs(float(process.create_time()) - created) >= 0.001:
            return None
        if not process.is_running():
            return None
        return process
    except psutil.NoSuchProcess:
        return None
    except (psutil.AccessDenied, OSError):
        return psutil.Process(pid) if psutil.pid_exists(pid) else None


def _wait_for_process_identities_gone(
    identities: Iterable[ProcessIdentity],
    *,
    timeout: float,
) -> None:
    pending = set(identities)
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        pending = {identity for identity in pending if _identity_process(identity) is not None}
        if pending:
            time.sleep(0.1)
    if pending:
        raise RuntimeError("Frozen shutdown leaked processes from the started family " f"(count={len(pending)})")


def _matching_webengine_identities() -> set[ProcessIdentity]:
    identities: set[ProcessIdentity] = set()
    for process in psutil.process_iter(("pid", "name")):
        try:
            name = str(process.info.get("name") or "").lower()
            if name in WEBENGINE_PROCESS_NAMES:
                identities.add(_process_identity(process))
        except (RuntimeError, psutil.Error, OSError):
            continue
    return identities


def _baseline_webengine_identities() -> set[ProcessIdentity]:
    """Allow unrelated Qt apps but reject stale DupeZ validation helpers."""

    dupez_local_root = Path(os.path.abspath(_windows_local_appdata() / "DupeZ"))
    normalized_root = os.path.normcase(str(dupez_local_root))
    identities: set[ProcessIdentity] = set()
    for process in psutil.process_iter(("pid", "name")):
        try:
            name = str(process.info.get("name") or "").lower()
            if name not in WEBENGINE_PROCESS_NAMES:
                continue
            identity = _process_identity(process)
            executable = os.path.normcase(os.path.abspath(process.exe()))
            try:
                is_dupez_local = os.path.commonpath((normalized_root, executable)) == normalized_root
            except ValueError:
                is_dupez_local = False
            if is_dupez_local:
                raise RuntimeError("Close stale DupeZ QtWebEngine helpers before validation")
            identities.add(identity)
        except RuntimeError:
            raise
        except (psutil.Error, OSError) as exc:
            raise RuntimeError("A pre-existing QtWebEngine helper could not be classified") from exc
    return identities


def _wait_for_no_new_webengine_processes(
    baseline: set[ProcessIdentity],
    *,
    timeout: float = 15.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        leaked = _matching_webengine_identities() - baseline
        if not leaked:
            return
        time.sleep(0.25)
    leaked = _matching_webengine_identities() - baseline
    if leaked:
        raise RuntimeError("Frozen shutdown leaked new QtWebEngine helper processes " f"(count={len(leaked)})")


def _enum_dashboard(process_ids: set[int]) -> tuple[int, int]:
    if not process_ids:
        return 0, 0

    found_hwnd = 0
    found_pid = 0
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        nonlocal found_hwnd, found_pid
        owner = wintypes.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        pid = int(owner.value)
        if pid not in process_ids or not USER32.IsWindowVisible(hwnd):
            return True
        length = int(USER32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(max(length + 1, 64))
        USER32.GetWindowTextW(hwnd, buffer, len(buffer))
        if "dupez v" in buffer.value.lower():
            found_hwnd = int(hwnd)
            found_pid = pid
            return False
        return True

    callback_ref = enum_proc_type(callback)
    USER32.EnumWindows(callback_ref, 0)
    return found_hwnd, found_pid


def _find_dashboard(root_pid: int) -> tuple[int, int, list[psutil.Process]]:
    processes = _tree(root_pid)
    hwnd, owner_pid = _enum_dashboard({item.pid for item in processes})
    return hwnd, owner_pid, processes


def _wait_for_dashboard(root_pid: int, timeout: float) -> tuple[int, int, list[psutil.Process]]:
    """Bind to the current dashboard HWND, which Qt may recreate at runtime."""

    deadline = time.monotonic() + timeout
    last_processes: list[psutil.Process] = []
    while time.monotonic() < deadline:
        hwnd, owner_pid, last_processes = _find_dashboard(root_pid)
        if hwnd:
            return hwnd, owner_pid, last_processes
        time.sleep(0.1)
    return 0, 0, last_processes


def _foreground_dashboard(hwnd: int, timeout: float = 2.0) -> bool:
    """Activate the exact dashboard across the documented input-queue boundary."""

    USER32.ShowWindow(hwnd, 9)  # SW_RESTORE
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        foreground = int(USER32.GetForegroundWindow() or 0)
        if foreground == hwnd:
            return True

        current_thread = int(KERNEL32.GetCurrentThreadId())
        target_thread = int(USER32.GetWindowThreadProcessId(hwnd, None))
        foreground_thread = int(USER32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
        attached: list[int] = []
        for thread_id in (foreground_thread, target_thread):
            if (
                thread_id
                and thread_id != current_thread
                and thread_id not in attached
                and USER32.AttachThreadInput(current_thread, thread_id, True)
            ):
                attached.append(thread_id)
        try:
            USER32.BringWindowToTop(hwnd)
            USER32.SetForegroundWindow(hwnd)
            USER32.SetActiveWindow(hwnd)
            USER32.SetFocus(hwnd)
        finally:
            for thread_id in reversed(attached):
                USER32.AttachThreadInput(current_thread, thread_id, False)
        time.sleep(0.05)
    return int(USER32.GetForegroundWindow() or 0) == hwnd


def _send_ctrl_key(hwnd: int, virtual_key: int) -> None:
    """Send one real shortcut only after the exact dashboard is foreground."""

    if not hwnd or not USER32.IsWindow(hwnd):
        raise RuntimeError("The exact DupeZ dashboard HWND is no longer valid")
    if not _foreground_dashboard(hwnd):
        raise RuntimeError("Could not foreground the exact DupeZ dashboard")

    inputs = (INPUT * 4)(
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_CONTROL, 0, 0, 0, 0)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(virtual_key, 0, 0, 0, 0)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(virtual_key, 0, KEYEVENTF_KEYUP, 0, 0)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0)),
    )
    ctypes.set_last_error(0)
    input_size = ctypes.sizeof(INPUT)
    sent = int(USER32.SendInput(len(inputs), inputs, input_size))
    if sent != len(inputs):
        error = ctypes.get_last_error()
        raise RuntimeError(
            f"SendInput accepted {sent}/{len(inputs)} keyboard events "
            f"(GetLastError={error}, sizeof(INPUT)={input_size})"
        )


LogFileIdentity = tuple[int, int]
LogCursor = dict[str, tuple[LogFileIdentity, int]]


def _regular_files_beneath(root: Path) -> list[Path]:
    try:
        metadata = os.lstat(root)
    except FileNotFoundError:
        return []
    if _is_reparse_stat(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("Validation runtime contains an unsafe directory")
    files: list[Path] = []
    with os.scandir(root) as entries:
        for entry in entries:
            path = Path(entry.path)
            entry_metadata = entry.stat(follow_symlinks=False)
            if _is_reparse_stat(entry_metadata):
                raise RuntimeError("Validation runtime contains a reparse point")
            if stat.S_ISDIR(entry_metadata.st_mode):
                files.extend(_regular_files_beneath(path))
            elif stat.S_ISREG(entry_metadata.st_mode):
                files.append(path)
            else:
                raise RuntimeError("Validation runtime contains a special file")
    return files


def _log_snapshot(runtime_root: Path) -> tuple[str, LogCursor]:
    """Read the current logs and return stable per-file byte offsets."""

    log_root = runtime_root / "DupeZ" / "logs"
    parts: list[str] = []
    cursor: LogCursor = {}
    paths = sorted(
        _regular_files_beneath(log_root),
        key=lambda item: item.relative_to(log_root).as_posix().casefold(),
    )
    for path in paths:
        try:
            path_metadata = os.lstat(path)
            if int(path_metadata.st_nlink) != 1:
                raise RuntimeError("Validation log is hard-linked")
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                path_identity = (int(path_metadata.st_dev), int(path_metadata.st_ino))
                opened_identity = (int(opened.st_dev), int(opened.st_ino))
                if path_identity != opened_identity:
                    raise RuntimeError("Validation log changed before it was opened")
                payload = handle.read()
                offset = handle.tell()
                finished = os.fstat(handle.fileno())
        except OSError:
            continue
        finished_identity = (int(finished.st_dev), int(finished.st_ino))
        if finished_identity != opened_identity:
            raise RuntimeError("Validation log identity changed while it was read")
        relative = path.relative_to(log_root).as_posix()
        cursor[relative] = (opened_identity, offset)
        parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts), cursor


def _log_text(runtime_root: Path) -> str:
    return _log_snapshot(runtime_root)[0]


def _log_text_since(runtime_root: Path, cursor: LogCursor) -> str:
    """Read only bytes appended after ``cursor``, including newly created logs."""

    log_root = runtime_root / "DupeZ" / "logs"
    parts: list[str] = []
    prior_offsets = {identity: offset for identity, offset in cursor.values()}
    paths = sorted(
        _regular_files_beneath(log_root),
        key=lambda item: item.relative_to(log_root).as_posix().casefold(),
    )
    for path in paths:
        relative = path.relative_to(log_root).as_posix()
        try:
            path_metadata = os.lstat(path)
            if int(path_metadata.st_nlink) != 1:
                raise RuntimeError("Validation log is hard-linked")
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                path_identity = (
                    int(path_metadata.st_dev),
                    int(path_metadata.st_ino),
                )
                opened_identity = (int(opened.st_dev), int(opened.st_ino))
                if path_identity != opened_identity:
                    raise RuntimeError("Validation log changed before it was opened")
                same_path = cursor.get(relative)
                if same_path is not None and same_path[0] == opened_identity:
                    offset = int(same_path[1])
                else:
                    offset = int(prior_offsets.get(opened_identity, 0))
                if offset < 0 or offset > int(opened.st_size):
                    raise RuntimeError("Validation log was truncated after the action cursor")
                handle.seek(offset)
                payload = handle.read()
                finished = os.fstat(handle.fileno())
        except OSError:
            continue
        finished_identity = (int(finished.st_dev), int(finished.st_ino))
        if finished_identity != opened_identity:
            raise RuntimeError("Validation log identity changed while it was read")
        parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def _map_failure_marker(text: str) -> Optional[str]:
    lowered = text.casefold()
    for marker in MAP_FAILURE_MARKERS:
        if marker.casefold() in lowered:
            return marker
    return None


def _raise_for_map_failure(text: str) -> None:
    marker = _map_failure_marker(text)
    if marker:
        raise RuntimeError("Frozen Map/WebEngine failure marker observed: " + marker)


def _wait_for_post_action_map_ready(
    runtime_root: Path,
    cursor: LogCursor,
    *,
    initialized_before_action: bool,
    load_finished_before_action: bool,
    timeout: int,
) -> str:
    """Require real WebEngine readiness and a Map activation after Ctrl+2."""

    initialized = initialized_before_action
    load_finished = load_finished_before_action
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        suffix = _log_text_since(runtime_root, cursor)
        _raise_for_map_failure(suffix)
        initialized = initialized or WEBENGINE_INITIALIZED_SIGNAL in suffix
        load_finished = load_finished or MAP_LOAD_FINISHED_SIGNAL in suffix
        dashboard_active = MAP_DASHBOARD_ACTIVE_SIGNAL in suffix
        if initialized and load_finished and dashboard_active:
            return MAP_DASHBOARD_ACTIVE_SIGNAL
        time.sleep(0.25)

    missing: list[str] = []
    if not initialized:
        missing.append(WEBENGINE_INITIALIZED_SIGNAL)
    if not load_finished:
        missing.append(MAP_LOAD_FINISHED_SIGNAL)
    missing.append(MAP_DASHBOARD_ACTIVE_SIGNAL)
    raise RuntimeError("Frozen Map validation did not observe required post-action state: " + ", ".join(missing))


def _assert_post_ready_stability(
    runtime_root: Path,
    cursor: LogCursor,
    *,
    duration: float = MAP_POST_READY_STABILITY_SECONDS,
) -> None:
    """Reject renderer/navigation failures that race immediately after ready."""

    deadline = time.monotonic() + duration
    while True:
        _raise_for_map_failure(_log_text_since(runtime_root, cursor))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def _wait_for_log(runtime_root: Path, patterns: Iterable[str], timeout: int) -> Optional[str]:
    ordered = tuple(patterns)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = _log_text(runtime_root)
        for pattern in ordered:
            if pattern in text:
                return pattern
        time.sleep(0.25)
    return None


def _shutdown_diagnostic_summary(runtime_root: Path) -> str:
    """Return only fixed shutdown-state labels; never copy runtime log text."""

    text = _log_text(runtime_root)
    observed = [
        label
        for label, marker in SHUTDOWN_DIAGNOSTIC_MARKERS
        if marker in text
    ]
    return ",".join(observed) if observed else "no-known-shutdown-signal"


def _write_acknowledgement(runtime_root: Path) -> None:
    target = runtime_root / "DupeZ" / "operator-acknowledgement.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "dupez.operator-acknowledgement.v1",
        "policy_version": 1,
        "acknowledged": True,
        "acknowledged_at": int(time.time()),
    }
    target.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_safety_dry_run_settings(runtime_root: Path) -> None:
    """Seed the shipped fail-closed mode used by GUI/WebEngine validation.

    Frozen lifecycle evidence proves startup, architecture, WebEngine, Map, and
    shutdown behavior. Privileged packet-engine and UAC behavior is covered by
    the separate exact-artifact manual and hardware gates. Using DupeZ's real
    operator-facing dry-run setting keeps this automated lifecycle non-mutating
    and prevents it from blocking on an unattended secure-desktop UAC prompt.
    """

    target = runtime_root / "DupeZ" / "config" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "auto_scan": False,
        "safety_dry_run": True,
    }
    target.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _terminate_started_family(
    root_pid: int,
    known_identities: set[ProcessIdentity],
) -> None:
    try:
        _remember_process_tree(root_pid, known_identities)
    except (RuntimeError, psutil.Error, OSError):
        pass
    candidates: list[psutil.Process] = []
    for identity in known_identities:
        process = _identity_process(identity)
        if process is not None:
            candidates.append(process)
    for process in reversed(candidates):
        try:
            process.terminate()
        except (psutil.Error, OSError):
            continue
    alive = _wait_processes_best_effort(candidates, timeout=3.0)
    for process in alive:
        try:
            process.kill()
        except (psutil.Error, OSError):
            continue
    _wait_processes_best_effort(alive, timeout=3.0)


def _wait_processes_best_effort(processes: Iterable[psutil.Process], timeout: float) -> list[psutil.Process]:
    """Wait for controllable processes without masking the triggering failure.

    A Medium Integrity GPU validator cannot open the elevated helper with the
    rights psutil.wait_procs requires. The helper exits through its parent
    watcher after the GUI is terminated, so an access-denied process is left to
    that boundary instead of replacing the original validation exception.
    """

    pending = list(processes)
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        still_running: list[psutil.Process] = []
        for process in pending:
            try:
                if process.is_running():
                    still_running.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        pending = still_running
        if pending:
            time.sleep(0.1)
    return pending


def _terminate_popen_handle(process: subprocess.Popen, timeout: float = 5.0) -> None:
    """Stop the exact process retained by ``Popen`` and prove its handle exited."""

    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError as exc:
        if process.poll() is None:
            raise RuntimeError("Could not terminate the launched frozen process") from exc
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError as exc:
            if process.poll() is None:
                raise RuntimeError("Could not kill the launched frozen process") from exc
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Launched frozen process did not exit during cleanup") from exc
    if process.poll() is None:
        raise RuntimeError("Launched frozen process cleanup is unconfirmed")


def _wait_for_no_dupez_processes(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _matching_dupez_processes():
            return
        time.sleep(0.25)
    detail = json.dumps([_process_info(item) for item in _matching_dupez_processes()], indent=2)
    raise RuntimeError(f"Frozen shutdown leaked GUI/helper processes:\n{detail}")


def _assert_no_legacy_runtime_inputs(executable_directory: Path) -> None:
    """Prevent frozen migration from importing stale proof into a smoke run."""

    forbidden: list[str] = []
    for relative in (Path("logs"), Path("app/data"), Path("app/config")):
        candidate = executable_directory / relative
        try:
            os.lstat(candidate)
        except FileNotFoundError:
            continue
        forbidden.append(relative.as_posix())
    for candidate in executable_directory.iterdir():
        if candidate.name.upper().startswith("FATAL_CRASH") and candidate.suffix.upper() == ".TXT":
            forbidden.append(candidate.name)
    if forbidden:
        raise RuntimeError(
            "Frozen validation refuses legacy runtime inputs beside the executable: "
            + ", ".join(sorted(forbidden, key=str.casefold))
        )


def _evidence_path(dist_root: Path, variant: str, source_state: str) -> Path:
    suffix = "" if source_state == "clean" else ".dirty-validation"
    return dist_root / f"frozen-runtime-evidence-{variant.lower()}{suffix}.json"


def _invalidate_evidence(path: Path) -> None:
    """Remove one prior evidence leaf without following links or reparses."""

    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return
    if _is_reparse_stat(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("Refusing an unsafe pre-existing evidence path")
    os.unlink(path)
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    raise RuntimeError("Prior frozen-runtime evidence could not be invalidated")


def _atomic_write_evidence(path: Path, evidence: Mapping[str, object]) -> None:
    """Install evidence atomically through an exclusive same-directory file."""

    _assert_non_reparse_directories(path.parent, allow_missing=False)
    try:
        os.lstat(path)
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("Evidence destination unexpectedly reappeared")

    payload = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    staged = Path(staged_name)
    installed = False
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _is_reparse_stat(opened):
            raise RuntimeError("Evidence staging file is unsafe")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("Short evidence write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        _assert_regular_non_reparse_file(staged, require_single_link=True)
        try:
            os.lstat(path)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("Evidence destination changed during write")
        os.replace(staged, path)
        installed = True
        _assert_regular_non_reparse_file(path, require_single_link=True)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not installed:
            try:
                metadata = os.lstat(staged)
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISREG(metadata.st_mode) and not _is_reparse_stat(metadata):
                    os.unlink(staged)


def _assert_release_inputs_unchanged(
    *,
    repo_root: Path,
    executable: Path,
    allow_dirty: bool,
    expected_source: tuple[str, str, str],
    expected_executable: tuple[str, int],
) -> None:
    observed_source = _git_source_identity(
        repo_root,
        allow_dirty=allow_dirty,
    )
    if observed_source != expected_source:
        raise RuntimeError("Source provenance changed during frozen validation")
    observed_hash = _sha256(executable, require_single_link=True)
    observed_size = int(
        _assert_regular_non_reparse_file(
            executable,
            require_single_link=True,
        ).st_size
    )
    if (observed_hash, observed_size) != expected_executable:
        raise RuntimeError("Frozen executable changed during validation")


def _run_profile(
    *,
    variant: str,
    executable: Path,
    executable_hash: str,
    executable_size: int,
    commit: str,
    source_state: str,
    source_fingerprint: str,
    validation_session_id: str,
    profile_name: str,
    profile_environment: dict[str, str],
    cycle: int,
    startup_timeout: int,
    map_timeout: int,
    shutdown_timeout: int,
    is_admin: bool,
) -> dict:
    runtime_root: Optional[Path] = None
    process: Optional[subprocess.Popen] = None
    executable_lock: Optional[BinaryIO] = None
    known_identities: set[ProcessIdentity] = set()
    baseline_webengine_identities: set[ProcessIdentity] = set()
    process_tree_snapshot: list[psutil.Process] = []
    dashboard = 0
    dashboard_owner_pid = 0

    try:
        runtime_root = _private_runtime_root(
            variant=variant,
            profile=profile_name,
            cycle=cycle,
        )
        temp_root = runtime_root / "temp"
        temp_root.mkdir(parents=True, exist_ok=False)
        _assert_non_reparse_directories(temp_root, allow_missing=False)
        _write_acknowledgement(runtime_root)
        _write_safety_dry_run_settings(runtime_root)

        environment = _validation_environment(
            runtime_root=runtime_root,
            temp_root=temp_root,
            profile_environment=profile_environment,
        )
        baseline_webengine_identities = _baseline_webengine_identities()

        print(f"\n=== {variant} / {profile_name} / cycle {cycle} ===", flush=True)
        started_wall = time.time()
        started_mono = time.monotonic()
        executable_lock = _locked_release_executable(
            executable,
            expected_hash=executable_hash,
            expected_size=executable_size,
        )
        process = subprocess.Popen(
            [str(executable)],
            cwd=executable.parent,
            env=environment,
        )
        known_identities.add(_process_identity(psutil.Process(process.pid)))
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            dashboard, dashboard_owner_pid, process_tree_snapshot = _find_dashboard(process.pid)
            known_identities.update(_process_identity(item) for item in process_tree_snapshot)
            if dashboard:
                break
            if process.poll() is not None and len(process_tree_snapshot) <= 1:
                raise RuntimeError(f"{executable.name} exited before dashboard creation with code {process.returncode}")
            time.sleep(0.2)
        if not dashboard:
            raise RuntimeError(f"{executable.name} did not create its dashboard within {startup_timeout} seconds")

        if not _wait_for_log(runtime_root, ("DupeZ started successfully",), 20):
            raise RuntimeError("Dashboard appeared but successful-start log was not observed")

        if not _wait_for_log(runtime_root, (NETWORK_VALIDATION_SIGNAL,), 5):
            raise RuntimeError(
                "Frozen GUI did not prove the required production safety dry-run mode"
            )

        architecture_signal = (
            "Architecture: split | Admin: False" if variant == "GPU" else "Architecture: inproc | Admin: True"
        )
        if not _wait_for_log(runtime_root, (architecture_signal,), 5):
            raise RuntimeError("Frozen GUI did not report the required architecture/token boundary")

        dashboard, dashboard_owner_pid, process_tree_snapshot = _wait_for_dashboard(process.pid, 5.0)
        known_identities.update(_process_identity(item) for item in process_tree_snapshot)
        if not dashboard:
            raise RuntimeError("The DupeZ dashboard disappeared after startup")

        try:
            gui_process = psutil.Process(dashboard_owner_pid)
            gui_working_set = int(gui_process.memory_info().rss)
        except (psutil.Error, OSError) as exc:
            raise RuntimeError("Dashboard-owning process disappeared unexpectedly") from exc

        startup_duration_ms = int((time.monotonic() - started_mono) * 1000)
        pre_action_text, log_cursor = _log_snapshot(runtime_root)
        _raise_for_map_failure(pre_action_text)
        initialized_before_action = WEBENGINE_INITIALIZED_SIGNAL in pre_action_text
        load_finished_before_action = MAP_LOAD_FINISHED_SIGNAL in pre_action_text
        _send_ctrl_key(dashboard, 0x32)  # Ctrl+2: Map
        map_result = _wait_for_post_action_map_ready(
            runtime_root,
            log_cursor,
            initialized_before_action=initialized_before_action,
            load_finished_before_action=load_finished_before_action,
            timeout=map_timeout,
        )
        _assert_post_ready_stability(runtime_root, log_cursor)

        dashboard, dashboard_owner_pid, process_tree_snapshot = _wait_for_dashboard(process.pid, 5.0)
        known_identities.update(_process_identity(item) for item in process_tree_snapshot)
        if not dashboard:
            raise RuntimeError("The DupeZ dashboard disappeared after Map initialization")

        process_tree_snapshot = _remember_process_tree(
            process.pid,
            known_identities,
        )
        process_names_observed = sorted(
            {
                str(_process_info(item).get("name") or "")
                for item in process_tree_snapshot
                if str(_process_info(item).get("name") or "")
            }
        )
        webengine_helper_observed = any(name.casefold() in WEBENGINE_PROCESS_NAMES for name in process_names_observed)
        if not webengine_helper_observed:
            raise RuntimeError("Frozen Map readiness lacked a QtWebEngine process descendant")
        _raise_for_map_failure(_log_text_since(runtime_root, log_cursor))
        _send_ctrl_key(dashboard, 0x51)  # Ctrl+Q: DupeZ force-quit path
        try:
            exit_code = process.wait(timeout=shutdown_timeout)
        except subprocess.TimeoutExpired as exc:
            diagnostic = _shutdown_diagnostic_summary(runtime_root)
            raise RuntimeError(
                f"{executable.name} did not complete normal force-quit in time "
                f"(signals={diagnostic})"
            ) from exc
        if exit_code != 0:
            raise RuntimeError(f"{executable.name} exited with code {exit_code}")
        _wait_for_process_identities_gone(
            known_identities,
            timeout=15.0,
        )
        _wait_for_no_new_webengine_processes(baseline_webengine_identities)
        _wait_for_no_dupez_processes()

        crash_files = [
            path
            for path in _regular_files_beneath(runtime_root)
            if (path.name.casefold().startswith("fatal_crash") and path.suffix.casefold() == ".txt")
            or path.suffix.casefold() == ".dmp"
        ]
        if crash_files:
            raise RuntimeError("Frozen run produced crash evidence")

        record = {
            "variant": variant,
            "profile": profile_name,
            "cycle": cycle,
            "executable": executable.name,
            "executable_sha256": executable_hash,
            "commit": commit,
            "source_state": source_state,
            "source_fingerprint": source_fingerprint,
            "validation_session_id": validation_session_id,
            "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_wall)),
            "startup_duration_ms": startup_duration_ms,
            "architecture_observed": architecture_signal,
            "network_validation_mode": NETWORK_VALIDATION_MODE,
            "launched_from_admin": is_admin,
            "working_set_bytes": gui_working_set,
            "process_names_observed": process_names_observed,
            "webengine_helper_observed": webengine_helper_observed,
            "map_result": map_result,
            "clean_exit": True,
            "exit_code": exit_code,
            "crash_files": [],
        }
    except BaseException as validation_error:
        cleanup_errors: list[BaseException] = []
        safe_to_remove_runtime = process is None
        if process is not None:
            root_process_exited = False
            identities_gone = False
            no_dupez_processes = False
            no_new_webengine_processes = False
            try:
                _terminate_started_family(process.pid, known_identities)
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            try:
                _terminate_popen_handle(process)
                root_process_exited = True
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            try:
                _wait_for_process_identities_gone(
                    known_identities,
                    timeout=10.0,
                )
                identities_gone = True
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            try:
                _wait_for_no_dupez_processes(timeout=10.0)
                no_dupez_processes = True
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            try:
                _wait_for_no_new_webengine_processes(
                    baseline_webengine_identities,
                    timeout=10.0,
                )
                no_new_webengine_processes = True
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
            safe_to_remove_runtime = (
                root_process_exited and identities_gone and no_dupez_processes and no_new_webengine_processes
            )
        if executable_lock is not None:
            try:
                executable_lock.close()
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        if runtime_root is not None and safe_to_remove_runtime:
            try:
                _remove_private_runtime_root(runtime_root)
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        elif runtime_root is not None:
            cleanup_errors.append(RuntimeError("Process cleanup is unconfirmed; private root retained"))
        if cleanup_errors:
            error_kinds = ", ".join(sorted({type(error).__name__ for error in cleanup_errors}))
            raise RuntimeError(
                "Frozen validation failed and cleanup could not be confirmed " f"({error_kinds})"
            ) from validation_error
        raise
    try:
        if executable_lock is not None:
            executable_lock.close()
        _remove_private_runtime_root(runtime_root)
    except BaseException as cleanup_error:
        raise RuntimeError("Frozen run passed but private runtime cleanup could not be confirmed") from cleanup_error
    return record


def main() -> int:
    args = _parse_args()
    if sys.platform != "win32":
        raise RuntimeError("Frozen lifecycle validation requires Windows")

    is_admin = _is_admin()
    if args.variant == "GPU" and is_admin:
        raise RuntimeError("GPU validation must run from a standard, non-Administrator desktop session")
    if args.variant == "Compat" and not is_admin:
        raise RuntimeError("Compat validation must run from Administrator PowerShell")

    _assert_no_release_sensitive_environment()
    _assert_no_git_override_environment()

    repo_root = Path(os.path.abspath(Path(__file__).resolve().parents[1]))
    dist_root = Path(os.path.abspath(repo_root / args.dist_directory))
    try:
        if os.path.commonpath((repo_root, dist_root)) != str(repo_root):
            raise ValueError
    except ValueError:
        raise RuntimeError("Frozen validation dist directory must be in the repository")
    _assert_non_reparse_directories(dist_root, allow_missing=False)
    executable = dist_root / ("DupeZ-GPU.exe" if args.variant == "GPU" else "DupeZ-Compat.exe")
    executable_metadata = _assert_regular_non_reparse_file(
        executable,
        require_single_link=True,
    )
    _assert_no_legacy_runtime_inputs(executable.parent)

    commit, source_state, source_fingerprint = _git_source_identity(
        repo_root,
        allow_dirty=args.allow_dirty_validation,
    )
    evidence_path = _evidence_path(dist_root, args.variant, source_state)
    _invalidate_evidence(evidence_path)
    _assert_clean_process_baseline()
    executable_hash = _sha256(executable, require_single_link=True)
    executable_size = int(executable_metadata.st_size)
    profiles = (
        (
            "normal",
            {
                "DUPEZ_LOW_RESOURCE": "0",
                "DUPEZ_MAP_PREWARM": "1",
                "DUPEZ_STARTUP_TIMEOUT_MS": "180000",
            },
        ),
        (
            "forced-low-resource",
            {
                "DUPEZ_LOW_RESOURCE": "1",
                "DUPEZ_MAP_PREWARM": "0",
                "DUPEZ_QT_MAX_THREADS": "2",
                "DUPEZ_STARTUP_TIMEOUT_MS": "240000",
            },
        ),
    )

    records: list[dict] = []
    validation_session_id = str(uuid.uuid4())
    for profile_name, profile_environment in profiles:
        for cycle in range(1, args.cycles_per_profile + 1):
            record = _run_profile(
                variant=args.variant,
                executable=executable,
                executable_hash=executable_hash,
                executable_size=executable_size,
                commit=commit,
                source_state=source_state,
                source_fingerprint=source_fingerprint,
                validation_session_id=validation_session_id,
                profile_name=profile_name,
                profile_environment=profile_environment,
                cycle=cycle,
                startup_timeout=args.startup_timeout,
                map_timeout=args.map_timeout,
                shutdown_timeout=args.shutdown_timeout,
                is_admin=is_admin,
            )
            records.append(record)
            print(
                f"{args.variant} {profile_name} cycle {cycle}: PASS",
                flush=True,
            )
            _assert_clean_process_baseline()

    _assert_release_inputs_unchanged(
        repo_root=repo_root,
        executable=executable,
        allow_dirty=args.allow_dirty_validation,
        expected_source=(commit, source_state, source_fingerprint),
        expected_executable=(executable_hash, executable_size),
    )

    evidence = {
        "schema": SCHEMA,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "variant": args.variant,
        "executable": executable.name,
        "executable_sha256": executable_hash,
        "commit": commit,
        "source_state": source_state,
        "source_fingerprint": source_fingerprint,
        "cycles_per_profile": args.cycles_per_profile,
        "network_validation_mode": NETWORK_VALIDATION_MODE,
        "validation_session_id": validation_session_id,
        "validation_host": {
            "administrator": is_admin,
            "python": sys.version.split()[0],
        },
        "runs": records,
    }
    _atomic_write_evidence(evidence_path, evidence)
    print(f"\nFROZEN {args.variant} RUNTIME VALIDATION: PASS", flush=True)
    print(f"Evidence: {evidence_path.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
