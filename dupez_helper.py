#!/usr/bin/env python
# dupez_helper.py
"""DupeZ elevated firewall helper entry point (ADR-0001).

This executable runs at High IL under ``DUPEZ_ARCH=split``. It owns WinDivert
and the direct Clumsy child-process lifecycle. Only authenticated control-plane
messages cross the named pipe; packet bodies remain inside the helper.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import ntpath
import os
import re
import signal
import stat
import sys
import threading
import time


def _force_helper_inproc_arch() -> None:
    """Keep every helper-owned firewall call inside this process."""

    os.environ["DUPEZ_ARCH"] = "inproc"


if "--role" in sys.argv:
    try:
        role_index = sys.argv.index("--role")
        if sys.argv[role_index + 1] == "helper":
            _force_helper_inproc_arch()
    except (ValueError, IndexError):
        pass

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_ATTRIBUTE_REPARSE_POINT = int(
    getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
)
_FILE_APPEND_DATA = 0x00000004
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_SHARE_READ = 0x00000001
_FILE_TYPE_DISK = 0x0001
_OPEN_ALWAYS = 4
_HELPER_FACTOR_PROMPT_TIMEOUT_MS = 60_000

_HELPER_PATH_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    (re.compile(r"(/Users/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    (re.compile(r"(/home/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
)
_HELPER_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_HELPER_BEARER_RE = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"
)
_HELPER_LABELED_SECRET_RE = re.compile(
    r"(?ix)"
    r"(?P<label>\b(?:api[_-]?key|password|passwd|secret|token|credential|"
    r"private[_-]?key|auth)\b\s*[:=]\s*)"
    r"(?:[\"'][^\r\n]*?[\"']|[^\s,;}\]\r\n]+)"
)


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


def _windows_local_appdata() -> str:
    """Resolve LocalAppData from Windows, never from inherited environment."""

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
        ctypes.byref(_FOLDERID_LOCAL_APPDATA),
        0,
        None,
        ctypes.byref(path_pointer),
    )
    try:
        if result != 0 or not path_pointer.value:
            raise OSError("Windows LocalAppData known folder is unavailable")
        state_root = os.path.abspath(path_pointer.value)
        if not os.path.isabs(state_root):
            raise OSError("Windows LocalAppData known folder is not absolute")
        return state_root
    finally:
        if path_pointer:
            free_memory(ctypes.cast(path_pointer, ctypes.c_void_p))


def _helper_log_path() -> str:
    if os.name == "nt":
        state_root = _windows_local_appdata()
    else:
        state_root = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~")
    return os.path.join(
        state_root,
        "DupeZ",
        "logs",
        "firewall_helper.log",
    )


def _assert_non_reparse_directories(
    directory: str,
    *,
    allow_missing: bool,
) -> None:
    """Reject symlink/reparse components and inconsistent path walks."""

    absolute = os.path.abspath(directory)
    components: list[str] = []
    current = absolute
    while True:
        components.append(current)
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent

    missing_parent = False
    for component in reversed(components):
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            if not allow_missing:
                raise OSError("secure helper log directory is missing") from None
            missing_parent = True
            continue
        if missing_parent:
            raise OSError("secure helper log directory changed during validation")
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        if (
            stat.S_ISLNK(metadata.st_mode)
            or attributes & _FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise OSError("secure helper log path contains a reparse point")
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("secure helper log path contains a non-directory")


def _win32_open_log_handle(path: str) -> int:
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
        path,
        _FILE_APPEND_DATA,
        _FILE_SHARE_READ,
        None,
        _OPEN_ALWAYS,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in (None, invalid_handle):
        raise OSError(ctypes.get_last_error(), "secure helper log open failed")
    return int(handle)


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [
        ("file_attributes", ctypes.c_uint32),
        ("reparse_tag", ctypes.c_uint32),
    ]


def _win32_handle_is_regular_non_reparse(handle: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_file_type = kernel32.GetFileType
    get_file_type.argtypes = [ctypes.c_void_p]
    get_file_type.restype = ctypes.c_uint32
    if get_file_type(handle) != _FILE_TYPE_DISK:
        return False

    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    get_information.restype = ctypes.c_int
    information = _FileAttributeTagInfo()
    file_attribute_tag_info = 9
    if not get_information(
        handle,
        file_attribute_tag_info,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise OSError(ctypes.get_last_error(), "secure helper log inspection failed")
    unsafe_attributes = _FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT
    return not bool(information.file_attributes & unsafe_attributes)


def _win32_final_handle_path(handle: int) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    get_final_path.restype = ctypes.c_uint32
    required = get_final_path(handle, None, 0, 0)
    if required == 0:
        raise OSError(ctypes.get_last_error(), "secure helper log path check failed")
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = get_final_path(handle, buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        raise OSError(ctypes.get_last_error(), "secure helper log path check failed")
    return buffer.value


def _normalize_windows_handle_path(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return ntpath.normcase(ntpath.normpath(path))


def _win32_close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    close_handle(handle)


def _consume_win32_log_handle(handle: int):
    """Convert *handle* to a text stream, consuming it even on failure."""

    import msvcrt

    flags = os.O_APPEND | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = msvcrt.open_osfhandle(handle, flags)
    except Exception:
        _win32_close_handle(handle)
        raise
    try:
        return os.fdopen(
            descriptor,
            "a",
            buffering=1,
            encoding="utf-8",
        )
    except Exception:
        os.close(descriptor)
        raise


def _open_secure_windows_log(log_path: str):
    log_directory = os.path.dirname(log_path)
    _assert_non_reparse_directories(log_directory, allow_missing=True)
    os.makedirs(log_directory, exist_ok=True)
    _assert_non_reparse_directories(log_directory, allow_missing=False)

    handle = _win32_open_log_handle(log_path)
    handle_owned = True
    try:
        if not _win32_handle_is_regular_non_reparse(handle):
            raise OSError("secure helper log file is not a regular file")
        final_path = _win32_final_handle_path(handle)
        if _normalize_windows_handle_path(final_path) != (
            _normalize_windows_handle_path(log_path)
        ):
            raise OSError("secure helper log resolved outside its expected path")
        _assert_non_reparse_directories(log_directory, allow_missing=False)
        handle_owned = False
        return _consume_win32_log_handle(handle)
    finally:
        if handle_owned:
            _win32_close_handle(handle)


def _open_secure_helper_log():
    if os.name != "nt":
        raise OSError("secure helper file logging is Windows-only")
    return _open_secure_windows_log(_helper_log_path())


class _OwnedLogStreamHandler(logging.StreamHandler):
    def close(self) -> None:
        stream = self.stream
        self.stream = None
        try:
            if stream is not None:
                stream.close()
        finally:
            super().close()


def _scrub_helper_log_text(message: str) -> str:
    """Remove private values before an elevated helper record is emitted."""

    rendered = str(message)
    try:
        from app.core.secrets_manager import scrub_message

        rendered = scrub_message(rendered)
    except Exception:
        pass
    try:
        from app.utils.helpers import mask_ips_in_text, mask_macs_in_text

        rendered = mask_macs_in_text(mask_ips_in_text(rendered))
    except Exception:
        pass
    try:
        from app.core.secret_store import _redact_local_paths

        rendered = _redact_local_paths(rendered)
    except Exception:
        pass
    try:
        canonical_root = _windows_local_appdata() if os.name == "nt" else ""
        if canonical_root:
            variants = {
                canonical_root,
                canonical_root.replace("\\", "\\\\"),
                canonical_root.replace("\\", "/"),
            }
            for candidate in variants:
                rendered = rendered.replace(candidate, "%LOCALAPPDATA%")
    except Exception:
        pass
    for pattern, replacement in _HELPER_PATH_PATTERNS:
        rendered = pattern.sub(replacement, rendered)
    rendered = _HELPER_URL_RE.sub("[REDACTED URL]", rendered)
    rendered = _HELPER_BEARER_RE.sub("[REDACTED CREDENTIAL]", rendered)
    rendered = _HELPER_LABELED_SECRET_RE.sub(
        lambda match: f"{match.group('label')}[REDACTED]",
        rendered,
    )
    return rendered


class _HelperScrubbingFormatter(logging.Formatter):
    """Scrub the fully-rendered message, including exception tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return _scrub_helper_log_text(super().format(record))


