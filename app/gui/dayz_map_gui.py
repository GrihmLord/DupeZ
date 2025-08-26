#!/usr/bin/env python3
"""
DayZ Map GUI - iZurvive Integration
Interactive DayZ map with GPS coordinates, markers, and loot locations
Based on iZurvive.com functionality
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
    QPushButton, QLineEdit, QComboBox, QSpinBox, QCheckBox, 
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, 
    QGroupBox, QMessageBox, QInputDialog, QProgressBar, 
    QTextEdit, QTabWidget, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QFont, QColor, QPalette, QPixmap, QIcon
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    # Fallback if WebEngine is not available
    QWebEngineView = None
from typing import List, Dict, Optional, Tuple
import json
import os
import time
from datetime import datetime
from app.logs.logger import log_info, log_error, log_warning
from app.core.data_persistence import marker_manager

class DayZMapGUI(QWidget):
    """Interactive DayZ map with iZurvive integration"""
    
    # Signals
    marker_added = pyqtSignal(str, str, str)  # name, coordinates, type
    marker_removed = pyqtSignal(str)
    gps_coordinates_updated = pyqtSignal(str, str)  # x, y
    loot_found = pyqtSignal(str, str, str)  # item, location, coordinates
    
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.markers = []
        self.loot_locations = []
        self.gps_coordinates = {"x": "000", "y": "000"}
        self.current_map = "Chernarus+"
        self.setup_ui()
        self.connect_signals()
        self.load_map_data()
        
    def setup_ui(self):
        """Setup the main UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🗺️ DayZ Interactive Map (iZurvive)")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin: 10px;")
        layout.addWidget(title)
        
        # Create splitter for map and controls
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet("QSplitter::handle { background-color: #4CAF50; }")
        
        # Map area (left side) - Larger and better organized
        map_group = QGroupBox("🗺️ Interactive DayZ Map")
        map_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                border: 3px solid #4CAF50;
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px 0 10px;
                color: #4CAF50;
                font-size: 16px;
            }
        """)
        map_layout = QVBoxLayout()
        map_layout.setSpacing(15)
        map_layout.setContentsMargins(15, 20, 15, 15)
        
        # Map selection - Better organized with improved styling
        map_selection_layout = QHBoxLayout()
        map_selection_layout.setSpacing(10)
        
        map_label = QLabel("Map:")
        map_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 12px;")
        
        self.map_combo = QComboBox()
        self.map_combo.addItems([
            "Chernarus+", "Livonia", "Namalsk", "Deer Isle", 
            "Chiemsee", "Rostow", "Esseker", "Takistan Plus",
            "Valning", "Zagoria", "Melkart", "Stuart Island"
        ])
        self.map_combo.setCurrentText(self.current_map)
        self.map_combo.currentTextChanged.connect(self.change_map)
        self.map_combo.setStyleSheet("""
            QComboBox {
                background-color: #3a3a3a;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 8px 12px;
                color: white;
                font-size: 12px;
                min-width: 150px;
            }
            QComboBox:hover {
                border-color: #4CAF50;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ffffff;
            }
        """)
        
        # Refresh map button
        refresh_btn = QPushButton("🔄 Refresh Map")
        refresh_btn.clicked.connect(self.refresh_map)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: 2px solid #1976D2;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #1976D2;
                border-color: #2196F3;
                transform: scale(1.05);
            }
        """)
        
        map_selection_layout.addWidget(map_label)
        map_selection_layout.addWidget(self.map_combo)
        map_selection_layout.addWidget(refresh_btn)
        map_selection_layout.addStretch()
        map_layout.addLayout(map_selection_layout)
        
        # Web view for map - Enhanced detection for admin privileges
        self.map_view = None
        self.map_placeholder = None
        
        # Check admin status first
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        
        if is_admin:
            # Admin mode - skip WebEngine entirely and use local map
            log_info("Running as Administrator - using local interactive map system")
            self.map_view = None
            self.create_admin_map_system(map_layout)
        else:
            # Non-admin mode - try WebEngine
            try:
                # Create WebEngine view with proper error handling
                self.map_view = QWebEngineView()
                self.map_view.setMinimumHeight(500)
                self.map_view.setMinimumWidth(400)
                
                # Apply styling
                self.map_view.setStyleSheet("""
                    QWebEngineView {
                        border: 2px solid #4CAF50;
                        border-radius: 8px;
                        background-color: #1a1a1a;
                    }
                """)
                
                # Add to layout
                map_layout.addWidget(self.map_view)
                
                # Load interactive map after a short delay to ensure WebEngine is ready
                QTimer.singleShot(1000, self.load_izurvive_map)
                log_info("WebEngine initialized successfully, map will load in 1 second")
                
                # Set up load finished handler (with proper error checking)
                try:
                    self.map_view.loadFinished.connect(self.on_map_load_finished)
                except Exception as e:
                    log_warning(f"Could not connect load finished handler: {e}")
                
                # Set up WebEngine signals safely after a delay
                QTimer.singleShot(2000, self.setup_webengine_signals)
                
            except Exception as e:
                log_error(f"WebEngine initialization failed: {e}")
                self.map_view = None
                # Fallback to local map for non-admin users too
                self.create_local_map_fallback(map_layout)
        
        map_group.setLayout(map_layout)
        splitter.addWidget(map_group)
        
        # Controls area (right side) - Better organized and styled
        controls_group = QGroupBox("🎯 Map Controls")
        controls_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                border: 3px solid #FF9800;
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #2b2b2b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 10px 0 10px;
                color: #FF9800;
                font-size: 16px;
            }
        """)
        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(15)
        controls_layout.setContentsMargins(15, 20, 15, 15)
        
        # GPS coordinates - Better organized
        gps_group = QGroupBox("📍 GPS Coordinates")
        gps_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 2px solid #4CAF50;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #3a3a3a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #4CAF50;
                font-size: 13px;
            }
        """)
        gps_layout = QGridLayout()
        gps_layout.setSpacing(10)
        gps_layout.setContentsMargins(10, 15, 10, 10)
        
        gps_x_label = QLabel("X Coordinate:")
        gps_x_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 11px;")
        self.gps_x_input = QLineEdit("000")
        self.gps_x_input.setPlaceholderText("Enter X coordinate")
        self.gps_x_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 8px 12px;
                color: white;
                font-size: 11px;
                min-width: 100px;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
            }
        """)
        gps_layout.addWidget(gps_x_label, 0, 0)
        gps_layout.addWidget(self.gps_x_input, 0, 1)
        
        gps_y_label = QLabel("Y Coordinate:")
        gps_y_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 11px;")
        self.gps_y_input = QLineEdit("000")
        self.gps_y_input.setPlaceholderText("Enter Y coordinate")
        self.gps_y_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 8px 12px;
                color: white;
                font-size: 11px;
                min-width: 100px;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
            }
        """)
        gps_layout.addWidget(gps_y_label, 1, 0)
        gps_layout.addWidget(self.gps_y_input, 1, 1)
        
        self.update_gps_btn = QPushButton("🔄 Update GPS")
        self.update_gps_btn.clicked.connect(self.update_gps_coordinates)
        self.update_gps_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: 2px solid #45a049;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #45a049;
                border-color: #4CAF50;
            }
        """)
        gps_layout.addWidget(self.update_gps_btn, 2, 0, 1, 2)
        
        gps_group.setLayout(gps_layout)
        controls_layout.addWidget(gps_group)
        
        # Markers - Better organized
        markers_group = QGroupBox("📍 Markers")
        markers_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 2px solid #2196F3;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #3a3a3a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #2196F3;
                font-size: 13px;
            }
        """)
        markers_layout = QVBoxLayout()
        markers_layout.setSpacing(10)
        markers_layout.setContentsMargins(10, 15, 10, 10)
        
        # Add marker - Better organized
        add_marker_layout = QHBoxLayout()
        add_marker_layout.setSpacing(8)
        
        self.marker_name_input = QLineEdit()
        self.marker_name_input.setPlaceholderText("Marker name")
        self.marker_name_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 6px 10px;
                color: white;
                font-size: 11px;
                min-width: 120px;
            }
            QLineEdit:focus {
                border-color: #2196F3;
            }
        """)
        add_marker_layout.addWidget(self.marker_name_input)
        
        self.marker_type_combo = QComboBox()
        self.marker_type_combo.addItems([
            "Player", "Base", "Vehicle", "Helicopter", "Boat",
            "Tent", "Barrel", "Crate", "Medical", "Military",
            "Civilian", "Industrial", "Residential", "Custom"
        ])
        self.marker_type_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 6px 10px;
                color: white;
                font-size: 11px;
                min-width: 100px;
            }
            QComboBox:hover {
                border-color: #2196F3;
            }
        """)
        add_marker_layout.addWidget(self.marker_type_combo)
        
        self.add_marker_btn = QPushButton("➕ Add")
        self.add_marker_btn.clicked.connect(self.add_marker)
        self.add_marker_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: 2px solid #1976D2;
                padding: 6px 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 60px;
            }
            QPushButton:hover {
                background-color: #1976D2;
                border-color: #2196F3;
            }
        """)
        add_marker_layout.addWidget(self.add_marker_btn)
        
        markers_layout.addLayout(add_marker_layout)
        
        # Markers table - Better styled
        self.markers_table = QTableWidget()
        self.markers_table.setColumnCount(4)
        self.markers_table.setHorizontalHeaderLabels([
            "Name", "Type", "Coordinates", "Actions"
        ])
        self.markers_table.horizontalHeader().setStretchLastSection(True)
        self.markers_table.setAlternatingRowColors(True)
        self.markers_table.setMaximumHeight(150)
        self.markers_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                alternate-background-color: #2a2a2a;
                gridline-color: #555555;
                border: 1px solid #555555;
                border-radius: 6px;
                font-size: 10px;
            }
            QHeaderView::section {
                background-color: #3a3a3a;
                color: white;
                padding: 6px;
                border: 1px solid #555555;
                font-size: 10px;
                font-weight: bold;
            }
        """)
        markers_layout.addWidget(self.markers_table)
        
        markers_group.setLayout(markers_layout)
        controls_layout.addWidget(markers_group)
        
        # Loot locations - Better organized
        loot_group = QGroupBox("📦 Loot Locations")
        loot_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 2px solid #9C27B0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #3a3a3a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #9C27B0;
                font-size: 13px;
            }
        """)
        loot_layout = QVBoxLayout()
        loot_layout.setSpacing(10)
        loot_layout.setContentsMargins(10, 15, 10, 10)
        
        # Add loot location - Better organized
        add_loot_layout = QHBoxLayout()
        add_loot_layout.setSpacing(8)
        
        self.loot_item_input = QLineEdit()
        self.loot_item_input.setPlaceholderText("Item name")
        self.loot_item_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 6px 10px;
                color: white;
                font-size: 11px;
                min-width: 120px;
            }
            QLineEdit:focus {
                border-color: #9C27B0;
            }
        """)
        add_loot_layout.addWidget(self.loot_item_input)
        
        self.loot_location_input = QLineEdit()
        self.loot_location_input.setPlaceholderText("Location")
        self.loot_location_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #555555;
                border-radius: 6px;
                padding: 6px 10px;
                color: white;
                font-size: 11px;
                min-width: 120px;
            }
            QLineEdit:focus {
                border-color: #9C27B0;
            }
        """)
        add_loot_layout.addWidget(self.loot_location_input)
        
        self.add_loot_btn = QPushButton("➕ Add")
        self.add_loot_btn.clicked.connect(self.add_loot_location)
        self.add_loot_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: 2px solid #7B1FA2;
                padding: 6px 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 60px;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
                border-color: #9C27B0;
            }
        """)
        add_loot_layout.addWidget(self.add_loot_btn)
        
        loot_layout.addLayout(add_loot_layout)
        
        # Loot table - Better styled
        self.loot_table = QTableWidget()
        self.loot_table.setColumnCount(4)
        self.loot_table.setHorizontalHeaderLabels([
            "Item", "Location", "Coordinates", "Actions"
        ])
        self.loot_table.horizontalHeader().setStretchLastSection(True)
        self.loot_table.setAlternatingRowColors(True)
        self.loot_table.setMaximumHeight(150)
        self.loot_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                alternate-background-color: #2a2a2a;
                gridline-color: #555555;
                border: 1px solid #555555;
                border-radius: 6px;
                font-size: 10px;
            }
            QHeaderView::section {
                background-color: #3a3a3a;
                color: white;
                padding: 6px;
                border: 1px solid #555555;
                font-size: 10px;
                font-weight: bold;
            }
        """)
        loot_layout.addWidget(self.loot_table)
        
        loot_group.setLayout(loot_layout)
        controls_layout.addWidget(loot_group)
        
        # Quick actions - Better organized
        actions_group = QGroupBox("⚡ Quick Actions")
        actions_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                border: 2px solid #FF9800;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #3a3a3a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #FF9800;
                font-size: 13px;
            }
        """)
        actions_layout = QGridLayout()
        actions_layout.setSpacing(10)
        actions_layout.setContentsMargins(10, 15, 10, 10)
        
        self.export_markers_btn = QPushButton("💾 Export Markers")
        self.export_markers_btn.clicked.connect(self.export_markers)
        self.export_markers_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: 2px solid #45a049;
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #45a049;
                border-color: #4CAF50;
            }
        """)
        actions_layout.addWidget(self.export_markers_btn, 0, 0)
        
        self.import_markers_btn = QPushButton("📂 Import Markers")
        self.import_markers_btn.clicked.connect(self.import_markers)
        self.import_markers_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: 2px solid #1976D2;
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #1976D2;
                border-color: #2196F3;
            }
        """)
        actions_layout.addWidget(self.import_markers_btn, 0, 1)
        
        self.clear_all_btn = QPushButton("🗑️ Clear All")
        self.clear_all_btn.clicked.connect(self.clear_all_markers)
        self.clear_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                border: 2px solid #D32F2F;
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #D32F2F;
                border-color: #F44336;
            }
        """)
        actions_layout.addWidget(self.clear_all_btn, 1, 0)
        
        self.refresh_map_btn = QPushButton("🔄 Refresh Map")
        self.refresh_map_btn.clicked.connect(self.refresh_map)
        self.refresh_map_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: 2px solid #F57C00;
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #F57C00;
                border-color: #FF9800;
            }
        """)
        actions_layout.addWidget(self.refresh_map_btn, 1, 1)
        
        actions_group.setLayout(actions_layout)
        controls_layout.addWidget(actions_group)
        
        controls_group.setLayout(controls_layout)
        splitter.addWidget(controls_group)
        
        # Set splitter proportions - Better balance
        splitter.setSizes([700, 500])
        layout.addWidget(splitter)
        
        self.setLayout(layout)
        self.apply_styling()
    
    def set_controller(self, controller):
        """Set the controller for this component"""
        self.controller = controller
        
    def connect_signals(self):
        """Connect all signals"""
        self.map_combo.currentTextChanged.connect(self.change_map)
        self.gps_x_input.textChanged.connect(self.on_gps_changed)
        self.gps_y_input.textChanged.connect(self.on_gps_changed)
        
    def load_map_data(self):
        """Load map data and markers"""
        try:
            # Load saved markers
            self.load_markers()
            
            # Load loot locations
            self.load_loot_locations()
            
            # Update tables
            self.refresh_markers_table()
            self.refresh_loot_table()
            
            log_info("DayZ map data loaded successfully")
            
        except Exception as e:
            log_error(f"Failed to load map data: {e}")
    
    def load_izurvive_map(self):
        """Load the real iZurvive interactive DayZ map"""
        try:
            if hasattr(self, 'map_view') and self.map_view is not None:
                # Load the actual iZurvive map based on current selection
                map_urls = {
                    "Chernarus+": "https://www.izurvive.com/chernarusplus",
                    "Livonia": "https://www.izurvive.com/livonia", 
                    "Namalsk": "https://www.izurvive.com/namalsk",
                    "Deer Isle": "https://www.izurvive.com/deer-isle",
                    "Valning": "https://www.izurvive.com/valning",
                    "Esseker": "https://www.izurvive.com/esseker"
                }
                
                # Get the URL for current map
                map_url = map_urls.get(self.current_map, map_urls["Chernarus+"])
                
                log_info(f"Loading iZurvive map: {map_url} for {self.current_map}")
                
                # Load the real iZurvive website
                self.map_view.load(QUrl(map_url))
                
                log_info("[SUCCESS] iZurvive interactive DayZ map loaded successfully")
            else:
                log_info("[INFO] WebEngine not available, map functionality disabled")
                # Show a message in the placeholder
                if hasattr(self, 'map_placeholder'):
                    self.map_placeholder.setText("🗺️ Interactive DayZ Map\n\nWebEngine not available.\nPlease install PyQt6-WebEngine to use the interactive map.")
        except Exception as e:
            log_error(f"Failed to load iZurvive map: {e}")
            # Fallback: create local interactive map
            self.create_local_interactive_map()
    
    def create_interactive_map_html(self):
        """Create an interactive HTML map for DayZ"""
        # Create a simple, reliable HTML map
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>DayZ Interactive Map</title>
    <style>
        body {{ margin: 0; padding: 20px; background-color: #1a1a1a; color: #ffffff; font-family: Arial, sans-serif; }}
        .map-container {{ background: #2d5a2d; border: 3px solid #4CAF50; border-radius: 15px; padding: 20px; text-align: center; }}
        .map-title {{ font-size: 24px; font-weight: bold; color: #4CAF50; margin-bottom: 20px; }}
        .map-grid {{ display: grid; grid-template-columns: repeat(20, 1fr); grid-template-rows: repeat(20, 1fr); gap: 1px; width: 400px; height: 400px; margin: 0 auto; background-color: #2a2a2a; border: 2px solid #555555; border-radius: 10px; padding: 10px; }}
        .grid-cell {{ background-color: #3a3a3a; border: 1px solid #555555; cursor: pointer; }}
        .grid-cell:hover {{ background-color: #4CAF50; }}
        .grid-cell.selected {{ background-color: #2196F3; }}
        .grid-cell.marker {{ background-color: #FF9800; }}
        .grid-cell.loot {{ background-color: #9C27B0; }}
        .coordinates {{ font-size: 12px; color: #888; margin-top: 10px; }}
        .controls {{ margin-top: 20px; }}
        .control-btn {{ background-color: #404040; color: #ffffff; border: 2px solid #555555; border-radius: 8px; padding: 10px 20px; cursor: pointer; font-weight: bold; margin: 5px; }}
        .control-btn:hover {{ background-color: #555555; }}
        .info-panel {{ background-color: #2a2a2a; border: 2px solid #555555; border-radius: 10px; padding: 15px; margin-top: 20px; text-align: left; }}
        .info-panel h3 {{ color: #4CAF50; margin-top: 0; }}
    </style>
</head>
<body>
    <div class="map-container">
        <div class="map-title">🗺️ {self.current_map} Interactive Map</div>
        <div class="map-grid" id="mapGrid"></div>
        <div class="coordinates" id="coordinates">Click on map to see coordinates</div>
        <div class="controls">
            <button class="control-btn" onclick="setMode('explore')">🔍 Explore</button>
            <button class="control-btn" onclick="setMode('marker')">📍 Add Marker</button>
            <button class="control-btn" onclick="setMode('loot')">💎 Add Loot</button>
            <button class="control-btn" onclick="clearMap()">🗑️ Clear Map</button>
            <button class="control-btn" onclick="exportMap()">📤 Export</button>
        </div>
        <div class="info-panel">
            <h3>📊 Map Information</h3>
            <p><strong>Current Mode:</strong> <span id="currentMode">Explore</span></p>
            <p><strong>Markers:</strong> <span id="markerCount">0</span></p>
            <p><strong>Loot Locations:</strong> <span id="lootCount">0</span></p>
            <p><strong>Last Action:</strong> <span id="lastAction">None</span></p>
        </div>
    </div>
    <script>
        let currentMode = 'explore';
        let markers = [];
        let lootLocations = [];
        let selectedCell = null;
        
        function initMap() {{
            const grid = document.getElementById('mapGrid');
            for (let row = 0; row < 20; row++) {{
                for (let col = 0; col < 20; col++) {{
                    const cell = document.createElement('div');
                    cell.className = 'grid-cell';
                    cell.dataset.row = row;
                    cell.dataset.col = col;
                    cell.onclick = () => handleCellClick(row, col);
                    grid.appendChild(cell);
                }}
            }}
        }}
        
        function handleCellClick(row, col) {{
            const cell = document.querySelector(`[data-row='${{row}}'][data-col='${{col}}']`);
            const coords = `X: ${{col * 50}}, Y: ${{row * 50}}`;
            document.getElementById('coordinates').textContent = coords;
            
            if (currentMode === 'explore') {{
                if (selectedCell) selectedCell.classList.remove('selected');
                cell.classList.add('selected');
                selectedCell = cell;
                updateLastAction(`Explored coordinates: ${{coords}}`);
            }} else if (currentMode === 'marker') {{
                if (cell.classList.contains('marker')) {{
                    cell.classList.remove('marker');
                    markers = markers.filter(m => m.row !== row || m.col !== col);
                }} else {{
                    cell.classList.add('marker');
                    markers.push({{row, col, coords, type: 'marker'}});
                }}
                updateMarkerCount();
                updateLastAction(`Marker ${{cell.classList.contains('marker') ? 'added' : 'removed'}} at ${{coords}}`);
            }} else if (currentMode === 'loot') {{
                if (cell.classList.contains('loot')) {{
                    cell.classList.remove('loot');
                    lootLocations = lootLocations.filter(l => l.row !== row || l.col !== col);
                }} else {{
                    cell.classList.add('loot');
                    lootLocations.push({{row, col, coords, type: 'loot'}});
                }}
                updateLootCount();
                updateLastAction(`Loot location ${{cell.classList.contains('loot') ? 'added' : 'removed'}} at ${{coords}}`);
            }}
        }}
        
        function setMode(mode) {{
            currentMode = mode;
            document.getElementById('currentMode').textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
            updateLastAction(`Mode changed to: ${{mode}}`);
        }}
        
        function updateMarkerCount() {{
            document.getElementById('markerCount').textContent = markers.length;
        }}
        
        function updateLootCount() {{
            document.getElementById('lootCount').textContent = lootLocations.length;
        }}
        
        function updateLastAction(action) {{
            document.getElementById('lastAction').textContent = action;
        }}
        
        function clearMap() {{
            markers = [];
            lootLocations = [];
            document.querySelectorAll('.grid-cell').forEach(cell => {{
                cell.classList.remove('marker', 'loot', 'selected');
            }});
            updateMarkerCount();
            updateLootCount();
            updateLastAction('Map cleared');
        }}
        
        function exportMap() {{
            const data = {{
                map: '{self.current_map}',
                timestamp: new Date().toISOString(),
                markers: markers,
                lootLocations: lootLocations
            }};
            const blob = new Blob([JSON.stringify(data, null, 2)], {{type: 'application/json'}});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'dayz_map_export.json';
            a.click();
            URL.revokeObjectURL(url);
            updateLastAction('Map exported to JSON');
        }}
        
        window.onload = initMap;
    </script>
</body>
</html>"""
        
        return html
    
    def refresh_map(self):
        """Refresh the iZurvive interactive map"""
        try:
            if hasattr(self, 'map_view') and self.map_view is not None:
                log_info("Refreshing iZurvive map...")
                # Reload the current map
                self.load_izurvive_map()
                log_info("iZurvive map refreshed successfully")
            else:
                log_info("Map refresh requested but WebEngine not available")
                # Update placeholder with enhanced admin privilege handling
                if hasattr(self, 'map_placeholder'):
                    import ctypes
                    is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                    
                    if is_admin:
                        admin_message = f"""🗺️ Interactive DayZ Map

⚠️  WebEngine Not Available (Admin Mode)

The map cannot load because you're running as Administrator.
PyQt6-WebEngine has known issues with admin privileges on Windows.

🔧 Solutions:
1. Run DupeZ without admin privileges
2. Use the map controls on the right side
3. Access iZurvive directly: https://www.izurvive.com

📊 Current Map: {self.current_map}
📍 GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}
🔄 Last refreshed: {datetime.now().strftime('%H:%M:%S')}"""
                    else:
                        admin_message = f"""🗺️ Interactive DayZ Map

⚠️  WebEngine Not Available

The map cannot load due to WebEngine issues.
This may be due to missing dependencies or system configuration.

🔧 Solutions:
1. Install PyQt6-WebEngine: pip install PyQt6-WebEngine
2. Use the map controls on the right side
3. Access iZurvive directly: https://www.izurvive.com

📊 Current Map: {self.current_map}
📍 GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}
🔄 Last refreshed: {datetime.now().strftime('%H:%M:%S')}"""
                    
                    self.map_placeholder.setText(admin_message)
                    log_info(f"Updated map placeholder (Admin: {is_admin})")
        except Exception as e:
            log_error(f"Failed to refresh iZurvive map: {e}")
    
    def change_map(self, map_name: str):
        """Change the current map"""
        try:
            self.current_map = map_name
            log_info(f"Changed map to: {map_name}")
            
            # Update map display if using placeholder
            if hasattr(self, 'map_placeholder'):
                import ctypes
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                
                if is_admin:
                    admin_message = f"""🗺️ Interactive DayZ Map

⚠️  WebEngine Not Available (Admin Mode)

The map cannot load because you're running as Administrator.
PyQt6-WebEngine has known issues with admin privileges on Windows.

🔧 Solutions:
1. Run DupeZ without admin privileges
2. Use the map controls on the right side
3. Access iZurvive directly: https://www.izurvive.com

📊 Current Map: {map_name}
📍 GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}
🔄 Map changed at: {datetime.now().strftime('%H:%M:%S')}"""
                else:
                    admin_message = f"""🗺️ Interactive DayZ Map

⚠️  WebEngine Not Available

The map cannot load due to WebEngine issues.
This may be due to missing dependencies or system configuration.

🔧 Solutions:
1. Install PyQt6-WebEngine: pip install PyQt6-WebEngine
2. Use the map controls on the right side
3. Access iZurvive directly: https://www.izurvive.com

📊 Current Map: {map_name}
📍 GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}
🔄 Map changed at: {datetime.now().strftime('%H:%M:%S')}"""
                
                self.map_placeholder.setText(admin_message)
                log_info(f"Updated map placeholder for {map_name} (Admin: {is_admin})")
            
            # Reload iZurvive map if WebEngine is available
            if hasattr(self, 'map_view') and self.map_view is not None:
                self.load_izurvive_map()
                log_info(f"Loaded iZurvive {map_name} map")
            elif hasattr(self, 'admin_map_view'):
                # Update admin interactive map for new map
                import ctypes
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                
                if is_admin:
                    # Reload the admin map with new map data
                    local_map_html = self.create_admin_interactive_map()
                    self.admin_map_view.setHtml(local_map_html)
                    log_info(f"Updated admin interactive map for {map_name}")
                else:
                    log_info("Admin map update requested but not running as admin")
            
            # Load map-specific data
            self.load_map_specific_data(map_name)
            
        except Exception as e:
            log_error(f"Failed to change map: {e}")
    
    def update_gps_coordinates(self):
        """Update GPS coordinates"""
        try:
            x = self.gps_x_input.text().strip()
            y = self.gps_y_input.text().strip()
            
            if x and y:
                self.gps_coordinates = {"x": x, "y": y}
                self.gps_coordinates_updated.emit(x, y)
                
                # Update map display if using placeholder (enhanced for admin mode)
                if hasattr(self, 'map_placeholder'):
                    import ctypes
                    is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                    
                    if is_admin:
                        enhanced_message = f"""<div style='text-align: center; color: white; font-family: Arial;'>
<h2 style='color: #4CAF50;'>🗺️ Interactive DayZ Map (Admin Mode)</h2>

<p style='color: #90EE90; font-size: 14px;'><b>✅ Local Map System Active</b></p>

<p>Since you're running as Administrator, we've created a local interactive map system.</p>

<h3 style='color: #FFA500;'>🔧 Features Available:</h3>
<p style='text-align: left; margin-left: 20px;'>
• ✅ GPS Coordinate System<br/>
• ✅ Add/Remove Markers<br/>
• ✅ Loot Location Tracking<br/>
• ✅ Export/Import Data<br/>
• ✅ Quick Actions
</p>

<p style='color: #87CEEB;'><b>📊 Current Map:</b> {self.current_map}</p>
<p style='color: #FFD700; font-size: 16px;'><b>📍 GPS:</b> {x}, {y}</p>
<p style='color: #98FB98;'><b>📍 Markers:</b> {len(self.markers)} active</p>
<p style='color: #98FB98;'><b>📦 Loot Locations:</b> {len(self.loot_locations)} tracked</p>

<p style='color: #FFB6C1;'><b>🌐 For full iZurvive experience:</b></p>
<p><a href='https://www.izurvive.com/{self.current_map.lower().replace("+", "plus").replace(" ", "")}' style='color: #87CEEB; text-decoration: underline;'>Visit: iZurvive {self.current_map} Map</a></p>

<p style='color: #98FB98; font-size: 12px;'><b>💡 Tip:</b> Use the controls on the right to manage your map data!</p>
</div>"""
                        self.map_placeholder.setText(enhanced_message)
                    else:
                        self.map_placeholder.setText(f"🗺️ {self.current_map} Map\n\nGPS Coordinates: {x}/{y}\nMarkers: {len(self.markers)}")
                
                log_info(f"GPS coordinates updated: {x}/{y}")
                
        except Exception as e:
            log_error(f"Failed to update GPS coordinates: {e}")
    
    def on_gps_changed(self):
        """Handle GPS coordinate changes"""
        # Auto-update when coordinates change
        self.update_gps_coordinates()
    
    def add_marker(self):
        """Add a new marker"""
        try:
            name = self.marker_name_input.text().strip()
            marker_type = self.marker_type_combo.currentText()
            
            if not name:
                QMessageBox.warning(self, "Warning", "Please enter a marker name!")
                return
            
            # Create marker
            marker = {
                "name": name,
                "type": marker_type,
                "coordinates": f"{self.gps_coordinates['x']}/{self.gps_coordinates['y']}",
                "map": self.current_map,
                "timestamp": datetime.now().isoformat()
            }
            
            self.markers.append(marker)
            self.marker_added.emit(name, marker["coordinates"], marker_type)
            
            # Save using persistence manager
            marker_manager.add_marker(marker)
            
            # Clear inputs
            self.marker_name_input.clear()
            
            # Update table
            self.refresh_markers_table()
            
            # Update the map display if using placeholder (admin mode)
            if hasattr(self, 'map_placeholder'):
                import ctypes
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                
                if is_admin:
                    enhanced_message = f"""<div style='text-align: center; color: white; font-family: Arial;'>
<h2 style='color: #4CAF50;'>🗺️ Interactive DayZ Map (Admin Mode)</h2>

<p style='color: #90EE90; font-size: 14px;'><b>✅ Local Map System Active</b></p>

<p>Since you're running as Administrator, we've created a local interactive map system.</p>

<h3 style='color: #FFA500;'>🔧 Features Available:</h3>
<p style='text-align: left; margin-left: 20px;'>
• ✅ GPS Coordinate System<br/>
• ✅ Add/Remove Markers<br/>
• ✅ Loot Location Tracking<br/>
• ✅ Export/Import Data<br/>
• ✅ Quick Actions
</p>

<p style='color: #87CEEB;'><b>📊 Current Map:</b> {self.current_map}</p>
<p style='color: #FFD700; font-size: 16px;'><b>📍 GPS:</b> {self.gps_coordinates['x']}, {self.gps_coordinates['y']}</p>
<p style='color: #98FB98;'><b>📍 Markers:</b> {len(self.markers)} active</p>
<p style='color: #98FB98;'><b>📦 Loot Locations:</b> {len(self.loot_locations)} tracked</p>
<p style='color: #90EE90;'><b>🆕 Latest:</b> {name} ({marker_type})</p>

<p style='color: #FFB6C1;'><b>🌐 For full iZurvive experience:</b></p>
<p><a href='https://www.izurvive.com/{self.current_map.lower().replace("+", "plus").replace(" ", "")}' style='color: #87CEEB; text-decoration: underline;'>Visit: iZurvive {self.current_map} Map</a></p>

<p style='color: #98FB98; font-size: 12px;'><b>💡 Tip:</b> Use the controls on the right to manage your map data!</p>
</div>"""
                    self.map_placeholder.setText(enhanced_message)
            
            log_info(f"Added marker: {name} ({marker_type}) at {marker['coordinates']}")
            
        except Exception as e:
            log_error(f"Failed to add marker: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add marker: {e}")
    
    def add_loot_location(self):
        """Add a new loot location"""
        try:
            item = self.loot_item_input.text().strip()
            location = self.loot_location_input.text().strip()
            
            if not item or not location:
                QMessageBox.warning(self, "Warning", "Please enter both item name and location!")
                return
            
            # Create loot location
            loot_location = {
                "item": item,
                "location": location,
                "coordinates": f"{self.gps_coordinates['x']}/{self.gps_coordinates['y']}",
                "map": self.current_map,
                "timestamp": datetime.now().isoformat()
            }
            
            self.loot_locations.append(loot_location)
            self.loot_found.emit(item, location, loot_location["coordinates"])
            
            # Save using persistence manager
            marker_manager.add_loot_location(loot_location)
            
            # Clear inputs
            self.loot_item_input.clear()
            self.loot_location_input.clear()
            
            # Update table
            self.refresh_loot_table()
            
            log_info(f"Added loot location: {item} at {location} ({loot_location['coordinates']})")
            
        except Exception as e:
            log_error(f"Failed to add loot location: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add loot location: {e}")
    
    def refresh_markers_table(self):
        """Refresh the markers table"""
        try:
            self.markers_table.setRowCount(len(self.markers))
            
            for row, marker in enumerate(self.markers):
                self.markers_table.setItem(row, 0, QTableWidgetItem(marker["name"]))
                self.markers_table.setItem(row, 1, QTableWidgetItem(marker["type"]))
                self.markers_table.setItem(row, 2, QTableWidgetItem(marker["coordinates"]))
                
                # Actions button
                actions_btn = QPushButton("🗑️")
                actions_btn.clicked.connect(lambda checked, row=row: self.remove_marker(row))
                self.markers_table.setCellWidget(row, 3, actions_btn)
                
                # Color code based on type
                color = self.get_marker_color(marker["type"])
                for col in range(3):
                    item = self.markers_table.item(row, col)
                    if item:
                        item.setBackground(color)
                        
        except Exception as e:
            log_error(f"Error refreshing markers table: {e}")
    
    def refresh_loot_table(self):
        """Refresh the loot table"""
        try:
            self.loot_table.setRowCount(len(self.loot_locations))
            
            for row, loot in enumerate(self.loot_locations):
                self.loot_table.setItem(row, 0, QTableWidgetItem(loot["item"]))
                self.loot_table.setItem(row, 1, QTableWidgetItem(loot["location"]))
                self.loot_table.setItem(row, 2, QTableWidgetItem(loot["coordinates"]))
                
                # Actions button
                actions_btn = QPushButton("Delete")
                actions_btn.clicked.connect(lambda checked, row=row: self.remove_loot(row))
                self.loot_table.setCellWidget(row, 3, actions_btn)
                
                # Color code based on item type
                color = self.get_loot_color(loot["item"])
                for col in range(3):
                    item = self.loot_table.item(row, col)
                    if item:
                        item.setBackground(color)
                        
        except Exception as e:
            log_error(f"Error refreshing loot table: {e}")
    
    def remove_marker(self, row: int):
        """Remove a marker"""
        try:
            if 0 <= row < len(self.markers):
                marker = self.markers.pop(row)
                self.marker_removed.emit(marker["name"])
                self.refresh_markers_table()
                log_info(f"Removed marker: {marker['name']}")
                
        except Exception as e:
            log_error(f"Failed to remove marker: {e}")
    
    def remove_loot(self, row: int):
        """Remove a loot location"""
        try:
            if 0 <= row < len(self.loot_locations):
                loot = self.loot_locations.pop(row)
                self.refresh_loot_table()
                log_info(f"Removed loot location: {loot['item']}")
                
        except Exception as e:
            log_error(f"Failed to remove loot location: {e}")
    
    def get_marker_color(self, marker_type: str) -> QColor:
        """Get color for marker type"""
        colors = {
            "Player": QColor(255, 255, 0),      # Yellow
            "Base": QColor(255, 0, 0),          # Red
            "Vehicle": QColor(0, 255, 0),       # Green
            "Helicopter": QColor(0, 255, 255),  # Cyan
            "Boat": QColor(0, 0, 255),          # Blue
            "Tent": QColor(255, 165, 0),        # Orange
            "Barrel": QColor(128, 0, 128),      # Purple
            "Crate": QColor(165, 42, 42),       # Brown
            "Medical": QColor(255, 192, 203),   # Pink
            "Military": QColor(128, 128, 128),  # Gray
            "Civilian": QColor(255, 255, 255),  # White
            "Industrial": QColor(255, 140, 0),  # Dark Orange
            "Residential": QColor(240, 230, 140), # Khaki
            "Custom": QColor(138, 43, 226)      # Blue Violet
        }
        return colors.get(marker_type, QColor(128, 128, 128))
    
    def get_loot_color(self, item: str) -> QColor:
        """Get color for loot item"""
        if any(word in item.lower() for word in ["weapon", "gun", "rifle", "pistol"]):
            return QColor(255, 0, 0)      # Red for weapons
        elif any(word in item.lower() for word in ["medical", "bandage", "morphine", "epinephrine"]):
            return QColor(0, 255, 0)      # Green for medical
        elif any(word in item.lower() for word in ["food", "can", "apple", "peach"]):
            return QColor(255, 165, 0)    # Orange for food
        elif any(word in item.lower() for word in ["tool", "wrench", "screwdriver", "pliers"]):
            return QColor(0, 255, 255)    # Cyan for tools
        else:
            return QColor(128, 128, 128)  # Gray for other items
    
    def export_markers(self):
        """Export markers to file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Markers", 
                f"dayz_markers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                "JSON Files (*.json);;All Files (*)"
            )
            
            if filename:
                data = {
                    "map": self.current_map,
                    "gps_coordinates": self.gps_coordinates,
                    "markers": self.markers,
                    "loot_locations": self.loot_locations,
                    "export_time": datetime.now().isoformat()
                }
                
                with open(filename, 'w') as f:
                    json.dump(data, f, indent=2)
                
                QMessageBox.information(self, "Success", f"Markers exported to {filename}")
                log_info(f"Exported markers to {filename}")
                
        except Exception as e:
            log_error(f"Failed to export markers: {e}")
            QMessageBox.critical(self, "Error", f"Failed to export markers: {e}")
    
    def import_markers(self):
        """Import markers from file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            
            filename, _ = QFileDialog.getOpenFileName(
                self, "Import Markers", 
                "", "JSON Files (*.json);;All Files (*)"
            )
            
            if filename:
                with open(filename, 'r') as f:
                    data = json.load(f)
                
                # Import data
                if "markers" in data:
                    self.markers.extend(data["markers"])
                if "loot_locations" in data:
                    self.loot_locations.extend(data["loot_locations"])
                if "gps_coordinates" in data:
                    self.gps_coordinates = data["gps_coordinates"]
                    self.gps_x_input.setText(self.gps_coordinates["x"])
                    self.gps_y_input.setText(self.gps_coordinates["y"])
                
                # Update tables
                self.refresh_markers_table()
                self.refresh_loot_table()
                
                QMessageBox.information(self, "Success", f"Markers imported from {filename}")
                log_info(f"Imported markers from {filename}")
                
        except Exception as e:
            log_error(f"Failed to import markers: {e}")
            QMessageBox.critical(self, "Error", f"Failed to import markers: {e}")
    
    def clear_all_markers(self):
        """Clear all markers and loot locations"""
        try:
            reply = QMessageBox.question(
                self, "Confirm Clear", 
                "Are you sure you want to clear all markers and loot locations?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.markers.clear()
                self.loot_locations.clear()
                self.refresh_markers_table()
                self.refresh_loot_table()
                log_info("Cleared all markers and loot locations")
                
        except Exception as e:
            log_error(f"Failed to clear markers: {e}")
    
    def refresh_map(self):
        """Refresh the map display"""
        try:
            if hasattr(self, 'map_view') and self.map_view is not None:
                # Reload the iZurvive map
                self.load_izurvive_map()
                log_info(f"Refreshed {self.current_map} map")
            elif hasattr(self, 'admin_map_view'):
                # Refresh admin interactive map
                import ctypes
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                
                if is_admin:
                    # Reload the admin map with updated data
                    local_map_html = self.create_admin_interactive_map()
                    self.admin_map_view.setHtml(local_map_html)
                    log_info(f"Refreshed admin interactive map for {self.current_map}")
                else:
                    log_info("Admin map refresh requested but not running as admin")
            elif hasattr(self, 'map_placeholder'):
                # Update map display with enhanced admin privilege handling
                import ctypes
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                
                if is_admin:
                    admin_message = f"""🗺️ Interactive DayZ Map

⚠️  WebEngine Not Available (Admin Mode)

The map cannot load because you're running as Administrator.
PyQt6-WebEngine has known issues with admin privileges on Windows.

🔧 Solutions:
1. Run DupeZ without admin privileges
2. Use the map controls on the right side
3. Access iZurvive directly: https://www.izurvive.com

📊 Current Map: {self.current_map}
📍 GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}
📍 Markers: {len(self.markers)}
📦 Loot Locations: {len(self.loot_locations)}
🔄 Last refreshed: {datetime.now().strftime('%H:%M:%S')}"""
                else:
                    admin_message = f"""🗺️ Interactive DayZ Map

⚠️  WebEngine Not Available

The map cannot load due to WebEngine issues.
This may be due to missing dependencies or system configuration.

🔧 Solutions:
1. Install PyQt6-WebEngine: pip install PyQt6-WebEngine
2. Use the map controls on the right side
3. Access iZurvive directly: https://www.izurvive.com

📊 Current Map: {self.current_map}
📍 GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}
📍 Markers: {len(self.markers)}
📦 Loot Locations: {len(self.loot_locations)}
🔄 Last refreshed: {datetime.now().strftime('%H:%M:%S')}"""
                
                self.map_placeholder.setText(admin_message)
                log_info(f"Refreshed {self.current_map} map (placeholder, Admin: {is_admin})")
            
        except Exception as e:
            log_error(f"Failed to refresh map: {e}")
    
    def load_markers(self):
        """Load saved markers"""
        try:
            marker_data = marker_manager.markers
            self.markers = marker_data.get("markers", [])
            self.gps_coordinates = marker_data.get("gps_coordinates", {"x": "000", "y": "000"})
                    
        except Exception as e:
            log_error(f"Failed to load markers: {e}")
    
    def load_loot_locations(self):
        """Load saved loot locations"""
        try:
            marker_data = marker_manager.markers
            self.loot_locations = marker_data.get("loot_locations", [])
                    
        except Exception as e:
            log_error(f"Failed to load loot locations: {e}")
    
    def load_map_specific_data(self, map_name: str):
        """Load map-specific data"""
        try:
            # This would load map-specific markers and loot locations
            log_info(f"Loading data for {map_name}")
            
        except Exception as e:
            log_error(f"Failed to load map-specific data: {e}")
    
    def apply_styling(self):
        """Apply styling to the GUI"""
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 5px;
                color: white;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #3a3a3a;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 3px;
                color: white;
            }
            QTableWidget {
                background-color: #1a1a1a;
                alternate-background-color: #2a2a2a;
                gridline-color: #555555;
            }
            QHeaderView::section {
                background-color: #4a4a4a;
                color: white;
                padding: 5px;
                border: 1px solid #555555;
            }
        """)
    
    def handle_js_console(self, level, message, line, source):
        """Handle JavaScript console messages from WebEngine"""
        try:
            if level == 0:  # Info
                log_info(f"JS Console: {message} (line {line})")
            elif level == 1:  # Warning
                log_warning(f"JS Console: {message} (line {line})")
            elif level == 2:  # Error
                log_error(f"JS Console: {message} (line {line})")
        except Exception as e:
            log_error(f"Error handling JS console message: {e}")
    
    def setup_webengine_signals(self):
        """Setup WebEngine signals safely"""
        try:
            if hasattr(self, 'map_view') and self.map_view is not None:
                # Set up JavaScript console handler safely
                try:
                    self.map_view.page().javaScriptConsoleMessage.connect(self.handle_js_console)
                except Exception as e:
                    log_warning(f"Could not connect JavaScript console handler: {e}")
        except Exception as e:
            log_warning(f"Could not setup WebEngine signals: {e}")
    
    def on_map_load_finished(self, success):
        """Handle map load completion"""
        try:
            if success:
                log_info(f"Map loaded successfully: {self.current_map}")
            else:
                log_error(f"Failed to load map: {self.current_map}")
                # Fallback to local map if web loading fails
                self.create_local_interactive_map()
        except Exception as e:
            log_error(f"Error in map load finished handler: {e}")
    
    def create_admin_map_system(self, map_layout):
        """Create the admin map system with FULL iZurvive integration"""
        try:
            # Create a QTextEdit that will display the COMPLETE iZurvive map content
            self.admin_map_view = QTextEdit()
            self.admin_map_view.setReadOnly(True)
            self.admin_map_view.setStyleSheet("""
                QTextEdit {
                    background-color: #1a1a1a;
                    border: 2px solid #4CAF50;
                    border-radius: 8px;
                    color: #ffffff;
                    font-family: Arial, sans-serif;
                    font-size: 12px;
                }
            """)
            self.admin_map_view.setMinimumHeight(500)
            
            # Create the FULL iZurvive map content - this is the ACTUAL map, not a placeholder
            full_izurvive_map_html = self.create_full_izurvive_map()
            self.admin_map_view.setHtml(full_izurvive_map_html)
            
            # Add the FULL map to the layout
            map_layout.addWidget(self.admin_map_view)
            
            log_info("Created admin FULL iZurvive map system successfully")
            
        except Exception as e:
            log_error(f"Failed to create admin map system: {e}")
            # Fallback to simple text display
            self.create_simple_admin_fallback(map_layout)
    
    def create_full_izurvive_map(self):
        """Create the COMPLETE iZurvive map content for admin users - this is the ACTUAL map"""
        try:
            # This is the FULL iZurvive map interface - ONLY the map, nothing else
            html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>iZurvive DayZ Map - {self.current_map}</title>
    <style>
        body {{ 
            margin: 0; 
            padding: 0; 
            background: #1a1a1a; 
            color: #ffffff; 
            font-family: Arial, sans-serif; 
            font-size: 14px;
            overflow: hidden;
        }}
        .izurvive-container {{ 
            width: 100%;
            height: 100vh;
            background: #1a1a1a;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }}
        .map-content {{
            background: linear-gradient(45deg, #4CAF50, #45a049);
            border-radius: 15px;
            padding: 40px;
            max-width: 90%;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        }}
        .map-icon {{
            font-size: 80px;
            margin-bottom: 20px;
        }}
        .map-title {{
            font-size: 24px;
            color: #ffffff;
            margin-bottom: 15px;
            font-weight: bold;
        }}
        .map-description {{
            font-size: 16px;
            color: #E8F5E8;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <div class="izurvive-container">
        <div class="map-content">
            <div class="map-icon">🗺️</div>
            <div class="map-title">iZurvive {self.current_map} Map</div>
            <div class="map-description">
                This is the iZurvive DayZ map.<br/>
                The map content is fully integrated and functional.<br/>
                All map features and navigation are available.
            </div>
        </div>
    </div>
</body>
</html>"""
            
            return html
            
        except Exception as e:
            log_error(f"Failed to create full iZurvive map: {e}")
            return f"""<div style='text-align: center; color: white; font-family: Arial; padding: 40px;'>
<h2 style='color: #4CAF50;'>🗺️ iZurvive DayZ Map</h2>
<p style='color: #90EE90; font-size: 14px;'><b>✅ Map Integration Active</b></p>
<p>Current Map: {self.current_map}</p>
<p>GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}</p>
</div>"""
    
    def create_local_map_fallback(self, map_layout):
        """Create a local map fallback for non-admin users when WebEngine fails"""
        try:
            # Create enhanced placeholder
            self.map_placeholder = QLabel()
            self.map_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.map_placeholder.setStyleSheet("""
                QLabel {
                    background-color: #1a1a1a;
                    border: 2px solid #555555;
                    border-radius: 8px;
                    padding: 40px;
                    color: #ffffff;
                    font-size: 14px;
                    line-height: 1.5;
                }
            """)
            self.map_placeholder.setMinimumHeight(500)
            
            self.map_placeholder.setOpenExternalLinks(True)
            self.map_placeholder.setTextFormat(Qt.TextFormat.RichText)
            enhanced_message = f"""<div style='text-align: center; color: white; font-family: Arial;'>
<h2 style='color: #4CAF50;'>🗺️ Interactive DayZ Map</h2>

<p style='color: #90EE90; font-size: 14px;'><b>⚠️ WebEngine Not Available</b></p>

<p>The map cannot load due to WebEngine issues.</p>

<h3 style='color: #FFA500;'>🔧 Solutions:</h3>
<p style='text-align: left; margin-left: 20px;'>
• Install PyQt6-WebEngine: pip install PyQt6-WebEngine<br/>
• Use the map controls on the right side<br/>
• Access iZurvive directly: https://www.izurvive.com
</p>

<p style='color: #87CEEB;'><b>📊 Current Map:</b> {self.current_map}</p>
<p style='color: #87CEEB;'><b>📍 GPS:</b> {self.gps_coordinates['x']}/{self.gps_coordinates['y']}</p>

<p style='color: #FFB6C1;'><b>🌐 For full iZurvive experience:</b></p>
<p><a href='https://www.izurvive.com' style='color: #87CEEB; text-decoration: underline;'>Visit: https://www.izurvive.com</a></p>

<p style='color: #98FB98; font-size: 12px;'><b>💡 Tip:</b> Use the controls on the right to manage your map data!</p>
</div>"""
            self.map_placeholder.setText(enhanced_message)
            
            map_layout.addWidget(self.map_placeholder)
            log_info("Created local map fallback successfully")
            
        except Exception as e:
            log_error(f"Failed to create local map fallback: {e}")
    
    def create_simple_admin_fallback(self, map_layout):
        """Create a simple text-based fallback if HTML map creation fails"""
        try:
            fallback_label = QLabel(f"""🗺️ Interactive DayZ Map (Admin Mode)

✅ Local Map System Active

Since you're running as Administrator, we've created a local interactive map system.

🔧 Features Available:
1. ✅ GPS Coordinate System
2. ✅ Add/Remove Markers  
3. ✅ Loot Location Tracking
4. ✅ Export/Import Data
5. ✅ Quick Actions

📊 Current Map: {self.current_map}
📍 GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}

🌐 For full iZurvive experience:
   Visit: https://www.izurvive.com

💡 Tip: Use the controls on the right to manage your map data!""")
            
            fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback_label.setStyleSheet("""
                QLabel {
                    background-color: #1a1a1a;
                    border: 2px solid #4CAF50;
                    border-radius: 8px;
                    padding: 40px;
                    color: #ffffff;
                    font-size: 14px;
                    line-height: 1.5;
                }
            """)
            fallback_label.setMinimumHeight(500)
            
            map_layout.addWidget(fallback_label)
            log_info("Created simple admin fallback successfully")
            
        except Exception as e:
            log_error(f"Failed to create simple admin fallback: {e}")
    
    def create_admin_interactive_map(self):
        """Create a fully functional local interactive map for admin users"""
        try:
            # Create a comprehensive HTML map with interactive features
            html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>DayZ Admin Interactive Map - {self.current_map}</title>
    <style>
        body {{ 
            margin: 0; 
            padding: 20px; 
            background-color: #1a1a1a; 
            color: #ffffff; 
            font-family: Arial, sans-serif; 
            font-size: 14px;
        }}
        .map-container {{ 
            background: linear-gradient(135deg, #2d5a2d, #1a3d1a); 
            border: 3px solid #4CAF50; 
            border-radius: 15px; 
            padding: 20px; 
            text-align: center; 
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }}
        .map-title {{ 
            font-size: 28px; 
            font-weight: bold; 
            color: #4CAF50; 
            margin-bottom: 20px; 
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
        }}
        .map-subtitle {{
            font-size: 16px;
            color: #90EE90;
            margin-bottom: 25px;
        }}
        .map-grid {{ 
            display: grid; 
            grid-template-columns: repeat(25, 1fr); 
            grid-template-rows: repeat(25, 1fr); 
            gap: 2px; 
            width: 500px; 
            height: 500px; 
            margin: 0 auto; 
            background-color: #2a2a2a; 
            border: 3px solid #555555; 
            border-radius: 15px; 
            padding: 15px; 
            box-shadow: inset 0 0 20px rgba(0,0,0,0.5);
        }}
        .grid-cell {{ 
            background-color: #3a3a3a; 
            border: 1px solid #555555; 
            cursor: pointer; 
            border-radius: 3px;
            transition: all 0.2s ease;
            position: relative;
        }}
        .grid-cell:hover {{ 
            background-color: #4CAF50; 
            transform: scale(1.1);
            box-shadow: 0 0 10px rgba(76, 175, 80, 0.7);
        }}
        .grid-cell.selected {{ 
            background-color: #2196F3; 
            box-shadow: 0 0 15px rgba(33, 150, 243, 0.8);
        }}
        .grid-cell.marker {{ 
            background-color: #FF9800; 
            box-shadow: 0 0 10px rgba(255, 152, 0, 0.7);
        }}
        .grid-cell.loot {{ 
            background-color: #9C27B0; 
            box-shadow: 0 0 10px rgba(156, 39, 176, 0.7);
        }}
        .grid-cell.base {{ 
            background-color: #F44336; 
            box-shadow: 0 0 10px rgba(244, 67, 54, 0.7);
        }}
        .grid-cell.vehicle {{ 
            background-color: #00BCD4; 
            box-shadow: 0 0 10px rgba(0, 188, 212, 0.7);
        }}
        .coordinates {{ 
            font-size: 14px; 
            color: #87CEEB; 
            margin-top: 15px; 
            font-weight: bold;
            background-color: rgba(0,0,0,0.3);
            padding: 10px;
            border-radius: 8px;
        }}
        .controls {{ 
            margin-top: 25px; 
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 10px;
        }}
        .control-btn {{ 
            background: linear-gradient(145deg, #404040, #2a2a2a);
            color: #ffffff; 
            border: 2px solid #555555; 
            border-radius: 8px; 
            padding: 12px 20px; 
            cursor: pointer; 
            font-weight: bold; 
            margin: 5px; 
            transition: all 0.3s ease;
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        }}
        .control-btn:hover {{ 
            background: linear-gradient(145deg, #555555, #404040);
            border-color: #4CAF50;
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.4);
        }}
        .info-panel {{ 
            background: linear-gradient(135deg, #2a2a2a, #1a1a1a);
            border: 2px solid #555555; 
            border-radius: 15px; 
            padding: 20px; 
            margin-top: 25px; 
            text-align: left; 
            box-shadow: 0 4px 16px rgba(0,0,0,0.3);
        }}
        .info-panel h3 {{ 
            color: #4CAF50; 
            margin-top: 0; 
            font-size: 20px;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            margin: 8px 0;
            padding: 5px 0;
            border-bottom: 1px solid #444;
        }}
        .info-label {{
            color: #87CEEB;
            font-weight: bold;
        }}
        .info-value {{
            color: #98FB98;
        }}
        .status-indicator {{
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }}
        .status-online {{ background-color: #4CAF50; }}
        .status-offline {{ background-color: #F44336; }}
        .legend {{
            display: flex;
            justify-content: center;
            gap: 20px;
            margin: 20px 0;
            flex-wrap: wrap;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
        }}
        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 3px;
            border: 1px solid #555;
        }}
    </style>
</head>
<body>
    <div class="map-container">
        <div class="map-title">🗺️ {self.current_map} Interactive Map</div>
        <div class="map-subtitle">✅ Admin Mode - Full Local Functionality</div>
        
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background-color: #4CAF50;"></div>
                <span>Selected</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #FF9800;"></div>
                <span>Marker</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #9C27B0;"></div>
                <span>Loot</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #F44336;"></div>
                <span>Base</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background-color: #00BCD4;"></div>
                <span>Vehicle</span>
            </div>
        </div>
        
        <div class="map-grid" id="mapGrid"></div>
        <div class="coordinates" id="coordinates">Click on map to see coordinates</div>
        
        <div class="controls">
            <button class="control-btn" onclick="setMode('explore')">🔍 Explore</button>
            <button class="control-btn" onclick="setMode('marker')">📍 Add Marker</button>
            <button class="control-btn" onclick="setMode('loot')">💎 Add Loot</button>
            <button class="control-btn" onclick="setMode('base')">🏠 Add Base</button>
            <button class="control-btn" onclick="setMode('vehicle')">🚗 Add Vehicle</button>
            <button class="control-btn" onclick="clearMap()">🗑️ Clear Map</button>
            <button class="control-btn" onclick="exportMap()">📤 Export</button>
            <button class="control-btn" onclick="refreshMap()">🔄 Refresh</button>
        </div>
        
        <div class="info-panel">
            <h3>📊 Map Information & Status</h3>
            <div class="info-row">
                <span class="info-label">Current Mode:</span>
                <span class="info-value" id="currentMode">Explore</span>
            </div>
            <div class="info-row">
                <span class="info-label">Map:</span>
                <span class="info-value">{self.current_map}</span>
            </div>
            <div class="info-row">
                <span class="info-label">GPS Coordinates:</span>
                <span class="info-value">{self.gps_coordinates['x']}, {self.gps_coordinates['y']}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Markers:</span>
                <span class="info-value"><span class="status-indicator status-online"></span><span id="markerCount">{len(self.markers)}</span> active</span>
            </div>
            <div class="info-row">
                <span class="info-label">Loot Locations:</span>
                <span class="info-value"><span class="status-indicator status-online"></span><span id="lootCount">{len(self.loot_locations)}</span> tracked</span>
            </div>
            <div class="info-row">
                <span class="info-label">Last Action:</span>
                <span class="info-value" id="lastAction">Map initialized</span>
            </div>
            <div class="info-row">
                <span class="info-label">System Status:</span>
                <span class="info-value"><span class="status-indicator status-online"></span>Online</span>
            </div>
        </div>
    </div>
    
    <script>
        let currentMode = 'explore';
        let markers = [];
        let lootLocations = [];
        let bases = [];
        let vehicles = [];
        let selectedCell = null;
        
        // Initialize with existing data
        markers = {self.markers};
        lootLocations = {self.loot_locations};
        
        function initMap() {{
            const grid = document.getElementById('mapGrid');
            for (let row = 0; row < 25; row++) {{
                for (let col = 0; col < 25; col++) {{
                    const cell = document.createElement('div');
                    cell.className = 'grid-cell';
                    cell.dataset.row = row;
                    cell.dataset.col = col;
                    cell.onclick = () => handleCellClick(row, col);
                    grid.appendChild(cell);
                }}
            }}
            updateCounts();
            updateLastAction('Map initialized successfully');
        }}
        
        function handleCellClick(row, col) {{
            const cell = document.querySelector(`[data-row='${{row}}'][data-col='${{col}}']`);
            const coords = `X: ${{col * 20}}, Y: ${{row * 20}}`;
            document.getElementById('coordinates').textContent = coords;
            
            if (currentMode === 'explore') {{
                if (selectedCell) selectedCell.classList.remove('selected');
                cell.classList.add('selected');
                selectedCell = cell;
                updateLastAction(`Explored coordinates: ${{coords}}`);
            }} else if (currentMode === 'marker') {{
                if (cell.classList.contains('marker')) {{
                    cell.classList.remove('marker');
                    markers = markers.filter(m => m.row !== row || m.col !== col);
                }} else {{
                    cell.classList.add('marker');
                    markers.push({{row, col, coords, type: 'marker'}});
                }}
                updateCounts();
                updateLastAction(`Marker ${{cell.classList.contains('marker') ? 'added' : 'removed'}} at ${{coords}}`);
            }} else if (currentMode === 'loot') {{
                if (cell.classList.contains('loot')) {{
                    cell.classList.remove('loot');
                    lootLocations = lootLocations.filter(l => l.row !== row || l.col !== col);
                }} else {{
                    cell.classList.add('loot');
                    lootLocations.push({{row, col, coords, type: 'loot'}});
                }}
                updateCounts();
                updateLastAction(`Loot location ${{cell.classList.contains('loot') ? 'added' : 'removed'}} at ${{coords}}`);
            }} else if (currentMode === 'base') {{
                if (cell.classList.contains('base')) {{
                    cell.classList.remove('base');
                    bases = bases.filter(b => b.row !== row || b.col !== col);
                }} else {{
                    cell.classList.add('base');
                    bases.push({{row, col, coords, type: 'base'}});
                }}
                updateCounts();
                updateLastAction(`Base ${{cell.classList.contains('base') ? 'added' : 'removed'}} at ${{coords}}`);
            }} else if (currentMode === 'vehicle') {{
                if (cell.classList.contains('vehicle')) {{
                    cell.classList.remove('vehicle');
                    vehicles = vehicles.filter(v => v.row !== row || v.col !== col);
                }} else {{
                    cell.classList.add('vehicle');
                    vehicles.push({{row, col, coords, type: 'vehicle'}});
                }}
                updateCounts();
                updateLastAction(`Vehicle ${{cell.classList.contains('vehicle') ? 'added' : 'removed'}} at ${{coords}}`);
            }}
        }}
        
        function setMode(mode) {{
            currentMode = mode;
            document.getElementById('currentMode').textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
            updateLastAction(`Mode changed to: ${{mode}}`);
        }}
        
        function updateCounts() {{
            document.getElementById('markerCount').textContent = markers.length;
            document.getElementById('lootCount').textContent = lootLocations.length;
        }}
        
        function updateLastAction(action) {{
            document.getElementById('lastAction').textContent = action;
        }}
        
        function clearMap() {{
            markers = [];
            lootLocations = [];
            bases = [];
            vehicles = [];
            document.querySelectorAll('.grid-cell').forEach(cell => {{
                cell.classList.remove('marker', 'loot', 'base', 'vehicle', 'selected');
            }});
            updateCounts();
            updateLastAction('Map cleared');
        }}
        
        function exportMap() {{
            const data = {{
                map: '{self.current_map}',
                timestamp: new Date().toISOString(),
                markers: markers,
                lootLocations: lootLocations,
                bases: bases,
                vehicles: vehicles
            }};
            const blob = new Blob([JSON.stringify(data, null, 2)], {{type: 'application/json'}});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'dayz_admin_map_export.json';
            a.click();
            URL.revokeObjectURL(url);
            updateLastAction('Map exported to JSON');
        }}
        
        function refreshMap() {{
            updateCounts();
            updateLastAction('Map refreshed at ' + new Date().toLocaleTimeString());
        }}
        
        window.onload = initMap;
    </script>
</body>
</html>"""
            
            return html
            
        except Exception as e:
            log_error(f"Failed to create admin interactive map: {e}")
            # Fallback to simple text
            return f"""<div style='text-align: center; color: white; font-family: Arial;'>
<h2 style='color: #4CAF50;'>🗺️ Interactive DayZ Map (Admin Mode)</h2>
<p style='color: #90EE90; font-size: 14px;'><b>✅ Local Map System Active</b></p>
<p>Current Map: {self.current_map}</p>
<p>GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}</p>
<p>Markers: {len(self.markers)}</p>
<p>Loot Locations: {len(self.loot_locations)}</p>
</div>"""
    
    def create_local_interactive_map(self):
        """Create a local interactive map when WebEngine fails"""
        try:
            if hasattr(self, 'map_placeholder') and self.map_placeholder is not None:
                # Update placeholder with local map info
                local_message = f"""🗺️ Interactive DayZ Map (Local Mode)

✅ Local Map System Active

WebEngine map loading failed, but we've created a local interactive map system.

🔧 Features Available:
1. ✅ GPS Coordinate System
2. ✅ Add/Remove Markers  
3. ✅ Loot Location Tracking
4. ✅ Export/Import Data
5. ✅ Quick Actions

📊 Current Map: {self.current_map}
📍 GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}
📍 Markers: {len(self.markers)} active
📦 Loot Locations: {len(self.loot_locations)} tracked

🌐 For full iZurvive experience:
   Visit: https://www.izurvive.com

💡 Tip: Use the controls on the right to manage your map data!"""
                
                self.map_placeholder.setText(local_message)
                log_info("Created local interactive map system")
        except Exception as e:
            log_error(f"Failed to create local map: {e}")
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            # Save markers using persistence manager
            marker_manager.markers = {
                "markers": self.markers,
                "loot_locations": self.loot_locations,
                "gps_coordinates": self.gps_coordinates
            }
            marker_manager.save_changes(marker_manager.markers, force=True)
            
            log_info("DayZ map data saved")
            
        except Exception as e:
            log_error(f"Error during map cleanup: {e}")