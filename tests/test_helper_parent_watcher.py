"""Parent identity checks for the elevated helper."""

import threading
from pathlib import Path

import psutil

import dupez_helper
from app.firewall_helper import feature_flag


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


def test_helper_forces_inproc_when_frozen_default_is_split(monkeypatch) -> None:
    """The elevated helper must never proxy privileged calls to itself."""
    monkeypatch.setenv("DUPEZ_ARCH", "split")
    monkeypatch.setattr(feature_flag, "_COMPILED_DEFAULT", "split")
    monkeypatch.setattr(feature_flag, "_DEFAULT_ARCH", "split")

    dupez_helper._force_helper_inproc_arch()

    assert feature_flag.get_arch() == "inproc"
    assert feature_flag.is_split_mode() is False


def test_frozen_gpu_arch_cannot_be_downgraded_by_environment(monkeypatch) -> None:
    monkeypatch.setattr(feature_flag.sys, "frozen", True, raising=False)
    monkeypatch.setattr(feature_flag.sys, "argv", ["DupeZ-GPU.exe"])
    monkeypatch.setattr(feature_flag, "_DEFAULT_ARCH", "split")
    monkeypatch.setenv("DUPEZ_ARCH", "inproc")

    assert feature_flag.get_arch() == "split"


def test_frozen_helper_role_uses_inproc_without_environment_trust(
    monkeypatch,
) -> None:
    monkeypatch.setattr(feature_flag.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        feature_flag.sys,
        "argv",
        ["DupeZ-GPU.exe", "--role", "helper"],
    )
    monkeypatch.setattr(feature_flag, "_DEFAULT_ARCH", "split")
    monkeypatch.delenv("DUPEZ_ARCH", raising=False)

    assert feature_flag.get_arch() == "inproc"


def test_helper_log_path_ignores_inherited_temp_directory(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    path = Path(dupez_helper._helper_log_path())
    trusted_root = Path(dupez_helper._windows_local_appdata())

    assert path == trusted_root / "DupeZ" / "logs" / "firewall_helper.log"
    assert tmp_path not in path.parents
    assert "_MEI" not in str(path)
