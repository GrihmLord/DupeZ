"""Qt shortcut lifecycle tests with no real keyboard hooks or packet actions."""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication

from app.gui import hotkey
from app.gui.disruption_hotkeys import DisruptionHotkeys


class _Keyboard:
    """Only the registration interface used by the real HotkeyManager."""

    def __init__(self):
        self.entries = {}
        self.added = []
        self.fail_add = set()
        self.fail_remove = set()

    def add_hotkey(self, key, callback, **options):
        if key in self.fail_add:
            raise RuntimeError(f"registration refused: {key}")
        handle = object()
        entry = SimpleNamespace(key=key, callback=callback, options=options)
        self.entries[handle] = entry
        self.added.append(entry)
        return handle

    def remove_hotkey(self, handle):
        if self.entries[handle].key in self.fail_remove:
            raise RuntimeError(f"cleanup refused: {self.entries[handle].key}")
        del self.entries[handle]

    def callback(self, key):
        callbacks = [entry.callback for entry in self.entries.values() if entry.key == key]
        assert len(callbacks) == 1
        return callbacks[0]

    def keys(self):
        return sorted(entry.key for entry in self.entries.values())


def _settings(**changes):
    values = {
        "disruption_hotkeys_enabled": True,
        "disruption_start_hotkey_enabled": False,
        "disruption_start_hotkey": "ctrl+alt+f8",
        "disruption_stop_hotkey": "ctrl+alt+f9",
        "disruption_panic_hotkey": "ctrl+alt+x",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _states(bridge):
    return {item["action"]: item for item in bridge.status()}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def harness(qapp, monkeypatch):
    keyboard = _Keyboard()
    monkeypatch.setattr(hotkey, "keyboard", keyboard)
    monkeypatch.setattr(hotkey, "_KEYBOARD_AVAILABLE", True)
    manager = hotkey.HotkeyManager()
    calls = []
    callbacks = {
        action: lambda action=action: calls.append((action, threading.get_ident()))
        for action in DisruptionHotkeys.ACTIONS
    }
    bridge = DisruptionHotkeys(
        None, manager=manager, callbacks=callbacks, backend_available=True,
    )
    result = SimpleNamespace(
        bridge=bridge, manager=manager, keyboard=keyboard, calls=calls,
    )
    try:
        yield result
    finally:
        keyboard.fail_remove.clear()
        bridge.close()
        manager.stop_all()
        sip.delete(bridge)


@pytest.mark.parametrize("settings", [SimpleNamespace(), _settings(disruption_hotkeys_enabled=False)])
def test_global_shortcuts_require_explicit_opt_in(harness, settings):
    assert harness.bridge.configure(settings)
    assert harness.keyboard.added == []
    assert all(row["state"] == "Disabled" for row in harness.bridge.status())


def test_start_requires_separate_opt_in_and_every_action_uses_key_release(harness):
    assert harness.bridge.configure(_settings())
    assert harness.keyboard.keys() == ["ctrl+alt+f9", "ctrl+alt+x"]
    assert harness.bridge.active_keys("start") == []

    assert harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    assert harness.keyboard.keys() == ["ctrl+alt+f8", "ctrl+alt+f9", "ctrl+alt+x"]
    assert all(
        entry.options == {"suppress": False, "trigger_on_release": True}
        for entry in harness.keyboard.added
    )


def test_backend_unavailable_reports_no_registered_shortcuts(harness):
    harness.bridge._backend_available = False
    assert not harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    assert harness.keyboard.added == []
    assert all(row["state"] == "Unavailable in this session" for row in harness.bridge.status())


@pytest.mark.parametrize("action", DisruptionHotkeys.ACTIONS)
def test_backend_thread_dispatch_is_queued_to_qt_thread(harness, qapp, action):
    assert harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    chord = harness.bridge.active_keys(action)[0]
    worker = threading.Thread(target=harness.keyboard.callback(chord))
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert harness.calls == []

    qapp.processEvents()

    assert harness.calls == [(action, threading.get_ident())]


@pytest.mark.parametrize("transition", ["configure", "close"])
def test_queued_start_from_old_generation_is_discarded(harness, qapp, transition):
    settings = _settings(disruption_start_hotkey_enabled=True)
    assert harness.bridge.configure(settings)
    old_callback = harness.keyboard.callback("ctrl+alt+f8")
    old_callback()
    assert harness.calls == []

    if transition == "configure":
        assert harness.bridge.configure(settings)
    else:
        assert harness.bridge.close()
    qapp.processEvents()
    old_callback()
    qapp.processEvents()
    assert harness.calls == []

    if transition == "configure":
        harness.keyboard.callback("ctrl+alt+f8")()
        qapp.processEvents()
        assert harness.calls == [("start", threading.get_ident())]


@pytest.mark.parametrize("action", DisruptionHotkeys.ACTIONS)
def test_callback_accepted_before_reconfigure_cannot_queue_after_it(harness, qapp, monkeypatch, action):
    settings = _settings(disruption_start_hotkey_enabled=True)
    assert harness.bridge.configure(settings)
    entered = threading.Event()
    release = threading.Event()
    original_queue = harness.bridge._queue

    def delayed_queue(generation, requested_action, start_epoch=None):
        entered.set()
        if release.wait(timeout=2):
            original_queue(generation, requested_action, start_epoch)

    monkeypatch.setattr(harness.bridge, "_queue", delayed_queue)
    chord = harness.bridge.active_keys(action)[0]
    worker = threading.Thread(target=harness.keyboard.callback(chord))
    worker.start()
    try:
        assert entered.wait(timeout=2)
        assert harness.bridge.configure(settings)
    finally:
        release.set()
        worker.join(timeout=2)
    assert not worker.is_alive()

    qapp.processEvents()

    assert harness.calls == []


def test_start_registration_failure_preserves_independent_emergency_actions(harness, qapp):
    harness.keyboard.fail_add.add("ctrl+alt+f8")
    assert not harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    states = _states(harness.bridge)
    assert states["start"]["active"] == []
    assert "registration refused" in states["start"]["error"]
    assert states["panic"]["state"] == "Registered (key release)"
    assert states["stop"]["state"] == "Registered (key release)"

    harness.keyboard.callback("ctrl+alt+x")()
    harness.keyboard.callback("ctrl+alt+f9")()
    qapp.processEvents()
    assert [action for action, _thread in harness.calls] == ["panic", "stop"]


@pytest.mark.parametrize("failed_actions", [("panic",), ("stop",), ("panic", "stop")])
def test_start_cannot_arm_without_both_emergency_hooks(harness, qapp, failed_actions):
    emergency_keys = {"panic": "ctrl+alt+x", "stop": "ctrl+alt+f9"}
    harness.keyboard.fail_add.update(emergency_keys[action] for action in failed_actions)

    assert not harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))

    states = _states(harness.bridge)
    assert states["start"]["active"] == []
    assert "Start requires registered Stop All and Panic Stop hooks" in states["start"]["error"]
    assert "ctrl+alt+f8" not in [entry.key for entry in harness.keyboard.added]
    expected_calls = []
    for action, key in emergency_keys.items():
        if action in failed_actions:
            assert states[action]["active"] == []
            assert "registration refused" in states[action]["error"]
        else:
            assert states[action]["active"] == [key]
            assert states[action]["state"] == "Registered (key release)"
            harness.keyboard.callback(key)()
            expected_calls.append(action)
    qapp.processEvents()
    assert [action for action, _thread in harness.calls] == expected_calls


