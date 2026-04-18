# app/gui/settings_dialog.py
"""Application settings dialog with tabbed UI for all DupeZ configuration."""

from __future__ import annotations

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                              QWidget, QLabel, QSpinBox, QCheckBox, QComboBox,
                              QPushButton, QGroupBox, QFormLayout,
                              QTextEdit, QSlider, QMessageBox, QScrollArea,
                              QFrame)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from app.logs.logger import log_info, log_error
from app.core.state import AppSettings

__all__ = ["SETTINGS_STYLE", "SettingsDialog"]

# Inline stylesheet — applied directly to the dialog so it always matches
# the DupeZ cyber‑HUD look regardless of the active app theme.
SETTINGS_STYLE = """
SettingsDialog {
    background-color: #050810;
    color: #e2e8f0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

/* --- Tabs --- */
QTabWidget::pane {
    border: 1px solid rgba(30, 41, 59, 0.4);
    background-color: transparent;
    border-radius: 10px;
}
QTabBar::tab {
    background-color: transparent;
    color: #64748b;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 20px;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.3px;
}
QTabBar::tab:hover {
    color: #94a3b8;
    border-bottom: 2px solid rgba(0, 240, 255, 0.2);
}
QTabBar::tab:selected {
    color: #00f0ff;
    border-bottom: 2px solid #00f0ff;
}

/* --- Glass Cards (GroupBox) --- */
QGroupBox {
    background-color: rgba(10, 15, 26, 0.55);
    border: 1px solid rgba(30, 41, 59, 0.45);
    border-radius: 10px;
    margin-top: 22px;
    padding: 24px 14px 14px 14px;
    font-weight: 700;
    color: #00f0ff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 4px;
    padding: 0 8px;
    color: #00f0ff;
    font-size: 11px;
    letter-spacing: 1px;
    background-color: rgba(10, 15, 26, 0.9);
    border-radius: 4px;
}

/* --- Labels --- */
QLabel {
    color: #cbd5e1;
    background: transparent;
}
QLabel#dialog_title {
    color: #00f0ff;
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#dialog_subtitle {
    color: #64748b;
    font-size: 11px;
}
QLabel#theme_info {
    color: #64748b;
    font-style: italic;
    font-size: 11px;
    padding: 4px 0;
}
QLabel#speed_value {
    color: #00f0ff;
    font-weight: 700;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    min-width: 32px;
}

/* --- Inputs --- */
QLineEdit, QSpinBox, QComboBox {
    background-color: rgba(15, 23, 42, 0.6);
    color: #f1f5f9;
    border: 1px solid rgba(51, 65, 85, 0.5);
    border-radius: 8px;
    padding: 6px 12px;
    min-height: 20px;
    font-size: 12px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid rgba(0, 240, 255, 0.6);
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: rgba(30, 41, 59, 0.5);
    border: none;
    border-left: 1px solid rgba(51, 65, 85, 0.4);
    width: 20px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: rgba(51, 65, 85, 0.6);
}
QSpinBox::up-button { border-top-right-radius: 8px; }
QSpinBox::down-button { border-bottom-right-radius: 8px; }
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #64748b;
}
QComboBox QAbstractItemView {
    background-color: #0c1220;
    color: #e2e8f0;
    border: 1px solid rgba(51, 65, 85, 0.5);
    border-radius: 8px;
    selection-background-color: rgba(0, 240, 255, 0.15);
    selection-color: #00f0ff;
    outline: 0;
    padding: 4px;
}

/* --- Checkboxes --- */
QCheckBox {
    spacing: 8px;
    color: #cbd5e1;
    font-weight: 600;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    background-color: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(51, 65, 85, 0.5);
    border-radius: 5px;
}
QCheckBox::indicator:checked {
    background-color: #00f0ff;
    border: 1px solid #00f0ff;
}
QCheckBox::indicator:unchecked:hover {
    border: 1px solid rgba(0, 240, 255, 0.4);
}

/* --- Sliders --- */
QSlider::groove:horizontal {
    background-color: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(51, 65, 85, 0.4);
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background-color: #00f0ff;
    border: none;
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background-color: #33f5ff;
    width: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(0,240,255,0.15), stop:1 rgba(0,240,255,0.35));
    border-radius: 3px;
}

/* --- TextEdit --- */
QTextEdit {
    background-color: rgba(15, 23, 42, 0.5);
    color: #e2e8f0;
    border: 1px solid rgba(51, 65, 85, 0.4);
    border-radius: 8px;
    padding: 8px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
}
QTextEdit:focus {
    border: 1px solid rgba(0, 240, 255, 0.5);
}

/* --- Scrollbar --- */
QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background-color: rgba(30, 41, 59, 0.6);
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background-color: rgba(51, 65, 85, 0.7);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* --- Buttons (base) --- */
QPushButton {
    background-color: rgba(30, 41, 59, 0.7);
    color: #f1f5f9;
    border: 1px solid rgba(51, 65, 85, 0.6);
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton:hover {
    background-color: rgba(51, 65, 85, 0.7);
    border: 1px solid rgba(71, 85, 105, 0.7);
}
QPushButton:pressed {
    background-color: rgba(15, 23, 42, 0.8);
}
QPushButton:disabled {
    background-color: rgba(15, 23, 42, 0.4);
    color: #475569;
    border-color: rgba(30, 41, 59, 0.3);
}

/* Save button — cyan accent */
QPushButton#save_btn {
    background-color: rgba(0, 240, 255, 0.08);
    color: #00f0ff;
    border: 1px solid rgba(0, 240, 255, 0.4);
}
QPushButton#save_btn:hover {
    background-color: rgba(0, 240, 255, 0.18);
    border-color: rgba(0, 240, 255, 0.6);
}

/* Cancel button — subtle */
QPushButton#cancel_btn {
    background-color: rgba(30, 41, 59, 0.5);
    color: #94a3b8;
    border: 1px solid rgba(51, 65, 85, 0.5);
}
QPushButton#cancel_btn:hover {
    color: #f1f5f9;
    background-color: rgba(51, 65, 85, 0.6);
}

/* Reset button — danger red */
QPushButton#reset_btn {
    background-color: rgba(255, 0, 60, 0.06);
    color: #ff003c;
    border: 1px solid rgba(255, 0, 60, 0.3);
}
QPushButton#reset_btn:hover {
    background-color: rgba(255, 0, 60, 0.15);
    border-color: rgba(255, 0, 60, 0.5);
}

/* Apply Theme button — cyan */
QPushButton#apply_theme_btn {
    background-color: rgba(0, 240, 255, 0.06);
    color: #00f0ff;
    border: 1px solid rgba(0, 240, 255, 0.35);
    padding: 7px 16px;
}
QPushButton#apply_theme_btn:hover {
    background-color: rgba(0, 240, 255, 0.15);
    border-color: rgba(0, 240, 255, 0.5);
}

/* Start Rainbow — green accent */
QPushButton#start_rainbow_btn {
    background-color: rgba(0, 255, 136, 0.06);
    color: #00ff88;
    border: 1px solid rgba(0, 255, 136, 0.35);
}
QPushButton#start_rainbow_btn:hover {
    background-color: rgba(0, 255, 136, 0.15);
    border-color: rgba(0, 255, 136, 0.5);
}

/* Stop Rainbow — red accent */
QPushButton#stop_rainbow_btn {
    background-color: rgba(255, 0, 60, 0.06);
    color: #ff003c;
    border: 1px solid rgba(255, 0, 60, 0.3);
}
QPushButton#stop_rainbow_btn:hover {
    background-color: rgba(255, 0, 60, 0.15);
    border-color: rgba(255, 0, 60, 0.5);
}

/* Quick theme buttons */
QPushButton#quick_theme_btn {
    padding: 6px 14px;
    font-size: 11px;
    border-radius: 6px;
}

/* Separator line */
QFrame#separator {
    background-color: rgba(30, 41, 59, 0.4);
    max-height: 1px;
    margin: 8px 0;
}

/* --- MessageBox override --- */
QMessageBox {
    background-color: #0a0f1a;
    color: #e2e8f0;
}
QMessageBox QPushButton {
    min-width: 96px;
    min-height: 32px;
}
"""

