# plugins/example_ping_monitor/plugin.py — Example UI Panel Plugin
"""
Ping Monitor — a simple UI panel plugin that shows live latency
to devices on the network. Demonstrates the UIPanelPlugin API.
"""

import subprocess
import threading
import time
from typing import Dict

from app.plugins.base import UIPanelPlugin

try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QTableWidget, QTableWidgetItem, QHeaderView
    )
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
    from PyQt6.QtGui import QColor
    HAS_QT = True
except ImportError:
    HAS_QT = False

__all__ = ["PingSignals", "PingMonitorWidget", "PingMonitorPlugin"]


class PingSignals(QObject):
    """Thread-safe signal bridge for ping results."""
    result = pyqtSignal(str, float)  # ip, latency_ms (-1 = timeout)


class PingMonitorWidget(QWidget):
    """Dashboard widget showing live ping results."""

    def __init__(self, controller=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.signals = PingSignals()
        self.signals.result.connect(self._on_ping_result)
        self._targets = {}  # ip -> last latency
        self._running = False
        self._thread = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel("Ping Monitor")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #00d9ff;")
        header.addWidget(title)
        header.addStretch()

        self.btn_toggle = QPushButton("Start")
        self.btn_toggle.setStyleSheet("""
            QPushButton {
                background: #1a2332;
                color: #00ff88;
                border: 1px solid #0f1a2e;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #243040; }
        """)
        self.btn_toggle.clicked.connect(self._toggle_monitoring)
        header.addWidget(self.btn_toggle)

        self.btn_refresh_targets = QPushButton("Refresh Targets")
        self.btn_refresh_targets.setStyleSheet("""
            QPushButton {
                background: #1a2332;
                color: #94a3b8;
                border: 1px solid #0f1a2e;
                border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover { background: #243040; }
        """)
        self.btn_refresh_targets.clicked.connect(self._refresh_targets)
        header.addWidget(self.btn_refresh_targets)

        layout.addLayout(header)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["IP", "Hostname", "Latency (ms)", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #1e293b;
                gridline-color: #1e293b;
            }
            QHeaderView::section {
                background-color: #1a2332;
                color: #94a3b8;
                border: 1px solid #1e293b;
                padding: 4px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.table)

        # Status bar
        self.status_label = QLabel("Idle — click Start to begin monitoring")
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.status_label)

    def _refresh_targets(self) -> None:
        """Pull devices from the controller's device list."""
        if not self.controller:
            return
        devices = self.controller.get_devices()
        self._targets.clear()
        self.table.setRowCount(len(devices))
        for i, dev in enumerate(devices):
            ip = dev.ip if hasattr(dev, 'ip') else dev.get('ip', '')
            hostname = dev.hostname if hasattr(dev, 'hostname') else dev.get('hostname', '')
            self._targets[ip] = -1
            self.table.setItem(i, 0, QTableWidgetItem(ip))
            self.table.setItem(i, 1, QTableWidgetItem(hostname or "Unknown"))
            self.table.setItem(i, 2, QTableWidgetItem("—"))
            self.table.setItem(i, 3, QTableWidgetItem("Waiting"))
        self.status_label.setText(f"Loaded {len(devices)} target(s)")

    def _toggle_monitoring(self) -> None:
        if self._running:
            self._running = False
            self.btn_toggle.setText("Start")
            self.btn_toggle.setStyleSheet(self.btn_toggle.styleSheet().replace("#ff4444", "#00ff88"))
            self.status_label.setText("Stopped")
        else:
            if not self._targets:
                self._refresh_targets()
            if not self._targets:
                self.status_label.setText("No targets — scan devices first")
                return
            self._running = True
            self.btn_toggle.setText("Stop")
            self.status_label.setText("Monitoring...")
            self._thread = threading.Thread(target=self._ping_loop, daemon=True)
            self._thread.start()

    def _ping_loop(self) -> None:
        """Background thread that pings all targets in a loop."""
        while self._running:
            for ip in list(self._targets.keys()):
                if not self._running:
                    break
                latency = self._ping(ip)
                self.signals.result.emit(ip, latency)
            time.sleep(2)

    def _ping(self, ip: str) -> float:
        """Ping an IP and return latency in ms, or -1 on timeout."""
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "1000", ip],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            for line in result.stdout.splitlines():
                if "time=" in line.lower() or "time<" in line.lower():
                    # Extract ms value
                    for part in line.split():
                        if part.lower().startswith("time=") or part.lower().startswith("time<"):
                            ms_str = part.split("=")[-1].replace("ms", "").replace("<", "")
                            return float(ms_str)
        except Exception:
            pass
        return -1.0

    def _on_ping_result(self, ip: str, latency: float) -> None:
        """Update table with ping result (runs on GUI thread via signal)."""
        self._targets[ip] = latency
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == ip:
                if latency < 0:
                    self.table.setItem(row, 2, QTableWidgetItem("TIMEOUT"))
                    self.table.setItem(row, 3, QTableWidgetItem("Unreachable"))
                    self.table.item(row, 3).setForeground(QColor("#ef4444"))
                else:
                    self.table.setItem(row, 2, QTableWidgetItem(f"{latency:.1f}"))
                    if latency < 30:
                        status = "Good"
                        color = "#00ff88"
                    elif latency < 80:
                        status = "OK"
                        color = "#fbbf24"
                    else:
                        status = "High"
                        color = "#ef4444"
                    status_item = QTableWidgetItem(status)
                    status_item.setForeground(QColor(color))
                    self.table.setItem(row, 3, status_item)
                break

    def stop(self) -> None:
        self._running = False


class PingMonitorPlugin(UIPanelPlugin):
    """Ping Monitor plugin — adds a live latency panel to the dashboard."""

    def __init__(self) -> None:
        super().__init__()
        self._widget = None

    def activate(self, controller) -> bool:
        self.controller = controller
        self._enabled = True
        return True

    def deactivate(self) -> bool:
        if self._widget:
            self._widget.stop()
        self._enabled = False
        return True

    def get_panel_info(self) -> Dict[str, str]:
        return {
            "icon": "📶",
            "tooltip": "Ping Monitor",
            "title": "Ping Monitor",
        }

    def create_widget(self, parent=None) -> Any:
        self._widget = PingMonitorWidget(controller=self.controller, parent=parent)
        return self._widget
