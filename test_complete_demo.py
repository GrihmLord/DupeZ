#!/usr/bin/env python3
"""
Complete Demo for Enhanced PulseDrop Pro
Shows all features: Angry IP Scanner + Clumsy 3.0 + Original PulseDrop Pro
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QTextEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """Main demo function"""
    try:
        # Create QApplication
        app = QApplication(sys.argv)
        app.setApplicationName("Enhanced PulseDrop Pro - Complete Demo")
        
        # Import the main dashboard
        from app.gui.dashboard import PulseDropDashboard
        
        # Create main window
        window = QMainWindow()
        window.setWindowTitle("Enhanced PulseDrop Pro - Complete Demo")
        window.setGeometry(100, 100, 1600, 1000)
        
        # Create central widget
        central = QWidget()
        window.setCentralWidget(central)
        
        # Create layout
        layout = QVBoxLayout()
        central.setLayout(layout)
        
        # Create enhanced dashboard
        dashboard = PulseDropDashboard()
        layout.addWidget(dashboard)
        
        # Show window
        window.show()
        window.raise_()
        window.activateWindow()
        
        print("Enhanced PulseDrop Pro - Complete Demo is running!")
        print("Features available:")
        print("• Original PulseDrop Pro features")
        print("• Angry IP Scanner-style network scanning")
        print("• Clumsy 3.0-style traffic control")
        print("• Enhanced device blocking")
        print("• Advanced network analysis")
        
        # Start the application
        sys.exit(app.exec())
        
    except Exception as e:
        print(f"Error starting demo: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 