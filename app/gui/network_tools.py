#!/usr/bin/env python3
# app/gui/network_tools.py — Network Intelligence Tools for DupeZ
"""Network Intelligence Tools — Live Traffic, Latency Overlay, Port Scanner, Connection Mapper.

Provides four tabbed panels:

* **TrafficMonitorWidget** — real-time per-interface bandwidth via ``psutil``.
* **LatencyOverlayWidget** — continuous ping/jitter with optional floating overlay.
* **PortScannerWidget** — quick TCP connect-scan with preset port lists.
* **ConnectionMapperWidget** — live connection table + text topology view.

All heavy I/O (ping, scanning, connection enumeration) runs on daemon threads
and communicates results back via ``pyqtSignal`` for thread-safe GUI updates.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.logs.logger import log_error
from app.utils.helpers import _NO_WINDOW

__all__ = [
    "TrafficMonitorWidget",
    "LatencyOverlayWidget",
    "PortScannerWidget",
    "ConnectionMapperWidget",
    "NetworkToolsView",
]

# ── Shared QSS constants ────────────────────────────────────────────

_NT_TITLE_QSS: str = (
    "color: #00d9ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;"
)

_NT_GREEN_BTN: str = (
    "QPushButton { background: #00ff88; color: #0a0e1a; font-weight: bold;"
    " border: none; padding: 4px 16px; border-radius: 4px; }"
    " QPushButton:hover { background: #00cc6a; }"
)

_NT_RED_BTN: str = (
    "QPushButton { background: #ff4444; color: white; font-weight: bold;"
    " border: none; padding: 4px 16px; border-radius: 4px; }"
    " QPushButton:hover { background: #cc3333; }"
)

_NT_GREEN_BTN_LG: str = (
    "QPushButton { background: #00ff88; color: #0a0e1a; font-weight: bold;"
    " border: none; padding: 6px 18px; border-radius: 4px; }"
    " QPushButton:hover { background: #00cc6a; }"
)

_NT_RED_BTN_LG: str = (
    "QPushButton { background: #ff4444; color: white; font-weight: bold;"
    " border: none; padding: 6px 18px; border-radius: 4px; }"
    " QPushButton:hover { background: #cc3333; }"
)

_NT_CYAN_BTN: str = (
    "QPushButton { background: #00d9ff; color: #0a0e1a; font-weight: bold;"
    " border: none; padding: 4px 16px; border-radius: 4px; }"
    " QPushButton:hover { background: #00b8d4; }"
)

_NT_PURPLE_BTN: str = (
    "QPushButton { background: #a855f7; color: white; font-weight: bold;"
    " border: none; padding: 4px 12px; border-radius: 4px; }"
    " QPushButton:hover { background: #9333ea; }"
)

_NT_TABLE_QSS: str = (
    "QTableWidget { background-color: #0f1923; color: #e0e0e0;"
    " border: 1px solid #1a2a3a; }"
    " QTableWidget::item:selected { background-color: rgba(0,217,255,0.2); }"
    " QTableWidget::item:alternate { background-color: #0a1628; }"
    " QHeaderView::section { background-color: #16213e; color: #00d9ff;"
    " padding: 6px; border: 1px solid #1a2a3a; font-weight: bold; }"
)

_NT_INPUT_QSS: str = (
    "QLineEdit { background: #0f1923; color: #e0e0e0;"
    " border: 1px solid #1a2a3a; padding: 4px; }"
)

_NT_COMBO_QSS: str = (
    "QComboBox { background: #0f1923; color: #e0e0e0;"
    " border: 1px solid #1a2a3a; padding: 4px; }"
    " QComboBox::drop-down { border: none; }"
)

_NT_PROGRESS_QSS: str = (
    "QProgressBar { background: #0f1923; border: 1px solid #1a2a3a;"
    " height: 16px; text-align: center; color: #e0e0e0; }"
    " QProgressBar::chunk { background: #00d9ff; }"
)

# ── Shared lookup tables ────────────────────────────────────────────

_STATE_COLORS: Dict[str, str] = {
    "ESTABLISHED": "#00ff88",
    "TIME_WAIT": "#fbbf24",
    "CLOSE_WAIT": "#fbbf24",
    "SYN_SENT": "#a855f7",
    "SYN_RECV": "#a855f7",
}

#: Ports commonly used by game servers and gaming network services.
GAMING_PORTS: frozenset[int] = frozenset({
    2302, 2303, 2304, 2305,   # Arma / DayZ
    3074,                       # Xbox Live / PSN
    3478, 3479, 3480,           # STUN
    7777, 7778,                 # Unreal Engine
    9306,                       # DayZ query
    19132,                      # Bedrock
    25565,                      # Minecraft Java
    27015, 27016, 27017,        # Steam / Source
    30120,                      # FiveM
})

#: Well-known port → service name for scan result display.
SERVICE_MAP: Dict[int, str] = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 445: "SMB",
    993: "IMAPS", 995: "POP3S", 1433: "MSSQL", 3306: "MySQL",
    3389: "RDP", 5432: "PostgreSQL", 5900: "VNC", 8080: "HTTP-Alt",
    8443: "HTTPS-Alt", 27015: "Steam", 3074: "XBL/PSN",
    3478: "STUN", 3479: "STUN", 3480: "STUN", 9306: "DayZ",
}

COMMON_SCAN_PORTS: List[int] = [
    21, 22, 23, 25, 53, 80, 110, 111, 135, 139, 143, 161,
    389, 443, 445, 465, 514, 587, 636, 993, 995, 1433, 1434,
    1521, 2049, 2082, 2083, 2086, 2087, 3306, 3389, 5432,
    5900, 5901, 6379, 8080, 8443, 8888, 9090, 9200, 9300,
    27017, 3074, 3478, 3479, 3480, 9306, 27015,
]

WEB_SCAN_PORTS: List[int] = [80, 443, 8080, 8443, 3000, 5000, 8000, 8888, 9090]

_PING_FLAG: str = "-n" if sys.platform == "win32" else "-c"

# Sparkline block characters, ordered low → high.
_SPARK_CHARS: str = "▁▂▃▄▅▆▇█"


# ── Helpers ─────────────────────────────────────────────────────────

def _run_ping(target: str, timeout: int = 1000) -> float:
    """Execute a single ICMP ping and return RTT in milliseconds.

    Returns ``-1.0`` on timeout or any failure.
    """
    try:
        result = subprocess.run(
            ["ping", _PING_FLAG, "1", "-w", str(timeout), target],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        match = re.search(r"time[=<](\d+\.?\d*)", result.stdout)
        return float(match.group(1)) if match else -1.0
    except Exception:
        return -1.0


def _color_for_latency(ms: float) -> str:
    """Return a hex colour string for the given latency value."""
    if ms < 50:
        return "#00ff88"
    if ms < 100:
        return "#fbbf24"
    return "#ff4444"


# ── TrafficMonitorWidget ────────────────────────────────────────────

class TrafficMonitorWidget(QWidget):
    """Real-time per-interface bandwidth display powered by ``psutil``.

    Refreshes every 2 seconds, showing bytes sent/received and an
    aggregate rate bar.  The ``QTimer`` is parented to ``self`` so it is
    automatically destroyed with the widget.
    """

    def __init__(self, controller: Any = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._prev_counters: Dict[str, Any] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("LIVE TRAFFIC MONITOR")
        title.setStyleSheet(_NT_TITLE_QSS)
        layout.addWidget(title)

        # Interface table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Interface", "IP", "Bytes Sent", "Bytes Recv", "Rate (KB/s)"],
        )
        hdr = self.table.horizontalHeader()
        for col in range(5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(_NT_TABLE_QSS)
        layout.addWidget(self.table)

        # Bandwidth bar
        bar_row = QHBoxLayout()
        bar_row.addWidget(QLabel("Total:"))
        self.bw_bar = QProgressBar()
        self.bw_bar.setRange(0, 100)
        self.bw_bar.setValue(0)
        self.bw_bar.setFormat("%v MB/s")
        self.bw_bar.setStyleSheet(
            "QProgressBar { background: #0f1923; border: 1px solid #1a2a3a;"
            " height: 20px; text-align: center; color: #e0e0e0; }"
            " QProgressBar::chunk { background: qlineargradient("
            "x1:0, x2:1, stop:0 #00d9ff, stop:1 #00ff88); }"
        )
        bar_row.addWidget(self.bw_bar, 1)
        layout.addLayout(bar_row)

        # Auto-refresh (parent=self → automatic cleanup on widget destroy)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)
        self._refresh()

    # ── Public API ──────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Stop the refresh timer explicitly (called by parent container)."""
        self._timer.stop()

    # ── Internal ────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """Pull fresh counters from psutil and update the table."""
        try:
            import psutil
        except ImportError:
            return

        try:
            counters = psutil.net_io_counters(pernic=True)
            addrs = psutil.net_if_addrs()

            self.table.setRowCount(0)
            total_rate = 0.0

            for iface, io in counters.items():
                # Skip loopback
                if iface.lower().startswith("lo") or "loopback" in iface.lower():
                    continue

                ip = self._first_ipv4(addrs.get(iface, []))
                if not ip:
                    continue

                row = self.table.rowCount()
                self.table.insertRow(row)

                # Calculate rate from previous sample
                rate = 0.0
                prev = self._prev_counters.get(iface)
                if prev is not None:
                    dt = 2.0  # refresh interval in seconds
                    rate = ((io.bytes_sent - prev.bytes_sent)
                            + (io.bytes_recv - prev.bytes_recv)) / dt / 1024.0
                self._prev_counters[iface] = io
                total_rate += rate

                self.table.setItem(row, 0, QTableWidgetItem(iface))
                self.table.setItem(row, 1, QTableWidgetItem(ip))
                self.table.setItem(row, 2, QTableWidgetItem(f"{io.bytes_sent / 1048576:.1f} MB"))
                self.table.setItem(row, 3, QTableWidgetItem(f"{io.bytes_recv / 1048576:.1f} MB"))

                rate_item = QTableWidgetItem(f"{rate:.1f}")
                if rate > 500:
                    rate_item.setForeground(QColor("#ff4444"))
                elif rate > 100:
                    rate_item.setForeground(QColor("#fbbf24"))
                else:
                    rate_item.setForeground(QColor("#00ff88"))
                self.table.setItem(row, 4, rate_item)

            mb_per_sec = total_rate / 1024.0
            self.bw_bar.setValue(min(100, int(mb_per_sec)))
            self.bw_bar.setFormat(f"{mb_per_sec:.2f} MB/s")

        except Exception as exc:
            log_error(f"Traffic monitor error: {exc}")

    @staticmethod
    def _first_ipv4(addrs: list) -> str:
        """Return the first IPv4 address from an ``psutil`` address list."""
        for addr in addrs:
            if addr.family == socket.AF_INET:
                return addr.address
        return ""


