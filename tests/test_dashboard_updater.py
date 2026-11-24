"""Updater UI regressions use fake checks/downloads and never run installers."""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox

from app.core import updater as updater_module
from app.gui import dashboard as dashboard_module
from app.gui.dashboard import DupeZDashboard


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    previous = application.quitOnLastWindowClosed()
    application.setQuitOnLastWindowClosed(False)
    yield application
    application.setQuitOnLastWindowClosed(previous)


def _pump_until(qapp, predicate):
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def _in_worker(callback):
    failures = []

    def run():
        try:
            callback()
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(1.0)
    assert not worker.is_alive()
    assert failures == []


class _FakeUpdater:
    def __init__(self):
        self.checks = []
        self.downloads = []
        self.browser_opens = 0

    def check_async(self, callback):
        self.checks.append(callback)

    def check_sync(self):
        raise AssertionError("GUI must not use the blocking update check")

    def download_and_install(self, **callbacks):
        self.downloads.append(callbacks)

    def open_download(self):
        self.browser_opens += 1


class _FakePrepared:
    def __init__(self, window):
        self.window = window
        self.launch_calls = 0
        self.cancel_calls = 0

    def launch(self):
        assert self.window.cleanup_calls
        assert self.window._update_cleanup_confirmed
        self.launch_calls += 1
        return True

    def cancel(self):
        self.cancel_calls += 1
        return True


class _DashboardHarness(DupeZDashboard):
    def __init__(self):
        QMainWindow.__init__(self)
        self.widget_threads = []
        self.cleanup_confirmed = True
        self.cleanup_calls = []
        self._minimize_to_tray = True
        self._force_quit = False
        self._dashboard_poll_generation = 0
        self._dashboard_poll_in_flight = False
        self._status_timer = QTimer(self)
        self._stats_timer = QTimer(self)
        self.tray_icon = SimpleNamespace(hide=lambda: None)
        self.controller = SimpleNamespace(shutdown=self._shutdown)
        self._setup_update_flow()

    def _shutdown(self):
        self.cleanup_calls.append(threading.get_ident())
        return self.cleanup_confirmed

    def statusBar(self):  # noqa: N802
        self.widget_threads.append(threading.get_ident())
        return QMainWindow.statusBar(self)


@pytest.fixture
def updater_ui(qapp, monkeypatch):
    fake = _FakeUpdater()
    messages = []
    monkeypatch.setattr(updater_module, "updater", fake)
    monkeypatch.setattr(dashboard_module, "KEYBOARD_AVAILABLE", False)
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(
            QMessageBox, kind,
            lambda _parent, title, message: messages.append(
                (title, message, threading.get_ident())
            ),
        )
    window = _DashboardHarness()
    yield window, fake, messages
    if not sip.isdeleted(window):
        window._stop_update_callbacks()
        sip.delete(window)
    qapp.processEvents()


def test_check_is_nonblocking_single_flight_and_displays_result_on_gui_thread(
    qapp, updater_ui,
):
    window, fake, messages = updater_ui
    main_thread = threading.get_ident()
    window._check_for_updates()
    window._check_for_updates()
    assert len(fake.checks) == 1
    assert window._update_check_in_flight
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    _pump_until(qapp, lambda: heartbeat)

    _in_worker(lambda: fake.checks[0]({
        "update_available": False, "current_version": "5.8.0",
    }))
    assert messages == []
    _pump_until(qapp, lambda: not window._update_check_in_flight)

    assert messages[0][0] == "Up to Date"
    assert messages[0][2] == main_thread
    assert set(window.widget_threads) == {main_thread}
    assert fake.downloads == []


@pytest.mark.parametrize("choice", ["install", "browser", "cancel"])
def test_update_prompt_preserves_explicit_choice(qapp, updater_ui, monkeypatch, choice):
    window, fake, _messages = updater_ui
    chosen = []

    def choose(dialog):
        assert threading.get_ident() == main_thread
        # A nested modal event loop must not permit overlapping checks.
        window._check_for_updates()
        assert len(fake.checks) == 1
        text = {
            "install": "Download && Install",
            "browser": "Open in Browser",
            "cancel": "Cancel",
        }[choice]
        chosen.append(next(button for button in dialog.buttons() if button.text() == text))
        return 0

    main_thread = threading.get_ident()
    monkeypatch.setattr(QMessageBox, "exec", choose)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda _dialog: chosen[0])
    window._check_for_updates()
    _in_worker(lambda: fake.checks[0]({
        "update_available": True,
        "latest_version": "5.9.0",
        "current_version": "5.8.0",
        "release_notes": "Example release notes",
    }))
    _pump_until(qapp, lambda: not window._update_check_in_flight)

    assert len(fake.downloads) == (1 if choice == "install" else 0)
    assert fake.browser_opens == (1 if choice == "browser" else 0)
    assert window._update_download_in_flight is (choice == "install")


