# app/main.py

import sys
import os
import ctypes
import threading

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QTimer

from app.gui.dashboard import DupeZDashboard
from app.gui.hotkey import HotkeyListener
from app.core.controller import AppController
from app.logs.logger import log_error, log_info, log_startup, log_shutdown

# Determine admin status
IS_ADMIN = os.name != 'nt' or (
    hasattr(ctypes, 'windll') and ctypes.windll.shell32.IsUserAnAdmin() != 0
)

def main():
    try:
        log_startup()
        
        # Create application with performance optimizations
        # Check if QApplication already exists to prevent multiple instances
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        else:
            log_info("QApplication instance already exists, using existing instance")
        
        # High DPI attributes are unnecessary or unavailable in this PyQt6 build; skip setting them
        
        # Set application icon
        app.setWindowIcon(QIcon("app/assets/icon.ico"))
        
        # Log environment information for debugging
        log_info("Initializing DupeZ...")
        log_info(f"Python executable: {sys.executable}")
        log_info(f"Python version: {sys.version}")
        log_info(f"Working directory: {os.getcwd()}")
        log_info(f"Admin privileges: {'Yes' if IS_ADMIN else 'No'}")
        log_info(f"DupeZ version: 2.0.0 Professional Edition")
        
        # Initialize controller (logic handler) in background thread
        controller = AppController()
        
        # Initialize GUI and inject controller
        # Check if main window already exists to prevent multiple instances
        existing_windows = [w for w in app.topLevelWidgets() if isinstance(w, DupeZDashboard)]
        if existing_windows:
            log_info("Main window already exists, using existing instance")
            window = existing_windows[0]
            window.raise_()
            window.activateWindow()
        else:
            window = DupeZDashboard(controller=controller)
        
        # Stability optimizer: DISABLED to prevent overlay issues
        # The stability optimizer was causing UI overlay problems and excessive memory usage
        # All stability monitoring is now disabled for a cohesive GUI experience
        log_info("Stability optimizer disabled to prevent overlay issues")
        
        # Warn if not run as admin
        if not IS_ADMIN:
            QMessageBox.warning(
                window, "Admin Warning",
                "⚠️ Please run as Administrator to enable full firewall control."
            )
        
        # Start hotkey listener
        hotkey = HotkeyListener(callback=controller.toggle_lag)
        hotkey.start()
        
        # Show GUI (only if not already visible)
        if not window.isVisible():
            window.show()
        else:
            log_info("Main window already visible")
        
        log_info("DupeZ started successfully")
        
        # Define shutdown cleanup function
        def _shutdown_cleanup():
            try:
                # Stability optimizer is disabled - no cleanup needed
                log_info("Stability optimizer was disabled - no cleanup needed")
            except Exception as e:
                log_error(f"Error in shutdown cleanup: {e}")
            
            # Log shutdown
            log_shutdown()
        
        # Connect shutdown signal
        app.aboutToQuit.connect(_shutdown_cleanup)
        
        sys.exit(app.exec())
        
    except Exception as e:
        log_error(f"Unhandled exception in main: {e}")
        QMessageBox.critical(None, "Critical Error", f"An error occurred:\n{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
