# app/gui/dashboard.py — DupeZ Dashboard (3-View Architecture)
"""Main application window for DupeZ.

``DupeZDashboard`` is a frameless ``QMainWindow`` with a custom title bar,
four sidebar-navigated views (Clumsy Control, iZurvive Map, Account Tracker,
Network Tools), a system tray integration, and a plugin panel extension
point.
"""

from __future__ import annotations

import gc
import html
import os
import threading
import webbrowser
from typing import Any, List, Optional

from PyQt6.QtCore import (
    Q_ARG,
    QMetaObject,
    QPoint,
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QAction, QCursor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.core.updater import CURRENT_VERSION
from app.gui.clumsy_control import ClumsyControlView
from app.gui.dayz_account_tracker import DayZAccountTracker
from app.gui.dayz_map_gui_new import DayZMapGUI, consume_prewarmed_map_gui
from app.gui.disruption_hotkeys import DisruptionHotkeys
from app.gui.network_tools import NetworkToolsView
from app.gui.panels.help_panel import HelpPanel
from app.gui.settings_dialog import SettingsDialog
from app.logs.logger import log_error, log_info, log_warning
from app.utils.helpers import is_admin

try:
    from app.gui.hotkey import KEYBOARD_AVAILABLE, hotkey_manager
except ImportError:
    KEYBOARD_AVAILABLE = False
    hotkey_manager = None

__all__ = ["DupeZDashboard"]

# ── Lazy admin check (avoid side-effect at import time) ─────────────

_IS_ADMIN: Optional[bool] = None


def _get_is_admin() -> bool:
    """Return cached admin/root status."""
    global _IS_ADMIN
    if _IS_ADMIN is None:
        _IS_ADMIN = is_admin()
    return _IS_ADMIN


# ── Icon discovery ──────────────────────────────────────────────────

_ICON_PATHS: List[str] = [
    "app/resources/dupez.ico",
    "app/resources/dupez.png",
    "app/assets/icon.ico",
]


def _find_icon() -> str:
    """Return first existing icon path, or empty string."""
    return next((p for p in _ICON_PATHS if os.path.exists(p)), "")


# ── QSS constants ──────────────────────────────────────────────────

_MAIN_CONTAINER_QSS: str = """
    #main_container {
        background-color: #050810;
        border: 1px solid rgba(15, 26, 46, 0.6);
        border-radius: 10px;
    }
"""

_TITLE_BAR_QSS: str = """
    #title_bar {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #040710, stop:0.5 #060a14, stop:1 #040710);
        border-bottom: 1px solid rgba(0, 240, 255, 0.06);
    }
"""

_MENUBAR_QSS: str = """
    QMenuBar {
        background-color: #060a14; color: #94a3b8;
        border-bottom: 1px solid rgba(30, 41, 59, 0.4); padding: 2px 6px;
        font-size: 12px; font-weight: 500;
    }
    QMenuBar::item { padding: 5px 12px; background: transparent; border-radius: 6px; }
    QMenuBar::item:selected { background: rgba(0, 240, 255, 0.1); color: #e2e8f0; }
    QMenu { background-color: #0c1220; color: #e2e8f0; border: 1px solid rgba(51,65,85,0.5);
        border-radius: 8px; padding: 6px; }
    QMenu::item { padding: 8px 28px 8px 16px; border-radius: 6px; margin: 1px 4px; }
    QMenu::item:selected { background: rgba(0, 240, 255, 0.12); color: #00f0ff; }
    QMenu::separator { height: 1px; background: rgba(30,41,59,0.5); margin: 6px 12px; }
"""

_TRAY_MENU_QSS: str = """
    QMenu {
        background: #0c1220; color: #e2e8f0;
        border: 1px solid rgba(51, 65, 85, 0.5); border-radius: 8px; padding: 6px;
    }
    QMenu::item { padding: 8px 28px 8px 16px; border-radius: 6px; margin: 1px 4px; }
    QMenu::item:selected { background: rgba(0, 240, 255, 0.12); color: #00f0ff; }
    QMenu::separator { height: 1px; background: rgba(30,41,59,0.5); margin: 6px 12px; }
"""

_NAV_BTN_QSS: str = """
    QPushButton {
        background: transparent; border: none; border-radius: 10px;
        padding: 0px; margin: 0px;
        min-width: 40px; max-width: 40px;
        min-height: 40px; max-height: 40px;
        font-size: 16px;
    }
    QPushButton:hover { background: rgba(0, 240, 255, 0.08); }
    QPushButton:checked {
        background: rgba(0, 240, 255, 0.12);
        border-left: 3px solid #00f0ff;
        border-radius: 6px;
    }
"""

_ABOUT_DLG_QSS: str = """
    QDialog {
        background-color: #060913; border: 1px solid rgba(0, 240, 255, 0.3);
        border-radius: 14px;
    }
    QLabel { background: transparent; color: #cbd5e1; }
"""

_CLOSE_BTN_QSS: str = (
    "QPushButton { background: transparent; color: #475569;"
    " border: none; font-size: 16px; font-weight: bold; border-radius: 6px; }"
    " QPushButton:hover { color: #ff4444; background: rgba(255,68,68,0.1); }"
)

_GH_BTN_QSS: str = """
    QPushButton {
        background: rgba(0, 240, 255, 0.06); color: #00f0ff;
        border: 1px solid rgba(0, 240, 255, 0.35);
        border-radius: 8px; padding: 10px 28px; font-weight: 600; font-size: 12px;
    }
    QPushButton:hover { background: rgba(0, 240, 255, 0.15); border-color: rgba(0,240,255,0.5); }
"""

_FALLBACK_THEME_QSS: str = """
    QMainWindow, QWidget { background-color: #050810; color: #e2e8f0; }
    QPushButton {
        background: rgba(30,41,59,0.7); color: #f1f5f9;
        border: 1px solid rgba(51,65,85,0.6); padding: 8px 16px; border-radius: 8px;
    }
    QPushButton:hover { background: rgba(51,65,85,0.7); }
"""

_WND_BTN_QSS_TEMPLATE: str = """
    QPushButton {{
        background: transparent; color: {color}; border: none;
        font-size: {size}; font-weight: bold; padding: 0;
        min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px;
        border-radius: 8px;
    }}
    QPushButton:hover {{ background: {hover_bg}; }}
"""

# ── Cursor map for frameless resize ────────────────────────────────

_RESIZE_CURSOR_MAP = {
    "left": Qt.CursorShape.SizeHorCursor,
    "right": Qt.CursorShape.SizeHorCursor,
    "top": Qt.CursorShape.SizeVerCursor,
    "bottom": Qt.CursorShape.SizeVerCursor,
    "left+top": Qt.CursorShape.SizeFDiagCursor,
    "right+bottom": Qt.CursorShape.SizeFDiagCursor,
    "right+top": Qt.CursorShape.SizeBDiagCursor,
    "left+bottom": Qt.CursorShape.SizeBDiagCursor,
}

_RESIZE_MARGIN: int = 6


# ═══════════════════════════════════════════════════════════════════
#  DupeZDashboard
# ═══════════════════════════════════════════════════════════════════

class DupeZDashboard(QMainWindow):
    """DupeZ main window — sidebar-navigated 4-view architecture.

    Views: Clumsy Control | iZurvive Map | Account Tracker | Network Tools.
    Supports system-tray minimisation, global hotkey toggle, and plugin
    panel extensions.
    """

    _dashboard_snapshot_ready = pyqtSignal(int, int, object)
    _dashboard_snapshot_failed = pyqtSignal(int, str)
    _cut_chain_event_ready = pyqtSignal(int, object)
    _update_check_ready = pyqtSignal(int, object)
    _update_progress_ready = pyqtSignal(int, object, object)
    _update_download_ready = pyqtSignal(int, bool, str)
    _update_prepared_ready = pyqtSignal(int, object)

    def __init__(self, controller: Any = None) -> None:
        super().__init__()
        from app.core.overlay_server import OverlayServerOwner

        self.controller = controller
        self.overlay_server_owner = OverlayServerOwner(controller)
        self._minimize_to_tray: bool = True
        self._force_quit: bool = False
        self._hotkeys_closing = False
        self._dashboard_poll_generation = 0
        self._dashboard_poll_in_flight = False
        self._device_count_snapshot = 0
        self._disrupted_devices_snapshot: frozenset[str] = frozenset()
        self._cut_chain_ui_generation = 0
        self._dashboard_snapshot_ready.connect(
            self._apply_dashboard_status_snapshot
        )
        self._dashboard_snapshot_failed.connect(
            self._apply_dashboard_status_error
        )
        self._cut_chain_event_ready.connect(self._on_cut_chain_event)
        self._setup_update_flow()

        # Frameless drag/resize state
        self._drag_pos: Optional[QPoint] = None
        self._resizing: bool = False
        self._resize_edge: Optional[str] = None
        self._start_geometry = None

        self._setup_ui()
        self._apply_startup_health()
        self._setup_menu()
        self._setup_status_bar()
        self._setup_tray()
        self._setup_tray_hotkey()
        self._setup_disruption_hotkeys()
        self._connect_signals()
        self._register_gui_toast()
        self._check_npcap_on_startup()

        # Periodic timers
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start(3000)

        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_header_stats)
        self._stats_timer.start(2000)

    # ── UI Construction ─────────────────────────────────────────────

    def _setup_ui(self) -> None:
        """Build the complete UI hierarchy."""
        admin_text = "ADMIN " if _get_is_admin() else ""
        self.setWindowTitle(f"{admin_text}DupeZ v{CURRENT_VERSION}")
        icon_path = _find_icon()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        screen = self.screen().availableGeometry()
        w, h = int(screen.width() * 0.85), int(screen.height() * 0.85)
        self.setGeometry(
            (screen.width() - w) // 2, (screen.height() - h) // 2, w, h,
        )
        self.setMinimumSize(900, 600)
        self._apply_theme()

        # Central widget
        central = QWidget()
        central.setObjectName("main_container")
        central.setStyleSheet(_MAIN_CONTAINER_QSS)
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self._build_title_bar(main_layout)
        self._build_menubar(main_layout)
        self._build_header(main_layout)
        self._build_content_area(main_layout)

        self.switch_view(0)

    def _build_title_bar(self, parent_layout: QVBoxLayout) -> None:
        """Custom frameless title bar with min/max/close buttons."""
        self.title_bar = QWidget()
        self.title_bar.setObjectName("title_bar")
        self.title_bar.setFixedHeight(36)
        self.title_bar.setStyleSheet(_TITLE_BAR_QSS)

        tb = QHBoxLayout(self.title_bar)
        tb.setContentsMargins(12, 0, 8, 0)
        tb.setSpacing(8)

        if _get_is_admin():
            admin_tag = QLabel("ADMIN")
            admin_tag.setStyleSheet(
                "color: #fbbf24; font-size: 10px; font-weight: bold; background: transparent;"
            )
            tb.addWidget(admin_tag)

        title_label = QLabel(f"DupeZ v{CURRENT_VERSION}")
        title_label.setStyleSheet(
            "color: #475569; font-size: 11px; font-weight: 600;"
            " letter-spacing: 1.5px; background: transparent;"
        )
        tb.addWidget(title_label)
        tb.addStretch()

        # Window control buttons
        wnd_btn_base = "rgba(255,255,255,0.08)"
        for attr, char, hover_bg, handler in [
            ("btn_minimize", "\u2014", wnd_btn_base, self.showMinimized),
            ("btn_maximize", "\u25a1", wnd_btn_base, self._toggle_maximize),
            ("btn_close", "\u2715", "rgba(255,50,50,0.6)", self.close),
        ]:
            btn = QPushButton(char)
            btn.setStyleSheet(
                _WND_BTN_QSS_TEMPLATE.format(
                    color="#64748b", size="14px", hover_bg=hover_bg,
                ),
            )
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(handler)
            btn.setAccessibleName(attr.removeprefix("btn_").capitalize())
            setattr(self, attr, btn)

        tb.addWidget(self.btn_minimize)
        tb.addWidget(self.btn_maximize)
        tb.addWidget(self.btn_close)
        parent_layout.addWidget(self.title_bar)

    def _build_menubar(self, parent_layout: QVBoxLayout) -> None:
        """Embedded custom menu bar (below title bar, not native)."""
        self._custom_menubar = QMenuBar()
        self._custom_menubar.setStyleSheet(_MENUBAR_QSS)
        parent_layout.addWidget(self._custom_menubar)

    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        """Logo + status indicator + CPU/RAM gauges."""
        header = QWidget()
        header.setObjectName("header_bar")
        header.setFixedHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 6, 18, 6)

        logo = QLabel("DUPEZ")
        logo.setStyleSheet(
            "font-size: 18px; font-weight: 800; color: #00f0ff;"
            " letter-spacing: 3px; background: transparent;"
        )
        hl.addWidget(logo)

        self.status_indicator = QLabel("\u25cf  CONNECTED")
        self.status_indicator.setAccessibleName("Application connection status")
        self.status_indicator.setStyleSheet(
            "color: #00ff88; font-weight: 700; font-size: 11px;"
            " letter-spacing: 0.5px; background: transparent;"
        )
        hl.addWidget(self.status_indicator)
        hl.addStretch()

        sys_qss = (
            "color: #64748b; font-size: 11px; font-family: 'Cascadia Code', 'Consolas', monospace;"
            " background: transparent;"
        )
        self.cpu_label = QLabel("CPU: 0%")
        self.cpu_label.setStyleSheet(sys_qss)
        self.ram_label = QLabel("RAM: 0%")
        self.ram_label.setStyleSheet(sys_qss)
        hl.addWidget(self.cpu_label)
        hl.addSpacing(16)
        hl.addWidget(self.ram_label)

        parent_layout.addWidget(header)

    def _apply_startup_health(self) -> None:
        """Surface controller recovery-safe mode in the persistent header."""
        if self.controller is None or not hasattr(
            self.controller,
            "get_startup_health",
        ):
            return
        health = self.controller.get_startup_health()
        if not health.get("recovery_blocked"):
            return
        self.status_indicator.setText("●  SAFE MODE — NETWORK DISABLED")
        self.status_indicator.setStyleSheet(
            "color: #fbbf24; font-weight: 700; font-size: 11px;"
            " letter-spacing: 0.5px; background: transparent;"
        )
        self.status_indicator.setToolTip(str(health.get("message", "")))

    def _build_content_area(self, parent_layout: QVBoxLayout) -> None:
        """Sidebar rail + stacked view container."""
        content = QWidget()
        cl = QHBoxLayout(content)
        cl.setSpacing(0)
        cl.setContentsMargins(0, 0, 0, 0)

        # Sidebar rail
        self.sidebar_rail = QWidget()
        self.sidebar_rail.setObjectName("sidebar_rail")
        self.sidebar_rail.setFixedWidth(58)
        sl = QVBoxLayout(self.sidebar_rail)
        sl.setContentsMargins(0, 12, 0, 12)
        sl.setSpacing(6)

        self.btn_clumsy = self._nav_btn("\U0001f3af", "Clumsy Control")
        self.btn_map = self._nav_btn("\U0001f5fa\ufe0f", "iZurvive Map")
        self.btn_accounts = self._nav_btn("\U0001f464", "Account Tracker")
        self.btn_nettools = self._nav_btn("\U0001f4e1", "Network Tools")
        self.btn_help = self._nav_btn("\U0001f680", "Getting Started")

        self.nav_buttons: List[QPushButton] = [
            self.btn_clumsy, self.btn_map, self.btn_accounts, self.btn_nettools,
            self.btn_help,
        ]
        # Add main nav buttons
        for idx, btn in enumerate(self.nav_buttons[:-1]):
            btn.clicked.connect(lambda _checked, i=idx: self.switch_view(i))
            sl.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)

        sl.addStretch()

        # Help button pinned to bottom of sidebar
        help_idx = len(self.nav_buttons) - 1
        self.btn_help.clicked.connect(lambda _checked, i=help_idx: self.switch_view(i))
        sl.addWidget(self.btn_help, 0, Qt.AlignmentFlag.AlignHCenter)

        cl.addWidget(self.sidebar_rail)

        # Stacked views
        self.view_stack = QStackedWidget()
        self.clumsy_view = ClumsyControlView(controller=self.controller)
        # Adopt the splash-prewarmed map widget if main.py built one.
        # Fallback to a cold construction so dashboard still builds
        # cleanly when prewarm was skipped or failed.
        self.map_view = consume_prewarmed_map_gui() or DayZMapGUI()
        map_status_signal = getattr(
            self.map_view,
            "webengineStatusChanged",
            None,
        )
        if (
            map_status_signal is not None
            and hasattr(map_status_signal, "connect")
        ):
            map_status_signal.connect(self._on_map_webengine_status)
        self.accounts_view = DayZAccountTracker()
        # NetworkToolsView adopts the AI / Smart Ops and GPC tabs built inside
        # ClumsyControlView. Panels stay owned by clumsy_view so their event
        # handlers (selected_ip, disrupt, etc.) keep working after reparenting.
        ai_tab = getattr(self.clumsy_view, "_ai_panel", None)
        gpc_tab = getattr(self.clumsy_view, "_gpc_panel", None)
        lan_cut_tab = getattr(self.clumsy_view, "_lan_cut_panel", None)
        self.nettools_view = NetworkToolsView(
            controller=self.controller, ai_tab=ai_tab, gpc_tab=gpc_tab,
            lan_cut_tab=lan_cut_tab,
        )
        self.help_view = HelpPanel()
        for view in (self.clumsy_view, self.map_view,
                     self.accounts_view, self.nettools_view,
                     self.help_view):
            self.view_stack.addWidget(view)

        # Plugin panels (extends sidebar + view stack)
        self._load_plugin_panels(sl)

        cl.addWidget(self.view_stack, 1)
        parent_layout.addWidget(content, 1)

    @staticmethod
    def _nav_btn(icon: str, tooltip: str) -> QPushButton:
        """Create a sidebar navigation button."""
        btn = QPushButton(icon)
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        btn.setAccessibleDescription(f"Open the {tooltip} view")
        btn.setCheckable(True)
        btn.setFixedSize(40, 40)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFont(QFont("Segoe UI Emoji", 16))
        btn.setObjectName("nav_btn")
        btn.setProperty("class", "nav-button")
        btn.setStyleSheet(_NAV_BTN_QSS)
        return btn

    # ── View switching ──────────────────────────────────────────────

    def switch_view(self, index: int) -> None:
        """Activate the view at *index* and update sidebar selection."""
        self.view_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        if index == 1:
            status = str(
                getattr(self.map_view, "webengine_status", "unavailable")
            )
            if status == "ready" and getattr(
                self.map_view, "webengine_ready", False
            ):
                log_info("Map: dashboard view active with WebEngine ready")
            elif status in {"deferred", "initializing", "loading"}:
                log_info(f"Map: dashboard view active while WebEngine is {status}")
            else:
                log_error("Map: dashboard view active without WebEngine")

    def _on_map_webengine_status(self, status: str) -> None:
        """Record actual navigation readiness, including async failures."""

        normalized = str(status)
        if normalized == "ready":
            log_info("Map: dashboard WebEngine navigation ready")
            if self.view_stack.currentIndex() == 1:
                log_info("Map: dashboard view active with WebEngine ready")
        elif normalized in {"failed", "crashed", "unavailable"}:
            log_error(f"Map: dashboard WebEngine state is {normalized}")

    # ── Plugin panels ───────────────────────────────────────────────

    def _load_plugin_panels(self, sidebar_layout: QVBoxLayout) -> None:
        """Discover and mount UI-panel plugins into sidebar + view stack."""
        if not self.controller or not hasattr(self.controller, "plugin_loader"):
            return
        try:
            ui_plugins = self.controller.plugin_loader.get_ui_panel_plugins()
            if not ui_plugins:
                return

            separator = QLabel("\u2500" * 4)
            separator.setStyleSheet("color: #1e293b; font-size: 8px;")
            separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sidebar_layout.addWidget(separator)

            for loaded in ui_plugins:
                try:
                    info = loaded.instance.get_panel_info()
                    widget = loaded.instance.create_widget(parent=self.view_stack)
                    if widget is None:
                        continue
                    view_idx = self.view_stack.count()
                    self.view_stack.addWidget(widget)

                    btn = self._nav_btn(
                        info.get("icon", "\U0001f50c"),
                        info.get("tooltip", loaded.name),
                    )
                    btn.clicked.connect(
                        lambda _checked, i=view_idx: self.switch_view(i),
                    )
                    self.nav_buttons.append(btn)
                    sidebar_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
                    log_info(f"Plugin UI panel loaded: {loaded.name}")
                except Exception as exc:
                    log_error(f"Failed to load plugin UI panel '{loaded.name}': {exc}")
        except Exception as exc:
            log_error(f"Plugin panel loading error: {exc}")

    # ── Header stats ────────────────────────────────────────────────

    def _update_header_stats(self) -> None:
        """Refresh CPU / RAM labels from psutil."""
        try:
            import psutil
            self.cpu_label.setText(f"CPU: {psutil.cpu_percent():.0f}%")
            self.ram_label.setText(f"RAM: {psutil.virtual_memory().percent:.0f}%")
        except Exception:
            pass

    # ── System tray ─────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        """Initialise system-tray icon with context menu."""
        self.tray_icon: Optional[QSystemTrayIcon] = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log_info("System tray not available on this platform")
            self._minimize_to_tray = False
            return

        self.tray_icon = QSystemTrayIcon(self)
        icon_path = _find_icon()
        self.tray_icon.setIcon(QIcon(icon_path) if icon_path else self.windowIcon())
        self.tray_icon.setToolTip("DupeZ \u2014 No active disruptions")

        tray_menu = QMenu()
        tray_menu.setStyleSheet(_TRAY_MENU_QSS)

        self.tray_action_show = QAction("Show DupeZ", self)
        self.tray_action_show.triggered.connect(self._tray_show_window)
        tray_menu.addAction(self.tray_action_show)
        tray_menu.addSeparator()

        self.tray_action_status = QAction("Disruptions: 0", self)
        self.tray_action_status.setEnabled(False)
        tray_menu.addAction(self.tray_action_status)

        self.tray_action_stop_all = QAction("Stop All Disruptions", self)
        self.tray_action_stop_all.triggered.connect(self._stop_all_disruptions)
        tray_menu.addAction(self.tray_action_stop_all)
        tray_menu.addSeparator()

        tray_action_quit = QAction("Quit", self)
        tray_action_quit.triggered.connect(self._tray_quit)
        tray_menu.addAction(tray_action_quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()
        log_info("System tray icon initialized")

    def _setup_tray_hotkey(self) -> None:
        """Register Ctrl+Shift+D to toggle window visibility."""
        if not self._minimize_to_tray:
            return
        if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
            return
        if not KEYBOARD_AVAILABLE or hotkey_manager is None:
            return
        try:
            listener = hotkey_manager.add_listener(
                "tray_toggle",
                callback=self._hotkey_toggle_visibility,
                keys=["ctrl+shift+d"],
                config={"cooldown": 0.5, "enabled": True, "trigger_on_release": True},
            )
            if listener.start():
                log_info("Tray hotkey registered: Ctrl+Shift+D")
            else:
                log_warning(f"Tray hotkey unavailable: {listener.last_error}")
        except Exception as exc:
            log_error(f"Failed to register tray hotkey: {exc}")

    def _setup_disruption_hotkeys(self) -> None:
        self._disruption_hotkeys = DisruptionHotkeys(
            self, manager=hotkey_manager,
            callbacks={
                "start": self._start_disruption_hotkey,
                "stop": self._stop_all_disruptions,
                "panic": self._kill_switch_panic,
            },
            backend_available=(
                KEYBOARD_AVAILABLE
                and os.environ.get("QT_QPA_PLATFORM", "").strip().lower() != "offscreen"
            ),
        )
        # The panel owns its existing clicked handlers. Cancel queued global
        # Starts on press, before those handlers can restore network state.
        for name in ("btn_stop", "btn_stop_all"):
            button = getattr(self.clumsy_view, name, None)
            if button is not None:
                button.pressed.connect(self._disruption_hotkeys.cancel_pending_starts)
        self._apply_disruption_hotkeys()

    def _apply_disruption_hotkeys(self) -> None:
        if getattr(self, "_hotkeys_closing", False):
            return
        settings = getattr(getattr(self.controller, "state", None), "settings", None)
        if not self._disruption_hotkeys.configure(settings):
            self.statusBar().showMessage(
                "Some global hotkeys are unavailable — press F1 for actual binding status", 10000
            )
        self._sync_panic_shortcut()

    def _sync_panic_shortcut(self) -> None:
        action = getattr(self, "_panic_stop_action", None)
        if action is None:
            return
        owner = getattr(self, "_disruption_hotkeys", None)
        shared_chord = owner is not None and "ctrl+alt+x" in owner.active_keys("panic")
        # Keep the menu action usable, but do not invoke it twice for one chord.
        action.setShortcut("" if shared_chord else "Ctrl+Alt+X")

    def _start_disruption_hotkey(self) -> None:
        """Use the normal selected-target action, only in a ready GUI session."""
        if (
            getattr(self, "_hotkeys_closing", False)
            or getattr(self, "_update_launch_in_flight", False)
            or getattr(self, "_update_cleanup_confirmed", False)
            or not self.isEnabled()
            or QApplication.activeModalWidget() is not None
        ):
            self.statusBar().showMessage("Global Start ignored while the application is busy", 5000)
            return
        self.clumsy_view._on_disrupt()

    def _stop_global_hotkeys(self) -> bool:
        """Disarm queued starts before independent hook-removal attempts."""
        self._hotkeys_closing = True
        confirmed = True
        owner = getattr(self, "_disruption_hotkeys", None)
        try:
            if owner is not None and not owner.close():
                confirmed = False
        except Exception as exc:
            confirmed = False
            log_error(f"Disruption hotkey cleanup failed: {exc}")
        try:
            if hotkey_manager is not None and hotkey_manager.stop_all() is False:
                confirmed = False
        except Exception as exc:
            confirmed = False
            log_error(f"Global hotkey cleanup failed: {exc}")
        DupeZDashboard._sync_panic_shortcut(self)
        return confirmed

    def _hotkey_toggle_visibility(self) -> None:
        """Thread-safe visibility toggle triggered from hotkey."""
        try:
            from PyQt6.QtCore import QMetaObject
            QMetaObject.invokeMethod(
                self, "_toggle_visibility_slot",
                Qt.ConnectionType.QueuedConnection,
            )
        except Exception as exc:
            log_error(f"Hotkey toggle error: {exc}")

    @pyqtSlot()
    def _toggle_visibility_slot(self) -> None:
        """Slot for thread-safe visibility toggle."""
        if getattr(self, "_hotkeys_closing", False):
            return
        if self.isVisible() and not self.isMinimized():
            self._minimize_to_tray_action()
        else:
            self._tray_show_window()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (double-click to show)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show_window()

    def _tray_show_window(self) -> None:
        """Restore window from tray."""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        if self.tray_icon:
            self.tray_action_show.setText("Hide DupeZ")

    def _minimize_to_tray_action(self) -> None:
        """Minimise the window to system tray."""
        self.hide()
        if self.tray_icon:
            self.tray_action_show.setText("Show DupeZ")
            self.tray_icon.showMessage(
                "DupeZ",
                "Running in background. Ctrl+Shift+D to toggle.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _tray_quit(self) -> None:
        """Fully quit from tray context menu."""
        self._force_quit = True
        # Hidden prewarmed WebEngine widgets are top-level windows. Closing
        # only the dashboard can therefore leave Qt's event loop alive even
        # after every owned service has shut down. Quit the application only
        # after closeEvent positively accepts the cleanup boundary.
        if self.close():
            application = QApplication.instance()
            if application is not None:
                application.quit()

    def _update_tray_tooltip(self) -> None:
        """Render the tray from the last completed background snapshot."""
        if not self.tray_icon:
            return
        try:
            count = len(self._disrupted_devices_snapshot)
            tip = (
                f"DupeZ \u2014 {count} active disruption{'s' if count != 1 else ''}"
                if count > 0
                else "DupeZ \u2014 No active disruptions"
            )
            self.tray_icon.setToolTip(tip)
            if hasattr(self, "tray_action_status"):
                self.tray_action_status.setText(f"Disruptions: {count}")
        except Exception:
            pass

    # ── Theme ───────────────────────────────────────────────────────

    def _apply_theme(self, theme_name: str = "dark") -> None:
        """Load a theme by name, falling back to embedded QSS.

        After applying the app-level stylesheet, re-applies the
        sidebar nav button inline QSS so that broad ``QPushButton``
        rules in theme files don't override the nav button layout.
        """
        try:
            from app.themes.theme_manager import get_theme_manager
            tm = get_theme_manager()
            if tm.apply_theme(theme_name):
                self._reapply_nav_styles()
                return
        except Exception:
            pass
        try:
            with open("app/themes/dark.qss", "r", encoding="utf-8") as fh:
                self.setStyleSheet(fh.read())
        except Exception:
            self.setStyleSheet(_FALLBACK_THEME_QSS)
        self._reapply_nav_styles()

    def _reapply_nav_styles(self) -> None:
        """Re-apply inline QSS to sidebar nav buttons after a theme change.

        This ensures that app-level QPushButton rules don't override
        the fixed 40×40 transparent nav button styling.
        """
        if hasattr(self, "nav_buttons"):
            for btn in self.nav_buttons:
                btn.setStyleSheet(_NAV_BTN_QSS)

    # ── Menu bar ────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        """Populate the custom embedded menu bar."""
        self.menuBar().setVisible(False)
        menubar = self._custom_menubar

        # File
        file_menu = menubar.addMenu("&File")
        self._add_action(file_menu, "&Scan Network", "Ctrl+S",
                         lambda: self.clumsy_view.start_scan())
        self._add_action(file_menu, "&Export Data", "Ctrl+E", self._export_data)
        self._add_action(
            file_menu,
            "Export Active Scenario &Report…",
            "Ctrl+Shift+E",
            self._export_active_scenario_report,
        )
        file_menu.addSeparator()
        self._add_action(file_menu, "Minimize to &Tray", "", self._minimize_to_tray_action)
        self._add_action(file_menu, "E&xit", "Ctrl+Q", self._tray_quit)

        # Tools
        tools_menu = menubar.addMenu("&Tools")
        self._add_action(tools_menu, "&Settings", "Ctrl+,", self._open_settings)
        self._add_action(tools_menu, "Stop All &Disruptions", "Ctrl+D",
                         self._stop_all_disruptions)
        # v5.6.9 additions
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Custom &Preset Editor…", "Ctrl+Shift+P",
                         self._open_preset_editor)
        self._add_action(tools_menu, "&Backup → File…", "",
                         self._on_create_backup)
        self._add_action(tools_menu, "Restore from &Backup…", "",
                         self._on_restore_backup)

        # v5.7.1: multi-account quick-switch. Forward / backward cycle
        # through the tracker accounts plus a "clear" entry. The active
        # account is persisted in app/data/active_account.json and
        # consumed by the episode recorder + audit log for tagging.
        tools_menu.addSeparator()
        self._add_action(tools_menu, "&Next Account", "Ctrl+Alt+A",
                         self._cycle_account_next)
        self._add_action(tools_menu, "Pre&vious Account", "Ctrl+Alt+Shift+A",
                         self._cycle_account_prev)
        self._add_action(tools_menu, "C&lear Active Account", "",
                         self._clear_active_account)

        # v5.7.4: wire the previously-orphaned v5.7.0/v5.7.1 feature
        # backends to actual menu entry points.
        tools_menu.addSeparator()
        self._add_action(tools_menu, "&Risk Score…", "",
                         self._show_risk_score)
        self._add_action(tools_menu, "&Diagnostics…", "F2",
                         self._show_diagnostics)
        self._add_action(tools_menu, "Audit &Webhook…", "",
                         self._show_audit_webhook_config)
        self._add_action(
            tools_menu,
            "Cut-&Chain Configurator…",
            "Ctrl+Shift+C",
            self._open_cut_chain_configurator,
        )
        self._add_action(tools_menu, "Network &Health…", "Ctrl+F2",
                         self._show_network_health)
        self._panic_stop_action = self._add_action(
            tools_menu, "&Kill Switch — Panic Stop", "Ctrl+Alt+X", self._kill_switch_panic
        )
        self._add_action(tools_menu, "Toggle &OBS Overlay Server", "",
                         self._toggle_obs_overlay)

        # View
        view_menu = menubar.addMenu("&View")
        self._add_action(view_menu, "&Clumsy Control", "Ctrl+1",
                         lambda: self.switch_view(0))
        self._add_action(view_menu, "&Map", "Ctrl+2",
                         lambda: self.switch_view(1))
        self._add_action(view_menu, "&Accounts", "Ctrl+3",
                         lambda: self.switch_view(2))
        self._add_action(view_menu, "&Network Tools", "Ctrl+4",
                         lambda: self.switch_view(3))

        # Help
        help_menu = menubar.addMenu("&Help")
        self._add_action(help_menu, "Check for &Updates", "", self._check_for_updates)
        help_menu.addSeparator()
        self._add_action(help_menu, "&Hotkeys", "F1", self._show_hotkeys)
        self._add_action(help_menu, "&About", "", self._show_about)

    def _add_action(self, menu: QMenu, text: str, shortcut: str,
                    callback: Any) -> QAction:
        """Helper: add a ``QAction`` to *menu*."""
        action = QAction(text, self)
        action.setAutoRepeat(False)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    # ── Status bar ──────────────────────────────────────────────────

    def _setup_status_bar(self) -> None:
        """Create the bottom status bar with device/disruption counts + GPU tier."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.device_status_label = QLabel("Devices: 0")
        self.disruption_status_label = QLabel("Disruptions: 0")
        self.device_status_label.setAccessibleName("Discovered device count")
        self.disruption_status_label.setAccessibleName(
            "Active operation count"
        )
        self.status_bar.addWidget(self.device_status_label)
        self.status_bar.addPermanentWidget(self.disruption_status_label)

        # GPU renderer tier indicator — shows whether the map is HW-accelerated
        _tier = os.environ.get("DUPEZ_MAP_RENDERER_TIER", "tier3_cpu")
        _tier_labels = {
            "tier1_hw": ("GPU", "#00ff88", "Map: hardware GPU raster (ANGLE/D3D11)"),
            "tier3_cpu": ("CPU", "#ff4444", "Map: CPU raster (no GPU) — use DupeZ-GPU.exe for best performance"),
        }
        label_text, color, tooltip = _tier_labels.get(_tier, ("?", "#94a3b8", "Unknown renderer tier"))
        self._gpu_tier_label = QLabel(f"  Map: {label_text}")
        self._gpu_tier_label.setAccessibleName("Map renderer status")
        self._gpu_tier_label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 600;")
        self._gpu_tier_label.setToolTip(tooltip)
        self.status_bar.addPermanentWidget(self._gpu_tier_label)

    def _update_status_bar(self) -> None:
        """Request the shared status-bar/tray snapshot off the Qt thread."""
        controller = self.controller
        if controller is None or self._dashboard_poll_in_flight:
            return

        self._dashboard_poll_generation += 1
        generation = self._dashboard_poll_generation
        self._dashboard_poll_in_flight = True

        def _fetch() -> None:
            try:
                devices = controller.get_devices()
                disrupted = controller.get_disrupted_devices()
                self._dashboard_snapshot_ready.emit(
                    generation,
                    len(devices),
                    disrupted,
                )
            except Exception as exc:
                self._dashboard_snapshot_failed.emit(
                    generation,
                    f"{type(exc).__name__}: {exc}",
                )

        threading.Thread(
            target=_fetch,
            daemon=True,
            name="DupeZDashboardStatusRefresh",
        ).start()

    @pyqtSlot(int, int, object)
    def _apply_dashboard_status_snapshot(
        self,
        generation: int,
        device_count: int,
        disrupted: object,
    ) -> None:
        """Update status bar and tray from the newest worker result."""
        if generation != self._dashboard_poll_generation:
            return
        self._dashboard_poll_in_flight = False
        if not isinstance(disrupted, (list, tuple, set, frozenset)):
            self._apply_dashboard_status_error(
                generation,
                "controller returned invalid disrupted-device state",
            )
            return
        self._device_count_snapshot = max(0, int(device_count))
        self._disrupted_devices_snapshot = frozenset(
            ip for ip in disrupted if isinstance(ip, str) and ip
        )

        self.device_status_label.setText(
            f"Devices: {self._device_count_snapshot}"
        )
        count = len(self._disrupted_devices_snapshot)
        self.disruption_status_label.setText(f"Disruptions: {count}")
        self.disruption_status_label.setStyleSheet(
            "color: #ff4444; font-weight: bold;"
            if count
            else "color: #94a3b8;"
        )
        self._update_tray_tooltip()

    @pyqtSlot(int, str)
    def _apply_dashboard_status_error(
        self,
        generation: int,
        message: str,
    ) -> None:
        """Release the guard after a failed snapshot without clearing state."""
        if generation != self._dashboard_poll_generation:
            return
        self._dashboard_poll_in_flight = False
        log_error(f"Dashboard status refresh error: {message}")

    # ── Signal wiring ───────────────────────────────────────────────

    def _connect_signals(self) -> None:
        """Wire up cross-widget signals."""
        try:
            if hasattr(self, "clumsy_view"):
                self.clumsy_view.scan_started.connect(
                    lambda: self.status_bar.showMessage("Scanning network...", 3000),
                )
                self.clumsy_view.scan_finished.connect(
                    lambda devs: self.status_bar.showMessage(
                        f"Scan complete \u2014 {len(devs)} devices", 3000,
                    ),
                )
            # Re-apply nav button styles whenever the global theme changes
            try:
                from app.themes.theme_manager import get_theme_manager
                get_theme_manager().theme_changed.connect(
                    lambda _name: self._reapply_nav_styles()
                )
            except Exception:
                pass
        except Exception as exc:
            log_error(f"Signal connection error: {exc}")

    # ── GUI toast / Npcap status ────────────────────────────────────

    def _register_gui_toast(self) -> None:
        """Route backend toast emissions to our status bar on the main thread."""
        try:
            from app.logs.gui_notify import register_gui_toast
            from PyQt6.QtCore import QMetaObject, Q_ARG, Qt as _Qt

            def _emit(level: str, msg: str) -> None:
                ms = 4000 if level == "info" else 8000
                prefix = {"info": "", "warn": "\u26A0 ", "error": "\u2716 "}.get(level, "")
                try:
                    QMetaObject.invokeMethod(
                        self.status_bar, "showMessage",
                        _Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, f"{prefix}{msg}"),
                        Q_ARG(int, ms),
                    )
                except Exception:
                    pass

            register_gui_toast(_emit)
        except Exception as exc:
            log_error(f"gui_toast register failed: {exc}")

    def _check_npcap_on_startup(self) -> None:
        """Surface Npcap status once at startup so the operator knows
        whether WiFi same-net interception / LAN Cut is available."""
        try:
            from app.network.npcap_check import check_npcap
            status = check_npcap()
            if status.available:
                self.status_bar.showMessage(status.short(), 4000)
            else:
                self.status_bar.showMessage(
                    f"\u26A0 {status.short()} \u2014 LAN Cut + WiFi "
                    f"same-net interception unavailable. See LAN Cut tab.",
                    10000,
                )
        except Exception as exc:
            log_error(f"npcap check failed: {exc}")

    # ── User actions ────────────────────────────────────────────────

    def _open_settings(self) -> None:
        """Launch the settings dialog."""
        try:
            if not self.controller:
                return
            self.controller.state.load_settings()
            dialog = SettingsDialog(
                self.controller.state.settings,
                self,
                controller=self.controller,
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._apply_disruption_hotkeys()
        except Exception as exc:
            log_error(f"Settings error: {exc}")

    def _stop_all_disruptions(self) -> None:
        """Emergency-stop all active disruptions."""
        owner = getattr(self, "_disruption_hotkeys", None)
        if owner is not None:
            owner.cancel_pending_starts()
        if not self.controller:
            self.status_bar.showMessage(
                "Stop unavailable — controller is not initialized", 5000
            )
            return
        if self.controller.stop_all_disruptions() is True:
            self.status_bar.showMessage("All disruptions stopped", 3000)
            return
        log_error("Stop All cleanup was not confirmed")
        self.status_bar.showMessage(
            "Cleanup not confirmed — retry Stop All or Panic Stop", 8000
        )

    # v5.6.9 menu handlers ─────────────────────────────────────────────
    def _open_preset_editor(self) -> None:
        """Open the custom preset editor dialog.

        On close, refresh the clumsy-control dropdown so newly-saved
        custom presets appear without requiring an app restart.
        """
        try:
            from app.gui.dialogs.preset_editor_dialog import PresetEditorDialog
            PresetEditorDialog(self).exec()
        except Exception as exc:
            log_error(f"open preset editor failed: {exc}")
            QMessageBox.critical(
                self, "Preset Editor",
                f"Could not open the editor: {exc}"
            )
            return
        # Best-effort: trigger the dropdown refresh on the clumsy view.
        # The view may not be initialized yet on very early invocations,
        # so guard with hasattr and swallow internal errors.
        try:
            view = getattr(self, "clumsy_view", None)
            refresh = getattr(view, "_refresh_preset_dropdown", None)
            if callable(refresh):
                refresh()
        except Exception as exc:
            log_warning(f"preset dropdown refresh failed: {exc}")

    def _on_create_backup(self) -> None:
        """Create a one-click backup bundle of all DupeZ data."""
        try:
            from app.core.backup import create_backup
            from app.core.app_paths import backups_dir

            default_dir = backups_dir()
            default_dir.mkdir(parents=True, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(
                self, "Create Backup",
                str(
                    default_dir
                    / f"dupez-backup-{__import__('time').strftime('%Y%m%d_%H%M%S')}.zip"
                ),
                "DupeZ Backup (*.zip);;Encrypted DupeZ Backup (*.zip.dpapi)",
            )
            if not path:
                return
            encrypt = path.endswith(".dpapi")
            out = create_backup(path, encrypt=encrypt)
            QMessageBox.information(
                self, "Backup Complete",
                f"Bundle written to:\n{out}"
            )
        except Exception as exc:
            log_error(f"create_backup failed: {exc}")
            QMessageBox.critical(
                self, "Backup Failed", f"{exc}"
            )

    # v5.7.1 multi-account quick-switch handlers ──────────────────────
    def _cycle_account_next(self) -> None:
        """Cycle the active-account marker forward to the next tracker entry."""
        try:
            from app.core import account_quick_switch as aqs
            new_name = aqs.cycle_active_account(1)
            if new_name:
                self.status_bar.showMessage(
                    f"Active account: {new_name}", 4000
                )
            else:
                self.status_bar.showMessage(
                    "Could not save active account; selection unchanged"
                    if aqs.active_account_names()
                    else "No accounts in tracker — add one first", 4000
                )
        except Exception as exc:
            log_error(f"cycle_account_next failed: {exc}")

    def _cycle_account_prev(self) -> None:
        """Cycle the active-account marker backward to the prior tracker entry."""
        try:
            from app.core import account_quick_switch as aqs
            new_name = aqs.cycle_active_account(-1)
            if new_name:
                self.status_bar.showMessage(
                    f"Active account: {new_name}", 4000
                )
            else:
                self.status_bar.showMessage(
                    "Could not save active account; selection unchanged"
                    if aqs.active_account_names()
                    else "No accounts in tracker — add one first", 4000
                )
        except Exception as exc:
            log_error(f"cycle_account_prev failed: {exc}")

    def _clear_active_account(self) -> None:
        """Unset the active-account marker. Episodes will no longer be tagged."""
        try:
            from app.core import account_quick_switch as aqs
            if aqs.clear_active_account():
                self.status_bar.showMessage("Active account cleared", 3000)
            else:
                self.status_bar.showMessage(
                    "Could not clear active account; selection unchanged", 4000,
                )
        except Exception as exc:
            log_error(f"clear_active_account failed: {exc}")

    # v5.7.4 — wire the orphaned v5.7.0/v5.7.1 feature backends ─────────
    def _show_risk_score(self) -> None:
        """Compute and display the current risk score with its breakdown."""
        try:
            from app.core.risk_score import compute_risk_score
            score = compute_risk_score()
            lines = [
                f"Risk score: {score.score}/100  ({score.band.upper()})",
                "",
                score.advisory,
                "",
                "Factor breakdown:",
            ]
            for c in score.contributions:
                lines.append(f"  +{c.value:>3}/{c.cap:<3}  {c.label}")
                if c.detail:
                    lines.append(f"           {c.detail}")
            QMessageBox.information(
                self, "DupeZ Risk Score", "\n".join(lines)
            )
        except Exception as exc:
            log_error(f"risk score display failed: {exc}")
            QMessageBox.warning(self, "Risk Score", f"Could not compute: {exc}")

    def _show_diagnostics(self) -> None:
        """Run all diagnostic self-checks and display the results."""
        try:
            from app.core.diagnostics import run_all_checks
            from app.gui.diagnostics_dialog import DiagnosticsDialog

            results = run_all_checks()
            DiagnosticsDialog(results, self).exec()
        except Exception as exc:
            log_error(
                f"diagnostics display failed ({type(exc).__name__})"
            )
            QMessageBox.warning(
                self,
                "Diagnostics",
                "Could not run diagnostics. Review the local application log "
                "and try again.",
            )

    def _show_audit_webhook_config(self) -> None:
        """Open the sealed audit-webhook configuration surface."""
        try:
            from app.gui.audit_webhook_dialog import AuditWebhookDialog

            AuditWebhookDialog(self).exec()
        except Exception:
            log_error("Audit webhook configuration dialog failed")
            QMessageBox.warning(
                self,
                "Audit Webhook",
                "Could not open audit webhook configuration. No stored URL "
                "was read or displayed.",
            )

    def _open_cut_chain_configurator(self) -> None:
        """Edit and start one authorized, controller-owned cut chain."""
        controller = self.controller
        if controller is None or not hasattr(controller, "start_cut_chain"):
            QMessageBox.warning(
                self,
                "Cut Chain Unavailable",
                "The active controller does not support configured chains.",
            )
            return

        view = getattr(self, "clumsy_view", None)
        selected = set(getattr(view, "selected_ips", set()) or set())
        if len(selected) > 1:
            QMessageBox.warning(
                self,
                "One Target Required",
                "A cut chain runs on exactly one device. Clear the other "
                "selections and try again.",
            )
            return
        target_ip = next(iter(selected), "")
        if not target_ip:
            target_ip = str(getattr(view, "selected_ip", "") or "")
        if not target_ip:
            state = getattr(controller, "state", None)
            target_ip = str(getattr(state, "selected_ip", "") or "")

        try:
            from app.gui.cut_chain_dialog import CutChainConfiguratorDialog

            dialog = CutChainConfiguratorDialog(
                target_ip,
                safety_policy=getattr(controller, "safety_policy", None),
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            config = dialog.selected_config()
            if config is None:
                raise ValueError("dialog returned no validated configuration")

            self._cut_chain_ui_generation += 1
            ui_generation = self._cut_chain_ui_generation

            def _on_event(event: object) -> None:
                self._cut_chain_event_ready.emit(ui_generation, event)

            generation = controller.start_cut_chain(
                config,
                on_event=_on_event,
            )
            if not generation:
                self._cut_chain_ui_generation += 1
                QMessageBox.warning(
                    self,
                    "Cut Chain Refused",
                    "The chain did not start. Recheck the target, safety "
                    "scope, engine readiness, and local application log.",
                )
                return
            self.status_bar.showMessage(
                f"Cut chain started ({len(config.stages)} stages)",
                5000,
            )
        except Exception as exc:
            log_error(
                "Cut-chain configurator failed "
                f"({type(exc).__name__})"
            )
            QMessageBox.warning(
                self,
                "Cut Chain",
                "Could not open or start the chain. No unvalidated "
                "configuration was executed.",
            )

    @pyqtSlot(int, object)
    def _on_cut_chain_event(self, generation: int, event: object) -> None:
        """Render runner progress only for the newest configured chain."""
        if generation != self._cut_chain_ui_generation:
            return
        kind = str(getattr(event, "kind", "") or "")
        stage_idx = int(getattr(event, "stage_idx", -1))
        if kind == "stage_start":
            self.status_bar.showMessage(
                f"Cut chain stage {stage_idx + 1} active",
                5000,
            )
        elif kind == "stage_end":
            self.status_bar.showMessage(
                f"Cut chain stage {stage_idx + 1} released",
                5000,
            )
        elif kind == "complete":
            self.status_bar.showMessage(
                "Cut chain complete — target released",
                6000,
            )
        elif kind == "halt":
            self.status_bar.showMessage(
                "Cut chain stopped — target released",
                6000,
            )
        elif kind == "error":
            detail = str(getattr(event, "detail", "") or "").casefold()
            if "release could not be confirmed" in detail:
                self.status_bar.showMessage(
                    "Cut chain failed — release not confirmed; retry Panic Stop",
                    8000,
                )
            else:
                self.status_bar.showMessage(
                    "Cut chain failed — target released; review the local log",
                    8000,
                )

    def _show_network_health(self) -> None:
        """Display a concise, privacy-preserving health summary."""
        try:
            from app.core.network_health import build_network_health_snapshot

            snapshot = build_network_health_snapshot()
            overall = snapshot["overall"]
            summary = overall["summary"]
            adapters = snapshot["network"]["adapters"]
            route = snapshot["network"]["default_route"]
            lines = [
                f"Health score: {overall['score']}/100",
                f"Status: {overall['status'].upper()}",
                (
                    "Checks: "
                    f"{summary['pass']} pass, {summary['warn']} warn, "
                    f"{summary['fail']} fail"
                ),
                "",
                (
                    "Adapters: "
                    f"{adapters.get('up_adapter_count', '?')}/"
                    f"{adapters.get('adapter_count', '?')} up"
                ),
                f"Default route: {route.get('kind', 'unknown')}",
                (
                    "Windows Packet Monitor: "
                    f"{'available' if snapshot['capabilities']['pktmon_available'] else 'unavailable'}"
                ),
                f"Recovery pending: {snapshot['recovery']['pending']}",
            ]
            if snapshot["recommendations"]:
                lines.extend(["", "Recommended next actions:"])
                lines.extend(
                    f"• {item}" for item in snapshot["recommendations"]
                )
            box = QMessageBox(self)
            box.setWindowTitle("DupeZ Network Health")
            box.setAccessibleName("DupeZ Network Health summary")
            box.setAccessibleDescription(
                "Network readiness, safety, recovery, and diagnostic results"
            )
            box.setIcon(
                QMessageBox.Icon.Critical
                if summary["fail"]
                else QMessageBox.Icon.Warning
                if summary["warn"]
                else QMessageBox.Icon.Information
            )
            box.setText("\n".join(lines))
            box.exec()
        except Exception as exc:
            log_error(f"network health display failed: {exc}")
            QMessageBox.warning(
                self,
                "Network Health",
                f"Could not build health snapshot: {exc}",
            )

    def _kill_switch_panic(self) -> None:
        """Immediate panic-stop of all disruptions (manual kill switch)."""
        owner = getattr(self, "_disruption_hotkeys", None)
        if owner is not None:
            owner.cancel_pending_starts()
        try:
            stopped = bool(
                self.controller
                and self.controller.fire_manual_kill_switch(
                    "dashboard panic stop"
                ) is True
            )
            if not stopped:
                log_error("Kill switch panic cleanup was not confirmed")
                self.status_bar.showMessage(
                    "KILL SWITCH — cleanup not confirmed; retry Panic Stop",
                    8000,
                )
                QMessageBox.critical(
                    self,
                    "Kill Switch",
                    "Panic-stop could not confirm that every disruption was "
                    "released. Retry Panic Stop and verify network state.",
                )
                return
            self.status_bar.showMessage(
                "KILL SWITCH — all disruptions stopped", 5000
            )
            log_warning("Kill switch panic-stop invoked by operator")
        except Exception as exc:
            log_error(f"kill switch panic failed: {exc}")
            QMessageBox.critical(
                self, "Kill Switch",
                f"Panic-stop encountered an error: {exc}\n"
                f"Check that disruptions actually stopped."
            )

    def _toggle_obs_overlay(self) -> None:
        """Start or stop the OBS overlay HTTP server."""
        try:
            from app.core.overlay_server import OverlayServerOwner
            from app.core.data_persistence import settings_manager

            owner = getattr(self, "overlay_server_owner", None)
            if owner is None:
                owner = OverlayServerOwner(self.controller)
                self.overlay_server_owner = owner

            if owner.owned:
                if not owner.stop():
                    QMessageBox.warning(
                        self,
                        "OBS Overlay",
                        "The overlay server did not confirm shutdown. Its "
                        "resources remain owned so cleanup can be retried.",
                    )
                    return
                try:
                    settings_manager.update_setting(
                        "obs_overlay_enabled",
                        False,
                    )
                except Exception as exc:
                    log_error(
                        "OBS overlay stopped, but the disabled preference "
                        f"could not be saved: {exc}"
                    )
                    QMessageBox.warning(
                        self,
                        "OBS Overlay Stopped",
                        "The overlay server stopped, but that preference "
                        "could not be saved. It may auto-start next launch.",
                    )
                    return
                self.status_bar.showMessage("OBS overlay stopped", 4000)
                return

            if not owner.start():
                retained = (
                    " Cleanup resources remain owned for a retry."
                    if owner.owned
                    else ""
                )
                QMessageBox.warning(
                    self, "OBS Overlay",
                    "Could not start the overlay server. The configured "
                    f"address ({owner.base_url}) may already be in use."
                    f"{retained}"
                )
                return

            try:
                settings_manager.update_setting("obs_overlay_enabled", True)
            except Exception as exc:
                rollback_ok = owner.stop()
                log_error(
                    "OBS overlay enabled preference could not be saved; "
                    f"runtime rollback confirmed={rollback_ok}: {exc}"
                )
                QMessageBox.warning(
                    self,
                    "OBS Overlay",
                    (
                        "The overlay start was rolled back because its "
                        "enabled preference could not be saved."
                        if rollback_ok
                        else "The enabled preference could not be saved and "
                        "server cleanup was not confirmed. Cleanup ownership "
                        "has been retained for another stop attempt."
                    ),
                )
                return
            QMessageBox.information(
                self, "OBS Overlay Started",
                f"Overlay server running. Add this as a Browser Source "
                f"in OBS:\n\n{owner.base_url}/overlay.html\n\n"
                f"It auto-starts on future launches until you toggle "
                f"it off here."
            )
        except Exception as exc:
            log_error(f"OBS overlay toggle failed: {exc}")
            QMessageBox.warning(
                self, "OBS Overlay", f"Could not toggle: {exc}"
            )

    def _on_restore_backup(self) -> None:
        """Restore from a previously-created backup bundle."""
        try:
            from app.core.backup import restore_backup
            path, _ = QFileDialog.getOpenFileName(
                self, "Restore Backup", "",
                "DupeZ Backup (*.zip *.zip.dpapi);;All Files (*)",
            )
            if not path:
                return
            # Dry-run preview first so the operator can confirm impact.
            preview = restore_backup(path, dry_run=True)
            if not preview.ok:
                reason = preview.error or next(
                    iter(preview.failed.values()),
                    "The backup contains corrupted files.",
                )
                QMessageBox.critical(
                    self, "Restore Failed",
                    f"The backup could not be restored completely.\n\n"
                    f"{reason}\n\nNo files were restored.",
                )
                return
            count = len(preview.restored)
            if QMessageBox.question(
                self, "Confirm Restore",
                f"This will overwrite {count} files in your DupeZ "
                f"install with the bundle's contents.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            result = restore_backup(path, dry_run=False)
            if result.ok:
                QMessageBox.information(
                    self, "Restore Complete",
                    f"Restored {len(result.restored)} files. "
                    f"Restart DupeZ for changes to take full effect."
                )
            else:
                reason = result.error or next(
                    iter(result.failed.values()),
                    "The backup contains corrupted files.",
                )
                QMessageBox.warning(
                    self, "Restore Issues",
                    f"Restored {len(result.restored)}, "
                    f"failed {len(result.failed)}.\n\n"
                    f"{reason}\n\nSee logs for details."
                )
        except Exception as exc:
            log_error(f"restore_backup failed: {exc}")
            QMessageBox.critical(
                self, "Restore Failed", f"{exc}"
            )

    def _export_data(self) -> None:
        """Export device list to CSV."""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export", "dupez_devices.csv", "CSV (*.csv)",
            )
            if filename and self.controller:
                devices = self.controller.get_devices()
                with open(filename, "w", encoding="utf-8") as fh:
                    fh.write("IP,MAC,Hostname,Vendor,Blocked\n")
                    for d in devices:
                        fh.write(f"{d.ip},{d.mac},{d.hostname},{d.vendor},{d.blocked}\n")
                self.status_bar.showMessage(f"Exported to {filename}", 3000)
        except Exception as exc:
            log_error(f"Export error: {exc}")

    def _export_active_scenario_report(self) -> None:
        """Export scope/deadline state without raw targets or parameters."""
        try:
            if not self.controller:
                return
            directory = QFileDialog.getExistingDirectory(
                self,
                "Choose Scenario Report Folder",
            )
            if not directory:
                return
            from app.core.scenario_report import (
                build_scenario_report,
                write_scenario_report,
            )

            report = build_scenario_report(
                self.controller.get_active_operations()
            )
            path = write_scenario_report(report, output_dir=directory)
            QMessageBox.information(
                self,
                "Scenario Report Exported",
                "Privacy-preserving report written to:\n"
                f"{path}\n\n"
                "Targets are masked and parameter values are fingerprinted.",
            )
        except Exception as exc:
            log_error(f"scenario report export failed: {exc}")
            QMessageBox.warning(
                self,
                "Scenario Report",
                f"Could not export report: {exc}",
            )

    def _show_hotkeys(self) -> None:
        """Show actual window shortcuts and backend registration status."""
        rows: list[str] = []
        try:
            for menu_action in self._custom_menubar.actions():
                menu = menu_action.menu()
                if menu is None:
                    continue
                for act in menu.actions():
                    if act.isSeparator():
                        continue
                    sc = act.shortcut().toString()
                    if not sc:
                        continue
                    label = act.text().replace("&", "").strip()
                    rows.append(
                        f"<tr><td style='padding-right:18px;'><b>{html.escape(sc)}</b>"
                        f"</td><td>{html.escape(label)}</td></tr>"
                    )
        except Exception as exc:  # pragma: no cover - defensive
            log_error(f"hotkey reference build failed: {exc}")
        global_rows: list[str] = []
        tray = hotkey_manager.get_listener("tray_toggle") if hotkey_manager is not None else None
        tray_keys = tray.get_active_keys() if tray is not None else []
        tray_status = "Registered (key release)" if tray_keys else "Disabled / unavailable"
        global_rows.append(
            "<tr><td>Toggle Window</td><td>ctrl+shift+d</td>"
            f"<td>{html.escape(', '.join(tray_keys) or 'None')}</td>"
            f"<td>{tray_status}</td></tr>"
        )
        owner = getattr(self, "_disruption_hotkeys", None)
        if owner is not None:
            labels = {"start": "Start selected disruption", "stop": "Stop All", "panic": "Panic Stop"}
            for binding in owner.status():
                state = binding["state"]
                if binding["error"]:
                    state += ": " + binding["error"]
                cells = [labels[binding["action"]], binding["configured"],
                         ", ".join(binding["active"]) or "None", state]
                global_rows.append("<tr>" + "".join(
                    f"<td>{html.escape(cell)}</td>" for cell in cells
                ) + "</tr>")
        QMessageBox.information(self, "Hotkeys", (
            "<h3>DupeZ window shortcuts</h3>"
            "<table cellpadding='3'>" + "".join(rows) + "</table>"
            "<h3>Global hooks</h3><table cellpadding='3'>"
            "<tr><th>Action</th><th>Configured</th><th>Armed</th><th>Status</th></tr>"
            + "".join(global_rows) + "</table>"
            "<p>Configure in Settings → Hotkeys. Global actions fire on key release. "
            "Registered means the backend accepted the hook; other applications "
            "may consume it. Verify Stop/Panic in your controlled test environment. "
            "Menu emergency actions remain available.</p>"
        ))

    def _setup_update_flow(self) -> None:
        """Keep updater workers and delayed installation handoff owned by Qt."""
        self._update_generation = 0
        self._update_check_in_flight = False
        self._update_download_in_flight = False
        self._update_launch_in_flight = False
        self._update_cleanup_confirmed = False
        self._prepared_update = None
        self._update_check_ready.connect(
            self._on_update_check_ready, Qt.ConnectionType.QueuedConnection,
        )
        self._update_progress_ready.connect(
            self._on_update_progress, Qt.ConnectionType.QueuedConnection,
        )
        self._update_download_ready.connect(
            self._on_update_download_ready, Qt.ConnectionType.QueuedConnection,
        )
        self._update_prepared_ready.connect(
            self._on_update_prepared, Qt.ConnectionType.QueuedConnection,
        )
        self._update_handoff_timer = QTimer(self)
        self._update_handoff_timer.setSingleShot(True)
        self._update_handoff_timer.setInterval(1500)
        self._update_handoff_timer.timeout.connect(self._tray_quit)

    def _stop_update_callbacks(self) -> None:
        """Discard pending updater UI callbacks when leaving the dashboard."""
        self._update_generation = getattr(self, "_update_generation", 0) + 1
        self._update_check_in_flight = False
        self._update_download_in_flight = False
        prepared = getattr(self, "_prepared_update", None)
        self._prepared_update = None
        if prepared is not None:
            prepared.cancel()
        timer = getattr(self, "_update_handoff_timer", None)
        if timer is not None:
            timer.stop()

    def _check_for_updates(self) -> None:
        """Check asynchronously, allowing only one update interaction at once."""
        if (
            self._update_check_in_flight
            or self._update_download_in_flight
            or self._update_handoff_timer.isActive()
        ):
            return
        self._update_generation += 1
        self._update_check_in_flight = True
        generation = self._update_generation
        self.statusBar().showMessage("Checking for updates...", 0)

        def on_result(result: object) -> None:
            try:
                self._update_check_ready.emit(generation, result)
            except RuntimeError:
                pass  # The window may have been destroyed during the check.

        try:
            from app.core.updater import updater
            updater.check_async(callback=on_result)
        except Exception as exc:
            self._on_update_check_ready(generation, {"error": str(exc)})

    @pyqtSlot(int, object)
    def _on_update_check_ready(self, generation: int, result: object) -> None:
        """Present a completed check on the GUI thread, including consent."""
        if generation != self._update_generation or not self._update_check_in_flight:
            return
        try:
            from app.core.updater import updater
            self.statusBar().clearMessage()
            if not isinstance(result, dict):
                raise ValueError("Invalid update check response")
            if result.get("error"):
                QMessageBox.warning(
                    self, "Update Check",
                    f"Could not check for updates:\n{result['error']}",
                )
            elif result.get("update_available"):
                msg = QMessageBox(self)
                msg.setWindowTitle("Update Available")
                msg.setIcon(QMessageBox.Icon.Information)
                msg.setText(
                    f"DupeZ v{result['latest_version']} is available!\n"
                    f"You're running v{result['current_version']}."
                )
                notes = result.get("release_notes", "")
                if notes:
                    # Truncate very long release notes
                    if len(notes) > 400:
                        notes = notes[:400] + "..."
                    msg.setInformativeText(notes)

                btn_install = msg.addButton(
                    "Download && Install", QMessageBox.ButtonRole.AcceptRole)
                btn_browser = msg.addButton(
                    "Open in Browser", QMessageBox.ButtonRole.ActionRole)
                msg.addButton(QMessageBox.StandardButton.Cancel)

                msg.exec()
                clicked = msg.clickedButton()

                if generation != self._update_generation:
                    return
                if clicked is btn_install:
                    self._do_auto_update()
                elif clicked is btn_browser:
                    updater.open_download()
            else:
                QMessageBox.information(
                    self, "Up to Date",
                    f"DupeZ v{result['current_version']} is the latest version.",
                )
        except Exception as exc:
            log_error(f"Update check error: {exc}")
            QMessageBox.warning(self, "Update Check",
                                f"Error checking for updates:\n{exc}")
        finally:
            if generation == self._update_generation:
                self._update_check_in_flight = False

    def _do_auto_update(self) -> None:
        """Download the new installer and launch it for in-place upgrade."""
        if self._update_download_in_flight or self._update_handoff_timer.isActive():
            return
        self._update_generation += 1
        self._update_check_in_flight = False
        self._update_download_in_flight = True
        generation = self._update_generation
        self.statusBar().showMessage("Downloading update...", 0)

        def on_progress(done: int, total: int) -> None:
            try:
                self._update_progress_ready.emit(generation, done, total)
            except RuntimeError:
                pass

        def on_done(success: bool, message: str) -> None:
            try:
                self._update_download_ready.emit(generation, success, message)
            except RuntimeError:
                pass

        def on_prepared(prepared: object) -> None:
            try:
                self._update_prepared_ready.emit(generation, prepared)
            except RuntimeError:
                prepared.cancel()

        try:
            from app.core.updater import updater
            updater.download_and_install(
                on_progress=on_progress, on_done=on_done, on_prepared=on_prepared,
            )
        except Exception as exc:
            self._on_update_download_ready(generation, False, str(exc))

    @pyqtSlot(int, object)
    def _on_update_prepared(self, generation: int, prepared: object) -> None:
        if (
            generation != self._update_generation
            or not self._update_download_in_flight
            or self._prepared_update is not None
        ):
            prepared.cancel()
            return
        self._prepared_update = prepared
        self._update_launch_in_flight = True
        self.statusBar().showMessage("Update verified. Releasing application resources...", 0)
        try:
            if not self._release_owned_resources():
                prepared.cancel()
                self._prepared_update = None
                self._update_launch_in_flight = False
                self._on_update_download_ready(
                    generation, False, "application cleanup was not confirmed; installer not launched",
                )
                return
            self._update_cleanup_confirmed = True
            # Keep the Qt event loop alive for the launch result, but do not
            # permit new work after controller and service shutdown.
            self.setEnabled(False)
            self.statusBar().showMessage("Application cleanup confirmed. Launching update...", 0)
            if not prepared.launch():
                raise RuntimeError("prepared update is no longer available")
        except Exception as exc:
            prepared.cancel()
            self._on_update_download_ready(generation, False, str(exc))

    @pyqtSlot(int, object, object)
    def _on_update_progress(self, generation: int, done: int, total: int) -> None:
        if generation != self._update_generation or not self._update_download_in_flight:
            return
        if total > 0:
            pct = max(0, min(100, int(done / total * 100)))
            self.statusBar().showMessage(f"Downloading update... {pct}%", 0)

    @pyqtSlot(int, bool, str)
    def _on_update_download_ready(
        self, generation: int, success: bool, message: str,
    ) -> None:
        if generation != self._update_generation or not self._update_download_in_flight:
            return
        self._update_download_in_flight = False
        self._update_launch_in_flight = False
        self._prepared_update = None
        if success and not self._update_cleanup_confirmed:
            success = False
            message = "installer completion arrived without confirmed application cleanup"
        if success:
            self.statusBar().showMessage("Update downloaded — installing...", 3000)
            # Use the same confirmed-cleanup exit as the tray's Quit action.
            self._update_handoff_timer.start()
        else:
            self.statusBar().showMessage(f"Update failed: {message}", 5000)
            log_error(f"Auto-update failed: {message}")
            if self._update_cleanup_confirmed:
                QMessageBox.warning(
                    self, "Update Launch Failed",
                    f"The installer could not be launched:\n{message}\n\n"
                    "Application services have already stopped. DupeZ will close; "
                    "restart it to try again.",
                )
                self._tray_quit()

    def _show_about(self) -> None:
        """Display the About dialog with credits and support info."""
        dlg = QDialog(self)
        dlg.setWindowTitle("About DupeZ")
        dlg.setFixedSize(480, 560)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.FramelessWindowHint)
        dlg.setStyleSheet(_ABOUT_DLG_QSS)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)
        layout.setContentsMargins(30, 20, 30, 20)

        self._about_build_header(layout, dlg)
        self._about_build_info_block(layout)
        self._about_build_credits(layout)
        self._about_build_support(layout)

        layout.addStretch()

        # ── Bottom button row: GitHub + Close ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        gh_btn = QPushButton("\u2728  View on GitHub")
        gh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        gh_btn.setStyleSheet(_GH_BTN_QSS)
        gh_btn.clicked.connect(
            lambda: webbrowser.open("https://github.com/GrihmLord/DupeZ"),
        )

        done_btn = QPushButton("Close")
        done_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        done_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.06); color: #94a3b8;"
            " border: 1px solid rgba(255,255,255,0.12); border-radius: 8px;"
            " padding: 10px 28px; font-weight: 600; font-size: 12px; }"
            " QPushButton:hover { background: rgba(255,255,255,0.12);"
            " color: #e2e8f0; }"
        )
        done_btn.clicked.connect(dlg.close)

        btn_row.addStretch()
        btn_row.addWidget(gh_btn)
        btn_row.addWidget(done_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        dlg.exec()

    # ── About dialog helpers ────────────────────────────────────────

    @staticmethod
    def _about_build_header(layout: QVBoxLayout, dialog: QDialog) -> None:
        """Close button, title, version, tagline, and separator."""
        # ── Close (×) button, top-right ──
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("\u2715")
        close_btn.setAccessibleName("Close About DupeZ")
        close_btn.setToolTip("Close")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(_CLOSE_BTN_QSS)
        close_btn.clicked.connect(dialog.reject)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        # ── Title ──
        title = QLabel("DUPEZ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color: #00d9ff; font-size: 32px; font-weight: 900;"
            " letter-spacing: 6px;"
        )
        layout.addWidget(title)

        # ── Version pill ──
        version = QLabel(f"v{CURRENT_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet(
            "color: #00d9ff; font-size: 11px; font-weight: 700;"
            " letter-spacing: 2px;"
        )
        layout.addWidget(version)

        layout.addSpacing(6)

        # ── Gradient separator ──
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(
            "background: qlineargradient(x1:0, x2:1,"
            " stop:0 transparent, stop:0.5 #00d9ff, stop:1 transparent);"
        )
        layout.addWidget(sep)
        layout.addSpacing(8)

        # ── Tagline ──
        desc = QLabel(
            "Owned-lab network-condition testing and diagnostics.\n"
            "Reproduce connection faults with bounded, auditable recovery."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.5;")
        layout.addWidget(desc)
        layout.addSpacing(10)

        # Wire close button to parent dialog
        close_btn.clicked.connect(layout.parentWidget().close)

    @staticmethod
    def _about_build_info_block(layout: QVBoxLayout) -> None:
        """ENGINE / ARCH / PLATFORM / RUNTIME info rows."""
        from app.firewall_helper.feature_flag import get_arch

        arch = get_arch()
        arch_label = (
            "Split (GUI + elevated helper)"
            if arch == "split"
            else "In-process (single elevated)"
        )

        lbl_qss = "color: #475569; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        val_qss = "color: #e2e8f0; font-size: 11px; font-weight: 600;"
        for label_text, value_text in [
            ("ENGINE", "WinDivert + Clumsy core"),
            ("ARCH", arch_label),
            ("PLATFORM", "Windows 11 / Windows 10 LTSC or ESU (x64)"),
            ("RUNTIME", "Python 3.12\u20133.13 \u00b7 PyQt6"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet(lbl_qss)
            lbl.setFixedWidth(90)
            val = QLabel(value_text)
            val.setStyleSheet(val_qss)
            row.addWidget(lbl)
            row.addWidget(val)
            row.addStretch()
            layout.addLayout(row)

    @staticmethod
    def _about_build_credits(layout: QVBoxLayout) -> None:
        """Credits section."""
        _sec_qss = "color: #00d9ff; font-size: 10px; font-weight: 700; letter-spacing: 2px;"
        _sep_qss = "background: rgba(0, 217, 255, 0.15);"
        _body_qss = "font-size: 12px; line-height: 1.6;"

        layout.addSpacing(10)
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(_sep_qss)
        layout.addWidget(sep)
        layout.addSpacing(8)

        credits_title = QLabel("CREDITS")
        credits_title.setStyleSheet(_sec_qss)
        layout.addWidget(credits_title)

        credits_text = QLabel(
            '<span style="color:#e2e8f0;">Created by</span> '
            '<a href="https://github.com/GrihmLord" '
            'style="color:#00d9ff; text-decoration:none; font-weight:bold;">'
            "GrihmLord</a>"
            "<br>"
            '<span style="color:#64748b; font-size:11px;">'
            "Built on the work of:</span><br>"
            '<a href="https://github.com/jagt/clumsy" '
            'style="color:#00d9ff; text-decoration:none;">Clumsy</a>'
            ' <span style="color:#475569;">\u2014 jagt (Chen Tao)</span>'
            " &nbsp;\u00b7&nbsp; "
            '<a href="https://github.com/kalirenegade-dev/clumsy" '
            'style="color:#00d9ff; text-decoration:none;">Keybind Edition</a>'
            ' <span style="color:#475569;">\u2014 Kalirenegade</span>'
        )
        credits_text.setOpenExternalLinks(True)
        credits_text.setWordWrap(True)
        credits_text.setStyleSheet(_body_qss)
        layout.addWidget(credits_text)

    @staticmethod
    def _about_build_support(layout: QVBoxLayout) -> None:
        """Support / donation section."""
        _sec_qss = "color: #00d9ff; font-size: 10px; font-weight: 700; letter-spacing: 2px;"
        _sep_qss = "background: rgba(0, 217, 255, 0.15);"
        _body_qss = "font-size: 12px; line-height: 1.6;"

        layout.addSpacing(10)
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(_sep_qss)
        layout.addWidget(sep)
        layout.addSpacing(8)

        support_title = QLabel("SUPPORT")
        support_title.setStyleSheet(_sec_qss)
        layout.addWidget(support_title)

        support_text = QLabel(
            '<span style="color:#94a3b8;">DupeZ is free and open-source.</span><br>'
            '<span style="color:#94a3b8;">If it saves you time, consider tipping:</span><br>'
            '<span style="color:#00ff88; font-size:14px; font-weight:bold;">'
            "CashApp: $YngTycoon</span>"
        )
        support_text.setWordWrap(True)
        support_text.setStyleSheet(_body_qss)
        layout.addWidget(support_text)

    # ── Frameless window: drag & resize ─────────────────────────────

    def _toggle_maximize(self) -> None:
        """Toggle between maximised and normal window state."""
        if self.isMaximized():
            self.showNormal()
            self.btn_maximize.setText("\u25a1")
        else:
            self.showMaximized()
            self.btn_maximize.setText("\u25a3")

    @staticmethod
    def _detect_resize_edge(pos: QPoint, rect_width: int, rect_height: int) -> Optional[str]:
        """Return the edge/corner string for the given position, or ``None``."""
        m = _RESIZE_MARGIN
        edges: List[str] = []
        if pos.x() <= m:
            edges.append("left")
        elif pos.x() >= rect_width - m:
            edges.append("right")
        if pos.y() <= m:
            edges.append("top")
        elif pos.y() >= rect_height - m:
            edges.append("bottom")
        return "+".join(edges) if edges else None

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            rect = self.rect()
            edge = self._detect_resize_edge(point, rect.width(), rect.height())
            if edge:
                self._resizing = True
                self._resize_edge = edge
                self._drag_pos = event.globalPosition().toPoint()
                self._start_geometry = self.geometry()
            elif self.title_bar.geometry().contains(point):
                self._drag_pos = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
            else:
                self._drag_pos = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self._resizing and self._drag_pos:
            self._handle_resize(event)
        elif self._drag_pos and not self._resizing:
            self._handle_drag(event)
        else:
            point = event.position().toPoint()
            rect = self.rect()
            edge = self._detect_resize_edge(point, rect.width(), rect.height())
            self.setCursor(
                _RESIZE_CURSOR_MAP.get(edge, Qt.CursorShape.ArrowCursor),
            )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        self._drag_pos = None
        self._resizing = False
        self._resize_edge = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        if self.title_bar.geometry().contains(event.position().toPoint()):
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)

    def _handle_resize(self, event: Any) -> None:
        """Apply resize delta based on the active edge."""
        delta = event.globalPosition().toPoint() - self._drag_pos
        geo = self._start_geometry
        new_geo = self.geometry()
        edge = self._resize_edge or ""

        if "right" in edge:
            new_geo.setWidth(max(self.minimumWidth(), geo.width() + delta.x()))
        if "bottom" in edge:
            new_geo.setHeight(max(self.minimumHeight(), geo.height() + delta.y()))
        if "left" in edge:
            new_w = max(self.minimumWidth(), geo.width() - delta.x())
            new_geo.setLeft(geo.left() + geo.width() - new_w)
            new_geo.setWidth(new_w)
        if "top" in edge:
            new_h = max(self.minimumHeight(), geo.height() - delta.y())
            new_geo.setTop(geo.top() + geo.height() - new_h)
            new_geo.setHeight(new_h)

        self.setGeometry(new_geo)

    def _handle_drag(self, event: Any) -> None:
        """Drag the window (un-maximise on first move if maximised)."""
        if self.isMaximized():
            self.showNormal()
            self.btn_maximize.setText("\u25a1")
            self._drag_pos = QPoint(self.width() // 2, 18)
        self.move(event.globalPosition().toPoint() - self._drag_pos)

    # ── Lifecycle ───────────────────────────────────────────────────

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        """Minimise to tray on close, unless force-quit is set."""
        if getattr(self, "_update_launch_in_flight", False):
            # The launch worker must report success/failure before Qt exits.
            event.ignore()
            return
        if self._minimize_to_tray and self.tray_icon and not self._force_quit:
            event.ignore()
            self._minimize_to_tray_action()
            return

        self._stop_update_callbacks()
        if not getattr(self, "_update_cleanup_confirmed", False):
            if not self._release_owned_resources():
                event.ignore()
                return
        try:
            gc.collect()
        except Exception as exc:
            log_error(f"Close garbage collection failed: {exc}")
        event.accept()

    def _release_owned_resources(self) -> bool:
        """Confirm shutdown before either closing Qt or launching an installer."""
        cleanup_confirmed = True
        try:
            if not DupeZDashboard._stop_global_hotkeys(self):
                cleanup_confirmed = False
                log_error("Dashboard hotkey cleanup was not confirmed")
        except Exception as exc:
            cleanup_confirmed = False
            log_error(f"Dashboard hotkey cleanup failed: {exc}")
        try:
            self._dashboard_poll_generation += 1
            self._dashboard_poll_in_flight = False
        except Exception as exc:
            cleanup_confirmed = False
            log_error(f"Dashboard poll cleanup failed: {exc}")
        # Each timer/service is an independent owner. A deleted Qt wrapper or
        # failed stop must not skip the remaining restoration attempts.
        for timer_name in ("_status_timer", "_stats_timer"):
            try:
                getattr(self, timer_name).stop()
            except Exception as exc:
                cleanup_confirmed = False
                log_error(f"Dashboard {timer_name} cleanup failed: {exc}")
        try:
            if hasattr(self, "clumsy_view"):
                self.clumsy_view.stop_background_refresh()
        except Exception as exc:
            cleanup_confirmed = False
            log_error(f"Dashboard background refresh cleanup failed: {exc}")

        try:
            if hasattr(self, "nettools_view"):
                if self.nettools_view.cleanup() is False:
                    cleanup_confirmed = False
                    log_error(
                        "Network Tools shutdown completed with unconfirmed cleanup"
                    )
        except Exception as exc:
            # Continue into the controller's independent restoration path even
            # when a child panel fails; active network state must never be
            # skipped because an earlier GUI cleanup raised.
            cleanup_confirmed = False
            log_error(f"Network Tools shutdown failed: {exc}")

        try:
            if self.tray_icon:
                self.tray_icon.hide()
        except Exception as exc:
            cleanup_confirmed = False
            log_error(f"Dashboard tray cleanup failed: {exc}")
        try:
            owner = getattr(self, "overlay_server_owner", None)
            if owner is not None and owner.owned and not owner.stop():
                cleanup_confirmed = False
                log_error(
                    "OBS overlay close cleanup was not confirmed; ownership retained"
                )
        except Exception as exc:
            cleanup_confirmed = False
            log_error(f"OBS overlay close cleanup failed: {exc}")

        try:
            if self.controller:
                if self.controller.shutdown() is False:
                    cleanup_confirmed = False
                    log_error("Controller close cleanup was not confirmed")
        except Exception as exc:
            cleanup_confirmed = False
            log_error(f"Controller close shutdown failed: {exc}")

        if not cleanup_confirmed:
            log_error(
                "Application close refused because one or more owned resources "
                "were not released"
            )
            try:
                QMessageBox.critical(
                    self,
                    "Cleanup Not Confirmed",
                    "DupeZ could not confirm that every network operation and "
                    "background service was released. The application will stay "
                    "open so you can use Panic Stop and retry Exit.",
                )
            except Exception as exc:
                log_error(f"Cleanup failure dialog could not be shown: {exc}")
        return cleanup_confirmed
