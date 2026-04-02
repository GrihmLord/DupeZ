# app/gui/clumsy_control.py — Main View: Device List + Full Clumsy Disruption Controls

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QSlider, QComboBox, QGroupBox, QGridLayout, QMessageBox,
    QProgressBar, QSplitter, QCheckBox, QSpinBox, QScrollArea,
    QLineEdit
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG
from PyQt6.QtGui import QFont, QColor, QCursor
from typing import List, Dict, Optional
import time
import threading

from app.logs.logger import log_info, log_error, log_warning
from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
from app.core.data_persistence import nickname_manager, device_cache_manager

# Smart Disruption Engine — AI auto-tuning
try:
    from app.ai.network_profiler import NetworkProfiler
    from app.ai.smart_engine import SmartDisruptionEngine
    from app.ai.llm_advisor import LLMAdvisor, LLMConfig
    from app.ai.session_tracker import SessionTracker
    SMART_ENGINE_AVAILABLE = True
except ImportError:
    SMART_ENGINE_AVAILABLE = False

# Profile system
try:
    from app.core.profiles import ProfileManager
    PROFILES_AVAILABLE = True
except ImportError:
    PROFILES_AVAILABLE = False


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
        self.selected_ips = set()     # multi-target mode
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

        self.multi_target_btn = QPushButton("MULTI")
        self.multi_target_btn.setCheckable(True)
        self.multi_target_btn.setToolTip("Multi-Target Mode — select multiple devices for simultaneous disruption")
        self.multi_target_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #64748b; border: 1px solid #1e293b;
                padding: 3px 10px; font-size: 10px; font-weight: bold; border-radius: 4px;
            }
            QPushButton:checked {
                background: rgba(168,85,247,0.15); color: #a855f7; border: 1px solid #a855f7;
            }
            QPushButton:hover { color: #e0e0e0; border-color: #3a4a5a; }
        """)
        self.multi_target_btn.setFixedHeight(26)
        self.multi_target_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        net_filter_row.addWidget(self.multi_target_btn)

        left_layout.addLayout(net_filter_row)

        # Device table — col 0=select, 1=IP, 2=Nickname, 3=Hostname, 4=Vendor, 5=Status, 6=Session
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(7)
        self.device_table.setHorizontalHeaderLabels(["", "IP", "Nickname", "Hostname", "Vendor", "Status", "Session"])
        self.device_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.device_table.customContextMenuRequested.connect(self._device_context_menu)
        hdr = self.device_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
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

        # Profile save/load buttons
        if PROFILES_AVAILABLE:
            self._profile_manager = ProfileManager()
            profile_btn_row = QHBoxLayout()
            profile_btn_row.setSpacing(6)

            self.btn_save_profile = QPushButton("SAVE")
            self.btn_save_profile.setStyleSheet(self._btn_style("#00ff88", "#0a1a0a"))
            self.btn_save_profile.setFixedHeight(26)
            self.btn_save_profile.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.btn_save_profile.setToolTip("Save current settings as a named profile")
            self.btn_save_profile.clicked.connect(self._on_save_profile)
            profile_btn_row.addWidget(self.btn_save_profile)

            self.btn_load_profile = QPushButton("LOAD")
            self.btn_load_profile.setStyleSheet(self._btn_style("#00d9ff", "#0a1628"))
            self.btn_load_profile.setFixedHeight(26)
            self.btn_load_profile.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.btn_load_profile.setToolTip("Load a saved profile")
            self.btn_load_profile.clicked.connect(self._on_load_profile)
            profile_btn_row.addWidget(self.btn_load_profile)

            self.btn_delete_profile = QPushButton("DEL")
            self.btn_delete_profile.setStyleSheet(self._btn_style("#ff4444", "#1a0a0a"))
            self.btn_delete_profile.setFixedHeight(26)
            self.btn_delete_profile.setFixedWidth(50)
            self.btn_delete_profile.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.btn_delete_profile.setToolTip("Delete a saved profile")
            self.btn_delete_profile.clicked.connect(self._on_delete_profile)
            profile_btn_row.addWidget(self.btn_delete_profile)

            # Import / Export
            io_row = QHBoxLayout()
            io_row.setSpacing(4)
            btn_import = QPushButton("IMPORT")
            btn_import.setStyleSheet(self._btn_style("#94a3b8", "#0a1628"))
            btn_import.setFixedHeight(24)
            btn_import.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_import.setToolTip("Import a profile from JSON file")
            btn_import.clicked.connect(self._on_import_profile)
            io_row.addWidget(btn_import)

            btn_export = QPushButton("EXPORT")
            btn_export.setStyleSheet(self._btn_style("#94a3b8", "#0a1628"))
            btn_export.setFixedHeight(24)
            btn_export.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_export.setToolTip("Export a profile to JSON file")
            btn_export.clicked.connect(self._on_export_profile)
            io_row.addWidget(btn_export)
            preset_layout.addLayout(io_row)

            preset_layout.addLayout(profile_btn_row)

        preset_group.setLayout(preset_layout)
        right_layout.addWidget(preset_group)

        # ---- SMART MODE: AI AUTO-TUNE ----
        if SMART_ENGINE_AVAILABLE:
            self._smart_profiler = NetworkProfiler(ping_count=6, ping_timeout=2.0)
            self._smart_engine = SmartDisruptionEngine()
            self._smart_tracker = SessionTracker()
            self._smart_advisor = LLMAdvisor()
            self._active_session_id = None

            smart_group = self._card("AI AUTO-TUNE")
            smart_layout = QVBoxLayout()
            smart_layout.setSpacing(6)

            # Goal selector
            goal_row = QHBoxLayout()
            goal_label = QLabel("GOAL:")
            goal_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
            goal_label.setFixedWidth(40)
            goal_row.addWidget(goal_label)

            self.smart_goal_combo = QComboBox()
            self.smart_goal_combo.addItems(["Auto", "Disconnect", "Lag", "Desync", "Throttle", "Chaos"])
            self.smart_goal_combo.setStyleSheet(self._combo_style())
            goal_row.addWidget(self.smart_goal_combo, 1)
            smart_layout.addLayout(goal_row)

            # Intensity slider
            intensity_row = QHBoxLayout()
            int_label = QLabel("POWER:")
            int_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
            int_label.setFixedWidth(48)
            intensity_row.addWidget(int_label)

            self.smart_intensity_slider = QSlider(Qt.Orientation.Horizontal)
            self.smart_intensity_slider.setRange(0, 100)
            self.smart_intensity_slider.setValue(80)
            self.smart_intensity_slider.setStyleSheet(self._slider_style().replace(
                "#00d9ff", "#a855f7").replace(
                "rgba(0, 217, 255, 0.3)", "rgba(168, 85, 247, 0.3)"))
            intensity_row.addWidget(self.smart_intensity_slider, 1)

            self.smart_intensity_label = QLabel("80%")
            self.smart_intensity_label.setFixedWidth(35)
            self.smart_intensity_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.smart_intensity_label.setStyleSheet(
                "color: #a855f7; font-weight: bold; font-size: 11px;")
            intensity_row.addWidget(self.smart_intensity_label)
            self.smart_intensity_slider.valueChanged.connect(
                lambda v: self.smart_intensity_label.setText(f"{v}%"))
            smart_layout.addLayout(intensity_row)

            # LLM prompt input (natural language)
            self.smart_llm_input = None
            llm_row = QHBoxLayout()
            llm_label = QLabel("ASK AI:")
            llm_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: bold;")
            llm_label.setFixedWidth(48)
            llm_row.addWidget(llm_label)

            self.smart_llm_input = QLineEdit()
            self.smart_llm_input.setPlaceholderText("e.g. desync a PS5 on my hotspot playing DayZ")
            self.smart_llm_input.setStyleSheet("""
                QLineEdit {
                    background: #0a1628; color: #e0e0e0; border: 1px solid #1a2a3a;
                    border-radius: 4px; padding: 6px 8px; font-size: 11px;
                }
                QLineEdit:focus { border-color: #a855f7; }
            """)
            self.smart_llm_input.returnPressed.connect(self._on_smart_llm_ask)
            llm_row.addWidget(self.smart_llm_input, 1)
            smart_layout.addLayout(llm_row)

            # Action buttons
            smart_btn_row = QHBoxLayout()
            smart_btn_row.setSpacing(6)

            self.btn_smart_profile = QPushButton("PROFILE")
            self.btn_smart_profile.setStyleSheet(self._btn_style("#a855f7", "#1a0a2a"))
            self.btn_smart_profile.setFixedHeight(32)
            self.btn_smart_profile.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.btn_smart_profile.setToolTip("Probe target and analyze connection")
            self.btn_smart_profile.clicked.connect(self._on_smart_profile)
            smart_btn_row.addWidget(self.btn_smart_profile)

            self.btn_smart_disrupt = QPushButton("SMART DISRUPT")
            self.btn_smart_disrupt.setStyleSheet(self._btn_style("#a855f7", "#1a0a2a").replace(
                "#a855f7", "#e040fb"))
            self.btn_smart_disrupt.setFixedHeight(32)
            self.btn_smart_disrupt.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.btn_smart_disrupt.setToolTip("Profile + auto-tune + disrupt in one click")
            self.btn_smart_disrupt.clicked.connect(self._on_smart_disrupt)
            smart_btn_row.addWidget(self.btn_smart_disrupt)
            smart_layout.addLayout(smart_btn_row)

            # AI recommendation display
            self.smart_info_label = QLabel("Select a target and click PROFILE or SMART DISRUPT")
            self.smart_info_label.setWordWrap(True)
            self.smart_info_label.setStyleSheet(
                "color: #6b7280; font-size: 10px; padding: 4px; "
                "background: #0a0f18; border: 1px solid #1a2a3a; border-radius: 4px;")
            self.smart_info_label.setMinimumHeight(50)
            smart_layout.addWidget(self.smart_info_label)

            # Confidence / effectiveness bar
            self.smart_confidence_bar = QProgressBar()
            self.smart_confidence_bar.setRange(0, 100)
            self.smart_confidence_bar.setValue(0)
            self.smart_confidence_bar.setFormat("Confidence: %p%")
            self.smart_confidence_bar.setFixedHeight(16)
            self.smart_confidence_bar.setStyleSheet("""
                QProgressBar {
                    background: #0a1628; border: 1px solid #1a2a3a;
                    border-radius: 3px; font-size: 9px; color: #94a3b8;
                    text-align: center;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #a855f7, stop:1 #e040fb);
                    border-radius: 3px;
                }
            """)
            smart_layout.addWidget(self.smart_confidence_bar)

            smart_group.setLayout(smart_layout)
            right_layout.addWidget(smart_group)

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

        # ── Scheduler / Macro panel ──
        sched_group = self._card("SCHEDULER / MACROS")
        sched_layout = QVBoxLayout()
        sched_layout.setSpacing(6)

        # Quick-schedule row
        sched_row1 = QHBoxLayout()
        sched_row1.setSpacing(4)
        self.sched_duration = QSpinBox()
        self.sched_duration.setRange(5, 3600)
        self.sched_duration.setValue(60)
        self.sched_duration.setSuffix("s")
        self.sched_duration.setToolTip("Disruption duration (seconds)")
        self.sched_duration.setFixedWidth(80)
        self.sched_duration.setStyleSheet("QSpinBox { background: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; }")
        sched_row1.addWidget(QLabel("Duration:"))
        sched_row1.addWidget(self.sched_duration)

        self.sched_delay = QSpinBox()
        self.sched_delay.setRange(0, 3600)
        self.sched_delay.setValue(0)
        self.sched_delay.setSuffix("s")
        self.sched_delay.setToolTip("Delay before starting (0 = now)")
        self.sched_delay.setFixedWidth(80)
        self.sched_delay.setStyleSheet("QSpinBox { background: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; }")
        sched_row1.addWidget(QLabel("Delay:"))
        sched_row1.addWidget(self.sched_delay)
        sched_layout.addLayout(sched_row1)

        sched_row2 = QHBoxLayout()
        sched_row2.setSpacing(4)
        self.btn_sched_once = QPushButton("TIMED DISRUPT")
        self.btn_sched_once.setToolTip("Disrupt for set duration, then auto-stop")
        self.btn_sched_once.setStyleSheet(self._btn_style("#a855f7", "#1a0a2a"))
        self.btn_sched_once.setFixedHeight(30)
        self.btn_sched_once.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_sched_once.clicked.connect(self._on_timed_disrupt)
        sched_row2.addWidget(self.btn_sched_once)

        self.btn_run_macro = QPushButton("RUN MACRO")
        self.btn_run_macro.setToolTip("Chain disruption steps in sequence")
        self.btn_run_macro.setStyleSheet(self._btn_style("#e040fb", "#1a0a1a"))
        self.btn_run_macro.setFixedHeight(30)
        self.btn_run_macro.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_run_macro.clicked.connect(self._on_run_macro)
        sched_row2.addWidget(self.btn_run_macro)

        self.btn_stop_macro = QPushButton("STOP MACRO")
        self.btn_stop_macro.setStyleSheet(self._btn_style("#fbbf24", "#1a1a0a"))
        self.btn_stop_macro.setFixedHeight(30)
        self.btn_stop_macro.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_stop_macro.clicked.connect(self._on_stop_macro)
        sched_row2.addWidget(self.btn_stop_macro)
        sched_layout.addLayout(sched_row2)

        self.sched_status = QLabel("No scheduled disruptions")
        self.sched_status.setStyleSheet("color: #6b7280; font-size: 11px;")
        sched_layout.addWidget(self.sched_status)

        sched_group.setLayout(sched_layout)
        right_layout.addWidget(sched_group)

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
            if ip in self.selected_ips or ip == self.selected_ip:
                cb.setChecked(True)

            # Col 1: IP (masked or real)
            display_ip = self._mask_ip(ip) if self._ip_hidden else ip
            ip_item = QTableWidgetItem(display_ip)
            ip_item.setData(Qt.ItemDataRole.UserRole, ip)  # store real IP
            self.device_table.setItem(row, 1, ip_item)

            # Col 2: Nickname
            mac = d.mac if hasattr(d, 'mac') else d.get('mac', '')
            nick = nickname_manager.get_nickname(mac=mac, ip=ip)
            nick_item = QTableWidgetItem(nick or "—")
            if nick:
                nick_item.setForeground(QColor("#fbbf24"))
            self.device_table.setItem(row, 2, nick_item)

            # Col 3-4: Hostname, Vendor
            self.device_table.setItem(row, 3, QTableWidgetItem(hostname or "—"))
            self.device_table.setItem(row, 4, QTableWidgetItem(vendor or "—"))

            # Col 5: Status
            if ip in disrupted:
                status_item = QTableWidgetItem("DISRUPTED")
                status_item.setForeground(QColor("#ff4444"))
            else:
                status_item = QTableWidgetItem("ONLINE")
                status_item.setForeground(QColor("#00ff88"))
            self.device_table.setItem(row, 5, status_item)

            # Col 6: Session timer
            if ip in self._disruption_timers:
                elapsed = int(time.time() - self._disruption_timers[ip])
                session_text = f"{elapsed // 60}:{elapsed % 60:02d}"
            else:
                session_text = "—"
            self.device_table.setItem(row, 6, QTableWidgetItem(session_text))

        total = len(self.devices)
        if network_filter == "All Networks":
            self.device_count_label.setText(f"{total} devices found")
        else:
            self.device_count_label.setText(f"{visible_count} of {total} devices ({network_filter})")
        self.scan_finished.emit(self.devices)

    def _on_row_checkbox(self, ip: str, checkbox: QCheckBox, state: int):
        """Handle row checkbox click — radio-like or multi-select depending on mode."""
        multi = hasattr(self, 'multi_target_btn') and self.multi_target_btn.isChecked()

        if state == 2:  # Qt.CheckState.Checked
            if multi:
                # Multi-target: keep all checked, track set
                self.selected_ips.add(ip)
                self.selected_ip = ip  # primary target for smart mode etc.
            else:
                # Single-target: uncheck all others
                for cb, cb_ip in self._row_checkboxes:
                    if cb is not checkbox:
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
                self.selected_ips = {ip}
                self.selected_ip = ip

            # Update target label
            if multi and len(self.selected_ips) > 1:
                self.target_label.setText(f"TARGETS: {len(self.selected_ips)} devices")
                self.target_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #a855f7; letter-spacing: 1px; padding: 8px;"
                )
            else:
                display = self._mask_ip(ip) if self._ip_hidden else ip
                self.target_label.setText(f"TARGET: {display}")
                self.target_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #00d9ff; letter-spacing: 1px; padding: 8px;"
                )
        else:
            # Unchecked
            self.selected_ips.discard(ip)
            if self.selected_ip == ip:
                self.selected_ip = next(iter(self.selected_ips), None)

            if not self.selected_ips:
                self.target_label.setText("NO TARGET SELECTED")
                self.target_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #ff4444; letter-spacing: 1px; padding: 8px;"
                )
            elif len(self.selected_ips) > 1:
                self.target_label.setText(f"TARGETS: {len(self.selected_ips)} devices")
                self.target_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #a855f7; letter-spacing: 1px; padding: 8px;"
                )
            else:
                remaining = next(iter(self.selected_ips))
                display = self._mask_ip(remaining) if self._ip_hidden else remaining
                self.target_label.setText(f"TARGET: {display}")
                self.target_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #00d9ff; letter-spacing: 1px; padding: 8px;"
                )

    @staticmethod
    def _mask_ip(ip: str) -> str:
        """Mask an IP: 198.51.100.5 → 198.51.***.***"""
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
    # Device Context Menu (right-click)
    # ------------------------------------------------------------------
    def _device_context_menu(self, pos):
        """Right-click context menu on device table — set/clear nickname."""
        from PyQt6.QtWidgets import QMenu as _QMenu, QInputDialog
        row_idx = self.device_table.rowAt(pos.y())
        if row_idx < 0:
            return
        ip_item = self.device_table.item(row_idx, 1)
        if not ip_item:
            return
        real_ip = ip_item.data(Qt.ItemDataRole.UserRole) or ip_item.text()

        # Find MAC for this device
        mac = ""
        for d in self.devices:
            d_ip = d.ip if hasattr(d, 'ip') else d.get('ip', '')
            if d_ip == real_ip:
                mac = d.mac if hasattr(d, 'mac') else d.get('mac', '')
                break

        key = mac or real_ip
        current_nick = nickname_manager.get_nickname(mac=mac, ip=real_ip)

        menu = _QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #0a0e1a; color: #e2e8f0; border: 1px solid #1e293b; }
            QMenu::item { padding: 6px 20px; }
            QMenu::item:selected { background: rgba(0, 217, 255, 0.2); }
        """)

        set_action = menu.addAction("Set Nickname..." if not current_nick else f"Rename \"{current_nick}\"...")
        clear_action = None
        if current_nick:
            clear_action = menu.addAction("Clear Nickname")

        action = menu.exec(self.device_table.viewport().mapToGlobal(pos))
        if action == set_action:
            text, ok = QInputDialog.getText(self, "Device Nickname",
                                            f"Nickname for {real_ip}:", text=current_nick)
            if ok and text.strip():
                nickname_manager.set_nickname(key, text.strip())
                nick_item = self.device_table.item(row_idx, 2)
                if nick_item:
                    nick_item.setText(text.strip())
                    nick_item.setForeground(QColor("#fbbf24"))
        elif clear_action and action == clear_action:
            nickname_manager.remove_nickname(key)
            nick_item = self.device_table.item(row_idx, 2)
            if nick_item:
                nick_item.setText("—")
                nick_item.setForeground(QColor("#e0e0e0"))

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
        targets = list(self.selected_ips) if self.selected_ips else ([self.selected_ip] if self.selected_ip else [])
        if not targets:
            QMessageBox.warning(self, "No Target", "Select a device from the list first.")
            return

        methods = [key for key, cb in self.module_checks.items() if cb.isChecked()]
        if not methods:
            preset = self.preset_combo.currentText()
            methods = PRESETS.get(preset, {}).get("methods", ["drop", "lag"])
            if not methods:
                methods = ["drop", "lag"]

        params = self._collect_params()

        if self.controller:
            failed = []
            for ip in targets:
                success = self.controller.disrupt_device(ip, methods, params)
                if success:
                    self._disruption_timers[ip] = time.time()
                    log_info(f"Disruption started on {ip}: methods={methods}")
                else:
                    failed.append(ip)

            self._refresh_device_table_status()

            if failed:
                QMessageBox.warning(
                    self, "Partial Failure",
                    f"Could not start disruption on: {', '.join(failed)}\n"
                    "Check admin privileges, WinDivert files, and logs."
                )

    def _on_stop(self):
        targets = list(self.selected_ips) if self.selected_ips else ([self.selected_ip] if self.selected_ip else [])
        if not targets:
            return
        if self.controller:
            for ip in targets:
                self.controller.stop_disruption(ip)
                self._disruption_timers.pop(ip, None)
                log_info(f"Disruption stopped on {ip}")
            self._refresh_device_table_status()

            # End smart session tracking if active
            if SMART_ENGINE_AVAILABLE and hasattr(self, '_active_session_id') and self._active_session_id:
                self._smart_tracker.end_session(self._active_session_id)
                self._active_session_id = None

    def _on_stop_all(self):
        if self.controller:
            self.controller.stop_all_disruptions()
            self._disruption_timers.clear()
            log_info("All disruptions stopped")
            self._refresh_device_table_status()

            # End all smart sessions
            if SMART_ENGINE_AVAILABLE and hasattr(self, '_active_session_id') and self._active_session_id:
                self._smart_tracker.end_session(self._active_session_id)
                self._active_session_id = None

    # ------------------------------------------------------------------
    # Scheduled / Timed Disruption + Macros
    # ------------------------------------------------------------------
    def _on_timed_disrupt(self):
        """Start a disruption with auto-stop after duration."""
        if not self.selected_ip:
            QMessageBox.warning(self, "No Target", "Select a device first.")
            return
        if not self.controller:
            return

        from app.core.scheduler import ScheduledRule
        duration = self.sched_duration.value()
        delay = self.sched_delay.value()
        methods = [key for key, cb in self.module_checks.items() if cb.isChecked()]
        if not methods:
            preset = self.preset_combo.currentText()
            methods = PRESETS.get(preset, {}).get("methods", ["drop", "lag"])
        params = self._collect_params()

        if delay == 0:
            # Immediate start with auto-stop timer
            targets = list(self.selected_ips) if self.selected_ips else [self.selected_ip]
            for ip in targets:
                self.controller.disrupt_device(ip, methods, params)
                self._disruption_timers[ip] = time.time()

            # Schedule auto-stop
            def _auto_stop():
                time.sleep(duration)
                if self.controller:
                    for ip in targets:
                        self.controller.stop_disruption(ip)
                        self._disruption_timers.pop(ip, None)
                    log_info(f"Timed disruption ended after {duration}s")

            threading.Thread(target=_auto_stop, daemon=True).start()
            self.sched_status.setText(f"Timed: {duration}s on {len(targets)} target(s)")
            self.sched_status.setStyleSheet("color: #a855f7; font-size: 11px;")
            self._refresh_device_table_status()
        else:
            # Delayed start via scheduler
            rule = ScheduledRule(
                name=f"Timed-{self.selected_ip}-{duration}s",
                target_ip=self.selected_ip,
                methods=methods,
                params=params,
                start_time="",
                duration_seconds=duration,
                repeat_interval=0,
            )
            # Use epoch for delayed start
            rule.last_run = time.time() - 99999  # force immediate on next tick after delay
            self.controller.scheduler.add_rule(rule)
            self.sched_status.setText(f"Scheduled: {delay}s delay → {duration}s disruption")
            self.sched_status.setStyleSheet("color: #a855f7; font-size: 11px;")

    def _on_run_macro(self):
        """Run a disruption macro — chain preset steps in sequence."""
        if not self.selected_ip:
            QMessageBox.warning(self, "No Target", "Select a device first.")
            return
        if not self.controller:
            return

        from app.core.scheduler import DisruptionMacro, MacroStep

        macros = self.controller.scheduler.get_macros()
        if macros:
            # Let user pick an existing macro
            from PyQt6.QtWidgets import QInputDialog
            names = [m.name for m in macros]
            names.insert(0, "-- Create Quick Macro --")
            choice, ok = QInputDialog.getItem(
                self, "Run Macro", "Select macro:", names, 0, False)
            if not ok:
                return
            if choice != "-- Create Quick Macro --":
                macro = next(m for m in macros if m.name == choice)
                self.controller.scheduler.run_macro(macro.macro_id, self.selected_ip)
                self.sched_status.setText(f"Macro '{macro.name}' running...")
                self.sched_status.setStyleSheet("color: #e040fb; font-size: 11px;")
                return

        # Quick macro: current settings → light → heavy → stop
        duration = self.sched_duration.value() // 3 or 10
        methods = [key for key, cb in self.module_checks.items() if cb.isChecked()]
        if not methods:
            methods = ["drop", "lag"]
        params = self._collect_params()

        macro = DisruptionMacro(
            name="Quick Macro",
            target_ip=self.selected_ip,
            repeat_count=1,
            steps=[
                MacroStep(methods=["lag", "drop"], params={"lag_delay": 500, "drop_chance": 40, "direction": "both"}, duration_seconds=duration),
                MacroStep(methods=methods, params=params, duration_seconds=duration),
                MacroStep(methods=["lag", "drop", "bandwidth"], params={"lag_delay": 2000, "drop_chance": 90, "bandwidth_limit": 1, "direction": "both"}, duration_seconds=duration),
            ]
        )
        mid = self.controller.scheduler.add_macro(macro)
        self.controller.scheduler.run_macro(mid, self.selected_ip)
        self.sched_status.setText(f"Quick Macro running ({duration}s x 3 steps)...")
        self.sched_status.setStyleSheet("color: #e040fb; font-size: 11px;")

    def _on_stop_macro(self):
        """Stop the active macro."""
        if self.controller:
            self.controller.scheduler.stop_macro()
            self.sched_status.setText("Macro stopped")
            self.sched_status.setStyleSheet("color: #6b7280; font-size: 11px;")

    # ------------------------------------------------------------------
    # Profile Management
    # ------------------------------------------------------------------
    def _on_save_profile(self):
        """Save current slider/module state as a named profile."""
        if not PROFILES_AVAILABLE:
            return
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Save Profile", "Profile name:",
            text=self.preset_combo.currentText())
        if not ok or not name.strip():
            return

        methods = [key for key, cb in self.module_checks.items() if cb.isChecked()]
        params = self._collect_params()
        self._profile_manager.save(
            name=name.strip(), methods=methods, params=params,
            description=f"Saved from DupeZ ({len(methods)} modules)")
        log_info(f"Profile saved: {name.strip()}")
        QMessageBox.information(self, "Saved", f"Profile '{name.strip()}' saved.")

    def _on_load_profile(self):
        """Load a saved profile and apply to controls."""
        if not PROFILES_AVAILABLE:
            return
        profiles = self._profile_manager.list_profiles()
        if not profiles:
            QMessageBox.information(self, "No Profiles", "No saved profiles found.")
            return

        from PyQt6.QtWidgets import QInputDialog
        names = [p.name for p in profiles]
        name, ok = QInputDialog.getItem(
            self, "Load Profile", "Select profile:", names, 0, False)
        if not ok or not name:
            return

        profile = self._profile_manager.load(name)
        if not profile:
            return

        # Apply to controls
        for key, cb in self.module_checks.items():
            cb.setChecked(key in profile.methods)
        for key, slider in self.sliders.items():
            if key in profile.params:
                slider.setValue(int(profile.params[key]))
        direction = profile.params.get("direction", "both")
        self.dir_inbound.setChecked(direction in ("inbound", "both"))
        self.dir_outbound.setChecked(direction in ("outbound", "both"))
        for key, cb in self.extra_checks.items():
            if key in profile.params:
                cb.setChecked(bool(profile.params[key]))

        # Switch preset to Custom
        idx = self.preset_combo.findText("Custom")
        if idx >= 0:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(idx)
            self.preset_combo.blockSignals(False)
        self.preset_desc.setText(profile.description)
        log_info(f"Profile loaded: {name}")

    def _on_delete_profile(self):
        """Delete a saved profile."""
        if not PROFILES_AVAILABLE:
            return
        profiles = self._profile_manager.list_profiles()
        if not profiles:
            QMessageBox.information(self, "No Profiles", "No saved profiles found.")
            return

        from PyQt6.QtWidgets import QInputDialog
        names = [p.name for p in profiles]
        name, ok = QInputDialog.getItem(
            self, "Delete Profile", "Select profile to delete:", names, 0, False)
        if not ok or not name:
            return

        confirm = QMessageBox.question(
            self, "Confirm Delete", f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            self._profile_manager.delete(name)
            log_info(f"Profile deleted: {name}")

    def _on_export_profile(self):
        """Export a profile to a standalone JSON file."""
        if not PROFILES_AVAILABLE:
            return
        profiles = self._profile_manager.list_profiles()
        if not profiles:
            QMessageBox.information(self, "No Profiles", "No saved profiles to export.")
            return
        from PyQt6.QtWidgets import QInputDialog, QFileDialog
        names = [p.name for p in profiles]
        name, ok = QInputDialog.getItem(
            self, "Export Profile", "Select profile:", names, 0, False)
        if not ok or not name:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Profile", f"{name}.json", "JSON (*.json)")
        if path:
            if self._profile_manager.export_profile(name, path):
                QMessageBox.information(self, "Exported", f"Profile '{name}' exported to:\n{path}")
            else:
                QMessageBox.warning(self, "Failed", "Export failed — check logs.")

    def _on_import_profile(self):
        """Import a profile from a JSON file."""
        if not PROFILES_AVAILABLE:
            return
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Profile", "", "JSON (*.json)")
        if not path:
            return
        profile = self._profile_manager.import_profile(path)
        if profile:
            QMessageBox.information(self, "Imported", f"Profile '{profile.name}' imported.")
        else:
            QMessageBox.warning(self, "Failed", "Import failed — check file format and logs.")

    # ------------------------------------------------------------------
    # Smart Mode — AI Auto-Tune
    # ------------------------------------------------------------------
    def _on_smart_profile(self):
        """Profile the selected target and display analysis."""
        if not SMART_ENGINE_AVAILABLE:
            return
        if not self.selected_ip:
            QMessageBox.warning(self, "No Target", "Select a device from the list first.")
            return

        self.smart_info_label.setText(f"Profiling {self.selected_ip}...")
        self.smart_info_label.setStyleSheet(
            "color: #a855f7; font-size: 10px; padding: 4px; "
            "background: #0a0f18; border: 1px solid #a855f7; border-radius: 4px;")
        self.btn_smart_profile.setEnabled(False)
        self.btn_smart_disrupt.setEnabled(False)

        def _on_profile_done(profile):
            # Generate recommendation
            goal = self.smart_goal_combo.currentText().lower()
            intensity = self.smart_intensity_slider.value() / 100.0
            rec = self._smart_engine.recommend(profile, goal=goal, intensity=intensity)

            # Update UI (must be thread-safe via signal)
            QMetaObject.invokeMethod(
                self, "_smart_update_ui",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(object, profile),
                Q_ARG(object, rec),
            )

        self._smart_profiler.profile_async(self.selected_ip, callback=_on_profile_done)

    def _on_smart_disrupt(self):
        """Profile + auto-tune + disrupt in one click."""
        if not SMART_ENGINE_AVAILABLE:
            return
        if not self.selected_ip:
            QMessageBox.warning(self, "No Target", "Select a device from the list first.")
            return

        self.smart_info_label.setText(f"Smart disrupting {self.selected_ip}...")
        self.smart_info_label.setStyleSheet(
            "color: #e040fb; font-size: 10px; padding: 4px; "
            "background: #0a0f18; border: 1px solid #e040fb; border-radius: 4px;")
        self.btn_smart_profile.setEnabled(False)
        self.btn_smart_disrupt.setEnabled(False)

        def _on_profile_done(profile):
            goal = self.smart_goal_combo.currentText().lower()
            intensity = self.smart_intensity_slider.value() / 100.0
            rec = self._smart_engine.recommend(profile, goal=goal, intensity=intensity)

            QMetaObject.invokeMethod(
                self, "_smart_apply_and_disrupt",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(object, profile),
                Q_ARG(object, rec),
            )

        self._smart_profiler.profile_async(self.selected_ip, callback=_on_profile_done)

    def _on_smart_llm_ask(self):
        """Handle natural language input to LLM advisor."""
        if not SMART_ENGINE_AVAILABLE or not self.smart_llm_input:
            return

        prompt = self.smart_llm_input.text().strip()
        if not prompt:
            return

        self.smart_info_label.setText("Asking AI advisor...")
        self.smart_llm_input.setEnabled(False)

        def _on_result(result):
            QMetaObject.invokeMethod(
                self, "_smart_apply_llm_result",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(object, result),
            )

        self._smart_advisor.ask_async(prompt, callback=_on_result)

    @pyqtSlot(object, object)
    def _smart_update_ui(self, profile, rec):
        """Update Smart Mode UI with profiling results (called on main thread)."""
        self.btn_smart_profile.setEnabled(True)
        self.btn_smart_disrupt.setEnabled(True)

        # Build info text
        info_lines = [
            f"<b style='color:#a855f7'>TARGET ANALYSIS</b>",
            f"<span style='color:#94a3b8'>RTT:</span> <b>{profile.avg_rtt_ms:.0f}ms</b> "
            f"(jitter: {profile.jitter_ms:.0f}ms) &nbsp; "
            f"<span style='color:#94a3b8'>Loss:</span> <b>{profile.packet_loss_pct:.0f}%</b>",
            f"<span style='color:#94a3b8'>Type:</span> {profile.connection_type} / {profile.device_type} "
            f"{'(' + profile.device_hint + ')' if profile.device_hint else ''}",
            f"<span style='color:#94a3b8'>Quality:</span> <b>{profile.quality_score:.0f}/100</b>",
            f"",
            f"<b style='color:#e040fb'>RECOMMENDATION: {rec.name}</b> "
            f"<span style='color:#6b7280'>(goal: {rec.goal})</span>",
            f"<span style='color:#94a3b8'>Modules:</span> {' + '.join(rec.methods)}",
        ]
        for reason in rec.reasoning[:3]:
            info_lines.append(f"<span style='color:#6b7280'>• {reason}</span>")

        self.smart_info_label.setText("<br>".join(info_lines))
        self.smart_info_label.setStyleSheet(
            "color: #e0e0e0; font-size: 10px; padding: 6px; "
            "background: #0a0f18; border: 1px solid #1a2a3a; border-radius: 4px;")

        # Update confidence bar
        conf_pct = int(rec.confidence * 100)
        self.smart_confidence_bar.setValue(conf_pct)
        self.smart_confidence_bar.setFormat(
            f"Confidence: {conf_pct}% | Effectiveness: {rec.estimated_effectiveness:.0f}%")

        # Auto-apply recommendation to the controls
        self._apply_recommendation(rec)

    @pyqtSlot(object, object)
    def _smart_apply_and_disrupt(self, profile, rec):
        """Apply recommendation and start disruption (main thread)."""
        self._smart_update_ui(profile, rec)

        # Start disruption with the recommended config
        if self.controller and self.selected_ip:
            success = self.controller.disrupt_device(
                self.selected_ip, rec.methods, rec.params)
            if success:
                self._disruption_timers[self.selected_ip] = time.time()
                log_info(f"Smart disruption started on {self.selected_ip}: "
                         f"{rec.name} ({rec.methods})")
                self._refresh_device_table_status()

                # Track session
                self._active_session_id = self._smart_tracker.start_session(
                    profile, rec,
                    intensity=self.smart_intensity_slider.value() / 100.0)
            else:
                QMessageBox.warning(
                    self, "Failed",
                    f"Smart disruption failed on {self.selected_ip}.\n"
                    "Check admin privileges, WinDivert files, and logs.")

    @pyqtSlot(object)
    def _smart_apply_llm_result(self, result):
        """Apply LLM advisor result to the controls (main thread)."""
        self.smart_llm_input.setEnabled(True)
        if not result:
            self.smart_info_label.setText("AI advisor returned no result. Try rephrasing.")
            return

        # Build a fake recommendation to reuse the apply logic
        from app.ai.smart_engine import DisruptionRecommendation
        rec = DisruptionRecommendation(
            name=result.get("name", "AI Recommendation"),
            description=result.get("description", ""),
            methods=result.get("methods", []),
            params=result.get("params", {}),
            reasoning=[result.get("reasoning", "")],
            confidence=0.7,
            estimated_effectiveness=75,
        )
        self._apply_recommendation(rec)

        info_lines = [
            f"<b style='color:#a855f7'>AI ADVISOR: {rec.name}</b>",
            f"<span style='color:#94a3b8'>{rec.description}</span>",
            f"<span style='color:#94a3b8'>Modules:</span> {' + '.join(rec.methods)}",
            f"<span style='color:#6b7280'>{rec.reasoning[0] if rec.reasoning else ''}</span>",
        ]
        self.smart_info_label.setText("<br>".join(info_lines))
        self.smart_confidence_bar.setValue(70)
        self.smart_confidence_bar.setFormat("AI Advisor — apply with DISRUPT button")

    def _apply_recommendation(self, rec):
        """Apply a DisruptionRecommendation to the manual controls."""
        # Set module checkboxes
        for key, cb in self.module_checks.items():
            cb.setChecked(key in rec.methods)

        # Set slider values
        for key, slider in self.sliders.items():
            if key in rec.params:
                slider.setValue(int(rec.params[key]))

        # Set direction
        direction = rec.params.get("direction", "both")
        self.dir_inbound.setChecked(direction in ("inbound", "both"))
        self.dir_outbound.setChecked(direction in ("outbound", "both"))

        # Set extra checkboxes
        for key, cb in self.extra_checks.items():
            if key in rec.params:
                cb.setChecked(bool(rec.params[key]))

        # Switch preset to Custom since AI overrode it
        idx = self.preset_combo.findText("Custom")
        if idx >= 0:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(idx)
            self.preset_combo.blockSignals(False)
            self.preset_desc.setText(rec.description)

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
                status_item = self.device_table.item(row, 5)  # Status col
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
                session_item = self.device_table.item(row, 6)  # Session col
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
