# app/gui/panels/gpc_panel.py — GPC / CronusZEN script panel widget
"""Extracted from ClumsyControlView._build_gpc_panel and GPC handler methods."""

from __future__ import annotations

import os
import re
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGroupBox, QMessageBox,
)
from PyQt6.QtCore import pyqtSlot

from app.logs.logger import log_info, log_error

# GPC / CronusZEN integration — optional
try:
    from app.gpc.gpc_generator import GPCGenerator, list_templates, get_template
    from app.gpc.device_bridge import DeviceMonitor, scan_devices
    GPC_AVAILABLE = True
except ImportError:
    GPC_AVAILABLE = False

__all__ = ["GPCPanel"]


class GPCPanel(QWidget):
    """GPC script generation, export, and device sync panel."""

    def __init__(self, parent_view, parent=None) -> None:
        super().__init__(parent)
        self._view = parent_view
        self._gpc_generator = None
        self._gpc_last_source = ""
        self._gpc_monitor = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        gpc_group = self._view._card("GPC / CRONUS")
        gl = QVBoxLayout()
        gl.setSpacing(6)

        if not GPC_AVAILABLE:
            missing_label = self._view._lbl(
                "GPC module not available", "#6b7280", italic=True)
            gl.addWidget(missing_label)
            gpc_group.setLayout(gl)
            layout.addWidget(gpc_group)
            return

        # Device status
        self.gpc_device_label = QLabel("Device: Scanning...")
        self.gpc_device_label.setStyleSheet(self._device_status_qss("#94a3b8"))
        gl.addWidget(self.gpc_device_label)

        # Template selector
        tmpl_row = QHBoxLayout()
        tmpl_label = self._view._lbl("SCRIPT:", bold=True, w=48)
        tmpl_row.addWidget(tmpl_label)

        self.gpc_template_combo = QComboBox()
        for tmpl in list_templates():
            self.gpc_template_combo.addItem(
                f"{tmpl['name']} ({tmpl['game']})", tmpl['name'])
        self.gpc_template_combo.setStyleSheet(self._view._COMBO_QSS)
        tmpl_row.addWidget(self.gpc_template_combo, 1)
        gl.addLayout(tmpl_row)

        # Template description
        self.gpc_desc_label = self._view._lbl("", "#6b7280", size=9)
        self.gpc_desc_label.setWordWrap(True)
        gl.addWidget(self.gpc_desc_label)
        self.gpc_template_combo.currentIndexChanged.connect(
            self._on_gpc_template_changed)
        self._on_gpc_template_changed()

        # Buttons
        btn_row = QHBoxLayout()
        for attr, text, color, handler, kw in [
            ("btn_gpc_generate", "GENERATE", "#ff6b35",
             self._on_gpc_generate, {}),
            ("btn_gpc_export", "EXPORT .GPC", "#00d9ff",
             self._on_gpc_export, {"enabled": False}),
            ("btn_gpc_sync", "SYNC TIMING", "#e040fb",
             self._on_gpc_sync,
             {"tip": "Generate script synced with current disruption settings"}),
        ]:
            btn = self._view._make_btn(text, color, "#0a1628", h=28, **kw)
            btn.clicked.connect(handler)
            setattr(self, attr, btn)
            btn_row.addWidget(btn)
        gl.addLayout(btn_row)

        # Generated script preview
        self.gpc_preview_label = QLabel("")
        self.gpc_preview_label.setStyleSheet(
            "color: #94a3b8; font-size: 9px; "
            "font-family: 'Cascadia Code', 'Consolas', monospace; "
            "padding: 8px; background: rgba(8,12,22,0.7); "
            "border: 1px solid rgba(30,41,59,0.4); border-radius: 6px;")
        self.gpc_preview_label.setWordWrap(True)
        self.gpc_preview_label.setMaximumHeight(120)
        self.gpc_preview_label.hide()
        gl.addWidget(self.gpc_preview_label)

        gpc_group.setLayout(gl)
        layout.addWidget(gpc_group)

        # State
        self._gpc_generator = GPCGenerator()
        self._gpc_last_source = ""

        # Device monitor
        self._gpc_monitor = DeviceMonitor(
            on_connect=lambda dev: self._gpc_device_event(
                f"Connected: {dev.name}"),
            on_disconnect=lambda dev: self._gpc_device_event(
                f"Disconnected: {dev.name}"),
        )
        self._gpc_monitor.start()

        # Initial device scan
        def _initial_scan():
            devices = scan_devices()
            msg = (f"Device: {devices[0].name} ({devices[0].device_type.upper()})"
                   if devices
                   else "Device: None detected — scripts export to file")
            self._view._invoke_main("_panel_gpc_set_device_label", msg)

        threading.Thread(target=_initial_scan, daemon=True).start()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _on_gpc_template_changed(self) -> None:
        if not GPC_AVAILABLE:
            return
        name = self.gpc_template_combo.currentData()
        if name:
            tmpl = get_template(name)
            if tmpl:
                self.gpc_desc_label.setText(tmpl.description)

    def _gpc_store_preview(self, source: str, label: str) -> None:
        self._gpc_last_source = source
        self.btn_gpc_export.setEnabled(True)
        self.gpc_preview_label.setText(
            source[:500] + ("..." if len(source) > 500 else ""))
        self.gpc_preview_label.show()
        log_info(f"GPC: {label} ({len(source)} chars)")

    def _on_gpc_generate(self) -> None:
        if not GPC_AVAILABLE:
            return
        name = self.gpc_template_combo.currentData()
        tmpl = get_template(name) if name else None
        if tmpl:
            self._gpc_store_preview(
                self._gpc_generator.generate(tmpl),
                f"generated script '{name}'")

    def _on_gpc_sync(self) -> None:
        if not GPC_AVAILABLE:
            return
        params = self._view._collect_params()
        methods = self._view._get_active_methods()
        source = self._gpc_generator.generate_from_disruption(
            {"methods": methods, "params": params})
        self._gpc_store_preview(source, "generated synced script")

    def _on_gpc_export(self) -> None:
        if not self._gpc_last_source or not GPC_AVAILABLE:
            return

        from app.gpc.device_bridge import get_default_export_path
        export_dir = get_default_export_path()
        name = self.gpc_template_combo.currentData() or "dupez_script"
        safe_name = re.sub(r'[^\w\-]', '_', name.lower())
        path = os.path.join(export_dir, f"{safe_name}.gpc")

        ok = self._gpc_generator.export_to_file(self._gpc_last_source, path)
        if ok:
            QMessageBox.information(
                self, "GPC Export", f"Script exported to:\n{path}")
        else:
            QMessageBox.warning(
                self, "GPC Export", "Failed to export — check logs")

    def _gpc_device_event(self, msg: str) -> None:
        self._view._invoke_main("_panel_gpc_set_device_label", msg)

    @pyqtSlot(object)
    def set_device_label(self, msg) -> None:
        if hasattr(self, 'gpc_device_label'):
            self.gpc_device_label.setText(msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _device_status_qss(color: str) -> str:
        return (f"color: {color}; font-size: 10px; padding: 4px 8px; "
                f"background: rgba(8,12,22,0.6); border: 1px solid {color}; "
                f"border-radius: 6px; font-weight: 600;")
