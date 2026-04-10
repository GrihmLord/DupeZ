# app/gui/clumsy_control.py — Main View: Device List + Full Clumsy Disruption Controls
"""Device scanner and per-device disruption control panel.

``ClumsyControlView`` is the primary DupeZ interaction surface: a split-pane
with a device table on the left and full disruption controls (presets,
modules, sliders, macros, profiles, smart-mode, voice, GPC) on the right.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.data_persistence import nickname_manager
from app.firewall.clumsy_network_disruptor import disruption_manager
from app.logs.logger import log_error, log_info
from app.utils.helpers import mask_ip as _log_mask_ip

# Extracted panel widgets
from app.gui.panels.stats_panel import StatsPanel
from app.gui.panels.voice_panel import VoicePanel
from app.gui.panels.gpc_panel import GPCPanel
from app.gui.panels.smart_mode_panel import SmartModePanel, SMART_ENGINE_AVAILABLE

# Profile system
try:
    from app.core.profiles import ProfileManager
    PROFILES_AVAILABLE = True
except ImportError:
    PROFILES_AVAILABLE = False

# Voice control — do NOT call is_voice_available() at module import time.
# It walks into whisper → torch, and torch's c10.dll crashes the interpreter
# with an access violation (WinError 1114) on broken installs — uncatchable
# from Python. The probe happens lazily inside ClumsyControlView instead.
try:
    from app.ai.voice_control import VoiceController, VoiceConfig, is_voice_available  # noqa: F401
    _VOICE_IMPORTABLE = True
except Exception:  # noqa: BLE001
    _VOICE_IMPORTABLE = False
VOICE_AVAILABLE: bool = False  # populated lazily on first view instantiation

# GPC / CronusZEN integration
try:
    from app.gpc.gpc_generator import (GPCGenerator, list_templates,
                                        get_template)
    from app.gpc.device_bridge import DeviceMonitor, scan_devices
    GPC_AVAILABLE = True
except ImportError:
    GPC_AVAILABLE = False

__all__ = ["ClumsyControlView", "PRESETS", "MODULE_DEFS", "CollapsibleCard"]


# ── Collapsible / reorderable card widget ─────────────────────────

_COLLAPSE_HEADER_QSS = (
    "QPushButton { background: rgba(10,15,26,0.55); color: #00f0ff; "
    "font-size: 11px; font-weight: 700; letter-spacing: 1px; "
    "border: 1px solid rgba(30,41,59,0.45); border-radius: 8px; "
    "text-align: left; padding: 8px 12px; } "
    "QPushButton:hover { border-color: rgba(0,240,255,0.25); "
    "background: rgba(10,15,26,0.7); }"
)
_REORDER_BTN_QSS = (
    "QPushButton { background: transparent; color: #475569; "
    "border: none; font-size: 13px; padding: 0; min-width: 20px; } "
    "QPushButton:hover { color: #00f0ff; }"
)


class CollapsibleCard(QWidget):
    """A collapsible, optionally reorderable card section.

    Click the header to expand/collapse.  The ▲/▼ buttons let users
    reorder sections within the parent layout.

    Parameters
    ----------
    title : str
        Section header label (e.g. "MODULES").
    content : QWidget
        The widget to show/hide when toggling.
    parent_layout : QVBoxLayout | None
        If provided, ▲/▼ reorder buttons are shown and wired to swap
        position within this layout.
    collapsed : bool
        Start collapsed (default False — start expanded).
    """

    def __init__(self, title: str, content: QWidget, *,
                 parent_layout: Optional[QVBoxLayout] = None,
                 collapsed: bool = False,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._expanded = not collapsed
        self._parent_layout = parent_layout

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(0)

        # Header row
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)

        arrow = "▼" if self._expanded else "▶"
        self._header_btn = QPushButton(f" {arrow}  {title}")
        self._header_btn.setStyleSheet(_COLLAPSE_HEADER_QSS)
        self._header_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._header_btn.setFixedHeight(34)
        self._header_btn.clicked.connect(self._toggle)
        header_row.addWidget(self._header_btn, 1)

        # Reorder buttons (only if parent_layout given)
        if parent_layout is not None:
            self._btn_up = QPushButton("▲")
            self._btn_up.setStyleSheet(_REORDER_BTN_QSS)
            self._btn_up.setFixedSize(22, 34)
            self._btn_up.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_up.setToolTip("Move section up")
            self._btn_up.clicked.connect(self._move_up)
            header_row.addWidget(self._btn_up)

            self._btn_down = QPushButton("▼")
            self._btn_down.setStyleSheet(_REORDER_BTN_QSS)
            self._btn_down.setFixedSize(22, 34)
            self._btn_down.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_down.setToolTip("Move section down")
            self._btn_down.clicked.connect(self._move_down)
            header_row.addWidget(self._btn_down)

        root.addLayout(header_row)

        # Content area
        self._content = content
        self._content.setVisible(self._expanded)
        root.addWidget(self._content)

    # ── Toggle collapse ──

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        arrow = "▼" if self._expanded else "▶"
        self._header_btn.setText(f" {arrow}  {self._title}")
        self._content.setVisible(self._expanded)

    # ── Reorder within parent layout ──

    def _find_index(self) -> int:
        """Find this widget's index in the parent layout."""
        if self._parent_layout is None:
            return -1
        for i in range(self._parent_layout.count()):
            item = self._parent_layout.itemAt(i)
            if item and item.widget() is self:
                return i
        return -1

    def _move_up(self) -> None:
        idx = self._find_index()
        if idx <= 0 or self._parent_layout is None:
            return
        # Find the previous CollapsibleCard (skip non-card widgets)
        target = idx - 1
        while target >= 0:
            item = self._parent_layout.itemAt(target)
            if item and isinstance(item.widget(), CollapsibleCard):
                break
            target -= 1
        if target < 0:
            return
        self._swap_with(target)

    def _move_down(self) -> None:
        idx = self._find_index()
        if idx < 0 or self._parent_layout is None:
            return
        count = self._parent_layout.count()
        target = idx + 1
        while target < count:
            item = self._parent_layout.itemAt(target)
            if item and isinstance(item.widget(), CollapsibleCard):
                break
            target += 1
        if target >= count:
            return
        self._swap_with(target)

    def _swap_with(self, other_idx: int) -> None:
        """Swap this widget's position with the widget at *other_idx*."""
        my_idx = self._find_index()
        if my_idx < 0 or self._parent_layout is None:
            return
        # Remove both (remove higher index first to preserve indices)
        hi, lo = max(my_idx, other_idx), min(my_idx, other_idx)
        hi_item = self._parent_layout.takeAt(hi)
        lo_item = self._parent_layout.takeAt(lo)
        # Re-insert swapped
        self._parent_layout.insertWidget(lo, hi_item.widget())
        self._parent_layout.insertWidget(hi, lo_item.widget())

