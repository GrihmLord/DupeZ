# app/gui/panels/gpc_panel.py — GPC / Game-Script device panel widget
"""GPC script generation, export, and device sync panel.

v5.6.7 generalization: the underlying engine (gpc_generator, device_bridge)
now supports Cronus Zen, Cronus Max, Titan One, and Titan Two — all of
which compile the same .gpc syntax. The panel label was updated from
``GPC / CRONUS`` to ``GAME SCRIPTS`` to reflect the broader device set,
and the device-status line now shows which IDE library will receive an
EXPORT (Zen Studio for Cronus, Gtuner for Titan, fallback to Documents
for any other / not-detected case).
"""

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

    # Human-friendly labels for each detected device_type. Used in the
    # device-status banner. Mapped from device_bridge._classify_device's
    # output strings. Anything not in this map renders as "Unknown".
    _DEVICE_LABELS = {
        "zen": "Cronus Zen",
        "max": "Cronus Max",
        "titan1": "Titan One",
        "titan2": "Titan Two",
        "cronus_other": "Cronus (model unknown)",
        "titan_other": "Titan (model unknown)",
        "unknown": "Game-script device",
    }

    def __init__(self, parent_view, parent=None) -> None:
        super().__init__(parent)
        self._view = parent_view
        self._gpc_generator = None
        self._gpc_last_source = ""
        self._gpc_monitor = None
        # v5.6.7: remember the currently-connected device's classification
        # so EXPORT routes the .gpc file to the matching IDE's library
        # (Zen Studio for Cronus, Gtuner for Titan). "" means nothing
        # connected → fall back to Documents/DupeZ/GPC.
        self._gpc_device_type: str = ""
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # v5.6.7: renamed from "GPC / CRONUS" → "GAME SCRIPTS" to reflect
        # the expanded device support (Cronus Zen/Max + Titan One/Two +
        # any future GPC-compatible device).
        gpc_group = self._view._card("GAME SCRIPTS")
        gl = QVBoxLayout()
        gl.setSpacing(6)

        if not GPC_AVAILABLE:
            missing_label = self._view._lbl(
                "Game-script module not available", "#6b7280", italic=True)
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
            on_connect=self._on_device_connect,
            on_disconnect=self._on_device_disconnect,
        )
        self._gpc_monitor.start()

        # Initial device scan
        def _initial_scan():
            devices = scan_devices()
            if devices:
                dev = devices[0]
                self._gpc_device_type = dev.device_type or ""
                label = self._DEVICE_LABELS.get(
                    dev.device_type, "Game-script device")
                msg = f"Device: {label} — {dev.name}"
            else:
                self._gpc_device_type = ""
                msg = "Device: None detected — scripts export to file"
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
        # v5.6.7: pass the connected device's type so the export folder
        # is whichever IDE library matches (Zen Studio vs Gtuner vs
        # CronusMAX Plus). Empty string is safe — falls back to the
        # Zen-first behavior we had pre-v5.6.7.
        export_dir = get_default_export_path(self._gpc_device_type)
        name = self.gpc_template_combo.currentData() or "dupez_script"
        safe_name = re.sub(r'[^\w\-]', '_', name.lower())
        path = os.path.join(export_dir, f"{safe_name}.gpc")

        ok = self._gpc_generator.export_to_file(self._gpc_last_source, path)
        if ok:
            QMessageBox.information(
                self, "Script Export", f"Script exported to:\n{path}")
        else:
            QMessageBox.warning(
                self, "Script Export", "Failed to export — check logs")

    # v5.6.7: connect/disconnect handlers update the cached device type
    # so EXPORT routes correctly. Previously these were inline lambdas
    # that only built a banner string; the device_type was thrown away.
    def _on_device_connect(self, dev) -> None:
        self._gpc_device_type = getattr(dev, "device_type", "") or ""
        label = self._DEVICE_LABELS.get(
            self._gpc_device_type, "Game-script device")
        self._gpc_device_event(f"Connected: {label} — {dev.name}")

    def _on_device_disconnect(self, dev) -> None:
        self._gpc_device_type = ""
        label = self._DEVICE_LABELS.get(
            getattr(dev, "device_type", "") or "", "Game-script device")
        self._gpc_device_event(f"Disconnected: {label} — {dev.name}")

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