# ── LatencyOverlayWidget ────────────────────────────────────────────

class LatencyOverlayWidget(QWidget):
    """Continuous ping/jitter display for a target host.

    When the **FLOAT** button is pressed, a small transparent always-on-top
    ``_FloatingLatency`` window is spawned — useful as an in-game overlay.

    Thread-safety: ``_history`` is only mutated inside the background
    thread; the GUI thread receives computed values via ``_ping_result``
    signal, so no lock is required.
    """

    _ping_result = pyqtSignal(float, float, float)  # avg_ms, jitter_ms, loss_%

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._target_ip: str = ""
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._history: List[float] = []
        self._float_win: Optional[_FloatingLatency] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("LATENCY OVERLAY")
        title.setStyleSheet(_NT_TITLE_QSS)
        layout.addWidget(title)

        # Target input row
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target:"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("IP or hostname (e.g. 198.51.100.1)")
        self.target_input.setStyleSheet(_NT_INPUT_QSS)
        target_row.addWidget(self.target_input, 1)

        self.btn_start = QPushButton("START")
        self.btn_start.setStyleSheet(_NT_GREEN_BTN)
        self.btn_start.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_start.clicked.connect(self._toggle_ping)
        target_row.addWidget(self.btn_start)

        self.btn_float = QPushButton("FLOAT")
        self.btn_float.setToolTip("Open as floating transparent overlay")
        self.btn_float.setStyleSheet(_NT_PURPLE_BTN)
        self.btn_float.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_float.clicked.connect(self._open_floating)
        target_row.addWidget(self.btn_float)

        layout.addLayout(target_row)

        # Stats display
        stats = QHBoxLayout()
        self.ping_label = QLabel("Ping: — ms")
        self.ping_label.setStyleSheet("color: #00ff88; font-size: 22px; font-weight: bold;")
        stats.addWidget(self.ping_label)

        self.jitter_label = QLabel("Jitter: — ms")
        self.jitter_label.setStyleSheet("color: #fbbf24; font-size: 16px;")
        stats.addWidget(self.jitter_label)

        self.loss_label = QLabel("Loss: — %")
        self.loss_label.setStyleSheet("color: #ff4444; font-size: 16px;")
        stats.addWidget(self.loss_label)
        stats.addStretch()
        layout.addLayout(stats)

        # Mini sparkline graph
        self.graph_label = QLabel("")
        self.graph_label.setStyleSheet(
            "color: #64748b; font-family: monospace; font-size: 11px;"
        )
        self.graph_label.setWordWrap(True)
        layout.addWidget(self.graph_label)

        layout.addStretch()

        self._ping_result.connect(self._update_display)

    # ── Public API ──────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Stop the ping thread (called by parent container on teardown)."""
        self._running = False

    # ── Internal ────────────────────────────────────────────────────

    def _toggle_ping(self) -> None:
        """Start or stop the continuous ping loop."""
        if self._running:
            self._running = False
            self.btn_start.setText("START")
            self.btn_start.setStyleSheet(_NT_GREEN_BTN)
            return

        target = self.target_input.text().strip()
        if not target:
            return
        self._target_ip = target
        self._running = True
        self._history.clear()
        self.btn_start.setText("STOP")
        self.btn_start.setStyleSheet(_NT_RED_BTN)
        self._thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._thread.start()

    def _ping_loop(self) -> None:
        """Background: continuously ping target and emit averaged results."""
        history: List[float] = []
        while self._running:
            rtt = _run_ping(self._target_ip)
            if rtt >= 0:
                history.append(rtt)
                if len(history) > 60:
                    history = history[-60:]

                avg = sum(history) / len(history)
                jitter = 0.0
                if len(history) > 1:
                    diffs = [abs(history[i] - history[i - 1])
                             for i in range(1, len(history))]
                    jitter = sum(diffs) / len(diffs)

                # Store snapshot for sparkline (read from GUI thread)
                self._history = list(history)
                self._ping_result.emit(avg, jitter, 0.0)
            else:
                self._ping_result.emit(-1.0, 0.0, 100.0)

            time.sleep(1)

    @pyqtSlot(float, float, float)
    def _update_display(self, avg_ms: float, jitter_ms: float, loss_pct: float) -> None:
        """Slot: update stat labels and sparkline from latest ping batch."""
        if avg_ms < 0:
            self.ping_label.setText("Ping: TIMEOUT")
            self.ping_label.setStyleSheet(
                "color: #ff4444; font-size: 22px; font-weight: bold;"
            )
            return

        color = _color_for_latency(avg_ms)
        self.ping_label.setText(f"Ping: {avg_ms:.0f} ms")
        self.ping_label.setStyleSheet(
            f"color: {color}; font-size: 22px; font-weight: bold;"
        )
        self.jitter_label.setText(f"Jitter: {jitter_ms:.1f} ms")
        self.loss_label.setText(f"Loss: {loss_pct:.0f}%")

        # Mini text sparkline (last 30 samples)
        recent = self._history[-30:]
        if recent:
            peak = max(recent) or 1.0
            bars = "".join(
                _SPARK_CHARS[min(int((v / peak) * 7), 7)] for v in recent
            )
            self.graph_label.setText(f"Last 30: {bars}")

    def _open_floating(self) -> None:
        """Spawn a small always-on-top latency overlay window."""
        target = self._target_ip or self.target_input.text().strip()
        self._float_win = _FloatingLatency(target)
        self._float_win.show()