# ── Disruption presets ──────────────────────────────────────────────
# Each preset defines a named disruption configuration with the modules
# to enable, their parameter values, and a short user-facing description.

PRESETS: Dict[str, Dict[str, Any]] = {
    "Red Disconnect": {
        "description": "Full disconnect — 95% drop, 2s lag, 1KB/s cap, throttle, disconnect",
        "methods": ["lag", "drop", "bandwidth", "throttle", "disconnect"],
        "params": {
            "lag_delay": 2000, "drop_chance": 95,
            "bandwidth_limit": 1, "bandwidth_queue": 0,
            "throttle_chance": 100, "throttle_frame": 500,
            "throttle_drop": True, "direction": "both",
        }
    },
    "Heavy Lag": {
        "description": "3s lag + 95% drop + 1KB/s cap — brutal sustained delay",
        "methods": ["lag", "drop", "bandwidth"],
        "params": {
            "lag_delay": 3000, "drop_chance": 95,
            "bandwidth_limit": 1, "bandwidth_queue": 0,
            "direction": "both",
        }
    },
    "Light Lag": {
        "description": "800ms lag + 60% drop — moderate disruption",
        "methods": ["lag", "drop"],
        "params": {
            "lag_delay": 800, "drop_chance": 60,
            "direction": "both",
        }
    },
    "God Mode": {
        "description": "Bidirectional pulse-cycle — teleport around, invulnerable, hits land.",
        "methods": ["godmode"],
        "params": {
            # GodModeModule v6 BIDIR: blocks BOTH directions during block phase.
            #   Outbound (device→server): queued → server has stale position → ghost
            #   Inbound (server→device): queued → frozen enemies on screen
            # Staggered flush: inbound first (fresh enemy pos) → stagger delay
            # → outbound (hit reports validated against current positions).
            # TCP/keepalives pass through always to prevent kicks.
            "godmode_pulse": True,
            "godmode_pulse_block_ms": 3000,   # 3s block per cycle
            "godmode_pulse_flush_ms": 400,    # 400ms flush window
            "godmode_flush_stagger_ms": 120,  # inbound→outbound stagger
            "godmode_keepalive_interval_ms": 800,
            "godmode_flush_gamestate_keep": 5,
            "direction": "both",
        }
    },
    "God Mode Aggressive": {
        "description": "Longer block + outbound hit duplication — maximum lethality",
        "methods": ["godmode", "duplicate"],
        "params": {
            # GodModeModule v6 BIDIR: longer block = longer ghost window.
            # 30% extra inbound drop during flush for harder freeze.
            # Stagger 150ms for more time to process fresh positions.
            "godmode_pulse": True,
            "godmode_pulse_block_ms": 4000,   # 4s block per cycle
            "godmode_pulse_flush_ms": 300,    # 300ms flush window
            "godmode_flush_stagger_ms": 150,  # longer stagger for accuracy
            "godmode_keepalive_interval_ms": 800,
            "godmode_drop_inbound_pct": 30,   # drop 30% extra inbound
            "godmode_flush_gamestate_keep": 3, # aggressive culling
            # Duplicate module: outbound only — floods hit reports to server.
            # Engine-level IP direction fix makes this work correctly now.
            "duplicate_chance": 80, "duplicate_count": 5,
            "duplicate_direction": "outbound",
            "direction": "both",
        }
    },
    "Dupe Mode": {
        "description": "Total network blackout for item duplication — 100% drop, zero bandwidth, disconnect",
        "methods": ["disconnect", "drop", "bandwidth"],
        "params": {
            # Unlike Red Disconnect (95% drop + lag for combat), Dupe Mode
            # is a TOTAL bidirectional blackout. No lag (pointless when
            # dropping everything), no throttle (nothing to throttle).
            # Pure hard cut for triggering DayZ inventory rollback.
            "drop_chance": 100,
            "bandwidth_limit": 0, "bandwidth_queue": 0,
            "direction": "both",
        }
    },
    "Desync": {
        "description": "Packet flood + reorder — massive server desync",
        "methods": ["lag", "duplicate", "ood"],
        "params": {
            "lag_delay": 800, "duplicate_chance": 90,
            "duplicate_count": 15, "ood_chance": 80,
            "direction": "both",
        }
    },
    "Custom": {
        "description": "Set your own parameters below",
        "methods": [],
        "params": {}
    }
}

# ── Module definitions ──────────────────────────────────────────────
# Each entry maps a disruption module key to its UI label, description,
# and slider parameter specs: (label, param_key, min, max, default).

def _mdef(key: str, label: str, desc: str,
          params: Optional[List[Tuple]] = None) -> Dict[str, Any]:
    """Build a module definition dict for the controls panel."""
    return {"key": key, "label": label, "desc": desc, "params": params or []}


