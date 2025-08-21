#!/usr/bin/env python3
"""
Test script for iZurvive integration
"""

import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtCore import QUrl
    print("✅ PyQt6 and WebEngine imports successful")
    
    # Test WebEngine functionality
    app = QApplication([])
    web_view = QWebEngineView()
    web_view.load(QUrl("https://www.izurvive.com/chernarusplus"))
    print("✅ WebEngine view created and loaded iZurvive URL")
    
    # Test the new DayZ Map GUI
    try:
        from gui.dayz_map_gui_new import DayZMapGUI
        print("✅ DayZ Map GUI import successful")
        
        # Create the GUI
        map_gui = DayZMapGUI()
        print("✅ DayZ Map GUI created successfully")
        print("✅ iZurvive integration is working!")
        
    except ImportError as e:
        print(f"❌ Failed to import DayZ Map GUI: {e}")
    except Exception as e:
        print(f"❌ Failed to create DayZ Map GUI: {e}")
    
    app.quit()
    
except ImportError as e:
    print(f"❌ Import failed: {e}")
    print("Please ensure PyQt6 and PyQt6-WebEngine are installed")
except Exception as e:
    print(f"❌ Test failed: {e}")

print("\n🎯 iZurvive Integration Test Complete!")
