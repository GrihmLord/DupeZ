# app/gui/dashboard.py — DupeZ Dashboard (3-View Architecture)

import os
import gc
import ctypes
import webbrowser

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStatusBar, QStackedWidget, QDialog, QMessageBox,
    QGraphicsDropShadowEffect, QSystemTrayIcon, QMenu
)
from PyQt6.QtGui import QIcon, QAction, QFont, QCursor, QColor
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSlot

from app.gui.clumsy_control import ClumsyControlView
from app.gui.dayz_map_gui_new import DayZMapGUI
from app.gui.dayz_account_tracker import DayZAccountTracker
from app.gui.network_tools import NetworkToolsView
from app.gui.settings_dialog import SettingsDialog
from app.logs.logger import log_info, log_error, log_warning

try:
    from app.gui.hotkey import hotkey_manager, KEYBOARD_AVAILABLE
except ImportError:
    KEYBOARD_AVAILABLE = False
    hotkey_manager = None

IS_ADMIN = os.name != 'nt' or (
    hasattr(ctypes, 'windll') and ctypes.windll.shell32.IsUserAnAdmin() != 0
)


class DupeZDashboard(QMainWindow):
    """DupeZ main window — 3-view architecture: Clumsy | Map | Accounts"""

    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self._minimize_to_tray = True  # User can toggle via settings
        self._force_quit = False

        self.setup_ui()
        self.setup_menu()
        self.setup_status_bar()
        self.setup_tray()
        self.setup_tray_hotkey()
        self.connect_signals()

        # Periodic status bar update
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status_bar)
        self.update_timer.start(3000)

        # Header stats
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self._update_header_stats)
        self.stats_timer.start(2000)

        # Tray tooltip updater
        self.tray_timer = QTimer()
        self.tray_timer.timeout.connect(self._update_tray_tooltip)
        self.tray_timer.start(5000)

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------
    def setup_ui(self):
        admin_text = " [ADMIN]" if IS_ADMIN else ""
        self.setWindowTitle(f"DupeZ v3.3.0{admin_text}")
        # App icon — try resources first, fall back to assets
        for icon_path in ["app/resources/dupez.ico", "app/resources/dupez.png", "app/assets/icon.ico"]:
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break

        # --- Borderless frameless window ---
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_pos = None
        self._resizing = False
        self._resize_edge = None
        self._resize_margin = 6

        screen = self.screen().availableGeometry()
        w = int(screen.width() * 0.85)
        h = int(screen.height() * 0.85)
        self.setGeometry((screen.width() - w) // 2, (screen.height() - h) // 2, w, h)
        self.setMinimumSize(900, 600)

        self.apply_default_theme()

        central = QWidget()
        central.setObjectName("main_container")
        central.setStyleSheet("""
            #main_container {
                background-color: #0a0e1a;
                border: 1px solid #0f1a2e;
            }
        """)
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # === CUSTOM TITLE BAR ===
        self.title_bar = QWidget()
        self.title_bar.setObjectName("title_bar")
        self.title_bar.setFixedHeight(36)
        self.title_bar.setStyleSheet("""
            #title_bar {
                background-color: #050810;
                border-bottom: 1px solid #0f1a2e;
            }
        """)
        tb_layout = QHBoxLayout(self.title_bar)
        tb_layout.setContentsMargins(12, 0, 8, 0)
        tb_layout.setSpacing(8)

        # Icon + title
        title_label = QLabel("DupeZ v3.3.0")
        title_label.setStyleSheet("color: #64748b; font-size: 12px; font-weight: 600; letter-spacing: 1px; background: transparent;")
        tb_layout.addWidget(title_label)

        if IS_ADMIN:
            admin_tag = QLabel("ADMIN")
            admin_tag.setStyleSheet("color: #fbbf24; font-size: 10px; font-weight: bold; background: transparent;")
            tb_layout.addWidget(admin_tag)

        tb_layout.addStretch()

        # Window control buttons
        btn_style_base = """
            QPushButton {{
                background: transparent;
                color: {color};
                border: none;
                font-size: {size};
                font-weight: bold;
                padding: 0;
                min-width: 36px;
                max-width: 36px;
                min-height: 36px;
                max-height: 36px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
        """

        self.btn_minimize = QPushButton("\u2014")  # em dash
        self.btn_minimize.setStyleSheet(btn_style_base.format(color="#64748b", size="14px", hover_bg="rgba(255,255,255,0.08)"))
        self.btn_minimize.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_minimize.clicked.connect(self.showMinimized)

        self.btn_maximize = QPushButton("\u25a1")  # white square
        self.btn_maximize.setStyleSheet(btn_style_base.format(color="#64748b", size="14px", hover_bg="rgba(255,255,255,0.08)"))
        self.btn_maximize.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_maximize.clicked.connect(self._toggle_maximize)

        self.btn_close = QPushButton("\u2715")  # multiplication x
        self.btn_close.setStyleSheet(btn_style_base.format(color="#64748b", size="14px", hover_bg="rgba(255,50,50,0.6)"))
        self.btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_close.clicked.connect(self.close)

        tb_layout.addWidget(self.btn_minimize)
        tb_layout.addWidget(self.btn_maximize)
        tb_layout.addWidget(self.btn_close)

        main_layout.addWidget(self.title_bar)

        # === HEADER ===
        header = QWidget()
        header.setObjectName("header_bar")
        header.setFixedHeight(50)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(15, 5, 15, 5)

        logo = QLabel("DUPEZ")
        logo.setStyleSheet("font-size: 18px; font-weight: bold; color: #00d9ff; letter-spacing: 2px;")
        hl.addWidget(logo)

        self.status_indicator = QLabel("CONNECTED")
        self.status_indicator.setStyleSheet("color: #00ff88; font-weight: bold;")
        hl.addWidget(self.status_indicator)
        hl.addStretch()

        self.cpu_label = QLabel("CPU: 0%")
        self.cpu_label.setStyleSheet("color: #94a3b8;")
        self.ram_label = QLabel("RAM: 0%")
        self.ram_label.setStyleSheet("color: #94a3b8;")
        hl.addWidget(self.cpu_label)
        hl.addSpacing(20)
        hl.addWidget(self.ram_label)

        main_layout.addWidget(header)

        # === CONTENT: Sidebar + Stacked Views ===
        content = QWidget()
        cl = QHBoxLayout(content)
        cl.setSpacing(0)
        cl.setContentsMargins(0, 0, 0, 0)

        # --- Sidebar Rail (3 buttons) ---
        self.sidebar_rail = QWidget()
        self.sidebar_rail.setObjectName("sidebar_rail")
        self.sidebar_rail.setFixedWidth(60)
        sl = QVBoxLayout(self.sidebar_rail)
        sl.setContentsMargins(0, 15, 0, 15)
        sl.setSpacing(10)

        self.btn_clumsy = self._nav_btn("🎯", "Clumsy Control")
        self.btn_map = self._nav_btn("🗺️", "iZurvive Map")
        self.btn_accounts = self._nav_btn("👤", "Account Tracker")
        self.btn_nettools = self._nav_btn("📡", "Network Tools")

        self.nav_buttons = [self.btn_clumsy, self.btn_map, self.btn_accounts, self.btn_nettools]
        for i, btn in enumerate(self.nav_buttons):
            btn.clicked.connect(lambda checked, idx=i: self.switch_view(idx))
            sl.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)

        sl.addStretch()
        cl.addWidget(self.sidebar_rail)

        # --- Stacked Views ---
        self.view_stack = QStackedWidget()

        # View 0: Clumsy Control (main)
        self.clumsy_view = ClumsyControlView(controller=self.controller)
        self.view_stack.addWidget(self.clumsy_view)

        # View 1: Map
        self.map_view = DayZMapGUI()
        self.view_stack.addWidget(self.map_view)

        # View 2: Accounts
        self.accounts_view = DayZAccountTracker()
        self.view_stack.addWidget(self.accounts_view)

        # View 3: Network Tools
        self.nettools_view = NetworkToolsView(controller=self.controller)
        self.view_stack.addWidget(self.nettools_view)

        cl.addWidget(self.view_stack, 1)
        main_layout.addWidget(content, 1)

        # Default to Clumsy view
        self.switch_view(0)

    def _nav_btn(self, icon: str, tooltip: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setToolTip(tooltip)
        btn.setCheckable(True)
        btn.setFixedSize(40, 40)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFont(QFont("Segoe UI Emoji", 16))
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background: rgba(0, 217, 255, 0.15);
            }
            QPushButton:checked {
                background: rgba(0, 217, 255, 0.25);
                border-left: 3px solid #00d9ff;
            }
        """)
        return btn

    def switch_view(self, index: int):
        self.view_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    # ------------------------------------------------------------------
    # Header Stats
    # ------------------------------------------------------------------
    def _update_header_stats(self):
        try:
            import psutil
            self.cpu_label.setText(f"CPU: {psutil.cpu_percent():.0f}%")
            self.ram_label.setText(f"RAM: {psutil.virtual_memory().percent:.0f}%")
        except:
            pass

    # ------------------------------------------------------------------
    # System Tray
    # ------------------------------------------------------------------
    def setup_tray(self):
        """Initialize system tray icon with context menu."""
        self.tray_icon = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log_info("System tray not available on this platform")
            self._minimize_to_tray = False
            return

        self.tray_icon = QSystemTrayIcon(self)

        # Icon — reuse app icon
        for icon_path in ["app/resources/dupez.ico", "app/resources/dupez.png", "app/assets/icon.ico"]:
            if os.path.exists(icon_path):
                self.tray_icon.setIcon(QIcon(icon_path))
                break
        else:
            self.tray_icon.setIcon(self.windowIcon())

        self.tray_icon.setToolTip("DupeZ — No active disruptions")

        # Context menu
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background: #0a0e1a;
                color: #e2e8f0;
                border: 1px solid #1e293b;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 24px;
            }
            QMenu::item:selected {
                background: rgba(0, 217, 255, 0.2);
            }
            QMenu::separator {
                height: 1px;
                background: #1e293b;
                margin: 4px 8px;
            }
        """)

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

    def setup_tray_hotkey(self):
        """Register a global hotkey to toggle window visibility (Ctrl+Shift+D)."""
        if not KEYBOARD_AVAILABLE or hotkey_manager is None:
            return
        try:
            hotkey_manager.add_listener(
                "tray_toggle",
                callback=self._hotkey_toggle_visibility,
                keys=["ctrl+shift+d"],
                config={"cooldown": 0.5, "enabled": True}
            )
            hotkey_manager.start_all()
            log_info("Tray hotkey registered: Ctrl+Shift+D")
        except Exception as e:
            log_error(f"Failed to register tray hotkey: {e}")

    def _hotkey_toggle_visibility(self):
        """Toggle window visibility from hotkey (thread-safe)."""
        try:
            from PyQt6.QtCore import QMetaObject, Qt as QtConst
            QMetaObject.invokeMethod(self, "_toggle_visibility_slot",
                                     QtConst.ConnectionType.QueuedConnection)
        except Exception as e:
            log_error(f"Hotkey toggle error: {e}")

    @pyqtSlot()
    def _toggle_visibility_slot(self):
        """Slot for thread-safe visibility toggle."""
        if self.isVisible() and not self.isMinimized():
            self._minimize_to_tray_action()
        else:
            self._tray_show_window()

    def _tray_activated(self, reason):
        """Handle tray icon activation (double-click to show)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show_window()

    def _tray_show_window(self):
        """Restore window from tray."""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        if self.tray_icon:
            self.tray_action_show.setText("Hide DupeZ")

    def _minimize_to_tray_action(self):
        """Minimize the window to system tray."""
        self.hide()
        if self.tray_icon:
            self.tray_action_show.setText("Show DupeZ")
            self.tray_icon.showMessage(
                "DupeZ",
                "Running in background. Ctrl+Shift+D to toggle.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

    def _tray_quit(self):
        """Fully quit from tray context menu."""
        self._force_quit = True
        self.close()

    def _update_tray_tooltip(self):
        """Update tray icon tooltip with disruption count."""
        if not self.tray_icon:
            return
        try:
            count = 0
            if self.controller:
                count = len(self.controller.get_disrupted_devices())
            if count > 0:
                tip = f"DupeZ — {count} active disruption{'s' if count != 1 else ''}"
            else:
                tip = "DupeZ — No active disruptions"
            self.tray_icon.setToolTip(tip)
            if hasattr(self, 'tray_action_status'):
                self.tray_action_status.setText(f"Disruptions: {count}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def apply_default_theme(self):
        try:
            from app.themes.theme_manager import theme_manager
            if theme_manager.apply_theme("dark"):
                return
        except:
            pass
        self._apply_fallback_theme()

    def _apply_fallback_theme(self):
        try:
            with open("app/themes/dark.qss", 'r') as f:
                self.setStyleSheet(f.read())
        except:
            self.setStyleSheet("""
                QMainWindow, QWidget { background-color: #1a1a2e; color: #e0e0e0; }
                QPushButton { background: #16213e; color: #e0e0e0; border: 1px solid #0f3460; padding: 6px 12px; border-radius: 4px; }
                QPushButton:hover { background: #0f3460; }
            """)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def setup_menu(self):
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu('&File')
        self._add_action(file_menu, '&Scan Network', 'Ctrl+S', lambda: self.clumsy_view.start_scan())
        self._add_action(file_menu, '&Export Data', 'Ctrl+E', self.export_data)
        file_menu.addSeparator()
        self._add_action(file_menu, 'Minimize to &Tray', '', self._minimize_to_tray_action)
        self._add_action(file_menu, 'E&xit', 'Ctrl+Q', self._tray_quit)

        # Tools
        tools_menu = menubar.addMenu('&Tools')
        self._add_action(tools_menu, '&Settings', 'Ctrl+,', self.open_settings)
        self._add_action(tools_menu, 'Stop All &Disruptions', 'Ctrl+D', self._stop_all_disruptions)

        # View
        view_menu = menubar.addMenu('&View')
        self._add_action(view_menu, '&Clumsy Control', 'Ctrl+1', lambda: self.switch_view(0))
        self._add_action(view_menu, '&Map', 'Ctrl+2', lambda: self.switch_view(1))
        self._add_action(view_menu, '&Accounts', 'Ctrl+3', lambda: self.switch_view(2))
        self._add_action(view_menu, '&Network Tools', 'Ctrl+4', lambda: self.switch_view(3))

        # Help
        help_menu = menubar.addMenu('&Help')
        self._add_action(help_menu, '&Hotkeys', 'F1', self.show_hotkeys)
        self._add_action(help_menu, '&About', '', self.show_about)

    def _add_action(self, menu, text, shortcut, callback):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)

    # ------------------------------------------------------------------
    # Status Bar
    # ------------------------------------------------------------------
    def setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.device_status_label = QLabel("Devices: 0")
        self.disruption_status_label = QLabel("Disruptions: 0")
        self.status_bar.addWidget(self.device_status_label)
        self.status_bar.addPermanentWidget(self.disruption_status_label)

    def update_status_bar(self):
        try:
            if self.controller:
                devices = self.controller.get_devices()
                self.device_status_label.setText(f"Devices: {len(devices)}")
                disrupted = self.controller.get_disrupted_devices()
                self.disruption_status_label.setText(f"Disruptions: {len(disrupted)}")
                if disrupted:
                    self.disruption_status_label.setStyleSheet("color: #ff4444; font-weight: bold;")
                else:
                    self.disruption_status_label.setStyleSheet("color: #94a3b8;")
        except Exception as e:
            log_error(f"Status bar update error: {e}")

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    def connect_signals(self):
        try:
            if hasattr(self, 'clumsy_view'):
                self.clumsy_view.scan_started.connect(
                    lambda: self.status_bar.showMessage("Scanning network...", 3000))
                self.clumsy_view.scan_finished.connect(
                    lambda devs: self.status_bar.showMessage(f"Scan complete — {len(devs)} devices", 3000))
        except Exception as e:
            log_error(f"Signal connection error: {e}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def open_settings(self):
        try:
            if self.controller:
                self.controller.state.load_settings()
                dialog = SettingsDialog(self.controller.state.settings, self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self.controller.update_settings(dialog.get_new_settings())
        except Exception as e:
            log_error(f"Settings error: {e}")

    def _stop_all_disruptions(self):
        if self.controller:
            self.controller.stop_all_disruptions()
            self.status_bar.showMessage("All disruptions stopped", 3000)

    def export_data(self):
        try:
            from PyQt6.QtWidgets import QFileDialog
            filename, _ = QFileDialog.getSaveFileName(self, "Export", "dupez_devices.csv", "CSV (*.csv)")
            if filename and self.controller:
                devices = self.controller.get_devices()
                with open(filename, 'w') as f:
                    f.write("IP,MAC,Hostname,Vendor,Blocked\n")
                    for d in devices:
                        f.write(f"{d.ip},{d.mac},{d.hostname},{d.vendor},{d.blocked}\n")
                self.status_bar.showMessage(f"Exported to {filename}", 3000)
        except Exception as e:
            log_error(f"Export error: {e}")

    def show_hotkeys(self):
        QMessageBox.information(self, "Hotkeys", """
        <h3>DupeZ Hotkeys</h3>
        <p><b>Ctrl+S</b> — Scan Network</p>
        <p><b>Ctrl+D</b> — Stop All Disruptions</p>
        <p><b>Ctrl+1/2/3</b> — Switch Views</p>
        <p><b>Ctrl+,</b> — Settings</p>
        <p><b>Ctrl+E</b> — Export Data</p>
        <p><b>Ctrl+Shift+D</b> — Toggle Window (Tray Mode)</p>
        <p><b>Ctrl+Q</b> — Exit</p>
        """)

    def show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("About DupeZ")
        dlg.setFixedSize(480, 520)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.FramelessWindowHint)
        dlg.setStyleSheet("""
            QDialog {
                background-color: #060913;
                border: 1px solid #00d9ff;
                border-radius: 12px;
            }
            QLabel {
                background: transparent;
                color: #cbd5e1;
            }
        """)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(30, 25, 30, 25)

        # Close button top-right
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("\u2715")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #64748b; border: none; font-size: 16px; font-weight: bold; }
            QPushButton:hover { color: #ff4444; }
        """)
        close_btn.clicked.connect(dlg.close)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        # Title
        title = QLabel("DUPEZ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #00d9ff; font-size: 28px; font-weight: 900; letter-spacing: 4px;")
        layout.addWidget(title)

        version = QLabel("v3.3.0")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: #64748b; font-size: 13px; font-weight: 600;")
        layout.addWidget(version)

        layout.addSpacing(8)

        # Separator
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: qlineargradient(x1:0, x2:1, stop:0 transparent, stop:0.5 #00d9ff, stop:1 transparent);")
        layout.addWidget(sep)

        layout.addSpacing(8)

        # Description
        desc = QLabel("Network disruption toolkit for DayZ.\nScan, target, disrupt — per-device packet manipulation.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.5;")
        layout.addWidget(desc)

        layout.addSpacing(12)

        # Info block
        info_style = "color: #64748b; font-size: 11px;"
        val_style = "color: #e2e8f0; font-size: 11px; font-weight: 600;"

        for label_text, value_text in [
            ("ENGINE", "Native WinDivert + Clumsy"),
            ("PLATFORM", "Windows 10/11 (64-bit)"),
            ("RUNTIME", "Python 3.10+ / PyQt6"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet(info_style)
            lbl.setFixedWidth(90)
            val = QLabel(value_text)
            val.setStyleSheet(val_style)
            row.addWidget(lbl)
            row.addWidget(val)
            row.addStretch()
            layout.addLayout(row)

        layout.addSpacing(12)

        # Separator
        sep2 = QLabel()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: rgba(51, 65, 85, 0.5);")
        layout.addWidget(sep2)

        layout.addSpacing(8)

        # Credits
        credits_title = QLabel("CREDITS")
        credits_title.setStyleSheet("color: #00d9ff; font-size: 11px; font-weight: 700; letter-spacing: 2px;")
        layout.addWidget(credits_title)

        credits_text = QLabel(
            '<span style="color:#e2e8f0;">Built by</span> '
            '<a href="https://github.com/GrihmLord" style="color:#00d9ff; text-decoration:none; font-weight:bold;">GrihmLord</a><br><br>'
            '<span style="color:#94a3b8;">Standing on the shoulders of:</span><br>'
            '<a href="https://github.com/jagt/clumsy" style="color:#00d9ff; text-decoration:none;">Clumsy</a>'
            ' <span style="color:#64748b;">by jagt (Chen Tao)</span><br>'
            '<a href="https://github.com/kalirenegade-dev/clumsy" style="color:#00d9ff; text-decoration:none;">Keybind Edition</a>'
            ' <span style="color:#64748b;">by Kalirenegade</span>'
        )
        credits_text.setOpenExternalLinks(True)
        credits_text.setWordWrap(True)
        credits_text.setStyleSheet("font-size: 12px; line-height: 1.6;")
        layout.addWidget(credits_text)

        layout.addSpacing(12)

        # Separator
        sep3 = QLabel()
        sep3.setFixedHeight(1)
        sep3.setStyleSheet("background: rgba(51, 65, 85, 0.5);")
        layout.addWidget(sep3)

        layout.addSpacing(8)

        # Support section
        support_title = QLabel("SUPPORT THE PROJECT")
        support_title.setStyleSheet("color: #00d9ff; font-size: 11px; font-weight: 700; letter-spacing: 2px;")
        layout.addWidget(support_title)

        support_text = QLabel(
            '<span style="color:#94a3b8;">If you like DupeZ and want to show appreciation:</span><br>'
            '<span style="color:#00ff88; font-size:14px; font-weight:bold;">CashApp: $YngTycoon</span>'
        )
        support_text.setWordWrap(True)
        support_text.setStyleSheet("font-size: 12px; line-height: 1.6;")
        layout.addWidget(support_text)

        layout.addStretch()

        # GitHub button
        gh_btn = QPushButton("GitHub")
        gh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        gh_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #00d9ff;
                border: 1px solid #00d9ff;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background: rgba(0, 217, 255, 0.15);
            }
        """)
        gh_btn.clicked.connect(lambda: webbrowser.open("https://github.com/GrihmLord/DupeZ"))

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(gh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        dlg.exec()

    # ------------------------------------------------------------------
    # Frameless Window — Drag, Resize, Maximize
    # ------------------------------------------------------------------
    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.btn_maximize.setText("\u25a1")
        else:
            self.showMaximized()
            self.btn_maximize.setText("\u25a3")

    def _get_resize_edge(self, pos):
        """Detect which edge/corner the mouse is near for resize."""
        m = self._resize_margin
        rect = self.rect()
        edges = []
        if pos.x() <= m:
            edges.append("left")
        elif pos.x() >= rect.width() - m:
            edges.append("right")
        if pos.y() <= m:
            edges.append("top")
        elif pos.y() >= rect.height() - m:
            edges.append("bottom")
        return "+".join(edges) if edges else None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._get_resize_edge(event.position().toPoint())
            if edge:
                self._resizing = True
                self._resize_edge = edge
                self._drag_pos = event.globalPosition().toPoint()
                self._start_geometry = self.geometry()
            elif self.title_bar.geometry().contains(event.position().toPoint()):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            else:
                self._drag_pos = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing and self._drag_pos:
            delta = event.globalPosition().toPoint() - self._drag_pos
            geo = self._start_geometry
            new_geo = self.geometry()
            edge = self._resize_edge

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
        elif self._drag_pos and not self._resizing:
            if self.isMaximized():
                self.showNormal()
                self.btn_maximize.setText("\u25a1")
                self._drag_pos = QPoint(self.width() // 2, 18)
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        else:
            # Update cursor shape for resize hints
            edge = self._get_resize_edge(event.position().toPoint())
            if edge in ("left", "right"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif edge in ("top", "bottom"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif edge in ("left+top", "right+bottom"):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edge in ("right+top", "left+bottom"):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self._resizing = False
        self._resize_edge = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.title_bar.geometry().contains(event.position().toPoint()):
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        # Minimize to tray instead of quitting (unless force quit)
        if self._minimize_to_tray and self.tray_icon and not self._force_quit:
            event.ignore()
            self._minimize_to_tray_action()
            return

        try:
            self.update_timer.stop()
            self.stats_timer.stop()
            self.tray_timer.stop()

            # Clean up tray
            if self.tray_icon:
                self.tray_icon.hide()

            # Clean up hotkeys
            if KEYBOARD_AVAILABLE and hotkey_manager:
                hotkey_manager.stop_all()

            if self.controller:
                self.controller.shutdown()
            gc.collect()
        except Exception as e:
            log_error(f"Close error: {e}")
        event.accept()
