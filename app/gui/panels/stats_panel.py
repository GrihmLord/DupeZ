# app/gui/panels/stats_panel.py — Live packet stats dashboard widget
"""Extracted from ClumsyControlView._build_stats_panel / _refresh_stats_panel."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QProgressBar,
)
from PyQt6.QtCore import Qt

from app.logs.logger import log_error

__all__ = ["StatsPanel"]


class StatsPanel(QWidget):
    """Real-time packet statistics dashboard."""

    def __init__(self, parent_view, parent=None) -> None:
        super().__init__(parent)
        self._view = parent_view  # back-ref to ClumsyControlView
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        stats_group = self._view._card("LIVE STATS")
        stats_layout = QVBoxLayout()
        stats_layout.setSpacing(4)

        # Summary row: processed | dropped | passed | in | out
        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)

        _stat_defs = [
            ("PROCESSED", "_stat_processed", "#00f0ff"),
            ("DROPPED",   "_stat_dropped",   "#ff6b6b"),
            ("PASSED",    "_stat_passed",     "#00ff88"),
            ("IN",        "_stat_inbound",    "#a78bfa"),
            ("OUT",       "_stat_outbound",   "#fbbf24"),
        ]
        for label_text, attr, color in _stat_defs:
            widget = QLabel("0")
            setattr(self, attr, widget)
            col = QVBoxLayout()
            col.setSpacing(2)
            header = QLabel(label_text)
            header.setStyleSheet(
                "color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 1px;")
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(header)
            widget.setStyleSheet(
                f"color: {color}; font-size: 14px; font-weight: 700;"
                f" font-family: 'Cascadia Code', 'Consolas', monospace;")
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(widget)
            summary_row.addLayout(col)

        stats_layout.addLayout(summary_row)

        # Drop rate bar
        drop_row = QHBoxLayout()
        drop_lbl = QLabel("DROP RATE:")
        drop_lbl.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold;")
        drop_lbl.setFixedWidth(70)
        drop_row.addWidget(drop_lbl)

        self._stat_drop_bar = self._view._progress_bar("%p%", 14, "#ff4444", "#ff8800")
        drop_row.addWidget(self._stat_drop_bar, 1)
        stats_layout.addLayout(drop_row)

        # Active engines count
        self._stat_engines_label = self._view._lbl("Engines: 0 active", "#6b7280")
        stats_layout.addWidget(self._stat_engines_label)

        # Per-device breakdown (compact table)
        self._stat_device_table = QTableWidget()
        self._stat_device_table.setColumnCount(4)
        self._stat_device_table.setHorizontalHeaderLabels(
            ["Device", "Processed", "Dropped", "Methods"])
        self._stat_device_table.setMaximumHeight(100)
        self._stat_device_table.verticalHeader().setVisible(False)
        self._stat_device_table.setAlternatingRowColors(True)
        hdr = self._stat_device_table.horizontalHeader()
        for i in range(4):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self._stat_device_table.setStyleSheet("""
            QTableWidget {
                background-color: rgba(8,12,22,0.7); color: #e2e8f0;
                border: 1px solid rgba(30,41,59,0.4); gridline-color: rgba(30,41,59,0.25);
                border-radius: 6px; font-size: 10px;
            }
            QTableWidget::item { padding: 4px 6px; }
            QTableWidget::item:alternate { background-color: rgba(15,23,42,0.35); }
            QTableWidget::item:selected { background-color: rgba(0,240,255,0.1); }
            QHeaderView::section {
                background-color: rgba(10,15,26,0.8); color: #64748b; padding: 4px;
                border: none; border-bottom: 1px solid rgba(0,240,255,0.1);
                font-weight: 700; font-size: 9px; letter-spacing: 0.5px;
            }
        """)
        stats_layout.addWidget(self._stat_device_table)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # ── God Mode detail panel (hidden when godmode inactive) ────
        self._godmode_group = self._view._card("GOD MODE")
        gm_layout = QVBoxLayout()
        gm_layout.setSpacing(4)

        # Phase indicator
        self._gm_phase_label = QLabel("INACTIVE")
        self._gm_phase_label.setStyleSheet(
            "color: #6b7280; font-size: 12px; font-weight: bold;")
        self._gm_phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gm_layout.addWidget(self._gm_phase_label)

        # Queue depths row
        gm_queue_row = QHBoxLayout()
        gm_queue_row.setSpacing(12)
        for label_text, attr, color in [
            ("IN QUEUE", "_gm_in_queue", "#a78bfa"),
            ("OUT QUEUE", "_gm_out_queue", "#fbbf24"),
            ("FLUSHES", "_gm_flushes", "#00f0ff"),
            ("GS CULLED", "_gm_culled", "#ff6b6b"),
        ]:
            widget = QLabel("0")
            setattr(self, attr, widget)
            col = QVBoxLayout()
            col.setSpacing(2)
            header = QLabel(label_text)
            header.setStyleSheet(
                "color: #64748b; font-size: 8px; font-weight: 700; letter-spacing: 1px;")
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(header)
            widget.setStyleSheet(
                f"color: {color}; font-size: 12px; font-weight: 700;"
                f" font-family: 'Cascadia Code', 'Consolas', monospace;")
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(widget)
            gm_queue_row.addLayout(col)
        gm_layout.addLayout(gm_queue_row)

        # Classification breakdown
        self._gm_class_label = QLabel("")
        self._gm_class_label.setStyleSheet(
            "color: #94a3b8; font-size: 9px; font-family: monospace;")
        self._gm_class_label.setWordWrap(True)
        gm_layout.addWidget(self._gm_class_label)

        # Kick risk bar
        kick_row = QHBoxLayout()
        kick_lbl = QLabel("KICK RISK:")
        kick_lbl.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold;")
        kick_lbl.setFixedWidth(70)
        kick_row.addWidget(kick_lbl)
        self._gm_kick_bar = self._view._progress_bar("%p%", 14, "#00ff88", "#ff4444")
        kick_row.addWidget(self._gm_kick_bar, 1)
        gm_layout.addLayout(kick_row)

        self._godmode_group.setLayout(gm_layout)
        self._godmode_group.setVisible(False)  # hidden until godmode active
        layout.addWidget(self._godmode_group)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Refresh the stats dashboard with live engine data."""
        controller = self._view.controller
        if not controller or not hasattr(controller, 'get_engine_stats'):
            return
        try:
            stats = controller.get_engine_stats()

            _keys = ("packets_processed", "packets_dropped", "packets_passed",
                     "packets_inbound", "packets_outbound")
            _widgets = (self._stat_processed, self._stat_dropped, self._stat_passed,
                        self._stat_inbound, self._stat_outbound)
            vals = [stats.get(k, 0) for k in _keys]
            for w, v in zip(_widgets, vals):
                w.setText(self._format_count(v))

            # Drop rate
            processed, dropped = vals[0], vals[1]
            self._stat_drop_bar.setValue(
                min(int(dropped / processed * 100), 100) if processed else 0)

            # Active engines
            active = stats.get("active_engines", 0)
            self._stat_engines_label.setText(f"Engines: {active} active")

            # Per-device breakdown
            per_device = stats.get("per_device", {})
            self._stat_device_table.setRowCount(0)
            for ip, dstats in per_device.items():
                row = self._stat_device_table.rowCount()
                self._stat_device_table.insertRow(row)
                display_ip = (self._view._mask_ip(ip)
                              if self._view._ip_hidden else ip)
                self._stat_device_table.setItem(
                    row, 0, QTableWidgetItem(display_ip))
                self._stat_device_table.setItem(
                    row, 1, QTableWidgetItem(
                        self._format_count(dstats.get("packets_processed", 0))))
                self._stat_device_table.setItem(
                    row, 2, QTableWidgetItem(
                        self._format_count(dstats.get("packets_dropped", 0))))
                methods = ", ".join(dstats.get("methods", []))
                self._stat_device_table.setItem(
                    row, 3, QTableWidgetItem(methods))

            # ── God Mode detail panel ───────────────────────────────
            self._refresh_godmode_stats(per_device)

        except Exception as e:
            log_error(f"Stats refresh error: {e}")

    def _refresh_godmode_stats(self, per_device: dict) -> None:
        """Update God Mode stats panel from module-level stats."""
        gm_stats = None
        for _ip, dstats in per_device.items():
            mod_stats = dstats.get("module_stats", {})
            if "GodModeModule" in mod_stats:
                gm_stats = mod_stats["GodModeModule"]
                break

        if not gm_stats:
            self._godmode_group.setVisible(False)
            return

        self._godmode_group.setVisible(True)

        # Queue depths
        in_depth = gm_stats.get("in_queue_depth", 0)
        out_depth = gm_stats.get("out_queue_depth", 0)
        self._gm_in_queue.setText(self._format_count(in_depth))
        self._gm_out_queue.setText(self._format_count(out_depth))
        self._gm_flushes.setText(self._format_count(
            gm_stats.get("pulse_flushes", 0)))
        self._gm_culled.setText(self._format_count(
            gm_stats.get("flush_gamestate_dropped", 0)))

        # Phase indicator — estimate from queue depths and timing
        block_ms = gm_stats.get("block_ms", 3000)
        flush_ms = gm_stats.get("flush_ms", 400)
        total_queued = in_depth + out_depth
        if total_queued > 10:
            self._gm_phase_label.setText(f"BLOCKING ({block_ms}ms)")
            self._gm_phase_label.setStyleSheet(
                "color: #ff4444; font-size: 12px; font-weight: bold;")
        else:
            self._gm_phase_label.setText(f"FLUSHING ({flush_ms}ms)")
            self._gm_phase_label.setStyleSheet(
                "color: #00ff88; font-size: 12px; font-weight: bold;")

        # Classification breakdown
        cls_in = gm_stats.get("class_in", {})
        cls_out = gm_stats.get("class_out", {})
        parts = []
        if cls_in:
            parts.append("IN: " + ", ".join(
                f"{k}={v}" for k, v in cls_in.items()))
        if cls_out:
            parts.append("OUT: " + ", ".join(
                f"{k}={v}" for k, v in cls_out.items()))
        self._gm_class_label.setText(" | ".join(parts) if parts else "")

        # Kick risk estimate
        # Based on: queue depth (higher = more aggressive = riskier),
        # keepalive counts vs queued (low keepalive ratio = risky),
        # and block duration.
        in_keepalive = gm_stats.get("in_keepalive", 0)
        out_keepalive = gm_stats.get("out_keepalive", 0)
        in_queued = gm_stats.get("in_queued", 0)
        out_queued = gm_stats.get("out_queued", 0)
        total_keepalive = in_keepalive + out_keepalive
        total_processed = in_queued + out_queued + total_keepalive
        # Risk factors: block duration, keepalive ratio, queue saturation
        risk = 0
        if block_ms >= 5000:
            risk += 40
        elif block_ms >= 3000:
            risk += 20
        elif block_ms >= 2000:
            risk += 10
        # Low keepalive ratio increases risk
        if total_processed > 100:
            ka_ratio = total_keepalive / total_processed
            if ka_ratio < 0.01:
                risk += 40
            elif ka_ratio < 0.03:
                risk += 20
            elif ka_ratio < 0.05:
                risk += 10
        # High current queue depth
        if total_queued > 500:
            risk += 20
        elif total_queued > 200:
            risk += 10
        self._gm_kick_bar.setValue(min(risk, 100))

    @staticmethod
    def _format_count(n: int) -> str:
        """Format a packet count: 1234 → '1.2K', 1234567 → '1.2M'."""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)
