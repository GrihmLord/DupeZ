# app/gui/dayz_account_tracker.py — DayZ Account Tracker
"""DayZ multi-account tracker with CSV/XLSX import/export.

``DayZAccountTracker`` presents a searchable, sortable table of game
accounts with per-row status colouring, bulk operations, and full
CRUD via a modal dialog.  Persistence is delegated to
``app.core.data_persistence.account_manager``.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.data_persistence import account_manager
from app.logs.logger import log_error, log_info, log_warning

__all__ = ["DayZAccountTracker"]

# ── Shared constants ───────────────────────────────────────────────
ACCOUNT_FIELDS = ['account', 'email', 'location', 'value', 'status',
                  'station', 'gear', 'holding', 'loadout', 'needs']
TABLE_HEADERS = ['Account', 'Email', 'Location', 'Value', 'Status',
                 'Station', 'Gear', 'Holding', 'Loadout', 'Needs']
STATUS_COLORS = {
    'Ready':           QColor(76, 175, 80),
    'Blood Infection': QColor(244, 67, 54),
    'Storage':         QColor(255, 152, 0),
    'Dead':            QColor(158, 158, 158),
    'Offline':         QColor(96, 125, 139),
}
STATUS_LABEL_STYLES: Dict[str, str] = {
    k: f"color: #{c.red():02X}{c.green():02X}{c.blue():02X};"
    for k, c in STATUS_COLORS.items()
}

#: Known header synonyms for XLSX column auto-detection.
_XLSX_KNOWN_HEADERS: Dict[str, str] = {
    "account": "account", "name": "account", "player": "account",
    "email": "email", "e-mail": "email",
    "location": "location", "loc": "location",
    "status": "status",
    "station": "station", "kit": "station",
    "gear": "gear", "equipment": "gear",
    "holding": "holding", "inventory": "holding",
    "loadout": "loadout", "weapons": "loadout",
    "needs": "needs", "need": "needs",
    "value": "value",
}

#: Default column order when no header row is detected.
_XLSX_DEFAULT_FIELDS: List[str] = [
    "account", "email", "location", "status", "station",
    "gear", "holding", "loadout", "needs",
]

# ── QSS constants ──────────────────────────────────────────────────

_TRACKER_QSS: str = """
    QWidget { background-color: #0f1923; color: #e0e0e0; }
    QGroupBox {
        color: #00d9ff; font-weight: bold; font-size: 12px;
        border: 1px solid #1a2a3a; border-radius: 6px;
        margin-top: 10px; padding: 12px 8px 8px 8px;
        background: #0f1923;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
    QPushButton {
        background: #16213e; color: #e0e0e0; border: 1px solid #0f3460;
        padding: 6px 12px; border-radius: 4px; font-size: 11px;
    }
    QPushButton:hover { background: #0f3460; color: #00d9ff; }
    QPushButton:pressed { background: #00d9ff; color: #0a0a0a; }
    QLineEdit {
        background: #0a1628; color: #e0e0e0; border: 1px solid #1a2a3a;
        border-radius: 4px; padding: 6px 10px; font-size: 12px;
    }
    QLineEdit:focus { border: 1px solid #00d9ff; }
    QTableWidget {
        background-color: #0f1923; color: #e0e0e0;
        border: 1px solid #1a2a3a; gridline-color: #1a2a3a; font-size: 12px;
    }
    QTableWidget::item:selected { background-color: rgba(0, 217, 255, 0.2); color: #fff; }
    QTableWidget::item:alternate { background-color: #0a1628; }
    QHeaderView::section {
        background-color: #16213e; color: #00d9ff; padding: 6px;
        border: 1px solid #1a2a3a; font-weight: bold; font-size: 11px;
    }
    QLabel { color: #e0e0e0; }
    QComboBox {
        background: #0a1628; color: #e0e0e0; border: 1px solid #1a2a3a;
        border-radius: 4px; padding: 4px 10px;
    }
    QComboBox QAbstractItemView {
        background: #0f1923; color: #e0e0e0;
        selection-background-color: rgba(0, 217, 255, 0.3);
    }
"""

_HEADER_QSS: str = "color: #00d9ff; letter-spacing: 2px; padding: 4px;"

_STAT_QSS: str = "font-weight: bold; font-size: 12px; padding: 4px 8px;"


# ── DayZAccountTracker ─────────────────────────────────────────────

class DayZAccountTracker(QWidget):
    """Searchable, sortable account table with CRUD, CSV/XLSX I/O, and bulk ops.

    Falls back to a minimal error label when initialisation fails so the
    rest of the dashboard remains usable.
    """

    def __init__(self, controller: Any = None) -> None:
        super().__init__()
        self.controller: Any = controller
        self.accounts: List[Dict[str, Any]] = []
        self.current_account: Optional[Dict[str, Any]] = None
        self.selected_accounts: Set[str] = set()

        try:
            self._build_ui()
            self._load_accounts()
        except Exception as e:
            log_error(f"Failed to initialize DayZ Account Tracker: {e}")
            self._create_fallback_ui()

    def _create_fallback_ui(self) -> None:
        """Create a minimal fallback UI if initialisation fails."""
        try:
            layout = QVBoxLayout()

            # Error message
            error_label = QLabel("⚠️ Account Tracker Error\n\nFailed to initialize account tracker.\nPlease restart the application.")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(error_label)

            self.setLayout(layout)

        except Exception as e:
            log_error(f"Failed to create fallback UI: {e}")

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Assemble the tracker: header + management panel."""
        self.setStyleSheet(_TRACKER_QSS)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)
        self.setLayout(layout)

        header = QLabel("ACCOUNT TRACKER")
        header.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        header.setStyleSheet(_HEADER_QSS)
        layout.addWidget(header)

        layout.addWidget(self._create_account_panel())

    def _create_account_panel(self) -> QWidget:
        """Build the account management panel (controls + stats + table)."""
        panel = QWidget()
        layout = QVBoxLayout()

        # Account controls
        controls_group = QGroupBox("📋 Account Management")

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(5)  # Reduce spacing between buttons

        for attr, text, handler in [
            ("add_account_btn", "➕ Add", self._add_account),
            ("edit_account_btn", "✏️ Edit", self._edit_account),
            ("delete_account_btn", "🗑️ Delete", self._delete_account),
            ("bulk_ops_btn", "⚡ Bulk Ops", self._show_bulk_operations),
            ("upload_btn", "📁 Upload", self._upload_accounts),
            ("export_csv_btn", "💾 Export", self._export_csv_accounts),
            ("clear_table_btn", "🗑️ Clear All", self._clear_account_table),
            ("refresh_btn", "🔄 Refresh", self._refresh_account_table),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            setattr(self, attr, btn)
            controls_layout.addWidget(btn)

        # Search functionality
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search accounts...")
        self.search_input.textChanged.connect(self._filter_accounts)
        controls_layout.addWidget(self.search_input)

        controls_group.setLayout(controls_layout)
        layout.addWidget(controls_group)

        # Account statistics panel
        stats_group = QGroupBox("📊 Account Statistics")

        stats_layout = QHBoxLayout()
        stat_defs = [
            ("total_accounts_label", "Total: 0", "#00d9ff"),
            ("ready_accounts_label", "Ready: 0", "#4CAF50"),
            ("blood_infection_label", "Blood Infection: 0", "#F44336"),
            ("storage_label", "Storage: 0", "#FF9800"),
            ("dead_label", "Dead: 0", "#9E9E9E"),
            ("offline_label", "Offline: 0", "#607D8B"),
        ]
        for attr, text, color in stat_defs:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {color}; {_STAT_QSS}")
            setattr(self, attr, lbl)
            stats_layout.addWidget(lbl)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # Account table
        table_group = QGroupBox("📊 Account Details")

        table_layout = QVBoxLayout()

        self.account_table = QTableWidget()
        self._setup_account_table()
        table_layout.addWidget(self.account_table)

        table_group.setLayout(table_layout)
        layout.addWidget(table_group)

        # Status bar
        self.status_label = QLabel("Ready to manage DayZ accounts")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Account details panel removed to declutter redundancy.

        panel.setLayout(layout)
        return panel

    def _setup_account_table(self, accounts_to_show: Optional[List[Dict[str, Any]]] = None) -> None:
        """Populate the account table, optionally with a filtered subset."""
        try:
            accounts = accounts_to_show if accounts_to_show is not None else self.accounts

            self.account_table.setColumnCount(len(TABLE_HEADERS))
            self.account_table.setHorizontalHeaderLabels(TABLE_HEADERS)
            self.account_table.setRowCount(len(accounts))
            self.account_table.setAlternatingRowColors(True)
            self.account_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.account_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
            self.account_table.setSortingEnabled(True)
            self.account_table.setWordWrap(True)
            self.account_table.setShowGrid(True)
            self.account_table.setGridStyle(Qt.PenStyle.SolidLine)

            # Populate table
            for row, account in enumerate(accounts):
                for col, field in enumerate(ACCOUNT_FIELDS):
                    self.account_table.setItem(row, col, QTableWidgetItem(account.get(field, '')))
                # Color code status
                status_item = self.account_table.item(row, 4)
                if status_item and status_item.text() in STATUS_COLORS:
                    status_item.setBackground(STATUS_COLORS[status_item.text()])

            # Connect selection change
            self.account_table.itemSelectionChanged.connect(self._on_account_selected)

            # Auto-resize columns
            self.account_table.resizeColumnsToContents()

        except Exception as e:
            log_error(f"Failed to setup account table: {e}")

    # ── Account CRUD ─────────────────────────────────────────────────

    def _add_account(self) -> None:
        """Open the account dialog and persist a new record."""
        try:
            account_data = self._show_account_dialog()
            if account_data:
                # Add unique ID and use consistent field names
                account_data['id'] = len(account_manager.accounts) + 1
                account_data['created_at'] = datetime.now().isoformat()
                account_data['updated_at'] = datetime.now().isoformat()

                account_manager.add_account(account_data)

                # Refresh local accounts list and UI
                self.accounts = account_manager.accounts
                self._refresh_account_table()

                self.status_label.setText(f"Added account: {account_data.get('account', '')}")
                log_info(f"Added new account: {account_data.get('account', '')}")

        except Exception as e:
            log_error(f"Failed to add account: {e}")
            QMessageBox.critical(self, "Error", f"Failed to add account: {e}")

    def _edit_account(self) -> None:
        """Edit the currently selected account via dialog."""
        try:
            if not self.current_account:
                QMessageBox.information(self, "No Selection", "Please select an account to edit.")
                return

            account_data = self._show_account_dialog(self.current_account)
            if account_data:
                # Update the account with consistent field names
                self.current_account.update(account_data)
                self.current_account['updated_at'] = datetime.now().isoformat()

                account_name = self.current_account.get('account', '')
                account_manager.update_account(account_name, self.current_account)

                # Refresh local accounts list and UI
                self.accounts = account_manager.accounts
                self._refresh_account_table()

                self.status_label.setText(f"Updated account: {self.current_account.get('account', '')}")
                log_info(f"Updated account: {self.current_account.get('account', '')}")

        except Exception as e:
            log_error(f"Failed to edit account: {e}")
            QMessageBox.critical(self, "Error", f"Failed to edit account: {e}")

    def _delete_account(self) -> None:
        """Delete the currently selected account after confirmation."""
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

                account_manager.remove_account(account_name)

                # Refresh local accounts list and UI
                self.accounts = account_manager.accounts
                self._refresh_account_table()
                self._clear_account_details()

                self.status_label.setText(f"Deleted account: {account_name}")
                log_info(f"Deleted account: {account_name}")

        except Exception as e:
            log_error(f"Failed to delete account: {e}")
            QMessageBox.critical(self, "Error", f"Failed to delete account: {e}")

    def _show_account_dialog(self, account_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, str]]:
        """Present a modal form for creating or editing an account."""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Account Details")
            dialog.setModal(True)

            layout = QFormLayout()

            # Text input fields
            _text_fields = [
                ("account_input", "Account:", "Account Name", "account"),
                ("email_input", "Email:", "user@domain.com", "email"),
                ("location_input", "Location:", "Location or Coordinates", "location"),
                ("value_input", "Value:", "Value or Worth", "value"),
            ]
            inputs = {}
            for var, label, placeholder, key in _text_fields:
                inp = QLineEdit()
                inp.setPlaceholderText(placeholder)
                if account_data:
                    inp.setText(account_data.get(key, ''))
                layout.addRow(label, inp)
                inputs[var] = inp

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

            for var, label, placeholder, key in [
                ("gear_input", "Gear:", "Equipment Description", "gear"),
                ("loadout_input", "Loadout:", "Weapon loadout (e.g. DMR + VSD)", "loadout"),
                ("needs_input", "Needs:", "Items needed (or -)", "needs"),
            ]:
                inp = QLineEdit()
                inp.setPlaceholderText(placeholder)
                if account_data:
                    inp.setText(account_data.get(key, ''))
                layout.addRow(label, inp)
                inputs[var] = inp

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
                result = {k.replace('_input', ''): v.text() for k, v in inputs.items()}
                result['status'] = status_combo.currentText()
                result['station'] = station_combo.currentText()
                result['holding'] = holding_input.toPlainText()
                return result

            return None

        except Exception as e:
            log_error(f"Account dialog error: {e}")
            return None

    # ── Selection and state ──────────────────────────────────────────

    def _on_account_selected(self) -> None:
        """Handle account selection change in the table."""
        try:
            current_row = self.account_table.currentRow()
            if current_row >= 0:
                account_name = self.account_table.item(current_row, 0).text()
                for account in self.accounts:
                    if account.get('account') == account_name:
                        self.current_account = account
                        self.status_label.setText(f"Selected: {account_name}")
                        return
                log_warning(f"Account {account_name} not found in accounts data")
            else:
                self.current_account = None
                self.status_label.setText("Ready to manage DayZ accounts")
        except Exception as e:
            log_error(f"Failed to handle account selection: {e}")

    def _clear_account_details(self) -> None:
        """Reset the current selection state."""
        self.current_account = None
        self.status_label.setText("Ready to manage DayZ accounts")

    # ── Persistence ─────────────────────────────────────────────────

    def _load_accounts(self) -> None:
        """Load accounts from the persistence layer."""
        try:
            self.accounts = account_manager.accounts.copy()
            self._refresh_account_table()
            self._update_statistics()
            log_info(f"Loaded {len(self.accounts)} accounts")
        except Exception as e:
            log_error(f"Failed to load accounts: {e}")
            self.accounts = []

    def _save_accounts(self) -> None:
        """Flush the local account list back to the persistence layer."""
        try:
            account_manager.accounts = self.accounts.copy()
            account_manager.save_changes(account_manager.accounts)
        except Exception as e:
            log_error(f"Failed to save accounts: {e}")

    def _refresh_after_import(self) -> None:
        """Common post-import refresh: save, rebuild table, update stats."""
        try:
            account_manager.save_changes(account_manager.accounts)
        except Exception as e:
            log_error(f"Failed to save imports: {e}")
        self.account_table.clearContents()
        self.account_table.setRowCount(0)
        self.accounts = account_manager.accounts.copy()
        self._setup_account_table(self.accounts)
        self._update_statistics()
        self.account_table.resizeColumnsToContents()

    # ── Table refresh / filter ────────────────────────────────────────

    def _refresh_account_table(self) -> None:
        """Rebuild the table from the current account list."""
        try:
            self._setup_account_table()
            self._update_statistics()
        except Exception as e:
            log_error(f"Failed to refresh account table: {e}")

    def _clear_account_table(self) -> None:
        """Clear all accounts after user confirmation."""
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
                self._refresh_account_table()
                self.status_label.setText("All accounts cleared")
                log_info("All accounts cleared")
        except Exception as e:
            log_error(f"Failed to clear accounts: {e}")
            QMessageBox.critical(self, "Error", f"Failed to clear accounts: {e}")

    def _filter_accounts(self, search_text: str) -> None:
        """Filter the table rows by a case-insensitive search term."""
        try:
            if not search_text:
                self._refresh_account_table()
                return
            search_lower = search_text.lower()
            filtered = [a for a in self.accounts
                        if any(search_lower in a.get(f, '').lower()
                               for f in ACCOUNT_FIELDS)]
            self._setup_account_table(filtered)
        except Exception as e:
            log_error(f"Failed to filter accounts: {e}")

    # ── Statistics ──────────────────────────────────────────────────

    def _update_statistics(self) -> None:
        """Recompute and display account status counts."""
        try:
            from collections import Counter
            counts = Counter(a.get('status', '') for a in self.accounts)
            self.total_accounts_label.setText(f"Total: {len(self.accounts)}")
            for attr, status in [("ready_accounts_label", "Ready"),
                                 ("blood_infection_label", "Blood Infection"),
                                 ("storage_label", "Storage"), ("dead_label", "Dead"),
                                 ("offline_label", "Offline")]:
                getattr(self, attr).setText(f"{status}: {counts.get(status, 0)}")
        except Exception as e:
            log_error(f"Failed to update statistics: {e}")

    # ── Import / Export ─────────────────────────────────────────────

    def _upload_accounts(self) -> None:
        """Prompt for a CSV or XLSX file and import its rows."""
        try:
            from PyQt6.QtWidgets import QFileDialog

            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Account File",
                "",
                "All Supported (*.xlsx *.xls *.csv);;Excel Files (*.xlsx *.xls);;CSV Files (*.csv);;All Files (*)"
            )

            if file_path:
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ('.xlsx', '.xls'):
                    self._process_xlsx_file(file_path)
                elif ext == '.csv':
                    self._process_csv_file(file_path)
                else:
                    QMessageBox.warning(self, "Unsupported File", f"File type '{ext}' is not supported. Use .xlsx or .csv files.")

        except Exception as e:
            log_error(f"Failed to upload accounts: {e}")
            QMessageBox.critical(self, "Error", f"Failed to upload accounts: {e}")

    def _process_xlsx_file(self, file_path: str) -> None:
        """Import accounts from an XLSX workbook with auto-detected headers."""
        try:
            import openpyxl

            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet = wb.active

            # --- Detect header row and column mapping ---
            # Scan first 5 rows to find a row with recognizable header keywords
            header_row_idx: Optional[int] = None
            header_map: Dict[int, str] = {}  # col_index -> normalised field name

            for row_idx in range(1, min(6, sheet.max_row + 1)):
                row_vals = []
                for col_idx in range(1, sheet.max_column + 1):
                    cell_val = sheet.cell(row=row_idx, column=col_idx).value
                    if cell_val is not None:
                        row_vals.append((col_idx, str(cell_val).strip().lower()))

                # Check if this row looks like a header (2+ recognized keywords)
                matches = {}
                for col_idx, val in row_vals:
                    if val in _XLSX_KNOWN_HEADERS:
                        matches[col_idx] = _XLSX_KNOWN_HEADERS[val]

                if len(matches) >= 2:
                    header_row_idx = row_idx
                    header_map = matches
                    break

            if header_row_idx is None:
                # Fallback: assume row 1 is header with positional mapping
                header_row_idx = 1
                for col_idx in range(1, min(len(_XLSX_DEFAULT_FIELDS) + 1, sheet.max_column + 1)):
                    header_map[col_idx] = _XLSX_DEFAULT_FIELDS[col_idx - 1]

            log_info(f"XLSX header detected at row {header_row_idx}: {header_map}")

            # --- Parse account rows ---
            accounts_imported = 0
            accounts_skipped = 0
            bases_data = []  # Store base info separately

            # Detect where "Bases" section starts (look for a cell containing "base" in col A)
            bases_start_row = None
            for row_idx in range(header_row_idx + 1, sheet.max_row + 1):
                cell_a = sheet.cell(row=row_idx, column=1).value
                if cell_a and 'base' in str(cell_a).strip().lower():
                    # Check if this looks like a section header (not an account name with "base" in it)
                    cell_b = sheet.cell(row=row_idx, column=2).value
                    # If column B is empty or also contains a header-like word, it's a section break
                    if cell_b is None or str(cell_b).strip().lower() in _XLSX_KNOWN_HEADERS:
                        bases_start_row = row_idx
                        log_info(f"XLSX bases section detected at row {bases_start_row}")
                        break

            account_end_row = bases_start_row if bases_start_row else sheet.max_row + 1

            for row_idx in range(header_row_idx + 1, account_end_row):
                try:
                    # Read row data using header map
                    row_data = {}
                    is_empty = True
                    for col_idx, field in header_map.items():
                        cell_val = sheet.cell(row=row_idx, column=col_idx).value
                        if cell_val is not None:
                            val = str(cell_val).strip()
                            if val:
                                is_empty = False
                            row_data[field] = val
                        else:
                            row_data[field] = ''

                    # Skip empty/spacer rows
                    if is_empty:
                        continue

                    # Skip rows where account field is empty or just whitespace
                    account_name = row_data.get('account', '').strip()
                    if not account_name or len(account_name) < 2:
                        accounts_skipped += 1
                        continue

                    now = datetime.now().isoformat()
                    account_data = {f: row_data.get(f, 'Ready' if f == 'status' else '')
                                    for f in ACCOUNT_FIELDS}
                    account_data.update(last_seen=now, created_date=now,
                                        id=f"xlsx_{accounts_imported + 1}_{datetime.now().timestamp()}")

                    if self._try_import_account(account_data):
                        accounts_imported += 1
                    else:
                        accounts_skipped += 1

                except Exception as e:
                    accounts_skipped += 1
                    log_error(f"XLSX error at row {row_idx}: {e}")
                    continue

            # --- Parse bases section if present ---
            bases_imported = 0
            if bases_start_row:
                # Re-detect header for bases section
                bases_header_map = {}
                bases_header_row = bases_start_row
                row_vals = []
                for col_idx in range(1, sheet.max_column + 1):
                    cell_val = sheet.cell(row=bases_start_row, column=col_idx).value
                    if cell_val is not None:
                        row_vals.append((col_idx, str(cell_val).strip().lower()))

                base_headers = {
                    'base': 'base_name', 'bases': 'base_name', 'name': 'base_name', 'code': 'base_code',
                    'location': 'base_location', 'loc': 'base_location',
                    'status': 'base_status', 'notes': 'base_notes',
                }
                for col_idx, val in row_vals:
                    if val in base_headers:
                        bases_header_map[col_idx] = base_headers[val]

                for row_idx in range(bases_start_row + 1, sheet.max_row + 1):
                    base_row = {}
                    is_empty = True
                    for col_idx in range(1, sheet.max_column + 1):
                        cell_val = sheet.cell(row=row_idx, column=col_idx).value
                        if cell_val is not None and str(cell_val).strip():
                            is_empty = False
                            field = bases_header_map.get(col_idx, f'col_{col_idx}')
                            base_row[field] = str(cell_val).strip()
                    if not is_empty:
                        bases_data.append(base_row)
                        bases_imported += 1

                log_info(f"XLSX bases imported: {bases_imported}")

            # Refresh UI
            self._refresh_after_import()

            # Build result message
            msg = f"Import completed!\n\nAccounts imported: {accounts_imported}\nAccounts skipped: {accounts_skipped}\nTotal accounts: {len(self.accounts)}"
            if bases_imported > 0:
                msg += f"\n\nBases found: {bases_imported}"
            QMessageBox.information(self, "XLSX Import Complete", msg)
            log_info(f"XLSX import done: {accounts_imported} imported, {accounts_skipped} skipped, {bases_imported} bases")

        except ImportError:
            log_error("openpyxl not installed")
            QMessageBox.critical(self, "Missing Library",
                "openpyxl is required for XLSX import.\n\nInstall it with:\npip install openpyxl")
        except Exception as e:
            log_error(f"Failed to process XLSX file: {e}")
            QMessageBox.critical(self, "Error", f"Failed to process XLSX file:\n{e}")

    def _process_csv_file(self, file_path: str) -> None:
        """Import accounts from a CSV file with header-based column mapping."""
        try:
            accounts_imported = 0
            accounts_skipped = 0

            with open(file_path, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)

                for row_num, row in enumerate(reader, start=2):  # Start at 2 since row 1 is header
                    try:
                        # Debug: Log the raw row data
                        log_info(f"Processing CSV row {row_num}: {dict(row)}")

                        # Map CSV columns to account fields
                        _defaults = {'status': 'Ready'}
                        account_data = {f: row.get(h, _defaults.get(f, '')).strip()
                                        for f, h in zip(ACCOUNT_FIELDS, TABLE_HEADERS)}
                        now = datetime.now().isoformat()
                        account_data.update(last_seen=now, created_date=now,
                                            id=f"imported_{accounts_imported + 1}_{datetime.now().timestamp()}")

                        if self._try_import_account(account_data):
                            accounts_imported += 1
                        else:
                            accounts_skipped += 1

                    except Exception as e:
                        accounts_skipped += 1
                        log_error(f"Error processing row {row_num}: {e}")
                        continue

            # Refresh UI
            self._refresh_after_import()
            log_info(f"CSV import: table rebuilt with {len(self.accounts)} accounts")

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

    def _try_import_account(self, account_data: dict) -> bool:
        """Validate, dedup, and add a single account. Returns True if imported."""
        if not self._validate_account_data(account_data):
            return False
        if self._is_duplicate_account(account_data):
            log_warning(f"Skipped duplicate: {account_data.get('account', '')}")
            return False
        self.accounts.append(account_data)
        try:
            account_manager.add_account(account_data)
        except Exception as e:
            log_warning(f"Failed to add account to manager: {e}")
            account_manager.accounts.append(account_data)
        log_info(f"Imported account: {account_data['account']}")
        return True

    # ── Validation helpers ──────────────────────────────────────────

    def _validate_account_data(self, data: Dict[str, str]) -> bool:
        """Return *True* if *data* contains a valid account name and email."""
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

            log_info(f"Account validation passed for: {account}")
            return True

        except Exception as e:
            log_error(f"Error in account validation: {e}")
            return False

    def _is_duplicate_account(self, account_data: Dict[str, Any]) -> bool:
        """Return *True* if an account with the same name+email already exists."""
        try:
            for account in account_manager.accounts:
                if (account.get('account') == account_data.get('account') and
                    account.get('email') == account_data.get('email')):
                    return True
            return False
        except Exception as e:
            log_error(f"Failed to check for duplicate account: {e}")
            return False

    def _export_csv_accounts(self) -> None:
        """Export accounts to a CSV or XLSX file chosen via a save dialog."""
        try:
            from PyQt6.QtWidgets import QFileDialog
            import csv

            if not self.accounts:
                QMessageBox.information(self, "No Accounts", "No accounts to export.")
                return

            file_path, selected_filter = QFileDialog.getSaveFileName(
                self,
                "Export Accounts",
                f"dayz_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                "Excel Files (*.xlsx);;CSV Files (*.csv);;All Files (*)"
            )

            if file_path:
                ext = os.path.splitext(file_path)[1].lower()

                if ext == '.xlsx':
                    self._export_xlsx(file_path)
                else:
                    with open(file_path, 'w', newline='', encoding='utf-8') as file:
                        writer = csv.DictWriter(file, fieldnames=TABLE_HEADERS)
                        writer.writeheader()
                        for account in self.accounts:
                            writer.writerow({h: account.get(f, '')
                                             for h, f in zip(TABLE_HEADERS, ACCOUNT_FIELDS)})

                fmt = "XLSX" if ext == '.xlsx' else "CSV"
                self.status_label.setText(f"Exported {len(self.accounts)} accounts to {fmt}")
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Successfully exported {len(self.accounts)} accounts."
                )
                log_info(f"Exported {len(self.accounts)} accounts to {fmt}")

        except Exception as e:
            log_error(f"Failed to export CSV accounts: {e}")
            QMessageBox.critical(self, "Error", f"Failed to export CSV accounts: {e}")

    def _export_xlsx(self, file_path: str) -> None:
        """Write accounts to a styled XLSX workbook with frozen header row."""
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Accounts"

            # XLSX export uses all fields except 'value' column for compact layout
            headers = [h for h in TABLE_HEADERS if h != 'Value']
            fields = [f for f in ACCOUNT_FIELDS if f != 'value']

            # Header styling
            header_font = Font(bold=True, color="FFFFFF", size=11)
            header_fill = PatternFill('solid', fgColor="16213E")
            header_align = Alignment(horizontal='center', vertical='center')
            thin_border = Border(
                left=Side(style='thin', color='1A2A3A'),
                right=Side(style='thin', color='1A2A3A'),
                top=Side(style='thin', color='1A2A3A'),
                bottom=Side(style='thin', color='1A2A3A'),
            )

            # Write headers
            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align
                cell.border = thin_border

            # Status color map (derived from shared STATUS_COLORS)
            status_fills = {k: PatternFill('solid', fgColor=f'{c.red():02X}{c.green():02X}{c.blue():02X}')
                           for k, c in STATUS_COLORS.items()}

            # Write account rows
            for row_idx, account in enumerate(self.accounts, 2):
                for col_idx, field in enumerate(fields, 1):
                    cell = ws.cell(row=row_idx, column=col_idx, value=account.get(field, ''))
                    cell.border = thin_border
                    cell.alignment = Alignment(vertical='center')

                # Color-code status cell
                status_val = account.get('status', '')
                status_cell = ws.cell(row=row_idx, column=4)
                if status_val in status_fills:
                    status_cell.fill = status_fills[status_val]
                    status_cell.font = Font(bold=True, color="FFFFFF")

            # Auto-width columns
            for col_idx in range(1, len(headers) + 1):
                max_len = len(headers[col_idx - 1])
                for row_idx in range(2, len(self.accounts) + 2):
                    val = ws.cell(row=row_idx, column=col_idx).value
                    if val:
                        max_len = max(max_len, len(str(val)))
                ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = min(max_len + 4, 50)

            # Freeze header row
            ws.freeze_panes = 'A2'

            wb.save(file_path)
            log_info(f"XLSX export saved to {file_path}")

        except ImportError:
            QMessageBox.critical(self, "Missing Library",
                "openpyxl is required for XLSX export.\n\nInstall it with:\npip install openpyxl")
        except Exception as e:
            log_error(f"XLSX export failed: {e}")
            raise

    # ── Bulk operations ─────────────────────────────────────────────

    def _show_bulk_operations(self) -> None:
        """Present a dialog for batch status changes or deletion."""
        try:
            if not self.accounts:
                QMessageBox.information(self, "No Accounts", "No accounts available for bulk operations.")
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("Bulk Operations")
            dialog.setModal(True)

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
                    self._clear_account_table()
                elif operation == "Change Status for All Accounts":
                    new_status = status_combo.currentText()
                    for account in self.accounts:
                        account['status'] = new_status
                        account['modified_date'] = datetime.now().isoformat()

                    self._save_accounts()
                    self._refresh_account_table()
                    self.status_label.setText(f"Changed status to '{new_status}' for all accounts")
                    QMessageBox.information(
                        self,
                        "Bulk Operation Complete",
                        f"Changed status to '{new_status}' for all accounts."
                    )
                elif operation == "Export Selected Accounts":
                    self._export_csv_accounts()

        except Exception as e:
            log_error(f"Failed to show bulk operations: {e}")
            QMessageBox.critical(self, "Error", f"Failed to show bulk operations: {e}")

