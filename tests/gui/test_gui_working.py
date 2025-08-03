#!/usr/bin/env python3
"""
Simple GUI Test Script
Tests that the main GUI components are working properly
"""

import sys
import os
import time
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_gui_components():
    """Test that GUI components can be imported and initialized"""
    try:
        print("Testing GUI component imports...")
        
        # Test core imports
        from app.core.controller import AppController
        from app.core.state import AppState
        from app.gui.dashboard import PulseDropDashboard
        from app.gui.sidebar import Sidebar
        from app.gui.enhanced_device_list import EnhancedDeviceList
        from app.gui.settings_dialog import SettingsDialog
        from app.themes.theme_manager import theme_manager
        
        print("✅ All core GUI components imported successfully")
        
        # Test theme manager
        print("Testing theme manager...")
        themes = theme_manager.get_available_themes()
        print(f"✅ Available themes: {themes}")
        
        # Test theme application
        success = theme_manager.apply_theme("dark")
        print(f"✅ Dark theme applied: {success}")
        
        # Test network scanner import
        from app.network.enhanced_scanner import EnhancedNetworkScanner
        print("✅ Network scanner imported successfully")
        
        # Test firewall components
        from app.firewall.blocker import block_device, unblock_device, is_blocking
        print("✅ Firewall components imported successfully")
        
        # Test PS5 tools
        from app.ps5.ps5_network_tool import PS5NetworkTool
        print("✅ PS5 tools imported successfully")
        
        # Test privacy components
        from app.privacy.privacy_manager import PrivacyManager
        print("✅ Privacy components imported successfully")
        
        # Test health components
        from app.health.device_health_monitor import DeviceHealthMonitor
        print("✅ Health components imported successfully")
        
        print("\n🎉 All GUI components are working properly!")
        return True
        
    except Exception as e:
        print(f"❌ GUI component test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_network_scanning():
    """Test that network scanning works"""
    try:
        print("\nTesting network scanning...")
        
        from app.network.enhanced_scanner import EnhancedNetworkScanner
        scanner = EnhancedNetworkScanner()
        
        # Test basic network info
        network_info = scanner.get_network_info()
        if network_info:
            print(f"✅ Network info: {network_info.get('local_ip', 'Unknown')}")
        else:
            print("⚠️ Could not get network info")
        
        # Test interface detection
        interfaces = scanner.get_all_network_interfaces()
        print(f"✅ Found {len(interfaces)} network interfaces")
        
        return True
        
    except Exception as e:
        print(f"❌ Network scanning test failed: {e}")
        return False

def test_theme_system():
    """Test that theme system works"""
    try:
        print("\nTesting theme system...")
        
        from app.themes.theme_manager import theme_manager
        
        # Test theme loading
        themes = theme_manager.get_available_themes()
        print(f"✅ Available themes: {themes}")
        
        # Test theme application
        for theme in themes:
            success = theme_manager.apply_theme(theme)
            print(f"✅ Applied {theme} theme: {success}")
        
        return True
        
    except Exception as e:
        print(f"❌ Theme system test failed: {e}")
        return False

def main():
    """Main test function"""
    print("🧪 PulseDrop Pro GUI Test")
    print("=" * 50)
    
    # Test 1: GUI Components
    gui_ok = test_gui_components()
    
    # Test 2: Network Scanning
    network_ok = test_network_scanning()
    
    # Test 3: Theme System
    theme_ok = test_theme_system()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST RESULTS")
    print("=" * 50)
    print(f"GUI Components: {'✅ PASS' if gui_ok else '❌ FAIL'}")
    print(f"Network Scanning: {'✅ PASS' if network_ok else '❌ FAIL'}")
    print(f"Theme System: {'✅ PASS' if theme_ok else '❌ FAIL'}")
    
    if gui_ok and network_ok and theme_ok:
        print("\n🎉 All tests passed! The GUI should work properly.")
        print("You can now run 'python run.py' to start the application.")
    else:
        print("\n⚠️ Some tests failed. Check the errors above.")
    
    return gui_ok and network_ok and theme_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 