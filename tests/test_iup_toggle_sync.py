"""Win32 message-contract coverage for IUP toggle synchronization."""

from __future__ import annotations

from app.firewall import clumsy_network_disruptor as legacy
from app.firewall import iup_toggle_sync as sync


class FakeUser32:
    def __init__(self, initial: int = 0):
        self.state = initial
        self.calls = []

    def GetParent(self, hwnd):
        self.calls.append(("GetParent", hwnd))
        return 200

    def GetDlgCtrlID(self, hwnd):
        self.calls.append(("GetDlgCtrlID", hwnd))
        return 77

    def SendMessageW(self, hwnd, message, wparam, lparam):
        self.calls.append(("SendMessageW", hwnd, message, wparam, lparam))
        if hwnd == 100 and message == 0x00F0:
            return self.state
        if hwnd == 100 and message == 0x00F1:
            self.state = int(wparam)
            return 1
        if hwnd == 200 and message == legacy.WM_COMMAND:
            return 1
        return 0


def test_toggle_on_sets_exact_state_then_notifies_real_parent():
    user32 = FakeUser32(initial=0)

    verified, before, actual = sync.set_toggle_state_and_notify(
        100,
        True,
        user32=user32,
    )

    assert verified is True
    assert before == 0
    assert actual == 1
    assert (
        "SendMessageW",
        100,
        0x00F1,
        1,
        0,
    ) in user32.calls
    assert (
        "SendMessageW",
        200,
        legacy.WM_COMMAND,
        77,
        100,
    ) in user32.calls


def test_toggle_off_sets_exact_state_without_bm_click():
    user32 = FakeUser32(initial=1)

    verified, before, actual = sync.set_toggle_state_and_notify(
        100,
        False,
        user32=user32,
    )

    assert verified is True
    assert before == 1
    assert actual == 0
    assert not any(
        call[0] == "SendMessageW" and call[2] == legacy.BM_CLICK
        for call in user32.calls
        if len(call) >= 3
    )


def test_missing_parent_fails_closed():
    user32 = FakeUser32(initial=1)
    user32.GetParent = lambda _hwnd: 0

    verified, before, actual = sync.set_toggle_state_and_notify(
        100,
        False,
        user32=user32,
    )

    assert verified is False
    assert before == 1
    assert actual == 1
