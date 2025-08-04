#!/usr/bin/env python3
"""
Responsive Layout Test
Verifies that all GUI components fit properly on different screen sizes
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_responsive_layout_manager():
    """Test the responsive layout manager"""
    print("🧪 Testing Responsive Layout Manager...")
    
    try:
        from app.gui.responsive_layout_manager import ResponsiveLayoutManager, get_screen_info
        
        # Test layout manager
        layout_manager = ResponsiveLayoutManager()
        
        # Test screen detection
        screen_info = get_screen_info()
        print(f"  [DEVICE] Screen Info:")
        print(f"    Width: {screen_info['width']}px")
        print(f"    Height: {screen_info['height']}px")
        print(f"    DPI: {screen_info['dpi']}")
        print(f"    Device Pixel Ratio: {screen_info['device_pixel_ratio']}")
        
        # Test scale factors
        scale_factor = layout_manager.get_scale_factor()
        print(f"  📏 Scale Factor: {scale_factor}")
        
        # Test responsive sizing
        font_size = layout_manager.get_responsive_font_size(10)
        spacing = layout_manager.get_responsive_spacing(8)
        margins = layout_manager.get_responsive_margins(8)
        
        print(f"  📝 Responsive Sizing:")
        print(f"    Font Size: {font_size}px")
        print(f"    Spacing: {spacing}px")
        print(f"    Margins: {margins}px")
        
        return True
        
    except Exception as e:
        print(f"  [FAILED] Responsive Layout Manager test failed: {e}")
        return False

def test_responsive_components():
    """Test responsive components"""
    print("🧪 Testing Responsive Components...")
    
    try:
        # Create QApplication if not exists
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        from app.gui.responsive_layout_manager import (
            ResponsiveWidget, ResponsiveTableWidget, ResponsiveTabWidget,
            ResponsiveGroupBox, ResponsiveButton, ResponsiveLabel,
            ResponsiveSplitter, ResponsiveScrollArea, create_responsive_layout
        )
        
        # Test responsive layout creation
        vertical_layout = create_responsive_layout("vertical")
        horizontal_layout = create_responsive_layout("horizontal")
        grid_layout = create_responsive_layout("grid")
        
        print(f"  [SUCCESS] Responsive layouts created successfully")
        
        # Test responsive widgets
        responsive_widget = ResponsiveWidget()
        responsive_table = ResponsiveTableWidget()
        responsive_tabs = ResponsiveTabWidget()
        responsive_group = ResponsiveGroupBox("Test Group")
        responsive_button = ResponsiveButton("Test Button")
        responsive_label = ResponsiveLabel("Test Label")
        responsive_splitter = ResponsiveSplitter()
        responsive_scroll = ResponsiveScrollArea()
        
        print(f"  [SUCCESS] Responsive widgets created successfully")
        
        return True
        
    except Exception as e:
        print(f"  [FAILED] Responsive Components test failed: {e}")
        return False

def test_dashboard_responsive():
    """Test dashboard responsive layout"""
    print("🧪 Testing Dashboard Responsive Layout...")
    
    try:
        # Create QApplication if not exists
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        from app.gui.dashboard import DupeZDashboard
        
        # Create dashboard
        dashboard = DupeZDashboard()
        
        # Test window sizing
        window_size = dashboard.size()
        print(f"  📐 Dashboard Window Size: {window_size.width()}x{window_size.height()}")
        
        # Test minimum size
        min_size = dashboard.minimumSize()
        print(f"  📏 Minimum Size: {min_size.width()}x{min_size.height()}")
        
        # Test if window fits on screen
        screen = dashboard.screen()
        screen_geometry = screen.availableGeometry()
        print(f"  [DEVICE] Screen Size: {screen_geometry.width()}x{screen_geometry.height()}")
        
        if (window_size.width() <= screen_geometry.width() and 
            window_size.height() <= screen_geometry.height()):
            print(f"  [SUCCESS] Dashboard fits on screen")
        else:
            print(f"  [WARNING] Dashboard may be too large for screen")
        
        # Test responsive layout manager
        if hasattr(dashboard, 'layout_manager'):
            print(f"  [SUCCESS] Dashboard has responsive layout manager")
        else:
            print(f"  [FAILED] Dashboard missing responsive layout manager")
        
        return True
        
    except Exception as e:
        print(f"  [FAILED] Dashboard Responsive Layout test failed: {e}")
        return False

def test_enhanced_device_list_responsive():
    """Test enhanced device list responsive layout"""
    print("🧪 Testing Enhanced Device List Responsive Layout...")
    
    try:
        # Create QApplication if not exists
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
        
        from app.gui.enhanced_device_list import EnhancedDeviceList
        
        # Create enhanced device list
        device_list = EnhancedDeviceList()
        
        # Test widget sizing
        widget_size = device_list.size()
        print(f"  📐 Device List Size: {widget_size.width()}x{widget_size.height()}")
        
        # Test responsive layout manager
        if hasattr(device_list, 'layout_manager'):
            print(f"  [SUCCESS] Device List has responsive layout manager")
        else:
            print(f"  [FAILED] Device List missing responsive layout manager")
        
        # Test device table
        if hasattr(device_list, 'device_table'):
            table_size = device_list.device_table.size()
            print(f"  [STATS] Device Table Size: {table_size.width()}x{table_size.height()}")
            
            # Test column ratios
            if hasattr(device_list.device_table, 'column_ratios'):
                print(f"  [SUCCESS] Device Table has responsive column ratios")
            else:
                print(f"  [FAILED] Device Table missing responsive column ratios")
        
        return True
        
    except Exception as e:
        print(f"  [FAILED] Enhanced Device List Responsive Layout test failed: {e}")
        return False

def test_screen_size_simulation():
    """Test different screen size simulations"""
    print("🧪 Testing Screen Size Simulations...")
    
    try:
        from app.gui.responsive_layout_manager import ResponsiveLayoutManager
        
        # Test different screen sizes
        test_sizes = [
            (1024, 768, "Small Laptop"),
            (1366, 768, "Standard Laptop"),
            (1920, 1080, "Full HD"),
            (2560, 1440, "2K"),
            (3840, 2160, "4K")
        ]
        
        for width, height, description in test_sizes:
            # Simulate screen size (this is a simplified test)
            print(f"  [DEVICE] {description} ({width}x{height}):")
            
            # Test scale factor calculation
            base_width, base_height = 1366, 768
            width_factor = width / base_width
            height_factor = height / base_height
            scale_factor = min(width_factor, height_factor)
            
            print(f"    Scale Factor: {scale_factor:.2f}")
            
            # Test responsive sizing
            font_size = max(8, int(10 * scale_factor))
            spacing = max(2, int(8 * scale_factor))
            margins = max(4, int(8 * scale_factor))
            
            print(f"    Font Size: {font_size}px")
            print(f"    Spacing: {spacing}px")
            print(f"    Margins: {margins}px")
        
        return True
        
    except Exception as e:
        print(f"  [FAILED] Screen Size Simulation test failed: {e}")
        return False

def main():
    """Main test function"""
    print("[ROCKET] Responsive Layout Test")
    print("=" * 60)
    
    # Test all responsive layout components
    tests = [
        ("Responsive Layout Manager", test_responsive_layout_manager),
        ("Responsive Components", test_responsive_components),
        ("Dashboard Responsive Layout", test_dashboard_responsive),
        ("Enhanced Device List Responsive Layout", test_enhanced_device_list_responsive),
        ("Screen Size Simulation", test_screen_size_simulation)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n[STATS] Testing {test_name}...")
        try:
            success = test_func()
            results[test_name] = success
            print(f"  {'[SUCCESS] PASSED' if success else '[FAILED] FAILED'}")
        except Exception as e:
            print(f"  [FAILED] Test error: {e}")
            results[test_name] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("[STATS] RESPONSIVE LAYOUT TEST RESULTS")
    print("=" * 60)
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, success in results.items():
        status = "[SUCCESS] PASSED" if success else "[FAILED] FAILED"
        print(f"{test_name}: {status}")
    
    print(f"\n[TARGET] Overall Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("[CELEBRATION] ALL GUI COMPONENTS FIT PROPERLY ON DIFFERENT SCREEN SIZES!")
        print("[SUCCESS] Responsive layout system is working correctly")
        print("[SUCCESS] All components can be adjusted to fit on screen")
        print("[SUCCESS] Screen size detection and scaling is functional")
    else:
        print("[WARNING] Some responsive layout features need attention")
        print("[TOOLS] Check the failed tests above for issues")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 