@pytest.mark.parametrize("action", ["panic", "stop"])
def test_emergency_rebind_failure_reports_retained_previous_chord(harness, qapp, action):
    assert harness.bridge.configure(_settings())
    old_key = harness.bridge.active_keys(action)[0]
    harness.keyboard.fail_add.add("ctrl+alt+f10")
    assert not harness.bridge.configure(_settings(**{
        f"disruption_{action}_hotkey": "ctrl+alt+f10",
    }))
    state = _states(harness.bridge)[action]
    assert state["configured"] == "ctrl+alt+f10"
    assert state["active"] == [old_key]
    assert state["state"] == "Previous chord retained (key release)"
    assert "rebind failed" in state["error"]

    harness.keyboard.callback(old_key)()
    qapp.processEvents()
    assert harness.calls == [(action, threading.get_ident())]


@pytest.mark.parametrize("action", ["panic", "stop"])
def test_retained_working_emergency_chord_satisfies_start_prerequisite(harness, qapp, action):
    assert harness.bridge.configure(_settings())
    retained_key = harness.bridge.active_keys(action)[0]
    harness.keyboard.fail_add.add("ctrl+alt+f10")

    assert not harness.bridge.configure(_settings(
        disruption_start_hotkey_enabled=True,
        **{f"disruption_{action}_hotkey": "ctrl+alt+f10"},
    ))

    states = _states(harness.bridge)
    assert states[action]["state"] == "Previous chord retained (key release)"
    assert states[action]["active"] == [retained_key]
    assert states["start"]["state"] == "Registered (key release)"
    assert states["start"]["active"] == ["ctrl+alt+f8"]
    assert states["start"]["error"] == ""
    harness.keyboard.callback(retained_key)()
    qapp.processEvents()
    # A new Start is usable after the emergency action completes, not queued
    # alongside an emergency action that deliberately cancels pending starts.
    harness.keyboard.callback("ctrl+alt+f8")()
    qapp.processEvents()
    assert [name for name, _thread in harness.calls] == [action, "start"]


