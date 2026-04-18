# app/main.py — DupeZ Entry Point
"""
Launches the DupeZ GUI application with automatic UAC elevation,
splash screen initialization, crash dump handler, and graceful
shutdown coordination.
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
import traceback

__all__ = ["dump_crash", "main"]


# ── Crash-dump PII scrubber (H5) ─────────────────────────────────────
# Tracebacks contain absolute filesystem paths — under Python these
# routinely include the developer's home directory (``C:\Users\<name>``
# or ``/home/<name>``). When users attach FATAL_CRASH.txt to a bug
# report or post it in Discord, those paths leak the Windows username
# and any directory names off of it. Scrub before writing.

# Patterns redact the user component while keeping the traceback
# structurally useful (file name, line number, code snippet all remain).
_PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # C:\Users\<name>\...   →   C:\Users\<REDACTED>\...
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    # /Users/<name>/...     →   /Users/<REDACTED>/...
    (re.compile(r"(/Users/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    # /home/<name>/...      →   /home/<REDACTED>/...
    (re.compile(r"(/home/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
)


def _scrub_traceback(text: str) -> str:
    """Redact home-directory usernames from traceback output.

    Keeps file basenames, line numbers and code context so the dump is
    still useful for post-mortem analysis, but removes the OS username
    so crash reports are safe to share verbatim.
    """
    for pat, repl in _PII_PATTERNS:
        text = pat.sub(repl, text)
    return text


def _get_pythonw() -> str:
    """Return path to pythonw.exe (no-console) next to current interpreter."""
    if getattr(sys, "frozen", False):
        return sys.executable
    d = os.path.dirname(sys.executable)
    pythonw = os.path.join(d, "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def dump_crash(exctype, value, tb) -> None:
    """Write unhandled exception to FATAL_CRASH.txt for post-mortem.

    Paths are scrubbed of OS username before being written to disk so
    the file is safe to share in bug reports. The original (un-scrubbed)
    traceback still reaches stderr via ``sys.__excepthook__`` for
    developer-side debugging.
    """
    try:
        crash_dir = (
            os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.getcwd()
        )
        crash_file = os.path.join(crash_dir, "FATAL_CRASH.txt")
        raw = "".join(traceback.format_exception(exctype, value, tb))
        scrubbed = _scrub_traceback(raw)
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write(scrubbed)
    except Exception:
        pass
    sys.__excepthook__(exctype, value, tb)


sys.excepthook = dump_crash

# Windows UAC drops CWD to System32 — force it back to exe directory
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

# ── Startup hardening (H6) ───────────────────────────────────────────
# Call SetDefaultDllDirectories BEFORE any import that triggers a
# LoadLibrary: PyQt6 pulls Chromium, Chromium loads ~60 .dlls, and a
# single attacker-controlled CWD resolution there is a sideload win.
# Keep this block above every third-party import.
try:
    from app.core.self_integrity import apply_startup_hardening as _apply_hardening
    _apply_hardening()
except Exception:
    # Never crash the app because hardening couldn't load — the offsec
    # layer will catch the regression in its next detection_coverage run.
    pass

# ── QtWebEngine sandbox gating (H6) ──────────────────────────────────
# Chromium refuses to render under Administrator (High-IL) without
# disabling its inner sandbox — mandatory for the Compat variant and
# the legacy in-proc path. Under split mode the GUI is Medium-IL and
# the Chromium sandbox MUST stay enabled; disabling it pointlessly
# reduces the defense-in-depth around iZurvive's embedded map context.
def _should_disable_qt_sandbox() -> bool:
    # Split mode never elevates the GUI → keep Chromium sandbox on.
    arch = os.environ.get("DUPEZ_ARCH", "").strip().lower()
    if arch == "split":
        return False
    # In-proc / Compat path runs High-IL → Chromium requires sandbox off.
    return True


if _should_disable_qt_sandbox():
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.core.updater import CURRENT_VERSION
from app.logs.logger import log_error, log_info, log_shutdown, log_startup, log_warning
from app.utils.helpers import is_admin

IS_ADMIN: bool = is_admin()


def main() -> None:
    # --- Phase 1: UAC Elevation ---
    # ADR-0001 split mode: the GUI process MUST stay at Medium IL so the
    # embedded Chromium map can initialize its GPU sandbox. WinDivert ops
    # are proxied through dupez_helper.py which runs separately at High
    # IL (see app/firewall_helper/elevation.py). Under split mode we do
    # NOT self-elevate here — doing so kills the GPU path and, worse,
    # creates a UAC cascade when the already-elevated GUI then tries to
    # spawn its own helper via runas. Inproc mode (the legacy code path
    # and the DupeZ-Compat.exe variant) still self-elevates as before.
    try:
        from app.firewall_helper.feature_flag import is_split_mode
        _split = is_split_mode()
    except Exception:
        _split = (os.environ.get("DUPEZ_ARCH", "").strip().lower() == "split")

    try:
        if not IS_ADMIN and not _split:
            log_warning("Not running as admin — auto-elevating via UAC...")
            exe = _get_pythonw()
            arguments = " ".join(
                f'"{arg}"' if " " in arg else arg for arg in sys.argv[1:]
            )
            if not getattr(sys, "frozen", False):
                if "-m" not in arguments and "app" not in arguments:
                    arguments = f"-m app.main {arguments}"
            result = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, arguments, os.getcwd(), 1,
            )
            if result <= 32:
                log_error(f"UAC elevation failed with code: {result}")
                ctypes.windll.user32.MessageBoxW(
                    0, "Failed to elevate. Run as Administrator.",
                    "Admin Required", 0x10,
                )
            sys.exit(0)
        if _split and not IS_ADMIN:
            log_info("split mode: running GUI at Medium IL; helper "
                     "will elevate on first firewall op")
    except SystemExit:
        raise
    except Exception as e:
        log_error(f"Error during auto-elevation: {e}")
        ctypes.windll.user32.MessageBoxW(
            0, "Failed to elevate. Run as Administrator.",
            "Admin Warning", 0x10,
        )
        sys.exit(1)

    # --- Phase 1b: Log GPU/renderer tier ---
    _tier = os.environ.get("DUPEZ_MAP_RENDERER_TIER", "tier3_cpu")
    _arch = os.environ.get("DUPEZ_ARCH", "unknown")
    log_info(f"Renderer tier: {_tier} | Architecture: {_arch} | Admin: {IS_ADMIN}")
    if _tier == "tier3_cpu" and not IS_ADMIN:
        log_warning(
            "Running CPU-raster map. If you have a GPU, ensure you are "
            "using DupeZ-GPU.exe (split mode) for hardware-accelerated map."
        )

    # --- Phase 2: QApplication + Splash Screen ---
    try:
        # QtWebEngine REQUIRES this attribute to be set on the
        # QCoreApplication BEFORE the QApplication instance is
        # constructed. Without it, Chromium prints a warning at
        # startup and some contexts (embedded iZurvive map) can
        # render with corrupted textures on multi-GPU machines.
        # This MUST come before `QApplication(sys.argv)` below.
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

        app = QApplication(sys.argv)

        # Set app icon
        for icon_path in [
            "app/resources/dupez.ico",
            "app/resources/dupez.png",
            "app/assets/icon.ico",
        ]:
            if os.path.exists(icon_path):
                app.setWindowIcon(QIcon(icon_path))
                break

        # --- Show splash screen and run init pipeline ---
        from app.gui.splash import DupeZSplash
        splash = DupeZSplash()
        splash.show()
        app.processEvents()

        # --- Prewarm the DayZ map widget -----------------------------
        # Construct DayZMapGUI once, early, on the main thread so the
        # QWebEngineView boot and the initial iZurvive tile download
        # run in parallel with the splash init pipeline (WinDivert,
        # controller, plugins). Dashboard adopts this prewarmed
        # instance when it builds the view stack, so the map is
        # already interactive by the time the user clicks the tab.
        #
        # The widget is hidden + parented to None; Qt reparents it
        # into the QStackedWidget automatically via addWidget().
        # Failures are non-fatal — Dashboard falls back to the cold
        # construction path.
        try:
            from app.gui.dayz_map_gui_new import (
                DayZMapGUI,
                set_prewarmed_map_gui,
            )
            _prewarmed_map = DayZMapGUI()
            _prewarmed_map.hide()
            set_prewarmed_map_gui(_prewarmed_map)
            app.processEvents()  # let the load request go out immediately
            log_info("Map: prewarmed DayZMapGUI during splash")
        except Exception as _prewarm_exc:
            log_warning(f"Map prewarm failed (non-fatal): {_prewarm_exc}")

        # State container for the completion callback
        _init_done = {"ready": False}

        def _on_splash_complete() -> None:
            """Called on main thread when splash pipeline finishes."""
            _init_done["ready"] = True

        splash.run_init_pipeline(on_complete=_on_splash_complete)

        # Process events while init runs (keeps splash animated)
        while not _init_done["ready"]:
            app.processEvents()

        # Grab the controller created by splash
        controller = splash.controller
        init_error = splash.init_error

        # Close splash
        splash.close()
        splash.deleteLater()

        if init_error and controller is None:
            QMessageBox.critical(
                None, "Initialization Failed",
                f"DupeZ could not start:\n{init_error}"
            )
            sys.exit(1)

        # --- Phase 3: Main Window ---
        from app.gui.dashboard import DupeZDashboard
        from app.gui.hotkey import HotkeyListener

        window = DupeZDashboard(controller=controller)

        hotkey = HotkeyListener(callback=controller.toggle_lag)
        hotkey.start()

        window.show()
        log_info("DupeZ started successfully")

        # --- Phase 4: Background Services ---
        try:
            from app.core.patch_monitor import start_background_monitoring
            start_background_monitoring()
            log_info("Patch monitor started")
        except Exception as e:
            log_warning(f"Patch monitor failed to start (non-fatal): {e}")

        def _shutdown_cleanup() -> None:
            try:
                from app.core.patch_monitor import stop_background_monitoring
                stop_background_monitoring()
                log_info("Patch monitor stopped")
            except Exception:
                pass
            try:
                from app.firewall.clumsy_network_disruptor import disruption_manager
                disruption_manager.stop()
                log_info("Disruption engine stopped")
            except Exception as e:
                log_error(f"Error stopping clumsy on exit: {e}")
            controller.shutdown()
            log_shutdown()

        app.aboutToQuit.connect(_shutdown_cleanup)
        sys.exit(app.exec())

    except Exception as e:
        log_error(f"Unhandled exception in main: {e}")
        QMessageBox.critical(None, "Critical Error", f"An error occurred:\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
