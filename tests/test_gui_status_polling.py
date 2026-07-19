from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QWidget,
)

from app.gui.clumsy_control import ClumsyControlView
from app.gui.dashboard import DupeZDashboard


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump_until(qapp, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    qapp.processEvents()
    assert predicate()


class _ClumsyHarness(ClumsyControlView):
    def __init__(self, controller) -> None:
        QWidget.__init__(self)
        self.controller = controller
        self._status_poll_generation = 0
        self._status_poll_in_flight = False
        self._clumsy_status_snapshot = {}
        self._disrupted_devices_snapshot = frozenset()
        self._status_snapshot_ready.connect(self._apply_status_snapshot)
        self._status_snapshot_failed.connect(
            self._apply_status_snapshot_error
        )
        self.clumsy_status_label = QLabel(self)
        self.device_table = QTableWidget(0, 7, self)
        self.network_combo = QComboBox(self)
        self.network_combo.addItem("All Networks")
        self.device_count_label = QLabel(self)
        self.devices = []
        self.selected_ip = None
        self.selected_ips = set()
        self._disruption_timers = {}
        self._row_checkboxes = []
        self._ip_hidden = False


class _BlockingClumsyController:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.status_calls = 0
        self.disrupted_calls = 0
        self.worker_thread_id = None

    def get_clumsy_status(self):
        self.status_calls += 1
        self.worker_thread_id = threading.get_ident()
        self.entered.set()
        self.release.wait(2.0)
        return {
            "is_admin": True,
            "clumsy_exe_exists": True,
            "windivert_dll_exists": True,
            "disrupted_devices_count": 1,
        }

    def get_disrupted_devices(self):
        self.disrupted_calls += 1
        return ["192.0.2.10"]


def test_clumsy_status_poll_is_nonblocking_and_single_flight(qapp):
    controller = _BlockingClumsyController()
    view = _ClumsyHarness(controller)
    main_thread_id = threading.get_ident()

    try:
        started = time.monotonic()
        view._refresh_disruption_status()
        assert time.monotonic() - started < 0.5
        assert controller.entered.wait(1.0)

        view._refresh_disruption_status()
        assert controller.status_calls == 1
        assert view._status_poll_in_flight is True

        controller.release.set()
        _pump_until(qapp, lambda: not view._status_poll_in_flight)

        assert controller.worker_thread_id != main_thread_id
        assert controller.disrupted_calls == 1
        assert view._disrupted_devices_snapshot == frozenset(
            {"192.0.2.10"}
        )
        assert view.clumsy_status_label.text().startswith("Engine: ACTIVE")
    finally:
        controller.release.set()


class _ForbiddenDevicePoll:
    def get_disrupted_devices(self):
        raise AssertionError("cached table rendering must not call controller")


def test_clumsy_filter_and_table_render_from_cached_devices(qapp):
    view = _ClumsyHarness(_ForbiddenDevicePoll())
    view.devices = [{
        "ip": "192.0.2.10",
        "mac": "",
        "hostname": "console",
        "vendor": "example",
    }]
    view._disrupted_devices_snapshot = frozenset({"192.0.2.10"})

    view._apply_device_filter()
    view._refresh_device_table_status()

    assert view.device_table.rowCount() == 1
    assert view.device_table.item(0, 5).text().startswith("ACTIVE")


def test_clumsy_status_ignores_stale_generation(qapp):
    view = _ClumsyHarness(None)
    view._status_poll_generation = 2
    view._status_poll_in_flight = True
    view._disrupted_devices_snapshot = frozenset({"192.0.2.1"})

    view._apply_status_snapshot(
        1,
        {"disrupted_devices_count": 1},
        ["192.0.2.99"],
    )

    assert view._status_poll_in_flight is True
    assert view._disrupted_devices_snapshot == frozenset({"192.0.2.1"})


def test_clumsy_shutdown_stops_timers_and_invalidates_worker(qapp):
    view = _ClumsyHarness(None)
    for timer_name in (
        "status_timer",
        "session_timer",
        "stats_refresh_timer",
    ):
        timer = QTimer(view)
        timer.start(1000)
        setattr(view, timer_name, timer)
    view._status_poll_generation = 4
    view._status_poll_in_flight = True

    view.stop_background_refresh()

    assert view._status_poll_generation == 5
    assert view._status_poll_in_flight is False
    assert not view.status_timer.isActive()
    assert not view.session_timer.isActive()
    assert not view.stats_refresh_timer.isActive()


def test_recovery_safe_mode_disables_new_actions_but_keeps_stop(qapp):
    controller = type(
        "_BlockedController",
        (),
        {"network_operations_available": False},
    )()
    view = _ClumsyHarness(controller)
    view.btn_disrupt = QPushButton(view)
    view.btn_sched_once = QPushButton(view)
    view.btn_run_macro = QPushButton(view)
    view.btn_stop = QPushButton(view)
    view.btn_stop_all = QPushButton(view)
    view.sched_status = QLabel(view)

    view._apply_network_availability()

    assert not view.btn_disrupt.isEnabled()
    assert not view.btn_sched_once.isEnabled()
    assert not view.btn_run_macro.isEnabled()
    assert view.btn_stop.isEnabled()
    assert view.btn_stop_all.isEnabled()
    assert "SAFE MODE" in view.sched_status.text()


class _FakeTray:
    def __init__(self) -> None:
        self.tooltip = ""

    def setToolTip(self, value: str) -> None:
        self.tooltip = value


class _FakeAction:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, value: str) -> None:
        self.text = value


