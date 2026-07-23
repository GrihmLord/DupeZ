"""Coverage for no-flash PID-owned Clumsy window bootstrap."""

from __future__ import annotations

from unittest.mock import MagicMock, call

from app.firewall import clumsy_hidden_window as hidden
from app.firewall import clumsy_network_disruptor as legacy


class FakeUser32:
    def __init__(self, windows):
        self.windows = list(windows)
        self.calls = []
        self.styles = {}

    def IsWindow(self, hwnd):
        return any(int(candidate) == int(hwnd) for candidate, _pid in self.windows)

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

    def GetWindowLongW(self, hwnd, index):
        self.calls.append(("GetWindowLongW", int(hwnd), int(index)))
        return self.styles.get(int(hwnd), 0)

    def SetWindowLongW(self, hwnd, index, value):
        self.calls.append(("SetWindowLongW", int(hwnd), int(index), int(value)))
        self.styles[int(hwnd)] = int(value)
        return int(value)

    def SetLayeredWindowAttributes(self, hwnd, color, alpha, flags):
        self.calls.append(
            (
                "SetLayeredWindowAttributes",
                int(hwnd),
                int(color),
                int(alpha),
                int(flags),
            )
        )
        return True

    def SetWindowPos(self, hwnd, insert_after, x, y, cx, cy, flags):
        self.calls.append(
            (
                "SetWindowPos",
                int(hwnd),
                insert_after,
                int(x),
                int(y),
                int(cx),
                int(cy),
                int(flags),
            )
        )
        return True

    def ShowWindow(self, hwnd, command):
        self.calls.append(("ShowWindow", int(hwnd), int(command)))
        return True


def test_enumerator_returns_only_exact_pid_live_windows():
    user32 = FakeUser32([(10, 111), (20, 222), (21, 222)])

    assert hidden.enumerate_owned_clumsy_windows(
        222,
        user32=user32,
    ) == (20, 21)


def test_pre_show_cloak_applies_policy_before_nonactivating_show():
    user32 = FakeUser32([(20, 222)])

    assert hidden.pre_show_cloak_owned_window(20, user32=user32) is True

    names = [entry[0] for entry in user32.calls]
    assert names == [
        "GetWindowLongW",
        "SetWindowLongW",
        "SetLayeredWindowAttributes",
        "SetWindowPos",
        "ShowWindow",
    ]
    style = user32.styles[20]
    assert style & legacy.WS_EX_TOOLWINDOW
    assert style & legacy.WS_EX_LAYERED
    assert user32.calls[-1] == ("ShowWindow", 20, 4)
    assert not hasattr(user32, "SetForegroundWindow")


def test_finder_prepares_every_exact_pid_candidate_before_returning():
    user32 = FakeUser32([(10, 111), (20, 222), (21, 222)])
    prepare = MagicMock(return_value=True)
    ticks = iter((0.0, 0.0, 0.1))

    hwnd = hidden.find_and_conceal_owned_clumsy_window(
        222,
        timeout=1.0,
        user32=user32,
        prepare_window=prepare,
        clock=lambda: next(ticks),
        sleeper=lambda _seconds: None,
    )

    assert hwnd == 20
    assert prepare.call_args_list == [call(20), call(21)]


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
