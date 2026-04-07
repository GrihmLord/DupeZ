# app/gui/clumsy_control.py — Main View: Device List + Full Clumsy Disruption Controls

import os
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QSlider, QComboBox, QGroupBox, QMessageBox,
    QProgressBar, QSplitter, QCheckBox, QSpinBox, QScrollArea,
    QLineEdit
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG
from PyQt6.QtGui import QColor, QCursor
import time
import threading

from app.logs.logger import log_info, log_error
from app.firewall.clumsy_network_disruptor import clumsy_network_disruptor
from app.core.data_persistence import nickname_manager

# Smart Disruption Engine — AI auto-tuning
try:
    from app.ai.network_profiler import NetworkProfiler
    from app.ai.smart_engine import SmartDisruptionEngine
    from app.ai.llm_advisor import LLMAdvisor
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

# Voice control
try:
    from app.ai.voice_control import VoiceController, VoiceConfig, is_voice_available
    VOICE_AVAILABLE = is_voice_available()
except ImportError:
    VOICE_AVAILABLE = False

# GPC / CronusZEN integration
try:
    from app.gpc.gpc_generator import (GPCGenerator, list_templates,
                                        get_template)
    from app.gpc.device_bridge import DeviceMonitor, scan_devices
    GPC_AVAILABLE = True
except ImportError:
    GPC_AVAILABLE = False
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
    "God Mode": {
        "description": "Directional lag — others freeze, you keep moving. Shots hit in real time.",
        "methods": ["godmode"],
        "params": {
            "godmode_lag_ms": 2000,
            "godmode_drop_inbound_pct": 0,
            "direction": "both",
        }
    },
    "God Mode Aggressive": {
        "description": "God Mode + 30% inbound drop — harder freeze, more desync on unlag",
        "methods": ["godmode"],
        "params": {
            "godmode_lag_ms": 3000,
            "godmode_drop_inbound_pct": 30,
            "direction": "both",
        }
    },
    "Custom": {
        "description": "Set your own parameters below",
        "methods": [],
        "params": {}
    }
}
def _mdef(key, label, desc, params=None):
    return {"key": key, "label": label, "desc": desc, "params": params or []}

MODULE_DEFS = [
    _mdef("lag", "LAG", "Add delay to packets", [("Delay (ms)", "lag_delay", 0, 2000, 500)]),
    _mdef("drop", "DROP", "Drop packets randomly", [("Chance %", "drop_chance", 0, 100, 100)]),
    _mdef("throttle", "THROTTLE", "Throttle packet flow", [
        ("Chance %", "throttle_chance", 0, 100, 80), ("Frame (ms)", "throttle_frame", 0, 1000, 100)]),
    _mdef("duplicate", "DUPLICATE", "Clone packets", [
        ("Chance %", "duplicate_chance", 0, 100, 50), ("Count", "duplicate_count", 1, 50, 5)]),
    _mdef("ood", "OUT OF ORDER", "Reorder packets", [("Chance %", "ood_chance", 0, 100, 50)]),
    _mdef("corrupt", "TAMPER", "Corrupt packet data", [("Chance %", "tamper_chance", 0, 100, 30)]),
    _mdef("rst", "TCP RST", "Inject RST flags", [("Chance %", "rst_chance", 0, 100, 100)]),
    _mdef("disconnect", "DISCONNECT", "Break connection"),
    _mdef("bandwidth", "BANDWIDTH", "Limit bandwidth", [
        ("Limit (KB/s)", "bandwidth_limit", 0, 1000, 5), ("Queue Size", "bandwidth_queue", 0, 1000, 0)]),
    _mdef("godmode", "GOD MODE", "Freeze others, keep moving", [
        ("Inbound Lag (ms)", "godmode_lag_ms", 0, 5000, 2000), ("Inbound Drop %", "godmode_drop_inbound_pct", 0, 100, 0)]),
]