class _DashboardHarness(DupeZDashboard):
    def __init__(self, controller) -> None:
        QMainWindow.__init__(self)
        self.controller = controller
        self._dashboard_poll_generation = 0
        self._dashboard_poll_in_flight = False
        self._device_count_snapshot = 0
        self._disrupted_devices_snapshot = frozenset()
        self._dashboard_snapshot_ready.connect(
            self._apply_dashboard_status_snapshot
        )
        self._dashboard_snapshot_failed.connect(
            self._apply_dashboard_status_error
        )
        self.device_status_label = QLabel(self)
        self.disruption_status_label = QLabel(self)
        self.tray_icon = _FakeTray()
        self.tray_action_status = _FakeAction()


class _BlockingDashboardController:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.disrupted_calls = 0
        self.worker_thread_id = None

    @staticmethod
    def get_devices():
        return [object(), object(), object()]

    def get_disrupted_devices(self):
        self.disrupted_calls += 1
        self.worker_thread_id = threading.get_ident()
        self.entered.set()
        self.release.wait(2.0)
        return ["198.51.100.7", "198.51.100.8"]


def test_dashboard_uses_one_nonblocking_snapshot_for_status_and_tray(qapp):
    controller = _BlockingDashboardController()
    dashboard = _DashboardHarness(controller)
    main_thread_id = threading.get_ident()

    try:
        started = time.monotonic()
        dashboard._update_status_bar()
        assert time.monotonic() - started < 0.5
        assert controller.entered.wait(1.0)

        dashboard._update_status_bar()
        assert controller.disrupted_calls == 1
        assert dashboard._dashboard_poll_in_flight is True

        controller.release.set()
        _pump_until(qapp, lambda: not dashboard._dashboard_poll_in_flight)

        assert controller.worker_thread_id != main_thread_id
        assert dashboard.device_status_label.text() == "Devices: 3"
        assert dashboard.disruption_status_label.text() == "Disruptions: 2"
        assert dashboard.tray_action_status.text == "Disruptions: 2"
        assert "2 active disruptions" in dashboard.tray_icon.tooltip
    finally:
        controller.release.set()


def test_dashboard_ignores_stale_generation(qapp):
    dashboard = _DashboardHarness(None)
    dashboard._dashboard_poll_generation = 3
    dashboard._dashboard_poll_in_flight = True
    dashboard._disrupted_devices_snapshot = frozenset({"192.0.2.1"})

    dashboard._apply_dashboard_status_snapshot(2, 99, ["192.0.2.2"])

    assert dashboard._dashboard_poll_in_flight is True
    assert dashboard._device_count_snapshot == 0
    assert dashboard._disrupted_devices_snapshot == frozenset(
        {"192.0.2.1"}
    )


def test_dashboard_surfaces_recovery_safe_mode(qapp):
    class _Blocked:
        @staticmethod
        def get_startup_health():
            return {
                "recovery_blocked": True,
                "message": "firewall cleanup incomplete",
            }

    dashboard = _DashboardHarness(_Blocked())
    dashboard.status_indicator = QLabel(dashboard)

    dashboard._apply_startup_health()

    assert "SAFE MODE" in dashboard.status_indicator.text()
    assert "firewall cleanup incomplete" in dashboard.status_indicator.toolTip()