# ── _FloatingLatency (private) ──────────────────────────────────────

class _FloatingLatency(QWidget):
    """Tiny frameless always-on-top transparent latency display.

    Draggable via left-click; right-click closes.
    """

    _ping_result = pyqtSignal(float)

    _LABEL_QSS_TEMPLATE: str = (
        "color: {color}; font-size: 16px; font-weight: bold;"
        " background: rgba(10, 14, 26, 0.85);"
        " padding: 8px; border-radius: 6px;"
        " border: 1px solid rgba(0, 217, 255, 0.3);"
    )

    def __init__(self, target_ip: str) -> None:
        super().__init__()
        self._target: str = target_ip
        self._running: bool = True
        self._drag_origin: Optional[Any] = None  # QPoint or None

        self.setWindowTitle("DupeZ Latency")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(200, 60)

        # Position top-right of screen
        screen = self.screen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.width() - 220, 20)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.label = QLabel(f"Ping {target_ip}: — ms")
        self.label.setStyleSheet(self._LABEL_QSS_TEMPLATE.format(color="#00ff88"))
        layout.addWidget(self.label)

        self._ping_result.connect(self._update)

        self._thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._thread.start()

    # ── Internal ────────────────────────────────────────────────────

    def _ping_loop(self) -> None:
        """Background: emit one ping result per second."""
        while self._running:
            self._ping_result.emit(_run_ping(self._target))
            time.sleep(1)

    @pyqtSlot(float)
    def _update(self, ms: float) -> None:
        """Slot: refresh label text and colour from latest ping."""
        if ms < 0:
            self.label.setText(f"Ping {self._target}: TIMEOUT")
            self.label.setStyleSheet(
                self._LABEL_QSS_TEMPLATE.format(color="#ff4444")
            )
        else:
            color = _color_for_latency(ms)
            self.label.setText(f"Ping {self._target}: {ms:.0f} ms")
            self.label.setStyleSheet(
                self._LABEL_QSS_TEMPLATE.format(color=color)
            )

    # ── Qt event overrides ──────────────────────────────────────────

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._running = False
        event.accept()

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
        elif event.button() == Qt.MouseButton.RightButton:
            self.close()

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self._drag_origin is not None:
            self.move(event.globalPosition().toPoint() - self._drag_origin)


