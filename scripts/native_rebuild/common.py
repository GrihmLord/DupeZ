"""Local native-build helpers: pinned inputs, held file handles and closed processes."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import stat
from scripts.native_rebuild import process

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/native-compilation-20261124"
TOOLCHAIN = BASE / "toolchain/llvm-mingw-20261117-ucrt-x86_64"
INVENTORY = BASE / "toolchain-inventory.json"
INVENTORY_PIN = (2125303, "b1fe9bc2406e7467aa6de0d0e9428663a296801cc916e26db6278ccffc945d9e")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ordinary(path: Path, *, missing=False) -> Path:
    path = Path(os.path.abspath(path))
    require(path.is_relative_to(ROOT), "Path outside workspace")
    for part in (*reversed(path.parents), path):
        if missing and not os.path.lexists(part):
            continue
        meta = part.lstat()
        require(not stat.S_ISLNK(meta.st_mode) and not getattr(meta, "st_file_attributes", 0) & 0x400,
                "Links/reparse points are not build inputs")
        require(stat.S_ISDIR(meta.st_mode) or (part == path and stat.S_ISREG(meta.st_mode)), "Unexpected path type")
        if stat.S_ISREG(meta.st_mode):
            require(meta.st_nlink == 1, "Hardlinked inputs are not accepted")
    return path


def pin(path: Path) -> dict:
    path = ordinary(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)
    require(identity(before) == identity(after) == identity(ordinary(path).stat()), "Input changed during hashing")
    return {"path": path.relative_to(ROOT).as_posix(), "size": after.st_size, "sha256": digest}


def toolchain_rows() -> list[dict]:
    with ordinary(INVENTORY).open("rb") as stream:
        raw = stream.read(INVENTORY_PIN[0] + 1)
    require((len(raw), hashlib.sha256(raw).hexdigest()) == INVENTORY_PIN, "Toolchain inventory changed")
    rows = json.loads(raw)
    require(len(rows) == 9069 and len({row["path"] for row in rows}) == len(rows), "Toolchain inventory differs")
    require(all((ROOT / row["path"]).is_relative_to(TOOLCHAIN) for row in rows), "Toolchain inventory escaped root")
    return rows


def verify_toolchain_tree(rows: list[dict]) -> None:
    expected = {row["path"] for row in rows}
    observed = set()
    for directory, dirs, files in os.walk(ordinary(TOOLCHAIN), followlinks=False):
        for name in dirs:
            ordinary(Path(directory) / name)
        for name in files:
            observed.add(ordinary(Path(directory) / name).relative_to(ROOT).as_posix())
    require(observed == expected, "Toolchain tree has missing or unexpected files")


@contextmanager
def held_file(row: dict):
    """Deny writes/deletion through use without consuming one CRT fd per held file."""
    require(os.name == "nt", "Native compiler proof requires Windows")
    path = ordinary(ROOT / row["path"])
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80 | 0x00200000, None)
    require(handle not in (None, ctypes.c_void_p(-1).value), "Input could not be locked")
    try:
        require(kernel.GetFileType(handle) == 1, "Input lock is not a disk file")
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        require(0 < length < len(buffer), "Input lock path unavailable")
        final = buffer.value
        if final.startswith("\\\\?\\"):
            final = final[4:]
        require(os.path.normcase(os.path.normpath(final)) == os.path.normcase(str(path)), "Input lock resolved elsewhere")
        require(pin(path) == row, "Locked input pin differs")
        yield path
        require(pin(path) == row, "Locked input changed")
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def held_inputs(extra: list[dict]):
    require(not ctypes.windll.shell32.IsUserAnAdmin(), "Use a standard Windows token")
    inventory = toolchain_rows()
    verify_toolchain_tree(inventory)
    merged = {}
    inventory_pin = {"path": INVENTORY.relative_to(ROOT).as_posix(), "size": INVENTORY_PIN[0], "sha256": INVENTORY_PIN[1]}
    for row in [*inventory, inventory_pin, pin(Path(__file__)), pin(Path(process.__file__)), *extra]:
        require(merged.setdefault(row["path"], row) == row, "Conflicting input pins")
    with ExitStack() as stack:
        for row in merged.values():
            stack.enter_context(held_file(row))
        yield list(merged.values())
        verify_toolchain_tree(inventory)


def closed_environment(private: Path) -> dict[str, str]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    folders = []
    for name in ("GetWindowsDirectoryW", "GetSystemDirectoryW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        function.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(buffer, len(buffer))
        require(0 < length < len(buffer), "Windows directory unavailable")
        folders.append(Path(buffer.value))
    windows, system = folders
    profile, temp = ordinary(private / "profile", missing=True), ordinary(private / "temp", missing=True)
    profile.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    return {"SystemRoot": str(windows), "WINDIR": str(windows), "SystemDrive": windows.drive,
            "ComSpec": str(system / "cmd.exe"), "PATH": os.pathsep.join([str(TOOLCHAIN / "bin"), str(system), str(windows)]),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD", "OS": "Windows_NT", "TEMP": str(temp), "TMP": str(temp),
            "TMPDIR": str(temp), "USERPROFILE": str(profile), "HOME": str(profile), "LOCALAPPDATA": str(profile),
            "APPDATA": str(profile), "PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": os.devnull,
            "SOURCE_DATE_EPOCH": "0", "ZERO_AR_DATE": "1"}


def run_tool(name: str, arguments: list[str], *, cwd: Path, env: dict, log: Path, timeout=120) -> dict:
    """Run inside held_inputs; caller owns the separately reviewed compile arguments."""
    require(name in {"x86_64-w64-mingw32-clang.exe", "x86_64-w64-mingw32-clang++.exe",
                     "x86_64-w64-mingw32-windres.exe", "llvm-ar.exe", "llvm-readobj.exe"}, "Unreviewed tool")
    executable = ordinary(TOOLCHAIN / "bin" / name)
    ordinary(cwd)
    ordinary(log, missing=True)
    arguments = [str(value) for value in arguments]
    if name.endswith(("clang.exe", "clang++.exe")) and "--no-default-config" not in arguments:
        arguments.insert(0, "--no-default-config")
    command = [str(executable), *arguments]
    with log.open("xb") as stream:
        exit_code = process.run_owned(command, cwd=cwd, env=env, stdout=stream, timeout=timeout)
    normalize = lambda value: value.replace(str(ROOT), "<workspace>").replace("\\", "/")
    return {"command": [normalize(value) for value in command], "cwd": cwd.relative_to(ROOT).as_posix(),
            "exit_code": exit_code, "log": pin(log),
            "process_ownership": {"launch_suspended": True, "job_assigned_before_resume": True,
                                  "inherited_handles": "log-only", "active_processes_after_cleanup": 0}}
