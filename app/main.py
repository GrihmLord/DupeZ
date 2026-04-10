# app/main.py — DupeZ Entry Point
"""
Launches the DupeZ GUI application with automatic UAC elevation,
splash screen initialization, crash dump handler, and graceful
shutdown coordination.
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback

__all__ = ["dump_crash", "main"]


def _get_pythonw() -> str:
    """Return path to pythonw.exe (no-console) next to current interpreter."""
    if getattr(sys, "frozen", False):
        return sys.executable
    d = os.path.dirname(sys.executable)
    pythonw = os.path.join(d, "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def dump_crash(exctype, value, tb) -> None:
    """Write unhandled exception to FATAL_CRASH.txt for post-mortem."""
    try:
        crash_dir = (
            os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.getcwd()
        )
        crash_file = os.path.join(crash_dir, "FATAL_CRASH.txt")
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write("".join(traceback.format_exception(exctype, value, tb)))
    except Exception:
        pass
    sys.__excepthook__(exctype, value, tb)


sys.excepthook = dump_crash

# Windows UAC drops CWD to System32 — force it back to exe directory
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

# Chromium refuses to render under Administrator without this
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.core.updater import CURRENT_VERSION
from app.logs.logger import log_error, log_info, log_shutdown, log_startup, log_warning
from app.utils.helpers import is_admin

IS_ADMIN: bool = is_admin()


def main() -> None:
    # --- Phase 1: UAC Elevation ---
    try:
        if not IS_ADMIN:
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
    except SystemExit:
        raise
    except Exception as e:
        log_error(f"Error during auto-elevation: {e}")
        ctypes.windll.user32.MessageBoxW(
            0, "Failed to elevate. Run as Administrator.",
            "Admin Warning", 0x10,
        )
        sys.exit(1)

    # --- Phase 2: QApplication + Splash Screen ---
    try:
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