@pytest.mark.parametrize("emergency", ["panic", "stop"])
@pytest.mark.parametrize("start_first", [True, False])
def test_emergency_dispatch_cancels_start_queued_in_same_batch(harness, qapp, monkeypatch, emergency, start_first):
    assert harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    # Test dispatch generations independently of the listener's cooldown.
    clock = [100.0]
    monkeypatch.setattr(hotkey, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    start = harness.keyboard.callback("ctrl+alt+f8")
    stop = harness.keyboard.callback(harness.bridge.active_keys(emergency)[0])
    first, second = (start, stop) if start_first else (stop, start)
    first()
    second()

    qapp.processEvents()

    assert [action for action, _thread in harness.calls] == [emergency]
    clock[0] += 1.0
    start()
    qapp.processEvents()
    assert [action for action, _thread in harness.calls] == [emergency, "start"]


def test_local_emergency_action_can_cancel_pending_global_start(harness, qapp):
    assert harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    harness.keyboard.callback("ctrl+alt+f8")()

    harness.bridge.cancel_pending_starts()
    qapp.processEvents()

    assert harness.calls == []


@pytest.mark.parametrize("emergency", ["local", "panic", "stop"])
def test_start_callback_accepted_before_emergency_cannot_queue_after_it(harness, qapp, emergency):
    assert harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    listener = harness.manager.get_listener("disruption_start")
    # HotkeyListener snapshots this callable under its lock before invoking it.
    # Retaining it models an accepted callback paused before entering _queue.
    with listener._lock:
        accepted_callback = listener._callback

    if emergency == "local":
        harness.bridge.cancel_pending_starts()
    else:
        chord = harness.bridge.active_keys(emergency)[0]
        harness.keyboard.callback(chord)()
    qapp.processEvents()
    expected = [] if emergency == "local" else [emergency]
    assert [action for action, _thread in harness.calls] == expected

    accepted_callback()
    qapp.processEvents()
    assert [action for action, _thread in harness.calls] == expected

    # A deliberate new backend event snapshots the replacement callback.
    harness.keyboard.callback("ctrl+alt+f8")()
    qapp.processEvents()
    assert [action for action, _thread in harness.calls] == [*expected, "start"]


def test_chord_still_owned_by_another_action_is_not_registered_twice(harness, qapp):
    assert harness.bridge.configure(_settings())
    old_panic = "ctrl+alt+x"
    old_stop = "ctrl+alt+f9"
    # Panic cannot take Stop's still-owned chord; Stop then fails rebinding,
    # leaving both independent previous bindings armed and correctly reported.
    harness.keyboard.fail_add.add("ctrl+alt+f10")
    assert not harness.bridge.configure(_settings(
        disruption_panic_hotkey=old_stop,
        disruption_stop_hotkey="ctrl+alt+f10",
    ))
    states = _states(harness.bridge)
    assert states["panic"]["active"] == [old_panic]
    assert "still owned by disruption_stop" in states["panic"]["error"]
    assert states["stop"]["active"] == [old_stop]
    assert harness.keyboard.keys() == [old_stop, old_panic]

    harness.keyboard.callback(old_panic)()
    harness.keyboard.callback(old_stop)()
    qapp.processEvents()
    assert [action for action, _thread in harness.calls] == ["panic", "stop"]


def test_unrelated_manager_owner_also_prevents_chord_reuse(harness):
    other = harness.manager.add_listener("unrelated", lambda: None, keys=["ctrl+alt+f10"])
    assert other.start()

    assert not harness.bridge.configure(_settings(disruption_stop_hotkey="ctrl+alt+f10"))

    assert "still owned by unrelated" in _states(harness.bridge)["stop"]["error"]
    assert harness.bridge.active_keys("stop") == []
    assert other.get_active_keys() == ["ctrl+alt+f10"]


def test_shutdown_attempts_all_cleanup_disarms_and_allows_retry(harness, qapp):
    assert harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    stale = harness.keyboard.callback("ctrl+alt+x")
    stale()
    harness.keyboard.fail_remove.add("ctrl+alt+x")

    assert harness.bridge.close() is False
    assert harness.keyboard.keys() == ["ctrl+alt+x"]
    assert all(row["active"] == [] for row in harness.bridge.status())
    assert _states(harness.bridge)["panic"]["state"] == "Disarmed; cleanup pending"
    assert harness.manager.get_listener("disruption_panic") is not None
    assert harness.manager.get_listener("disruption_stop") is None
    assert harness.manager.get_listener("disruption_start") is None
    stale()
    qapp.processEvents()
    assert harness.calls == []

    harness.keyboard.fail_remove.clear()
    assert harness.bridge.close() is True
    assert harness.keyboard.keys() == []
    assert harness.manager.get_all_listeners() == {}
    assert all(row["state"] == "Disabled" for row in harness.bridge.status())
    assert all(row["error"] == "" for row in harness.bridge.status())


def test_invalid_saved_settings_disarm_previously_registered_hooks(harness, qapp):
    assert harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    harness.keyboard.callback("ctrl+alt+f8")()

    assert not harness.bridge.configure(_settings(disruption_start_hotkey="w"))

    assert harness.keyboard.keys() == []
    assert all(row["active"] == [] for row in harness.bridge.status())
    assert all(row["state"] == "Invalid settings; disarmed" for row in harness.bridge.status())
    qapp.processEvents()
    assert harness.calls == []


def test_invalid_settings_preserve_failed_cleanup_status_and_retry_ownership(harness, qapp):
    assert harness.bridge.configure(_settings(disruption_start_hotkey_enabled=True))
    stale = harness.keyboard.callback("ctrl+alt+x")
    harness.keyboard.fail_remove.add("ctrl+alt+x")

    assert not harness.bridge.configure(_settings(disruption_start_hotkey="w"))

    states = _states(harness.bridge)
    assert states["panic"]["state"] == "Invalid settings; disarmed; cleanup pending"
    assert "Start hotkey needs" in states["panic"]["error"]
    assert "cleanup refused: ctrl+alt+x" in states["panic"]["error"]
    assert all(row["configured"] == "" for row in states.values())
    assert all(row["active"] == [] for row in states.values())
    assert states["stop"]["state"] == "Invalid settings; disarmed"
    assert "cleanup refused" not in states["stop"]["error"]
    assert harness.keyboard.keys() == ["ctrl+alt+x"]
    assert harness.manager.get_listener("disruption_panic") is not None
    stale()
    qapp.processEvents()
    assert harness.calls == []

    harness.keyboard.fail_remove.clear()
    assert harness.bridge.close()
    assert harness.keyboard.keys() == []
    assert harness.manager.get_all_listeners() == {}
    assert all(row["state"] == "Disabled" for row in harness.bridge.status())
    assert all(row["error"] == "" for row in harness.bridge.status())