MODULE_DEFS: List[Dict[str, Any]] = [
    _mdef("lag", "LAG", "Add delay to packets", [("Delay (ms)", "lag_delay", 0, 120000, 500)]),
    _mdef("drop", "DROP", "Drop packets randomly", [("Chance %", "drop_chance", 0, 100, 100)]),
    _mdef("disconnect", "DISCONNECT", "Break connection"),
    _mdef("bandwidth", "BANDWIDTH", "Limit bandwidth", [
        ("Limit (KB/s)", "bandwidth_limit", 0, 1000, 5), ("Queue Size", "bandwidth_queue", 0, 1000, 0)]),
    _mdef("throttle", "THROTTLE", "Throttle packet flow", [
        ("Chance %", "throttle_chance", 0, 100, 80), ("Frame (ms)", "throttle_frame", 0, 1000, 100)]),
    _mdef("duplicate", "DUPLICATE", "Clone packets", [
        ("Chance %", "duplicate_chance", 0, 100, 50), ("Count", "duplicate_count", 1, 50, 5)]),
    _mdef("ood", "OUT OF ORDER", "Reorder packets", [("Chance %", "ood_chance", 0, 100, 50)]),
    _mdef("corrupt", "TAMPER", "Corrupt packet data (limited vs DayZ)", [("Chance %", "tamper_chance", 0, 100, 30)]),
    _mdef("rst", "TCP RST", "Inject RST flags (kicks you too!)", [("Chance %", "rst_chance", 0, 100, 100)]),
]

