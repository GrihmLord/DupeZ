# app/gui/clumsy_control.py — Main View: Device List + Full Clumsy Disruption Controls

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QSlider, QComboBox, QGroupBox, QGridLayout, QMessageBox,
    QProgressBar, QSplitter, QCheckBox, QSpinBox, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QCursor
from typing import List, Dict, Optional
import time

from app.logs.logger import log_info, log_error, log_warning
from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor


# ======================================================================
# Disruption Presets — full clumsy feature coverage
# ======================================================================
PRESETS = {
    "Red Disconnect": {
        "description": "Hard disconnect — 95% drop + 2000ms lag + 1KB/s cap + full throttle",
        "methods": ["lag", "drop", "bandwidth", "throttle", "disconnect"],
        "params": {
            "lag_delay": 2000, "drop_chance": 95,
            "bandwidth_limit": 1, "bandwidth_queue": 0,
            "throttle_chance": 100, "throttle_frame": 500,
            "throttle_drop": True,
            "direction": "both",
        }
    },
    "DupeZ Default": {
        "description": "Sustained disruption — disconnect + drop + lag + bandwidth cap + throttle",
        "methods": ["disconnect", "drop", "lag", "bandwidth", "throttle"],
        "params": {
            "lag_delay": 1500, "drop_chance": 95,
            "bandwidth_limit": 1, "bandwidth_queue": 0,
            "throttle_chance": 100, "throttle_frame": 400,
            "throttle_drop": True,
            "direction": "both",
        }
    },
    "Heavy Lag": {
        "description": "Brutal lag — 3000ms delay + 95% drop + 1KB/s cap",
        "methods": ["lag", "drop", "bandwidth"],
        "params": {
            "lag_delay": 3000, "drop_chance": 95,
            "bandwidth_limit": 1, "bandwidth_queue": 0,
            "direction": "both",
        }
    },
    "Light Lag": {
        "description": "Moderate lag — 800ms delay, 60% drop",
        "methods": ["lag", "drop"],
        "params": {"lag_delay": 800, "drop_chance": 60, "direction": "both"}
    },
    "Desync": {
        "description": "Duplicate flood + lag — causes massive server desync",
        "methods": ["lag", "duplicate", "ood"],
        "params": {
            "lag_delay": 800, "duplicate_chance": 90, "duplicate_count": 15,
            "ood_chance": 80, "direction": "both",
        }
    },
    "Bandwidth Cap": {
        "description": "Throttle to 1KB/s — near-zero bandwidth",
        "methods": ["bandwidth", "throttle"],
        "params": {
            "bandwidth_limit": 1, "bandwidth_queue": 0,
            "throttle_chance": 80, "throttle_frame": 300,
            "throttle_drop": True, "direction": "both",
        }
    },
    "Total Chaos": {
        "description": "All modules maxed — complete network destruction",
        "methods": ["lag", "drop", "duplicate", "corrupt", "rst", "ood", "disconnect"],
        "params": {
            "lag_delay": 1500, "drop_chance": 95, "duplicate_chance": 80,
            "duplicate_count": 10, "tamper_chance": 60, "rst_chance": 90,
            "ood_chance": 80, "direction": "both",
        }
    },
    "Custom": {
        "description": "Set your own parameters below",
        "methods": [],
        "params": {}
    }
}


# ======================================================================
# Module definitions for the full controls UI
# ======================================================================
MODULE_DEFS = [
    {
        "key": "lag",
        "label": "LAG",
        "desc": "Add delay to packets",
        "params": [
            ("Delay (ms)", "lag_delay", 0, 2000, 500),
        ]
    },
    {
        "key": "drop",
        "label": "DROP",
        "desc": "Drop packets randomly",
        "params": [
            ("Chance %", "drop_chance", 0, 100, 100),
        ]
    },
    {
        "key": "throttle",
        "label": "THROTTLE",
        "desc": "Throttle packet flow",
        "params": [
            ("Chance %", "throttle_chance", 0, 100, 80),
            ("Frame (ms)", "throttle_frame", 0, 1000, 100),
        ]
    },
    {
        "key": "duplicate",
        "label": "DUPLICATE",
        "desc": "Clone packets",
        "params": [
            ("Chance %", "duplicate_chance", 0, 100, 50),
            ("Count", "duplicate_count", 1, 50, 5),
        ]
    },
    {
        "key": "ood",
        "label": "OUT OF ORDER",
        "desc": "Reorder packets",
        "params": [
            ("Chance %", "ood_chance", 0, 100, 50),
        ]
    },
    {
        "key": "corrupt",
        "label": "TAMPER",
        "desc": "Corrupt packet data",
        "params": [
            ("Chance %", "tamper_chance", 0, 100, 30),
        ]
    },
    {
        "key": "rst",
        "label": "TCP RST",
        "desc": "Inject RST flags",
        "params": [
            ("Chance %", "rst_chance", 0, 100, 100),
        ]
    },
    {
        "key": "disconnect",
        "label": "DISCONNECT",
        "desc": "Break connection",
        "params": []
    },
    {
        "key": "bandwidth",
        "label": "BANDWIDTH",
        "desc": "Limit bandwidth",
        "params": [
            ("Limit (KB/s)", "bandwidth_limit", 0, 1000, 5),
            ("Queue Size", "bandwidth_queue", 0, 1000, 0),
        ]
    },
]


