"""Tests for Clumsy diagnostic controls in both architectures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.firewall import clumsy_network_disruptor as legacy
from app.firewall.clumsy_diagnostics import install_clumsy_diagnostic_bridge
from app.firewall_helper.feature_flag import _install_proxy_diagnostic_method


def test_inproc_bridge_delegates_for_non_direct_manager():
    original_show = MagicMock(return_value=True)
    manager = SimpleNamespace(
        show_clumsy_diagnostic_window=original_show,
    )

    install_clumsy_diagnostic_bridge(manager)
    result = manager.hotkey_trigger(
        "show_clumsy_diagnostic_window",
        {"target_ip": "192.168.1.20"},
    )

    assert result is True
    original_show.assert_called_once_with("192.168.1.20")


def test_diagnostic_bridge_rejects_public_target():
    original_show = MagicMock(return_value=True)
    manager = SimpleNamespace(
        show_clumsy_diagnostic_window=original_show,
    )
    install_clumsy_diagnostic_bridge(manager)

    result = manager.hotkey_trigger(
        "show_clumsy_diagnostic_window",
        {"target_ip": "8.8.8.8"},
    )

    assert result is False
    original_show.assert_not_called()


def test_direct_manager_restores_opacity_style_position_and_focus(monkeypatch):
    style = legacy.WS_EX_LAYERED | legacy.WS_EX_TOOLWINDOW | 0x200

    class FakeUser32:
        def __init__(self):
            self.calls = []

        def GetWindowLongW(self, hwnd, index):
            self.calls.append(("get-style", hwnd, index))
            return style

        def SetLayeredWindowAttributes(self, hwnd, key, alpha, flags):
            self.calls.append(("alpha", hwnd, key, alpha, flags))
            return 1

        def SetWindowLongW(self, hwnd, index, value):
            self.calls.append(("set-style", hwnd, index, value))
            return value

        def GetSystemMetrics(self, index):
            return 1920 if index == 0 else 1080

        def GetWindowRect(self, hwnd, rect_pointer):
            rect = rect_pointer._obj
            rect.left = -32000
            rect.top = -32000
            rect.right = -31100
            rect.bottom = -31350
            return 1

        def SetWindowPos(self, hwnd, after, x, y, cx, cy, flags):
            self.calls.append(("position", hwnd, x, y, cx, cy, flags))
            return 1

        def ShowWindow(self, hwnd, command):
            self.calls.append(("show", hwnd, command))
            return 1

        def BringWindowToTop(self, hwnd):
            self.calls.append(("top", hwnd))
            return 1

        def SetForegroundWindow(self, hwnd):
            self.calls.append(("foreground", hwnd))
            return 1

    user32 = FakeUser32()
    monkeypatch.setattr(
        legacy.ctypes,
        "windll",
        SimpleNamespace(user32=user32),
        raising=False,
    )
    engine = SimpleNamespace(_hwnd=77, alive=True)
    manager = SimpleNamespace(
        disrupted_devices={
            "192.168.1.30": {"engine": engine},
        },
    )

    install_clumsy_diagnostic_bridge(manager)
    result = manager.show_clumsy_diagnostic_window("192.168.1.30")

    assert result is True
    assert (
        "alpha",
        77,
        0,
        255,
        legacy.LWA_ALPHA,
    ) in user32.calls
    expected_style = style & ~legacy.WS_EX_LAYERED & ~legacy.WS_EX_TOOLWINDOW
    assert (
        "set-style",
        77,
        legacy.GWL_EXSTYLE,
        expected_style,
    ) in user32.calls
    position = next(call for call in user32.calls if call[0] == "position")
    assert position[2:4] == (510, 215)
    assert ("show", 77, 9) in user32.calls
    assert ("foreground", 77) in user32.calls


def test_bridge_preserves_existing_generic_actions():
    original = MagicMock(return_value=True)
    manager = SimpleNamespace(
        hotkey_trigger=original,
        show_clumsy_diagnostic_window=MagicMock(return_value=False),
    )
    install_clumsy_diagnostic_bridge(manager)

    assert manager.hotkey_trigger("record_marker", {"value": 1}) is True
    original.assert_called_once_with("record_marker", {"value": 1})


def test_split_proxy_maps_show_window_to_authenticated_control_action():
    proxy = SimpleNamespace(hotkey_trigger=MagicMock(return_value=True))

    _install_proxy_diagnostic_method(proxy)
    result = proxy.show_clumsy_diagnostic_window("10.0.0.9")

    assert result is True
    proxy.hotkey_trigger.assert_called_once_with(
        "show_clumsy_diagnostic_window",
        {"target_ip": "10.0.0.9"},
    )


def test_helper_installs_bridge_before_starting_server():
    source = open("dupez_helper.py", encoding="utf-8").read()

    install_index = source.index("install_clumsy_diagnostic_bridge(")
    server_index = source.index("run_helper_server(")
    assert install_index < server_index