# ── PortScannerWidget ───────────────────────────────────────────────

class PortScannerWidget(QWidget):
    """Quick TCP connect-scan for discovered devices.

    Runs the scan on a daemon thread and reports open ports via
    ``_scan_done`` signal with progress updates through ``QMetaObject``.
    """

    _scan_done = pyqtSignal(str, list)  # ip, [(port, service_hint)]

    def __init__(self, controller: Any = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._scanning: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("PORT SCANNER")
        title.setStyleSheet(_NT_TITLE_QSS)
        layout.addWidget(title)

        # Target + port-set row
        row = QHBoxLayout()
        row.addWidget(QLabel("Target:"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("IP address")
        self.target_input.setStyleSheet(_NT_INPUT_QSS)
        row.addWidget(self.target_input, 1)

        row.addWidget(QLabel("Ports:"))
        self.port_combo = QComboBox()
        self.port_combo.addItems([
            "Common (Top 100)", "Gaming", "Web", "All (1-1024)", "Full (1-65535)",
        ])
        self.port_combo.setStyleSheet(_NT_COMBO_QSS)
        row.addWidget(self.port_combo)

        self.btn_scan = QPushButton("SCAN")
        self.btn_scan.setStyleSheet(_NT_CYAN_BTN)
        self.btn_scan.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_scan.clicked.connect(self._start_scan)
        row.addWidget(self.btn_scan)
        layout.addLayout(row)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setStyleSheet(_NT_PROGRESS_QSS)
        layout.addWidget(self.progress)

        # Results table
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["Port", "State", "Service"])
        hdr = self.result_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setStyleSheet(_NT_TABLE_QSS)
        layout.addWidget(self.result_table)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self.status_label)

        self._scan_done.connect(self._on_scan_done)

    # ── Internal ────────────────────────────────────────────────────

    def _resolve_port_list(self) -> List[int]:
        """Map the combo-box selection to a concrete list of ports."""
        choice = self.port_combo.currentText()
        if "Gaming" in choice:
            return sorted(GAMING_PORTS)
        if "Web" in choice:
            return list(WEB_SCAN_PORTS)
        if "Full" in choice:
            return list(range(1, 65536))
        if "All" in choice:
            return list(range(1, 1025))
        return list(COMMON_SCAN_PORTS)

    def _start_scan(self) -> None:
        """Validate target and launch the scan thread."""
        target = self.target_input.text().strip()
        if not target:
            QMessageBox.warning(self, "No Target", "Enter an IP address to scan.")
            return
        if self._scanning:
            return

        self._scanning = True
        self.btn_scan.setText("SCANNING...")
        self.btn_scan.setEnabled(False)
        self.result_table.setRowCount(0)
        self.progress.setValue(0)
        self.status_label.setText(f"Scanning {target}...")

        ports = self._resolve_port_list()
        threading.Thread(
            target=self._scan_thread, args=(target, ports), daemon=True,
        ).start()

    def _scan_thread(self, ip: str, ports: List[int]) -> None:
        """Background: TCP-connect each port and collect open ones."""
        open_ports: List[Tuple[int, str]] = []
        total = len(ports)
        progress_step = max(1, total // 100)

        try:
            for idx, port in enumerate(ports):
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                        sock.settimeout(0.5)
                        if sock.connect_ex((ip, port)) == 0:
                            open_ports.append((port, SERVICE_MAP.get(port, "Unknown")))
                except Exception:
                    pass

                # Throttled progress update
                if idx % progress_step == 0:
                    pct = int((idx / total) * 100)
                    try:
                        QMetaObject.invokeMethod(
                            self.progress, "setValue",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(int, pct),
                        )
                    except Exception:
                        pass

        except Exception as exc:
            log_error(f"Port scan error: {exc}")

        self._scan_done.emit(ip, open_ports)

    @pyqtSlot(str, list)
    def _on_scan_done(self, ip: str, open_ports: list) -> None:
        """Slot: populate results table after scan completes."""
        self._scanning = False
        self.btn_scan.setText("SCAN")
        self.btn_scan.setEnabled(True)
        self.progress.setValue(100)

        self.result_table.setRowCount(0)
        for port, service in sorted(open_ports):
            row = self.result_table.rowCount()
            self.result_table.insertRow(row)
            self.result_table.setItem(row, 0, QTableWidgetItem(str(port)))

            state_item = QTableWidgetItem("OPEN")
            state_item.setForeground(QColor("#00ff88"))
            self.result_table.setItem(row, 1, state_item)

            self.result_table.setItem(row, 2, QTableWidgetItem(service))

        self.status_label.setText(f"Scan complete: {len(open_ports)} open ports on {ip}")
        self.status_label.setStyleSheet("color: #00ff88; font-size: 11px;")


# ── ConnectionMapperWidget ──────────────────────────────────────────

class ConnectionMapperWidget(QWidget):
    """Live connection table + text-art topology view.

    Uses ``psutil.net_connections()`` to enumerate TCP/UDP sockets,
    groups by remote IP, optionally resolves hostnames, and renders
    both a compact topology diagram and a full detail table.
    """

    _refresh_done = pyqtSignal(list)  # list of connection dicts

    _MAX_RESOLVE_CACHE: int = 512

    def __init__(self, controller: Any = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._resolve_cache: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("CONNECTION MAPPER")
        title.setStyleSheet(_NT_TITLE_QSS)
        layout.addWidget(title)

        # Controls row
        ctrl_row = QHBoxLayout()
        self.btn_start = QPushButton("START MAPPING")
        self.btn_start.setStyleSheet(_NT_GREEN_BTN_LG)
        self.btn_start.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_start.clicked.connect(self._toggle_mapping)
        ctrl_row.addWidget(self.btn_start)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All", "TCP Only", "UDP Only", "Established Only", "Gaming Ports",
        ])
        self.filter_combo.setStyleSheet(_NT_COMBO_QSS)
        ctrl_row.addWidget(self.filter_combo)

        self.chk_resolve = QCheckBox("Resolve Hostnames")
        self.chk_resolve.setChecked(False)
        self.chk_resolve.setStyleSheet("color: #94a3b8;")
        ctrl_row.addWidget(self.chk_resolve)

        ctrl_row.addStretch()

        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        ctrl_row.addWidget(self.status_label)
        layout.addLayout(ctrl_row)

        # Topology text display
        self.topo_label = QLabel("")
        self.topo_label.setStyleSheet(
            "color: #94a3b8; font-family: 'Consolas', 'Courier New', monospace;"
            " font-size: 11px; background: #0a1628; border: 1px solid #1a2a3a;"
            " border-radius: 4px; padding: 8px;"
        )
        self.topo_label.setWordWrap(True)
        self.topo_label.setMinimumHeight(80)
        layout.addWidget(self.topo_label)

        # Connection detail table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Proto", "Local Port", "Remote IP", "Remote Port",
            "State", "PID", "Hostname",
        ])
        hdr = self.table.horizontalHeader()
        for col in range(7):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(_NT_TABLE_QSS)
        layout.addWidget(self.table, 1)

        # Summary
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.summary_label)

        self._refresh_done.connect(self._update_display)

    # ── Public API ──────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Stop the mapping thread (called by parent container)."""
        self._running = False

    # ── Internal ────────────────────────────────────────────────────

    def _toggle_mapping(self) -> None:
        """Start or stop the background connection-enumeration loop."""
        if self._running:
            self._running = False
            self.btn_start.setText("START MAPPING")
            self.btn_start.setStyleSheet(_NT_GREEN_BTN_LG)
            self.status_label.setText("Stopped")
        else:
            self._running = True
            self.btn_start.setText("STOP")
            self.btn_start.setStyleSheet(_NT_RED_BTN_LG)
            self.status_label.setText("Mapping...")
            self._thread = threading.Thread(
                target=self._map_loop, daemon=True,
            )
            self._thread.start()

    def _map_loop(self) -> None:
        """Background: collect connection data every 3 seconds."""
        while self._running:
            try:
                import psutil
                raw = psutil.net_connections(kind="inet")
            except ImportError:
                return
            except Exception as exc:
                log_error(f"Connection mapper error: {exc}")
                time.sleep(3)
                continue

            connections: List[Dict[str, Any]] = []
            resolve = self.chk_resolve.isChecked()

            for conn in raw:
                if not conn.raddr:
                    continue
                rip = conn.raddr.ip
                if rip.startswith("127.") or rip == "::1":
                    continue

                proto = "TCP" if conn.type == socket.SOCK_STREAM else "UDP"
                hostname = self._maybe_resolve(rip) if resolve else ""

                connections.append({
                    "proto": proto,
                    "lport": conn.laddr.port if conn.laddr else 0,
                    "rip": rip,
                    "rport": conn.raddr.port,
                    "state": getattr(conn, "status", ""),
                    "pid": conn.pid or 0,
                    "hostname": hostname,
                })

            self._refresh_done.emit(connections)
            time.sleep(3)

    def _maybe_resolve(self, ip: str) -> str:
        """Resolve an IP to a hostname, with caching and size cap."""
        cached = self._resolve_cache.get(ip)
        if cached is not None:
            return cached

        try:
            hostname = socket.getfqdn(ip)
            if hostname == ip:
                hostname = ""
        except Exception:
            hostname = ""

        if len(self._resolve_cache) >= self._MAX_RESOLVE_CACHE:
            self._resolve_cache.clear()
        self._resolve_cache[ip] = hostname
        return hostname

    @pyqtSlot(list)
    def _update_display(self, connections: list) -> None:
        """Slot: apply filter, rebuild topology and table."""
        filtered = self._apply_filter(connections)

        # Group by remote IP
        ip_map: Dict[str, List[Dict]] = {}
        for conn in filtered:
            ip_map.setdefault(conn["rip"], []).append(conn)

        self._render_topology(ip_map)
        self._render_table(filtered)
        self._render_summary(filtered, ip_map)
        self.status_label.setText(f"Updated {time.strftime('%H:%M:%S')}")

    def _apply_filter(self, connections: list) -> list:
        """Return the subset matching the current combo-box filter."""
        filt = self.filter_combo.currentText()
        filters: Dict[str, Callable] = {
            "TCP Only": lambda c: c["proto"] == "TCP",
            "UDP Only": lambda c: c["proto"] == "UDP",
            "Established Only": lambda c: c["state"] == "ESTABLISHED",
            "Gaming Ports": lambda c: (
                c["rport"] in GAMING_PORTS or c["lport"] in GAMING_PORTS
            ),
        }
        fn = filters.get(filt)
        return [c for c in connections if fn(c)] if fn else list(connections)

    def _render_topology(self, ip_map: Dict[str, list]) -> None:
        """Build the text-art topology label from grouped connections."""
        if not ip_map:
            self.topo_label.setText("  No active connections matching filter.")
            return

        lines: List[str] = []
        local_label = "[ THIS PC ]"
        arrow = "───►"

        top_ips = sorted(ip_map.items(), key=lambda x: len(x[1]), reverse=True)[:12]
        for rip, conns in top_ips:
            host = conns[0].get("hostname") or ""
            label = f"{rip}" + (f" ({host})" if host else "")
            ports = sorted({c["rport"] for c in conns})
            port_str = ", ".join(str(p) for p in ports[:6])
            if len(ports) > 6:
                port_str += f" +{len(ports) - 6}"
            lines.append(
                f"  {local_label} {arrow} {label}  [{len(conns)} conn, ports: {port_str}]"
            )
            local_label = " " * len("[ THIS PC ]")

        self.topo_label.setText("\n".join(lines))

    def _render_table(self, filtered: list) -> None:
        """Populate the detail table from filtered connections."""
        self.table.setRowCount(0)
        for conn in filtered:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(conn["proto"]))
            self.table.setItem(row, 1, QTableWidgetItem(str(conn["lport"])))
            self.table.setItem(row, 2, QTableWidgetItem(conn["rip"]))
            self.table.setItem(row, 3, QTableWidgetItem(str(conn["rport"])))

            state_item = QTableWidgetItem(conn["state"])
            state_item.setForeground(
                QColor(_STATE_COLORS.get(conn["state"], "#6b7280"))
            )
            self.table.setItem(row, 4, state_item)

            self.table.setItem(
                row, 5, QTableWidgetItem(str(conn["pid"]) if conn["pid"] else "—"),
            )
            self.table.setItem(row, 6, QTableWidgetItem(conn["hostname"]))

    def _render_summary(self, filtered: list, ip_map: Dict[str, list]) -> None:
        """Update the summary label with connection statistics."""
        tcp = sum(1 for c in filtered if c["proto"] == "TCP")
        udp = sum(1 for c in filtered if c["proto"] == "UDP")
        gaming = sum(
            1 for c in filtered
            if c["rport"] in GAMING_PORTS or c["lport"] in GAMING_PORTS
        )
        self.summary_label.setText(
            f"{len(filtered)} connections | {len(ip_map)} unique IPs | "
            f"TCP: {tcp} | UDP: {udp} | Gaming: {gaming}"
        )


