"""Regression coverage for deterministic IUP EDIT synchronization."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.firewall import clumsy_network_disruptor as legacy
from app.firewall import iup_edit_sync as sync
from app.firewall.direct_clumsy_manager import ManagedClumsyEngine


def _engine(tmp_path):
    executable = tmp_path / "clumsy.exe"
    executable.write_bytes(b"iup-edit-sync-test")
    return ManagedClumsyEngine(
        str(executable),
        str(tmp_path),
        "true",
        ["lag"],
        {"direction": "both", "lag_delay": 100},
    )


class _FakeUser32:
    def __init__(self):
        self.text = {11: "170"}
        self.notifications = []
        self.GetParent = MagicMock(return_value=22)
        self.GetDlgCtrlID = MagicMock(return_value=7)

    def SendMessageW(self, hwnd, message, wparam, lparam):
        if message == legacy.WM_SETTEXT:
            self.text[hwnd] = lparam.value
            return 1
        if message == legacy.WM_COMMAND:
            self.notifications.append((hwnd, wparam, lparam))
            return 1
        return 0


def test_edit_sync_sets_text_and_emits_en_change(monkeypatch):
    user32 = _FakeUser32()
    monkeypatch.setattr(
        legacy,
        "_get_window_text",
        lambda hwnd: user32.text.get(hwnd, ""),
    )

    verified, actual = sync._set_edit_value_and_notify(
        11,
        "100",
        user32=user32,
    )

    assert verified is True
    assert actual == "100"
    assert user32.notifications == [
        (22, (sync._EN_CHANGE << 16) | 7, 11)
    ]


def test_requested_numeric_control_is_verified(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    monkeypatch.setattr(
        legacy,
        "_get_edit_controls_sorted",
        lambda _hwnd: [10, 11],
    )
    monkeypatch.setattr(
        legacy,
        "_get_window_text",
        lambda hwnd: "170" if hwnd == 11 else "true",
    )
    notify = MagicMock(return_value=(True, "100"))
    monkeypatch.setattr(sync, "_set_edit_value_and_notify", notify)

    assert sync._set_input_values_with_notifications(engine) is True
    notify.assert_called_once_with(11, "100")


def test_numeric_mismatch_surfaces_parameter_and_values(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    monkeypatch.setattr(
        legacy,
        "_get_edit_controls_sorted",
        lambda _hwnd: [10, 11],
    )
    monkeypatch.setattr(legacy, "_get_window_text", lambda _hwnd: "170")
    monkeypatch.setattr(
        sync,
        "_set_edit_value_and_notify",
        lambda _hwnd, _value: (False, "170"),
    )

    assert sync._set_input_values_with_notifications(engine) is False
    assert "lag_delay" in engine._last_error
    assert "'100'" in engine._last_error
    assert "'170'" in engine._last_error


def test_installer_replaces_only_managed_engine_method(monkeypatch):
    original = ManagedClumsyEngine._set_input_values
    monkeypatch.delattr(
        ManagedClumsyEngine,
        "_iup_edit_sync_installed",
        raising=False,
    )

    sync.install_iup_edit_sync()

    assert (
        ManagedClumsyEngine._set_input_values
        is sync._set_input_values_with_notifications
    )
    assert (
        legacy.ClumsyEngine._set_input_values
        is not sync._set_input_values_with_notifications
    )
    ManagedClumsyEngine._set_input_values = original