class ClumsyControlView(QWidget):
    """Main view: Device scanner + per-device Clumsy disruption with full controls."""

    scan_started = pyqtSignal()
    scan_finished = pyqtSignal(list)
    _scan_results_ready = pyqtSignal(list)   # internal: thread-safe scan delivery

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.devices = []
        self.selected_ip = None
        self._disruption_timers = {}  # ip -> start_time
        self._ip_hidden = False       # IP masking state
        self._row_checkboxes = []     # list of (QCheckBox, real_ip) per row

        self.setup_ui()
        self.connect_signals()

        # Auto-refresh disruption status
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._refresh_disruption_status)
        self.status_timer.start(2000)

        # Session timer display
        self.session_timer = QTimer()
        self.session_timer.timeout.connect(self._update_session_timers)
        self.session_timer.start(1000)

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------
    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setLayout(main_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- LEFT: Device List ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 6, 12)
        left_layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("NETWORK DEVICES")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #00d9ff; letter-spacing: 1px;")
        header.addWidget(title)
        header.addStretch()

        self.hide_ip_btn = QPushButton("HIDE IPs")
        self.hide_ip_btn.setCheckable(True)
        self.hide_ip_btn.setStyleSheet("""
            QPushButton {
                background: #0a1628; color: #94a3b8; border: 1px solid #1a2a3a;
                border-radius: 4px; font-size: 10px; font-weight: bold;
                padding: 4px 10px; letter-spacing: 1px;
            }
            QPushButton:checked {
                background: rgba(255,68,68,0.15); color: #ff4444; border: 1px solid #ff4444;
            }
            QPushButton:hover { color: #e0e0e0; border-color: #3a4a5a; }
        """)
        self.hide_ip_btn.setFixedHeight(30)
        self.hide_ip_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hide_ip_btn.clicked.connect(self._toggle_ip_visibility)
        header.addWidget(self.hide_ip_btn)

        self.scan_btn = QPushButton("SCAN")
        self.scan_btn.setStyleSheet(self._btn_style("#00d9ff", "#0a1628"))
        self.scan_btn.setFixedSize(80, 30)
        self.scan_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        header.addWidget(self.scan_btn)
        left_layout.addLayout(header)

        # Network filter dropdown
        net_filter_row = QHBoxLayout()
        net_label = QLabel("NETWORK:")
        net_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
        net_filter_row.addWidget(net_label)

        self.network_combo = QComboBox()
        self.network_combo.addItem("All Networks")
        self.network_combo.setStyleSheet("""
            QComboBox {
                background-color: #16213e; color: #00d9ff; border: 1px solid #1a2a3a;
                padding: 4px 8px; font-size: 11px; border-radius: 4px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #16213e; color: #e0e0e0; selection-background-color: rgba(0,217,255,0.3);
            }
        """)
        self.network_combo.currentTextChanged.connect(self._on_network_filter_changed)
        net_filter_row.addWidget(self.network_combo, 1)
        left_layout.addLayout(net_filter_row)

        # Device table — col 0 = select checkbox, 1 = IP, 2 = Hostname, 3 = Vendor, 4 = Status, 5 = Session
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels(["", "IP", "Hostname", "Vendor", "Status", "Session"])
        hdr = self.device_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.device_table.setColumnWidth(0, 32)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.device_table.setAlternatingRowColors(True)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setStyleSheet("""
            QTableWidget {
                background-color: #0f1923; color: #e0e0e0;
                border: 1px solid #1a2a3a; gridline-color: #1a2a3a; font-size: 12px;
            }
            QTableWidget::item:selected {
                background-color: rgba(0, 217, 255, 0.2); color: #ffffff;
            }
            QTableWidget::item:alternate { background-color: #0a1628; }
            QHeaderView::section {
                background-color: #16213e; color: #00d9ff; padding: 6px;
                border: 1px solid #1a2a3a; font-weight: bold; font-size: 11px;
            }
        """)
        left_layout.addWidget(self.device_table)

        # Device count
        self.device_count_label = QLabel("0 devices found")
        self.device_count_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        left_layout.addWidget(self.device_count_label)

        # ---- RIGHT: Disruption Controls (scrollable) ----
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 12, 12, 12)
        right_layout.setSpacing(8)

        # Target display
        self.target_label = QLabel("NO TARGET SELECTED")
        self.target_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #ff4444; letter-spacing: 1px; padding: 8px;"
        )
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.target_label)

        # Preset selector
        preset_group = self._card("PRESET")
        preset_layout = QVBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS.keys())
        self.preset_combo.setStyleSheet(self._combo_style())
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        self.preset_desc = QLabel(PRESETS["Red Disconnect"]["description"])
        self.preset_desc.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        self.preset_desc.setWordWrap(True)
        preset_layout.addWidget(self.preset_desc)
        preset_group.setLayout(preset_layout)
        right_layout.addWidget(preset_group)

        # Global direction toggle
        dir_group = self._card("DIRECTION")
        dir_layout = QHBoxLayout()
        self.dir_inbound = QCheckBox("INBOUND")
        self.dir_outbound = QCheckBox("OUTBOUND")
        self.dir_outbound.setChecked(True)  # default outbound
        self.dir_inbound.setStyleSheet("color: #e0e0e0; font-size: 11px; font-weight: bold;")
        self.dir_outbound.setStyleSheet("color: #e0e0e0; font-size: 11px; font-weight: bold;")
        dir_layout.addWidget(self.dir_inbound)
        dir_layout.addWidget(self.dir_outbound)
        dir_layout.addStretch()
        dir_group.setLayout(dir_layout)
        right_layout.addWidget(dir_group)

        # ---- MODULE CONTROLS ----
        # Each module: [enable checkbox] NAME  [param sliders]
        modules_group = self._card("MODULES")
        modules_layout = QVBoxLayout()
        modules_layout.setSpacing(6)

        self.module_checks = {}   # key -> QCheckBox
        self.sliders = {}         # param_key -> QSlider
        self.slider_labels = {}   # param_key -> QLabel (value display)
        self.extra_checks = {}    # key -> QCheckBox (tamper_checksum, throttle_drop)

        for mdef in MODULE_DEFS:
            key = mdef["key"]
            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(2)

            # Module header: [checkbox] LABEL — desc
            header_row = QHBoxLayout()
            header_row.setSpacing(6)

            cb = QCheckBox(mdef["label"])
            cb.setStyleSheet("""
                QCheckBox { color: #00d9ff; font-size: 11px; font-weight: bold; }
                QCheckBox::indicator { width: 14px; height: 14px; }
                QCheckBox::indicator:unchecked {
                    border: 1px solid #3a4a5a; background: #0a1628; border-radius: 2px;
                }
                QCheckBox::indicator:checked {
                    border: 1px solid #00d9ff; background: #00d9ff; border-radius: 2px;
                }
            """)
            header_row.addWidget(cb)
            self.module_checks[key] = cb

            desc = QLabel(mdef["desc"])
            desc.setStyleSheet("color: #4a5a6a; font-size: 10px;")
            header_row.addWidget(desc)
            header_row.addStretch()

            row_layout.addLayout(header_row)

            # Parameter sliders
            for plabel, pkey, pmin, pmax, pdefault in mdef["params"]:
                param_row = QHBoxLayout()
                param_row.setContentsMargins(20, 0, 0, 0)  # indent under module

                plbl = QLabel(plabel)
                plbl.setFixedWidth(75)
                plbl.setStyleSheet("color: #94a3b8; font-size: 10px;")
                param_row.addWidget(plbl)

                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(pmin, pmax)
                slider.setValue(pdefault)
                slider.setMinimumWidth(60)
                slider.setStyleSheet(self._slider_style())
                param_row.addWidget(slider, 1)

                val_lbl = QLabel(str(pdefault))
                val_lbl.setFixedWidth(45)
                val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                val_lbl.setStyleSheet("color: #00d9ff; font-weight: bold; font-size: 10px;")
                param_row.addWidget(val_lbl)

                slider.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
                self.sliders[pkey] = slider
                self.slider_labels[pkey] = val_lbl

                row_layout.addLayout(param_row)

            # Extra checkboxes for tamper (redo checksum) and throttle (drop throttled)
            if key == "corrupt":
                extra_row = QHBoxLayout()
                extra_row.setContentsMargins(20, 0, 0, 0)
                redo_cb = QCheckBox("Redo Checksum")
                redo_cb.setChecked(True)  # Match clumsy C default: doChecksum=1
                redo_cb.setStyleSheet("color: #94a3b8; font-size: 10px;")
                extra_row.addWidget(redo_cb)
                extra_row.addStretch()
                self.extra_checks["tamper_checksum"] = redo_cb
                row_layout.addLayout(extra_row)

            if key == "throttle":
                extra_row = QHBoxLayout()
                extra_row.setContentsMargins(20, 0, 0, 0)
                drop_cb = QCheckBox("Drop Throttled")
                drop_cb.setStyleSheet("color: #94a3b8; font-size: 10px;")
                extra_row.addWidget(drop_cb)
                extra_row.addStretch()
                self.extra_checks["throttle_drop"] = drop_cb
                row_layout.addLayout(extra_row)

            # Separator line
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("color: #1a2a3a;")
            row_layout.addWidget(sep)

            modules_layout.addWidget(row_widget)

        modules_group.setLayout(modules_layout)
        right_layout.addWidget(modules_group)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_disrupt = QPushButton("DISRUPT")
        self.btn_disrupt.setStyleSheet(self._btn_style("#ff4444", "#1a0a0a"))
        self.btn_disrupt.setFixedHeight(40)
        self.btn_disrupt.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_layout.addWidget(self.btn_disrupt)

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setStyleSheet(self._btn_style("#00ff88", "#0a1a0a"))
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_layout.addWidget(self.btn_stop)

        self.btn_stop_all = QPushButton("STOP ALL")
        self.btn_stop_all.setStyleSheet(self._btn_style("#fbbf24", "#1a1a0a"))
        self.btn_stop_all.setFixedHeight(40)
        self.btn_stop_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_layout.addWidget(self.btn_stop_all)

        right_layout.addLayout(btn_layout)

        # Clumsy status
        self.clumsy_status_label = QLabel("Clumsy: Checking...")
        self.clumsy_status_label.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        right_layout.addWidget(self.clumsy_status_label)

        right_layout.addStretch()
        right_scroll.setWidget(right)

        # Splitter setup
        splitter.addWidget(left)
        splitter.addWidget(right_scroll)
        splitter.setSizes([500, 400])
        splitter.setStyleSheet("QSplitter::handle { background: #1a2a3a; width: 2px; }")
        main_layout.addWidget(splitter)

        # Apply Red Disconnect preset on startup (hardest disconnect)
        self._on_preset_changed("Red Disconnect")

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    def connect_signals(self):
        self.scan_btn.clicked.connect(self.start_scan)
        self.device_table.itemSelectionChanged.connect(self._on_device_selected)
        self.btn_disrupt.clicked.connect(self._on_disrupt)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        self._scan_results_ready.connect(self._update_device_table)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def start_scan(self):
        self.scan_started.emit()
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("...")

        if self.controller:
            import threading
            def _scan():
                devices = self.controller.scan_devices()
                self._scan_results_ready.emit(devices if isinstance(devices, list) else [])
            threading.Thread(target=_scan, daemon=True).start()
        else:
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("SCAN")

    def _get_subnet(self, ip: str) -> str:
        parts = ip.split('.')
        if len(parts) == 4:
            return '.'.join(parts[:3])
        return ip

    def _update_device_table(self, devices):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("SCAN")

        self.devices = devices if isinstance(devices, list) else []

        subnets = set()
        for d in self.devices:
            ip = d.ip if hasattr(d, 'ip') else d.get('ip', '')
            if ip:
                subnets.add(self._get_subnet(ip))

        current_filter = self.network_combo.currentText()
        self.network_combo.blockSignals(True)
        self.network_combo.clear()
        self.network_combo.addItem("All Networks")
        for subnet in sorted(subnets):
            self.network_combo.addItem(f"{subnet}.x")
        idx = self.network_combo.findText(current_filter)
        self.network_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.network_combo.blockSignals(False)

        self._apply_device_filter()

    def _on_network_filter_changed(self, text: str):
        self._apply_device_filter()

    def _apply_device_filter(self):
        self.device_table.setRowCount(0)
        self._row_checkboxes = []

        network_filter = self.network_combo.currentText()
        disrupted = self.controller.get_disrupted_devices() if self.controller else []

        visible_count = 0
        for d in self.devices:
            ip = d.ip if hasattr(d, 'ip') else d.get('ip', '')
            hostname = d.hostname if hasattr(d, 'hostname') else d.get('hostname', '')
            vendor = d.vendor if hasattr(d, 'vendor') else d.get('vendor', '')

            if network_filter != "All Networks":
                subnet_prefix = network_filter.replace('.x', '')
                if not ip.startswith(subnet_prefix + '.'):
                    continue

            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            visible_count += 1

            # Col 0: Selection checkbox (radio-like — only one at a time)
            cb = QCheckBox()
            cb.setStyleSheet("""
                QCheckBox { margin-left: 6px; }
                QCheckBox::indicator { width: 14px; height: 14px; }
                QCheckBox::indicator:unchecked {
                    border: 1px solid #3a4a5a; background: #0a1628; border-radius: 7px;
                }
                QCheckBox::indicator:checked {
                    border: 1px solid #00d9ff; background: #00d9ff; border-radius: 7px;
                }
            """)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self.device_table.setCellWidget(row, 0, cb_widget)

            # Store reference with real IP
            self._row_checkboxes.append((cb, ip))
            cb.stateChanged.connect(lambda state, r_ip=ip, r_cb=cb: self._on_row_checkbox(r_ip, r_cb, state))

            # If this IP was previously selected, re-check it
            if ip == self.selected_ip:
                cb.setChecked(True)

            # Col 1: IP (masked or real)
            display_ip = self._mask_ip(ip) if self._ip_hidden else ip
            ip_item = QTableWidgetItem(display_ip)
            ip_item.setData(Qt.ItemDataRole.UserRole, ip)  # store real IP
            self.device_table.setItem(row, 1, ip_item)

            # Col 2-3: Hostname, Vendor
            self.device_table.setItem(row, 2, QTableWidgetItem(hostname or "—"))
            self.device_table.setItem(row, 3, QTableWidgetItem(vendor or "—"))

            # Col 4: Status
            if ip in disrupted:
                status_item = QTableWidgetItem("DISRUPTED")
                status_item.setForeground(QColor("#ff4444"))
            else:
                status_item = QTableWidgetItem("ONLINE")
                status_item.setForeground(QColor("#00ff88"))
            self.device_table.setItem(row, 4, status_item)

            # Col 5: Session timer
            if ip in self._disruption_timers:
                elapsed = int(time.time() - self._disruption_timers[ip])
                session_text = f"{elapsed // 60}:{elapsed % 60:02d}"
            else:
                session_text = "—"
            self.device_table.setItem(row, 5, QTableWidgetItem(session_text))

        total = len(self.devices)
        if network_filter == "All Networks":
            self.device_count_label.setText(f"{total} devices found")
        else:
            self.device_count_label.setText(f"{visible_count} of {total} devices ({network_filter})")
        self.scan_finished.emit(self.devices)

    def _on_row_checkbox(self, ip: str, checkbox: QCheckBox, state: int):
        """Handle row checkbox click — radio-like: only one selected at a time."""
        if state == 2:  # Qt.CheckState.Checked
            # Uncheck all other checkboxes
            for cb, cb_ip in self._row_checkboxes:
                if cb is not checkbox:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
            # Set as selected target
            self.selected_ip = ip
            display = self._mask_ip(ip) if self._ip_hidden else ip
            self.target_label.setText(f"TARGET: {display}")
            self.target_label.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: #00d9ff; letter-spacing: 1px; padding: 8px;"
            )
        else:
            # Unchecked — clear selection if it was this IP
            if self.selected_ip == ip:
                self.selected_ip = None
                self.target_label.setText("NO TARGET SELECTED")
                self.target_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #ff4444; letter-spacing: 1px; padding: 8px;"
                )

    @staticmethod
    def _mask_ip(ip: str) -> str:
        """Mask an IP: 192.168.137.5 → 192.168.***.***"""
        parts = ip.split('.')
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.***.***"
        return "***"

    def _toggle_ip_visibility(self):
        """Toggle IP masking on/off."""
        self._ip_hidden = self.hide_ip_btn.isChecked()
        # Update all IP cells in the table
        for row in range(self.device_table.rowCount()):
            ip_item = self.device_table.item(row, 1)
            if ip_item:
                real_ip = ip_item.data(Qt.ItemDataRole.UserRole)
                if real_ip:
                    ip_item.setText(self._mask_ip(real_ip) if self._ip_hidden else real_ip)
        # Update target label
        if self.selected_ip:
            display = self._mask_ip(self.selected_ip) if self._ip_hidden else self.selected_ip
            self.target_label.setText(f"TARGET: {display}")

    # ------------------------------------------------------------------
    # Device Selection
    # ------------------------------------------------------------------
    def _on_device_selected(self):
        rows = self.device_table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            ip_item = self.device_table.item(row, 1)  # IP is col 1 now
            if ip_item:
                real_ip = ip_item.data(Qt.ItemDataRole.UserRole) or ip_item.text()
                # Check the corresponding checkbox (which triggers _on_row_checkbox)
                for cb, cb_ip in self._row_checkboxes:
                    if cb_ip == real_ip:
                        cb.setChecked(True)
                        break

    # ------------------------------------------------------------------
    # Disruption Actions
    # ------------------------------------------------------------------
    def _collect_params(self) -> dict:
        """Read all slider + checkbox values into a params dict."""
        params = {}

        # Slider values
        for key, slider in self.sliders.items():
            params[key] = slider.value()

        # Extra checkboxes
        for key, cb in self.extra_checks.items():
            params[key] = cb.isChecked()

        # Direction
        inb = self.dir_inbound.isChecked()
        outb = self.dir_outbound.isChecked()
        if inb and outb:
            params["direction"] = "both"
        elif inb:
            params["direction"] = "inbound"
        else:
            params["direction"] = "outbound"

        return params

    def _on_disrupt(self):
        if not self.selected_ip:
            QMessageBox.warning(self, "No Target", "Select a device from the list first.")
            return

        methods = [key for key, cb in self.module_checks.items() if cb.isChecked()]
        if not methods:
            # Fall back to preset
            preset = self.preset_combo.currentText()
            methods = PRESETS.get(preset, {}).get("methods", ["drop", "lag"])
            if not methods:
                methods = ["drop", "lag"]

        params = self._collect_params()

        if self.controller:
            success = self.controller.disrupt_device(self.selected_ip, methods, params)
            if success:
                self._disruption_timers[self.selected_ip] = time.time()
                log_info(f"Disruption started on {self.selected_ip}: methods={methods}")
                self._refresh_device_table_status()
            else:
                QMessageBox.warning(
                    self, "Failed",
                    f"Could not start disruption on {self.selected_ip}.\n"
                    "Check admin privileges, WinDivert files, and logs."
                )

    def _on_stop(self):
        if not self.selected_ip:
            return
        if self.controller:
            self.controller.stop_disruption(self.selected_ip)
            self._disruption_timers.pop(self.selected_ip, None)
            log_info(f"Disruption stopped on {self.selected_ip}")
            self._refresh_device_table_status()

    def _on_stop_all(self):
        if self.controller:
            self.controller.stop_all_disruptions()
            self._disruption_timers.clear()
            log_info("All disruptions stopped")
            self._refresh_device_table_status()

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------
    def _on_preset_changed(self, preset_name: str):
        preset = PRESETS.get(preset_name, {})
        self.preset_desc.setText(preset.get("description", ""))

        methods = preset.get("methods", [])
        params = preset.get("params", {})

        # Set module checkboxes
        for key, cb in self.module_checks.items():
            cb.setChecked(key in methods)

        # Set slider values from preset params
        for key, slider in self.sliders.items():
            if key in params:
                slider.setValue(int(params[key]))

        # Set direction
        direction = params.get("direction", "outbound")
        self.dir_inbound.setChecked(direction in ("inbound", "both"))
        self.dir_outbound.setChecked(direction in ("outbound", "both"))

        # Set extra checkboxes
        for key, cb in self.extra_checks.items():
            if key in params:
                cb.setChecked(bool(params[key]))

    # ------------------------------------------------------------------
    # Status Refresh
    # ------------------------------------------------------------------
    def _refresh_disruption_status(self):
        try:
            status = clumsy_network_disruptor.get_clumsy_status()
            admin = status.get("is_admin", False)
            exe = status.get("clumsy_exe_exists", False)
            dll = status.get("windivert_dll_exists", False)

            if admin and exe and dll:
                count = status.get("disrupted_devices_count", 0)
                if count > 0:
                    self.clumsy_status_label.setText(
                        f"Engine: ACTIVE | {count} disruption(s)")
                    self.clumsy_status_label.setStyleSheet(
                        "color: #ff4444; font-size: 11px; padding: 4px; font-weight: bold;")
                else:
                    self.clumsy_status_label.setText("Engine: Ready")
                    self.clumsy_status_label.setStyleSheet(
                        "color: #00ff88; font-size: 11px; padding: 4px;")
            else:
                issues = []
                if not admin:
                    issues.append("no admin")
                if not exe:
                    issues.append("clumsy.exe missing")
                if not dll:
                    issues.append("WinDivert.dll missing")
                self.clumsy_status_label.setText(
                    f"Engine: UNAVAILABLE ({', '.join(issues)})")
                self.clumsy_status_label.setStyleSheet(
                    "color: #ff4444; font-size: 11px; padding: 4px;")
        except Exception as e:
            self.clumsy_status_label.setText(f"Engine: Error — {e}")

    def _refresh_device_table_status(self):
        disrupted = self.controller.get_disrupted_devices() if self.controller else []
        for row in range(self.device_table.rowCount()):
            ip_item = self.device_table.item(row, 1)  # IP col
            if ip_item:
                ip = ip_item.data(Qt.ItemDataRole.UserRole) or ip_item.text()
                status_item = self.device_table.item(row, 4)  # Status col
                if ip in disrupted:
                    if status_item:
                        status_item.setText("DISRUPTED")
                        status_item.setForeground(QColor("#ff4444"))
                else:
                    if status_item:
                        status_item.setText("ONLINE")
                        status_item.setForeground(QColor("#00ff88"))

    def _update_session_timers(self):
        for row in range(self.device_table.rowCount()):
            ip_item = self.device_table.item(row, 1)  # IP col
            if ip_item:
                ip = ip_item.data(Qt.ItemDataRole.UserRole) or ip_item.text()
                session_item = self.device_table.item(row, 5)  # Session col
                if ip in self._disruption_timers and session_item:
                    elapsed = int(time.time() - self._disruption_timers[ip])
                    session_item.setText(f"{elapsed // 60}:{elapsed % 60:02d}")

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------
    def _card(self, title: str) -> QGroupBox:
        box = QGroupBox(title)
        box.setStyleSheet("""
            QGroupBox {
                color: #00d9ff;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
                border: 1px solid #1a2a3a;
                border-radius: 6px;
                margin-top: 12px;
                padding: 12px 8px 8px 8px;
                background: #0f1923;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)
        return box

    @staticmethod
    def _btn_style(color: str, bg: str) -> str:
        return f"""
            QPushButton {{
                background: {bg};
                color: {color};
                border: 1px solid {color};
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background: {color};
                color: #0a0a0a;
            }}
            QPushButton:pressed {{
                background: {color};
                color: #0a0a0a;
                border: 2px solid {color};
            }}
            QPushButton:disabled {{
                background: #1a1a1a;
                color: #4a4a4a;
                border: 1px solid #2a2a2a;
            }}
        """

    @staticmethod
    def _slider_style() -> str:
        return """
            QSlider::groove:horizontal {
                border: 1px solid #1a2a3a;
                height: 6px;
                background: #0a1628;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #00d9ff;
                border: none;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: rgba(0, 217, 255, 0.3);
                border-radius: 3px;
            }
        """

    @staticmethod
    def _combo_style() -> str:
        return """
            QComboBox {
                background: #0a1628;
                color: #e0e0e0;
                border: 1px solid #1a2a3a;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background: #0f1923;
                color: #e0e0e0;
                selection-background-color: rgba(0, 217, 255, 0.3);
                border: 1px solid #1a2a3a;
            }
        """