# ── NetworkToolsView (top-level container) ──────────────────────────

class NetworkToolsView(QWidget):
    """Tabbed container exposing all four network intelligence panels."""

    def __init__(self, controller: Any = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #1a2a3a; background: #0a0e1a; }"
            " QTabBar::tab { background: #16213e; color: #94a3b8; padding: 8px 16px;"
            " border: 1px solid #1a2a3a; border-bottom: none; font-weight: bold; }"
            " QTabBar::tab:selected { background: #0a0e1a; color: #00d9ff;"
            " border-bottom: 2px solid #00d9ff; }"
            " QTabBar::tab:hover { color: #e0e0e0; }"
        )

        self.traffic_tab = TrafficMonitorWidget(controller=controller)
        self.tabs.addTab(self.traffic_tab, "Traffic Monitor")

        self.latency_tab = LatencyOverlayWidget()
        self.tabs.addTab(self.latency_tab, "Latency Overlay")

        self.scanner_tab = PortScannerWidget(controller=controller)
        self.tabs.addTab(self.scanner_tab, "Port Scanner")

        self.mapper_tab = ConnectionMapperWidget(controller=controller)
        self.tabs.addTab(self.mapper_tab, "Connection Mapper")

        layout.addWidget(self.tabs)

    def cleanup(self) -> None:
        """Stop all background threads and timers across child tabs."""
        self.traffic_tab.cleanup()
        self.latency_tab.cleanup()
        self.mapper_tab.cleanup()
