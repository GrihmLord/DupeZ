# app/main.py — DupeZ Entry Point (Stripped)

import sys
import os
import ctypes
import traceback


def _get_pythonw() -> str:
    """Return path to pythonw.exe (no-console Python) next to current interpreter."""
    if getattr(sys, 'frozen', False):
        return sys.executable  # PyInstaller exe — no console by default
    d = os.path.dirname(sys.executable)
    pythonw = os.path.join(d, "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def dump_crash(exctype, value, tb):
    try:
        crash_file = os.path.join(
            os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd(),
            "FATAL_CRASH.txt"
        )
        with open(crash_file, "w") as f:
            f.write("".join(traceback.format_exception(exctype, value, tb)))
    except:
        pass
    sys.__excepthook__(exctype, value, tb)


sys.excepthook = dump_crash

# Windows UAC drops CWD to System32 — force it back
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

# Chromium refuses to render under Administrator without this
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon
from app.gui.dashboard import DupeZDashboard
from app.gui.hotkey import HotkeyListener
from app.core.controller import AppController
from app.logs.logger import log_error, log_info, log_warning, log_startup, log_shutdown

IS_ADMIN = os.name != 'nt' or (
    hasattr(ctypes, 'windll') and ctypes.windll.shell32.IsUserAnAdmin() != 0
)


def main():
    # --- Phase 1: UAC Elevation (always re-launch as pythonw.exe for zero-flash) ---
    try:
        if not IS_ADMIN:
            log_warning("Not running as admin — auto-elevating via UAC...")
            exe = _get_pythonw()
            arguments = " ".join([f'"{arg}"' if ' ' in arg else arg for arg in sys.argv[1:]])
            if not getattr(sys, 'frozen', False):
                if "-m" not in arguments and "app" not in arguments:
                    arguments = f"-m app.main {arguments}"
            result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, arguments, os.getcwd(), 1)
            if result <= 32:
                log_error(f"UAC elevation failed with code: {result}")
                ctypes.windll.user32.MessageBoxW(0, "Failed to elevate. Run as Administrator.", "Admin Required", 0x10)
            sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        log_error(f"Error during auto-elevation: {e}")
        ctypes.windll.user32.MessageBoxW(0, "Failed to elevate. Run as Administrator.", "Admin Warning", 0x10)
        sys.exit(1)

    # --- Phase 2: App Initialization ---
    try:
        log_startup()

        if os.name == 'nt':
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('com.dupez.app.3.0')
            except Exception as e:
                log_error(f"Failed to set AppUserModelID: {e}")

        app = QApplication(sys.argv)
        # App icon — try resources first, fall back to assets
        for icon_path in ["app/resources/dupez.ico", "app/resources/dupez.png", "app/assets/icon.ico"]:
            if os.path.exists(icon_path):
                app.setWindowIcon(QIcon(icon_path))
                break

        log_info("Initializing DupeZ...")
        log_info(f"Admin privileges: {'Yes' if IS_ADMIN else 'No'}")
        log_info("DupeZ version: 3.0.0")

        controller = AppController()
        window = DupeZDashboard(controller=controller)

        # Hotkey listener for lag toggle
        hotkey = HotkeyListener(callback=controller.toggle_lag)
        hotkey.start()

        window.show()
        log_info("DupeZ started successfully")

        def _shutdown_cleanup():
            try:
                from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
                clumsy_network_disruptor.stop_clumsy()
                log_info("Clumsy disruptor stopped")
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
