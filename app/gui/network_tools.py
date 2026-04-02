#!/usr/bin/env python3
"""
Network Intelligence Tools — v3.3.0

Three tools packaged as a tabbed widget:
  1. Live Traffic Monitor   — real-time bandwidth graph per device
  2. Latency Overlay        — floating transparent ping/jitter widget
  3. Port Scanner           — scan open ports on discovered devices
"""

import time
import threading
import socket
import subprocess
import sys
import re
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QSpinBox, QLineEdit, QProgressBar, QGroupBox, QComboBox,
    QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QMetaObject, Q_ARG
from PyQt6.QtGui import QFont, QColor, QCursor, QPainter, QPen, QBrush

from app.logs.logger import log_info, log_error


# ======================================================================
# Live Traffic Monitor
# ======================================================================
class TrafficMonitorWidget(QWidget):
    """Real-time bandwidth usage per device using psutil.

    Shows a simple bar chart updated every 2 seconds showing bytes
    sent/received for each active network interface.
    """

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._history: Dict[str, list] = {}   # ip -> [(timestamp, bytes_in, bytes_out)]
        self._prev_counters = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("LIVE TRAFFIC MONITOR")
        title.setStyleSheet("color: #00d9ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(title)

        # Interface table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Interface", "IP", "Bytes Sent", "Bytes Recv", "Rate (KB/s)"])
        hdr = self.table.horizontalHeader()
        for i in range(5):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; }
            QTableWidget::item:selected { background-color: rgba(0,217,255,0.2); }
            QTableWidget::item:alternate { background-color: #0a1628; }
            QHeaderView::section { background-color: #16213e; color: #00d9ff; padding: 6px; border: 1px solid #1a2a3a; font-weight: bold; }
        """)
        layout.addWidget(self.table)

        # Bandwidth bar
        bar_row = QHBoxLayout()
        bar_row.addWidget(QLabel("Total:"))
        self.bw_bar = QProgressBar()
        self.bw_bar.setRange(0, 100)
        self.bw_bar.setValue(0)
        self.bw_bar.setFormat("%v MB/s")
        self.bw_bar.setStyleSheet("""
            QProgressBar { background: #0f1923; border: 1px solid #1a2a3a; height: 20px; text-align: center; color: #e0e0e0; }
            QProgressBar::chunk { background: qlineargradient(x1:0, x2:1, stop:0 #00d9ff, stop:1 #00ff88); }
        """)
        bar_row.addWidget(self.bw_bar, 1)
        layout.addLayout(bar_row)

        # Auto-refresh
        self._timer = QTimer(self)  # parent=self ensures cleanup on destroy
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)
        self._refresh()

    def cleanup(self):
        """Stop timer when widget is destroyed."""
        self._timer.stop()

    def _refresh(self):
        try:
            import psutil
            counters = psutil.net_io_counters(pernic=True)
            addrs = psutil.net_if_addrs()

            self.table.setRowCount(0)
            total_rate = 0.0

            for iface, io in counters.items():
                # Skip loopback
                if iface.lower().startswith('lo') or 'loopback' in iface.lower():
                    continue

                ip = ""
                if iface in addrs:
                    for a in addrs[iface]:
                        if a.family == 2:  # AF_INET
                            ip = a.address
                            break
                if not ip:
                    continue

                row = self.table.rowCount()
                self.table.insertRow(row)

                # Calculate rate
                rate = 0.0
                key = iface
                if key in self._prev_counters:
                    prev = self._prev_counters[key]
                    dt = 2.0  # refresh interval
                    delta_sent = io.bytes_sent - prev.bytes_sent
                    delta_recv = io.bytes_recv - prev.bytes_recv
                    rate = (delta_sent + delta_recv) / dt / 1024  # KB/s
                self._prev_counters[key] = io
                total_rate += rate

                self.table.setItem(row, 0, QTableWidgetItem(iface))
                self.table.setItem(row, 1, QTableWidgetItem(ip))
                self.table.setItem(row, 2, QTableWidgetItem(f"{io.bytes_sent / 1024 / 1024:.1f} MB"))
                self.table.setItem(row, 3, QTableWidgetItem(f"{io.bytes_recv / 1024 / 1024:.1f} MB"))

                rate_item = QTableWidgetItem(f"{rate:.1f}")
                if rate > 500:
                    rate_item.setForeground(QColor("#ff4444"))
                elif rate > 100:
                    rate_item.setForeground(QColor("#fbbf24"))
                else:
                    rate_item.setForeground(QColor("#00ff88"))
                self.table.setItem(row, 4, rate_item)

            self.bw_bar.setValue(min(100, int(total_rate / 1024)))  # scale to MB/s, cap at 100
            self.bw_bar.setFormat(f"{total_rate / 1024:.2f} MB/s")

        except ImportError:
            pass
        except Exception as e:
            log_error(f"Traffic monitor error: {e}")


# ======================================================================
# Latency Overlay
# ======================================================================
class LatencyOverlayWidget(QWidget):
    """Ping/jitter display for a target IP.

    When launched as a standalone window, it stays on top with
    semi-transparent background — useful as a gameplay overlay.
    """

    _ping_result = pyqtSignal(float, float, float)  # avg_ms, jitter_ms, loss_%

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_ip = ""
        self._running = False
        self._thread = None
        self._history: List[float] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("LATENCY OVERLAY")
        title.setStyleSheet("color: #00d9ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(title)

        # Target input
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target:"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("IP or hostname (e.g. 198.51.100.1)")
        self.target_input.setStyleSheet("QLineEdit { background: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; padding: 4px; }")
        target_row.addWidget(self.target_input, 1)

        self.btn_start = QPushButton("START")
        self.btn_start.setStyleSheet("""
            QPushButton { background: #00ff88; color: #0a0e1a; font-weight: bold; border: none; padding: 4px 16px; border-radius: 4px; }
            QPushButton:hover { background: #00cc6a; }
        """)
        self.btn_start.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_start.clicked.connect(self._toggle_ping)
        target_row.addWidget(self.btn_start)

        self.btn_float = QPushButton("FLOAT")
        self.btn_float.setToolTip("Open as floating transparent overlay")
        self.btn_float.setStyleSheet("""
            QPushButton { background: #a855f7; color: white; font-weight: bold; border: none; padding: 4px 12px; border-radius: 4px; }
            QPushButton:hover { background: #9333ea; }
        """)
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

        # Mini graph (simple text-based)
        self.graph_label = QLabel("")
        self.graph_label.setStyleSheet("color: #64748b; font-family: monospace; font-size: 11px;")
        self.graph_label.setWordWrap(True)
        layout.addWidget(self.graph_label)

        layout.addStretch()

        self._ping_result.connect(self._update_display)

    def _toggle_ping(self):
        if self._running:
            self._running = False
            self.btn_start.setText("START")
            self.btn_start.setStyleSheet("""
                QPushButton { background: #00ff88; color: #0a0e1a; font-weight: bold; border: none; padding: 4px 16px; border-radius: 4px; }
                QPushButton:hover { background: #00cc6a; }
            """)
        else:
            target = self.target_input.text().strip()
            if not target:
                return
            self._target_ip = target
            self._running = True
            self._history.clear()
            self.btn_start.setText("STOP")
            self.btn_start.setStyleSheet("""
                QPushButton { background: #ff4444; color: white; font-weight: bold; border: none; padding: 4px 16px; border-radius: 4px; }
                QPushButton:hover { background: #cc3333; }
            """)
            self._thread = threading.Thread(target=self._ping_loop, daemon=True)
            self._thread.start()

    def _ping_loop(self):
        """Continuously ping the target and emit results."""
        while self._running:
            try:
                flag = "-n" if sys.platform == "win32" else "-c"
                creation = 0x08000000 if sys.platform == "win32" else 0
                result = subprocess.run(
                    ["ping", flag, "1", "-w", "1000", self._target_ip],
                    capture_output=True, text=True, timeout=5,
                    creationflags=creation
                )
                output = result.stdout

                # Parse RTT
                rtt_match = re.search(r'time[=<](\d+\.?\d*)', output)
                if rtt_match:
                    rtt = float(rtt_match.group(1))
                    self._history.append(rtt)
                    if len(self._history) > 60:
                        self._history = self._history[-60:]

                    avg = sum(self._history) / len(self._history)
                    jitter = 0.0
                    if len(self._history) > 1:
                        diffs = [abs(self._history[i] - self._history[i-1]) for i in range(1, len(self._history))]
                        jitter = sum(diffs) / len(diffs)

                    self._ping_result.emit(avg, jitter, 0.0)
                else:
                    self._ping_result.emit(-1, 0, 100.0)

            except Exception:
                self._ping_result.emit(-1, 0, 100.0)

            time.sleep(1)

    @pyqtSlot(float, float, float)
    def _update_display(self, avg_ms, jitter_ms, loss_pct):
        if avg_ms < 0:
            self.ping_label.setText("Ping: TIMEOUT")
            self.ping_label.setStyleSheet("color: #ff4444; font-size: 22px; font-weight: bold;")
            return

        # Color code ping
        if avg_ms < 50:
            color = "#00ff88"
        elif avg_ms < 100:
            color = "#fbbf24"
        else:
            color = "#ff4444"

        self.ping_label.setText(f"Ping: {avg_ms:.0f} ms")
        self.ping_label.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")
        self.jitter_label.setText(f"Jitter: {jitter_ms:.1f} ms")
        self.loss_label.setText(f"Loss: {loss_pct:.0f}%")

        # Mini text sparkline
        if self._history:
            max_val = max(self._history[-30:]) or 1
            bars = ""
            for v in self._history[-30:]:
                level = int((v / max_val) * 7)
                bars += ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"][min(level, 7)]
            self.graph_label.setText(f"Last 30: {bars}")

    def _open_floating(self):
        """Launch a floating overlay window."""
        self._float_win = _FloatingLatency(self._target_ip or self.target_input.text().strip())
        self._float_win.show()

    def cleanup(self):
        """Stop ping thread when widget is destroyed."""
        self._running = False


class _FloatingLatency(QWidget):
    """Tiny always-on-top transparent latency overlay."""

    _ping_result = pyqtSignal(float)

    def __init__(self, target_ip: str):
        super().__init__()
        self._target = target_ip
        self._running = True

        self.setWindowTitle("DupeZ Latency")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(200, 60)

        # Position top-right
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            self.move(screen.width() - 220, 20)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.label = QLabel(f"Ping {target_ip}: — ms")
        self.label.setStyleSheet("""
            color: #00ff88; font-size: 16px; font-weight: bold;
            background: rgba(10, 14, 26, 0.85);
            padding: 8px; border-radius: 6px;
            border: 1px solid rgba(0, 217, 255, 0.3);
        """)
        layout.addWidget(self.label)

        self._ping_result.connect(self._update)

        self._thread = threading.Thread(target=self._ping_loop, daemon=True)
        self._thread.start()

    def _ping_loop(self):
        while self._running:
            try:
                flag = "-n" if sys.platform == "win32" else "-c"
                creation = 0x08000000 if sys.platform == "win32" else 0
                result = subprocess.run(
                    ["ping", flag, "1", "-w", "1000", self._target],
                    capture_output=True, text=True, timeout=5,
                    creationflags=creation
                )
                m = re.search(r'time[=<](\d+\.?\d*)', result.stdout)
                self._ping_result.emit(float(m.group(1)) if m else -1)
            except Exception:
                self._ping_result.emit(-1)
            time.sleep(1)

    @pyqtSlot(float)
    def _update(self, ms):
        if ms < 0:
            self.label.setText(f"Ping {self._target}: TIMEOUT")
            self.label.setStyleSheet(self.label.styleSheet().replace("#00ff88", "#ff4444"))
        else:
            color = "#00ff88" if ms < 50 else "#fbbf24" if ms < 100 else "#ff4444"
            self.label.setText(f"Ping {self._target}: {ms:.0f} ms")
            self.label.setStyleSheet(f"""
                color: {color}; font-size: 16px; font-weight: bold;
                background: rgba(10, 14, 26, 0.85);
                padding: 8px; border-radius: 6px;
                border: 1px solid rgba(0, 217, 255, 0.3);
            """)

    def closeEvent(self, event):
        self._running = False
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.MouseButton.RightButton:
            self.close()

    def mouseMoveEvent(self, event):
        if hasattr(self, '_drag_pos') and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)


# ======================================================================
# Port Scanner
# ======================================================================
class PortScannerWidget(QWidget):
    """Quick port scanner for discovered devices."""

    _scan_done = pyqtSignal(str, list)  # ip, [(port, service_hint)]

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._scanning = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("PORT SCANNER")
        title.setStyleSheet("color: #00d9ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(title)

        # Target input
        row = QHBoxLayout()
        row.addWidget(QLabel("Target:"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("IP address")
        self.target_input.setStyleSheet("QLineEdit { background: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; padding: 4px; }")
        row.addWidget(self.target_input, 1)

        row.addWidget(QLabel("Ports:"))
        self.port_combo = QComboBox()
        self.port_combo.addItems(["Common (Top 100)", "Gaming", "Web", "All (1-1024)", "Full (1-65535)"])
        self.port_combo.setStyleSheet("""
            QComboBox { background: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; padding: 4px; }
            QComboBox::drop-down { border: none; }
        """)
        row.addWidget(self.port_combo)

        self.btn_scan = QPushButton("SCAN")
        self.btn_scan.setStyleSheet("""
            QPushButton { background: #00d9ff; color: #0a0e1a; font-weight: bold; border: none; padding: 4px 16px; border-radius: 4px; }
            QPushButton:hover { background: #00b8d4; }
        """)
        self.btn_scan.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_scan.clicked.connect(self._start_scan)
        row.addWidget(self.btn_scan)
        layout.addLayout(row)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setStyleSheet("""
            QProgressBar { background: #0f1923; border: 1px solid #1a2a3a; height: 16px; text-align: center; color: #e0e0e0; }
            QProgressBar::chunk { background: #00d9ff; }
        """)
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
        self.result_table.setStyleSheet("""
            QTableWidget { background-color: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; }
            QTableWidget::item:selected { background-color: rgba(0,217,255,0.2); }
            QTableWidget::item:alternate { background-color: #0a1628; }
            QHeaderView::section { background-color: #16213e; color: #00d9ff; padding: 6px; border: 1px solid #1a2a3a; font-weight: bold; }
        """)
        layout.addWidget(self.result_table)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self.status_label)

        self._scan_done.connect(self._on_scan_done)

    # Well-known port → service hints
    SERVICE_MAP = {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
        80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 445: "SMB",
        993: "IMAPS", 995: "POP3S", 1433: "MSSQL", 3306: "MySQL",
        3389: "RDP", 5432: "PostgreSQL", 5900: "VNC", 8080: "HTTP-Alt",
        8443: "HTTPS-Alt", 27015: "Steam", 3074: "XBL/PSN",
        3478: "STUN", 3479: "STUN", 3480: "STUN", 9306: "DayZ",
    }

    GAMING_PORTS = [
        3074, 3478, 3479, 3480, 9306, 27015, 27016, 27017,
        7777, 7778, 2302, 2303, 2304, 2305, 25565, 19132, 30120,
    ]

    COMMON_PORTS = [
        21, 22, 23, 25, 53, 80, 110, 111, 135, 139, 143, 161,
        389, 443, 445, 465, 514, 587, 636, 993, 995, 1433, 1434,
        1521, 2049, 2082, 2083, 2086, 2087, 3306, 3389, 5432,
        5900, 5901, 6379, 8080, 8443, 8888, 9090, 9200, 9300,
        27017, 3074, 3478, 3479, 3480, 9306, 27015,
    ]

    WEB_PORTS = [80, 443, 8080, 8443, 3000, 5000, 8000, 8888, 9090]

    def _get_ports(self) -> List[int]:
        choice = self.port_combo.currentText()
        if "Gaming" in choice:
            return self.GAMING_PORTS
        elif "Web" in choice:
            return self.WEB_PORTS
        elif "All" in choice:
            return list(range(1, 1025))
        elif "Full" in choice:
            return list(range(1, 65536))
        else:
            return self.COMMON_PORTS

    def _start_scan(self):
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

        ports = self._get_ports()
        threading.Thread(
            target=self._scan_thread, args=(target, ports), daemon=True
        ).start()

    def _scan_thread(self, ip: str, ports: List[int]):
        open_ports = []
        total = len(ports)
        try:
            for i, port in enumerate(ports):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    if result == 0:
                        service = self.SERVICE_MAP.get(port, "Unknown")
                        open_ports.append((port, service))
                except Exception:
                    pass

                # Update progress periodically
                if i % max(1, total // 100) == 0:
                    pct = int((i / total) * 100)
                    try:
                        QMetaObject.invokeMethod(
                            self.progress, "setValue",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(int, pct)
                        )
                    except Exception:
                        pass

        except Exception as e:
            log_error(f"Port scan error: {e}")

        self._scan_done.emit(ip, open_ports)

    @pyqtSlot(str, list)
    def _on_scan_done(self, ip: str, open_ports: list):
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


# ======================================================================
# Connection Mapper
# ======================================================================
class ConnectionMapperWidget(QWidget):
    """Visual topology of active network connections.

    Uses ``psutil.net_connections()`` to enumerate all TCP/UDP sockets,
    groups them by remote IP, resolves hostnames where possible, and
    presents a live-updating table + simple text-art topology view.
    """

    _refresh_done = pyqtSignal(list)  # list of connection dicts

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._running = False
        self._thread = None
        self._resolve_cache: Dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("CONNECTION MAPPER")
        title.setStyleSheet("color: #00d9ff; font-size: 14px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(title)

        # Controls
        ctrl_row = QHBoxLayout()
        self.btn_start = QPushButton("START MAPPING")
        self.btn_start.setStyleSheet("""
            QPushButton { background: #00ff88; color: #0a0e1a; font-weight: bold; border: none; padding: 6px 18px; border-radius: 4px; }
            QPushButton:hover { background: #00cc6a; }
        """)
        self.btn_start.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_start.clicked.connect(self._toggle_mapping)
        ctrl_row.addWidget(self.btn_start)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "TCP Only", "UDP Only", "Established Only", "Gaming Ports"])
        self.filter_combo.setStyleSheet("""
            QComboBox { background: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; padding: 4px 8px; }
            QComboBox::drop-down { border: none; }
        """)
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
        self.topo_label.setStyleSheet("""
            color: #94a3b8; font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px; background: #0a1628; border: 1px solid #1a2a3a;
            border-radius: 4px; padding: 8px;
        """)
        self.topo_label.setWordWrap(True)
        self.topo_label.setMinimumHeight(80)
        layout.addWidget(self.topo_label)

        # Connection table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Proto", "Local Port", "Remote IP", "Remote Port", "State", "PID", "Hostname"
        ])
        hdr = self.table.horizontalHeader()
        for i in range(7):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #0f1923; color: #e0e0e0; border: 1px solid #1a2a3a; }
            QTableWidget::item:selected { background-color: rgba(0,217,255,0.2); }
            QTableWidget::item:alternate { background-color: #0a1628; }
            QHeaderView::section { background-color: #16213e; color: #00d9ff; padding: 6px; border: 1px solid #1a2a3a; font-weight: bold; }
        """)
        layout.addWidget(self.table, 1)

        # Summary row
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.summary_label)

        self._refresh_done.connect(self._update_display)

    # -- Gaming port set for filter --
    GAMING_PORTS = {
        3074, 3478, 3479, 3480, 9306, 27015, 27016, 27017,
        7777, 7778, 2302, 2303, 2304, 2305, 25565, 19132, 30120,
    }

    def _toggle_mapping(self):
        if self._running:
            self._running = False
            self.btn_start.setText("START MAPPING")
            self.btn_start.setStyleSheet("""
                QPushButton { background: #00ff88; color: #0a0e1a; font-weight: bold; border: none; padding: 6px 18px; border-radius: 4px; }
                QPushButton:hover { background: #00cc6a; }
            """)
            self.status_label.setText("Stopped")
        else:
            self._running = True
            self.btn_start.setText("STOP")
            self.btn_start.setStyleSheet("""
                QPushButton { background: #ff4444; color: white; font-weight: bold; border: none; padding: 6px 18px; border-radius: 4px; }
                QPushButton:hover { background: #cc3333; }
            """)
            self.status_label.setText("Mapping...")
            self._thread = threading.Thread(target=self._map_loop, daemon=True)
            self._thread.start()

    def _map_loop(self):
        """Background loop that collects connection data every 3 seconds."""
        while self._running:
            try:
                import psutil
                raw = psutil.net_connections(kind='inet')
                connections = []
                for c in raw:
                    if not c.raddr:
                        continue  # skip listening-only sockets
                    rip = c.raddr.ip if c.raddr else ""
                    rport = c.raddr.port if c.raddr else 0
                    lip = c.laddr.ip if c.laddr else ""
                    lport = c.laddr.port if c.laddr else 0

                    # Skip loopback
                    if rip.startswith("127.") or rip == "::1":
                        continue

                    proto = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
                    state = c.status if hasattr(c, 'status') else ""

                    # Resolve hostname (cached)
                    hostname = ""
                    if self.chk_resolve.isChecked():
                        hostname = self._resolve_cache.get(rip, "")
                        if not hostname:
                            try:
                                hostname = socket.getfqdn(rip)
                                if hostname == rip:
                                    hostname = ""
                            except Exception:
                                hostname = ""
                            self._resolve_cache[rip] = hostname

                    connections.append({
                        "proto": proto,
                        "lport": lport,
                        "rip": rip,
                        "rport": rport,
                        "state": state,
                        "pid": c.pid or 0,
                        "hostname": hostname,
                    })

                self._refresh_done.emit(connections)
            except ImportError:
                pass
            except Exception as e:
                log_error(f"Connection mapper error: {e}")

            time.sleep(3)

    @pyqtSlot(list)
    def _update_display(self, connections: list):
        """Update table and topology from collected connection data."""
        # Apply filter
        filt = self.filter_combo.currentText()
        filtered = connections
        if filt == "TCP Only":
            filtered = [c for c in connections if c["proto"] == "TCP"]
        elif filt == "UDP Only":
            filtered = [c for c in connections if c["proto"] == "UDP"]
        elif filt == "Established Only":
            filtered = [c for c in connections if c["state"] == "ESTABLISHED"]
        elif filt == "Gaming Ports":
            filtered = [c for c in connections
                        if c["rport"] in self.GAMING_PORTS or c["lport"] in self.GAMING_PORTS]

        # Build topology summary — group by remote IP
        ip_map: Dict[str, list] = {}
        for c in filtered:
            ip_map.setdefault(c["rip"], []).append(c)

        # Text topology
        lines = []
        local_label = "[ THIS PC ]"
        for rip, conns in sorted(ip_map.items(), key=lambda x: len(x[1]), reverse=True)[:12]:
            host = conns[0].get("hostname") or ""
            label = f"{rip}" + (f" ({host})" if host else "")
            ports = sorted(set(c["rport"] for c in conns))
            port_str = ", ".join(str(p) for p in ports[:6])
            if len(ports) > 6:
                port_str += f" +{len(ports)-6}"
            arrow = f"{'─' * 3}{'►'}"
            lines.append(f"  {local_label} {arrow} {label}  [{len(conns)} conn, ports: {port_str}]")
            local_label = " " * len(local_label)  # indent subsequent lines

        if not lines:
            self.topo_label.setText("  No active connections matching filter.")
        else:
            self.topo_label.setText("\n".join(lines))

        # Populate table
        self.table.setRowCount(0)
        for c in filtered:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(c["proto"]))
            self.table.setItem(row, 1, QTableWidgetItem(str(c["lport"])))
            self.table.setItem(row, 2, QTableWidgetItem(c["rip"]))
            self.table.setItem(row, 3, QTableWidgetItem(str(c["rport"])))

            state_item = QTableWidgetItem(c["state"])
            if c["state"] == "ESTABLISHED":
                state_item.setForeground(QColor("#00ff88"))
            elif c["state"] in ("TIME_WAIT", "CLOSE_WAIT"):
                state_item.setForeground(QColor("#fbbf24"))
            elif c["state"] in ("SYN_SENT", "SYN_RECV"):
                state_item.setForeground(QColor("#a855f7"))
            else:
                state_item.setForeground(QColor("#6b7280"))
            self.table.setItem(row, 4, state_item)

            self.table.setItem(row, 5, QTableWidgetItem(str(c["pid"]) if c["pid"] else "—"))
            self.table.setItem(row, 6, QTableWidgetItem(c["hostname"]))

        # Summary
        unique_ips = len(ip_map)
        tcp_count = sum(1 for c in filtered if c["proto"] == "TCP")
        udp_count = sum(1 for c in filtered if c["proto"] == "UDP")
        gaming = sum(1 for c in filtered
                     if c["rport"] in self.GAMING_PORTS or c["lport"] in self.GAMING_PORTS)
        self.summary_label.setText(
            f"{len(filtered)} connections | {unique_ips} unique IPs | "
            f"TCP: {tcp_count} | UDP: {udp_count} | Gaming: {gaming}"
        )
        self.status_label.setText(f"Updated {time.strftime('%H:%M:%S')}")

    def cleanup(self):
        """Stop mapping thread when widget is destroyed."""
        self._running = False


# ======================================================================
# Combined Network Tools View
# ======================================================================
class NetworkToolsView(QWidget):
    """Tabbed container for all network intelligence tools."""

    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #1a2a3a; background: #0a0e1a; }
            QTabBar::tab {
                background: #16213e; color: #94a3b8; padding: 8px 16px;
                border: 1px solid #1a2a3a; border-bottom: none; font-weight: bold;
            }
            QTabBar::tab:selected { background: #0a0e1a; color: #00d9ff; border-bottom: 2px solid #00d9ff; }
            QTabBar::tab:hover { color: #e0e0e0; }
        """)

        self.traffic_tab = TrafficMonitorWidget(controller=controller)
        self.tabs.addTab(self.traffic_tab, "Traffic Monitor")

        self.latency_tab = LatencyOverlayWidget()
        self.tabs.addTab(self.latency_tab, "Latency Overlay")

        self.scanner_tab = PortScannerWidget(controller=controller)
        self.tabs.addTab(self.scanner_tab, "Port Scanner")

        self.mapper_tab = ConnectionMapperWidget(controller=controller)
        self.tabs.addTab(self.mapper_tab, "Connection Mapper")

        layout.addWidget(self.tabs)

    def cleanup(self):
        """Stop all background threads and timers."""
        self.traffic_tab.cleanup()
        self.latency_tab.cleanup()
        self.mapper_tab.cleanup()
