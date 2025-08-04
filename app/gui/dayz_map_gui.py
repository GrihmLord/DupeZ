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
from PyQt6.QtWebEngineWidgets import QWebEngineView
from typing import List, Dict, Optional, Tuple
import json
import os
import time
from datetime import datetime
from app.logs.logger import log_info, log_error
from app.core.data_persistence import marker_manager

class DayZMapGUI(QWidget):
    """Interactive DayZ map with iZurvive integration"""
    
    # Signals
    marker_added = pyqtSignal(str, str, str)  # name, coordinates, type
    marker_removed = pyqtSignal(str)
    gps_coordinates_updated = pyqtSignal(str, str)  # x, y
    loot_found = pyqtSignal(str, str, str)  # item, location, coordinates
    
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
        """Setup the main UI"""
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("🗺️ DayZ Interactive Map (iZurvive)")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin: 10px;")
        layout.addWidget(title)
        
        # Create splitter for map and controls
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Map area (left side)
        map_group = QGroupBox("🗺️ Interactive Map")
        map_layout = QVBoxLayout()
        
        # Map selection
        map_selection_layout = QHBoxLayout()
        map_label = QLabel("Map:")
        self.map_combo = QComboBox()
        self.map_combo.addItems([
            "Chernarus+", "Livonia", "Namalsk", "Deer Isle", 
            "Chiemsee", "Rostow", "Esseker", "Takistan Plus",
            "Banov", "Swans Island", "Pripyat", "Iztek",
            "Valning", "Zagoria", "Melkart", "Stuart Island"
        ])
        self.map_combo.setCurrentText(self.current_map)
        map_selection_layout.addWidget(map_label)
        map_selection_layout.addWidget(self.map_combo)
        map_selection_layout.addStretch()
        map_layout.addLayout(map_selection_layout)
        
        # Web view for map
        if QWebEngineView is not None:
            self.map_view = QWebEngineView()
            self.map_view.setStyleSheet("""
                QWebEngineView {
                    border: 1px solid #555555;
                    border-radius: 4px;
                    background-color: #2b2b2b;
                }
            """)
            self.map_view.setMinimumHeight(400)
            map_layout.addWidget(self.map_view)
            
            # Load iZurvive map
            self.load_izurvive_map()
        else:
            # Fallback: show a message that WebEngine is not available
            self.map_placeholder = QLabel("🗺️ Interactive DayZ Map\n\nWebEngine not available.\nMap functionality requires PyQt6-WebEngine.")
            self.map_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.map_placeholder.setStyleSheet("""
                QLabel {
                    background-color: #1a1a1a;
                    border: 2px solid #555555;
                    border-radius: 5px;
                    padding: 50px;
                    color: #888888;
                    font-size: 14px;
                }
            """)
            self.map_placeholder.setMinimumHeight(400)
            map_layout.addWidget(self.map_placeholder)
        
        map_group.setLayout(map_layout)
        splitter.addWidget(map_group)
        
        # Controls area (right side)
        controls_group = QGroupBox("🎯 Map Controls")
        controls_layout = QVBoxLayout()
        
        # GPS coordinates
        gps_group = QGroupBox("📍 GPS Coordinates")
        gps_layout = QGridLayout()
        
        gps_x_label = QLabel("X Coordinate:")
        self.gps_x_input = QLineEdit("000")
        self.gps_x_input.setPlaceholderText("Enter X coordinate")
        gps_layout.addWidget(gps_x_label, 0, 0)
        gps_layout.addWidget(self.gps_x_input, 0, 1)
        
        gps_y_label = QLabel("Y Coordinate:")
        self.gps_y_input = QLineEdit("000")
        self.gps_y_input.setPlaceholderText("Enter Y coordinate")
        gps_layout.addWidget(gps_y_label, 1, 0)
        gps_layout.addWidget(self.gps_y_input, 1, 1)
        
        self.update_gps_btn = QPushButton("🔄 Update GPS")
        self.update_gps_btn.clicked.connect(self.update_gps_coordinates)
        gps_layout.addWidget(self.update_gps_btn, 2, 0, 1, 2)
        
        gps_group.setLayout(gps_layout)
        controls_layout.addWidget(gps_group)
        
        # Markers
        markers_group = QGroupBox("📍 Markers")
        markers_layout = QVBoxLayout()
        
        # Add marker
        add_marker_layout = QHBoxLayout()
        self.marker_name_input = QLineEdit()
        self.marker_name_input.setPlaceholderText("Marker name")
        add_marker_layout.addWidget(self.marker_name_input)
        
        self.marker_type_combo = QComboBox()
        self.marker_type_combo.addItems([
            "Player", "Base", "Vehicle", "Helicopter", "Boat",
            "Tent", "Barrel", "Crate", "Medical", "Military",
            "Civilian", "Industrial", "Residential", "Custom"
        ])
        add_marker_layout.addWidget(self.marker_type_combo)
        
        self.add_marker_btn = QPushButton("➕ Add")
        self.add_marker_btn.clicked.connect(self.add_marker)
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
        markers_layout.addWidget(self.markers_table)
        
        markers_group.setLayout(markers_layout)
        controls_layout.addWidget(markers_group)
        
        # Loot locations
        loot_group = QGroupBox("📦 Loot Locations")
        loot_layout = QVBoxLayout()
        
        # Add loot location
        add_loot_layout = QHBoxLayout()
        self.loot_item_input = QLineEdit()
        self.loot_item_input.setPlaceholderText("Item name")
        add_loot_layout.addWidget(self.loot_item_input)
        
        self.loot_location_input = QLineEdit()
        self.loot_location_input.setPlaceholderText("Location")
        add_loot_layout.addWidget(self.loot_location_input)
        
        self.add_loot_btn = QPushButton("➕ Add")
        self.add_loot_btn.clicked.connect(self.add_loot_location)
        add_loot_layout.addWidget(self.add_loot_btn)
        
        loot_layout.addLayout(add_loot_layout)
        
        # Loot table
        self.loot_table = QTableWidget()
        self.loot_table.setColumnCount(4)
        self.loot_table.setHorizontalHeaderLabels([
            "Item", "Location", "Coordinates", "Actions"
        ])
        self.loot_table.horizontalHeader().setStretchLastSection(True)
        self.loot_table.setAlternatingRowColors(True)
        loot_layout.addWidget(self.loot_table)
        
        loot_group.setLayout(loot_layout)
        controls_layout.addWidget(loot_group)
        
        # Quick actions
        actions_group = QGroupBox("⚡ Quick Actions")
        actions_layout = QGridLayout()
        
        self.export_markers_btn = QPushButton("💾 Export Markers")
        self.export_markers_btn.clicked.connect(self.export_markers)
        actions_layout.addWidget(self.export_markers_btn, 0, 0)
        
        self.import_markers_btn = QPushButton("📂 Import Markers")
        self.import_markers_btn.clicked.connect(self.import_markers)
        actions_layout.addWidget(self.import_markers_btn, 0, 1)
        
        self.clear_all_btn = QPushButton("🗑️ Clear All")
        self.clear_all_btn.clicked.connect(self.clear_all_markers)
        actions_layout.addWidget(self.clear_all_btn, 1, 0)
        
        self.refresh_map_btn = QPushButton("🔄 Refresh Map")
        self.refresh_map_btn.clicked.connect(self.refresh_map)
        actions_layout.addWidget(self.refresh_map_btn, 1, 1)
        
        actions_group.setLayout(actions_layout)
        controls_layout.addWidget(actions_group)
        
        controls_group.setLayout(controls_layout)
        splitter.addWidget(controls_group)
        
        # Set splitter proportions
        splitter.setSizes([600, 400])
        layout.addWidget(splitter)
        
        self.setLayout(layout)
        self.apply_styling()
        
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
        """Load the iZurvive map"""
        try:
            if hasattr(self, 'map_view') and self.map_view is not None:
                # Load iZurvive map URL
                map_url = QUrl("https://www.izurvive.com/")
                self.map_view.setUrl(map_url)
                log_info("[SUCCESS] iZurvive map loaded in DayZ Map GUI")
            else:
                log_info("[INFO] WebEngine not available, map functionality disabled")
        except Exception as e:
            log_error(f"Failed to load iZurvive map: {e}")
    
    def change_map(self, map_name: str):
        """Change the current map"""
        try:
            self.current_map = map_name
            log_info(f"Changed map to: {map_name}")
            
            # Update map display if using placeholder
            if hasattr(self, 'map_placeholder'):
                self.map_placeholder.setText(f"🗺️ {map_name} Map\n\nLoading map data...\nGPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}")
            
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
                
                # Update map display if using placeholder
                if hasattr(self, 'map_placeholder'):
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
            elif hasattr(self, 'map_placeholder'):
                # Update map display with current data (fallback)
                self.map_placeholder.setText(
                    f"🗺️ {self.current_map} Map\n\n"
                    f"GPS: {self.gps_coordinates['x']}/{self.gps_coordinates['y']}\n"
                    f"Markers: {len(self.markers)}\n"
                    f"Loot Locations: {len(self.loot_locations)}"
                )
                log_info(f"Refreshed {self.current_map} map (placeholder)")
            
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