def _configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    file_logging_available = False
    try:
        # Keep the verified handle for the process lifetime. A pathname-based
        # rotating handler would reopen files across the elevation boundary.
        log_stream = _open_secure_helper_log()
        handlers.insert(0, _OwnedLogStreamHandler(log_stream))
        file_logging_available = True
    except Exception:
        # An elevated process must never fall back to an untrusted pathname.
        # Console capture remains available to the launcher/operator.
        pass
    formatter = _HelperScrubbingFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
        force=True,
    )
    if not file_logging_available:
        logging.getLogger("dupez-helper").warning(
            "secure file logging unavailable; using stream-only logging"
        )


def _positive_pid(value: str) -> int:
    try:
        parsed = int(value, 10)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("parent PID must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("parent PID must be a positive integer")
    return parsed


def _positive_timestamp(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("parent creation time is invalid") from exc
    if not (0 < parsed < float("inf")):
        raise argparse.ArgumentTypeError("parent creation time is invalid")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DupeZ elevated firewall helper (ADR-0001)",
    )
    parser.add_argument(
        "--role",
        choices=["helper"],
        required=True,
        help="Execution role. Only 'helper' is supported.",
    )
    parser.add_argument(
        "--parent-pid",
        type=_positive_pid,
        required=True,
        help="Parent GUI PID. Helper exits if that exact process dies.",
    )
    parser.add_argument(
        "--parent-created",
        type=_positive_timestamp,
        required=True,
        help="Parent creation time used to reject stale/reused process IDs.",
    )
    return parser.parse_args()


def _validate_parent_identity(parent_pid: int, expected_create_time: float) -> float:
    """Fail closed unless the exact launching GUI process is still live."""
    if parent_pid <= 0 or parent_pid == os.getpid():
        raise RuntimeError("invalid helper parent identity")
    try:
        import psutil

        process = psutil.Process(parent_pid)
        actual_create_time = float(process.create_time())
        if not process.is_running():
            raise RuntimeError("helper parent is not running")
        if getattr(sys, "frozen", False):
            parent_image = os.path.normcase(
                os.path.realpath(process.exe())
            )
            helper_image = os.path.normcase(
                os.path.realpath(sys.executable)
            )
            if parent_image != helper_image:
                raise RuntimeError("helper parent image is not the DupeZ GUI")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("helper parent identity is unavailable") from exc
    if abs(actual_create_time - expected_create_time) >= 0.001:
        raise RuntimeError("helper parent identity is stale")
    return actual_create_time


def _helper_second_factor_prompter(
    scope: str,
    *,
    parent_shutdown_event: threading.Event | None = None,
) -> str:
    """Collect a bounded, foreground factor inside the High-IL process."""

    application = None
    owns_application = False
    dialog = None
    timer = None
    try:
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtWidgets import (
            QApplication,
            QDialog,
            QInputDialog,
            QLineEdit,
        )

        if parent_shutdown_event is not None and parent_shutdown_event.is_set():
            return ""
        application = QApplication.instance()
        owns_application = application is None
        if application is None:
            application = QApplication(["DupeZ privileged authorization"])

        dialog = QInputDialog()
        dialog.setWindowTitle("DupeZ privileged authorization")
        dialog.setLabelText(
            f"Second factor required for {scope}. Enter the 6-digit code:"
        )
        dialog.setTextEchoMode(QLineEdit.EchoMode.Password)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        deadline = time.monotonic() + (
            _HELPER_FACTOR_PROMPT_TIMEOUT_MS / 1000.0
        )

        def _cancel_stale_prompt() -> None:
            parent_gone = (
                parent_shutdown_event is not None
                and parent_shutdown_event.is_set()
            )
            if parent_gone or time.monotonic() >= deadline:
                dialog.reject()

        timer = QTimer(dialog)
        timer.setInterval(100)
        timer.timeout.connect(_cancel_stale_prompt)
        timer.start()

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        QApplication.alert(dialog, 0)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        presented = dialog.textValue() if accepted else ""
        return presented if isinstance(presented, str) else ""
    except Exception:
        # A privileged boundary must never fall back to getpass/stdin: the
        # frozen GUI executable has no trusted console and could disclose the
        # factor or block indefinitely.
        return ""
    finally:
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
        if dialog is not None:
            try:
                dialog.close()
                dialog.deleteLater()
            except Exception:
                pass
        if owns_application and application is not None:
            try:
                application.quit()
            except Exception:
                pass


def _consume_helper_session_secret() -> bytes:
    """Consume and validate the one-launch IPC secret before engine import."""

    from app.firewall_helper.auth import (
        TOKEN_BYTES,
        read_and_consume_token_sentinel,
    )

    secret = read_and_consume_token_sentinel()
    if not isinstance(secret, bytes) or len(secret) != TOKEN_BYTES:
        raise RuntimeError("helper session authorization is unavailable")
    return secret


def _discard_helper_session_secret() -> None:
    """Best-effort secure cleanup for a launch that fails before auth."""

    try:
        from app.firewall_helper.auth import discard_token_sentinel

        discard_token_sentinel()
    except Exception:
        # Cleanup must not copy a path or token into the elevated log.
        pass


def _parent_watcher(
    parent_pid: int,
    shutdown_event,
    expected_create_time: float | None = None,
) -> None:
    """Request shutdown if the exact parent process disappears."""

    import psutil

    log = logging.getLogger("parent-watcher")
    log.info("watching the validated parent process")
    while not shutdown_event.is_set():
        try:
            process = psutil.Process(parent_pid)
            same_process = (
                expected_create_time is None
                or abs(process.create_time() - expected_create_time) < 0.001
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            same_process = False
        if not same_process:
            log.warning("validated parent process gone, initiating shutdown")
            shutdown_event.set()
            return
        shutdown_event.wait(1.0)


def main() -> int:
    _force_helper_inproc_arch()
    _configure_logging()
    log = logging.getLogger("dupez-helper")
    try:
        args = _parse_args()
    except SystemExit:
        _discard_helper_session_secret()
        raise

    try:
        parent_create_time = _validate_parent_identity(
            args.parent_pid,
            args.parent_created,
        )
    except RuntimeError:
        _discard_helper_session_secret()
        log.error("helper parent identity validation failed; refusing startup")
        return 5

    log.info("dupez_helper starting with a validated parent binding")
    # Bind liveness before any modal authorization UI. If the GUI disappears,
    # the prompt is rejected and no native firewall module is imported.
    parent_shutdown_event = threading.Event()
    watcher = threading.Thread(
        target=_parent_watcher,
        args=(
            args.parent_pid,
            parent_shutdown_event,
            parent_create_time,
        ),
        name="parent-watcher",
        daemon=True,
    )
    watcher.start()
    disruption_manager = None
    blocker_module = None
    dispatcher = None
    try:
        # Consume the ephemeral pipe secret and verify any enrolled factor
        # before importing the native firewall engine. Enforcing here (inside
        # High IL) closes direct ``--role helper`` invocation paths.
        try:
            shared_secret = _consume_helper_session_secret()
            from app.firewall_helper.elevation import enforce_second_factor

            def _prompt_factor(scope: str) -> str:
                return _helper_second_factor_prompter(
                    scope,
                    parent_shutdown_event=parent_shutdown_event,
                )

            enforce_second_factor(
                boundary="helper_startup",
                prompter=_prompt_factor,
            )
        except Exception:
            if parent_shutdown_event.is_set():
                log.error("validated parent exited during authorization")
                return 5
            log.error("helper authorization failed; refusing engine startup")
            return 6

        # The prompt can remain open for a bounded interval. Revalidate the
        # exact process identity immediately before native imports and again
        # before engine start so the original trust decision cannot go stale.
        try:
            if parent_shutdown_event.is_set():
                raise RuntimeError("parent exited")
            _validate_parent_identity(args.parent_pid, parent_create_time)
        except RuntimeError:
            log.error("helper parent identity became stale; refusing startup")
            return 5

        try:
            from app.firewall.clumsy_diagnostics import (
                install_clumsy_diagnostic_bridge,
            )
            from app.firewall.direct_clumsy_manager import (
                disruption_manager as direct_manager,
            )

            disruption_manager = install_clumsy_diagnostic_bridge(
                direct_manager
            )
        except Exception:
            log.error("privileged disruption engine import failed")
            return 2

        degraded_ok = (
            not getattr(sys, "frozen", False)
            and os.environ.get("DUPEZ_HELPER_ALLOW_DEGRADED") == "1"
        )
        degraded = False
        if parent_shutdown_event.is_set():
            log.error("validated parent exited before engine initialization")
            return 5
        if not disruption_manager.initialize():
            if not degraded_ok:
                log.error("disruption engine initialization was refused")
                return 3
            log.warning("continuing with the source-only degraded helper")
            degraded = True

        if not degraded:
            try:
                if parent_shutdown_event.is_set():
                    raise RuntimeError("parent exited")
                _validate_parent_identity(args.parent_pid, parent_create_time)
            except RuntimeError:
                log.error("validated parent exited before engine start")
                return 5
            try:
                disruption_manager.start()
            except Exception:
                if not degraded_ok:
                    log.error("disruption engine start failed")
                    return 4
                log.warning("source-only degraded helper could not start engine")
                degraded = True

        log.info(
            "disruption engine running in helper process (degraded=%s)",
            degraded,
        )

        try:
            from app.firewall import blocker as blocker_module
        except Exception:
            log.warning("optional firewall blocker module is unavailable")
            blocker_module = None

        if parent_shutdown_event.is_set():
            log.error("validated parent exited before helper server startup")
            return 5

        try:
            from app.firewall_helper.server import run_helper_server

            dispatcher = run_helper_server(
                disruption_manager,
                blocker_module=blocker_module,
                shared_secret=shared_secret,
                expected_client_pid=args.parent_pid,
            )
        except Exception:
            log.error("authenticated helper server startup failed")
            return 7

        def _signal_handler(signum, _frame):
            log.info("received signal %d, shutting down", signum)
            dispatcher.shutdown_event.set()

        for handled_signal in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(handled_signal, _signal_handler)
            except Exception:
                pass

        try:
            while not dispatcher.shutdown_event.wait(timeout=0.5):
                if parent_shutdown_event.is_set():
                    dispatcher.shutdown_event.set()
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt, shutting down")

        log.info("dupez_helper shutdown requested")
        return 0
    finally:
        parent_shutdown_event.set()
        if watcher is not threading.current_thread():
            watcher.join(timeout=1.5)
        if disruption_manager is not None:
            try:
                disruption_manager.stop_all_devices()
            except Exception:
                log.error("active-device cleanup failed")
        if blocker_module is not None:
            try:
                blocker_module.clear_all_dupez_blocks()
            except Exception:
                log.error("firewall-block cleanup failed")
        if disruption_manager is not None:
            try:
                disruption_manager.stop()
            except Exception:
                log.error("disruption engine shutdown failed")
        log.info("dupez_helper exit")


if __name__ == "__main__":
    sys.exit(main())
