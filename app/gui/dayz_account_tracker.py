# app/gui/dayz_account_tracker.py

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QLineEdit, QComboBox, QTextEdit, QGroupBox,
                             QTabWidget, QSplitter, QFrame, QHeaderView,
                             QMessageBox, QInputDialog, QColorDialog,
                             QCheckBox, QSpinBox, QFormLayout, QDialog,
                             QProgressBar, QSlider, QSpinBox, QDateEdit)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QDate
from PyQt6.QtGui import QFont, QColor, QIcon
import json
import os
import csv
from typing import Dict, List, Optional
from datetime import datetime

from app.logs.logger import log_info, log_error, log_warning
from app.core.data_persistence import account_manager

class DayZAccountTracker(QWidget):
    """Comprehensive DayZ account tracker with enhanced features"""
    
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.accounts = []
        self.current_account = None
        self.selected_accounts = set()  # Track multiple selections
        
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
        
        # Account management panel (full width)
        account_panel = self.create_account_panel()
        layout.addWidget(account_panel)
        
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
        controls_layout.setSpacing(5)  # Reduce spacing between buttons
        
        # Add account button
        self.add_account_btn = QPushButton("➕ Add")
        self.add_account_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 6px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.add_account_btn.clicked.connect(self.add_account)
        controls_layout.addWidget(self.add_account_btn)
        
        # Edit account button
        self.edit_account_btn = QPushButton("✏️ Edit")
        self.edit_account_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 6px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.edit_account_btn.clicked.connect(self.edit_account)
        controls_layout.addWidget(self.edit_account_btn)
        
        # Delete account button
        self.delete_account_btn = QPushButton("🗑️ Delete")
        self.delete_account_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 6px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        self.delete_account_btn.clicked.connect(self.delete_account)
        controls_layout.addWidget(self.delete_account_btn)
        
        # Bulk operations button
        self.bulk_ops_btn = QPushButton("⚡ Bulk Ops")
        self.bulk_ops_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF5722;
                color: white;
                border: none;
                padding: 6px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #E64A19;
            }
        """)
        self.bulk_ops_btn.clicked.connect(self.show_bulk_operations)
        controls_layout.addWidget(self.bulk_ops_btn)
        
        # Upload CSV button
        self.upload_csv_btn = QPushButton("📁 Upload")
        self.upload_csv_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 6px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        self.upload_csv_btn.clicked.connect(self.upload_csv_accounts)
        controls_layout.addWidget(self.upload_csv_btn)
        
        # Export CSV button
        self.export_csv_btn = QPushButton("💾 Export")
        self.export_csv_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: none;
                padding: 6px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
        """)
        self.export_csv_btn.clicked.connect(self.export_csv_accounts)
        controls_layout.addWidget(self.export_csv_btn)
        
        # Clear Table button
        self.clear_table_btn = QPushButton("🗑️ Clear All")
        self.clear_table_btn.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f;
                color: white;
                border: none;
                padding: 6px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #b71c1c;
            }
        """)
        self.clear_table_btn.clicked.connect(self.clear_account_table)
        controls_layout.addWidget(self.clear_table_btn)
        
        # Refresh button
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: white;
                border: none;
                padding: 6px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 9px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #0097A7;
            }
        """)
        self.refresh_btn.clicked.connect(self.refresh_account_table)
        controls_layout.addWidget(self.refresh_btn)
        
        # Search functionality
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search accounts...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #424242;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 10px;
                min-height: 22px;
            }
            QLineEdit:focus {
                border-color: #2196F3;
            }
        """)
        self.search_input.textChanged.connect(self.filter_accounts)
        controls_layout.addWidget(self.search_input)
        
        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)
        
        # Account statistics panel
        stats_group = QGroupBox("📊 Account Statistics")
        stats_group.setStyleSheet("""
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
        
        stats_layout = QHBoxLayout()
        
        # Total accounts
        self.total_accounts_label = QLabel("Total: 0")
        self.total_accounts_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 5px;")
        stats_layout.addWidget(self.total_accounts_label)
        
        # Ready accounts
        self.ready_accounts_label = QLabel("Ready: 0")
        self.ready_accounts_label.setStyleSheet("color: #4CAF50; font-weight: bold; padding: 5px;")
        stats_layout.addWidget(self.ready_accounts_label)
        
        # Blood infection accounts
        self.blood_infection_label = QLabel("Blood Infection: 0")
        self.blood_infection_label.setStyleSheet("color: #f44336; font-weight: bold; padding: 5px;")
        stats_layout.addWidget(self.blood_infection_label)
        
        # Storage accounts
        self.storage_label = QLabel("Storage: 0")
        self.storage_label.setStyleSheet("color: #FF9800; font-weight: bold; padding: 5px;")
        stats_layout.addWidget(self.storage_label)
        
        # Dead accounts
        self.dead_label = QLabel("Dead: 0")
        self.dead_label.setStyleSheet("color: #9E9E9E; font-weight: bold; padding: 5px;")
        stats_layout.addWidget(self.dead_label)
        
        # Offline accounts
        self.offline_label = QLabel("Offline: 0")
        self.offline_label.setStyleSheet("color: #607D8B; font-weight: bold; padding: 5px;")
        stats_layout.addWidget(self.offline_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
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
        
        # Status bar
        self.status_label = QLabel("Ready to manage DayZ accounts")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            color: #4CAF50; 
            font-weight: bold; 
            padding: 8px;
            background-color: #1e1e1e;
            border-radius: 4px;
            margin: 5px 0;
        """)
        layout.addWidget(self.status_label)
        
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
        
        self.account_value_label = QLabel("")
        self.account_value_label.setStyleSheet("color: #888888; font-size: 11px;")
        details_layout.addRow("Value:", self.account_value_label)
        
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
        
        # Add account details directly to layout (no splitter needed)
        layout.addWidget(details_group)
        
        panel.setLayout(layout)
        return panel
        
    def setup_account_table(self, accounts_to_show=None):
        """Setup the account table with data"""
        try:
            accounts = accounts_to_show if accounts_to_show is not None else self.accounts
            log_info(f"Setting up account table with {len(accounts)} accounts")
            
            # Set up table structure
            self.account_table.setColumnCount(8)
            self.account_table.setHorizontalHeaderLabels([
                "Account", "Email", "Location", "Value", "Status", "Station", "Gear", "Holding"
            ])
            
            # Set table properties
            self.account_table.setRowCount(len(accounts))
            log_info(f"Set table row count to {len(accounts)}")
            self.account_table.setAlternatingRowColors(True)
            self.account_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.account_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
            self.account_table.setSortingEnabled(True)
            self.account_table.setWordWrap(True)
            self.account_table.setShowGrid(True)
            self.account_table.setGridStyle(Qt.PenStyle.SolidLine)
            
            # Populate table
            log_info("Starting table population...")
            for row, account in enumerate(accounts):
                log_info(f"Populating row {row}: {account.get('account', 'N/A')}")
                self.account_table.setItem(row, 0, QTableWidgetItem(account.get('account', '')))
                self.account_table.setItem(row, 1, QTableWidgetItem(account.get('email', '')))
                self.account_table.setItem(row, 2, QTableWidgetItem(account.get('location', '')))
                self.account_table.setItem(row, 3, QTableWidgetItem(account.get('value', '')))
                self.account_table.setItem(row, 4, QTableWidgetItem(account.get('status', '')))
                self.account_table.setItem(row, 5, QTableWidgetItem(account.get('station', '')))
                self.account_table.setItem(row, 6, QTableWidgetItem(account.get('gear', '')))
                self.account_table.setItem(row, 7, QTableWidgetItem(account.get('holding', '')))
                
                # Color code status
                status_item = self.account_table.item(row, 4)
                if status_item:
                    status = status_item.text()
                    if status == 'Ready':
                        status_item.setBackground(QColor(76, 175, 80))  # Green
                    elif status == 'Blood Infection':
                        status_item.setBackground(QColor(244, 67, 54))  # Red
                    elif status == 'Storage':
                        status_item.setBackground(QColor(255, 152, 0))  # Orange
                    elif status == 'Dead':
                        status_item.setBackground(QColor(158, 158, 158))  # Gray
                    elif status == 'Offline':
                        status_item.setBackground(QColor(96, 125, 139))  # Blue Gray
            
            # Connect selection change
            self.account_table.itemSelectionChanged.connect(self.on_account_selected)
            
            # Auto-resize columns
            self.account_table.resizeColumnsToContents()
            
        except Exception as e:
            log_error(f"Failed to setup account table: {e}")
    
    def add_account(self):
        """Add a new account"""
        try:
            account_data = self.show_account_dialog()
            if account_data:
                # Add unique ID and use consistent field names
                account_data['id'] = len(account_manager.accounts) + 1
                account_data['created_at'] = datetime.now().isoformat()
                account_data['updated_at'] = datetime.now().isoformat()
                
                # Add to account manager
                account_manager.add_account(account_data)
                
                # Refresh local accounts list and UI
                self.accounts = account_manager.accounts
                self.refresh_account_table()
                
                self.status_label.setText(f"Added account: {account_data.get('account', '')}")
                log_info(f"Added new account: {account_data.get('account', '')}")
                
        except Exception as e:
            log_error(f"Failed to add account: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add account: {e}")
    
    def edit_account(self):
        """Edit the selected account"""
        try:
            if not self.current_account:
                QMessageBox.information(self, "No Selection", "Please select an account to edit.")
                return
            
            account_data = self.show_account_dialog(self.current_account)
            if account_data:
                # Update the account with consistent field names
                self.current_account.update(account_data)
                self.current_account['updated_at'] = datetime.now().isoformat()
                
                # Update in account manager
                account_name = self.current_account.get('account', '')
                account_manager.update_account(account_name, self.current_account)
                
                # Refresh local accounts list and UI
                self.accounts = account_manager.accounts
                self.refresh_account_table()
                
                self.status_label.setText(f"Updated account: {self.current_account.get('account', '')}")
                log_info(f"Updated account: {self.current_account.get('account', '')}")
                
        except Exception as e:
            log_error(f"Failed to edit account: {e}")
            QMessageBox.critical(self, "Error", f"Failed to edit account: {e}")
    
    def delete_account(self):
        """Delete the selected account"""
        try:
            if not self.current_account:
                QMessageBox.information(self, "No Selection", "Please select an account to delete.")
                return
            
            reply = QMessageBox.question(
                self, 
                "Delete Account", 
                f"Are you sure you want to delete account '{self.current_account.get('account', '')}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                account_name = self.current_account.get('account', '')
                
                # Remove from account manager
                account_manager.remove_account(account_name)
                
                # Refresh local accounts list and UI
                self.accounts = account_manager.accounts
                self.refresh_account_table()
                self.clear_account_details()
                
                self.status_label.setText(f"Deleted account: {account_name}")
                log_info(f"Deleted account: {account_name}")
                
        except Exception as e:
            log_error(f"Failed to delete account: {e}")
            QMessageBox.critical(self, "Error", f"Failed to delete account: {e}")
    
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
            account_input.setPlaceholderText("Account Name")
            if account_data:
                account_input.setText(account_data.get('account', ''))
            layout.addRow("Account:", account_input)
            
            email_input = QLineEdit()
            email_input.setPlaceholderText("user@domain.com")
            if account_data:
                email_input.setText(account_data.get('email', ''))
            layout.addRow("Email:", email_input)
            
            location_input = QLineEdit()
            location_input.setPlaceholderText("Location or Coordinates")
            if account_data:
                location_input.setText(account_data.get('location', ''))
            layout.addRow("Location:", location_input)
            
            # Value field
            value_input = QLineEdit()
            value_input.setPlaceholderText("Value or Worth")
            if account_data:
                value_input.setText(account_data.get('value', ''))
            layout.addRow("Value:", value_input)
            
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
            gear_input.setPlaceholderText("Equipment Description")
            if account_data:
                gear_input.setText(account_data.get('gear', ''))
            layout.addRow("Gear:", gear_input)
            
            holding_input = QTextEdit()
            holding_input.setMaximumHeight(60)
            holding_input.setPlaceholderText("Items Currently Holding")
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
                    'value': value_input.text(),
                    'status': status_combo.currentText(),
                    'station': station_combo.currentText(),
                    'gear': gear_input.text(),
                    'holding': holding_input.toPlainText()
                }
            
            return None
            
        except Exception as e:
            log_error(f"Account dialog error: {e}")
            return None
    
    def on_account_selected(self):
        """Handle account selection change"""
        try:
            current_row = self.account_table.currentRow()
            log_info(f"Account selection changed - Row: {current_row}")
            
            if current_row >= 0:
                # Get account data from the selected row
                account_name = self.account_table.item(current_row, 0).text()
                log_info(f"Selected account name: {account_name}")
                
                # Find the account in our data
                for account in self.accounts:
                    if account.get('account') == account_name:
                        self.current_account = account
                        log_info(f"Found account in data: {account}")
                        self.update_account_details()
                        break
                else:
                    log_warning(f"Account {account_name} not found in accounts data")
            else:
                self.current_account = None
                log_info("No row selected, clearing account details")
                self.clear_account_details()
                
        except Exception as e:
            log_error(f"Failed to handle account selection: {e}")
    
    def update_account_details(self):
        """Update the account details display"""
        try:
            if self.current_account:
                log_info(f"Updating account details for: {self.current_account.get('account', '')}")
                
                self.account_name_label.setText(self.current_account.get('account', ''))
                self.account_email_label.setText(self.current_account.get('email', ''))
                self.account_location_label.setText(self.current_account.get('location', ''))
                self.account_value_label.setText(self.current_account.get('value', ''))
                self.account_status_label.setText(self.current_account.get('status', ''))
                self.account_station_label.setText(self.current_account.get('station', ''))
                self.account_gear_label.setText(self.current_account.get('gear', ''))
                self.account_holding_label.setText(self.current_account.get('holding', ''))
                
                # Update status label
                self.status_label.setText(f"Selected: {self.current_account.get('account', '')}")
                log_info("Account details updated successfully")
            else:
                log_info("No current account, clearing details")
                self.clear_account_details()
                
        except Exception as e:
            log_error(f"Failed to update account details: {e}")
    
    def clear_account_details(self):
        """Clear the account details display"""
        try:
            self.account_name_label.setText("No account selected")
            self.account_email_label.setText("")
            self.account_location_label.setText("")
            self.account_value_label.setText("")
            self.account_status_label.setText("")
            self.account_station_label.setText("")
            self.account_gear_label.setText("")
            self.account_holding_label.setText("")
            
            self.status_label.setText("Ready to manage DayZ accounts")
            
        except Exception as e:
            log_error(f"Failed to clear account details: {e}")
    
    def load_accounts(self):
        """Load accounts from storage"""
        try:
            # Force reload from account manager
            self.accounts = account_manager.accounts.copy()
            log_info(f"Loaded {len(self.accounts)} accounts from account manager")
            
            # Refresh the table display
            self.refresh_account_table()
            
            # Update statistics
            self.update_statistics()
            
            log_info(f"Successfully loaded and displayed {len(self.accounts)} accounts")
        except Exception as e:
            log_error(f"Failed to load accounts: {e}")
            self.accounts = []
    
    def save_accounts(self):
        """Save accounts to storage"""
        try:
            # Update the account manager's accounts list
            account_manager.accounts = self.accounts.copy()
            # Save changes using the account manager
            account_manager.save_changes(account_manager.accounts)
            log_info(f"Saved {len(self.accounts)} accounts")
        except Exception as e:
            log_error(f"Failed to save accounts: {e}")
    
    def refresh_account_table(self):
        """Refresh the account table display"""
        try:
            log_info(f"Refreshing account table with {len(self.accounts)} accounts")
            self.setup_account_table()
            self.update_statistics()
            log_info("Account table refresh completed successfully")
        except Exception as e:
            log_error(f"Failed to refresh account table: {e}")
    
    def clear_account_table(self):
        """Clear all accounts from the table"""
        try:
            reply = QMessageBox.question(
                self, 
                "Clear All Accounts", 
                "Are you sure you want to clear all accounts? This action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Clear from account manager
                account_manager.accounts.clear()
                account_manager.save_changes(account_manager.accounts)
                
                # Refresh local accounts list and UI
                self.accounts = account_manager.accounts
                self.refresh_account_table()
                self.status_label.setText("All accounts cleared")
                log_info("All accounts cleared")
        except Exception as e:
            log_error(f"Failed to clear accounts: {e}")
            QMessageBox.critical(self, "Error", f"Failed to clear accounts: {e}")
    
    def filter_accounts(self, search_text: str):
        """Filter accounts based on search text"""
        try:
            if not search_text:
                self.refresh_account_table()
                return
            
            # Filter accounts
            filtered_accounts = []
            search_lower = search_text.lower()
            
            for account in self.accounts:
                # Search in multiple fields
                if (search_lower in account.get('account', '').lower() or
                    search_lower in account.get('email', '').lower() or
                    search_lower in account.get('location', '').lower() or
                    search_lower in account.get('status', '').lower() or
                    search_lower in account.get('station', '').lower() or
                    search_lower in account.get('gear', '').lower() or
                    search_lower in account.get('holding', '').lower()):
                    filtered_accounts.append(account)
            
            # Update table with filtered results
            self.setup_account_table(filtered_accounts)
            
        except Exception as e:
            log_error(f"Failed to filter accounts: {e}")
    
    def update_statistics(self):
        """Update the account statistics display"""
        try:
            total = len(self.accounts)
            ready = len([a for a in self.accounts if a.get('status') == 'Ready'])
            blood_infection = len([a for a in self.accounts if a.get('status') == 'Blood Infection'])
            storage = len([a for a in self.accounts if a.get('status') == 'Storage'])
            dead = len([a for a in self.accounts if a.get('status') == 'Dead'])
            offline = len([a for a in self.accounts if a.get('status') == 'Offline'])
            
            self.total_accounts_label.setText(f"Total: {total}")
            self.ready_accounts_label.setText(f"Ready: {ready}")
            self.blood_infection_label.setText(f"Blood Infection: {blood_infection}")
            self.storage_label.setText(f"Storage: {storage}")
            self.dead_label.setText(f"Dead: {dead}")
            self.offline_label.setText(f"Offline: {offline}")
            
        except Exception as e:
            log_error(f"Failed to update statistics: {e}")
    
    def upload_csv_accounts(self):
        """Upload accounts from CSV file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            import csv
            
            file_path, _ = QFileDialog.getOpenFileName(
                self, 
                "Select CSV File", 
                "", 
                "CSV Files (*.csv);;All Files (*)"
            )
            
            if file_path:
                self._process_csv_file(file_path)
                
        except Exception as e:
            log_error(f"Failed to upload CSV accounts: {e}")
            QMessageBox.critical(self, "Error", f"Failed to upload CSV accounts: {e}")
    
    def _process_csv_file(self, file_path: str):
        """Process CSV file and import accounts"""
        try:
            accounts_imported = 0
            accounts_skipped = 0
            
            with open(file_path, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                
                for row_num, row in enumerate(reader, start=2):  # Start at 2 since row 1 is header
                    try:
                        # Debug: Log the raw row data
                        log_info(f"Processing CSV row {row_num}: {dict(row)}")
                        
                        # Map CSV columns to account fields with consistent field names
                        account_data = {
                            'account': row.get('Account', '').strip(),
                            'email': row.get('Email', '').strip(),
                            'location': row.get('Location', '').strip(),
                            'value': row.get('Value', '').strip(),
                            'status': row.get('Status', 'Ready').strip(),  # Default to Ready
                            'station': row.get('Station', '').strip(),
                            'gear': row.get('Gear', '').strip(),
                            'holding': row.get('Holding', '').strip(),
                            'last_seen': datetime.now().isoformat(),
                            'created_date': datetime.now().isoformat(),
                            'id': f"imported_{accounts_imported + 1}_{datetime.now().timestamp()}"
                        }
                        
                        # Validate account data
                        if self._validate_account_data(account_data):
                            # Check for duplicates
                            if not self._is_duplicate_account(account_data):
                                # Add to local accounts list first
                                self.accounts.append(account_data)
                                
                                # Add to account manager
                                try:
                                    account_manager.add_account(account_data)
                                    log_info(f"Successfully added account to manager: {account_data['account']}")
                                except Exception as e:
                                    log_warning(f"Failed to add account to manager: {e}")
                                    # Fallback: add directly to account manager's accounts list
                                    account_manager.accounts.append(account_data)
                                
                                accounts_imported += 1
                                log_info(f"Imported account: {account_data['account']}")
                            else:
                                accounts_skipped += 1
                                log_warning(f"Skipped duplicate account: {account_data['account']}")
                        else:
                            accounts_skipped += 1
                            log_warning(f"Skipped invalid account data at row {row_num}")
                            
                    except Exception as e:
                        accounts_skipped += 1
                        log_error(f"Error processing row {row_num}: {e}")
                        continue
            
            # Save all imported accounts at once
            try:
                account_manager.save_changes(account_manager.accounts)
                log_info("Saved all imported accounts to storage")
            except Exception as e:
                log_error(f"Failed to save imported accounts: {e}")
            
            # Update the display immediately
            log_info("Refreshing account table and statistics...")
            
            # Force table update to ensure data is displayed
            if hasattr(self, 'account_table'):
                log_info("Clearing and rebuilding account table...")
                self.account_table.clearContents()
                self.account_table.setRowCount(0)  # Reset row count
                
                # Ensure we have the latest data from account manager
                self.accounts = account_manager.accounts.copy()
                log_info(f"Updated local accounts list: {len(self.accounts)} accounts")
                
                # Rebuild table with new data
                self.setup_account_table(self.accounts)
                
                # Force refresh of statistics
                self.update_statistics()
                
                # Ensure table is visible and properly sized
                self.account_table.resizeColumnsToContents()
                self.account_table.setVisible(True)
                
                log_info(f"Table rebuilt with {len(self.accounts)} accounts")
                log_info(f"Table now has {self.account_table.rowCount()} rows")
                
                # Debug: Check if accounts are actually in the table
                for i, acc in enumerate(self.accounts):
                    log_info(f"Account {i+1}: {acc.get('account', 'N/A')} - {acc.get('status', 'N/A')}")
                
            # Show results
            QMessageBox.information(
                self, 
                "CSV Import Complete", 
                f"Import completed!\n\n"
                f"✅ Accounts imported: {accounts_imported}\n"
                f"⚠️ Accounts skipped: {accounts_skipped}\n\n"
                f"Total accounts: {len(self.accounts)}"
            )
            
            log_info(f"CSV import completed: {accounts_imported} imported, {accounts_skipped} skipped")
            log_info(f"Final account count: {len(self.accounts)}")
            
        except Exception as e:
            log_error(f"Failed to process CSV file: {e}")
            QMessageBox.critical(self, "Error", f"Failed to process CSV file:\n{e}")
    
    def _validate_account_data(self, data: Dict[str, str]) -> bool:
        """Enhanced validation for account data"""
        try:
            # Check if account field has meaningful content
            account = data.get('account', '').strip()
            if not account or len(account) < 2:
                log_warning(f"Account validation failed: account field too short or empty: '{account}'")
                return False
            
            # Check if account contains only whitespace or special characters
            if account.isspace() or not any(c.isalnum() for c in account):
                log_warning(f"Account validation failed: account field contains no alphanumeric characters: '{account}'")
                return False
            
            # Validate email format if provided
            email = data.get('email', '').strip()
            if email and '@' not in email:
                log_warning(f"Account validation failed: invalid email format: '{email}'")
                return False
            
            # Validate status if provided (allow any non-empty status)
            status = data.get('status', '').strip()
            if status and len(status) < 1:
                log_warning(f"Account validation failed: status field too short: '{status}'")
                return False
            
            log_info(f"Account validation passed for: {account}")
            return True
            
        except Exception as e:
            log_error(f"Error in account validation: {e}")
            return False
    
    def _is_duplicate_account(self, account_data: Dict) -> bool:
        """Check if account is a duplicate using account manager"""
        try:
            for account in account_manager.accounts:
                if (account.get('account') == account_data.get('account') and
                    account.get('email') == account_data.get('email')):
                    return True
            return False
        except Exception as e:
            log_error(f"Failed to check for duplicate account: {e}")
            return False
    
    def export_csv_accounts(self):
        """Export accounts to CSV file"""
        try:
            from PyQt6.QtWidgets import QFileDialog
            import csv
            
            if not self.accounts:
                QMessageBox.information(self, "No Accounts", "No accounts to export.")
                return
            
            file_path, _ = QFileDialog.getSaveFileName(
                self, 
                "Save CSV File", 
                f"dayz_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
                "CSV Files (*.csv);;All Files (*)"
            )
            
            if file_path:
                with open(file_path, 'w', newline='', encoding='utf-8') as file:
                    fieldnames = ['Account', 'Email', 'Location', 'Value', 'Status', 'Station', 'Gear', 'Holding']
                    writer = csv.DictWriter(file, fieldnames=fieldnames)
                    
                    writer.writeheader()
                    for account in self.accounts:
                        writer.writerow({
                            'Account': account.get('account', ''),
                            'Email': account.get('email', ''),
                            'Location': account.get('location', ''),
                            'Value': account.get('value', ''),
                            'Status': account.get('status', ''),
                            'Station': account.get('station', ''),
                            'Gear': account.get('gear', ''),
                            'Holding': account.get('holding', '')
                        })
                
                self.status_label.setText(f"Exported {len(self.accounts)} accounts to CSV")
                QMessageBox.information(
                    self, 
                    "Export Complete", 
                    f"Successfully exported {len(self.accounts)} accounts to CSV file."
                )
                log_info(f"Exported {len(self.accounts)} accounts to CSV")
                
        except Exception as e:
            log_error(f"Failed to export CSV accounts: {e}")
            QMessageBox.critical(self, "Error", f"Failed to export CSV accounts: {e}")
    
    def show_bulk_operations(self):
        """Show bulk operations dialog"""
        try:
            if not self.accounts:
                QMessageBox.information(self, "No Accounts", "No accounts available for bulk operations.")
                return
            
            dialog = QDialog(self)
            dialog.setWindowTitle("Bulk Operations")
            dialog.setModal(True)
            dialog.setStyleSheet("""
                QWidget {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QLabel, QComboBox, QPushButton {
                    font-size: 11px;
                }
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    padding: 8px 12px;
                    border-radius: 4px;
                    font-weight: bold;
                    min-height: 25px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
            
            layout = QVBoxLayout()
            
            # Operation type selection
            operation_label = QLabel("Select Operation:")
            operation_combo = QComboBox()
            operation_combo.addItems([
                "Delete All Accounts",
                "Change Status for All Accounts",
                "Export Selected Accounts"
            ])
            
            layout.addWidget(operation_label)
            layout.addWidget(operation_combo)
            
            # Status change options (initially hidden)
            status_label = QLabel("New Status:")
            status_combo = QComboBox()
            status_combo.addItems(["Ready", "Blood Infection", "Storage", "Dead", "Offline"])
            status_label.hide()
            status_combo.hide()
            
            layout.addWidget(status_label)
            layout.addWidget(status_combo)
            
            # Show/hide status options based on operation
            def on_operation_changed():
                if operation_combo.currentText() == "Change Status for All Accounts":
                    status_label.show()
                    status_combo.show()
                else:
                    status_label.hide()
                    status_combo.hide()
            
            operation_combo.currentTextChanged.connect(on_operation_changed)
            
            # Buttons
            button_layout = QHBoxLayout()
            apply_btn = QPushButton("Apply Operation")
            cancel_btn = QPushButton("Cancel")
            
            apply_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            
            button_layout.addWidget(apply_btn)
            button_layout.addWidget(cancel_btn)
            layout.addLayout(button_layout)
            
            dialog.setLayout(layout)
            
            # Show dialog and handle result
            if dialog.exec() == QDialog.DialogCode.Accepted:
                operation = operation_combo.currentText()
                
                if operation == "Delete All Accounts":
                    self.clear_account_table()
                elif operation == "Change Status for All Accounts":
                    new_status = status_combo.currentText()
                    for account in self.accounts:
                        account['status'] = new_status
                        account['modified_date'] = datetime.now().isoformat()
                    
                    self.save_accounts()
                    self.refresh_account_table()
                    self.status_label.setText(f"Changed status to '{new_status}' for all accounts")
                    QMessageBox.information(
                        self, 
                        "Bulk Operation Complete", 
                        f"Changed status to '{new_status}' for all accounts."
                    )
                elif operation == "Export Selected Accounts":
                    self.export_csv_accounts()
                    
        except Exception as e:
            log_error(f"Failed to show bulk operations: {e}")
            QMessageBox.critical(self, "Error", f"Failed to show bulk operations: {e}") 