@pytest.mark.parametrize("result", [{"error": "offline"}, None])
def test_check_errors_are_reported_and_allow_retry(qapp, updater_ui, result):
    window, fake, messages = updater_ui
    window._check_for_updates()
    _in_worker(lambda: fake.checks[0](result))
    _pump_until(qapp, lambda: not window._update_check_in_flight)

    assert messages[0][0] == "Update Check"
    assert messages[0][2] == threading.get_ident()
    window._check_for_updates()
    assert len(fake.checks) == 2


def test_download_progress_and_failure_touch_widgets_only_on_gui_thread(qapp, updater_ui):
    window, fake, _messages = updater_ui
    window._do_auto_update()
    window._do_auto_update()
    window._check_for_updates()
    assert len(fake.downloads) == 1
    assert fake.checks == []
    callbacks = fake.downloads[0]
    _in_worker(lambda: callbacks["on_progress"](2**32, 2**33))
    _pump_until(qapp, lambda: "50%" in window.statusBar().currentMessage())
    _in_worker(lambda: callbacks["on_done"](False, "signature rejected"))
    _pump_until(qapp, lambda: not window._update_download_in_flight)

    assert "signature rejected" in window.statusBar().currentMessage()
    assert set(window.widget_threads) == {threading.get_ident()}
    assert not window._update_handoff_timer.isActive()
    assert window.cleanup_calls == []


@pytest.mark.parametrize("cleanup_confirmed", [True, False])
def test_install_handoff_uses_confirmed_cleanup_quit(
    qapp, updater_ui, monkeypatch, cleanup_confirmed,
):
    window, fake, messages = updater_ui
    quit_calls = []
    monkeypatch.setattr(QApplication, "quit", lambda *_args: quit_calls.append(True))
    window.cleanup_confirmed = cleanup_confirmed
    window._update_handoff_timer.setInterval(0)
    window._do_auto_update()
    prepared = _FakePrepared(window)
    _in_worker(lambda: fake.downloads[0]["on_prepared"](prepared))
    _pump_until(qapp, lambda: window.cleanup_calls)

    assert window.cleanup_calls == [threading.get_ident()]
    assert quit_calls == []
    assert prepared.launch_calls == (1 if cleanup_confirmed else 0)
    assert prepared.cancel_calls == (0 if cleanup_confirmed else 1)
    if cleanup_confirmed:
        # Neither user Exit nor last-window closure may kill the worker
        # between cleanup approval and its launch result.
        window._force_quit = True
        assert not window.close()
        _in_worker(lambda: fake.downloads[0]["on_done"](True, "mock installer"))
        _pump_until(qapp, lambda: quit_calls)
    assert quit_calls == ([True] if cleanup_confirmed else [])
    assert bool(messages) is (not cleanup_confirmed)
    if not cleanup_confirmed:
        assert messages[0][0] == "Cleanup Not Confirmed"


def test_launch_failure_after_cleanup_reports_restart_and_exits(
    qapp, updater_ui, monkeypatch,
):
    window, fake, messages = updater_ui
    quit_calls = []
    monkeypatch.setattr(QApplication, "quit", lambda *_args: quit_calls.append(True))
    window._do_auto_update()
    prepared = _FakePrepared(window)
    _in_worker(lambda: fake.downloads[0]["on_prepared"](prepared))
    _pump_until(qapp, lambda: prepared.launch_calls == 1)
    assert not window.isEnabled()
    _in_worker(lambda: fake.downloads[0]["on_done"](False, "publisher changed"))
    _pump_until(qapp, lambda: quit_calls)

    assert messages[0][0] == "Update Launch Failed"
    assert "restart" in messages[0][1]
    assert window.cleanup_calls == [threading.get_ident()]


def test_stale_preparation_is_cancelled_without_cleanup_or_launch(qapp, updater_ui):
    window, fake, _messages = updater_ui
    window._do_auto_update()
    old = fake.downloads[0]
    _in_worker(lambda: old["on_done"](False, "first attempt failed"))
    _pump_until(qapp, lambda: not window._update_download_in_flight)
    window._do_auto_update()
    prepared = _FakePrepared(window)
    _in_worker(lambda: old["on_prepared"](prepared))
    _pump_until(qapp, lambda: prepared.cancel_calls == 1)

    assert window._update_download_in_flight
    assert prepared.launch_calls == 0
    assert window.cleanup_calls == []