class ClumsyControlView(QWidget):
    """Main view: Device scanner + per-device Clumsy disruption with full controls."""

    scan_started = pyqtSignal()
    scan_finished = pyqtSignal(list)
    _scan_results_ready = pyqtSignal(list)   # internal: thread-safe scan delivery

    @staticmethod
    def _cb_qss(radius=2, color="#00f0ff", margin=False):
        m = "margin-left: 6px; " if margin else ""
        return (f"QCheckBox {{ {m}color: {color}; font-size: 11px; font-weight: 600; }}"
                f"QCheckBox::indicator {{ width: 16px; height: 16px; }}"
                f"QCheckBox::indicator:unchecked {{ border: 1px solid rgba(51,65,85,0.5); "
                f"background: rgba(15,23,42,0.6); border-radius: {radius}px; }}"
                f"QCheckBox::indicator:unchecked:hover {{ border-color: rgba(0,240,255,0.4); }}"
                f"QCheckBox::indicator:checked {{ border: 1px solid #00f0ff; "
                f"background: #00f0ff; border-radius: {radius}px; }}")
    _MODULE_CB_QSS = _cb_qss.__func__(3)
    _MUTED_QSS = "color: #64748b; font-size: 11px;"
    _MUTED_PAD_QSS = "color: #64748b; font-size: 11px; padding: 4px;"
    _SPINBOX_QSS = ("QSpinBox { background: rgba(15,23,42,0.6); color: #e2e8f0; "
                    "border: 1px solid rgba(51,65,85,0.5); border-radius: 6px; padding: 4px 8px; }")
    _SUBTLE_QSS = "color: #94a3b8; font-size: 10px;"
    _LABEL_BOLD_QSS = "color: #94a3b8; font-size: 11px; font-weight: 700;"
    _SCHED_PURPLE_QSS = "color: #a78bfa; font-size: 11px; font-weight: 600;"
    _SCHED_PINK_QSS = "color: #e879f9; font-size: 11px; font-weight: 600;"
    _RADIO_CB_QSS = _cb_qss.__func__(8, margin=True)
    _SLIDER_QSS = ("QSlider::groove:horizontal { border: 1px solid rgba(51,65,85,0.4); height: 6px; "
                   "background: rgba(15,23,42,0.6); border-radius: 3px; } "
                   "QSlider::handle:horizontal { background: #00f0ff; border: none; "
                   "width: 14px; margin: -4px 0; border-radius: 7px; } "
                   "QSlider::handle:horizontal:hover { background: #33f5ff; "
                   "width: 16px; margin: -5px 0; border-radius: 8px; } "
                   "QSlider::sub-page:horizontal { background: qlineargradient("
                   "x1:0,y1:0,x2:1,y2:0, stop:0 rgba(0,240,255,0.15), "
                   "stop:1 rgba(0,240,255,0.35)); border-radius: 3px; }")
    _COMBO_QSS = ("QComboBox { background: rgba(15,23,42,0.6); color: #e2e8f0; "
                  "border: 1px solid rgba(51,65,85,0.5); "
                  "border-radius: 8px; padding: 7px 12px; font-size: 12px; } "
                  "QComboBox:focus { border-color: rgba(0,240,255,0.5); } "
                  "QComboBox::drop-down { border: none; width: 24px; } "
                  "QComboBox::down-arrow { image: none; border-left: 5px solid transparent; "
                  "border-right: 5px solid transparent; border-top: 5px solid #64748b; } "
                  "QComboBox QAbstractItemView { background: #0c1220; color: #e2e8f0; "
                  "selection-background-color: rgba(0,240,255,0.15); selection-color: #00f0ff; "
                  "border: 1px solid rgba(51,65,85,0.5); border-radius: 8px; padding: 4px; }")
    _CARD_QSS = ("QGroupBox { color: #00f0ff; font-size: 11px; font-weight: 700; "
                 "letter-spacing: 1px; border: 1px solid rgba(30,41,59,0.45); border-radius: 10px; "
                 "margin-top: 14px; padding: 16px 12px 12px 12px; "
                 "background: rgba(10,15,26,0.55); } "
                 "QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; "
                 "letter-spacing: 1px; }")

    def __init__(self, controller: Any = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller

        # Device state
        self.devices: List[Any] = []
        self.selected_ip: Optional[str] = None
        self.selected_ips: Set[str] = set()
        self._disruption_timers: Dict[str, float] = {}
        self._ip_hidden: bool = False
        self._row_checkboxes: List[Tuple[QCheckBox, str]] = []

        # Lazy-initialised by extracted panels
        self._voice_controller: Any = None
        self._gpc_generator: Any = None
        self._gpc_last_source: str = ""
        self._gpc_monitor: Any = None

        # Lazy voice availability probe — first view instantiation.
        # Wrapped broadly because whisper/torch can crash with WinError 1114.
        global VOICE_AVAILABLE
        if _VOICE_IMPORTABLE and not VOICE_AVAILABLE:
            try:
                VOICE_AVAILABLE = bool(is_voice_available())
            except Exception as _exc:  # noqa: BLE001
                log_error(f"ClumsyControlView: is_voice_available() raised {type(_exc).__name__}: {_exc}")
                VOICE_AVAILABLE = False

        self._build_ui()
        self._connect_signals()

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
        self.stats_refresh_timer.timeout.connect(
            lambda: self._stats_panel.refresh() if hasattr(self, '_stats_panel') else None)
        self.stats_refresh_timer.start(1500)

    # ── UI Construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct the full split-pane UI."""
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
        title.setStyleSheet(
            "font-size: 13px; font-weight: 800; color: #00f0ff;"
            " letter-spacing: 2px;")
        header.addWidget(title)
        header.addStretch()

        self.hide_ip_btn = QPushButton("HIDE IPs")
        self.hide_ip_btn.setCheckable(True)
        self.hide_ip_btn.setStyleSheet("""
            QPushButton {
                background: rgba(15,23,42,0.5); color: #94a3b8;
                border: 1px solid rgba(51,65,85,0.4);
                border-radius: 6px; font-size: 10px; font-weight: 700;
                padding: 4px 12px; letter-spacing: 1px;
            }
            QPushButton:checked {
                background: rgba(255,68,68,0.1); color: #ff6b6b;
                border: 1px solid rgba(255,68,68,0.4);
            }
            QPushButton:hover { color: #e2e8f0; border-color: rgba(71,85,105,0.6); }
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
                background-color: rgba(15,23,42,0.6); color: #00f0ff;
                border: 1px solid rgba(51,65,85,0.5);
                padding: 5px 10px; font-size: 11px; border-radius: 6px;
                font-weight: 600;
            }
            QComboBox:focus { border-color: rgba(0,240,255,0.5); }
            QComboBox::drop-down { border: none; width: 22px; }
            QComboBox::down-arrow { image: none; border-left: 4px solid transparent;
                border-right: 4px solid transparent; border-top: 4px solid #64748b; }
            QComboBox QAbstractItemView {
                background-color: #0c1220; color: #e2e8f0;
                selection-background-color: rgba(0,240,255,0.15);
                selection-color: #00f0ff; border: 1px solid rgba(51,65,85,0.5);
                border-radius: 6px; padding: 4px;
            }
        """)
        self.network_combo.currentTextChanged.connect(self._on_network_filter_changed)
        net_filter_row.addWidget(self.network_combo, 1)

        self.multi_target_btn = QPushButton("MULTI")
        self.multi_target_btn.setCheckable(True)
        self.multi_target_btn.setToolTip("Multi-Target Mode — select multiple devices for simultaneous disruption")
        self.multi_target_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #64748b;
                border: 1px solid rgba(30,41,59,0.5);
                padding: 3px 12px; font-size: 10px; font-weight: 700;
                border-radius: 6px; letter-spacing: 0.5px;
            }
            QPushButton:checked {
                background: rgba(168,85,247,0.1); color: #a78bfa;
                border: 1px solid rgba(168,85,247,0.4);
            }
            QPushButton:hover { color: #e2e8f0; border-color: rgba(71,85,105,0.5); }
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
                background-color: rgba(8,12,22,0.8); color: #e2e8f0;
                border: 1px solid rgba(30,41,59,0.5); gridline-color: rgba(30,41,59,0.3);
                border-radius: 8px; font-size: 12px;
            }
            QTableWidget::item {
                padding: 8px 10px; border-bottom: 1px solid rgba(30,41,59,0.2);
            }
            QTableWidget::item:selected {
                background-color: rgba(0,240,255,0.12); color: #ffffff;
            }
            QTableWidget::item:hover {
                background-color: rgba(0,240,255,0.05);
            }
            QTableWidget::item:alternate { background-color: rgba(15,23,42,0.4); }
            QHeaderView::section {
                background-color: rgba(10,15,26,0.9); color: #64748b; padding: 8px 10px;
                border: none; border-bottom: 2px solid rgba(0,240,255,0.12);
                font-weight: 700; font-size: 11px; letter-spacing: 0.5px;
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
            "font-size: 13px; font-weight: 800; color: #ff6b6b; letter-spacing: 2px;"
            " padding: 10px; background: rgba(255,68,68,0.04);"
            " border: 1px solid rgba(255,68,68,0.15); border-radius: 8px;"
        )
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.target_label)

        # Preset selector
        preset_group = self._card("PRESET")
        preset_layout = QVBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet(self._COMBO_QSS)
        self.preset_combo.addItems(PRESETS.keys())
        # Connect ALL combo signals for maximum reliability across PyQt6 versions.
        self.preset_combo.currentIndexChanged.connect(self._on_preset_index_changed)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        self.preset_combo.activated.connect(self._on_preset_index_changed)
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

        # ── Collapsible sections container ──
        # All major sections go into this layout so they can be reordered.
        self._sections_layout = QVBoxLayout()
        self._sections_layout.setSpacing(4)
        right_layout.addLayout(self._sections_layout)

        self._section_preset = CollapsibleCard(
            "PRESET", preset_group,
            parent_layout=self._sections_layout)
        self._sections_layout.addWidget(self._section_preset)

        # ---- SMART MODE: AI AUTO-TUNE (extracted panel) ----
        self._smart_panel = SmartModePanel(self)
        if self._smart_panel.available:
            self._section_smart = CollapsibleCard(
                "AUTO-TUNE / SMART MODE", self._smart_panel,
                parent_layout=self._sections_layout, collapsed=True)
            self._sections_layout.addWidget(self._section_smart)

        # Platform mode toggle — PC Local vs Remote (console/hotspot)
        platform_group = self._card("PLATFORM")
        platform_layout = QHBoxLayout()
        self.pc_local_check = QCheckBox("PC LOCAL")
        self.pc_local_check.setToolTip(
            "Enable when DayZ runs on THIS machine (not a console/remote PC).\n"
            "Uses NETWORK layer instead of NETWORK_FORWARD.\n"
            "Target IP becomes the game server IP, not a device IP.\n"
            "Leave unchecked for PS5, Xbox, or remote PC over hotspot.")
        self.pc_local_check.setStyleSheet(
            "color: #e0e0e0; font-size: 11px; font-weight: bold;")
        self.pc_local_label = QLabel("PS5 / Xbox / Remote PC")
        self.pc_local_label.setStyleSheet("color: #64748b; font-size: 10px;")
        self.pc_local_check.stateChanged.connect(self._on_platform_changed)
        platform_layout.addWidget(self.pc_local_check)
        platform_layout.addStretch()
        platform_layout.addWidget(self.pc_local_label)
        platform_group.setLayout(platform_layout)
        self._section_platform = CollapsibleCard(
            "PLATFORM", platform_group,
            parent_layout=self._sections_layout, collapsed=True)
        self._sections_layout.addWidget(self._section_platform)

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
        self._section_direction = CollapsibleCard(
            "DIRECTION", dir_group,
            parent_layout=self._sections_layout, collapsed=True)
        self._sections_layout.addWidget(self._section_direction)

        # ---- MODULE CONTROLS ----
        # Each module: [enable checkbox] NAME  [param sliders]
        modules_group = self._card("MODULES")
        modules_layout = QVBoxLayout()
        modules_layout.setSpacing(6)

        self.module_checks = {}   # key -> QCheckBox
        self.sliders = {}         # param_key -> QSlider
        self.slider_labels = {}   # param_key -> QLabel (value display)
        self.extra_checks = {}    # key -> QCheckBox (tamper_checksum, throttle_drop)
        self.module_param_widgets = {}  # module_key -> list of child widgets to enable/disable

        for mdef in MODULE_DEFS:
            key = mdef["key"]
            child_widgets = []  # track sliders/labels/extras for this module
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
            desc.setStyleSheet("color: #64748b; font-size: 10px;")
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
                val_lbl.setStyleSheet("color: #00f0ff; font-weight: 700; font-size: 10px;"
                                     " font-family: 'Cascadia Code', 'Consolas', monospace;")
                param_row.addWidget(val_lbl)

                slider.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
                self.sliders[pkey] = slider
                self.slider_labels[pkey] = val_lbl
                child_widgets.extend([plbl, slider, val_lbl])

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
                child_widgets.append(ecb)
                row_layout.addLayout(extra_row)

            # Store child widgets and connect checkbox to enable/disable them
            self.module_param_widgets[key] = child_widgets
            # Initially disable params for unchecked modules
            is_checked = cb.isChecked()
            for w in child_widgets:
                w.setEnabled(is_checked)
                if not is_checked:
                    w.setStyleSheet(w.styleSheet())  # keep style, just disabled
            # Connect toggle signal
            cb.toggled.connect(lambda checked, k=key: self._on_module_toggled(k, checked))

            # Separator line
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("color: rgba(30,41,59,0.3);")
            row_layout.addWidget(sep)

            modules_layout.addWidget(row_widget)

        modules_group.setLayout(modules_layout)
        self._section_modules = CollapsibleCard(
            "MODULES", modules_group,
            parent_layout=self._sections_layout)
        self._sections_layout.addWidget(self._section_modules)

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
        self._section_scheduler = CollapsibleCard(
            "SCHEDULER / MACROS", sched_group,
            parent_layout=self._sections_layout, collapsed=True)
        self._sections_layout.addWidget(self._section_scheduler)

        # ---- LIVE STATS (extracted panel) ----
        self._stats_panel = StatsPanel(self)
        self._section_stats = CollapsibleCard(
            "LIVE STATS", self._stats_panel,
            parent_layout=self._sections_layout, collapsed=True)
        self._sections_layout.addWidget(self._section_stats)

        # ---- VOICE CONTROL (extracted panel) ----
        self._voice_panel = VoicePanel(self)
        self._section_voice = CollapsibleCard(
            "VOICE CONTROL", self._voice_panel,
            parent_layout=self._sections_layout, collapsed=True)
        self._sections_layout.addWidget(self._section_voice)

        # ---- GPC / CRONUS (extracted panel) ----
        self._gpc_panel = GPCPanel(self)
        self._section_gpc = CollapsibleCard(
            "GPC / CRONUS ZEN", self._gpc_panel,
            parent_layout=self._sections_layout, collapsed=True)
        self._sections_layout.addWidget(self._section_gpc)

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
        splitter.setStyleSheet(
            "QSplitter::handle { background: rgba(0,240,255,0.06); width: 1px; }"
            " QSplitter::handle:hover { background: rgba(0,240,255,0.2); }"
        )
        main_layout.addWidget(splitter)

        # Apply Red Disconnect preset on startup (hardest disconnect)
        self._on_preset_changed("Red Disconnect")

    # ── Signal wiring ──────────────────────────────────────────────

    def _connect_signals(self) -> None:
        """Wire all button/table signals to their handlers."""
        self.scan_btn.clicked.connect(self.start_scan)
        self.device_table.itemSelectionChanged.connect(self._on_device_selected)
        self.btn_disrupt.clicked.connect(self._on_disrupt)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        self._scan_results_ready.connect(self._update_device_table)

    # ── Scanning ────────────────────────────────────────────────────

    def start_scan(self) -> None:
        """Trigger a background network scan."""
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

    @staticmethod
    def _get_subnet(ip: str) -> str:
        """Return the /24 subnet prefix of an IPv4 address."""
        parts = ip.split('.')
        if len(parts) == 4:
            return '.'.join(parts[:3])
        return ip

    def _update_device_table(self, devices: list) -> None:
        """Slot: populate device table from scan results."""
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

    def _on_platform_changed(self, state: int) -> None:
        """Update label when PC LOCAL checkbox toggles."""
        if self.pc_local_check.isChecked():
            self.pc_local_label.setText("DayZ on THIS PC — target = server IP")
            self.pc_local_label.setStyleSheet("color: #22d3ee; font-size: 10px;")
        else:
            self.pc_local_label.setText("PS5 / Xbox / Remote PC")
            self.pc_local_label.setStyleSheet("color: #64748b; font-size: 10px;")

    def _on_network_filter_changed(self, text: str) -> None:
        """Refilter device table when network combo changes."""
        self._apply_device_filter()

    def _apply_device_filter(self) -> Any:
        """Rebuild visible rows from ``self.devices`` honouring the network filter."""
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

    def _update_target_label(self) -> None:
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

    def _on_row_checkbox(self, ip: str, checkbox: QCheckBox, state: int) -> None:
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

    def _toggle_ip_visibility(self) -> None:
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
    def _device_context_menu(self, pos) -> None:
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
    def _on_device_selected(self) -> None:
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
        """Return checked module keys plus any preset-only methods.

        Some modules (e.g. ``godmode``) have no GUI checkbox because they
        are preset-activated.  These are injected from the active preset's
        method list so they reach the engine even though no checkbox exists.
        """
        methods = [key for key, cb in self.module_checks.items() if cb.isChecked()]

        # Inject preset methods that have no GUI checkbox (e.g. "godmode")
        preset_name = self.preset_combo.currentText()
        preset = PRESETS.get(preset_name, {})
        for m in preset.get("methods", []):
            if m not in self.module_checks and m not in methods:
                methods.append(m)

        if not methods:
            methods = PRESETS.get(preset_name, {}).get("methods", []) or ["drop", "lag"]
        return methods

    def _end_smart_session(self) -> None:
        """End smart session tracking if active."""
        if SMART_ENGINE_AVAILABLE and getattr(self, '_active_session_id', None):
            self._smart_tracker.end_session(self._active_session_id)
            self._active_session_id = None

    def _invoke_main(self, slot: str, *args) -> None:
        """Thread-safe invokeMethod shorthand — marshals to main thread."""
        q_args = [Q_ARG(object, a) for a in args]
        QMetaObject.invokeMethod(self, slot, Qt.ConnectionType.QueuedConnection, *q_args)

    # ── Disruption actions ────────────────────────────────────────────

    def _collect_params(self) -> Dict[str, Any]:
        """Read all slider + checkbox values into a params dict.

        Also merges per-module direction overrides from the active preset
        (e.g. lag_direction, drop_direction) which have no GUI slider but
        must be passed to the engine.
        """
        params = {}

        # Slider values
        for key, slider in self.sliders.items():
            params[key] = slider.value()

        # Extra checkboxes
        for key, cb in self.extra_checks.items():
            params[key] = cb.isChecked()

        # Platform mode
        params["_network_local"] = self.pc_local_check.isChecked()

        # Direction
        inb = self.dir_inbound.isChecked()
        outb = self.dir_outbound.isChecked()
        if inb and outb:
            params["direction"] = "both"
        elif inb:
            params["direction"] = "inbound"
        else:
            params["direction"] = "outbound"

        # Merge ALL preset params that don't have a corresponding slider or
        # checkbox in the GUI. This catches per-module direction overrides
        # (lag_direction, drop_direction), engine hints (lag_passthrough,
        # lag_preserve_connection), and any other params the preset defines
        # that have no UI control.
        preset_name = self.preset_combo.currentText()
        preset = PRESETS.get(preset_name)
        if preset:
            gui_keys = set(self.sliders.keys()) | set(self.extra_checks.keys()) | {"direction"}
            for k, v in preset.get("params", {}).items():
                if k not in gui_keys:
                    params[k] = v

        return params

    def _on_disrupt(self) -> None:
        """Handle the DISRUPT button press."""
        targets = self._get_targets()
        if not targets:
            QMessageBox.warning(self, "No Target", "Select a device from the list first.")
            return

        methods = self._get_active_methods()
        params = self._collect_params()

        # ── Comprehensive disruption debug ──
        preset_name = self.preset_combo.currentText()
        log_info("=" * 60)
        log_info(f"[DISRUPT] BUTTON PRESSED")
        log_info(f"[DISRUPT] Preset: '{preset_name}'")
        log_info(f"[DISRUPT] Targets: {[_log_mask_ip(t) for t in targets]}")
        log_info(f"[DISRUPT] Methods (from checkboxes): {methods}")

        # Show checked vs unchecked modules
        checked = [k for k, cb in self.module_checks.items() if cb.isChecked()]
        unchecked = [k for k, cb in self.module_checks.items() if not cb.isChecked()]
        log_info(f"[DISRUPT] Checked modules: {checked}")
        log_info(f"[DISRUPT] Unchecked modules: {unchecked}")

        # Show ALL params being sent to engine
        log_info(f"[DISRUPT] ── Full params dict ({len(params)} keys) ──")
        # Group: direction params
        dir_params = {k: v for k, v in sorted(params.items()) if "direction" in k}
        log_info(f"[DISRUPT]   Directions: {dir_params}")
        # Group: module values (sliders)
        for mod_key in methods:
            mod_params = {k: v for k, v in params.items()
                          if k.startswith(mod_key.replace("disconnect", "disconnect"))}
            # Also grab params by common prefixes
            related = {}
            for k, v in params.items():
                if any(k.startswith(p) for p in (mod_key, mod_key[:4])):
                    related[k] = v
            if related:
                log_info(f"[DISRUPT]   {mod_key}: {related}")
        # Group: engine hints (non-slider, non-direction)
        gui_slider_keys = set(self.sliders.keys())
        gui_extra_keys = set(self.extra_checks.keys())
        hint_keys = {k: v for k, v in params.items()
                     if k not in gui_slider_keys
                     and k not in gui_extra_keys
                     and "direction" not in k}
        if hint_keys:
            log_info(f"[DISRUPT]   Engine hints (non-GUI): {hint_keys}")

        # Verify preset params were merged
        preset_cfg = PRESETS.get(preset_name, {})
        preset_params = preset_cfg.get("params", {})
        missing = []
        for k, v in preset_params.items():
            if k not in params:
                missing.append(k)
            elif params[k] != v and k in gui_slider_keys:
                pass  # slider may have been manually adjusted
            elif params[k] != v and k not in gui_slider_keys:
                log_info(f"[DISRUPT]   WARNING: preset param '{k}' expected={v} got={params[k]}")
        if missing:
            log_info(f"[DISRUPT]   MISSING from params: {missing}")
        else:
            log_info(f"[DISRUPT]   All preset params present in engine params ✓")

        log_info(f"[DISRUPT] Controller present: {self.controller is not None}")
        log_info("=" * 60)

        if self.controller:
            failed = []
            for ip in targets:
                success = self.controller.disrupt_device(ip, methods, params)
                if success:
                    self._disruption_timers[ip] = time.time()
                    log_info(f"Disruption started on {_log_mask_ip(ip)}: methods={methods}")
                else:
                    failed.append(ip)

            self._refresh_device_table_status()

            if failed:
                QMessageBox.warning(
                    self, "Partial Failure",
                    f"Could not start disruption on: {', '.join(failed)}\n"
                    "Check admin privileges, WinDivert files, and logs."
                )

    def _on_stop(self) -> None:
        """Stop disruption on selected target(s)."""
        targets = self._get_targets()
        if not targets or not self.controller:
            return
        for ip in targets:
            self.controller.stop_disruption(ip)
            self._disruption_timers.pop(ip, None)
            log_info(f"Disruption stopped on {_log_mask_ip(ip)}")
        self._refresh_device_table_status()
        self._end_smart_session()

    def _on_stop_all(self) -> None:
        """Emergency-stop all active disruptions."""
        if self.controller:
            self.controller.stop_all_disruptions()
            self._disruption_timers.clear()
            log_info("All disruptions stopped")
            self._refresh_device_table_status()
            self._end_smart_session()

    # ── Scheduled / timed disruption + macros ──────────────────────
    def _on_timed_disrupt(self) -> None:
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

    def _on_macro_step_event(self, event: str, ip: str, step_info: dict) -> None:
        """Called from scheduler background thread — marshal to Qt thread."""
        QTimer.singleShot(0, lambda: self._handle_macro_step(event, ip, step_info))

    def _handle_macro_step(self, event: str, ip: str, step_info: dict) -> None:
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

    def _timed_auto_stop(self, targets, duration) -> None:
        """Auto-stop callback — runs on the Qt main thread via QTimer.singleShot."""
        if self.controller:
            for ip in targets:
                self.controller.stop_disruption(ip)
                self._disruption_timers.pop(ip, None)
            log_info(f"Timed disruption ended after {duration}s")
            self._refresh_device_table_status()
            self.sched_status.setText(f"Timed disruption finished ({duration}s)")
            self.sched_status.setStyleSheet(self._MUTED_QSS)

    def _on_run_macro(self) -> None:
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

    def _on_stop_macro(self) -> None:
        """Stop the active macro."""
        if self.controller:
            self.controller.scheduler.stop_macro()
            self.sched_status.setText("Macro stopped")
            self.sched_status.setStyleSheet(self._MUTED_QSS)

    # ── Profile management ──────────────────────────────────────────
    def _on_save_profile(self) -> None:
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

    def _pick_profile(self, title: str, prompt: str, empty_msg: str = "No saved profiles found.") -> Optional[str]:
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

    def _on_load_profile(self) -> None:
        name = self._pick_profile("Load Profile", "Select profile:")
        if not name:
            return
        profile = self._profile_manager.load(name)
        if profile:
            self._apply_config(profile.methods, profile.params,
                               description=profile.description, switch_to_custom=True)
            log_info(f"Profile loaded: {name}")

    def _on_delete_profile(self) -> None:
        name = self._pick_profile("Delete Profile", "Select profile to delete:")
        if not name:
            return
        confirm = QMessageBox.question(
            self, "Confirm Delete", f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            self._profile_manager.delete(name)
            log_info(f"Profile deleted: {name}")

    def _on_export_profile(self) -> None:
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

    def _on_import_profile(self) -> None:
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

    # ── Smart mode panel bridges ────────────────────────────────────
    @pyqtSlot(object, object)
    def _panel_smart_update_ui(self, profile, rec) -> None:
        self._smart_panel.update_ui(profile, rec)

    @pyqtSlot(object, object)
    def _panel_smart_apply_and_disrupt(self, profile, rec) -> None:
        self._smart_panel.apply_and_disrupt(profile, rec)

    @pyqtSlot(object)
    def _panel_smart_apply_llm_result(self, result) -> None:
        self._smart_panel.apply_llm_result(result)

    def _on_module_toggled(self, module_key: str, checked: bool) -> None:
        """Enable/disable parameter widgets when a module checkbox is toggled."""
        widgets = self.module_param_widgets.get(module_key, [])
        for w in widgets:
            w.setEnabled(checked)

    def _sync_param_widget_states(self) -> None:
        """Sync all module parameter widgets enabled/disabled to checkbox state."""
        for key, cb in self.module_checks.items():
            widgets = self.module_param_widgets.get(key, [])
            checked = cb.isChecked()
            for w in widgets:
                w.setEnabled(checked)

    # Unified config application (presets, profiles, AI, voice all use this)
    def _apply_config(self, methods: list, params: dict,
                      description: str = "", switch_to_custom: bool = False) -> None:
        """Apply a disruption config to all UI controls.

        Used by presets, profiles, AI recommendations, and voice commands.
        """
        # Guard: module_checks may not exist yet during early init
        if not hasattr(self, 'module_checks') or not self.module_checks:
            return

        # Toggle module checkboxes to match preset methods
        for key, cb in self.module_checks.items():
            should_check = key in methods
            cb.blockSignals(True)
            cb.setChecked(should_check)
            cb.blockSignals(False)

        # Build mapping: slider param key → (parent module key, default value)
        _slider_defaults = {}
        for mdef in MODULE_DEFS:
            for _label, pkey, _lo, _hi, default in mdef["params"]:
                _slider_defaults[pkey] = (mdef["key"], default)

        # Set slider values from params; reset unchecked modules to defaults
        for key, slider in self.sliders.items():
            if key in params:
                val = int(params[key])
                val = max(slider.minimum(), min(slider.maximum(), val))
                slider.setValue(val)
                if key in self.slider_labels:
                    self.slider_labels[key].setText(str(val))
            elif key in _slider_defaults:
                parent_mod, default_val = _slider_defaults[key]
                if parent_mod not in methods:
                    slider.setValue(int(default_val))
                    if key in self.slider_labels:
                        self.slider_labels[key].setText(str(int(default_val)))

        # Direction checkboxes
        direction = params.get("direction", "both")
        self.dir_inbound.setChecked(direction in ("inbound", "both"))
        self.dir_outbound.setChecked(direction in ("outbound", "both"))

        # Extra checkboxes (tamper_checksum, throttle_drop, etc.)
        # Reset to False when preset doesn't specify them, so they don't bleed
        for key, cb in self.extra_checks.items():
            cb.setChecked(bool(params.get(key, False)))

        if switch_to_custom:
            idx = self.preset_combo.findText("Custom")
            if idx >= 0:
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentIndex(idx)
                self.preset_combo.blockSignals(False)
        if description:
            self.preset_desc.setText(description)

        # Enable/disable parameter widgets based on checkbox state
        self._sync_param_widget_states()

        # Force full UI repaint to ensure checkbox visuals sync
        self.update()

    def _apply_recommendation(self, rec) -> None:
        """Apply a DisruptionRecommendation to the manual controls."""
        self._apply_config(rec.methods, rec.params,
                           description=rec.description, switch_to_custom=True)

    # ── Presets ──────────────────────────────────────────────────────

    _last_applied_preset: str = ""  # dedup guard for triple-signal

    def _on_preset_index_changed(self, index: int) -> None:
        """Fires when the combo box index changes or user activates an item."""
        self._last_applied_preset = ""  # reset dedup so re-select works
        preset_name = self.preset_combo.itemText(index) if index >= 0 else ""
        self._on_preset_changed(preset_name)

    def _on_preset_changed(self, preset_name: str) -> None:
        if not preset_name:
            return
        # Dedup: all three signals may fire for same selection
        if preset_name == self._last_applied_preset:
            return
        self._last_applied_preset = preset_name

        preset = PRESETS.get(preset_name)
        if preset is None:
            print(f"[PRESET] Unknown preset: '{preset_name}'")
            return

        methods = preset.get("methods", [])
        params = preset.get("params", {})
        description = preset.get("description", "")
        self._apply_config(methods, params, description=description)

    # ── Status refresh ──────────────────────────────────────────────

    def _refresh_disruption_status(self) -> None:
        """Update the engine status label from the disruption manager."""
        _qss = lambda c, bold=False: f"color: {c}; font-size: 11px; padding: 4px;{' font-weight: bold;' if bold else ''}"
        try:
            status = disruption_manager.get_status()
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


    def _refresh_device_table_status(self) -> None:
        disrupted = self.controller.get_disrupted_devices() if self.controller else []
        for row in range(self.device_table.rowCount()):
            ip_item = self.device_table.item(row, 1)
            status_item = self.device_table.item(row, 5)
            if ip_item and status_item:
                ip = ip_item.data(Qt.ItemDataRole.UserRole) or ip_item.text()
                text, color = ("DISRUPTED", "#ff4444") if ip in disrupted else ("ONLINE", "#00ff88")
                status_item.setText(text)
                status_item.setForeground(QColor(color))

    def _update_session_timers(self) -> None:
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

    # ---- Panel bridge methods (thread-safe _invoke_main targets) ----
    # These are called by extracted panels via _invoke_main to marshal
    # background-thread callbacks onto the Qt main thread.

    @pyqtSlot(object)
    def _panel_voice_init_done(self, ok) -> None:
        self._voice_panel.voice_init_done(ok)

    @pyqtSlot(object)
    def _panel_voice_listening_changed(self, listening) -> None:
        self._voice_panel.update_listen_btn(listening)

    @pyqtSlot(object)
    def _panel_voice_apply_command(self, config) -> None:
        self._voice_panel.apply_command(config)

    @pyqtSlot(object)
    def _panel_voice_set_status(self, msg) -> None:
        self._voice_panel.set_status(msg)

    @pyqtSlot(object)
    def _panel_gpc_set_device_label(self, msg) -> None:
        self._gpc_panel.set_device_label(msg)

    # ---- REMOVED: Old inline panel methods ----
    # _build_stats_panel, _refresh_stats_panel, _format_count,
    # _build_voice_panel and voice handlers,
    # _build_gpc_panel and GPC handlers
    # have been extracted to app/gui/panels/

    # ── Widget factory helpers ────────────────────────────────────────

    def _card(self, title: str) -> QGroupBox:
        """Create a themed ``QGroupBox`` card."""
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
                background: rgba(15,23,42,0.5); border: 1px solid rgba(30,41,59,0.4);
                border-radius: 4px; font-size: 9px; color: #94a3b8;
                text-align: center; font-weight: 600;
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
                border-radius: 8px;
                font-weight: 700;
                font-size: 12px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background: {color};
                color: #050810;
            }}
            QPushButton:pressed {{
                background: {color};
                color: #050810;
                border: 2px solid {color};
            }}
            QPushButton:disabled {{
                background: rgba(15,23,42,0.4);
                color: #475569;
                border: 1px solid rgba(30,41,59,0.3);
            }}
        """


