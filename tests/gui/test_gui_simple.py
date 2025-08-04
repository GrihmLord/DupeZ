#!/usr/bin/env python3
"""
Simple GUI Test
Test if the GUI loads without responsive layout manager
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_simple_gui():
    """Test simple GUI creation"""
    print("Testing simple GUI creation...")
    
    try:
        # Create QApplication
        app = QApplication(sys.argv)
        print("QApplication created successfully")
        
        # Create simple window
        window = QMainWindow()
        window.setWindowTitle("Simple Test")
        window.setGeometry(100, 100, 400, 300)
        
        # Create central widget
        central_widget = QWidget()
        layout = QVBoxLayout()
        
        # Add a label
        label = QLabel("GUI Test - If you can see this, GUI is working!")
        layout.addWidget(label)
        
        central_widget.setLayout(layout)
        window.setCentralWidget(central_widget)
        
        # Show window
        window.show()
        print("Simple GUI window shown successfully")
        
        # Run the application
        return app.exec()
        
    except Exception as e:
        print(f"Error creating simple GUI: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(test_simple_gui()) 