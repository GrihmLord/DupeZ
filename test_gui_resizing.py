#!/usr/bin/env python3
"""
Test GUI Resizing Issues
Tests the GUI resizing functionality and identifies readability problems
"""

import sys
import os
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

def test_responsive_layout_manager():
    """Test the responsive layout manager with different screen sizes"""
    print("📱 Testing Responsive Layout Manager...")
    
    try:
        from app.gui.responsive_layout_manager import ResponsiveLayoutManager
        
        # Test different screen sizes
        test_sizes = {
            'small': (1024, 768),
            'medium': (1366, 768), 
            'large': (1920, 1080),
            'ultra': (2560, 1440),
            '4k': (3840, 2160)
        }
        
        for size_name, (width, height) in test_sizes.items():
            print(f"  - Testing {size_name} screen ({width}x{height})...")
            
            # Create layout manager
            layout_manager = ResponsiveLayoutManager()
            
            # Test font sizing
            base_font_size = 12
            responsive_font_size = layout_manager.get_responsive_font_size(base_font_size)
            print(f"    Font size: {base_font_size} -> {responsive_font_size}")
            
            # Test spacing
            base_spacing = 10
            responsive_spacing = layout_manager.get_responsive_spacing(base_spacing)
            print(f"    Spacing: {base_spacing} -> {responsive_spacing}")
            
            # Test margins
            base_margins = 8
            responsive_margins = layout_manager.get_responsive_margins(base_margins)
            print(f"    Margins: {base_margins} -> {responsive_margins}")
        
        return True
        
    except Exception as e:
        print(f"    ❌ Responsive layout manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_test_gui():
    """Create a test GUI to check resizing issues"""
    print("\n🖥️ Creating Test GUI for Resizing...")
    
    app = QApplication(sys.argv)
    
    # Create main window
    window = QMainWindow()
    window.setWindowTitle("GUI Resizing Test")
    window.setGeometry(100, 100, 1200, 800)
    
    # Create central widget
    central_widget = QWidget()
    window.setCentralWidget(central_widget)
    
    # Create layout
    layout = QVBoxLayout(central_widget)
    
    # Test 1: Responsive title
    title = QLabel("Enhanced Network Scanner Test")
    title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title.setStyleSheet("color: #ffffff; background-color: #2c3e50; padding: 10px; border-radius: 5px;")
    layout.addWidget(title)
    
    # Test 2: Control panel
    control_layout = QHBoxLayout()
    
    scan_button = QPushButton("Start Scan")
    scan_button.setFont(QFont("Arial", 12))
    scan_button.setStyleSheet("""
        QPushButton {
            background-color: #27ae60;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #2ecc71;
        }
    """)
    control_layout.addWidget(scan_button)
    
    stop_button = QPushButton("Stop Scan")
    stop_button.setFont(QFont("Arial", 12))
    stop_button.setStyleSheet("""
        QPushButton {
            background-color: #e74c3c;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #c0392b;
        }
    """)
    control_layout.addWidget(stop_button)
    
    layout.addLayout(control_layout)
    
    # Test 3: Device table
    table = QTableWidget()
    table.setColumnCount(8)
    table.setRowCount(5)
    
    # Set headers
    headers = ["IP Address", "MAC Address", "Hostname", "Vendor", "Device Type", "Interface", "Open Ports", "Status"]
    table.setHorizontalHeaderLabels(headers)
    
    # Set header styling
    header = table.horizontalHeader()
    header.setStyleSheet("""
        QHeaderView::section {
            background-color: #34495e;
            color: white;
            padding: 8px;
            border: 1px solid #2c3e50;
            font-weight: bold;
        }
    """)
    
    # Set column widths
    column_widths = [120, 140, 200, 150, 120, 100, 80, 80]
    for i, width in enumerate(column_widths):
        table.setColumnWidth(i, width)
    
    # Add sample data
    sample_data = [
        ["192.168.1.100", "AA:BB:CC:DD:EE:FF", "PS5-B9BDB0", "Sony Interactive", "PS5", "Wi-Fi", "80,443", "Online"],
        ["192.168.1.101", "11:22:33:44:55:66", "iPhone-User", "Apple Inc", "Mobile", "Wi-Fi", "443", "Online"],
        ["192.168.1.102", "AA:BB:CC:DD:EE:FF", "Laptop-User", "Dell Inc", "Laptop", "Wi-Fi", "80,443,22", "Online"],
        ["192.168.1.103", "FF:EE:DD:CC:BB:AA", "Unknown", "Unknown", "Unknown", "Wi-Fi", "", "Offline"],
        ["192.168.1.104", "12:34:56:78:9A:BC", "Router", "TP-Link", "Router", "Ethernet", "80,443,22", "Online"]
    ]
    
    for row, data in enumerate(sample_data):
        for col, value in enumerate(data):
            item = QTableWidgetItem(value)
            table.setItem(row, col, item)
    
    # Style the table
    table.setStyleSheet("""
        QTableWidget {
            background-color: #2b2b2b;
            color: #ffffff;
            gridline-color: #555555;
            border: 1px solid #555555;
        }
        QTableWidget::item {
            padding: 4px;
            border-bottom: 1px solid #444444;
        }
        QTableWidget::item:selected {
            background-color: #3498db;
        }
    """)
    
    layout.addWidget(table)
    
    # Test 4: Status bar
    status_label = QLabel("Ready to scan network")
    status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_label.setStyleSheet("color: #ffffff; background-color: #34495e; padding: 8px; border-radius: 3px;")
    layout.addWidget(status_label)
    
    # Test resize functionality
    def on_resize():
        """Handle resize events"""
        width = window.width()
        height = window.height()
        
        # Update status
        status_label.setText(f"Window size: {width}x{height}")
        
        # Adjust table column widths based on window size
        if width > 0:
            total_width = table.width()
            if total_width > 0:
                # Recalculate column widths
                new_widths = {
                    0: int(total_width * 0.12),  # IP Address
                    1: int(total_width * 0.15),  # MAC Address
                    2: int(total_width * 0.20),  # Hostname
                    3: int(total_width * 0.15),  # Vendor
                    4: int(total_width * 0.12),  # Device Type
                    5: int(total_width * 0.10),  # Interface
                    6: int(total_width * 0.08),  # Open Ports
                    7: int(total_width * 0.08)   # Status
                }
                
                for col, width in new_widths.items():
                    if col != 2:  # Don't resize stretch column
                        table.setColumnWidth(col, width)
    
    # Connect resize event
    window.resizeEvent = lambda event: on_resize()
    
    # Set dark theme
    app.setStyleSheet("""
        QMainWindow {
            background-color: #1e1e1e;
        }
        QWidget {
            background-color: #1e1e1e;
            color: #ffffff;
        }
    """)
    
    # Show window
    window.show()
    
    # Timer to test resize
    timer = QTimer()
    timer.timeout.connect(on_resize)
    timer.start(1000)  # Update every second
    
    print("    ✅ Test GUI created successfully")
    print("    📏 Try resizing the window to test responsive behavior")
    print("    🔍 Check if text remains readable at different sizes")
    
    return app.exec()

def main():
    """Main test function"""
    print("🚀 Starting GUI Resizing Tests")
    print("=" * 50)
    
    # Test responsive layout manager
    layout_ok = test_responsive_layout_manager()
    
    if layout_ok:
        print("\n✅ Responsive layout manager is working")
        print("🖥️ Launching test GUI...")
        
        # Create and run test GUI
        return create_test_gui()
    else:
        print("\n❌ Responsive layout manager has issues")
        return 1

if __name__ == "__main__":
    main() 