class ClumsyControlView(QWidget):
    """Main view: Device scanner + per-device Clumsy disruption with full controls."""

    scan_started = pyqtSignal()
    scan_finished = pyqtSignal(list)
    _scan_results_ready = pyqtSignal(list)   # internal: thread-safe scan delivery

    @staticmethod
    def _cb_qss(radius=2, color="#00d9ff", margin=False):
        m = "margin-left: 6px; " if margin else ""
        return (f"QCheckBox {{ {m}color: {color}; font-size: 11px; font-weight: bold; }}"
                f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
                f"QCheckBox::indicator:unchecked {{ border: 1px solid #3a4a5a; background: #0a1628; border-radius: {radius}px; }}"
                f"QCheckBox::indicator:checked {{ border: 1px solid #00d9ff; background: #00d9ff; border-radius: {radius}px; }}")
    _MODULE_CB_QSS = _cb_qss.__func__(2)
    _MUTED_QSS = "color: #6b7280; font-size: 11px;"
    _MUTED_PAD_QSS = "color: #6b7280; font-size: 11px; padding: 4px;"
    _SPINBOX_QSS = "QSpinBox { background: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; }"
    _SUBTLE_QSS = "color: #94a3b8; font-size: 10px;"
    _LABEL_BOLD_QSS = "color: #94a3b8; font-size: 11px; font-weight: bold;"
    _SCHED_PURPLE_QSS = "color: #a855f7; font-size: 11px;"
    _SCHED_PINK_QSS = "color: #e040fb; font-size: 11px;"
    _RADIO_CB_QSS = _cb_qss.__func__(7, margin=True)
    _SLIDER_QSS = ("QSlider::groove:horizontal { border: 1px solid #1a2a3a; height: 6px; "
                   "background: #0a1628; border-radius: 3px; } "
                   "QSlider::handle:horizontal { background: #00d9ff; border: none; "
                   "width: 14px; margin: -4px 0; border-radius: 7px; } "
                   "QSlider::sub-page:horizontal { background: rgba(0,217,255,0.3); border-radius: 3px; }")
    _COMBO_QSS = ("QComboBox { background: #0a1628; color: #e0e0e0; border: 1px solid #1a2a3a; "
                  "border-radius: 4px; padding: 6px 10px; font-size: 12px; } "
                  "QComboBox::drop-down { border: none; width: 20px; } "
                  "QComboBox QAbstractItemView { background: #0f1923; color: #e0e0e0; "
                  "selection-background-color: rgba(0,217,255,0.3); border: 1px solid #1a2a3a; }")
    _CARD_QSS = ("QGroupBox { color: #00d9ff; font-size: 11px; font-weight: bold; "
                 "letter-spacing: 1px; border: 1px solid #1a2a3a; border-radius: 6px; "
                 "margin-top: 12px; padding: 12px 8px 8px 8px; background: #0f1923; } "
                 "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }")

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.devices = []
        self.selected_ip = None
        self.selected_ips = set()     # multi-target mode
        self._disruption_timers = {}  # ip -> start_time
        self._ip_hidden = False       # IP masking state
        self._row_checkboxes = []     # list of (QCheckBox, real_ip) per row
        self._voice_controller = None  # initialized in _build_voice_panel
        self._gpc_generator = None     # initialized in _build_gpc_panel
        self._gpc_last_source = ""
        self._gpc_monitor = None

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

        # Hook macro step callback for timer/status updates
        if self.controller and hasattr(self.controller, 'scheduler'):
            self.controller.scheduler._on_macro_step = self._on_macro_step_event

        # Stats dashboard refresh
        self.stats_refresh_timer = QTimer()
        self.stats_refresh_timer.timeout.connect(self._refresh_stats_panel)
        self.stats_refresh_timer.start(1500)

    # UI Setup
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

        self.scan_btn = self._make_btn("SCAN", "#00d9ff", "#0a1628", h=30, w=80)
        header.addWidget(self.scan_btn)
        left_layout.addLayout(header)

        # Network filter dropdown
        net_filter_row = QHBoxLayout()
        net_label = self._lbl("NETWORK:", bold=True, size=11)
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
        _modes = [QHeaderView.ResizeMode.Fixed] + [QHeaderView.ResizeMode.Stretch]*4 + [QHeaderView.ResizeMode.ResizeToContents]*2
        for i, mode in enumerate(_modes):
            hdr.setSectionResizeMode(i, mode)
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
        self.device_count_label.setStyleSheet(self._MUTED_QSS)
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
        self.preset_combo.setStyleSheet(self._COMBO_QSS)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        self.preset_desc = QLabel(PRESETS["Red Disconnect"]["description"])
        self.preset_desc.setStyleSheet(self._MUTED_PAD_QSS)
        self.preset_desc.setWordWrap(True)
        preset_layout.addWidget(self.preset_desc)

        # Profile save/load buttons
        if PROFILES_AVAILABLE:
            self._profile_manager = ProfileManager()
            profile_btn_row = QHBoxLayout()
            profile_btn_row.setSpacing(6)

            for attr, text, color, bg, handler, kw in [
                ("btn_save_profile", "SAVE", "#00ff88", "#0a1a0a", self._on_save_profile, {"h": 26, "tip": "Save current settings as a named profile"}),
                ("btn_load_profile", "LOAD", "#00d9ff", "#0a1628", self._on_load_profile, {"h": 26, "tip": "Load a saved profile"}),
                ("btn_delete_profile", "DEL", "#ff4444", "#1a0a0a", self._on_delete_profile, {"h": 26, "w": 50, "tip": "Delete a saved profile"}),
            ]:
                btn = self._make_btn(text, color, bg, **kw)
                btn.clicked.connect(handler); setattr(self, attr, btn); profile_btn_row.addWidget(btn)

            io_row = QHBoxLayout()
            io_row.setSpacing(4)
            for handler, text in [(self._on_import_profile, "IMPORT"), (self._on_export_profile, "EXPORT")]:
                btn = self._make_btn(text, "#94a3b8", "#0a1628", h=24, tip=f"{text.title()} a profile {'from' if text == 'IMPORT' else 'to'} JSON file")
                btn.clicked.connect(handler); io_row.addWidget(btn)
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
            goal_label.setStyleSheet(self._LABEL_BOLD_QSS)
            goal_label.setFixedWidth(40)
            goal_row.addWidget(goal_label)

            self.smart_goal_combo = QComboBox()
            self.smart_goal_combo.addItems(["Auto", "Disconnect", "Lag", "Desync", "Throttle", "Chaos", "God Mode"])
            self.smart_goal_combo.setStyleSheet(self._COMBO_QSS)
            goal_row.addWidget(self.smart_goal_combo, 1)
            smart_layout.addLayout(goal_row)

            # Intensity slider
            intensity_row = QHBoxLayout()
            int_label = QLabel("POWER:")
            int_label.setStyleSheet(self._LABEL_BOLD_QSS)
            int_label.setFixedWidth(48)
            intensity_row.addWidget(int_label)

            self.smart_intensity_slider = QSlider(Qt.Orientation.Horizontal)
            self.smart_intensity_slider.setRange(0, 100)
            self.smart_intensity_slider.setValue(80)
            self.smart_intensity_slider.setStyleSheet(self._SLIDER_QSS.replace(
                "#00d9ff", "#a855f7").replace(
                "rgba(0,217,255,0.3)", "rgba(168,85,247,0.3)"))
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
            llm_label = self._lbl("ASK AI:", bold=True, size=11, w=48)
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

            for attr, text, color, handler, tip in [
                ("btn_smart_profile", "PROFILE", "#a855f7", self._on_smart_profile, "Probe target and analyze connection"),
                ("btn_smart_disrupt", "SMART DISRUPT", "#e040fb", self._on_smart_disrupt, "Profile + auto-tune + disrupt in one click"),
            ]:
                btn = self._make_btn(text, color, "#1a0a2a", h=32, tip=tip)
                btn.clicked.connect(handler); setattr(self, attr, btn); smart_btn_row.addWidget(btn)
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
            self.smart_confidence_bar = self._progress_bar("Confidence: %p%", 16, "#a855f7", "#e040fb")
            smart_layout.addWidget(self.smart_confidence_bar)

            smart_group.setLayout(smart_layout)
            right_layout.addWidget(smart_group)

        # Global direction toggle
        dir_group = self._card("DIRECTION")
        dir_layout = QHBoxLayout()
        self.dir_inbound = QCheckBox("INBOUND")
        self.dir_outbound = QCheckBox("OUTBOUND")
        self.dir_outbound.setChecked(True)  # default outbound
        for cb in (self.dir_inbound, self.dir_outbound):
            cb.setStyleSheet("color: #e0e0e0; font-size: 11px; font-weight: bold;")
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
            cb.setStyleSheet(self._MODULE_CB_QSS)
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
                plbl.setStyleSheet(self._SUBTLE_QSS)
                param_row.addWidget(plbl)

                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(pmin, pmax)
                slider.setValue(pdefault)
                slider.setMinimumWidth(60)
                slider.setStyleSheet(self._SLIDER_QSS)
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

            # Extra checkboxes (tamper redo checksum, throttle drop)
            _EXTRAS = {"corrupt": ("Redo Checksum", "tamper_checksum", True),
                       "throttle": ("Drop Throttled", "throttle_drop", False)}
            if key in _EXTRAS:
                label, ekey, checked = _EXTRAS[key]
                extra_row = QHBoxLayout()
                extra_row.setContentsMargins(20, 0, 0, 0)
                ecb = QCheckBox(label)
                ecb.setChecked(checked)
                ecb.setStyleSheet(self._SUBTLE_QSS)
                extra_row.addWidget(ecb); extra_row.addStretch()
                self.extra_checks[ekey] = ecb
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

        self.btn_disrupt = self._make_btn("DISRUPT", "#ff4444", "#1a0a0a", h=40)
        btn_layout.addWidget(self.btn_disrupt)
        self.btn_stop = self._make_btn("STOP", "#00ff88", "#0a1a0a", h=40)
        btn_layout.addWidget(self.btn_stop)
        self.btn_stop_all = self._make_btn("STOP ALL", "#fbbf24", "#1a1a0a", h=40)
        btn_layout.addWidget(self.btn_stop_all)

        right_layout.addLayout(btn_layout)

        # ── Scheduler / Macro panel ──
        sched_group = self._card("SCHEDULER / MACROS")
        sched_layout = QVBoxLayout()
        sched_layout.setSpacing(6)

        # Quick-schedule row
        sched_row1 = QHBoxLayout()
        sched_row1.setSpacing(4)
        for attr, label, rng, val, tip in [
            ("sched_duration", "Duration:", (5, 3600), 60, "Disruption duration (seconds)"),
            ("sched_delay", "Delay:", (0, 3600), 0, "Delay before starting (0 = now)"),
        ]:
            sb = QSpinBox()
            sb.setRange(*rng); sb.setValue(val); sb.setSuffix("s")
            sb.setToolTip(tip); sb.setFixedWidth(80); sb.setStyleSheet(self._SPINBOX_QSS)
            setattr(self, attr, sb)
            sched_row1.addWidget(QLabel(label)); sched_row1.addWidget(sb)
        sched_layout.addLayout(sched_row1)

        sched_row2 = QHBoxLayout()
        sched_row2.setSpacing(4)
        for attr, text, color, bg, handler, tip in [
            ("btn_sched_once", "TIMED DISRUPT", "#a855f7", "#1a0a2a", self._on_timed_disrupt, "Disrupt for set duration, then auto-stop"),
            ("btn_run_macro", "RUN MACRO", "#e040fb", "#1a0a1a", self._on_run_macro, "Chain disruption steps in sequence"),
            ("btn_stop_macro", "STOP MACRO", "#fbbf24", "#1a1a0a", self._on_stop_macro, ""),
        ]:
            btn = self._make_btn(text, color, bg, tip=tip if tip else None)
            btn.clicked.connect(handler)
            setattr(self, attr, btn)
            sched_row2.addWidget(btn)
        sched_layout.addLayout(sched_row2)

        self.sched_status = QLabel("No scheduled disruptions")
        self.sched_status.setStyleSheet(self._MUTED_QSS)
        sched_layout.addWidget(self.sched_status)

        sched_group.setLayout(sched_layout)
        right_layout.addWidget(sched_group)

        # ---- LIVE STATS DASHBOARD ----
        self._build_stats_panel(right_layout)

        # ---- VOICE CONTROL PANEL ----
        self._build_voice_panel(right_layout)

        # ---- GPC / CRONUS PANEL ----
        self._build_gpc_panel(right_layout)

        # Clumsy status
        self.clumsy_status_label = QLabel("Clumsy: Checking...")
        self.clumsy_status_label.setStyleSheet(self._MUTED_PAD_QSS)
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

    # Signals
    def connect_signals(self):
        self.scan_btn.clicked.connect(self.start_scan)
        self.device_table.itemSelectionChanged.connect(self._on_device_selected)
        self.btn_disrupt.clicked.connect(self._on_disrupt)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        self._scan_results_ready.connect(self._update_device_table)

    # Scanning
    def start_scan(self):
        self.scan_started.emit()
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("...")

        if self.controller:
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
        def _attr(obj, key, default=''):
            return getattr(obj, key, None) or (obj.get(key, default) if isinstance(obj, dict) else default)

        for d in self.devices:
            ip, hostname, vendor = _attr(d, 'ip'), _attr(d, 'hostname'), _attr(d, 'vendor')

            if network_filter != "All Networks":
                subnet_prefix = network_filter.replace('.x', '')
                if not ip.startswith(subnet_prefix + '.'):
                    continue

            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            visible_count += 1

            # Col 0: Selection checkbox (radio-like — only one at a time)
            cb = QCheckBox()
            cb.setStyleSheet(self._RADIO_CB_QSS)
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

    def _update_target_label(self):
        """Update the target label based on current selection state."""
        base = "font-size: 14px; font-weight: bold; letter-spacing: 1px; padding: 8px; color: "
        if not self.selected_ips:
            self.target_label.setText("NO TARGET SELECTED")
            self.target_label.setStyleSheet(base + "#ff4444;")
        elif len(self.selected_ips) > 1:
            self.target_label.setText(f"TARGETS: {len(self.selected_ips)} devices")
            self.target_label.setStyleSheet(base + "#a855f7;")
        else:
            ip = next(iter(self.selected_ips))
            display = self._mask_ip(ip) if self._ip_hidden else ip
            self.target_label.setText(f"TARGET: {display}")
            self.target_label.setStyleSheet(base + "#00d9ff;")

    def _on_row_checkbox(self, ip: str, checkbox: QCheckBox, state: int):
        """Handle row checkbox click — radio-like or multi-select depending on mode."""
        multi = hasattr(self, 'multi_target_btn') and self.multi_target_btn.isChecked()

        if state == 2:  # Qt.CheckState.Checked
            if multi:
                self.selected_ips.add(ip)
                self.selected_ip = ip
            else:
                for cb, cb_ip in self._row_checkboxes:
                    if cb is not checkbox:
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
                self.selected_ips = {ip}
                self.selected_ip = ip
        else:
            self.selected_ips.discard(ip)
            if self.selected_ip == ip:
                self.selected_ip = next(iter(self.selected_ips), None)

        self._update_target_label()

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
        for row in range(self.device_table.rowCount()):
            ip_item = self.device_table.item(row, 1)
            if ip_item:
                real_ip = ip_item.data(Qt.ItemDataRole.UserRole)
                if real_ip:
                    ip_item.setText(self._mask_ip(real_ip) if self._ip_hidden else real_ip)
        if self.selected_ip:
            display = self._mask_ip(self.selected_ip) if self._ip_hidden else self.selected_ip
            self.target_label.setText(f"TARGET: {display}")

    # Device Context Menu (right-click)
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

    # Device Selection
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

    # ── Shared Helpers ──
    def _get_targets(self) -> list:
        """Return list of target IPs (multi-select aware)."""
        if self.selected_ips:
            return list(self.selected_ips)
        return [self.selected_ip] if self.selected_ip else []

    def _get_active_methods(self) -> list:
        """Return checked module keys, falling back to current preset."""
        methods = [key for key, cb in self.module_checks.items() if cb.isChecked()]
        if not methods:
            methods = PRESETS.get(self.preset_combo.currentText(), {}).get("methods", []) or ["drop", "lag"]
        return methods

    def _end_smart_session(self):
        """End smart session tracking if active."""
        if SMART_ENGINE_AVAILABLE and getattr(self, '_active_session_id', None):
            self._smart_tracker.end_session(self._active_session_id)
            self._active_session_id = None

    def _invoke_main(self, slot: str, *args):
        """Thread-safe invokeMethod shorthand — marshals to main thread."""
        q_args = [Q_ARG(object, a) for a in args]
        QMetaObject.invokeMethod(self, slot, Qt.ConnectionType.QueuedConnection, *q_args)

    # Disruption Actions
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
        targets = self._get_targets()
        if not targets:
            QMessageBox.warning(self, "No Target", "Select a device from the list first.")
            return

        methods = self._get_active_methods()
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
        targets = self._get_targets()
        if not targets or not self.controller:
            return
        for ip in targets:
            self.controller.stop_disruption(ip)
            self._disruption_timers.pop(ip, None)
            log_info(f"Disruption stopped on {ip}")
        self._refresh_device_table_status()
        self._end_smart_session()

    def _on_stop_all(self):
        if self.controller:
            self.controller.stop_all_disruptions()
            self._disruption_timers.clear()
            log_info("All disruptions stopped")
            self._refresh_device_table_status()
            self._end_smart_session()

    # Scheduled / Timed Disruption + Macros
    def _on_timed_disrupt(self):
        """Start a disruption with auto-stop after duration."""
        targets = self._get_targets()
        if not targets:
            QMessageBox.warning(self, "No Target", "Select a device first.")
            return
        if not self.controller:
            return

        from app.core.scheduler import ScheduledRule
        duration = self.sched_duration.value()
        delay = self.sched_delay.value()
        methods = self._get_active_methods()
        params = self._collect_params()

        if delay == 0:
            for ip in targets:
                self.controller.disrupt_device(ip, methods, params)
                self._disruption_timers[ip] = time.time()

            # Schedule auto-stop — use QTimer to stay on the GUI thread
            _targets_copy = list(targets)
            _dur = duration
            QTimer.singleShot(_dur * 1000, lambda: self._timed_auto_stop(_targets_copy, _dur))
            self.sched_status.setText(f"Timed: {duration}s on {len(targets)} target(s)")
            self.sched_status.setStyleSheet(self._SCHED_PURPLE_QSS)
            self._refresh_device_table_status()
        else:
            # Delayed start via scheduler — use epoch-based start_time
            rule = ScheduledRule(
                name=f"Timed-{self.selected_ip}-{duration}s",
                target_ip=self.selected_ip,
                methods=methods,
                params=params,
                start_time=str(time.time() + delay),  # epoch trigger
                duration_seconds=duration,
                repeat_interval=0,
            )
            self.controller.scheduler.add_rule(rule)
            self.sched_status.setText(f"Scheduled: {delay}s delay → {duration}s disruption")
            self.sched_status.setStyleSheet(self._SCHED_PURPLE_QSS)

    def _on_macro_step_event(self, event: str, ip: str, step_info: dict):
        """Called from scheduler background thread — marshal to Qt thread."""
        QTimer.singleShot(0, lambda: self._handle_macro_step(event, ip, step_info))

    def _handle_macro_step(self, event: str, ip: str, step_info: dict):
        """Process macro step events on the Qt main thread."""
        macro_name = step_info.get("macro", "Macro")
        if event == "start":
            self._disruption_timers[ip] = time.time()
            step_num = step_info.get("step", "?")
            total = step_info.get("total_steps", "?")
            cycle = step_info.get("cycle", 1)
            self.sched_status.setText(
                f"{macro_name}: step {step_num}/{total} (cycle {cycle})")
            self.sched_status.setStyleSheet(self._SCHED_PINK_QSS)
        elif event == "stop":
            self._disruption_timers.pop(ip, None)
        elif event == "done":
            self._disruption_timers.pop(ip, None)
            self.sched_status.setText(f"{macro_name} complete")
            self.sched_status.setStyleSheet(self._MUTED_QSS)
        self._refresh_device_table_status()

    def _timed_auto_stop(self, targets, duration):
        """Auto-stop callback — runs on the Qt main thread via QTimer.singleShot."""
        if self.controller:
            for ip in targets:
                self.controller.stop_disruption(ip)
                self._disruption_timers.pop(ip, None)
            log_info(f"Timed disruption ended after {duration}s")
            self._refresh_device_table_status()
            self.sched_status.setText(f"Timed disruption finished ({duration}s)")
            self.sched_status.setStyleSheet(self._MUTED_QSS)

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
                self.sched_status.setStyleSheet(self._SCHED_PINK_QSS)
                return

        # Quick macro: current settings → light → heavy → stop
        duration = self.sched_duration.value() // 3 or 10
        methods = self._get_active_methods()
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
        self.sched_status.setStyleSheet(self._SCHED_PINK_QSS)

    def _on_stop_macro(self):
        """Stop the active macro."""
        if self.controller:
            self.controller.scheduler.stop_macro()
            self.sched_status.setText("Macro stopped")
            self.sched_status.setStyleSheet(self._MUTED_QSS)

    # Profile Management
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

        methods = self._get_active_methods()
        params = self._collect_params()
        self._profile_manager.save(
            name=name.strip(), methods=methods, params=params,
            description=f"Saved from DupeZ ({len(methods)} modules)")
        log_info(f"Profile saved: {name.strip()}")
        QMessageBox.information(self, "Saved", f"Profile '{name.strip()}' saved.")

    def _pick_profile(self, title: str, prompt: str, empty_msg: str = "No saved profiles found."):
        """Shared helper: check availability, list profiles, pick one via dialog. Returns name or None."""
        if not PROFILES_AVAILABLE:
            return None
        profiles = self._profile_manager.list_profiles()
        if not profiles:
            QMessageBox.information(self, "No Profiles", empty_msg)
            return None
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getItem(self, title, prompt, [p.name for p in profiles], 0, False)
        return name if ok and name else None

    def _on_load_profile(self):
        name = self._pick_profile("Load Profile", "Select profile:")
        if not name:
            return
        profile = self._profile_manager.load(name)
        if profile:
            self._apply_config(profile.methods, profile.params,
                               description=profile.description, switch_to_custom=True)
            log_info(f"Profile loaded: {name}")

    def _on_delete_profile(self):
        name = self._pick_profile("Delete Profile", "Select profile to delete:")
        if not name:
            return
        confirm = QMessageBox.question(
            self, "Confirm Delete", f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            self._profile_manager.delete(name)
            log_info(f"Profile deleted: {name}")

    def _on_export_profile(self):
        name = self._pick_profile("Export Profile", "Select profile:", "No saved profiles to export.")
        if not name:
            return
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export Profile", f"{name}.json", "JSON (*.json)")
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

    # Smart Mode — AI Auto-Tune
    def _smart_run(self, label: str, color: str, slot: str):
        """Shared helper for smart profile/disrupt: validate, show status, profile_async → slot."""
        if not SMART_ENGINE_AVAILABLE:
            return
        if not self.selected_ip:
            QMessageBox.warning(self, "No Target", "Select a device from the list first.")
            return
        self.smart_info_label.setText(label)
        self.smart_info_label.setStyleSheet(
            f"color: {color}; font-size: 10px; padding: 4px; "
            f"background: #0a0f18; border: 1px solid {color}; border-radius: 4px;")
        self.btn_smart_profile.setEnabled(False)
        self.btn_smart_disrupt.setEnabled(False)

        def _on_profile_done(profile):
            goal = self.smart_goal_combo.currentText().lower()
            intensity = self.smart_intensity_slider.value() / 100.0
            rec = self._smart_engine.recommend(profile, goal=goal, intensity=intensity)
            self._invoke_main(slot, profile, rec)

        self._smart_profiler.profile_async(self.selected_ip, callback=_on_profile_done)

    def _on_smart_profile(self):
        self._smart_run(f"Profiling {self.selected_ip}...", "#a855f7", "_smart_update_ui")

    def _on_smart_disrupt(self):
        self._smart_run(f"Smart disrupting {self.selected_ip}...", "#e040fb", "_smart_apply_and_disrupt")

    def _on_smart_llm_ask(self):
        """Handle natural language input to LLM advisor."""
        if not SMART_ENGINE_AVAILABLE or not self.smart_llm_input:
            return

        prompt = self.smart_llm_input.text().strip()
        if not prompt:
            return

        self.smart_info_label.setText("Asking AI advisor...")
        self.smart_llm_input.setEnabled(False)

        self._smart_advisor.ask_async(prompt, callback=lambda r: self._invoke_main("_smart_apply_llm_result", r))

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

    # Unified config application (presets, profiles, AI, voice all use this)
    def _apply_config(self, methods: list, params: dict,
                      description: str = "", switch_to_custom: bool = False):
        """Apply a disruption config to all UI controls.

        Used by presets, profiles, AI recommendations, and voice commands.
        """
        for key, cb in self.module_checks.items():
            cb.setChecked(key in methods)
        for key, slider in self.sliders.items():
            if key in params:
                slider.setValue(int(params[key]))
        direction = params.get("direction", "both")
        self.dir_inbound.setChecked(direction in ("inbound", "both"))
        self.dir_outbound.setChecked(direction in ("outbound", "both"))
        for key, cb in self.extra_checks.items():
            if key in params:
                cb.setChecked(bool(params[key]))
        if switch_to_custom:
            idx = self.preset_combo.findText("Custom")
            if idx >= 0:
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(idx)
                self.preset_combo.blockSignals(False)
        if description:
            self.preset_desc.setText(description)

    def _apply_recommendation(self, rec):
        """Apply a DisruptionRecommendation to the manual controls."""
        self._apply_config(rec.methods, rec.params,
                           description=rec.description, switch_to_custom=True)

    # Presets
    def _on_preset_changed(self, preset_name: str):
        preset = PRESETS.get(preset_name, {})
        self._apply_config(
            preset.get("methods", []), preset.get("params", {}),
            description=preset.get("description", ""))

    # Status Refresh
    def _refresh_disruption_status(self):
        _qss = lambda c, bold=False: f"color: {c}; font-size: 11px; padding: 4px;{' font-weight: bold;' if bold else ''}"
        try:
            status = clumsy_network_disruptor.get_clumsy_status()
            admin, exe, dll = (status.get(k, False)
                               for k in ("is_admin", "clumsy_exe_exists", "windivert_dll_exists"))
            if admin and exe and dll:
                count = status.get("disrupted_devices_count", 0)
                if count > 0:
                    self.clumsy_status_label.setText(f"Engine: ACTIVE | {count} disruption(s)")
                    self.clumsy_status_label.setStyleSheet(_qss("#ff4444", bold=True))
                else:
                    self.clumsy_status_label.setText("Engine: Ready")
                    self.clumsy_status_label.setStyleSheet(_qss("#00ff88"))
            else:
                checks = [("no admin", admin), ("clumsy.exe missing", exe), ("WinDivert.dll missing", dll)]
                issues = [msg for msg, ok in checks if not ok]
                self.clumsy_status_label.setText(f"Engine: UNAVAILABLE ({', '.join(issues)})")
                self.clumsy_status_label.setStyleSheet(_qss("#ff4444"))
        except Exception as e:
            self.clumsy_status_label.setText(f"Engine: Error — {e}")

    def _refresh_device_table_status(self):
        disrupted = self.controller.get_disrupted_devices() if self.controller else []
        for row in range(self.device_table.rowCount()):
            ip_item = self.device_table.item(row, 1)
            status_item = self.device_table.item(row, 5)
            if ip_item and status_item:
                ip = ip_item.data(Qt.ItemDataRole.UserRole) or ip_item.text()
                text, color = ("DISRUPTED", "#ff4444") if ip in disrupted else ("ONLINE", "#00ff88")
                status_item.setText(text)
                status_item.setForeground(QColor(color))

    def _update_session_timers(self):
        for row in range(self.device_table.rowCount()):
            ip_item = self.device_table.item(row, 1)  # IP col
            if ip_item:
                ip = ip_item.data(Qt.ItemDataRole.UserRole) or ip_item.text()
                session_item = self.device_table.item(row, 6)  # Session col
                if session_item:
                    if ip in self._disruption_timers:
                        elapsed = int(time.time() - self._disruption_timers[ip])
                        mins = elapsed // 60
                        secs = elapsed % 60
                        session_item.setText(f"{mins}:{secs:02d}")
                    else:
                        session_item.setText("—")

    # Live Stats Dashboard
    def _build_stats_panel(self, parent_layout):
        """Build the real-time packet stats dashboard."""
        stats_group = self._card("LIVE STATS")
        stats_layout = QVBoxLayout()
        stats_layout.setSpacing(4)

        # Summary row: processed | dropped | passed
        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)

        _stat_defs = [
            ("PROCESSED", "_stat_processed", "#00d9ff"),
            ("DROPPED", "_stat_dropped", "#ff4444"),
            ("PASSED", "_stat_passed", "#00ff88"),
            ("IN", "_stat_inbound", "#a855f7"),
            ("OUT", "_stat_outbound", "#fbbf24"),
        ]
        for label_text, attr, color in _stat_defs:
            setattr(self, attr, QLabel("0"))
            widget = getattr(self, attr)
            col = QVBoxLayout()
            col.setSpacing(0)
            header = QLabel(label_text)
            header.setStyleSheet(f"color: #6b7280; font-size: 9px; font-weight: bold; letter-spacing: 1px;")
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(header)
            widget.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(widget)
            summary_row.addLayout(col)

        stats_layout.addLayout(summary_row)

        # Drop rate bar
        drop_row = QHBoxLayout()
        drop_lbl = QLabel("DROP RATE:")
        drop_lbl.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold;")
        drop_lbl.setFixedWidth(70)
        drop_row.addWidget(drop_lbl)

        self._stat_drop_bar = self._progress_bar("%p%", 14, "#ff4444", "#ff8800")
        drop_row.addWidget(self._stat_drop_bar, 1)
        stats_layout.addLayout(drop_row)

        # Active engines count
        self._stat_engines_label = self._lbl("Engines: 0 active", "#6b7280")
        stats_layout.addWidget(self._stat_engines_label)

        # Per-device breakdown (compact table)
        self._stat_device_table = QTableWidget()
        self._stat_device_table.setColumnCount(4)
        self._stat_device_table.setHorizontalHeaderLabels(["Device", "Processed", "Dropped", "Methods"])
        self._stat_device_table.setMaximumHeight(100)
        self._stat_device_table.verticalHeader().setVisible(False)
        self._stat_device_table.setAlternatingRowColors(True)
        hdr = self._stat_device_table.horizontalHeader()
        for i in range(4):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self._stat_device_table.setStyleSheet("""
            QTableWidget {
                background-color: #0a0f18; color: #e0e0e0;
                border: 1px solid #1a2a3a; gridline-color: #1a2a3a; font-size: 10px;
            }
            QTableWidget::item:alternate { background-color: #0a1628; }
            QHeaderView::section {
                background-color: #0f1923; color: #94a3b8; padding: 3px;
                border: 1px solid #1a2a3a; font-weight: bold; font-size: 9px;
            }
        """)
        stats_layout.addWidget(self._stat_device_table)

        stats_group.setLayout(stats_layout)
        parent_layout.addWidget(stats_group)

    def _refresh_stats_panel(self):
        """Refresh the stats dashboard with live engine data."""
        if not self.controller or not hasattr(self.controller, 'get_engine_stats'):
            return
        try:
            stats = self.controller.get_engine_stats()

            _keys = ("packets_processed", "packets_dropped", "packets_passed",
                     "packets_inbound", "packets_outbound")
            _widgets = (self._stat_processed, self._stat_dropped, self._stat_passed,
                        self._stat_inbound, self._stat_outbound)
            vals = [stats.get(k, 0) for k in _keys]
            for w, v in zip(_widgets, vals):
                w.setText(self._format_count(v))

            # Drop rate
            processed, dropped = vals[0], vals[1]
            self._stat_drop_bar.setValue(min(int(dropped / processed * 100), 100) if processed else 0)

            # Active engines
            active = stats.get("active_engines", 0)
            self._stat_engines_label.setText(f"Engines: {active} active")

            # Per-device breakdown
            per_device = stats.get("per_device", {})
            self._stat_device_table.setRowCount(0)
            for ip, dstats in per_device.items():
                row = self._stat_device_table.rowCount()
                self._stat_device_table.insertRow(row)
                display_ip = self._mask_ip(ip) if self._ip_hidden else ip
                self._stat_device_table.setItem(row, 0, QTableWidgetItem(display_ip))
                self._stat_device_table.setItem(row, 1, QTableWidgetItem(
                    self._format_count(dstats.get("packets_processed", 0))))
                self._stat_device_table.setItem(row, 2, QTableWidgetItem(
                    self._format_count(dstats.get("packets_dropped", 0))))
                methods = ", ".join(dstats.get("methods", []))
                self._stat_device_table.setItem(row, 3, QTableWidgetItem(methods))

        except Exception as e:
            log_error(f"Stats refresh error: {e}")

    @staticmethod
    def _format_count(n: int) -> str:
        """Format a packet count for display: 1234 → '1.2K', 1234567 → '1.2M'."""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    # Voice Control Panel
    def _build_voice_panel(self, parent_layout):
        """Build the voice control UI section."""
        voice_group = self._card("VOICE CONTROL")
        vl = QVBoxLayout()
        vl.setSpacing(6)

        if not VOICE_AVAILABLE:
            missing_label = QLabel("Install sounddevice + openai-whisper to enable")
            missing_label.setStyleSheet("color: #6b7280; font-size: 10px; font-style: italic;")
            vl.addWidget(missing_label)
            voice_group.setLayout(vl)
            parent_layout.addWidget(voice_group)
            return

        # Status row
        status_row = QHBoxLayout()
        self.voice_status_label = QLabel("Voice: Not initialized")
        self.voice_status_label.setStyleSheet(
            "color: #94a3b8; font-size: 10px; padding: 2px; "
            "background: #0a0f18; border: 1px solid #1a2a3a; border-radius: 3px;")
        status_row.addWidget(self.voice_status_label, 1)
        vl.addLayout(status_row)

        # Controls row
        ctrl_row = QHBoxLayout()

        self.btn_voice_init = self._make_btn("INIT", "#e040fb", "#0a1628", h=28)
        self.btn_voice_init.clicked.connect(self._on_voice_init)
        ctrl_row.addWidget(self.btn_voice_init)

        self.btn_voice_listen = self._make_btn("LISTEN", "#00ff88", "#0a1628", h=28,
                                                tip="Toggle continuous listening — say 'stop listening' to deactivate", enabled=False)
        self.btn_voice_listen.clicked.connect(self._on_voice_listen_toggle)
        ctrl_row.addWidget(self.btn_voice_listen)

        self.btn_voice_ptt = self._make_btn("PTT", "#6b7280", "#0a1628", h=28,
                                             tip="Push-to-talk: hold to record, release to transcribe", enabled=False)
        self.btn_voice_ptt.pressed.connect(self._on_voice_ptt_press)
        self.btn_voice_ptt.released.connect(self._on_voice_ptt_release)
        ctrl_row.addWidget(self.btn_voice_ptt)

        vl.addLayout(ctrl_row)

        # Model + Mic selectors
        for attr, label_text, items in [
            ("voice_model_combo", "MODEL:", [("tiny",), ("base",), ("small",)]),
            ("voice_mic_combo", "MIC:", [("System Default", None)]),
        ]:
            row = QHBoxLayout()
            row.addWidget(self._lbl(label_text, bold=True, w=48))
            combo = QComboBox()
            for item in items:
                combo.addItem(*item) if len(item) > 1 else combo.addItem(item[0])
            combo.setStyleSheet(self._COMBO_QSS)
            setattr(self, attr, combo)
            row.addWidget(combo, 1)
            vl.addLayout(row)

        voice_group.setLayout(vl)
        parent_layout.addWidget(voice_group)

        self._voice_controller = None

    def _on_voice_init(self):
        """Initialize the voice engine."""
        if not VOICE_AVAILABLE:
            return

        model_name = self.voice_model_combo.currentText()
        self.voice_status_label.setText(f"Loading {model_name} model...")
        self.voice_status_label.setStyleSheet(self._voice_status_qss("#e040fb"))
        self.btn_voice_init.setEnabled(False)

        # Build advisor if smart engine available
        advisor = None
        if SMART_ENGINE_AVAILABLE:
            advisor = LLMAdvisor()

        config = VoiceConfig(model_name=model_name)

        # Mic selection
        mic_data = self.voice_mic_combo.currentData()
        if mic_data is not None:
            config.input_device = mic_data

        self._voice_controller = VoiceController(
            advisor=advisor,
            on_command=self._on_voice_command,
            on_status=self._on_voice_status_update,
            on_listening_changed=self._on_voice_listening_changed,
            config=config,
        )

        self._voice_controller.initialize(callback=lambda ok: self._invoke_main("_voice_init_done", ok))

    @pyqtSlot(object)
    def _voice_init_done(self, ok):
        self.btn_voice_init.setEnabled(True)
        if ok:
            self.btn_voice_listen.setEnabled(True)
            self.btn_voice_ptt.setEnabled(True)
            self.voice_status_label.setText("Voice ready — click LISTEN or hold PTT")
            self.voice_status_label.setStyleSheet(self._voice_status_qss("#00ff88"))

            # Populate mic list
            if self._voice_controller:
                devices = self._voice_controller.list_input_devices()
                self.voice_mic_combo.clear()
                self.voice_mic_combo.addItem("System Default", None)
                for dev in devices:
                    self.voice_mic_combo.addItem(dev["name"], dev["index"])
        else:
            self.voice_status_label.setText("Voice init failed — check logs")
            self.voice_status_label.setStyleSheet(self._voice_status_qss("#ff4444"))

    def _on_voice_listen_toggle(self):
        """Toggle continuous listening on/off."""
        if not self._voice_controller:
            return
        self._voice_controller.toggle_listening()

    def _on_voice_listening_changed(self, listening: bool):
        """Called from VoiceController (background thread) — marshal to main thread."""
        self._invoke_main("_voice_update_listen_btn", listening)

    @pyqtSlot(object)
    def _voice_update_listen_btn(self, listening):
        """Update LISTEN button appearance based on listening state."""
        if not hasattr(self, 'btn_voice_listen'):
            return
        if listening:
            self.btn_voice_listen.setText("LISTENING")
            self.btn_voice_listen.setStyleSheet(self._btn_style("#ff4444", "#0a1628"))
            self.voice_status_label.setText("Listening... say 'stop listening' to deactivate")
            self.voice_status_label.setStyleSheet(self._voice_status_qss("#ff4444"))
        else:
            self.btn_voice_listen.setText("LISTEN")
            self.btn_voice_listen.setStyleSheet(self._btn_style("#00ff88", "#0a1628"))
            self.voice_status_label.setText("Voice ready — click LISTEN or hold PTT")
            self.voice_status_label.setStyleSheet(self._voice_status_qss("#00ff88"))

    def _on_voice_ptt_press(self):
        if self._voice_controller:
            self._voice_controller.push_to_talk_press()

    def _on_voice_ptt_release(self):
        if self._voice_controller:
            self._voice_controller.push_to_talk_release()

    def _on_voice_command(self, config: dict):
        """Handle a voice-generated disruption config (background thread → main)."""
        self._invoke_main("_voice_apply_command", config)

    @pyqtSlot(object)
    def _voice_apply_command(self, config):
        """Apply voice command on the main thread (Qt-safe)."""
        action = config.get("action")
        if action == "stop":
            self._on_stop()
            return
        if action == "start":
            self._on_disrupt()
            return

        # Apply as disruption config
        methods = config.get("methods", [])
        params = config.get("params", {})
        if methods and self.selected_ip and self.controller:
            log_info(f"VoiceCommand: applying {config.get('name', 'voice config')}")
            self.controller.disrupt_device(self.selected_ip, methods, params)
            self._disruption_timers[self.selected_ip] = time.time()
            self._refresh_device_table_status()

    def _on_voice_status_update(self, msg: str):
        """Thread-safe voice status update."""
        self._invoke_main("_voice_set_status", msg)

    @pyqtSlot(object)
    def _voice_set_status(self, msg):
        if hasattr(self, 'voice_status_label'):
            self.voice_status_label.setText(msg)

    # GPC / CronusZEN Panel
    def _build_gpc_panel(self, parent_layout):
        """Build the GPC script management panel."""
        gpc_group = self._card("GPC / CRONUS")
        gl = QVBoxLayout()
        gl.setSpacing(6)

        if not GPC_AVAILABLE:
            missing_label = self._lbl("GPC module not available", "#6b7280", italic=True)
            gl.addWidget(missing_label)
            gpc_group.setLayout(gl)
            parent_layout.addWidget(gpc_group)
            return

        # Device status
        self.gpc_device_label = QLabel("Device: Scanning...")
        self.gpc_device_label.setStyleSheet(self._voice_status_qss("#94a3b8"))
        gl.addWidget(self.gpc_device_label)

        # Template selector
        tmpl_row = QHBoxLayout()
        tmpl_label = self._lbl("SCRIPT:", bold=True, w=48)
        tmpl_row.addWidget(tmpl_label)

        self.gpc_template_combo = QComboBox()
        for tmpl in list_templates():
            self.gpc_template_combo.addItem(
                f"{tmpl['name']} ({tmpl['game']})", tmpl['name'])
        self.gpc_template_combo.setStyleSheet(self._COMBO_QSS)
        tmpl_row.addWidget(self.gpc_template_combo, 1)
        gl.addLayout(tmpl_row)

        # Template description
        self.gpc_desc_label = self._lbl("", "#6b7280", size=9)
        self.gpc_desc_label.setWordWrap(True)
        gl.addWidget(self.gpc_desc_label)
        self.gpc_template_combo.currentIndexChanged.connect(self._on_gpc_template_changed)
        self._on_gpc_template_changed()  # set initial description

        # Buttons
        btn_row = QHBoxLayout()

        for attr, text, color, handler, kw in [
            ("btn_gpc_generate", "GENERATE", "#ff6b35", self._on_gpc_generate, {}),
            ("btn_gpc_export", "EXPORT .GPC", "#00d9ff", self._on_gpc_export, {"enabled": False}),
            ("btn_gpc_sync", "SYNC TIMING", "#e040fb", self._on_gpc_sync, {"tip": "Generate script synced with current disruption settings"}),
        ]:
            btn = self._make_btn(text, color, "#0a1628", h=28, **kw)
            btn.clicked.connect(handler); setattr(self, attr, btn); btn_row.addWidget(btn)

        gl.addLayout(btn_row)

        # Generated script preview (collapsed by default)
        self.gpc_preview_label = QLabel("")
        self.gpc_preview_label.setStyleSheet(
            "color: #6b7280; font-size: 9px; font-family: 'Consolas', 'Courier New', monospace; "
            "padding: 4px; background: #080c14; border: 1px solid #1a2a3a; border-radius: 3px;")
        self.gpc_preview_label.setWordWrap(True)
        self.gpc_preview_label.setMaximumHeight(120)
        self.gpc_preview_label.hide()
        gl.addWidget(self.gpc_preview_label)

        gpc_group.setLayout(gl)
        parent_layout.addWidget(gpc_group)

        # State
        self._gpc_generator = GPCGenerator()
        self._gpc_last_source = ""

        # Start device monitor in background
        self._gpc_monitor = DeviceMonitor(
            on_connect=lambda dev: self._gpc_device_event(f"Connected: {dev.name}"),
            on_disconnect=lambda dev: self._gpc_device_event(f"Disconnected: {dev.name}"),
        )
        self._gpc_monitor.start()

        # Initial device scan
        def _initial_scan():
            devices = scan_devices()
            msg = (f"Device: {devices[0].name} ({devices[0].device_type.upper()})"
                   if devices else "Device: None detected — scripts export to file")
            self._invoke_main("_gpc_set_device_label", msg)

        threading.Thread(target=_initial_scan, daemon=True).start()

    def _on_gpc_template_changed(self):
        if not GPC_AVAILABLE:
            return
        name = self.gpc_template_combo.currentData()
        if name:
            tmpl = get_template(name)
            if tmpl:
                self.gpc_desc_label.setText(tmpl.description)

    def _gpc_store_preview(self, source: str, label: str):
        """Store generated GPC source and show truncated preview."""
        self._gpc_last_source = source
        self.btn_gpc_export.setEnabled(True)
        self.gpc_preview_label.setText(source[:500] + ("..." if len(source) > 500 else ""))
        self.gpc_preview_label.show()
        log_info(f"GPC: {label} ({len(source)} chars)")

    def _on_gpc_generate(self):
        if not GPC_AVAILABLE:
            return
        name = self.gpc_template_combo.currentData()
        tmpl = get_template(name) if name else None
        if tmpl:
            self._gpc_store_preview(self._gpc_generator.generate(tmpl), f"generated script '{name}'")

    def _on_gpc_sync(self):
        if not GPC_AVAILABLE:
            return
        params = self._collect_params()
        methods = self._get_active_methods()
        source = self._gpc_generator.generate_from_disruption({"methods": methods, "params": params})
        self._gpc_store_preview(source, "generated synced script")

    def _on_gpc_export(self):
        """Export the last generated script to a .gpc file."""
        if not self._gpc_last_source or not GPC_AVAILABLE:
            return

        from app.gpc.device_bridge import get_default_export_path
        export_dir = get_default_export_path()
        name = self.gpc_template_combo.currentData() or "dupez_script"
        safe_name = re.sub(r'[^\w\-]', '_', name.lower())
        path = os.path.join(export_dir, f"{safe_name}.gpc")

        ok = self._gpc_generator.export_to_file(self._gpc_last_source, path)
        if ok:
            QMessageBox.information(self, "GPC Export",
                                   f"Script exported to:\n{path}")
        else:
            QMessageBox.warning(self, "GPC Export", "Failed to export — check logs")

    def _gpc_device_event(self, msg: str):
        self._invoke_main("_gpc_set_device_label", msg)

    @pyqtSlot(object)
    def _gpc_set_device_label(self, msg):
        if hasattr(self, 'gpc_device_label'):
            self.gpc_device_label.setText(msg)

    # Styles
    def _card(self, title: str) -> QGroupBox:
        box = QGroupBox(title)
        box.setStyleSheet(self._CARD_QSS)
        return box

    def _make_btn(self, text: str, color: str, bg: str, h: int = 30,
                  w: int = 0, tip: str = "", enabled: bool = True) -> QPushButton:
        """Factory: create a styled button with cursor, height, optional tooltip."""
        btn = QPushButton(text)
        btn.setStyleSheet(self._btn_style(color, bg))
        btn.setFixedHeight(h)
        if w:
            btn.setFixedWidth(w)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if tip:
            btn.setToolTip(tip)
        if not enabled:
            btn.setEnabled(False)
        return btn

    @staticmethod
    def _voice_status_qss(color: str) -> str:
        """QSS for the voice status label with a given accent color."""
        return (f"color: {color}; font-size: 10px; padding: 2px; "
                f"background: #0a0f18; border: 1px solid {color}; border-radius: 3px;")

    def _lbl(self, text: str, color: str = "#94a3b8", size: int = 10,
             bold: bool = False, italic: bool = False, w: int = 0) -> QLabel:
        """Factory: create a styled QLabel."""
        lbl = QLabel(text)
        parts = [f"color: {color}", f"font-size: {size}px"]
        if bold: parts.append("font-weight: bold")
        if italic: parts.append("font-style: italic")
        lbl.setStyleSheet("; ".join(parts) + ";")
        if w: lbl.setFixedWidth(w)
        return lbl

    def _progress_bar(self, fmt: str, h: int, color1: str, color2: str) -> QProgressBar:
        """Factory: create a styled progress bar."""
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat(fmt)
        bar.setFixedHeight(h)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background: #0a1628; border: 1px solid #1a2a3a;
                border-radius: 3px; font-size: 9px; color: #94a3b8;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {color1}, stop:1 {color2});
                border-radius: 3px;
            }}
        """)
        return bar

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


