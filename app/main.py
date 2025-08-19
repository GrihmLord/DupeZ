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
        app = QApplication(sys.argv)
        
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
        window = DupeZDashboard(controller=controller)
        
        # Initialize stability optimizer
        try:
            from app.core.stability_optimizer import stability_optimizer
            stability_optimizer.start_monitoring()
            log_info("Stability optimizer started successfully")
        except Exception as e:
            log_error(f"Failed to start stability optimizer: {e}")
        
        # Warn if not run as admin
        if not IS_ADMIN:
            QMessageBox.warning(
                window, "Admin Warning",
                "⚠️ Please run as Administrator to enable full firewall control."
            )
        
        # Start hotkey listener
        hotkey = HotkeyListener(callback=controller.toggle_lag)
        hotkey.start()
        
        # Show GUI
        window.show()
        
        log_info("DupeZ started successfully")
        
        # Define shutdown cleanup function
        def _shutdown_cleanup():
            try:
                # Stop stability optimizer
                from app.core.stability_optimizer import stability_optimizer
                try:
                    stability_optimizer.stop_monitoring()
                    log_info("Stability optimizer stopped")
                except Exception as e:
                    log_error(f"Error stopping stability optimizer: {e}")
            except Exception as e:
                log_error(f"Error importing stability optimizer: {e}")
            
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
