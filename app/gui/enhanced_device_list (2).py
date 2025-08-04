# app/gui/enhanced_device_list.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QListWidget, QListWidgetItem,
                             QProgressBar, QTextEdit, QSplitter, QFrame,
                             QHeaderView, QTableWidget, QTableWidgetItem,
                             QComboBox, QSpinBox, QCheckBox, QGroupBox,
                             QMenu, QGridLayout, QLineEdit)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon, QAction
import time
from typing import List, Dict, Optional

from app.network.enhanced_scanner import get_enhanced_scanner, cleanup_enhanced_scanner
from app.logs.logger import log_info, log_error

class EnhancedDeviceList(QWidget):
    """Enhanced device list with Angry IP Scanner-like features"""
    
    # Signals
    device_selected = pyqtSignal(dict)  # Selected device
    device_blocked = pyqtSignal(str, bool)  # IP, blocked status
    scan_started = pyqtSignal()
    scan_finished = pyqtSignal(list)  # All devices
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.scanner = None  # Initialize later
        self.devices = []
        self.scanning = False  # Add scanning state
        self.setup_ui()
        self.connect_signals()
        
        # Initialize scanner after UI is set up - IMPROVED
        self._initialize_scanner()
        
        # Connect resize event for responsive design
        self.resizeEvent = self.on_resize
        
    def _initialize_scanner(self):
        """Initialize the enhanced network scanner"""
        try:
            if not self.scanner:
                from app.network.enhanced_scanner import EnhancedNetworkScanner
                self.scanner = EnhancedNetworkScanner()
                log_info("Enhanced scanner initialized successfully for GUI component")
                
                # Connect signals
                self.scanner.device_found.connect(self.on_device_found)
                self.scanner.scan_complete.connect(self.on_scan_complete)
                self.scanner.scan_error.connect(self.on_scan_error)
                self.scanner.status_update.connect(self.update_status)
                
        except Exception as e:
            log_error(f"Failed to initialize scanner: {e}")
            self.scanner = None
    
    def setup_ui(self):
        """Setup the enhanced device list UI with modern typography and clean design"""
        # Import responsive layout manager
        from app.gui.responsive_layout_manager import ResponsiveLayoutManager, create_responsive_layout, ResponsiveLabel, ResponsiveButton, ResponsiveTableWidget
        
        # Initialize responsive layout manager
        self.layout_manager = ResponsiveLayoutManager()
        
        # Create responsive layout
        layout = create_responsive_layout("vertical")
        self.setLayout(layout)
        
        # ===== HEADER SECTION =====
        header_layout = create_responsive_layout("horizontal")
        
        # Title with modern typography - CLEAN DESIGN
        title = ResponsiveLabel("Enhanced Network Scanner")
        title_font_size = max(16, self.layout_manager.get_responsive_font_size(18))
        title.setFont(QFont("Segoe UI", title_font_size, QFont.Weight.DemiBold))
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title.setStyleSheet(f"""
            color: #ffffff;
            padding: {max(12, self.layout_manager.get_responsive_spacing(12))}px 16px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 8px;
            margin-right: {max(12, self.layout_manager.get_responsive_spacing(12))}px;
            min-height: {max(36, self.layout_manager.get_responsive_spacing(36))}px;
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            letter-spacing: 0.5px;
        """)
        header_layout.addWidget(title)
        
        # Quick stats panel
        stats_panel = self.create_quick_stats_panel()
        header_layout.addWidget(stats_panel)
        
        layout.addLayout(header_layout)
        
        # ===== CONTROL SECTION =====
        control_section = self.create_enhanced_control_section()
        layout.addWidget(control_section)
        
        # ===== PROGRESS SECTION =====
        progress_section = self.create_progress_section()
        layout.addWidget(progress_section)
        
        # ===== MAIN CONTENT SECTION =====
        main_content = create_responsive_layout("horizontal")
        
        # Left panel - Device table (responsive proportion) - IMPROVED SIZING
        left_panel = self.create_device_table_panel()
        main_content.addWidget(left_panel, 3)  # Takes 3/5 of space (reduced from 4/5)
        
        # Right panel - Device details and actions (responsive proportion)
        right_panel = self.create_device_details_panel()
        main_content.addWidget(right_panel, 2)  # Takes 2/5 of space (increased from 1/5)
        
        layout.addLayout(main_content)
        
        # ===== STATUS SECTION =====
        status_section = self.create_status_section()
        layout.addWidget(status_section)
        
    def on_resize(self, event):
        """Handle resize events for responsive design - IMPROVED"""
        super().resizeEvent(event)
        
        # Update table column widths when window is resized
        if hasattr(self, 'device_table') and self.device_table:
            total_width = self.device_table.width()
            if total_width > 0:
                # IMPROVED: Better column width calculations with minimum sizes
                min_column_width = 50  # Reduced from 60 for more compact design
                
                # Calculate responsive column widths with better proportions
                column_widths = {
                    0: max(min_column_width, int(total_width * 0.15)),  # IP Address (increased)
                    1: max(min_column_width, int(total_width * 0.18)),  # MAC Address (increased)
                    2: max(min_column_width * 2, int(total_width * 0.20)),  # Hostname (reduced)
                    3: max(min_column_width, int(total_width * 0.15)),  # Vendor
                    4: max(min_column_width, int(total_width * 0.12)),  # Device Type
                    5: max(min_column_width, int(total_width * 0.10)),  # Interface
                    6: max(min_column_width, int(total_width * 0.05)),  # Open Ports (reduced)
                    7: max(min_column_width, int(total_width * 0.05))   # Status
                }
                
                # Apply new column widths
                header = self.device_table.horizontalHeader()
                for col, width in column_widths.items():
                    if col != 2:  # Don't resize stretch column
                        self.device_table.setColumnWidth(col, width)
                
                # Update font sizes for better readability
                self.update_table_font_sizes()
    
    def update_table_font_sizes(self):
        """Update table font sizes with modern typography"""
        if hasattr(self, 'device_table') and self.device_table:
            # Calculate responsive font size - modern typography
            base_font_size = 10  # Increased from 8 for better readability
            responsive_font_size = max(9, self.layout_manager.get_responsive_font_size(base_font_size))
            
            # Update table font with modern typography
            table_font = self.device_table.font()
            table_font.setFamily("Segoe UI")
            table_font.setPointSize(responsive_font_size)
            table_font.setWeight(QFont.Weight.Normal)
            self.device_table.setFont(table_font)
            
            # Update header font with modern typography
            header = self.device_table.horizontalHeader()
            header_font = header.font()
            header_font.setFamily("Segoe UI")
            header_font.setPointSize(max(11, responsive_font_size + 1))  # Header slightly larger
            header_font.setWeight(QFont.Weight.DemiBold)
            header.setFont(header_font)
    
    def create_quick_stats_panel(self) -> QWidget:
        """Create a compact quick stats panel with modern typography"""
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                border-radius: 8px;
                padding: 8px 12px;
                margin: 4px;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setSpacing(16)  # Increased spacing for better readability
        
        # Device count with modern typography
        self.device_count_label = QLabel("Devices: 0")
        self.device_count_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self.device_count_label.setStyleSheet("""
            color: #ffffff;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            letter-spacing: 0.3px;
        """)
        layout.addWidget(self.device_count_label)
        
        # PS5 count with modern typography
        self.ps5_count_label = QLabel("PS5: 0")
        self.ps5_count_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self.ps5_count_label.setStyleSheet("""
            color: #ffffff;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            letter-spacing: 0.3px;
        """)
        layout.addWidget(self.ps5_count_label)
        
        # Blocked count with modern typography
        self.blocked_count_label = QLabel("Blocked: 0")
        self.blocked_count_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self.blocked_count_label.setStyleSheet("""
            color: #ffffff;
            font-weight: 600;
            font-size: 11px;
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            letter-spacing: 0.3px;
        """)
        layout.addWidget(self.blocked_count_label)
        
        panel.setLayout(layout)
        return panel
        
    def create_enhanced_control_section(self) -> QWidget:
        """Create an enhanced control section with modern typography"""
        section = QGroupBox("Control Panel")
        section.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        section.setStyleSheet("""
            QGroupBox {
                font-weight: 600;
                font-size: 12px;
                border: 2px solid #e1e8ed;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 12px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                letter-spacing: 0.5px;
            }
        """)
        
        layout = QGridLayout()
        layout.setSpacing(12)  # Increased spacing for better readability
        
        # Row 1: Scan controls with modern typography
        self.scan_button = QPushButton("Start Network Scan")
        self.scan_button.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.scan_button.setStyleSheet("""
            QPushButton {
                background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
                color: white;
                border: none;
                padding: 10px 16px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 10px;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                min-height: 28px;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: linear-gradient(135deg, #45a049 0%, #3d8b40 100%);
            }
            QPushButton:pressed {
                background: linear-gradient(135deg, #3d8b40 0%, #2e7d32 100%);
            }
        """)
        layout.addWidget(self.scan_button, 0, 0)
        
        self.stop_button = QPushButton("Stop Scan")
        self.stop_button.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background: linear-gradient(135deg, #f44336 0%, #da190b 100%);
                color: white;
                border: none;
                padding: 10px 16px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 10px;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                min-height: 28px;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: linear-gradient(135deg, #da190b 0%, #c62828 100%);
            }
            QPushButton:pressed {
                background: linear-gradient(135deg, #c62828 0%, #b71c1c 100%);
            }
            QPushButton:disabled {
                background: linear-gradient(135deg, #95a5a6 0%, #7f8c8d 100%);
                color: #ecf0f1;
            }
        """)
        layout.addWidget(self.stop_button, 0, 1)
        
        # Row 2: Blocking controls with modern typography
        self.block_selected_btn = QPushButton("Block Selected")
        self.block_selected_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.block_selected_btn.setStyleSheet("""
            QPushButton {
                background: linear-gradient(135deg, #FF9800 0%, #F57C00 100%);
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 10px;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                min-height: 26px;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: linear-gradient(135deg, #F57C00 0%, #EF6C00 100%);
            }
        """)
        layout.addWidget(self.block_selected_btn, 1, 0)
        
        self.unblock_selected_btn = QPushButton("Unblock Selected")
        self.unblock_selected_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.unblock_selected_btn.setStyleSheet("""
            QPushButton {
                background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 10px;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                min-height: 26px;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: linear-gradient(135deg, #45a049 0%, #3d8b40 100%);
            }
        """)
        layout.addWidget(self.unblock_selected_btn, 1, 1)
        
        # Row 3: Advanced controls with modern typography
        self.drop_internet_btn = QPushButton("Drop Internet")
        self.drop_internet_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.drop_internet_btn.setStyleSheet("""
            QPushButton {
                background: linear-gradient(135deg, #9C27B0 0%, #7B1FA2 100%);
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 10px;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                min-height: 26px;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: linear-gradient(135deg, #7B1FA2 0%, #6A1B9A 100%);
            }
        """)
        layout.addWidget(self.drop_internet_btn, 2, 0)
        
        # Disconnect button for DayZ duping with modern typography
        self.internet_drop_button = QPushButton("Disconnect")
        self.internet_drop_button.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.internet_drop_button.setStyleSheet("""
            QPushButton {
                background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
                font-size: 10px;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                min-height: 26px;
                letter-spacing: 0.3px;
            }
            QPushButton:hover {
                background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%);
            }
        """)
        layout.addWidget(self.internet_drop_button, 2, 1)
        
        self.clear_blocks_btn = QPushButton("🧹 Clear All Blocks")
        self.clear_blocks_btn.setStyleSheet("""
            QPushButton {
                background-color: #607D8B;
                color: white;
                border: none;
                padding: 6px 10px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #455A64;
            }
        """)
        layout.addWidget(self.clear_blocks_btn, 2, 2)
        
        section.setLayout(layout)
        return section
        
    def create_progress_section(self) -> QWidget:
        """Create a compact progress section"""
        section = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(4)  # Reduced spacing
        
        # Progress bar - Made more compact
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #404040;
                border-radius: 4px;
                text-align: center;
                font-weight: bold;
                height: 18px;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Progress label - Made more compact
        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setStyleSheet("""
            color: #888888;
            font-size: 9px;
            padding: 2px;
        """)
        layout.addWidget(self.progress_label)
        
        section.setLayout(layout)
        return section
        
    def create_device_table_panel(self) -> QWidget:
        """Create the device table panel with modern typography and clean design"""
        from app.gui.responsive_layout_manager import ResponsiveGroupBox, ResponsiveLabel, ResponsiveTableWidget, create_responsive_layout
        
        panel = ResponsiveGroupBox("Network Devices")
        panel.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        panel.setStyleSheet(f"""
            QGroupBox {{
                border: 2px solid #e1e8ed;
                border-radius: 10px;
                margin-top: {max(12, self.layout_manager.get_responsive_spacing(12))}px;
                padding-top: {max(12, self.layout_manager.get_responsive_spacing(12))}px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {max(12, self.layout_manager.get_responsive_spacing(12))}px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: {max(13, self.layout_manager.get_responsive_font_size(14))}pt;
                font-weight: 600;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                letter-spacing: 0.5px;
            }}
        """)
        
        layout = create_responsive_layout("vertical")
        
        # Search bar with modern typography
        search_layout = create_responsive_layout("horizontal")
        
        search_label = ResponsiveLabel("Search:")
        search_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        search_label.setStyleSheet(f"""
            color: #ffffff; 
            font-weight: 600; 
            font-size: {max(11, self.layout_manager.get_responsive_font_size(12))}pt;
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            margin-right: {max(10, self.layout_manager.get_responsive_spacing(10))}px;
            letter-spacing: 0.3px;
        """)
        search_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search devices by IP, MAC, or hostname...")
        self.search_input.setFont(QFont("Segoe UI", 10, QFont.Weight.Normal))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 0.9);
                border: 2px solid #e1e8ed;
                border-radius: 6px;
                padding: {max(8, self.layout_manager.get_responsive_spacing(8))}px 12px;
                color: #2c3e50;
                font-size: {max(10, self.layout_manager.get_responsive_font_size(11))}pt;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                min-height: {max(24, self.layout_manager.get_responsive_spacing(24))}px;
                letter-spacing: 0.2px;
            }}
            QLineEdit:focus {{
                border: 2px solid #667eea;
                background-color: #ffffff;
            }}
            QLineEdit::placeholder {{
                color: #95a5a6;
                font-style: italic;
            }}
        """)
        search_layout.addWidget(self.search_input)
        
        layout.addLayout(search_layout)
        
        # Device table with modern typography
        self.device_table = ResponsiveTableWidget()
        self.setup_device_table()
        
        # IMPROVED: Set responsive column ratios with better proportions
        self.device_table.set_column_ratios({
            0: 0.15,  # IP Address (increased)
            1: 0.18,  # MAC Address (increased)
            2: 0.20,  # Hostname (reduced from 0.25)
            3: 0.15,  # Vendor
            4: 0.12,  # Device Type
            5: 0.10,  # Interface
            6: 0.05,  # Open Ports (reduced)
            7: 0.05   # Status
        })
        
        # IMPROVED: Modern table styling with clean typography
        self.device_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: #ffffff;
                border: 2px solid #e1e8ed;
                border-radius: 8px;
                gridline-color: #ecf0f1;
                font-size: {max(10, self.layout_manager.get_responsive_font_size(11))}pt;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                selection-background-color: #667eea;
                selection-color: #ffffff;
            }}
            QTableWidget::item {{
                padding: {max(6, self.layout_manager.get_responsive_spacing(6))}px 8px;
                border: none;
                color: #2c3e50;
                font-weight: 400;
                letter-spacing: 0.2px;
            }}
            QTableWidget::item:selected {{
                background-color: #667eea;
                color: #ffffff;
                font-weight: 500;
            }}
            QTableWidget::item:hover {{
                background-color: #f8f9fa;
            }}
            QHeaderView::section {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: #ffffff;
                padding: {max(8, self.layout_manager.get_responsive_spacing(8))}px 10px;
                border: none;
                font-weight: 600;
                font-size: {max(11, self.layout_manager.get_responsive_font_size(12))}pt;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                letter-spacing: 0.3px;
            }}
            QHeaderView::section:hover {{
                background: linear-gradient(135deg, #5a6fd8 0%, #6a4190 100%);
            }}
            QScrollBar:vertical {{
                background-color: #ecf0f1;
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #bdc3c7;
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #95a5a6;
            }}
        """)
        layout.addWidget(self.device_table)
        
        panel.setLayout(layout)
        return panel
        
    def create_device_details_panel(self) -> QWidget:
        """Create the device details panel with better organization and more space"""
        panel = QGroupBox("[STATS] Device Details")
        panel.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #555555;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px 0 3px;
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setSpacing(8)  # Reduced spacing for more content
        
        # Selected device info - Made larger
        self.selected_device_label = QLabel("No device selected")
        self.selected_device_label.setStyleSheet("""
            color: #888888;
            font-size: 11px;
            padding: 12px;
            background-color: #3a3a3a;
            border-radius: 4px;
            min-height: 60px;
        """)
        self.selected_device_label.setWordWrap(True)
        layout.addWidget(self.selected_device_label)
        
        # Device actions - Made larger
        actions_group = QGroupBox("⚡ Quick Actions")
        actions_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #555555;
                border-radius: 4px;
                margin-top: 6px;
                padding-top: 6px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 2px 0 2px;
                color: #ffffff;
            }
        """)
        
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)  # Reduced spacing
        
        self.ping_btn = QPushButton("🏓 Ping Device")
        self.ping_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 10px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        actions_layout.addWidget(self.ping_btn)
        
        self.port_scan_btn = QPushButton("[SCAN] Port Scan")
        self.port_scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 8px 10px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        actions_layout.addWidget(self.port_scan_btn)
        
        self.copy_ip_btn = QPushButton("[COPY] Copy IP")
        self.copy_ip_btn.setStyleSheet("""
            QPushButton {
                background-color: #607D8B;
                color: white;
                border: none;
                padding: 8px 10px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #455A64;
            }
        """)
        actions_layout.addWidget(self.copy_ip_btn)
        
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)
        
        # Disconnect methods - Made larger and better organized
        disconnect_group = QGroupBox("[GAMING] Disconnect Methods")
        disconnect_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #555555;
                border-radius: 4px;
                margin-top: 6px;
                padding-top: 6px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 6px;
                padding: 0 2px 0 2px;
                color: #ffffff;
            }
        """)
        
        disconnect_layout = QVBoxLayout()
        disconnect_layout.setSpacing(4)  # Reduced spacing for more checkboxes
        
        # WinDivert (Prioritized)
        self.windivert_cb = QCheckBox("[SHIELD] WinDivert (Prioritized)")
        self.windivert_cb.setChecked(True)
        self.windivert_cb.setStyleSheet("""
            color: #00ff00;
            font-weight: bold;
            font-size: 9px;
            padding: 2px;
        """)
        disconnect_layout.addWidget(self.windivert_cb)
        
        self.udp_interrupt_cb = QCheckBox("UDP Interrupt")
        self.udp_interrupt_cb.setChecked(True)
        self.udp_interrupt_cb.setStyleSheet("color: #ffffff; font-size: 9px; padding: 2px;")
        disconnect_layout.addWidget(self.udp_interrupt_cb)
        
        self.icmp_disconnect_cb = QCheckBox("ICMP Disconnect")
        self.icmp_disconnect_cb.setChecked(True)
        self.icmp_disconnect_cb.setStyleSheet("color: #ffffff; font-size: 9px; padding: 2px;")
        disconnect_layout.addWidget(self.icmp_disconnect_cb)
        
        self.dns_spoofing_cb = QCheckBox("DNS Spoofing")
        self.dns_spoofing_cb.setChecked(True)
        self.dns_spoofing_cb.setStyleSheet("color: #ffffff; font-size: 9px; padding: 2px;")
        disconnect_layout.addWidget(self.dns_spoofing_cb)
        
        self.arp_poison_cb = QCheckBox("ARP Poisoning")
        self.arp_poison_cb.setChecked(True)
        self.arp_poison_cb.setStyleSheet("color: #ffffff; font-size: 9px; padding: 2px;")
        disconnect_layout.addWidget(self.arp_poison_cb)
        
        disconnect_group.setLayout(disconnect_layout)
        layout.addWidget(disconnect_group)
        
        # Add some stretch to push content to top
        layout.addStretch()
        
        panel.setLayout(layout)
        return panel
        
    def create_status_section(self) -> QWidget:
        """Create a compact status section"""
        section = QWidget()
        section.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setSpacing(8)  # Reduced spacing
        
        # Status bar - Made more compact
        self.status_label = QLabel("Ready to scan network")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setStyleSheet("""
            color: #4CAF50; 
            font-weight: bold; 
            padding: 3px;
            background-color: rgba(76, 175, 80, 0.1);
            border-radius: 3px;
            font-size: 10px;
        """)
        layout.addWidget(self.status_label)
        
        # Blocking status indicator - Made more compact
        self.blocking_status = QLabel("🔒 Blocking: Inactive")
        self.blocking_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.blocking_status.setStyleSheet("""
            color: #FF9800; 
            font-weight: bold; 
            padding: 3px;
            background-color: rgba(255, 152, 0, 0.1);
            border-radius: 3px;
            font-size: 10px;
        """)
        layout.addWidget(self.blocking_status)
        
        section.setLayout(layout)
        return section
    
    def setup_device_table(self):
        """Setup the device table with responsive columns - IMPROVED"""
        # Set up table headers
        headers = [
            "IP Address", "MAC Address", "Hostname", "Vendor", 
            "Device Type", "Interface", "Open Ports", "Status"
        ]
        self.device_table.setColumnCount(len(headers))
        self.device_table.setHorizontalHeaderLabels(headers)
        
        # Set up table properties
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)  # Allow multiple selection
        self.device_table.setSortingEnabled(True)
        self.device_table.setWordWrap(True)  # Enable word wrapping
        self.device_table.setShowGrid(True)
        self.device_table.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Set responsive column widths - IMPROVED
        header = self.device_table.horizontalHeader()
        header.setStretchLastSection(False)
        
        # IMPROVED: Better initial column width calculation
        total_width = max(1200, self.device_table.width())  # Minimum width of 1200px
        min_column_width = 50  # Reduced from 60 for more compact design
        
        column_widths = {
            0: max(min_column_width, int(total_width * 0.15)),  # IP Address (increased)
            1: max(min_column_width, int(total_width * 0.18)),  # MAC Address (increased)
            2: max(min_column_width * 2, int(total_width * 0.20)),  # Hostname (reduced)
            3: max(min_column_width, int(total_width * 0.15)),  # Vendor
            4: max(min_column_width, int(total_width * 0.12)),  # Device Type
            5: max(min_column_width, int(total_width * 0.10)),  # Interface
            6: max(min_column_width, int(total_width * 0.05)),  # Open Ports (reduced)
            7: max(min_column_width, int(total_width * 0.05))   # Status
        }
        
        # Apply column widths with improved resize modes
        for col, width in column_widths.items():
            self.device_table.setColumnWidth(col, width)
            if col == 2:  # Hostname column stretches
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)  # Allow manual resizing
        
        # IMPROVED: Set responsive font sizes
        self.update_table_font_sizes()
        
        # IMPROVED: Enhanced table styling for better readability
        self.device_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: #2d2d2d;
                color: #ffffff;
                gridline-color: #404040;
                border: 2px solid #404040;
                border-radius: 6px;
                font-size: {max(9, self.layout_manager.get_responsive_font_size(10))}pt;
                selection-background-color: #4CAF50;
                selection-color: #ffffff;
            }}
            QTableWidget::item {{
                padding: {max(4, self.layout_manager.get_responsive_spacing(6))}px;
                border-bottom: 1px solid #404040;
            }}
            QTableWidget::item:selected {{
                background-color: #4CAF50;
                color: #ffffff;
            }}
            QHeaderView::section {{
                background-color: #3d3d3d;
                color: #ffffff;
                padding: {max(6, self.layout_manager.get_responsive_spacing(8))}px;
                border: 1px solid #404040;
                font-weight: bold;
                font-size: {max(10, self.layout_manager.get_responsive_font_size(11))}pt;
            }}
            QHeaderView::section:hover {{
                background-color: #505050;
            }}
            QScrollBar:vertical {{
                background-color: #2d2d2d;
                width: {max(12, self.layout_manager.get_responsive_spacing(14))}px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #4CAF50;
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #45a049;
            }}
            QScrollBar:horizontal {{
                background-color: #2d2d2d;
                height: {max(12, self.layout_manager.get_responsive_spacing(14))}px;
                border-radius: 6px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: #4CAF50;
                border-radius: 6px;
                min-width: 20px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: #45a049;
            }}
        """)
        
        # Connect selection signal
        self.device_table.itemSelectionChanged.connect(self.on_device_selected)
        
        # Connect double-click signal for toggle blocking
        self.device_table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        
        # Connect context menu
        self.device_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self.show_context_menu)
    
    def connect_signals(self):
        """Connect all signals for the enhanced device list"""
        # Scan controls
        self.scan_button.clicked.connect(self.start_scan)
        self.stop_button.clicked.connect(self.stop_scan)
        
        # Blocking controls
        self.block_selected_btn.clicked.connect(self.block_selected)
        self.unblock_selected_btn.clicked.connect(self.unblock_selected)
        self.drop_internet_btn.clicked.connect(self.toggle_internet_drop)
        self.internet_drop_button.clicked.connect(self.toggle_internet_drop)
        self.clear_blocks_btn.clicked.connect(self.clear_all_blocks)
        
        # Device actions
        self.ping_btn.clicked.connect(self.ping_selected_device)
        self.port_scan_btn.clicked.connect(self.port_scan_selected_device)
        self.copy_ip_btn.clicked.connect(self.copy_selected_ip)
        
        # Table signals
        self.device_table.itemSelectionChanged.connect(self.on_device_selected)
        self.device_table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.device_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self.show_context_menu)
        
        # Search functionality
        self.search_input.textChanged.connect(self.filter_devices_by_search)
        
    def ping_selected_device(self):
        """Ping the currently selected device"""
        selected_items = self.device_table.selectedItems()
        if not selected_items:
            self.update_status("No device selected for ping")
            return
            
        row = selected_items[0].row()
        ip = self.device_table.item(row, 1).text()  # IP is in column 1
        self.ping_device(ip)
        
    def port_scan_selected_device(self):
        """Port scan the currently selected device"""
        selected_items = self.device_table.selectedItems()
        if not selected_items:
            self.update_status("No device selected for port scan")
            return
            
        row = selected_items[0].row()
        ip = self.device_table.item(row, 1).text()  # IP is in column 1
        self.port_scan_device(ip)
        
    def copy_selected_ip(self):
        """Copy the IP of the selected device to clipboard"""
        selected_items = self.device_table.selectedItems()
        if not selected_items:
            self.update_status("No device selected to copy IP")
            return
            
        row = selected_items[0].row()
        ip = self.device_table.item(row, 1).text()  # IP is in column 1
        self.copy_ip_to_clipboard(ip)
        
    def update_quick_stats(self):
        """Update the quick stats panel"""
        total_devices = len(self.devices)
        ps5_count = sum(1 for device in self.devices if self._is_ps5_device(device))
        blocked_count = sum(1 for device in self.devices if device.get('blocked', False))
        
        self.device_count_label.setText(f"Devices: {total_devices}")
        self.ps5_count_label.setText(f"PS5: {ps5_count}")
        self.blocked_count_label.setText(f"Blocked: {blocked_count}")
        
        if hasattr(self, 'scanning') and self.scanning:
            self.scan_status_label.setText("Status: Scanning")
            self.scan_status_label.setStyleSheet("""
                color: #FF9800;
                font-weight: bold;
                font-size: 12px;
            """)
        else:
            self.scan_status_label.setText("Status: Ready")
            self.scan_status_label.setStyleSheet("""
                color: #2196F3;
                font-weight: bold;
                font-size: 12px;
            """)
            
    def update_selected_device_info(self):
        """Update the selected device information panel"""
        selected_items = self.device_table.selectedItems()
        if not selected_items:
            self.selected_device_label.setText("No device selected")
            return
            
        row = selected_items[0].row()
        device = self.devices[row] if row < len(self.devices) else None
        
        if device:
            info_text = f"""
IP: {device.get('ip', 'Unknown')}
MAC: {device.get('mac', 'Unknown')}
Hostname: {device.get('hostname', 'Unknown')}
Vendor: {device.get('vendor', 'Unknown')}
Status: {'[BLOCKED]' if device.get('blocked', False) else '[ACTIVE]'}
Type: {device.get('device_type', 'Unknown')}
            """.strip()
            self.selected_device_label.setText(info_text)
        else:
            self.selected_device_label.setText("Device information not available")
            
    def on_device_selected(self):
        """Handle device selection"""
        self.update_selected_device_info()
        
    def update_progress(self, current: int, total: int):
        """Update progress bar and label"""
        if total > 0:
            percentage = (current / total) * 100
            self.progress_bar.setValue(int(percentage))
            self.progress_label.setText(f"Scanning: {current}/{total} ({percentage:.1f}%)")
            
    def start_scan(self):
        """Start the network scan with enhanced UI feedback - FIXED"""
        try:
            # Ensure scanner is initialized
            if not self.scanner:
                self._initialize_scanner()
                if not self.scanner:
                    self.on_scan_error("Scanner not initialized")
                    return
            
            self.scanning = True
            self.scan_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.progress_label.setText("Initializing scan...")
            self.update_quick_stats()
            
            # Clear previous results
            self.device_table.setRowCount(0)
            self.devices = []
            
            # Ensure signals are connected
            if self.scanner:
                # Disconnect and reconnect signals to avoid duplicates
                try:
                    self.scanner.device_found.disconnect()
                except:
                    pass
                self.scanner.device_found.connect(self.on_device_found)
                
                try:
                    self.scanner.scan_complete.disconnect()
                except:
                    pass
                self.scanner.scan_complete.connect(self.on_scan_complete)
                
                try:
                    self.scanner.scan_error.disconnect()
                except:
                    pass
                self.scanner.scan_error.connect(self.on_scan_error)
                
                try:
                    self.scanner.status_update.disconnect()
                except:
                    pass
                self.scanner.status_update.connect(self.update_status)
            
            # Start the scan using the correct method signature
            if self.scanner:
                # Use threading to avoid blocking the GUI
                import threading
                scan_thread = threading.Thread(target=self._run_scan_thread)
                scan_thread.daemon = True
                scan_thread.start()
            else:
                self.on_scan_error("Scanner not initialized")
                
        except Exception as e:
            log_error(f"Error starting scan: {e}")
            self.on_scan_error(f"Error starting scan: {e}")
    
    def _run_scan_thread(self):
        """Run the scan in a separate thread"""
        try:
            if self.scanner:
                # Start the scan with the correct parameters
                devices = self.scanner.scan_network("192.168.1.0/24", quick_scan=True)
                
                # The scan_complete signal will be emitted automatically
                # and handled by on_scan_complete method
                log_info(f"Scan completed with {len(devices)} devices found")
            else:
                self.on_scan_error("Scanner not available")
        except Exception as e:
            log_error(f"Error in scan thread: {e}")
            self.on_scan_error(f"Error in scan thread: {e}")
    
    def on_device_found(self, device: dict):
        """Handle when a device is found during scanning"""
        try:
            self.devices.append(device)
            self.add_device_to_table(device)
            self.update_quick_stats()
            
            # Update progress
            total_devices = len(self.devices)
            self.update_progress(total_devices, total_devices + 1)  # Estimate total
            
        except Exception as e:
            log_error(f"Error handling device found: {e}")
    
    def stop_scan(self):
        """Stop the network scan"""
        self.scanning = False
        self.scan_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Scan stopped")
        self.update_quick_stats()
        
        # Stop the scanner
        if self.scanner:
            self.scanner.stop_scan()
            
    def on_scan_complete(self, devices: List[Dict]):
        """Handle scan completion"""
        try:
            self.scanning = False
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            self.progress_bar.setValue(100)
            self.progress_label.setText("Scan completed")
            
            # Update devices list
            self.devices = devices if devices else []
            
            # Clear table and add all devices
            self.device_table.setRowCount(0)
            for device in self.devices:
                self.add_device_to_table(device)
            
            # Update stats and status
            self.update_quick_stats()
            device_count = len(self.devices)
            ps5_count = len([d for d in self.devices if d.get('is_ps5', False)])
            
            status_msg = f"Scan completed: {device_count} devices found"
            if ps5_count > 0:
                status_msg += f" ({ps5_count} PS5 devices)"
            
            self.update_status(f"[SUCCESS] {status_msg}")
            log_info(f"Scan completed successfully with {device_count} devices")
            
        except Exception as e:
            log_error(f"Error handling scan completion: {e}")
            self.on_scan_error(f"Error handling scan completion: {e}")
    
    def on_scan_error(self, error_msg: str):
        """Handle scan errors"""
        try:
            self.scanning = False
            self.scan_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            self.progress_label.setText("Scan failed")
            self.update_status(f"Scan error: {error_msg}")
            self.update_quick_stats()
            
        except Exception as e:
            log_error(f"Error handling scan error: {e}")
    
    def add_device_to_table(self, device: Dict):
        """Add device to table - OPTIMIZED FOR SPEED"""
        try:
            # Get current row count
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            
            # Add device data to table
            self.device_table.setItem(row, 0, QTableWidgetItem(device.get('ip', 'Unknown')))
            self.device_table.setItem(row, 1, QTableWidgetItem(device.get('mac', 'Unknown')))
            self.device_table.setItem(row, 2, QTableWidgetItem(device.get('hostname', 'Unknown')))
            self.device_table.setItem(row, 3, QTableWidgetItem(device.get('vendor', 'Unknown')))
            self.device_table.setItem(row, 4, QTableWidgetItem(device.get('device_type', 'Unknown')))
            self.device_table.setItem(row, 5, QTableWidgetItem('Online'))
            self.device_table.setItem(row, 6, QTableWidgetItem('No'))
            self.device_table.setItem(row, 7, QTableWidgetItem('Online'))
            
            # Color code the device
            self.color_code_device(row, device)
            
            # Update status immediately
            self.update_status(f"Found device: {device.get('ip', 'Unknown')}")
            
        except Exception as e:
            log_error(f"Error adding device to table: {e}")
    
    def color_code_device(self, row: int, device: Dict):
        """Color code device based on type"""
        try:
            device_type = device.get('device_type', '').lower()
            is_local = device.get('local', False)
            
            # Set background color based on device type
            if "gaming console" in device_type:
                color = QColor(255, 200, 200)  # Light red for gaming
            elif "network device" in device_type:
                color = QColor(200, 255, 200)  # Light green for network
            elif "mobile device" in device_type:
                color = QColor(200, 200, 255)  # Light blue for mobile
            elif "computer" in device_type:
                color = QColor(255, 255, 200)  # Light yellow for computer
            else:
                color = QColor(240, 240, 240)  # Light gray for unknown
            
            # Special color for local device
            if is_local:
                color = QColor(255, 255, 150)  # Bright yellow for local
            
            # Apply color to all cells in the row
            for col in range(self.device_table.columnCount()):
                item = self.device_table.item(row, col)
                if item:
                    item.setBackground(color)
                    
        except Exception as e:
            log_error(f"Error color coding device: {e}")
    
    def update_progress(self, current: int, total: int):
        """Update progress bar"""
        try:
            if total > 0:
                progress = int((current / total) * 100)
                self.progress_bar.setValue(progress)
        except Exception as e:
            log_error(f"Error updating progress: {e}")
    
    def update_status(self, message: str):
        """Update status label"""
        try:
            self.status_label.setText(message)
            
            # Color code status messages
            if "error" in message.lower():
                self.status_label.setStyleSheet("color: #f44336; font-weight: bold;")
            elif "complete" in message.lower():
                self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            elif "scanning" in message.lower():
                self.status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
            else:
                self.status_label.setStyleSheet("color: #2196F3; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error updating status: {e}")
    
    def on_device_selected(self):
        """Handle device selection"""
        try:
            current_row = self.device_table.currentRow()
            if current_row >= 0 and current_row < len(self.devices):
                selected_device = self.devices[current_row]
                self.device_selected.emit(selected_device)
                
        except Exception as e:
            log_error(f"Error handling device selection: {e}")
    
    def on_cell_double_clicked(self, row: int, column: int):
        """Handle double-click on table cell to toggle blocking"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                # Toggle blocking status
                current_blocked = device.get('blocked', False)
                new_blocked = not current_blocked
                
                # Update device status
                device['blocked'] = new_blocked
                device['status'] = 'Blocked' if new_blocked else 'Online'
                
                # Update table display
                status_item = QTableWidgetItem(device['status'])
                if new_blocked:
                    status_item.setBackground(QColor(255, 100, 100))  # Red for blocked
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                else:
                    status_item.setBackground(QColor(100, 255, 100))  # Green for online
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                
                self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                
                # Actually block/unblock the device
                self.actually_block_device(ip, new_blocked)
                
                # Update status message
                action = "blocked" if new_blocked else "unblocked"
                self.update_status(f"Device {ip} {action}")
                
                # Emit signal
                self.device_blocked.emit(ip, new_blocked)
                
        except Exception as e:
            log_error(f"Error toggling device blocking: {e}")
    
    def show_context_menu(self, position):
        """Show context menu for device actions"""
        try:
            
            # Get the row under the cursor
            row = self.device_table.rowAt(position.y())
            if row < 0 or row >= len(self.devices):
                return
            
            device = self.devices[row]
            ip = device.get('ip', '')
            is_blocked = device.get('blocked', False)
            
            # Create context menu
            menu = QMenu(self)
            
            # Toggle blocking action
            toggle_action = QAction("Block Device" if not is_blocked else "Unblock Device", self)
            toggle_action.triggered.connect(lambda: self.toggle_device_blocking(row))
            menu.addAction(toggle_action)
            
            # Add separator
            menu.addSeparator()
            
            # Ping device action
            ping_action = QAction("Ping Device", self)
            ping_action.triggered.connect(lambda: self.ping_device(ip))
            menu.addAction(ping_action)
            
            # Port scan action
            scan_action = QAction("Port Scan", self)
            scan_action.triggered.connect(lambda: self.port_scan_device(ip))
            menu.addAction(scan_action)
            
            # Add separator
            menu.addSeparator()
            
            # Copy IP action
            copy_action = QAction("Copy IP Address", self)
            copy_action.triggered.connect(lambda: self.copy_ip_to_clipboard(ip))
            menu.addAction(copy_action)
            
            # Show menu at cursor position
            menu.exec(self.device_table.mapToGlobal(position))
            
        except Exception as e:
            log_error(f"Error showing context menu: {e}")
    
    def toggle_device_blocking(self, row: int):
        """Toggle blocking for a specific device row"""
        try:
            if row < len(self.devices):
                device = self.devices[row]
                ip = device.get('ip', '')
                
                # Toggle blocking status
                current_blocked = device.get('blocked', False)
                new_blocked = not current_blocked
                
                # Update device status
                device['blocked'] = new_blocked
                device['status'] = 'Blocked' if new_blocked else 'Online'
                
                # Update table display
                status_item = QTableWidgetItem(device['status'])
                if new_blocked:
                    status_item.setBackground(QColor(255, 100, 100))  # Red for blocked
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                else:
                    status_item.setBackground(QColor(100, 255, 100))  # Green for online
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                
                self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                
                # Actually block/unblock the device
                self.actually_block_device(ip, new_blocked)
                
                # Update status message
                action = "blocked" if new_blocked else "unblocked"
                self.update_status(f"Device {ip} {action}")
                
                # Emit signal
                self.device_blocked.emit(ip, new_blocked)
                
        except Exception as e:
            log_error(f"Error toggling device blocking: {e}")
    
    def actually_block_device(self, ip: str, block: bool):
        """Actually block/unblock a device using REAL network disruption"""
        try:
            log_info(f"[SCAN] Starting blocking process for {ip} (block={block})")
            
            if self.controller:
                log_info(f"[SUCCESS] Controller found, using toggle_lag method")
                # Use the controller's REAL blocking mechanism
                # toggle_lag returns the new blocked state
                new_blocked_state = self.controller.toggle_lag(ip)
                log_info(f"toggle_lag returned: {new_blocked_state}")
                
                if block:
                    # We want to block the device
                    if new_blocked_state:
                        log_info(f"[SUCCESS] Device {ip} blocked using REAL network disruption")
                        self.update_status(f"Successfully blocked {ip}")
                    else:
                        log_error(f"[FAILED] Failed to block device {ip}")
                        self.update_status(f"Failed to block {ip}")
                else:
                    # We want to unblock the device
                    if not new_blocked_state:
                        log_info(f"[SUCCESS] Device {ip} unblocked successfully")
                        self.update_status(f"Successfully unblocked {ip}")
                    else:
                        log_error(f"[FAILED] Failed to unblock device {ip}")
                        self.update_status(f"Failed to unblock {ip}")
                
                # Update the device's blocked status in our local list
                for device in self.devices:
                    if device.get('ip') == ip:
                        device['blocked'] = new_blocked_state
                        log_info(f"📝 Updated device {ip} blocked status to {new_blocked_state}")
                        break
                
            else:
                # Fallback to direct firewall blocking
                log_error("[FAILED] No controller available, using fallback blocking")
                self.aggressive_block_device(ip, block)
                
            # Update blocking status indicator
            self.update_blocking_status()
            
        except Exception as e:
            log_error(f"[FAILED] Error blocking device {ip}: {e}")
            self.update_status(f"Error blocking {ip}: {e}")
    
    def update_blocking_status(self):
        """Update the blocking status indicator"""
        try:
            blocked_count = sum(1 for device in self.devices if device.get('blocked', False))
            total_devices = len(self.devices)
            
            if blocked_count > 0:
                self.blocking_status.setText(f"🔒 Blocking: Active ({blocked_count}/{total_devices} devices blocked)")
                self.blocking_status.setStyleSheet("color: #f44336; font-weight: bold;")
            else:
                self.blocking_status.setText("🔒 Blocking: Inactive")
                self.blocking_status.setStyleSheet("color: #FF9800; font-weight: bold;")
                
        except Exception as e:
            log_error(f"Error updating blocking status: {e}")
    
    def block_with_firewall(self, ip: str, block: bool):
        """Block device using Windows Firewall rules"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add firewall rule to block IP
                    rule_name = f"DupeZ_Block_{ip.replace('.', '_')}"
                    cmd = [
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name={rule_name}",
                        "dir=out",
                        "action=block",
                        f"remoteip={ip}",
                        "enable=yes"
                    ]
                else:
                    # Remove firewall rule
                    rule_name = f"DupeZ_Block_{ip.replace('.', '_')}"
                    cmd = [
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        f"name={rule_name}"
                    ]
                
                # Execute command with admin privileges
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0:
                    log_error(f"Firewall command failed: {result.stderr}")
                    raise Exception(f"Firewall command failed: {result.stderr}")
                
                log_info(f"Firewall rule {'added' if block else 'removed'} for {ip}")
                
                # Also add route blocking for more aggressive blocking
                if block:
                    self.block_with_route(ip, True)
                else:
                    self.block_with_route(ip, False)
                    
            else:
                # For non-Windows systems, use iptables
                if block:
                    cmd = ["iptables", "-A", "OUTPUT", "-d", ip, "-j", "DROP"]
                else:
                    cmd = ["iptables", "-D", "OUTPUT", "-d", ip, "-j", "DROP"]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    log_error(f"iptables command failed: {result.stderr}")
                    raise Exception(f"iptables command failed: {result.stderr}")
                
                log_info(f"iptables rule {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with firewall blocking: {e}")
            raise
    
    def block_with_route(self, ip: str, block: bool):
        """Block device using route table manipulation"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add a blackhole route to the IP
                    cmd = [
                        "route", "add", ip, "mask", "255.255.255.255", "0.0.0.0", "metric", "1"
                    ]
                else:
                    # Remove the blackhole route
                    cmd = [
                        "route", "delete", ip
                    ]
                
                # Execute command with admin privileges
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0 and "already exists" not in result.stderr:
                    log_error(f"Route command failed: {result.stderr}")
                    # Don't raise exception for route commands as they might fail for various reasons
                
                log_info(f"Route {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with route blocking: {e}")
            # Don't raise exception for route blocking as it's secondary
    
    def aggressive_block_device(self, ip: str, block: bool):
        """Aggressive blocking that tries multiple methods"""
        try:
            # Method 1: Firewall rules
            self.block_with_firewall(ip, block)
            
            # Method 2: Route table manipulation
            self.block_with_route(ip, block)
            
            # Method 3: ARP poisoning (for local network)
            if self.is_local_network(ip):
                self.block_with_arp(ip, block)
            
            # Method 4: DNS blocking
            self.block_with_dns(ip, block)
            
            log_info(f"Aggressive blocking {'enabled' if block else 'disabled'} for {ip}")
            
        except Exception as e:
            log_error(f"Error with aggressive blocking: {e}")
            raise
    
    def is_local_network(self, ip: str) -> bool:
        """Check if IP is on local network"""
        try:
            import socket
            
            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            
            # Extract network prefix
            local_parts = local_ip.split('.')
            ip_parts = ip.split('.')
            
            # Check if same network (assuming /24)
            return local_parts[:3] == ip_parts[:3]
            
        except:
            return False
    
    def block_with_arp(self, ip: str, block: bool):
        """Block device using ARP poisoning"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                if block:
                    # Add static ARP entry pointing to invalid MAC
                    cmd = [
                        "arp", "-s", ip, "00-00-00-00-00-00"
                    ]
                else:
                    # Remove static ARP entry
                    cmd = [
                        "arp", "-d", ip
                    ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                
                if result.returncode != 0:
                    log_error(f"ARP command failed: {result.stderr}")
                
                log_info(f"ARP entry {'added' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with ARP blocking: {e}")
    
    def block_with_dns(self, ip: str, block: bool):
        """Block device using DNS manipulation"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                # This would require modifying hosts file or DNS settings
                # For now, just log the attempt
                log_info(f"DNS blocking {'requested' if block else 'removed'} for {ip}")
                
        except Exception as e:
            log_error(f"Error with DNS blocking: {e}")
    
    def ping_device(self, ip: str):
        """Ping a device to check connectivity"""
        try:
            import subprocess
            import platform
            
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "4", ip]
            else:
                cmd = ["ping", "-c", "4", ip]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.update_status(f"Ping to {ip}: Success")
            else:
                self.update_status(f"Ping to {ip}: Failed")
                
        except Exception as e:
            log_error(f"Error pinging {ip}: {e}")
            self.update_status(f"Error pinging {ip}: {e}")
    
    def port_scan_device(self, ip: str):
        """Perform a quick port scan on a device"""
        try:
            import socket
            
            common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 8080]
            open_ports = []
            
            for port in common_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    
                    if result == 0:
                        open_ports.append(port)
                except:
                    continue
            
            if open_ports:
                ports_str = ', '.join(map(str, open_ports))
                self.update_status(f"Port scan {ip}: Open ports: {ports_str}")
            else:
                self.update_status(f"Port scan {ip}: No common ports open")
                
        except Exception as e:
            log_error(f"Error port scanning {ip}: {e}")
            self.update_status(f"Error port scanning {ip}: {e}")
    
    def copy_ip_to_clipboard(self, ip: str):
        """Copy IP address to clipboard"""
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                clipboard = app.clipboard()
                clipboard.setText(ip)
                self.update_status(f"IP address {ip} copied to clipboard")
            else:
                self.update_status("Cannot copy to clipboard - QApplication not initialized")
        except Exception as e:
            log_error(f"Error copying IP to clipboard: {e}")
            self.update_status(f"Error copying IP to clipboard: {e}")
    
    def clear_devices(self):
        """Clear all devices from the table"""
        try:
            self.device_table.setRowCount(0)
            self.devices = []
            self.update_status("Device list cleared")
            
        except Exception as e:
            log_error(f"Error clearing devices: {e}")
    
    def block_selected(self):
        """Block selected devices"""
        try:
            selected_rows = set()
            for item in self.device_table.selectedItems():
                selected_rows.add(item.row())
            
            if not selected_rows:
                self.update_status("No devices selected for blocking")
                return
            
            # Block selected devices
            for row in selected_rows:
                if row < len(self.devices):
                    device = self.devices[row]
                    ip = device.get('ip', '')
                    
                    # Update device status
                    device['blocked'] = True
                    device['status'] = 'Blocked'
                    
                    # Update table
                    status_item = QTableWidgetItem('Blocked')
                    status_item.setBackground(QColor(255, 100, 100))
                    self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                    
                    # Emit signal
                    self.device_blocked.emit(ip, True)
            
            self.update_status(f"Blocked {len(selected_rows)} selected device(s)")
            
        except Exception as e:
            log_error(f"Error blocking devices: {e}")
    
    def unblock_selected(self):
        """Unblock selected devices"""
        try:
            selected_rows = set()
            for item in self.device_table.selectedItems():
                selected_rows.add(item.row())
            
            if not selected_rows:
                self.update_status("No devices selected for unblocking")
                return
            
            # Unblock selected devices
            for row in selected_rows:
                if row < len(self.devices):
                    device = self.devices[row]
                    ip = device.get('ip', '')
                    
                    # Update device status
                    device['blocked'] = False
                    device['status'] = 'Online'
                    
                    # Update table
                    status_item = QTableWidgetItem('Online')
                    status_item.setBackground(QColor(100, 255, 100))
                    self.device_table.setItem(row, 7, status_item) # Changed from 8 to 7
                    
                    # Emit signal
                    self.device_blocked.emit(ip, False)
            
            self.update_status(f"Unblocked {len(selected_rows)} selected device(s)")
            
        except Exception as e:
            log_error(f"Error unblocking devices: {e}")
    
    def block_all_devices(self):
        """Block all devices in the list"""
        try:
            if not self.devices:
                self.update_status("No devices to block")
                return
            
            # Import PS5 blocker
            from app.firewall.ps5_blocker import ps5_blocker
            
            blocked_count = 0
            ps5_ips = []
            
            for i, device in enumerate(self.devices):
                ip = device.get('ip', '')
                if ip and not device.get('blocked', False):
                    # Check if it's a PS5
                    if self._is_ps5_device(device):
                        ps5_ips.append(ip)
                    
                    # Block this device
                    self.actually_block_device(ip, True)
                    device['blocked'] = True
                    device['status'] = 'Blocked'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Blocked')
                    status_item.setBackground(QColor(255, 100, 100))  # Red
                    status_item.setForeground(QColor(255, 255, 255))  # White text
                    self.device_table.setItem(i, 7, status_item)
                    
                    blocked_count += 1
            
            # Block PS5s specifically
            if ps5_ips:
                ps5_blocker.block_all_ps5s(ps5_ips)
                self.update_status(f"Blocked {blocked_count} devices (including {len(ps5_ips)} PS5s)")
            else:
                self.update_status(f"Blocked {blocked_count} devices")
            
            self.update_blocking_status()
            
        except Exception as e:
            log_error(f"Error blocking all devices: {e}")
            self.update_status(f"Error blocking all devices: {e}")
    
    def _is_ps5_device(self, device: dict) -> bool:
        """Check if device is a PS5"""
        try:
            # Check vendor name
            vendor = device.get('vendor', '').lower()
            if 'sony' in vendor or 'playstation' in vendor or 'ps5' in vendor:
                return True
            
            # Check hostname
            hostname = device.get('hostname', '').lower()
            if 'ps5' in hostname or 'playstation' in hostname:
                return True
            
            # Check MAC address (Sony's OUI)
            mac = device.get('mac', '').lower()
            if mac.startswith(('00:50:c2', '00:1f:a7', '00:19:c5')):
                return True
            
            return False
        except:
            return False
    
    def get_methods_description(self, methods: List[str]) -> str:
        """Get human-readable descriptions of selected methods"""
        descriptions = []
        
        for method in methods:
            if method == "windivert":
                descriptions.append("WinDivert (Prioritized Packet Manipulation)")
            elif method == "icmp_spoof":
                descriptions.append("ICMP Spoof")
            elif method == "dns_spoof":
                descriptions.append("DNS Spoofing")
            elif method == "arp_poison":
                descriptions.append("ARP Poisoning")
            elif method == "udp_interrupt":
                descriptions.append("UDP Interrupt")
            else:
                descriptions.append(method)
        
        return ", ".join(descriptions)
    
    def get_selected_disconnect_methods(self) -> List[str]:
        """Get the selected disconnect methods for DayZ duping"""
        selected_methods = []
        
        # WinDivert (Prioritized) - check first
        if self.windivert_cb.isChecked():
            selected_methods.append("windivert")
        
        if self.icmp_disconnect_cb.isChecked():
            selected_methods.append("icmp_spoof")
        if self.dns_spoofing_cb.isChecked():
            selected_methods.append("dns_spoof")
        if self.arp_poison_cb.isChecked():
            selected_methods.append("arp_poison")
        if self.udp_interrupt_cb.isChecked():
            selected_methods.append("udp_interrupt")
            
        return selected_methods
    
    def toggle_internet_drop(self):
        """Toggle internet drop/dupe functionality with selected methods"""
        try:
            from app.firewall.dupe_internet_dropper import dupe_internet_dropper
            
            # Get selected methods
            selected_methods = self.get_selected_disconnect_methods()
            
            if not selected_methods:
                self.update_status("[FAILED] Please select at least one disconnect method")
                return
            
            # Get selected devices from the table
            selected_devices = self.get_selected_devices()
            
            if not selected_devices:
                self.update_status("[FAILED] Please select at least one device to disconnect")
                return
            
            if not dupe_internet_dropper.is_dupe_active():
                # Start dupe with selected methods and devices
                success = dupe_internet_dropper.start_dupe_with_devices(selected_devices, selected_methods)
                if success:
                    self.internet_drop_button.setText("[DISCONNECT] Reconnect")
                    self.internet_drop_button.setStyleSheet("""
                        QPushButton {
                            background-color: #4caf50;
                            color: white;
                            border: 2px solid #388e3c;
                            border-radius: 4px;
                            padding: 8px 16px;
                            font-weight: bold;
                            font-size: 12px;
                            min-height: 30px;
                        }
                        QPushButton:hover {
                            background-color: #66bb6a;
                            border-color: #4caf50;
                        }
                        QPushButton:pressed {
                            background-color: #388e3c;
                        }
                        QPushButton:disabled {
                            background-color: #666666;
                            border-color: #444444;
                            color: #cccccc;
                        }
                    """)
                    methods_text = self.get_methods_description(selected_methods)
                    device_count = len(selected_devices)
                    self.update_status(f"[DISCONNECT] Disconnect active on {device_count} device(s) - Using: {methods_text}")
                    log_info(f"DayZ disconnect mode activated on {device_count} devices with methods: {selected_methods}")
                else:
                    self.update_status("[FAILED] Failed to start disconnect mode")
                    log_error("Failed to start DayZ disconnect mode")
            else:
                # Stop dupe
                success = dupe_internet_dropper.stop_dupe()
                if success:
                    self.internet_drop_button.setText("[DISCONNECT] Disconnect")
                    self.internet_drop_button.setStyleSheet("""
                        QPushButton {
                            background-color: #d32f2f;
                            color: white;
                            border: 2px solid #b71c1c;
                            border-radius: 4px;
                            padding: 8px 16px;
                            font-weight: bold;
                            font-size: 12px;
                            min-height: 30px;
                        }
                        QPushButton:hover {
                            background-color: #f44336;
                            border-color: #d32f2f;
                        }
                        QPushButton:pressed {
                            background-color: #b71c1c;
                        }
                        QPushButton:disabled {
                            background-color: #666666;
                            border-color: #444444;
                            color: #cccccc;
                        }
                    """)
                    self.update_status("[SUCCESS] Disconnect mode stopped - normal connection restored")
                    log_info("DayZ disconnect mode deactivated")
                else:
                    self.update_status("[FAILED] Failed to stop disconnect mode")
                    log_error("Failed to stop DayZ disconnect mode")
                    
        except Exception as e:
            log_error(f"Error toggling disconnect mode: {e}")
            self.update_status(f"[FAILED] Error: {e}")
    
    def unblock_all_devices(self):
        """Unblock all devices in the list"""
        try:
            if not self.devices:
                self.update_status("No devices to unblock")
                return
            
            # Import PS5 blocker
            from app.firewall.ps5_blocker import ps5_blocker
            
            unblocked_count = 0
            ps5_ips = []
            
            for i, device in enumerate(self.devices):
                ip = device.get('ip', '')
                if ip and device.get('blocked', False):
                    # Check if it's a PS5
                    if self._is_ps5_device(device):
                        ps5_ips.append(ip)
                    
                    # Unblock this device
                    self.actually_block_device(ip, False)
                    device['blocked'] = False
                    device['status'] = 'Online'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Online')
                    status_item.setBackground(QColor(100, 255, 100))  # Green
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                    self.device_table.setItem(i, 7, status_item)
                    
                    unblocked_count += 1
            
            # Unblock PS5s specifically
            if ps5_ips:
                ps5_blocker.unblock_all_ps5s(ps5_ips)
                self.update_status(f"Unblocked {unblocked_count} devices (including {len(ps5_ips)} PS5s)")
            else:
                self.update_status(f"Unblocked {unblocked_count} devices")
            
            self.update_blocking_status()
            
        except Exception as e:
            log_error(f"Error unblocking all devices: {e}")
            self.update_status(f"Error unblocking all devices: {e}")
    
    def clear_all_blocks(self):
        """Clear all blocks and restore network"""
        try:
            from app.firewall.blocker import clear_all_blocks
            from app.firewall.ps5_blocker import ps5_blocker
            
            # Clear all blocks using the blocker module
            success = clear_all_blocks()
            
            # Clear PS5 blocks specifically
            ps5_success = ps5_blocker.clear_all_ps5_blocks()
            
            if success and ps5_success:
                # Update all devices to unblocked status
                for i, device in enumerate(self.devices):
                    device['blocked'] = False
                    device['status'] = 'Online'
                    
                    # Update table display
                    status_item = QTableWidgetItem('Online')
                    status_item.setBackground(QColor(100, 255, 100))  # Green
                    status_item.setForeground(QColor(0, 0, 0))  # Black text
                    self.device_table.setItem(i, 7, status_item)
                
                self.update_status("All blocks cleared successfully (including PS5s)")
                self.update_blocking_status()
            else:
                self.update_status("Failed to clear all blocks")
                
        except Exception as e:
            log_error(f"Error clearing all blocks: {e}")
            self.update_status(f"Error clearing blocks: {e}")
    
    def get_selected_devices(self) -> List[Dict]:
        """Get selected devices from the table"""
        selected_devices = []
        
        try:
            # Get selected rows
            selected_rows = set()
            for item in self.device_table.selectedItems():
                selected_rows.add(item.row())
            
            # Get device data for selected rows
            for row in selected_rows:
                if row < len(self.devices):
                    device = self.devices[row].copy()
                    selected_devices.append(device)
            
            # If no devices selected, use all devices
            if not selected_devices and self.devices:
                selected_devices = self.devices.copy()
                
        except Exception as e:
            log_error(f"Error getting selected devices: {e}")
            
        return selected_devices
    
    def get_device_count(self) -> int:
        """Get total number of devices"""
        return len(self.devices)
    
    def apply_styling(self):
        """Apply modern styling to the widget"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                color: #ffffff;
            }
            QPushButton {
                background-color: #3d3d3d;
                border: 2px solid #4a4a4a;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
                border-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #2d2d2d;
                border-color: #3a3a3a;
            }
            QPushButton:disabled {
                background-color: #1a1a1a;
                border-color: #333333;
                color: #666666;
            }
            QTableWidget {
                background-color: #1e1e1e;
                border: 2px solid #4a4a4a;
                border-radius: 6px;
                alternate-background-color: #252525;
                gridline-color: #3a3a3a;
            }
            QTableWidget::item {
                padding: 6px;
                border-bottom: 1px solid #3a3a3a;
            }
            QTableWidget::item:selected {
                background-color: #4CAF50;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                color: #ffffff;
                padding: 8px;
                border: 1px solid #4a4a4a;
                font-weight: bold;
            }
            QProgressBar {
                border: 1px solid #555555;
                background-color: #1e1e1e;
                text-align: center;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 4px;
            }
            QSpinBox {
                background-color: #3d3d3d;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 4px;
                color: #ffffff;
            }
            QCheckBox {
                color: #ffffff;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #4a4a4a;
                border-radius: 3px;
                background-color: #2d2d2d;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border-color: #4CAF50;
            }
        """)
    
    def search_for_device(self, search_term: str, search_field: str = "All Fields") -> List[Dict]:
        """Search for devices by various criteria"""
        try:
            if not self.devices:
                log_info("No devices to search")
                return []
            
            search_term = search_term.lower().strip()
            results = []
            
            for device in self.devices:
                match_found = False
                
                if search_field == "All Fields":
                    # Search in all fields
                    for field in ['ip', 'hostname', 'vendor', 'mac', 'device_type']:
                        if search_term in str(device.get(field, '')).lower():
                            match_found = True
                            break
                else:
                    # Search in specific field
                    field_map = {
                        "IP Address": "ip",
                        "Hostname": "hostname", 
                        "Vendor": "vendor",
                        "MAC Address": "mac"
                    }
                    
                    field_name = field_map.get(search_field, "ip")
                    if search_term in str(device.get(field_name, '')).lower():
                        match_found = True
                
                if match_found:
                    results.append(device)
            
            log_info(f"Search for '{search_term}' in '{search_field}' found {len(results)} devices")
            return results
            
        except Exception as e:
            log_error(f"Error searching for devices: {e}")
            return []
    
    def filter_devices_by_search(self, search_term: str):
        """Filter the device table by search term"""
        try:
            if not search_term.strip():
                # Show all devices if search is empty
                for row in range(self.device_table.rowCount()):
                    self.device_table.setRowHidden(row, False)
                return
            
            search_term = search_term.lower().strip()
            
            for row in range(self.device_table.rowCount()):
                if row >= len(self.devices):
                    continue
                    
                device = self.devices[row]
                match_found = False
                
                # Search in all device fields
                for field in ['ip', 'hostname', 'vendor', 'mac', 'device_type']:
                    if search_term in str(device.get(field, '')).lower():
                        match_found = True
                        break
                
                # Show/hide row based on match
                self.device_table.setRowHidden(row, not match_found)
            
            log_info(f"Filtered devices by search term: '{search_term}'")
            
        except Exception as e:
            log_error(f"Error filtering devices: {e}")
    
    def add_search_input(self):
        """Add search input field to the control panel"""
        try:
            # Create search input
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("Search devices by IP, MAC, or hostname...")
            self.search_input.setStyleSheet("""
                QLineEdit {
                    background-color: #3d3d3d;
                    color: #ffffff;
                    border: 2px solid #404040;
                    border-radius: 4px;
                    padding: 5px;
                    min-height: 25px;
                    font-size: 10px;
                }
                QLineEdit:focus {
                    border-color: #4CAF50;
                }
            """)
            
            # Connect search input to filter function
            self.search_input.textChanged.connect(self.filter_devices_by_search)
            
            # Add search input to control panel
            search_layout = QHBoxLayout()
            search_layout.addWidget(QLabel("Search:"))
            search_layout.addWidget(self.search_input)
            
            # Add to the control panel layout
            if hasattr(self, 'control_panel'):
                self.control_panel.layout().addLayout(search_layout)
            
        except Exception as e:
            log_error(f"Error adding search input: {e}")
    
    def cleanup(self):
        """Cleanup resources and disconnect signals"""
        try:
            # Disconnect scanner signals
            if self.scanner:
                try:
                    self.scanner.device_found.disconnect()
                except:
                    pass
                try:
                    self.scanner.scan_complete.disconnect()
                except:
                    pass
                try:
                    self.scanner.scan_error.disconnect()
                except:
                    pass
                try:
                    self.scanner.status_update.disconnect()
                except:
                    pass
                
                # Stop any ongoing scan
                if self.scanning:
                    self.scanner.stop_scan()
                
            # Clear data
            self.devices = []
            self.scanning = False
            
            log_info("Enhanced device list cleanup completed")
            
        except Exception as e:
            log_error(f"Error during cleanup: {e}")
    
    def closeEvent(self, event):
        """Handle close event to ensure proper cleanup"""
        self.cleanup()
        super().closeEvent(event)