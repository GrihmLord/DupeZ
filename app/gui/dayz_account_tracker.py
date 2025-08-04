# app/gui/dayz_account_tracker.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QLineEdit, QComboBox, QTextEdit, QGroupBox,
                             QTabWidget, QSplitter, QFrame, QHeaderView,
                             QMessageBox, QInputDialog, QColorDialog,
                             QCheckBox, QSpinBox, QFormLayout, QDialog)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    # Fallback if WebEngine is not available
    QWebEngineView = None
import json
import os
from typing import Dict, List, Optional
from datetime import datetime

from app.logs.logger import log_info, log_error
from app.core.data_persistence import account_manager

class DayZAccountTracker(QWidget):
    """Comprehensive DayZ account tracker with iZurvive map integration"""
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.accounts = []
        self.current_account = None
        self.map_view = None
        
        try:
            self.setup_ui()
            self.load_accounts()
        except Exception as e:
            log_error(f"Failed to initialize DayZ Account Tracker: {e}")
            # Create a minimal fallback UI
            self._create_fallback_ui()
    
    def _create_fallback_ui(self):
        """Create a minimal fallback UI if initialization fails"""
        try:
            layout = QVBoxLayout()
            
            # Error message
            error_label = QLabel("⚠️ Account Tracker Error\n\nFailed to initialize account tracker.\nPlease restart the application.")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet("""
                QLabel {
                    color: #ff6b6b;
                    background-color: #2b2b2b;
                    border: 1px solid #ff6b6b;
                    border-radius: 4px;
                    padding: 20px;
                    font-size: 12px;
                }
            """)
            layout.addWidget(error_label)
            
            self.setLayout(layout)
            
        except Exception as e:
            log_error(f"Failed to create fallback UI: {e}")
        
    def setup_ui(self):
        """Setup the account tracker UI"""
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(layout)
        
        # Header
        header = QLabel("🎮 DayZ Account Tracker")
        header.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header.setStyleSheet("""
            color: #ffffff;
            padding: 10px;
            background-color: #2c3e50;
            border-radius: 6px;
            margin-bottom: 10px;
        """)
        layout.addWidget(header)
        
        # Main content splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - Account management
        left_panel = self.create_account_panel()
        main_splitter.addWidget(left_panel)
        
        # Right panel - iZurvive map
        right_panel = self.create_map_panel()
        main_splitter.addWidget(right_panel)
        
        # Set splitter proportions (60% accounts, 40% map)
        main_splitter.setSizes([600, 400])
        layout.addWidget(main_splitter)
        
    def create_account_panel(self) -> QWidget:
        """Create the account management panel"""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # Account controls
        controls_group = QGroupBox("📋 Account Management")
        controls_group.setStyleSheet("""
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
        
        controls_layout = QHBoxLayout()
        
        # Add account button
        self.add_account_btn = QPushButton("➕ Add Account")
        self.add_account_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
                min-height: 25px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.add_account_btn.clicked.connect(self.add_account)
        controls_layout.addWidget(self.add_account_btn)
        
        # Edit account button
        self.edit_account_btn = QPushButton("✏️ Edit Account")
        self.edit_account_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
                min-height: 25px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.edit_account_btn.clicked.connect(self.edit_account)
        controls_layout.addWidget(self.edit_account_btn)
        
        # Delete account button
        self.delete_account_btn = QPushButton("🗑️ Delete Account")
        self.delete_account_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
                min-height: 25px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        self.delete_account_btn.clicked.connect(self.delete_account)
        controls_layout.addWidget(self.delete_account_btn)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Account table
        table_group = QGroupBox("📊 Account Details")
        table_group.setStyleSheet("""
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
        
        table_layout = QVBoxLayout()
        
        # Create account table
        self.account_table = QTableWidget()
        self.setup_account_table()
        table_layout.addWidget(self.account_table)
        
        table_group.setLayout(table_layout)
        layout.addWidget(table_group)
        
        # Account details panel
        details_group = QGroupBox("📝 Selected Account Details")
        details_group.setStyleSheet("""
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
        
        details_layout = QFormLayout()
        
        # Account details fields
        self.account_name_label = QLabel("No account selected")
        self.account_name_label.setStyleSheet("color: #888888; font-size: 11px;")
        details_layout.addRow("Account:", self.account_name_label)
        
        self.account_email_label = QLabel("")
        self.account_email_label.setStyleSheet("color: #888888; font-size: 11px;")
        details_layout.addRow("Email:", self.account_email_label)
        
        self.account_location_label = QLabel("")
        self.account_location_label.setStyleSheet("color: #888888; font-size: 11px;")
        details_layout.addRow("Location:", self.account_location_label)
        
        self.account_status_label = QLabel("")
        self.account_status_label.setStyleSheet("color: #888888; font-size: 11px;")
        details_layout.addRow("Status:", self.account_status_label)
        
        self.account_station_label = QLabel("")
        self.account_station_label.setStyleSheet("color: #888888; font-size: 11px;")
        details_layout.addRow("Station:", self.account_station_label)
        
        self.account_gear_label = QLabel("")
        self.account_gear_label.setStyleSheet("color: #888888; font-size: 11px;")
        details_layout.addRow("Gear:", self.account_gear_label)
        
        self.account_holding_label = QLabel("")
        self.account_holding_label.setStyleSheet("color: #888888; font-size: 11px;")
        details_layout.addRow("Holding:", self.account_holding_label)
        
        details_group.setLayout(details_layout)
        layout.addWidget(details_group)
        
        panel.setLayout(layout)
        return panel
        
    def create_map_panel(self) -> QWidget:
        """Create the iZurvive map panel"""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # Map header
        map_header = QLabel("🗺️ iZurvive Map")
        map_header.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        map_header.setStyleSheet("""
            color: #ffffff;
            padding: 8px;
            background-color: #34495e;
            border-radius: 4px;
            margin-bottom: 8px;
        """)
        layout.addWidget(map_header)
        
        # Map controls
        map_controls = QHBoxLayout()
        
        self.refresh_map_btn = QPushButton("🔄 Refresh Map")
        self.refresh_map_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 6px 10px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        self.refresh_map_btn.clicked.connect(self.refresh_map)
        map_controls.addWidget(self.refresh_map_btn)
        
        self.show_all_locations_btn = QPushButton("📍 Show All Locations")
        self.show_all_locations_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: none;
                padding: 6px 10px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
        """)
        self.show_all_locations_btn.clicked.connect(self.show_all_locations)
        map_controls.addWidget(self.show_all_locations_btn)
        
        map_controls.addStretch()
        layout.addLayout(map_controls)
        
        # Map view
        if QWebEngineView is not None:
            self.map_view = QWebEngineView()
            self.map_view.setStyleSheet("""
                QWebEngineView {
                    border: 1px solid #555555;
                    border-radius: 4px;
                    background-color: #2b2b2b;
                }
            """)
            layout.addWidget(self.map_view)
            
            # Load iZurvive map
            self.load_izurvive_map()
        else:
            # Fallback: show a message that WebEngine is not available
            fallback_label = QLabel("🗺️ iZurvive Map\n\nWebEngine not available.\nMap functionality requires PyQt6-WebEngine.")
            fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback_label.setStyleSheet("""
                QLabel {
                    color: #ffffff;
                    background-color: #2b2b2b;
                    border: 1px solid #555555;
                    border-radius: 4px;
                    padding: 20px;
                    font-size: 12px;
                }
            """)
            layout.addWidget(fallback_label)
        
        panel.setLayout(layout)
        return panel
        
    def setup_account_table(self):
        """Setup the account table with columns similar to the spreadsheet"""
        headers = [
            "Account", "Email", "Location", "Status", "Station", "Gear", "Holding"
        ]
        self.account_table.setColumnCount(len(headers))
        self.account_table.setHorizontalHeaderLabels(headers)
        
        # Set table properties
        self.account_table.setAlternatingRowColors(True)
        self.account_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.account_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.account_table.setSortingEnabled(True)
        self.account_table.setWordWrap(True)
        self.account_table.setShowGrid(True)
        self.account_table.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Set responsive column widths
        header = self.account_table.horizontalHeader()
        header.setStretchLastSection(False)
        
        # Column widths based on content
        column_widths = {
            0: 150,  # Account
            1: 200,  # Email
            2: 200,  # Location
            3: 100,  # Status
            4: 120,  # Station
            5: 100,  # Gear
            6: 200   # Holding
        }
        
        for col, width in column_widths.items():
            self.account_table.setColumnWidth(col, width)
            if col == 2:  # Location column stretches
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        
        # Set table styling
        self.account_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                gridline-color: #404040;
                border: 1px solid #555555;
                border-radius: 4px;
                font-size: 10px;
                selection-background-color: #4CAF50;
                selection-color: #ffffff;
            }
            QTableWidget::item {
                padding: 4px;
                border: none;
            }
            QHeaderView::section {
                background-color: #3a3a3a;
                color: white;
                padding: 6px;
                border: 1px solid #555555;
                font-weight: bold;
                font-size: 10px;
            }
        """)
        
        # Connect selection change
        self.account_table.itemSelectionChanged.connect(self.on_account_selected)
        
    def load_izurvive_map(self):
        """Load the iZurvive map"""
        try:
            if self.map_view is not None:
                # Load iZurvive map URL
                from PyQt6.QtCore import QUrl
                map_url = QUrl("https://www.izurvive.com/")
                self.map_view.setUrl(map_url)
                log_info("[SUCCESS] iZurvive map loaded")
            else:
                log_info("[INFO] WebEngine not available, map functionality disabled")
        except Exception as e:
            log_error(f"Failed to load iZurvive map: {e}")
            
    def add_account(self):
        """Add a new account"""
        try:
            # Create account dialog
            account_data = self.show_account_dialog()
            if account_data:
                # Add to accounts list
                account_data['id'] = len(self.accounts) + 1
                account_data['created'] = datetime.now().isoformat()
                self.accounts.append(account_data)
                
                # Add to table
                self.add_account_to_table(account_data)
                
                # Save accounts using persistence manager
                account_manager.add_account(account_data)
                
                log_info(f"[SUCCESS] Added account: {account_data['account']}")
                
        except Exception as e:
            log_error(f"Failed to add account: {e}")
            
    def edit_account(self):
        """Edit selected account"""
        try:
            if not self.current_account:
                QMessageBox.warning(self, "No Selection", "Please select an account to edit.")
                return
                
            # Show edit dialog
            account_data = self.show_account_dialog(self.current_account)
            if account_data:
                # Update account
                account_data['id'] = self.current_account['id']
                account_data['created'] = self.current_account['created']
                account_data['updated'] = datetime.now().isoformat()
                
                # Update in list
                for i, account in enumerate(self.accounts):
                    if account['id'] == self.current_account['id']:
                        self.accounts[i] = account_data
                        break
                
                # Update table
                self.update_account_in_table(account_data)
                
                # Save accounts using persistence manager
                account_manager.update_account(self.current_account['account'], account_data)
                
                log_info(f"[SUCCESS] Updated account: {account_data['account']}")
                
        except Exception as e:
            log_error(f"Failed to edit account: {e}")
            
    def delete_account(self):
        """Delete selected account"""
        try:
            if not self.current_account:
                QMessageBox.warning(self, "No Selection", "Please select an account to delete.")
                return
                
            # Confirm deletion
            reply = QMessageBox.question(
                self, "Confirm Delete", 
                f"Are you sure you want to delete account '{self.current_account['account']}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Remove from list
                self.accounts = [acc for acc in self.accounts if acc['id'] != self.current_account['id']]
                
                # Remove from table
                self.remove_account_from_table(self.current_account['id'])
                
                # Clear current account
                self.current_account = None
                self.update_account_details()
                
                # Save accounts using persistence manager
                account_manager.remove_account(self.current_account['account'])
                
                log_info(f"[SUCCESS] Deleted account: {self.current_account['account']}")
                
        except Exception as e:
            log_error(f"Failed to delete account: {e}")
            
    def show_account_dialog(self, account_data=None) -> Optional[Dict]:
        """Show account input dialog"""
        try:
            # Create dialog
            dialog = QDialog(self)
            dialog.setWindowTitle("Account Details")
            dialog.setModal(True)
            dialog.setStyleSheet("""
                QWidget {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QLineEdit, QComboBox, QTextEdit {
                    background-color: #3a3a3a;
                    border: 1px solid #555555;
                    border-radius: 4px;
                    padding: 6px;
                    color: #ffffff;
                    font-size: 10px;
                }
                QLabel {
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    padding: 8px 12px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 10px;
                    min-height: 25px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
            
            layout = QFormLayout()
            
            # Account fields
            account_input = QLineEdit()
            account_input.setPlaceholderText("e.g., Sir Grihm (Grihmlord)")
            if account_data:
                account_input.setText(account_data.get('account', ''))
            layout.addRow("Account:", account_input)
            
            email_input = QLineEdit()
            email_input.setPlaceholderText("e.g., ismackthebandit@gmail.com")
            if account_data:
                email_input.setText(account_data.get('email', ''))
            layout.addRow("Email:", email_input)
            
            location_input = QLineEdit()
            location_input.setPlaceholderText("e.g., 2602 Deep Woods Base")
            if account_data:
                location_input.setText(account_data.get('location', ''))
            layout.addRow("Location:", location_input)
            
            # Status dropdown
            status_combo = QComboBox()
            status_options = ["Ready", "Blood Infection", "Storage", "Dead", "Offline"]
            status_combo.addItems(status_options)
            if account_data:
                current_status = account_data.get('status', 'Ready')
                index = status_combo.findText(current_status)
                if index >= 0:
                    status_combo.setCurrentIndex(index)
            layout.addRow("Status:", status_combo)
            
            # Station dropdown
            station_combo = QComboBox()
            station_options = ["Exploder Kit", "Pox Kit", "Raider Kit", "Geared", "PVP/Raid Kit", "Raider/PvP Kit", "PvP Kit/Raider Kit"]
            station_combo.addItems(station_options)
            if account_data:
                current_station = account_data.get('station', '')
                index = station_combo.findText(current_station)
                if index >= 0:
                    station_combo.setCurrentIndex(index)
            layout.addRow("Station:", station_combo)
            
            gear_input = QLineEdit()
            gear_input.setPlaceholderText("e.g., Civilian, Blue Hiking Cargo")
            if account_data:
                gear_input.setText(account_data.get('gear', ''))
            layout.addRow("Gear:", gear_input)
            
            holding_input = QTextEdit()
            holding_input.setMaximumHeight(60)
            holding_input.setPlaceholderText("e.g., x3 Crates of Explosives {Holding barrel}")
            if account_data:
                holding_input.setText(account_data.get('holding', ''))
            layout.addRow("Holding:", holding_input)
            
            # Buttons
            button_layout = QHBoxLayout()
            save_btn = QPushButton("Save")
            cancel_btn = QPushButton("Cancel")
            
            save_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            
            button_layout.addWidget(save_btn)
            button_layout.addWidget(cancel_btn)
            layout.addRow("", button_layout)
            
            dialog.setLayout(layout)
            
            # Show dialog
            if dialog.exec() == QDialog.DialogCode.Accepted:
                return {
                    'account': account_input.text(),
                    'email': email_input.text(),
                    'location': location_input.text(),
                    'status': status_combo.currentText(),
                    'station': station_combo.currentText(),
                    'gear': gear_input.text(),
                    'holding': holding_input.toPlainText()
                }
            
            return None
            
        except Exception as e:
            log_error(f"Account dialog error: {e}")
            return None
            
    def add_account_to_table(self, account_data: Dict):
        """Add account to the table"""
        try:
            row = self.account_table.rowCount()
            self.account_table.insertRow(row)
            
            # Set items with color coding - with safe access
            self.account_table.setItem(row, 0, QTableWidgetItem(str(account_data.get('account', ''))))
            self.account_table.setItem(row, 1, QTableWidgetItem(str(account_data.get('email', ''))))
            self.account_table.setItem(row, 2, QTableWidgetItem(str(account_data.get('location', ''))))
            
            # Status with color coding
            status = str(account_data.get('status', ''))
            status_item = QTableWidgetItem(status)
            if status == 'Ready':
                status_item.setForeground(QColor('#4CAF50'))  # Green
            elif status == 'Blood Infection':
                status_item.setForeground(QColor('#f44336'))  # Red
            elif status == 'Storage':
                status_item.setForeground(QColor('#FF9800'))  # Orange
            self.account_table.setItem(row, 3, status_item)
            
            # Station with color coding
            station = str(account_data.get('station', ''))
            station_item = QTableWidgetItem(station)
            if 'Kit' in station:
                station_item.setForeground(QColor('#9C27B0'))  # Purple
            elif station == 'Geared':
                station_item.setForeground(QColor('#FF9800'))  # Orange
            elif 'PvP' in station or 'Raid' in station:
                station_item.setForeground(QColor('#f44336'))  # Red
            self.account_table.setItem(row, 4, station_item)
            
            self.account_table.setItem(row, 5, QTableWidgetItem(str(account_data.get('gear', ''))))
            
            # Holding with color coding
            holding = str(account_data.get('holding', ''))
            holding_item = QTableWidgetItem(holding)
            if 'IED' in holding or 'Explosive' in holding:
                holding_item.setForeground(QColor('#f44336'))  # Red
            elif 'POX' in holding or 'GL' in holding:
                holding_item.setForeground(QColor('#9C27B0'))  # Purple
            self.account_table.setItem(row, 6, holding_item)
            
        except Exception as e:
            log_error(f"Failed to add account to table: {e}")
            # Try to remove the row if it was partially created
            try:
                if self.account_table.rowCount() > 0:
                    self.account_table.removeRow(self.account_table.rowCount() - 1)
            except:
                pass
            
    def update_account_in_table(self, account_data: Dict):
        """Update account in the table"""
        try:
            # Find the row with this account
            for row in range(self.account_table.rowCount()):
                item = self.account_table.item(row, 0)
                if item and item.text() == str(account_data.get('account', '')):
                    # Update items with safe access
                    self.account_table.setItem(row, 1, QTableWidgetItem(str(account_data.get('email', ''))))
                    self.account_table.setItem(row, 2, QTableWidgetItem(str(account_data.get('location', ''))))
                    
                    # Status with color coding
                    status = str(account_data.get('status', ''))
                    status_item = QTableWidgetItem(status)
                    if status == 'Ready':
                        status_item.setForeground(QColor('#4CAF50'))
                    elif status == 'Blood Infection':
                        status_item.setForeground(QColor('#f44336'))
                    elif status == 'Storage':
                        status_item.setForeground(QColor('#FF9800'))
                    self.account_table.setItem(row, 3, status_item)
                    
                    # Station with color coding
                    station = str(account_data.get('station', ''))
                    station_item = QTableWidgetItem(station)
                    if 'Kit' in station:
                        station_item.setForeground(QColor('#9C27B0'))
                    elif station == 'Geared':
                        station_item.setForeground(QColor('#FF9800'))
                    elif 'PvP' in station or 'Raid' in station:
                        station_item.setForeground(QColor('#f44336'))
                    self.account_table.setItem(row, 4, station_item)
                    
                    self.account_table.setItem(row, 5, QTableWidgetItem(str(account_data.get('gear', ''))))
                    
                    # Holding with color coding
                    holding = str(account_data.get('holding', ''))
                    holding_item = QTableWidgetItem(holding)
                    if 'IED' in holding or 'Explosive' in holding:
                        holding_item.setForeground(QColor('#f44336'))
                    elif 'POX' in holding or 'GL' in holding:
                        holding_item.setForeground(QColor('#9C27B0'))
                    self.account_table.setItem(row, 6, holding_item)
                    break
                    
        except Exception as e:
            log_error(f"Failed to update account in table: {e}")
            
    def remove_account_from_table(self, account_id: int):
        """Remove account from the table"""
        try:
            for row in range(self.account_table.rowCount()):
                # Find the row with this account ID
                # This is a simplified version - in practice you'd need to store account IDs in the table
                if row < len(self.accounts) and self.accounts[row]['id'] == account_id:
                    self.account_table.removeRow(row)
                    break
                    
        except Exception as e:
            log_error(f"Failed to remove account from table: {e}")
            
    def on_account_selected(self):
        """Handle account selection"""
        try:
            current_row = self.account_table.currentRow()
            if current_row >= 0 and current_row < self.account_table.rowCount():
                # Get the account ID from the table item
                account_id_item = self.account_table.item(current_row, 0)  # Account column
                if account_id_item:
                    account_name = account_id_item.text()
                    # Find the account in the accounts list
                    for account in self.accounts:
                        if str(account.get('account', '')) == account_name:
                            self.current_account = account
                            self.update_account_details()
                            break
                
        except Exception as e:
            log_error(f"Failed to handle account selection: {e}")
            
    def update_account_details(self):
        """Update the account details panel"""
        try:
            if self.current_account:
                self.account_name_label.setText(str(self.current_account.get('account', '')))
                self.account_email_label.setText(str(self.current_account.get('email', '')))
                self.account_location_label.setText(str(self.current_account.get('location', '')))
                self.account_status_label.setText(str(self.current_account.get('status', '')))
                self.account_station_label.setText(str(self.current_account.get('station', '')))
                self.account_gear_label.setText(str(self.current_account.get('gear', '')))
                self.account_holding_label.setText(str(self.current_account.get('holding', '')))
            else:
                self.account_name_label.setText("No account selected")
                self.account_email_label.setText("")
                self.account_location_label.setText("")
                self.account_status_label.setText("")
                self.account_station_label.setText("")
                self.account_gear_label.setText("")
                self.account_holding_label.setText("")
                
        except Exception as e:
            log_error(f"Failed to update account details: {e}")
            
    def refresh_map(self):
        """Refresh the iZurvive map"""
        try:
            self.load_izurvive_map()
            log_info("[SUCCESS] Map refreshed")
        except Exception as e:
            log_error(f"Failed to refresh map: {e}")
            
    def show_all_locations(self):
        """Show all account locations on the map"""
        try:
            if not self.accounts:
                QMessageBox.information(self, "No Accounts", "No accounts to show on map.")
                return
                
            # This would integrate with iZurvive API to show markers
            # For now, just show a message
            locations = [acc['location'] for acc in self.accounts if acc['location']]
            if locations:
                QMessageBox.information(self, "Account Locations", 
                                      f"Found {len(locations)} account locations:\n" + 
                                      "\n".join(locations))
            else:
                QMessageBox.information(self, "No Locations", "No locations found in accounts.")
                
        except Exception as e:
            log_error(f"Failed to show locations: {e}")
            
    def load_accounts(self):
        """Load accounts from file"""
        try:
            self.accounts = account_manager.accounts
            
            # Add accounts to table with validation
            for account in self.accounts:
                # Validate account data before adding to table
                if self._validate_account_data(account):
                    self.add_account_to_table(account)
                else:
                    log_error(f"Skipping invalid account data: {account}")
                    
            log_info(f"[SUCCESS] Loaded {len(self.accounts)} accounts")
                
        except Exception as e:
            log_error(f"Failed to load accounts: {e}")
    
    def _validate_account_data(self, account: Dict) -> bool:
        """Validate account data before adding to table"""
        try:
            required_fields = ['account', 'email', 'location', 'status', 'station', 'gear', 'holding']
            
            # Check if all required fields exist
            for field in required_fields:
                if field not in account:
                    log_error(f"Missing required field '{field}' in account data")
                    return False
                
                # Ensure all fields are strings
                if not isinstance(account[field], str):
                    account[field] = str(account[field])
            
            return True
            
        except Exception as e:
            log_error(f"Account validation error: {e}")
            return False
            
    def save_accounts(self):
        """Save accounts to file"""
        try:
            account_manager.accounts = self.accounts
            account_manager.save_changes(self.accounts, force=True)
            log_info(f"[SUCCESS] Saved {len(self.accounts)} accounts")
            
        except Exception as e:
            log_error(f"Failed to save accounts: {e}")

# Global instance - removed to prevent QWidget creation during import
# dayz_account_tracker = DayZAccountTracker() 