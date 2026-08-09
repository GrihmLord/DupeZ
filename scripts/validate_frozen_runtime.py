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
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterable, Optional

import psutil

SCHEMA = "dupez.frozen-runtime-validation.v1"
DUPEZ_PROCESS_NAMES = frozenset({"dupez-gpu.exe", "dupez-compat.exe", "dupez.exe"})
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_CONTROL = 0x11
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
ULONG_PTR = wintypes.WPARAM


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or not commit:
        raise RuntimeError("Could not resolve the source commit")
    return commit


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
        "command_line": safe(process.cmdline, []),
    }


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
            "Close every DupeZ GPU/Compat/installed session before frozen "
            f"validation. Active processes:\n{detail}"
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


def _wait_for_dashboard(
    root_pid: int, timeout: float
) -> tuple[int, int, list[psutil.Process]]:
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
        foreground_thread = (
            int(USER32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
        )
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


def _log_text(runtime_root: Path) -> str:
    log_root = runtime_root / "DupeZ" / "logs"
    if not log_root.is_dir():
        return ""
    parts: list[str] = []
    for path in sorted(log_root.rglob("*"), key=lambda item: item.stat().st_mtime_ns):
        if not path.is_file():
            continue
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


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


def _terminate_started_family(root_pid: int, known_pids: set[int]) -> None:
    for item in _tree(root_pid):
        known_pids.add(item.pid)
    candidates: list[psutil.Process] = []
    for pid in known_pids:
        try:
            candidates.append(psutil.Process(pid))
        except psutil.NoSuchProcess:
            continue
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


def _wait_processes_best_effort(
    processes: Iterable[psutil.Process], timeout: float
) -> list[psutil.Process]:
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


def _wait_for_no_dupez_processes(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _matching_dupez_processes():
            return
        time.sleep(0.25)
    detail = json.dumps([_process_info(item) for item in _matching_dupez_processes()], indent=2)
    raise RuntimeError(f"Frozen shutdown leaked GUI/helper processes:\n{detail}")


def _run_profile(
    *,
    variant: str,
    executable: Path,
    executable_hash: str,
    commit: str,
    profile_name: str,
    profile_environment: dict[str, str],
    cycle: int,
    startup_timeout: int,
    map_timeout: int,
    shutdown_timeout: int,
    is_admin: bool,
) -> dict:
    run_id = f"{variant.lower()}-{profile_name}-{cycle}-{time.time_ns()}"
    runtime_root = Path(tempfile.gettempdir()) / "dupez-release-smoke" / run_id
    shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    temp_root = runtime_root / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    _write_acknowledgement(runtime_root)

    environment = os.environ.copy()
    environment.update(
        {
            "LOCALAPPDATA": str(runtime_root),
            "APPDATA": str(runtime_root),
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
            "DUPEZ_RELEASE_VALIDATION": "1",
            **profile_environment,
        }
    )

    print(f"\n=== {variant} / {profile_name} / cycle {cycle} ===", flush=True)
    started_wall = time.time()
    started_mono = time.monotonic()
    process = subprocess.Popen([str(executable)], cwd=executable.parent, env=environment)
    known_pids: set[int] = {process.pid}
    process_tree_snapshot: list[psutil.Process] = []
    dashboard = 0
    dashboard_owner_pid = 0

    try:
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            dashboard, dashboard_owner_pid, process_tree_snapshot = _find_dashboard(process.pid)
            known_pids.update(item.pid for item in process_tree_snapshot)
            if dashboard:
                break
            if process.poll() is not None and len(process_tree_snapshot) <= 1:
                raise RuntimeError(
                    f"{executable.name} exited before dashboard creation with code {process.returncode}"
                )
            time.sleep(0.2)
        if not dashboard:
            raise RuntimeError(
                f"{executable.name} did not create its dashboard within {startup_timeout} seconds"
            )

        if not _wait_for_log(runtime_root, ("DupeZ started successfully",), 20):
            raise RuntimeError("Dashboard appeared but successful-start log was not observed")

        dashboard, dashboard_owner_pid, process_tree_snapshot = _wait_for_dashboard(
            process.pid, 5.0
        )
        known_pids.update(item.pid for item in process_tree_snapshot)
        if not dashboard:
            raise RuntimeError("The DupeZ dashboard disappeared after startup")

        try:
            gui_process = psutil.Process(dashboard_owner_pid)
            gui_working_set = int(gui_process.memory_info().rss)
        except (psutil.Error, OSError) as exc:
            raise RuntimeError("Dashboard-owning process disappeared unexpectedly") from exc

        startup_duration_ms = int((time.monotonic() - started_mono) * 1000)
        _send_ctrl_key(dashboard, 0x32)  # Ctrl+2: Map

        map_patterns = (
            (
                "Map: lazy DayZMapGUI initialized on first tab open",
                "Lazy map initialization failed",
            )
            if profile_name == "forced-low-resource"
            else (
                "Map: prewarmed DayZMapGUI after controller startup",
                "Map: lazy DayZMapGUI initialized on first tab open",
                "Lazy map initialization failed",
            )
        )
        map_result = _wait_for_log(runtime_root, map_patterns, map_timeout)
        if not map_result:
            raise RuntimeError("No map initialization result was observed")
        if map_result == "Lazy map initialization failed":
            raise RuntimeError(f"The real frozen Map failed; inspect {runtime_root}")

        dashboard, dashboard_owner_pid, process_tree_snapshot = _wait_for_dashboard(
            process.pid, 5.0
        )
        known_pids.update(item.pid for item in process_tree_snapshot)
        if not dashboard:
            raise RuntimeError("The DupeZ dashboard disappeared after Map initialization")

        _send_ctrl_key(dashboard, 0x51)  # Ctrl+Q: DupeZ force-quit path
        try:
            exit_code = process.wait(timeout=shutdown_timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"{executable.name} did not complete normal force-quit in time"
            ) from exc
        if exit_code != 0:
            raise RuntimeError(f"{executable.name} exited with code {exit_code}")
        _wait_for_no_dupez_processes()

        crash_files = [
            path
            for path in runtime_root.rglob("*")
            if path.is_file() and path.name in {"FATAL_CRASH.txt", "DupeZ.dmp"}
        ]
        if crash_files:
            raise RuntimeError(f"Frozen run produced crash evidence under {runtime_root}")

        return {
            "variant": variant,
            "profile": profile_name,
            "cycle": cycle,
            "executable": executable.name,
            "executable_sha256": executable_hash,
            "commit": commit,
            "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_wall)),
            "startup_duration_ms": startup_duration_ms,
            "launcher_pid": process.pid,
            "gui_pid": dashboard_owner_pid,
            "dashboard_hwnd": dashboard,
            "architecture_expectation": (
                "split-medium-integrity-gui"
                if variant == "GPU"
                else "inproc-high-integrity"
            ),
            "launched_from_admin": is_admin,
            "working_set_bytes": gui_working_set,
            "process_tree_observed": [_process_info(item) for item in process_tree_snapshot],
            "map_result": map_result,
            "clean_exit": True,
            "exit_code": exit_code,
            "crash_files": [],
            "runtime_root": str(runtime_root),
        }
    except Exception:
        _terminate_started_family(process.pid, known_pids)
        raise


def main() -> int:
    args = _parse_args()
    if sys.platform != "win32":
        raise RuntimeError("Frozen lifecycle validation requires Windows")

    is_admin = _is_admin()
    if args.variant == "GPU" and is_admin:
        raise RuntimeError(
            "GPU validation must run from a standard, non-Administrator desktop session"
        )
    if args.variant == "Compat" and not is_admin:
        raise RuntimeError("Compat validation must run from Administrator PowerShell")

    repo_root = Path(__file__).resolve().parents[1]
    dist_root = (repo_root / args.dist_directory).resolve()
    executable = dist_root / (
        "DupeZ-GPU.exe" if args.variant == "GPU" else "DupeZ-Compat.exe"
    )
    if not executable.is_file():
        raise RuntimeError(f"Frozen executable missing: {executable}")

    _assert_clean_process_baseline()
    commit = _git_commit(repo_root)
    executable_hash = _sha256(executable)
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
    for profile_name, profile_environment in profiles:
        for cycle in range(1, args.cycles_per_profile + 1):
            record = _run_profile(
                variant=args.variant,
                executable=executable,
                executable_hash=executable_hash,
                commit=commit,
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

    evidence = {
        "schema": SCHEMA,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "variant": args.variant,
        "executable": executable.name,
        "executable_sha256": executable_hash,
        "commit": commit,
        "validation_host": {
            "computer": os.environ.get("COMPUTERNAME", ""),
            "windows": os.environ.get("OS", "Windows"),
            "administrator": is_admin,
            "python": sys.version.split()[0],
        },
        "runs": records,
    }
    evidence_path = dist_root / f"frozen-runtime-evidence-{args.variant.lower()}.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nFROZEN {args.variant} RUNTIME VALIDATION: PASS", flush=True)
    print(f"Evidence: {evidence_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
