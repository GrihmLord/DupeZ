"""Parent identity checks for the elevated helper."""

import threading

import psutil

import dupez_helper


class _Process:
    def __init__(self, create_time: float) -> None:
        self._create_time = create_time

    def create_time(self) -> float:
        return self._create_time


def test_parent_watcher_rejects_pid_reuse(monkeypatch) -> None:
    event = threading.Event()
    monkeypatch.setattr(psutil, "Process", lambda _pid: _Process(200.0))

    dupez_helper._parent_watcher(
        1234,
        event,
        expected_create_time=100.0,
    )

    assert event.is_set()


def test_parent_watcher_stops_when_parent_unreadable(monkeypatch) -> None:
    event = threading.Event()

    def denied(_pid):
        raise psutil.AccessDenied(pid=1234)

    monkeypatch.setattr(psutil, "Process", denied)
    dupez_helper._parent_watcher(1234, event, expected_create_time=100.0)

    assert event.is_set()
