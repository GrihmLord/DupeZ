#!/usr/bin/env python3
"""
Minimal GUI Test
Test minimal imports to isolate the issue
"""

import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_minimal_imports():
    """Test minimal imports"""
    print("Testing minimal imports...")
    
    try:
        # Test 1: Basic PyQt6 imports
        print("1. Testing PyQt6 imports...")
        from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
        print("   ✓ PyQt6 imports successful")
        
        # Test 2: Import dashboard class (without instantiation)
        print("2. Testing dashboard class import...")
        from app.gui.dashboard import DupeZDashboard
        print("   ✓ Dashboard class import successful")
        
        # Test 3: Create QApplication
        print("3. Testing QApplication creation...")
        app = QApplication(sys.argv)
        print("   ✓ QApplication created successfully")
        
        # Test 4: Create dashboard instance
        print("4. Testing dashboard instantiation...")
        dashboard = DupeZDashboard()
        print("   ✓ Dashboard instantiation successful")
        
        # Test 5: Show dashboard
        print("5. Testing dashboard display...")
        dashboard.show()
        print("   ✓ Dashboard displayed successfully")
        
        return app.exec()
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(test_minimal_imports()) 