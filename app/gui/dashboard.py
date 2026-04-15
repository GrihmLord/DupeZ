# app/gui/dashboard.py — DupeZ Dashboard (3-View Architecture)
"""Main application window for DupeZ.

``DupeZDashboard`` is a frameless ``QMainWindow`` with a custom title bar,
four sidebar-navigated views (Clumsy Control, iZurvive Map, Account Tracker,
Network Tools), a system tray integration, and a plugin panel extension
point.
"""

from __future__ import annotations

import gc
import os
import webbrowser
from typing import Any, List, Optional

from PyQt6.QtCore import Q_ARG, QMetaObject, QPoint, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QCursor, QFont, QIcon
from PyQt6.QtWidgets import (
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
from app.gui.network_tools import NetworkToolsView
from app.gui.panels.help_panel import HelpPanel
from app.gui.settings_dialog import SettingsDialog
from app.logs.logger import log_error, log_info
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

    def __init__(self, controller: Any = None) -> None:
        super().__init__()
        self.controller = controller
        self._minimize_to_tray: bool = True
        self._force_quit: bool = False

        # Frameless drag/resize state
        self._drag_pos: Optional[QPoint] = None
        self._resizing: bool = False
        self._resize_edge: Optional[str] = None
        self._start_geometry = None

        self._setup_ui()
        self._setup_menu()
        self._setup_status_bar()
        self._setup_tray()
        self._setup_tray_hotkey()
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

        self._tray_timer = QTimer(self)
        self._tray_timer.timeout.connect(self._update_tray_tooltip)
        self._tray_timer.start(5000)

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
        if not KEYBOARD_AVAILABLE or hotkey_manager is None:
            return
        try:
            hotkey_manager.add_listener(
                "tray_toggle",
                callback=self._hotkey_toggle_visibility,
                keys=["ctrl+shift+d"],
                config={"cooldown": 0.5, "enabled": True},
            )
            hotkey_manager.start_all()
            log_info("Tray hotkey registered: Ctrl+Shift+D")
        except Exception as exc:
            log_error(f"Failed to register tray hotkey: {exc}")

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
        self.close()

    def _update_tray_tooltip(self) -> None:
        """Refresh tray tooltip with current disruption count."""
        if not self.tray_icon:
            return
        try:
            count = 0
            if self.controller:
                count = len(self.controller.get_disrupted_devices())
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
        file_menu.addSeparator()
        self._add_action(file_menu, "Minimize to &Tray", "", self._minimize_to_tray_action)
        self._add_action(file_menu, "E&xit", "Ctrl+Q", self._tray_quit)

        # Tools
        tools_menu = menubar.addMenu("&Tools")
        self._add_action(tools_menu, "&Settings", "Ctrl+,", self._open_settings)
        self._add_action(tools_menu, "Stop All &Disruptions", "Ctrl+D",
                         self._stop_all_disruptions)

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
                    callback: Any) -> None:
        """Helper: add a ``QAction`` to *menu*."""
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)

    # ── Status bar ──────────────────────────────────────────────────

    def _setup_status_bar(self) -> None:
        """Create the bottom status bar with device/disruption counts + GPU tier."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.device_status_label = QLabel("Devices: 0")
        self.disruption_status_label = QLabel("Disruptions: 0")
        self.status_bar.addWidget(self.device_status_label)
        self.status_bar.addPermanentWidget(self.disruption_status_label)

        # GPU renderer tier indicator — shows whether the map is HW-accelerated
        _tier = os.environ.get("DUPEZ_MAP_RENDERER_TIER", "tier3_cpu")
        _tier_labels = {
            "tier1_hw": ("GPU", "#00ff88", "Map: hardware GPU raster (ANGLE/D3D11)"),
            "tier2_swiftshader": ("SW-GL", "#fbbf24", "Map: SwiftShader software GL — consider DupeZ-GPU.exe"),
            "tier3_cpu": ("CPU", "#ff4444", "Map: CPU raster (no GPU) — use DupeZ-GPU.exe for best performance"),
        }
        label_text, color, tooltip = _tier_labels.get(_tier, ("?", "#94a3b8", "Unknown renderer tier"))
        self._gpu_tier_label = QLabel(f"  Map: {label_text}")
        self._gpu_tier_label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 600;")
        self._gpu_tier_label.setToolTip(tooltip)
        self.status_bar.addPermanentWidget(self._gpu_tier_label)

    def _update_status_bar(self) -> None:
        """Refresh device/disruption counts."""
        try:
            if not self.controller:
                return
            devices = self.controller.get_devices()
            self.device_status_label.setText(f"Devices: {len(devices)}")
            disrupted = self.controller.get_disrupted_devices()
            self.disruption_status_label.setText(f"Disruptions: {len(disrupted)}")
            style = (
                "color: #ff4444; font-weight: bold;" if disrupted
                else "color: #94a3b8;"
            )
            self.disruption_status_label.setStyleSheet(style)
        except Exception as exc:
            log_error(f"Status bar update error: {exc}")

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
            dialog = SettingsDialog(self.controller.state.settings, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.controller.update_settings(dialog.get_new_settings())
        except Exception as exc:
            log_error(f"Settings error: {exc}")

    def _stop_all_disruptions(self) -> None:
        """Emergency-stop all active disruptions."""
        if self.controller:
            self.controller.stop_all_disruptions()
            self.status_bar.showMessage("All disruptions stopped", 3000)

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

    def _show_hotkeys(self) -> None:
        """Display the hotkey reference dialog."""
        QMessageBox.information(self, "Hotkeys", (
            "<h3>DupeZ Hotkeys</h3>"
            "<p><b>Ctrl+S</b> \u2014 Scan Network</p>"
            "<p><b>Ctrl+D</b> \u2014 Stop All Disruptions</p>"
            "<p><b>Ctrl+1/2/3/4</b> \u2014 Switch Views</p>"
            "<p><b>Ctrl+,</b> \u2014 Settings</p>"
            "<p><b>Ctrl+E</b> \u2014 Export Data</p>"
            "<p><b>Ctrl+Shift+D</b> \u2014 Toggle Window (Tray Mode)</p>"
            "<p><b>Ctrl+Q</b> \u2014 Exit</p>"
        ))

    def _check_for_updates(self) -> None:
        """Query GitHub for new releases and offer direct install or browser."""
        try:
            from app.core.updater import updater
            result = updater.check_sync()
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

    def _do_auto_update(self) -> None:
        """Download the new installer and launch it for in-place upgrade."""
        from app.core.updater import updater

        # Show a simple progress message
        self.statusBar().showMessage("Downloading update...", 0)

        def on_progress(done: int, total: int) -> None:
            if total > 0:
                pct = int(done / total * 100)
                QMetaObject.invokeMethod(
                    self.statusBar(), "showMessage",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, f"Downloading update... {pct}%"),
                    Q_ARG(int, 0),
                )

        def on_done(success: bool, message: str) -> None:
            if success:
                QMetaObject.invokeMethod(
                    self.statusBar(), "showMessage",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, "Update downloaded — installing..."),
                    Q_ARG(int, 3000),
                )
                # Close DupeZ so the installer can replace files
                QTimer.singleShot(1500, self.close)
            else:
                QMetaObject.invokeMethod(
                    self.statusBar(), "showMessage",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, f"Update failed: {message}"),
                    Q_ARG(int, 5000),
                )
                log_error(f"Auto-update failed: {message}")

        updater.download_and_install(on_progress=on_progress, on_done=on_done)

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

        self._about_build_header(layout)
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
    def _about_build_header(layout: QVBoxLayout) -> None:
        """Close button, title, version, tagline, and separator."""
        # ── Close (×) button, top-right ──
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("\u2715")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(_CLOSE_BTN_QSS)
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
            "Per-device network disruption toolkit.\n"
            "Scan your network, pick your targets, manipulate their packets."
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
            ("PLATFORM", "Windows 10 / 11 (x64)"),
            ("RUNTIME", "Python 3.10+ \u00b7 PyQt6"),
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
        if self._minimize_to_tray and self.tray_icon and not self._force_quit:
            event.ignore()
            self._minimize_to_tray_action()
            return

        try:
            self._status_timer.stop()
            self._stats_timer.stop()
            self._tray_timer.stop()

            if self.tray_icon:
                self.tray_icon.hide()
            if KEYBOARD_AVAILABLE and hotkey_manager:
                hotkey_manager.stop_all()
            if self.controller:
                self.controller.shutdown()
            gc.collect()
        except Exception as exc:
            log_error(f"Close error: {exc}")
        event.accept()
