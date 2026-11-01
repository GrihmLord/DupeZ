"""Fail-closed ownership tests for the LAN Cut GUI lifecycle."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget

from app.core.safety_policy import SafetyPolicy
from app.gui.panels import lan_cut_panel as lan_cut_module
from app.gui.panels.lan_cut_panel import LanCutPanel


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Spoofer:
    def __init__(self, *, stop_releases: bool = True, stop_raises: bool = False):
        self.active = True
        self.stop_releases = stop_releases
        self.stop_raises = stop_raises
        self.stop_calls = 0

    @property
    def is_active(self) -> bool:
        return self.active

    def start(self) -> bool:
        return True

    def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_raises:
            raise RuntimeError("stop failed")
        if self.stop_releases:
            self.active = False


class _Journal:
    def __init__(self) -> None:
        self.marked = []
        self.cleared = 0

    def mark_forwarding_change(self, state: bool) -> None:
        self.marked.append(state)

    def clear_forwarding_change(self) -> None:
        self.cleared += 1


def _make_panel(qapp: QApplication, *, policy: SafetyPolicy | None = None) -> LanCutPanel:
    del qapp
    panel = LanCutPanel.__new__(LanCutPanel)
    QWidget.__init__(panel)
    controller = SimpleNamespace(
        safety_policy=policy or SafetyPolicy(),
        network_operations_available=True,
    )
    panel._view = SimpleNamespace(controller=controller)
    panel._arp_spoofers = {}
    panel._forwarding_was_on = None
    panel._a2s_probe = None
    panel._a2s_baseline = None
    panel._refresh_row_for = Mock()
    panel._refresh_active_count = Mock()
    panel._stop_a2s = Mock()
    return panel


def _silence_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lan_cut_module.QMessageBox, "warning", Mock())
    monkeypatch.setattr(lan_cut_module.QMessageBox, "critical", Mock())
    monkeypatch.setattr(lan_cut_module.QMessageBox, "information", Mock())


def test_start_fails_closed_when_forwarding_state_is_unobservable(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.network import arp_spoof

    panel = _make_panel(qapp)
    _silence_dialogs(monkeypatch)
    monkeypatch.setattr(
        lan_cut_module,
        "check_npcap",
        lambda: SimpleNamespace(available=True),
    )
    constructed = Mock()
    monkeypatch.setattr(arp_spoof, "ArpSpoofer", constructed)
    monkeypatch.setattr(
        arp_spoof,
        "_get_ip_forwarding_state",
        Mock(side_effect=RuntimeError("helper unavailable")),
    )
    set_forwarding = Mock()
    monkeypatch.setattr(arp_spoof, "_set_ip_forwarding", set_forwarding)

    assert panel._start_cut("192.168.1.20") is False
    assert panel._forwarding_was_on is None
    assert panel._arp_spoofers == {}
    constructed.assert_not_called()
    set_forwarding.assert_not_called()


def test_start_and_cleanup_verify_both_forwarding_transitions(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import operation_journal
    from app.network import arp_spoof

    panel = _make_panel(qapp)
    _silence_dialogs(monkeypatch)
    monkeypatch.setattr(
        lan_cut_module,
        "check_npcap",
        lambda: SimpleNamespace(available=True),
    )
    spoofer = _Spoofer()
    monkeypatch.setattr(arp_spoof, "ArpSpoofer", lambda **_kwargs: spoofer)
    states = iter((True, False, True))
    monkeypatch.setattr(
        arp_spoof,
        "_get_ip_forwarding_state",
        lambda: next(states),
    )
    set_forwarding = Mock(return_value=True)
    monkeypatch.setattr(arp_spoof, "_set_ip_forwarding", set_forwarding)
    journal = _Journal()
    monkeypatch.setattr(operation_journal, "OperationJournal", lambda: journal)

    assert panel._start_cut("192.168.1.20") is True
    assert panel._arp_spoofers == {"192.168.1.20": spoofer}
    assert panel._forwarding_was_on is True

    assert panel.cleanup() is True
    assert panel._arp_spoofers == {}
    assert panel._forwarding_was_on is None
    assert set_forwarding.call_args_list == [
        call(False),
        call(True),
    ]
    assert journal.marked == [True]
    assert journal.cleared == 1
    panel._stop_a2s.assert_called_once_with()


def test_stop_retains_owner_until_spoofer_reports_inactive(
    qapp: QApplication,
) -> None:
    panel = _make_panel(qapp)
    spoofer = _Spoofer(stop_releases=False)
    panel._arp_spoofers["192.168.1.20"] = spoofer
    panel._forwarding_was_on = False

    assert panel._stop_cut("192.168.1.20") is False
    assert panel._arp_spoofers["192.168.1.20"] is spoofer
    assert panel._forwarding_was_on is False


def test_stop_retains_owner_until_forwarding_restore_is_verified(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import operation_journal
    from app.network import arp_spoof

    panel = _make_panel(qapp)
    spoofer = _Spoofer()
    panel._arp_spoofers["192.168.1.20"] = spoofer
    panel._forwarding_was_on = True
    set_forwarding = Mock(side_effect=(False, True))
    monkeypatch.setattr(arp_spoof, "_set_ip_forwarding", set_forwarding)
    monkeypatch.setattr(arp_spoof, "_get_ip_forwarding_state", lambda: True)
    journal = _Journal()
    monkeypatch.setattr(operation_journal, "OperationJournal", lambda: journal)

    assert panel._stop_cut("192.168.1.20") is False
    assert panel._arp_spoofers["192.168.1.20"] is spoofer
    assert panel._forwarding_was_on is True

    assert panel._stop_cut("192.168.1.20") is True
    assert panel._arp_spoofers == {}
    assert panel._forwarding_was_on is None
    assert spoofer.stop_calls == 2
    assert journal.cleared == 1


def test_target_scope_rejects_public_ip_before_capability_probe(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = _make_panel(qapp)
    _silence_dialogs(monkeypatch)
    capability_probe = Mock()
    monkeypatch.setattr(lan_cut_module, "check_npcap", capability_probe)

    assert panel._start_cut("8.8.8.8") is False
    capability_probe.assert_not_called()
    assert panel._arp_spoofers == {}


def test_network_tools_cleanup_runs_lan_cut_first_and_continues_on_failure(
    qapp: QApplication,
) -> None:
    from app.gui.network_tools import NetworkToolsView

    del qapp
    order = []

    def child(name: str, result=None):
        return SimpleNamespace(
            cleanup=lambda: (order.append(name), result)[1],
        )

    view = NetworkToolsView.__new__(NetworkToolsView)
    QWidget.__init__(view)
    view.lan_cut_tab = child("lan", False)
    view.traffic_tab = child("traffic")
    view.latency_tab = child("latency")
    view.scanner_tab = child("scanner")
    view.mapper_tab = child("mapper")

    assert view.cleanup() is False
    assert order == ["lan", "traffic", "latency", "scanner", "mapper"]


def test_dashboard_shutdown_runs_controller_after_unconfirmed_lan_cleanup(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.gui import dashboard as dashboard_module
    from app.gui.dashboard import DupeZDashboard

    del qapp
    dashboard = DupeZDashboard.__new__(DupeZDashboard)
    QMainWindow.__init__(dashboard)
    dashboard._minimize_to_tray = False
    dashboard._force_quit = True
    dashboard.tray_icon = None
    dashboard._dashboard_poll_generation = 0
    dashboard._dashboard_poll_in_flight = True
    dashboard._status_timer = SimpleNamespace(stop=Mock())
    dashboard._stats_timer = SimpleNamespace(stop=Mock())
    dashboard.clumsy_view = SimpleNamespace(stop_background_refresh=Mock())
    dashboard.nettools_view = SimpleNamespace(cleanup=Mock(return_value=False))
    dashboard.controller = SimpleNamespace(shutdown=Mock())
    event = SimpleNamespace(accept=Mock(), ignore=Mock())
    monkeypatch.setattr(dashboard_module, "KEYBOARD_AVAILABLE", False)
    monkeypatch.setattr(dashboard_module.gc, "collect", Mock())
    critical = Mock()
    monkeypatch.setattr(dashboard_module.QMessageBox, "critical", critical)

    dashboard.closeEvent(event)

    dashboard.nettools_view.cleanup.assert_called_once_with()
    dashboard.controller.shutdown.assert_called_once_with()
    event.ignore.assert_called_once_with()
    event.accept.assert_not_called()
    critical.assert_called_once()


def test_dashboard_shutdown_refuses_close_when_controller_retains_ownership(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.gui import dashboard as dashboard_module
    from app.gui.dashboard import DupeZDashboard

    del qapp
    dashboard = DupeZDashboard.__new__(DupeZDashboard)
    QMainWindow.__init__(dashboard)
    dashboard._minimize_to_tray = False
    dashboard._force_quit = True
    dashboard.tray_icon = None
    dashboard._dashboard_poll_generation = 0
    dashboard._dashboard_poll_in_flight = True
    dashboard._status_timer = SimpleNamespace(stop=Mock())
    dashboard._stats_timer = SimpleNamespace(stop=Mock())
    dashboard.clumsy_view = SimpleNamespace(stop_background_refresh=Mock())
    dashboard.nettools_view = SimpleNamespace(cleanup=Mock(return_value=True))
    dashboard.controller = SimpleNamespace(shutdown=Mock(return_value=False))
    event = SimpleNamespace(accept=Mock(), ignore=Mock())
    monkeypatch.setattr(dashboard_module, "KEYBOARD_AVAILABLE", False)
    monkeypatch.setattr(dashboard_module.gc, "collect", Mock())
    monkeypatch.setattr(dashboard_module.QMessageBox, "critical", Mock())

    dashboard.closeEvent(event)

    dashboard.controller.shutdown.assert_called_once_with()
    event.ignore.assert_called_once_with()
    event.accept.assert_not_called()
