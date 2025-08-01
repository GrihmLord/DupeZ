#!/usr/bin/env python3
"""
PulseDropPro Launcher
Run this script from the project root directory to start the application.
"""

import sys
import os
from PyQt6.QtWidgets import QApplication

# Ensure we're in the correct directory
if __name__ == "__main__":
    # Add the current directory to Python path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    try:
        from app.gui.dashboard import PulseDropDashboard
        from app.core.controller import AppController
        
        app = QApplication(sys.argv)
        
        # Initialize controller
        controller = AppController()
        
        # Create dashboard with controller
        window = PulseDropDashboard(controller=controller)
        window.show()
        sys.exit(app.exec())
        
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure you're running this script from the project root directory.")
        print("Current directory:", os.getcwd())
        sys.exit(1)
    except Exception as e:
        print(f"Error starting application: {e}")
        sys.exit(1) 