"""Observer delivery must survive Python workers without a Qt event loop."""

from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from app.core import state as state_module
from app.core.state import AppState


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("create_on_worker", [False, True])
def test_worker_notification_arrives_on_qt_thread_after_worker_exits(
    qapp, tmp_path, create_on_worker
):
    states = []
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    received = []
    main_thread = threading.get_ident()

    def observer(event, data):
        received.append((event, data, threading.get_ident()))
        loop.quit()

    def create_state():
        state = AppState(str(tmp_path / "settings.json"))
        state.add_observer(observer)
        states.append(state)

    if not create_on_worker:
        create_state()

    def notify():
        if create_on_worker:
            create_state()
        states[0].notify_observers("ready", 42)

    worker = threading.Thread(target=notify)
    worker.start()
    worker.join(1.0)
    assert not worker.is_alive()
    assert received == []

    timeout.start(1000)
    loop.exec()
    timeout.stop()

    assert received == [("ready", 42, main_thread)]
    state = states[0]
    assert state._observer_dispatcher.thread() == qapp.thread()
    assert state._observer_dispatcher.parent() is qapp


def test_main_thread_observers_are_immediate_reentrant_and_isolated(qapp, tmp_path):
    state = AppState(str(tmp_path / "settings.json"))
    received = []

    def failing_observer(*_args):
        raise ValueError("one observer failed")

    def observer(event, data):
        # Taking the state lock here would deadlock if dispatch held it.
        state.add_observer(lambda *_args: received.append("added later"))
        received.append((event, data))

    state.add_observer(failing_observer)
    state.add_observer(observer)
    state.notify_observers("ready", 42)

    assert received == [("ready", 42)]


def test_headless_worker_observers_are_delivered_directly(tmp_path, monkeypatch):
    monkeypatch.setattr(state_module, "_qt_application", lambda: None)
    state = AppState(str(tmp_path / "settings.json"))
    received = []
    worker_ids = []
    state.add_observer(
        lambda event, data: received.append((event, data, threading.get_ident()))
    )

    def notify():
        worker_ids.append(threading.get_ident())
        state.notify_observers("ready", 42)

    worker = threading.Thread(target=notify)
    worker.start()
    worker.join(1.0)

    assert not worker.is_alive()
    assert received == [("ready", 42, worker_ids[0])]
    assert state._observer_dispatcher is None


def test_deleted_qt_dispatcher_never_calls_gui_observers_from_worker(
    qapp, tmp_path, monkeypatch
):
    state = AppState(str(tmp_path / "settings.json"))
    received = []
    warnings = []
    state.add_observer(lambda *_args: received.append(threading.get_ident()))

    state._observer_dispatcher = state_module._create_observer_dispatcher(qapp)
    sip.delete(state._observer_dispatcher)
    monkeypatch.setattr(state_module, "log_warning", warnings.append)
    worker = threading.Thread(target=lambda: state.notify_observers("ready", 42))
    worker.start()
    worker.join(1.0)

    assert not worker.is_alive()
    assert received == []
    assert len(warnings) == 1
    assert "Qt shutdown" in warnings[0]