class SettingsDialog(QDialog):
    """DupeZ Settings — cyber HUD styled dialog"""

    settings_changed = pyqtSignal(dict)

    def __init__(self, current_settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.current_settings = current_settings
        self.new_settings = current_settings

        self.setWindowTitle("DupeZ Settings")
        self.setModal(True)
        self.resize(640, 560)
        self.setMinimumSize(520, 420)
        self.setStyleSheet(SETTINGS_STYLE)

        self._build_ui()
        self._load_settings()
        self.update_theme_info()

    # UI Construction
    def _build_ui(self) -> None:
        root = QVBoxLayout()
        root.setSpacing(10)
        root.setContentsMargins(16, 14, 16, 14)

        # Header
        header = QHBoxLayout()
        title = QLabel("SETTINGS")
        title.setObjectName("dialog_title")
        header.addWidget(title)
        header.addStretch()
        subtitle = QLabel("Configure DupeZ behavior")
        subtitle.setObjectName("dialog_subtitle")
        header.addWidget(subtitle)
        root.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self._tab_general(), "General")
        self.tab_widget.addTab(self._tab_network(), "Network")
        self.tab_widget.addTab(self._tab_smart(), "Smart Mode")
        self.tab_widget.addTab(self._tab_interface(), "Interface")
        self.tab_widget.addTab(self._tab_advanced(), "Advanced")
        root.addWidget(self.tab_widget, 1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("save_btn")
        self.save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.save_btn.clicked.connect(self.save_settings)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.cancel_btn.clicked.connect(self.reject)

        self.reset_btn = QPushButton("Reset Defaults")
        self.reset_btn.setObjectName("reset_btn")
        self.reset_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.reset_btn.clicked.connect(self.reset_to_defaults)

        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.reset_btn)
        root.addLayout(btn_row)

        self.setLayout(root)

    # --- General Tab ---
    def _tab_general(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout()
        lay.setSpacing(12)
        lay.setContentsMargins(4, 4, 4, 4)

        g = QGroupBox("Auto-Scan")
        fl = QFormLayout()
        fl.setVerticalSpacing(10)
        fl.setContentsMargins(10, 8, 10, 8)
        self.auto_scan_checkbox = QCheckBox("Enable automatic scanning")
        fl.addRow("Auto-Scan:", self.auto_scan_checkbox)

        self.scan_interval_spinbox = QSpinBox()
        self.scan_interval_spinbox.setRange(30, 3600)
        self.scan_interval_spinbox.setSuffix(" sec")
        fl.addRow("Interval:", self.scan_interval_spinbox)

        self.max_devices_spinbox = QSpinBox()
        self.max_devices_spinbox.setRange(10, 500)
        self.max_devices_spinbox.setSuffix(" devices")
        fl.addRow("Max Devices:", self.max_devices_spinbox)
        g.setLayout(fl)
        lay.addWidget(g)

        g2 = QGroupBox("Logging")
        fl2 = QFormLayout()
        fl2.setVerticalSpacing(10)
        fl2.setContentsMargins(10, 8, 10, 8)
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        fl2.addRow("Log Level:", self.log_level_combo)
        g2.setLayout(fl2)
        lay.addWidget(g2)

        lay.addStretch()
        w.setLayout(lay)
        return w

    # --- Network Tab ---
    def _tab_network(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout()
        lay.setSpacing(12)
        lay.setContentsMargins(4, 4, 4, 4)

        g = QGroupBox("Scanning")
        fl = QFormLayout()
        fl.setVerticalSpacing(10)
        fl.setContentsMargins(10, 8, 10, 8)

        self.ping_timeout_spinbox = QSpinBox()
        self.ping_timeout_spinbox.setRange(1, 10)
        self.ping_timeout_spinbox.setSuffix(" sec")
        fl.addRow("Ping Timeout:", self.ping_timeout_spinbox)

        self.max_threads_spinbox = QSpinBox()
        self.max_threads_spinbox.setRange(5, 50)
        self.max_threads_spinbox.setSuffix(" threads")
        fl.addRow("Threads:", self.max_threads_spinbox)

        self.quick_scan_checkbox = QCheckBox("Fast ARP-only mode")
        fl.addRow("Quick Scan:", self.quick_scan_checkbox)
        g.setLayout(fl)
        lay.addWidget(g)

        lay.addStretch()
        w.setLayout(lay)
        return w

    # --- Smart Mode Tab ---
    def _tab_smart(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        w = QWidget()
        lay = QVBoxLayout()
        lay.setSpacing(12)
        lay.setContentsMargins(4, 4, 4, 4)

        g1 = QGroupBox("Smart Mode")
        fl1 = QFormLayout()
        fl1.setVerticalSpacing(10)
        fl1.setContentsMargins(10, 8, 10, 8)
        self.smart_mode_checkbox = QCheckBox("Enable traffic analysis")
        fl1.addRow("Smart Mode:", self.smart_mode_checkbox)
        self.auto_block_checkbox = QCheckBox("Auto-block suspicious devices")
        fl1.addRow("Auto-Block:", self.auto_block_checkbox)
        g1.setLayout(fl1)
        lay.addWidget(g1)

        g2 = QGroupBox("Thresholds")
        fl2 = QFormLayout()
        fl2.setVerticalSpacing(10)
        fl2.setContentsMargins(10, 8, 10, 8)
        self.high_traffic_threshold = QSpinBox()
        self.high_traffic_threshold.setRange(100, 10000)
        self.high_traffic_threshold.setSuffix(" KB/s")
        fl2.addRow("High Traffic:", self.high_traffic_threshold)

        self.connection_limit = QSpinBox()
        self.connection_limit.setRange(10, 1000)
        self.connection_limit.setSuffix(" conn")
        fl2.addRow("Connection Limit:", self.connection_limit)

        self.suspicious_activity_threshold = QSpinBox()
        self.suspicious_activity_threshold.setRange(5, 100)
        self.suspicious_activity_threshold.setSuffix(" events/min")
        fl2.addRow("Suspicious Activity:", self.suspicious_activity_threshold)
        g2.setLayout(fl2)
        lay.addWidget(g2)

        g3 = QGroupBox("Blocking")
        fl3 = QFormLayout()
        fl3.setVerticalSpacing(10)
        fl3.setContentsMargins(10, 8, 10, 8)
        self.block_duration_spinbox = QSpinBox()
        self.block_duration_spinbox.setRange(1, 1440)
        self.block_duration_spinbox.setSuffix(" min")
        fl3.addRow("Block Duration:", self.block_duration_spinbox)

        self.whitelist_edit = QTextEdit()
        self.whitelist_edit.setMaximumHeight(70)
        self.whitelist_edit.setPlaceholderText("One IP per line")
        fl3.addRow("Whitelist:", self.whitelist_edit)
        g3.setLayout(fl3)
        lay.addWidget(g3)

        lay.addStretch()
        w.setLayout(lay)
        scroll.setWidget(w)
        return scroll

    # --- Interface Tab ---
    def _tab_interface(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        w = QWidget()
        lay = QVBoxLayout()
        lay.setSpacing(12)
        lay.setContentsMargins(4, 4, 4, 4)

        # Theme selection
        g1 = QGroupBox("Theme")
        t_lay = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light", "hacker", "rainbow"])
        self.theme_combo.currentTextChanged.connect(self.on_theme_selected)
        row.addWidget(self.theme_combo, 1)

        self.apply_theme_btn = QPushButton("Apply")
        self.apply_theme_btn.setObjectName("apply_theme_btn")
        self.apply_theme_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.apply_theme_btn.clicked.connect(self.apply_selected_theme)
        row.addWidget(self.apply_theme_btn)
        t_lay.addLayout(row)

        # Quick theme buttons
        qrow = QHBoxLayout()
        qrow.setSpacing(6)
        for name in ("Dark", "Light", "Hacker", "Rainbow"):
            btn = QPushButton(name)
            btn.setObjectName("quick_theme_btn")
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda checked, n=name.lower(): self.apply_theme(n))
            qrow.addWidget(btn)
            # Store references for later
            setattr(self, f"{name.lower()}_theme_btn", btn)
        t_lay.addLayout(qrow)

        g1.setLayout(t_lay)
        lay.addWidget(g1)

        # Rainbow controls
        g2 = QGroupBox("Rainbow Mode")
        r_lay = QVBoxLayout()

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        self.rainbow_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.rainbow_speed_slider.setRange(1, 100)
        self.rainbow_speed_slider.setValue(20)
        self.rainbow_speed_slider.valueChanged.connect(self.on_rainbow_speed_changed)
        speed_row.addWidget(self.rainbow_speed_slider, 1)

        self.speed_label = QLabel("2.0")
        self.speed_label.setObjectName("speed_value")
        speed_row.addWidget(self.speed_label)
        r_lay.addLayout(speed_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for attr, text, handler in [
            ("start_rainbow_btn", "Start Rainbow", self.start_rainbow_mode),
            ("stop_rainbow_btn", "Stop Rainbow", self.stop_rainbow_mode),
        ]:
            btn = QPushButton(text); btn.setObjectName(attr)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(handler); setattr(self, attr, btn); btn_row.addWidget(btn)
        r_lay.addLayout(btn_row)

        self.theme_info_label = QLabel("Current Theme: Dark")
        self.theme_info_label.setObjectName("theme_info")
        r_lay.addWidget(self.theme_info_label)

        g2.setLayout(r_lay)
        lay.addWidget(g2)

        # Display settings
        g3 = QGroupBox("Display")
        fl3 = QFormLayout()
        fl3.setVerticalSpacing(10)
        fl3.setContentsMargins(10, 8, 10, 8)

        for attr, label, row_label in [
            ("auto_refresh_checkbox", "Auto-refresh device list", "Auto-Refresh:"),
            ("show_device_icons_checkbox", "Show device type icons", "Device Icons:"),
            ("show_status_indicators_checkbox", "Show status indicators", "Status Indicators:"),
            ("compact_view_checkbox", "Compact row height", "Compact View:"),
        ]:
            cb = QCheckBox(label); setattr(self, attr, cb); fl3.addRow(row_label, cb)

        self.refresh_interval_spinbox = QSpinBox()
        self.refresh_interval_spinbox.setRange(10, 300)
        self.refresh_interval_spinbox.setSuffix(" sec")
        fl3.addRow("Refresh Interval:", self.refresh_interval_spinbox)
        g3.setLayout(fl3)
        lay.addWidget(g3)

        # Map / GPU
        g_map = QGroupBox("Map Renderer")
        fl_map = QFormLayout()
        fl_map.setVerticalSpacing(10)
        fl_map.setContentsMargins(10, 8, 10, 8)

        self.map_renderer_combo = QComboBox()
        # Values match DUPEZ_MAP_RENDERER env var expectations
        self.map_renderer_combo.addItems(["auto", "gpu", "swiftshader", "software"])
        fl_map.addRow("Renderer:", self.map_renderer_combo)

        _renderer_desc = QLabel(
            "auto = detect GPU automatically · gpu = force hardware · "
            "swiftshader = software GL · software = CPU only")
        _renderer_desc.setWordWrap(True)
        _renderer_desc.setStyleSheet("color: #64748b; font-size: 10px;")
        fl_map.addRow("", _renderer_desc)

        import os as _os
        _cur_tier = _os.environ.get("DUPEZ_MAP_RENDERER_TIER", "tier3_cpu")
        _tier_names = {
            "tier1_hw": "GPU hardware raster",
            "tier2_swiftshader": "SwiftShader software GL",
            "tier3_cpu": "CPU raster (no GPU)",
        }
        self._map_tier_label = QLabel(
            f"Current session: {_tier_names.get(_cur_tier, _cur_tier)}")
        self._map_tier_label.setObjectName("map_tier_info")
        self._map_tier_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        fl_map.addRow("Active:", self._map_tier_label)

        self._map_restart_label = QLabel(
            "Changing this will prompt a restart.")
        self._map_restart_label.setStyleSheet(
            "color: #fbbf24; font-size: 10px; font-style: italic;")
        fl_map.addRow("", self._map_restart_label)

        g_map.setLayout(fl_map)
        lay.addWidget(g_map)

        # Game Profile section removed — DupeZ is DayZ-only

        # Notifications
        g4 = QGroupBox("Notifications")
        fl4 = QFormLayout()
        fl4.setVerticalSpacing(10)
        fl4.setContentsMargins(10, 8, 10, 8)
        for attr, label, row_label in [
            ("show_notifications_checkbox", "Desktop notifications", "Notifications:"),
            ("sound_alerts_checkbox", "Sound alerts", "Sound:"),
        ]:
            cb = QCheckBox(label); setattr(self, attr, cb); fl4.addRow(row_label, cb)
        g4.setLayout(fl4); lay.addWidget(g4)

        lay.addStretch()
        w.setLayout(lay)
        scroll.setWidget(w)
        return scroll

    # --- Advanced Tab ---
    @staticmethod
    def _make_row_widget(label_text: str, control: QWidget) -> QWidget:
        """Build a label + control inside a container widget with a hard height."""
        container = QWidget()
        container.setFixedHeight(44)
        container.setStyleSheet("background: transparent;")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 4, 0, 4)
        lbl = QLabel(label_text)
        lbl.setFixedWidth(140)
        row.addWidget(lbl)
        row.addWidget(control, 1)
        return container

    def _tab_advanced(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        w = QWidget()
        lay = QVBoxLayout()
        lay.setSpacing(14)
        lay.setContentsMargins(4, 4, 4, 4)

        # ── Performance ──
        g1 = QGroupBox("Performance")
        g1_lay = QVBoxLayout()
        g1_lay.setSpacing(4)
        g1_lay.setContentsMargins(12, 24, 12, 12)

        self.cache_duration_spinbox = QSpinBox()
        self.cache_duration_spinbox.setRange(30, 600)
        self.cache_duration_spinbox.setSuffix(" sec")
        g1_lay.addWidget(self._make_row_widget("Cache Duration:", self.cache_duration_spinbox))

        self.memory_limit_spinbox = QSpinBox()
        self.memory_limit_spinbox.setRange(50, 1000)
        self.memory_limit_spinbox.setSuffix(" MB")
        g1_lay.addWidget(self._make_row_widget("Memory Limit:", self.memory_limit_spinbox))

        g1.setLayout(g1_lay)
        lay.addWidget(g1)

        # ── Security ──
        g2 = QGroupBox("Security")
        g2_lay = QVBoxLayout()
        g2_lay.setSpacing(4)
        g2_lay.setContentsMargins(12, 24, 12, 12)

        self.require_admin_checkbox = QCheckBox("Require administrator")
        g2_lay.addWidget(self._make_row_widget("Admin Required:", self.require_admin_checkbox))
        self.encrypt_logs_checkbox = QCheckBox("Encrypt log files")
        g2_lay.addWidget(self._make_row_widget("Encrypt Logs:", self.encrypt_logs_checkbox))

        g2.setLayout(g2_lay)
        lay.addWidget(g2)

        # ── Debug ──
        g3 = QGroupBox("Debug")
        g3_lay = QVBoxLayout()
        g3_lay.setSpacing(4)
        g3_lay.setContentsMargins(12, 24, 12, 12)

        self.debug_mode_checkbox = QCheckBox("Enable debug mode")
        g3_lay.addWidget(self._make_row_widget("Debug Mode:", self.debug_mode_checkbox))
        self.verbose_logging_checkbox = QCheckBox("Verbose logging")
        g3_lay.addWidget(self._make_row_widget("Verbose:", self.verbose_logging_checkbox))

        g3.setLayout(g3_lay)
        lay.addWidget(g3)

        lay.addStretch()
        w.setLayout(lay)
        scroll.setWidget(w)
        return scroll

    def _widget_map(self) -> list:
        """Return (widget, setting_key) pairs for all settings controls."""
        return [
            (self.auto_scan_checkbox, 'auto_scan'), (self.scan_interval_spinbox, 'scan_interval'),
            (self.max_devices_spinbox, 'max_devices'), (self.log_level_combo, 'log_level'),
            (self.ping_timeout_spinbox, 'ping_timeout'), (self.max_threads_spinbox, 'max_threads'),
            (self.quick_scan_checkbox, 'quick_scan'), (self.smart_mode_checkbox, 'smart_mode'),
            (self.auto_block_checkbox, 'auto_block'), (self.high_traffic_threshold, 'high_traffic_threshold'),
            (self.connection_limit, 'connection_limit'),
            (self.suspicious_activity_threshold, 'suspicious_activity_threshold'),
            (self.block_duration_spinbox, 'block_duration'), (self.theme_combo, 'theme'),
            (self.auto_refresh_checkbox, 'auto_refresh'), (self.refresh_interval_spinbox, 'refresh_interval'),
            (self.show_device_icons_checkbox, 'show_device_icons'),
            (self.show_status_indicators_checkbox, 'show_status_indicators'),
            (self.compact_view_checkbox, 'compact_view'),
            (self.show_notifications_checkbox, 'show_notifications'),
            (self.sound_alerts_checkbox, 'sound_alerts'), (self.cache_duration_spinbox, 'cache_duration'),
            (self.memory_limit_spinbox, 'memory_limit'), (self.require_admin_checkbox, 'require_admin'),
            (self.encrypt_logs_checkbox, 'encrypt_logs'), (self.debug_mode_checkbox, 'debug_mode'),
            (self.verbose_logging_checkbox, 'verbose_logging'),
            (self.map_renderer_combo, 'map_renderer'),
        ]

    def _apply_settings_to_widgets(self, s) -> None:
        """Set widget values from an AppSettings object."""
        for widget, key in self._widget_map():
            val = getattr(s, key, None)
            if val is None:
                continue
            if isinstance(widget, QCheckBox):
                widget.setChecked(val)
            elif isinstance(widget, QSpinBox):
                widget.setValue(val)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(val))
        if hasattr(s, 'whitelist') and s.whitelist:
            self.whitelist_edit.setPlainText('\n'.join(s.whitelist))

    def _read_widgets_to_dict(self) -> dict:
        """Read all widget values into a dict keyed by setting name."""
        d = {}
        for widget, key in self._widget_map():
            if isinstance(widget, QCheckBox):
                d[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                d[key] = widget.value()
            elif isinstance(widget, QComboBox):
                d[key] = widget.currentText()
        d['whitelist'] = (self.whitelist_edit.toPlainText().split('\n')
                          if self.whitelist_edit.toPlainText() else [])
        return d

    def _load_settings(self) -> None:
        """Populate all controls from current_settings."""
        try:
            self._apply_settings_to_widgets(self.current_settings)
        except Exception as e:
            log_error(f"Error loading settings: {e}")

    def save_settings(self) -> None:
        """Collect all controls → AppSettings → emit → accept."""
        try:
            d = self._read_widgets_to_dict()
            new_settings = AppSettings(**d)
            self.new_settings = new_settings
            self.settings_changed.emit({k: d[k] for k in (
                'theme', 'auto_refresh', 'refresh_interval', 'show_device_icons',
                'show_status_indicators', 'compact_view', 'show_notifications', 'sound_alerts')})
            if hasattr(self, 'controller') and self.controller:
                self.controller.update_settings(new_settings)
            log_info("Settings saved")

            # Check if map renderer changed — requires app restart
            old_renderer = getattr(self.current_settings, 'map_renderer', 'auto')
            new_renderer = d.get('map_renderer', 'auto')
            if new_renderer != old_renderer:
                self._prompt_restart_for_renderer(new_renderer)
            else:
                QMessageBox.information(self, "Settings", "Settings saved successfully.")

            self.accept()
        except Exception as e:
            log_error(f"Error saving settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save settings:\n{e}")

    def _prompt_restart_for_renderer(self, new_renderer: str) -> None:
        """Ask the user to restart for a map renderer change, then relaunch."""
        _labels = {
            "auto": "Auto-detect",
            "gpu": "GPU (hardware)",
            "swiftshader": "SwiftShader",
            "software": "CPU (software)",
        }
        label = _labels.get(new_renderer, new_renderer)
        reply = QMessageBox.question(
            self,
            "Restart Required",
            f"Map renderer changed to <b>{label}</b>.<br><br>"
            "DupeZ needs to restart for this to take effect.<br>"
            "Restart now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._do_restart()
        else:
            QMessageBox.information(
                self, "Settings",
                "Settings saved. The new renderer will apply next time you launch DupeZ."
            )

    @staticmethod
    def _do_restart() -> None:
        """Relaunch the application and exit the current process."""
        import os
        import sys

        log_info("Restarting DupeZ for map renderer change...")

        if getattr(sys, "frozen", False):
            # PyInstaller frozen exe — relaunch the same exe
            exe = sys.executable
            args = sys.argv[1:]
        else:
            # Dev mode — relaunch python with the entry script
            exe = sys.executable
            # Find the entry point (dupez.py in the repo root)
            entry = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))),
                "dupez.py",
            )
            args = [entry] + sys.argv[1:]

        try:
            if sys.platform == "win32":
                # On Windows, spawn a detached successor through
                # safe_subprocess so argv validation, CREATE_NO_WINDOW,
                # and audit logging all apply. ``exe`` here is
                # ``sys.executable`` or the frozen binary itself — already
                # trusted, so we pass trusted_executable=True.
                from app.core import safe_subprocess as _safe_sp
                _safe_sp.spawn_detached(
                    [exe] + list(args),
                    trusted_executable=True,
                    intent="settings_dialog.restart_self",
                )
            else:
                # Unix — os.execv replaces the current process
                os.execv(exe, [exe] + args)
        except Exception as exc:
            log_error(f"Restart failed: {exc}")
            # Non-fatal — the user can restart manually
            return

        # Exit the current instance
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.quit()
        sys.exit(0)

    def reset_to_defaults(self) -> None:
        """Reset all controls to AppSettings() defaults."""
        try:
            reply = QMessageBox.question(
                self, "Reset Settings", "Reset all settings to factory defaults?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._apply_settings_to_widgets(AppSettings())
            self.whitelist_edit.clear()
            log_info("Settings reset to defaults")
        except Exception as e:
            log_error(f"Error resetting settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to reset:\n{e}")

    def get_new_settings(self) -> AppSettings:
        return self.new_settings

    # Theme controls

    @staticmethod
    def _tm():
        """Lazy-import the theme manager singleton."""
        from app.themes.theme_manager import get_theme_manager
        return get_theme_manager()

    def on_theme_selected(self, theme_name: str) -> None:
        """Apply theme immediately when the combo selection changes."""
        try:
            self.apply_theme(theme_name)
        except Exception as e:
            log_error(f"Error handling theme selection: {e}")

    def apply_selected_theme(self) -> None:
        try:
            self.apply_theme(self.theme_combo.currentText())
        except Exception as e:
            log_error(f"Error applying selected theme: {e}")

    def apply_theme(self, theme_name: str) -> None:
        try:
            tm = self._tm()
            if tm.get_current_theme() == theme_name:
                return
            if tm.apply_theme(theme_name):
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentText(theme_name)
                self.theme_combo.blockSignals(False)
                self.setStyleSheet(SETTINGS_STYLE)
                self.update_theme_info()
                log_info(f"Theme applied: {theme_name}")
        except Exception as e:
            log_error(f"Error applying theme {theme_name}: {e}")

    def on_rainbow_speed_changed(self, value: int) -> None:
        try:
            speed = value / 10.0
            self.speed_label.setText(f"{speed:.1f}")
            self._tm().set_rainbow_speed(speed)
        except Exception as e:
            log_error(f"Error changing rainbow speed: {e}")

    def start_rainbow_mode(self) -> None:
        try:
            self._tm().start_rainbow_mode()
            self.setStyleSheet(SETTINGS_STYLE)
            self.update_theme_info()
        except Exception as e:
            log_error(f"Error starting rainbow mode: {e}")

    def stop_rainbow_mode(self) -> None:
        try:
            tm = self._tm()
            tm.stop_rainbow_mode()
            tm.apply_theme("dark")
            self.theme_combo.setCurrentText("dark")
            self.setStyleSheet(SETTINGS_STYLE)
            self.update_theme_info()
        except Exception as e:
            log_error(f"Error stopping rainbow mode: {e}")

    def update_theme_info(self) -> None:
        try:
            tm = self._tm()
            current = tm.get_current_theme()
            rainbow = tm.is_rainbow_active()

            text = f"Current Theme: {current.title()}"
            if rainbow:
                text += f"  •  Rainbow Active (Speed {tm.get_rainbow_speed():.1f})"

            self.theme_info_label.setText(text)
            self.start_rainbow_btn.setEnabled(not rainbow)
            self.stop_rainbow_btn.setEnabled(rainbow)
        except Exception as e:
            log_error(f"Error updating theme info: {e}")

