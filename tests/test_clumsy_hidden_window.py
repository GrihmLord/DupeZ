"""Coverage for no-flash PID-owned Clumsy window discovery."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.firewall import clumsy_hidden_window as hidden
from app.firewall import clumsy_network_disruptor as legacy


class FakeUser32:
    def __init__(self, windows):
        self.windows = list(windows)

    def EnumWindows(self, callback, _lparam):
        for hwnd, _pid in self.windows:
            if callback(hwnd, 0) is False:
                break
        return True

    def GetWindowThreadProcessId(self, hwnd, pid_pointer):
        for candidate, pid in self.windows:
            if int(candidate) == int(hwnd):
                pid_pointer._obj.value = int(pid)
                return 1
        pid_pointer._obj.value = 0
        return 0


def test_hidden_finder_matches_exact_pid_without_visibility_probe():
    user32 = FakeUser32([(10, 111), (20, 222)])
    conceal = MagicMock(return_value=True)
    ticks = iter((0.0, 0.0, 0.1))

    hwnd = hidden.find_and_conceal_owned_clumsy_window(
        222,
        timeout=1.0,
        user32=user32,
        hide_window=conceal,
        clock=lambda: next(ticks),
        sleeper=lambda _seconds: None,
    )

    assert hwnd == 20
    conceal.assert_called_once_with(20)
    assert not hasattr(user32, "IsWindowVisible")


def test_hidden_finder_rejects_invalid_pid():
    assert hidden.find_and_conceal_owned_clumsy_window(0) is None


def test_installer_replaces_legacy_visible_only_finder(monkeypatch):
    original = legacy._find_window_by_pid
    monkeypatch.delattr(
        legacy,
        "_hidden_owned_window_discovery_installed",
        raising=False,
    )

    hidden.install_hidden_clumsy_window_discovery()

    assert legacy._find_window_by_pid is (
        hidden.find_and_conceal_owned_clumsy_window
    )
    legacy._find_window_by_pid = original