def test_timer_cleanup_failure_cancels_preparation_and_still_stops_controller(
    qapp, updater_ui,
):
    window, fake, messages = updater_ui

    def fail():
        raise RuntimeError("timer stop failed")

    window._status_timer = SimpleNamespace(stop=fail)
    window._do_auto_update()
    prepared = _FakePrepared(window)
    _in_worker(lambda: fake.downloads[0]["on_prepared"](prepared))
    _pump_until(qapp, lambda: not window._update_download_in_flight)

    assert window.cleanup_calls == [threading.get_ident()]
    assert prepared.cancel_calls == 1
    assert prepared.launch_calls == 0
    assert messages[0][0] == "Cleanup Not Confirmed"


@pytest.mark.parametrize("failed_timer", ["_status_timer", "_stats_timer"])
def test_timer_cleanup_failure_still_stops_other_refreshes(updater_ui, failed_timer):
    window, _fake, messages = updater_ui
    stopped = []

    def stop(name):
        stopped.append(name)
        if name == failed_timer:
            raise RuntimeError("timer has already been deleted")

    for name in ("_status_timer", "_stats_timer"):
        setattr(window, name, SimpleNamespace(stop=lambda name=name: stop(name)))
    window.clumsy_view = SimpleNamespace(
        stop_background_refresh=lambda: stopped.append("clumsy"),
    )

    assert not window._release_owned_resources()
    assert stopped == ["_status_timer", "_stats_timer", "clumsy"]
    assert window.cleanup_calls == [threading.get_ident()]
    assert messages[0][0] == "Cleanup Not Confirmed"


def test_tray_cleanup_failure_still_stops_hotkeys(updater_ui, monkeypatch):
    window, _fake, messages = updater_ui
    stopped = []

    def fail():
        raise RuntimeError("tray icon has already been deleted")

    window.tray_icon = SimpleNamespace(hide=fail)
    monkeypatch.setattr(dashboard_module, "KEYBOARD_AVAILABLE", True)
    monkeypatch.setattr(
        dashboard_module, "hotkey_manager",
        SimpleNamespace(stop_all=lambda: stopped.append("hotkeys")),
    )

    assert not window._release_owned_resources()
    assert stopped == ["hotkeys"]
    assert window.cleanup_calls == [threading.get_ident()]
    assert messages[0][0] == "Cleanup Not Confirmed"


def test_late_check_result_cannot_complete_a_new_check(qapp, updater_ui):
    window, fake, messages = updater_ui
    window._check_for_updates()
    old_callback = fake.checks[0]
    _in_worker(lambda: old_callback({"error": "first check failed"}))
    _pump_until(qapp, lambda: not window._update_check_in_flight)
    window._check_for_updates()
    _in_worker(lambda: old_callback({"error": "late first result"}))
    qapp.processEvents()

    assert window._update_check_in_flight
    assert len(messages) == 1
    _in_worker(lambda: fake.checks[1]({"error": "second result"}))
    _pump_until(qapp, lambda: not window._update_check_in_flight)
    assert "second result" in messages[1][1]


def test_late_download_completion_cannot_finish_a_new_download(qapp, updater_ui):
    window, fake, _messages = updater_ui
    window._do_auto_update()
    old_callbacks = fake.downloads[0]
    _in_worker(lambda: old_callbacks["on_done"](False, "first download failed"))
    _pump_until(qapp, lambda: not window._update_download_in_flight)
    window._do_auto_update()
    _in_worker(lambda: (
        old_callbacks["on_progress"](90, 100),
        old_callbacks["on_done"](True, "late first completion"),
    ))
    qapp.processEvents()

    assert window._update_download_in_flight
    assert window.statusBar().currentMessage() == "Downloading update..."
    assert not window._update_handoff_timer.isActive()
    _in_worker(lambda: fake.downloads[1]["on_done"](False, "second failure"))
    _pump_until(qapp, lambda: not window._update_download_in_flight)
    assert "second failure" in window.statusBar().currentMessage()


@pytest.mark.parametrize("destroy", [False, True])
def test_late_callbacks_after_close_or_deletion_are_ignored(qapp, updater_ui, destroy):
    window, fake, messages = updater_ui
    window._check_for_updates()
    check_callback = fake.checks[0]
    window._do_auto_update()
    download_callbacks = fake.downloads[0]
    prepared = _FakePrepared(window)
    window._force_quit = True
    assert window.close()
    if destroy:
        sip.delete(window)
    previous_widget_calls = list(window.widget_threads)

    _in_worker(lambda: (
        check_callback({"error": "late check"}),
        download_callbacks["on_progress"](50, 100),
        download_callbacks["on_prepared"](prepared),
        download_callbacks["on_done"](True, "late completion"),
    ))
    qapp.processEvents()

    assert window.widget_threads == previous_widget_calls
    assert prepared.cancel_calls == 1
    assert messages == []
