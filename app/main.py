# app/main.py

import sys
import os
import ctypes
import threading

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QTimer

from app.gui.dashboard import PulseDropDashboard
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
        
        # Set application properties for better performance
        app.setAttribute(app.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
        app.setAttribute(app.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        
        # Set application icon
        app.setWindowIcon(QIcon("app/assets/icon.ico"))
        
        log_info("Initializing PulseDrop Pro...")
        
        # Initialize controller (logic handler) in background thread
        controller = AppController()
        
        # Initialize GUI and inject controller
        window = PulseDropDashboard(controller=controller)
        
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
        
        log_info("PulseDrop Pro started successfully")
        
        # Connect shutdown signal
        app.aboutToQuit.connect(lambda: log_shutdown())
        
        sys.exit(app.exec())
        
    except Exception as e:
        log_error(f"Unhandled exception in main: {e}")
        QMessageBox.critical(None, "Critical Error", f"An error occurred:\n{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
