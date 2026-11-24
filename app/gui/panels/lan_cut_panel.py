# app/gui/panels/lan_cut_panel.py — NetCut-style LAN severance widget
"""One-click ARP-local forwarding severance for any device on the same WiFi /24.

Unlike the main disruption engine (which layers WinDivert on top of
local forwarding to do timing-based cuts), LAN Cut just:

  1. Starts ``ArpSpoofer`` (target + gateway forwarding setup).
  2. DISABLES IP forwarding.

With forwarding setup active and forwarding off, the target device's upstream
traffic lands at this laptop and is dropped at the IP layer — instant
total severance, no WinDivert, no disruption modules. This is the
canonical "NetCut" primitive.

On STOP:
  * Corrective ARP replies restore real MACs in both caches.
  * IP forwarding is restored to its prior state.

Npcap (Windows) or AF_PACKET+root (Linux) is required; the panel shows
a red status banner when unavailable.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView, QMessageBox,
    QAbstractItemView,
)

from app.logs.logger import log_error, log_info
from app.network.npcap_check import check_npcap

__all__ = ["LanCutPanel"]


class LanCutPanel(QWidget):
    """Scans the local /24, lists devices, cuts any one with a click."""

    _scan_done = pyqtSignal(list)
    _a2s_update = pyqtSignal(object)   # A2SSnapshot; object to avoid metatype reg

    def __init__(self, parent_view, parent=None) -> None:
        super().__init__(parent)
        self._view = parent_view
        self._arp_spoofers: Dict[str, object] = {}   # ip -> ArpSpoofer
        self._forwarding_was_on: Optional[bool] = None
        # Server Monitor (A2S badge) state
        self._a2s_probe: Optional[object] = None
        self._a2s_baseline: Optional[int] = None
        self._setup_ui()
        self._scan_done.connect(self._on_scan_done)
        self._a2s_update.connect(self._on_a2s_snapshot)
        # Defer first scan so UI renders before the network thread runs
        QTimer.singleShot(500, self._start_scan)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.setLayout(root)

        group = self._view._card("LAN CUT (NetCut-style)")
        gl = QVBoxLayout()
        gl.setSpacing(6)

        # ── Npcap status banner ─────────────────────────────────────
        status = check_npcap()
        color = "#10b981" if status.available else "#ef4444"
        self.status_label = QLabel(status.short())
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 10px; padding: 4px 8px; "
            f"background: rgba(8,12,22,0.6); border: 1px solid {color}; "
            f"border-radius: 6px; font-weight: 700;"
        )
        gl.addWidget(self.status_label)
        if not status.available:
            hint = QLabel(
                "Install Npcap from https://npcap.com/#download "
                "(check the WinPcap-API-compatible option during install)."
            )
            hint.setStyleSheet("color: #94a3b8; font-size: 9px; padding: 2px 8px;")
            hint.setWordWrap(True)
            gl.addWidget(hint)

        # ── Server Monitor (A2S badge) ──────────────────────────────
        # Polls A2S_INFO against a game server and shows live player
        # count vs baseline. When the count drops while a cut is
        # active, that's the isolation window landing.
        srv_row = QHBoxLayout()
        srv_row.setSpacing(4)

        srv_label = QLabel("SERVER:")
        srv_label.setStyleSheet("color:#94a3b8; font-size:9px; font-weight:700;")
        srv_row.addWidget(srv_label)

        self.a2s_host_edit = QLineEdit()
        self.a2s_host_edit.setPlaceholderText("server IP (e.g. 198.51.100.10)")
        self.a2s_host_edit.setStyleSheet(
            "QLineEdit { background:#0a1628; color:#cbd5e1; "
            "border:1px solid #1e293b; border-radius:4px; "
            "padding:2px 6px; font-size:10px; }"
        )
        self.a2s_host_edit.setMaximumWidth(170)
        srv_row.addWidget(self.a2s_host_edit)

        self.a2s_port_spin = QSpinBox()
        self.a2s_port_spin.setRange(1, 65535)
        self.a2s_port_spin.setValue(27016)
        self.a2s_port_spin.setStyleSheet(
            "QSpinBox { background:#0a1628; color:#cbd5e1; "
            "border:1px solid #1e293b; border-radius:4px; "
            "padding:2px 6px; font-size:10px; }"
        )
        self.a2s_port_spin.setMaximumWidth(80)
        srv_row.addWidget(self.a2s_port_spin)

        self.btn_a2s_toggle = self._view._make_btn(
            "WATCH", "#a78bfa", "#0a1628", h=24,
            tip="Poll A2S_INFO every second. Baseline on first reachable "
                "response; highlights drops = hive evicted our session.",
        )
        self.btn_a2s_toggle.clicked.connect(self._toggle_a2s)
        srv_row.addWidget(self.btn_a2s_toggle)

        # Live badge
        self.a2s_badge = QLabel("— idle —")
        self.a2s_badge.setTextFormat(Qt.TextFormat.PlainText)
        self.a2s_badge.setStyleSheet(
            "color:#64748b; font-size:10px; font-weight:700; "
            "padding:3px 10px; background:rgba(8,12,22,0.6); "
            "border:1px solid #1e293b; border-radius:6px;"
        )
        self.a2s_badge.setMinimumWidth(220)
        srv_row.addWidget(self.a2s_badge, 1)

        gl.addLayout(srv_row)

        # ── Toolbar ─────────────────────────────────────────────────
        tools = QHBoxLayout()
        self.btn_scan = self._view._make_btn(
            "RESCAN LAN", "#00d9ff", "#0a1628", h=26)
        self.btn_scan.clicked.connect(self._start_scan)
        tools.addWidget(self.btn_scan)

        self.btn_restore_all = self._view._make_btn(
            "RESTORE ALL", "#10b981", "#0a1628", h=26,
            tip="Stop every active cut, restore ARP caches, re-enable forwarding.",
        )
        self.btn_restore_all.clicked.connect(self._restore_all)
        tools.addWidget(self.btn_restore_all)
        tools.addStretch(1)

        self.active_label = QLabel("Active cuts: 0")
        self.active_label.setStyleSheet(
            "color: #94a3b8; font-size: 10px; padding: 2px 8px;")
        tools.addWidget(self.active_label)
        gl.addLayout(tools)

        # ── Device table ────────────────────────────────────────────
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["IP", "MAC", "Hostname", "Status", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { background:#0a1628; color:#cbd5e1; "
            "border:1px solid #1e293b; gridline-color:#1e293b; font-size:10px; }"
            "QHeaderView::section { background:#111827; color:#94a3b8; "
            "border:0; border-bottom:1px solid #1e293b; padding:4px; }"
        )
        self.table.setMinimumHeight(160)
        gl.addWidget(self.table)

        warn = QLabel(
            "LAN Cut severs the target's internet via ARP cache forwarding setup + "
            "IP-forwarding OFF. Use only on devices you own. Stop promptly "
            "to avoid leaving stale local forwarding entries."
        )
        warn.setStyleSheet("color: #f59e0b; font-size: 9px; padding: 4px 8px;")
        warn.setWordWrap(True)
        gl.addWidget(warn)

        group.setLayout(gl)
        root.addWidget(group)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def _start_scan(self) -> None:
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("SCANNING…")

        def _work() -> None:
            try:
                from app.network.device_scan import scan_devices
                devices = scan_devices(quick=True)
            except Exception as exc:
                log_error(f"[LAN CUT] scan failed: {exc}")
                devices = []
            self._scan_done.emit(list(devices))

        threading.Thread(target=_work, daemon=True, name="LanCutScan").start()

    def _on_scan_done(self, devices: List[Dict]) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("RESCAN LAN")

        self.table.setRowCount(0)
        for dev in devices:
            ip = dev.get("ip") or ""
            if not ip:
                continue
            mac = dev.get("mac") or "—"
            host = dev.get("hostname") or dev.get("device_type") or ""
            owned = ip in self._arp_spoofers
            active = self._spoofer_is_active(self._arp_spoofers.get(ip))

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(ip))
            self.table.setItem(row, 1, QTableWidgetItem(mac))
            self.table.setItem(row, 2, QTableWidgetItem(host))

            status_text = (
                "CUT" if active else "RESTORE PENDING" if owned else "online"
            )
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, status_item)

            btn = QPushButton("RESTORE" if owned else "CUT")
            btn.setStyleSheet(self._btn_qss(owned))
            btn.clicked.connect(lambda _=False, _ip=ip: self._toggle(_ip))
            self.table.setCellWidget(row, 4, btn)

        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(3)
        self.table.resizeColumnToContents(4)
        self._refresh_active_count()

    # ------------------------------------------------------------------
    # Cut / restore
    # ------------------------------------------------------------------
    def _toggle(self, ip: str) -> None:
        if ip in self._arp_spoofers:
            self._stop_cut(ip)
        else:
            self._start_cut(ip)
        # Refresh table row state
        self._refresh_row_for(ip)
        self._refresh_active_count()

    def _start_cut(self, ip: str) -> bool:
        """Start a cut only after safety and forwarding state are observable.

        The panel owns every spoofer from the moment ``start()`` succeeds until
        both the spoofer has stopped and the original forwarding state has
        been restored.  That ownership is intentionally retained on cleanup
        failure so the operator (or shutdown path) can retry.
        """
        try:
            ip = self._validate_target(ip)
        except (RuntimeError, ValueError) as exc:
            log_error(f"[LAN CUT] refused target {ip!r}: {exc}")
            QMessageBox.warning(self, "LAN Cut refused", str(exc))
            return False

        status = check_npcap()
        if not status.available:
            QMessageBox.warning(
                self, "LAN Cut unavailable",
                f"Cannot start local forwarding — {status.reason}\n\n"
                f"Install Npcap: {status.install_url}",
            )
            return False

        try:
            from app.network.arp_spoof import ArpSpoofer, _get_ip_forwarding_state, _set_ip_forwarding
        except Exception as exc:
            log_error(f"[LAN CUT] import failed: {exc}")
            QMessageBox.critical(self, "LAN Cut error",
                                 f"local forwarding module unavailable: {exc}")
            return False

        # Remember forwarding state only on the FIRST cut of this session.
        if not self._arp_spoofers:
            try:
                self._forwarding_was_on = _get_ip_forwarding_state()
            except Exception as exc:
                # False is a valid state.  Treating an unavailable query as
                # False can permanently disable forwarding that was enabled
                # before DupeZ started, so mutation must fail closed here.
                self._forwarding_was_on = None
                log_error(f"[LAN CUT] forwarding-state query failed: {exc}")
                QMessageBox.critical(
                    self,
                    "LAN Cut safety check failed",
                    "Could not determine the current IP-forwarding state. "
                    "No network changes were made.",
                )
                return False

        try:
            spoofer = ArpSpoofer(target_ip=ip)
        except Exception as exc:
            if not self._arp_spoofers:
                self._forwarding_was_on = None
            log_error(f"[LAN CUT] could not create spoofer for {ip}: {exc}")
            QMessageBox.warning(self, "LAN Cut failed", str(exc))
            return False
        if not spoofer.start():
            if not self._arp_spoofers:
                self._forwarding_was_on = None
            QMessageBox.warning(
                self, "LAN Cut failed",
                f"Could not start local forwarding for {ip}. Check logs for details.",
            )
            return False

        # From this point on, retain ownership until restoration is confirmed.
        self._arp_spoofers[ip] = spoofer

        # Kill the severance: disable IP forwarding so nothing routes through.
        try:
            from app.core.operation_journal import OperationJournal
            OperationJournal().mark_forwarding_change(
                bool(self._forwarding_was_on)
            )
            if not _set_ip_forwarding(False):
                raise RuntimeError("failed to disable IP forwarding")
            if _get_ip_forwarding_state() is not False:
                raise RuntimeError(
                    "IP forwarding remained enabled after the disable request"
                )
        except Exception as exc:
            log_error(f"[LAN CUT] disable forwarding failed: {exc}")
            restored = self._stop_cut(ip)
            detail = (
                "The partial operation was restored."
                if restored
                else "Cleanup is still pending; use RESTORE ALL before exiting."
            )
            QMessageBox.critical(
                self,
                "LAN Cut failed safely",
                f"Could not confirm that IP forwarding was disabled. {detail}",
            )
            return False

        log_info(f"[LAN CUT] severed {ip}")
        return True

    def _stop_cut(self, ip: str) -> bool:
        """Stop one owned cut and return whether release was confirmed."""
        spoofer = self._arp_spoofers.get(ip)
        if spoofer is None:
            return True
        try:
            spoofer.stop()
        except Exception as exc:
            log_error(f"[LAN CUT] stop {ip} failed: {exc}")
            return False

        if self._spoofer_is_active(spoofer):
            log_error(
                f"[LAN CUT] stop {ip} was not confirmed; spoofer remains active"
            )
            return False

        # Keep the final owner in the map until the process-wide forwarding
        # state has also been restored and read back successfully.
        if len(self._arp_spoofers) == 1 and not self._restore_forwarding():
            return False

        self._arp_spoofers.pop(ip, None)
        log_info(f"[LAN CUT] restored {ip}")
        return True

    def _restore_all(self) -> bool:
        """Attempt to release all owned cuts, retaining failed owners."""
        restored = True
        for ip in list(self._arp_spoofers.keys()):
            if not self._stop_cut(ip):
                restored = False
            self._refresh_row_for(ip)

        # Defensive recovery for a partial start that obtained the original
        # forwarding state but failed before an owner was recorded.
        if not self._arp_spoofers and self._forwarding_was_on is not None:
            restored = self._restore_forwarding() and restored

        self._refresh_active_count()
        return (
            restored
            and not self._arp_spoofers
            and self._forwarding_was_on is None
        )

    def _restore_forwarding(self) -> bool:
        """Restore and verify the forwarding state saved at first mutation."""
        expected = self._forwarding_was_on
        if expected is None:
            log_error("[LAN CUT] forwarding restore refused: prior state unknown")
            return False

        try:
            from app.network.arp_spoof import (
                _get_ip_forwarding_state,
                _set_ip_forwarding,
            )

            if not _set_ip_forwarding(bool(expected)):
                raise RuntimeError("forwarding update was not acknowledged")
            actual = _get_ip_forwarding_state()
            if actual is not bool(expected):
                raise RuntimeError(
                    f"forwarding verification mismatch (expected {expected}, "
                    f"observed {actual})"
                )

            from app.core.operation_journal import OperationJournal
            OperationJournal().clear_forwarding_change()
        except Exception as exc:
            log_error(f"[LAN CUT] restore forwarding failed: {exc}")
            return False

        self._forwarding_was_on = None
        return True

    def _validate_target(self, ip: str) -> str:
        """Apply the controller's fail-closed target scope to LAN Cut."""
        controller = getattr(self._view, "controller", None)
        policy = getattr(controller, "safety_policy", None)
        if controller is None or policy is None:
            raise RuntimeError(
                "Network safety controls are unavailable; LAN Cut is disabled."
            )
        if getattr(controller, "network_operations_available", True) is not True:
            raise RuntimeError(
                "Network operations are blocked until startup recovery completes."
            )

        target = policy.validate_target(ip)
        if bool(getattr(policy, "dry_run", False)):
            raise RuntimeError(
                f"Safety dry-run is enabled; LAN Cut did not modify {target}."
            )
        return target

    @staticmethod
    def _spoofer_is_active(spoofer: object | None) -> bool:
        if spoofer is None:
            return False
        try:
            return bool(spoofer.is_active)
        except Exception as exc:
            # An unreadable state is not positive confirmation of release.
            log_error(f"[LAN CUT] could not query spoofer state: {exc}")
            return True

    def cleanup(self) -> bool:
        """Stop monitoring and return whether every network change restored."""
        self._stop_a2s()
        return self._restore_all()

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------
    def _refresh_row_for(self, ip: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == ip:
                owned = ip in self._arp_spoofers
                active = self._spoofer_is_active(self._arp_spoofers.get(ip))
                self.table.item(row, 3).setText(
                    "CUT" if active else "RESTORE PENDING" if owned else "online"
                )
                btn = self.table.cellWidget(row, 4)
                if isinstance(btn, QPushButton):
                    btn.setText("RESTORE" if owned else "CUT")
                    btn.setStyleSheet(self._btn_qss(owned))
                return

    def _refresh_active_count(self) -> None:
        active = sum(
            1 for spoofer in self._arp_spoofers.values()
            if self._spoofer_is_active(spoofer)
        )
        pending = len(self._arp_spoofers) - active
        suffix = f" · restore pending: {pending}" if pending else ""
        self.active_label.setText(f"Active cuts: {active}{suffix}")

    @staticmethod
    def _btn_qss(active: bool) -> str:
        bg = "#10b981" if active else "#ef4444"
        return (f"QPushButton {{ background:{bg}; color:#0a1628; "
                f"font-weight:700; font-size:10px; border:0; "
                f"border-radius:4px; padding:4px 10px; }}"
                f"QPushButton:hover {{ opacity:0.85; }}")

    # ------------------------------------------------------------------
    # Server Monitor (A2S badge)
    # ------------------------------------------------------------------
    def _toggle_a2s(self) -> None:
        if self._a2s_probe is not None:
            self._stop_a2s()
        else:
            self._start_a2s()

    def _start_a2s(self) -> None:
        host = self.a2s_host_edit.text().strip()
        port = int(self.a2s_port_spin.value())
        if not host:
            QMessageBox.information(
                self, "Server Monitor",
                "Enter the game server IP to start the A2S watch.",
            )
            return
        try:
            from app.network.a2s_probe import A2SProbe
            # Marshal snapshots back to the GUI thread via signal.
            probe = A2SProbe(host=host, port=port, interval_s=1.0, timeout_s=1.0)
            probe.subscribe(lambda snap: self._a2s_update.emit(snap))
            probe.start()
            self._a2s_probe = probe
            self._a2s_baseline = None
            self.a2s_badge.setText(f"watching {host}:{port}…")
            self.a2s_badge.setStyleSheet(
                "color:#a78bfa; font-size:10px; font-weight:700; "
                "padding:3px 10px; background:rgba(8,12,22,0.6); "
                "border:1px solid #a78bfa; border-radius:6px;"
            )
            self.btn_a2s_toggle.setText("STOP")
            self.a2s_host_edit.setEnabled(False)
            self.a2s_port_spin.setEnabled(False)
        except Exception as exc:
            log_error(f"[LAN CUT] A2S start failed: {exc}")
            QMessageBox.critical(self, "Server Monitor", f"Failed: {exc}")

    def _stop_a2s(self) -> None:
        probe = self._a2s_probe
        self._a2s_probe = None
        self._a2s_baseline = None
        if probe is not None:
            try:
                probe.stop()
            except Exception:
                pass
        self.a2s_badge.setText("— idle —")
        self.a2s_badge.setStyleSheet(
            "color:#64748b; font-size:10px; font-weight:700; "
            "padding:3px 10px; background:rgba(8,12,22,0.6); "
            "border:1px solid #1e293b; border-radius:6px;"
        )
        self.btn_a2s_toggle.setText("WATCH")
        self.a2s_host_edit.setEnabled(True)
        self.a2s_port_spin.setEnabled(True)

    def _on_a2s_snapshot(self, snap) -> None:
        """Render an A2SSnapshot onto the badge. Thread-safe: called
        from the GUI thread via signal."""
        if snap is None:
            return
        # Cache baseline locally (independent of probe's own baseline so
        # the UI survives probe restarts).
        if snap.reachable and snap.player_count is not None and self._a2s_baseline is None:
            self._a2s_baseline = int(snap.player_count)

        if not snap.reachable:
            self.a2s_badge.setText(
                f"unreachable ({snap.error or 'no response'})"
            )
            self.a2s_badge.setStyleSheet(
                "color:#f59e0b; font-size:10px; font-weight:700; "
                "padding:3px 10px; background:rgba(8,12,22,0.6); "
                "border:1px solid #f59e0b; border-radius:6px;"
            )
            return

        pc = snap.player_count if snap.player_count is not None else 0
        mx = snap.max_players if snap.max_players is not None else 0
        baseline = self._a2s_baseline if self._a2s_baseline is not None else pc
        delta = pc - baseline
        name = (snap.server_name or "")[:24]

        if delta < 0:
            # Player count dropped = cut likely landed
            txt = (f"{name} · {pc}/{mx} ▼{-delta} "
                   f"(baseline {baseline}) CUT LANDED")
            color = "#10b981"
        elif delta > 0:
            txt = f"{name} · {pc}/{mx} ▲{delta} (baseline {baseline})"
            color = "#cbd5e1"
        else:
            txt = f"{name} · {pc}/{mx} (baseline {baseline})"
            color = "#cbd5e1"

        rtt = f" · {snap.rtt_ms:.0f}ms" if snap.rtt_ms is not None else ""
        self.a2s_badge.setText(txt + rtt)
        self.a2s_badge.setStyleSheet(
            f"color:{color}; font-size:10px; font-weight:700; "
            f"padding:3px 10px; background:rgba(8,12,22,0.6); "
            f"border:1px solid {color}; border-radius:6px;"
        )

    # ------------------------------------------------------------------
    # Lifecycle — ensure ARP caches are restored on panel teardown
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        if not self.cleanup():
            log_error(
                "[LAN CUT] panel closed with unconfirmed network restoration"
            )
        super().closeEvent(event)
