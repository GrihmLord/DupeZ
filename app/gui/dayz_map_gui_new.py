#!/usr/bin/env python3
"""
DayZ Map GUI - iZurvive Integration for Admin Build
Interactive DayZ map with full iZurvive functionality
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, 
    QGroupBox, QMessageBox, QFileDialog, QSplitter, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView
from typing import List, Dict
import json
import os
from datetime import datetime
from app.logs.logger import log_info, log_error

class DayZMapGUI(QWidget):
    """Interactive DayZ map with full iZurvive integration"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.markers = []
        self.loot_locations = []
        self.gps_coordinates = {"x": "000", "y": "000"}
        self.current_map = "Chernarus+"
        self.setup_ui()
        self.connect_signals()
        self.load_map_data()
        
    def setup_ui(self):
        """Setup the main UI with iZurvive map"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🗺️ DayZ Interactive Map (iZurvive)")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin: 10px; text-align: center;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Create splitter for map and controls
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet("QSplitter::handle { background-color: #4CAF50; }")
        
        # Map area (left side) - iZurvive integration
        map_group = QGroupBox("🗺️ iZurvive DayZ Map")
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
        
        # Map selection
        map_selection_layout = QHBoxLayout()
        map_selection_layout.setSpacing(10)
        
        map_label = QLabel("Map:")
        map_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 12px;")
        
        self.map_combo = QComboBox()
        self.map_combo.addItems([
            "Chernarus+", "Livonia", "Namalsk", "Deer Isle", 
            "Valning", "Esseker", "Chiemsee", "Rostow"
        ])
        self.map_combo.setCurrentText(self.current_map)
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
            QComboBox:hover { border-color: #4CAF50; }
        """)
        
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
            QPushButton:hover { background-color: #1976D2; }
        """)
        
        map_selection_layout.addWidget(map_label)
        map_selection_layout.addWidget(self.map_combo)
        map_selection_layout.addWidget(refresh_btn)
        map_selection_layout.addStretch()
        map_layout.addLayout(map_selection_layout)
        
        # iZurvive Web View
        self.map_view = QWebEngineView()
        self.map_view.setMinimumHeight(600)
        self.map_view.setMinimumWidth(800)
        self.map_view.setStyleSheet("""
            QWebEngineView {
                border: 2px solid #4CAF50;
                border-radius: 8px;
                background-color: #1a1a1a;
            }
        """)
        
        map_layout.addWidget(self.map_view)
        map_group.setLayout(map_layout)
        splitter.addWidget(map_group)
        
        # Controls area (right side)
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
        
        # GPS coordinates
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
        gps_layout = QVBoxLayout()
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
            QLineEdit:focus { border-color: #4CAF50; }
        """)
        
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
            QLineEdit:focus { border-color: #4CAF50; }
        """)
        
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
            QPushButton:hover { background-color: #45a049; }
        """)
        
        gps_layout.addWidget(gps_x_label)
        gps_layout.addWidget(self.gps_x_input)
        gps_layout.addWidget(gps_y_label)
        gps_layout.addWidget(self.gps_y_input)
        gps_layout.addWidget(self.update_gps_btn)
        gps_group.setLayout(gps_layout)
        controls_layout.addWidget(gps_group)
        
        # Markers
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
        
        # Add marker
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
            QLineEdit:focus { border-color: #2196F3; }
        """)
        
        self.marker_type_combo = QComboBox()
        self.marker_type_combo.addItems([
            "Player", "Base", "Vehicle", "Helicopter", "Boat",
            "Tent", "Barrel", "Crate", "Medical", "Military"
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
            QComboBox:hover { border-color: #2196F3; }
        """)
        
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
            QPushButton:hover { background-color: #1976D2; }
        """)
        
        add_marker_layout.addWidget(self.marker_name_input)
        add_marker_layout.addWidget(self.marker_type_combo)
        add_marker_layout.addWidget(self.add_marker_btn)
        markers_layout.addLayout(add_marker_layout)
        
        # Markers table
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
        
        # Quick actions
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
        actions_layout = QVBoxLayout()
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
            QPushButton:hover { background-color: #45a049; }
        """)
        
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
            QPushButton:hover { background-color: #1976D2; }
        """)
        
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
            QPushButton:hover { background-color: #D32F2F; }
        """)
        
        actions_layout.addWidget(self.export_markers_btn)
        actions_layout.addWidget(self.import_markers_btn)
        actions_layout.addWidget(self.clear_all_btn)
        actions_group.setLayout(actions_layout)
        controls_layout.addWidget(actions_group)
        
        controls_group.setLayout(controls_layout)
        splitter.addWidget(controls_group)
        
        # Set splitter proportions
        splitter.setSizes([800, 400])
        layout.addWidget(splitter)
        
        self.setLayout(layout)
        
        # Load iZurvive map
        QTimer.singleShot(1000, self.load_izurvive_map)
        
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
            
            # Update tables
            self.refresh_markers_table()
            
            log_info("DayZ map data loaded successfully")
            
        except Exception as e:
            log_error(f"Failed to load map data: {e}")
    
    def load_izurvive_map(self):
        """Load the real iZurvive interactive DayZ map"""
        try:
            # Map URLs for different DayZ maps
            map_urls = {
                "Chernarus+": "https://www.izurvive.com/chernarusplus",
                "Livonia": "https://www.izurvive.com/livonia", 
                "Namalsk": "https://www.izurvive.com/namalsk",
                "Deer Isle": "https://www.izurvive.com/deer-isle",
                "Valning": "https://www.izurvive.com/valning",
                "Esseker": "https://www.izurvive.com/esseker",
                "Chiemsee": "https://www.izurvive.com/chiemsee",
                "Rostow": "https://www.izurvive.com/rostow"
            }
            
            # Get the URL for current map
            map_url = map_urls.get(self.current_map, map_urls["Chernarus+"])
            
            log_info(f"Loading iZurvive map: {map_url} for {self.current_map}")
            
            # Load the real iZurvive website
            self.map_view.load(QUrl(map_url))
            
            # Set up load finished handler
            self.map_view.loadFinished.connect(self.on_map_load_finished)
            
            log_info("[SUCCESS] iZurvive interactive DayZ map loaded successfully")
            
        except Exception as e:
            log_error(f"Failed to load iZurvive map: {e}")
    
    def refresh_map(self):
        """Refresh the iZurvive interactive map"""
        try:
            log_info("Refreshing iZurvive map...")
            self.load_izurvive_map()
            log_info("iZurvive map refreshed successfully")
        except Exception as e:
            log_error(f"Failed to refresh iZurvive map: {e}")
    
    def change_map(self, map_name: str):
        """Change the current map"""
        try:
            self.current_map = map_name
            log_info(f"Changed map to: {map_name}")
            
            # Reload iZurvive map
            self.load_izurvive_map()
            
        except Exception as e:
            log_error(f"Failed to change map: {e}")
    
    def update_gps_coordinates(self):
        """Update GPS coordinates"""
        try:
            x = self.gps_x_input.text().strip()
            y = self.gps_y_input.text().strip()
            
            if x and y:
                self.gps_coordinates = {"x": x, "y": y}
                log_info(f"GPS coordinates updated: {x}/{y}")
                
        except Exception as e:
            log_error(f"Failed to update GPS coordinates: {e}")
    
    def on_gps_changed(self):
        """Handle GPS coordinate changes"""
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
            
            # Clear inputs
            self.marker_name_input.clear()
            
            # Update table
            self.refresh_markers_table()
            
            log_info(f"Added marker: {name} ({marker_type}) at {marker['coordinates']}")
            
        except Exception as e:
            log_error(f"Failed to add marker: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add marker: {e}")
    
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
    
    def remove_marker(self, row: int):
        """Remove a marker"""
        try:
            if 0 <= row < len(self.markers):
                marker = self.markers.pop(row)
                self.refresh_markers_table()
                log_info(f"Removed marker: {marker['name']}")
                
        except Exception as e:
            log_error(f"Failed to remove marker: {e}")
    
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
        }
        return colors.get(marker_type, QColor(128, 128, 128))
    
    def export_markers(self):
        """Export markers to file"""
        try:
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
                if "gps_coordinates" in data:
                    self.gps_coordinates = data["gps_coordinates"]
                    self.gps_x_input.setText(self.gps_coordinates["x"])
                    self.gps_y_input.setText(self.gps_coordinates["y"])
                
                # Update tables
                self.refresh_markers_table()
                
                QMessageBox.information(self, "Success", f"Markers imported from {filename}")
                log_info(f"Imported markers from {filename}")
                
        except Exception as e:
            log_error(f"Failed to import markers: {e}")
            QMessageBox.critical(self, "Error", f"Failed to import markers: {e}")
    
    def clear_all_markers(self):
        """Clear all markers"""
        try:
            reply = QMessageBox.question(
                self, "Confirm Clear", 
                "Are you sure you want to clear all markers?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.markers.clear()
                self.refresh_markers_table()
                log_info("Cleared all markers")
                
        except Exception as e:
            log_error(f"Failed to clear markers: {e}")
    
    def load_markers(self):
        """Load saved markers"""
        try:
            # Load from file if exists
            marker_file = "app/data/dayz_markers.json"
            if os.path.exists(marker_file):
                with open(marker_file, 'r') as f:
                    data = json.load(f)
                    self.markers = data.get("markers", [])
                    self.gps_coordinates = data.get("gps_coordinates", {"x": "000", "y": "000"})
                    
        except Exception as e:
            log_error(f"Failed to load markers: {e}")
    
    def on_map_load_finished(self, success):
        """Handle map load completion"""
        try:
            if success:
                log_info(f"iZurvive map loaded successfully: {self.current_map}")
            else:
                log_error(f"Failed to load iZurvive map: {self.current_map}")
        except Exception as e:
            log_error(f"Error in map load finished handler: {e}")
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            # Save markers to file
            marker_file = "app/data/dayz_markers.json"
            os.makedirs(os.path.dirname(marker_file), exist_ok=True)
            
            data = {
                "markers": self.markers,
                "gps_coordinates": self.gps_coordinates
            }
            
            with open(marker_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            log_info("DayZ map data saved")
            
        except Exception as e:
            log_error(f"Error during map cleanup: {e}")
