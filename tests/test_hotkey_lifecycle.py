"""Lifecycle regressions use a fake backend; no keyboard hooks are installed."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.gui import hotkey


class FakeKeyboard:
    def __init__(self):
        self.active = {}
        self.added = []
        self.removed = []
        self.fail_add = set()
        self.fail_remove = set()
        self.on_add = None

    def add_hotkey(self, key, callback, **options):
        if key in self.fail_add:
            raise ValueError(f"unavailable {key}")
        handle = object()
        entry = SimpleNamespace(key=key, callback=callback, options=options, handle=handle)
        self.added.append(entry)
        self.active[handle] = entry
        if self.on_add is not None:
            self.on_add(entry)
        return handle

    def remove_hotkey(self, handle):
        entry = self.active[handle]
        self.removed.append(entry.key)
        if entry.key in self.fail_remove:
            raise RuntimeError(f"busy {entry.key}")
        del self.active[handle]

    def callback(self, key):
        matches = [entry.callback for entry in self.active.values() if entry.key == key]
        assert len(matches) == 1
        return matches[0]

    def keys(self):
        return sorted(entry.key for entry in self.active.values())


@pytest.fixture
def backend(monkeypatch):
    fake = FakeKeyboard()
    monkeypatch.setattr(hotkey, "keyboard", fake)
    monkeypatch.setattr(hotkey, "_KEYBOARD_AVAILABLE", True)
    monkeypatch.setattr(hotkey, "KEYBOARD_AVAILABLE", True)
    return fake


def test_unspecified_and_empty_keys_never_arm_a_bare_key(backend):
    for keys in (None, []):
        listener = hotkey.HotkeyListener(lambda: None, keys=keys)
        assert listener.start() is False
        assert listener.get_active_keys() == []
        assert listener.get_owned_keys() == []
        assert "No hotkey" in listener.last_error
    assert backend.added == []


def test_start_is_synchronous_truthful_and_idempotent(backend):
    listener = hotkey.HotkeyListener(lambda: None, [" CTRL+F7 ", "ctrl+f7", "ctrl+f8"])
    assert listener.get_active_keys() == []
    assert listener.start() is True
    assert listener.get_active_keys() == ["ctrl+f7", "ctrl+f8"]
    assert len(backend.active) == 2
    assert listener.is_running
    assert listener.last_error == ""
    assert listener.start() is True
    assert len(backend.added) == 2
    assert listener.stop() is True
    assert listener.stop() is True
    assert backend.keys() == []


@pytest.mark.parametrize("release", [True, False])
def test_release_trigger_option_and_non_suppression(backend, release):
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7"], {"trigger_on_release": release})
    assert listener.start()
    assert backend.added[0].options == {"suppress": False, "trigger_on_release": release}


def test_release_triggering_is_the_default(backend):
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7"])
    assert listener.start()
    assert backend.added[0].options["trigger_on_release"] is True


def test_disabled_and_unavailable_backend_cannot_start(backend, monkeypatch):
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7"], {"enabled": False})
    assert not listener.start()
    listener.enable()
    monkeypatch.setattr(hotkey, "_KEYBOARD_AVAILABLE", False)
    assert not listener.start()
    assert "unavailable" in listener.last_error
    assert backend.added == []


def test_registration_failure_rolls_back_all_staged_keys(backend):
    backend.fail_add.add("ctrl+f8")
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7", "ctrl+f8"])
    assert not listener.start()
    assert not listener.is_running
    assert listener.get_active_keys() == []
    assert listener.get_owned_keys() == []
    assert backend.keys() == []
    assert "registration failed" in listener.last_error


def test_failed_start_cleanup_retains_retry_ownership_and_disarms_callback(backend):
    calls = []
    backend.fail_add.add("ctrl+f8")
    backend.fail_remove.add("ctrl+f7")
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7", "ctrl+f8"])
    assert not listener.start()
    stale = backend.callback("ctrl+f7")
    stale()
    assert calls == []
    assert listener.get_owned_keys() == ["ctrl+f7"]
    assert not listener.start()
    assert len(backend.added) == 1
    assert not listener.stop()
    backend.fail_remove.clear()
    assert listener.stop()
    assert listener.get_owned_keys() == []
    assert backend.keys() == []


def test_callbacks_are_not_armed_during_partial_registration(backend):
    calls = []
    backend.on_add = lambda entry: entry.callback()
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7", "ctrl+f8"])
    assert listener.start()
    assert calls == []
    backend.callback("ctrl+f7")()
    assert calls == [True]


def test_failed_stop_disarms_and_keeps_handles_for_retry(backend):
    calls = []
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7", "ctrl+f8"])
    assert listener.start()
    stale = backend.callback("ctrl+f7")
    backend.fail_remove.add("ctrl+f7")
    assert listener.stop() is False
    assert not listener.is_running
    assert listener.get_active_keys() == []
    assert listener.get_owned_keys() == ["ctrl+f7"]
    assert backend.removed == ["ctrl+f7", "ctrl+f8"]
    stale()
    assert calls == []
    backend.fail_remove.clear()
    assert listener.stop() is True
    assert backend.keys() == []


def test_old_registration_cannot_fire_after_stop_and_restart(backend):
    calls = []
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7"])
    assert listener.start()
    stale = backend.callback("ctrl+f7")
    assert listener.stop()
    assert listener.start()
    stale()
    assert calls == []
    backend.callback("ctrl+f7")()
    assert calls == [True]


def test_cooldown_uses_monotonic_time_and_accepts_first_tick_zero(backend, monkeypatch):
    calls = []
    clock = [0.0]
    monkeypatch.setattr(hotkey, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7"])
    assert listener.start()
    callback = backend.callback("ctrl+f7")
    callback()
    clock[0] = 0.49
    callback()
    clock[0] = 0.5
    callback()
    assert calls == [True, True]


@pytest.mark.parametrize("cooldown", [float("nan"), float("inf"), float("-inf"), "invalid"])
def test_cooldown_must_be_finite(backend, cooldown):
    with pytest.raises(ValueError):
        hotkey.HotkeyListener(lambda: None, ["ctrl+f7"], {"cooldown": cooldown})
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7"])
    with pytest.raises(ValueError):
        listener.set_cooldown(cooldown)


def test_cooldown_is_shared_and_synchronized_across_keys(backend, monkeypatch):
    calls = []
    monkeypatch.setattr(hotkey.time, "monotonic", lambda: 10.0)
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7", "ctrl+f8"])
    assert listener.start()
    barrier = threading.Barrier(9)

    def trigger(key):
        barrier.wait(timeout=2)
        backend.callback(key)()

    threads = [threading.Thread(target=trigger, args=(f"ctrl+f{7 + index % 2}",)) for index in range(8)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert calls == [True]


def test_callback_can_stop_its_own_listener(backend):
    results = []
    listener = hotkey.HotkeyListener(lambda: results.append(listener.stop()), ["ctrl+f7"])
    assert listener.start()
    backend.callback("ctrl+f7")()
    assert results == [True]
    assert backend.keys() == []


def test_callback_exception_is_contained(backend):
    def raises():
        raise RuntimeError("synthetic callback failure")

    listener = hotkey.HotkeyListener(raises, ["ctrl+f7"])
    assert listener.start()
    backend.callback("ctrl+f7")()
    assert listener.is_running
    assert listener.stop()


def test_callback_replacement_validates_callable_and_keeps_previous_on_error(backend):
    calls = []
    listener = hotkey.HotkeyListener(lambda: calls.append("old"), ["ctrl+f7"])
    assert listener.start()
    with pytest.raises(TypeError, match="must be callable"):
        listener.set_callback(None)
    backend.callback("ctrl+f7")()
    assert calls == ["old"]
    with pytest.raises(TypeError, match="must be callable"):
        hotkey.HotkeyListener(None, ["ctrl+f8"])


def test_accepted_callback_keeps_snapshot_during_concurrent_replacement(backend, monkeypatch):
    calls = []
    clock = [10.0]
    monkeypatch.setattr(hotkey, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    listener = hotkey.HotkeyListener(lambda: calls.append("old"), ["ctrl+f7"])
    assert listener.start()
    accepted = threading.Event()
    proceed = threading.Event()
    original_lock = listener._lock

    class PauseAfterAcceptance:
        """Stop exactly after ownership checks, before application invocation."""

        pause = True

        def __enter__(self):
            original_lock.acquire()
            return self

        def __exit__(self, *args):
            original_lock.release()
            if self.pause:
                self.pause = False
                accepted.set()
                assert proceed.wait(timeout=3)

    listener._lock = PauseAfterAcceptance()
    worker = threading.Thread(target=backend.callback("ctrl+f7"))
    worker.start()
    assert accepted.wait(timeout=2)
    try:
        listener.set_callback(lambda: calls.append("new"))
    finally:
        proceed.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert calls == ["old"]
    clock[0] += 1.0
    backend.callback("ctrl+f7")()
    assert calls == ["old", "new"]


def test_stop_serializes_with_registration_and_cannot_leak_late_handle(backend):
    entered = threading.Event()
    release = threading.Event()
    stop_entered = threading.Event()
    stop_done = threading.Event()
    results = []

    def block_registration(entry):
        entered.set()
        assert release.wait(timeout=3)

    backend.on_add = block_registration
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7"])

    def stop():
        stop_entered.set()
        results.append(listener.stop())
        stop_done.set()

    starter = threading.Thread(target=lambda: results.append(listener.start()))
    stopper = threading.Thread(target=stop)
    starter.start()
    assert entered.wait(timeout=2)
    stopper.start()
    assert stop_entered.wait(timeout=2)
    assert not stop_done.is_set()
    release.set()
    starter.join(timeout=2)
    stopper.join(timeout=2)
    assert not starter.is_alive() and not stopper.is_alive()
    assert results == [True, True]
    assert backend.keys() == []
    assert not listener.is_running


def test_successful_rebind_reuses_shared_keys_and_rejects_removed_callback(backend):
    calls = []
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7", "ctrl+f8"])
    assert listener.start()
    stale = backend.callback("ctrl+f7")
    retained = backend.callback("ctrl+f8")
    assert listener.set_keys(["ctrl+f8", "ctrl+f9"])
    assert listener.get_active_keys() == ["ctrl+f8", "ctrl+f9"]
    assert backend.callback("ctrl+f8") is retained
    assert [entry.key for entry in backend.added].count("ctrl+f8") == 1
    stale()
    assert calls == []
    retained()
    assert calls == [True]


def test_failed_rebind_addition_preserves_old_working_binding(backend):
    calls = []
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7"])
    assert listener.start()
    backend.fail_add.add("ctrl+f9")
    assert not listener.set_keys(["ctrl+f8", "ctrl+f9"])
    assert listener.is_running
    assert listener.get_active_keys() == ["ctrl+f7"]
    assert backend.keys() == ["ctrl+f7"]
    backend.callback("ctrl+f7")()
    assert calls == [True]


def test_failed_rebind_cleanup_retains_inert_staged_handle_until_stop(backend):
    calls = []
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7"])
    assert listener.start()
    backend.fail_add.add("ctrl+f9")
    backend.fail_remove.add("ctrl+f8")
    assert not listener.set_keys(["ctrl+f8", "ctrl+f9"])
    assert listener.get_active_keys() == ["ctrl+f7"]
    assert sorted(listener.get_owned_keys()) == ["ctrl+f7", "ctrl+f8"]
    backend.callback("ctrl+f8")()
    assert calls == []
    assert not listener.set_keys(["ctrl+f10"])
    backend.fail_remove.clear()
    assert listener.stop()
    assert backend.keys() == []


def test_failed_rebind_removal_restores_previously_removed_old_keys(backend):
    calls = []
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7", "ctrl+f8"])
    assert listener.start()
    old_callback = backend.callback("ctrl+f7")
    backend.fail_remove.add("ctrl+f8")
    assert not listener.set_keys(["ctrl+f9"])
    assert listener.is_running
    assert listener.get_active_keys() == ["ctrl+f7", "ctrl+f8"]
    assert backend.keys() == ["ctrl+f7", "ctrl+f8"]
    old_callback()
    assert calls == []
    backend.callback("ctrl+f7")()
    assert calls == [True]


def test_failed_rebind_rollback_fails_closed_and_keeps_retry_ownership(backend):
    calls = []
    listener = hotkey.HotkeyListener(lambda: calls.append(True), ["ctrl+f7", "ctrl+f8"])
    assert listener.start()
    backend.fail_remove.add("ctrl+f8")
    backend.fail_add.add("ctrl+f7")
    assert not listener.set_keys(["ctrl+f9"])
    assert not listener.is_running
    assert listener.get_active_keys() == []
    assert listener.get_owned_keys() == ["ctrl+f8"]
    assert "restore failed" in listener.last_error
    backend.callback("ctrl+f8")()
    assert calls == []
    backend.fail_remove.clear()
    assert listener.stop()


def test_rebinding_empty_disarms_and_inactive_rebind_waits_for_start(backend):
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7"])
    assert listener.start()
    assert listener.set_keys([])
    assert not listener.is_running
    assert listener.get_active_keys() == []
    assert backend.keys() == []
    assert listener.set_keys(["ctrl+f8"])
    assert backend.keys() == []
    assert listener.start()
    assert listener.get_active_keys() == ["ctrl+f8"]


@pytest.mark.parametrize("invalid", ["ctrl+f7", [""], [None], [" "]])
def test_invalid_rebind_preserves_working_binding(backend, invalid):
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7"])
    assert listener.start()
    assert listener.set_keys(invalid) is False
    assert listener.get_active_keys() == ["ctrl+f7"]
    assert backend.keys() == ["ctrl+f7"]


def test_add_remove_and_disable_preserve_return_contract(backend):
    listener = hotkey.HotkeyListener(lambda: None, ["ctrl+f7"])
    assert listener.start()
    assert listener.add_key("ctrl+f8")
    assert listener.remove_key(" CTRL+F7 ")
    assert listener.get_active_keys() == ["ctrl+f8"]
    assert listener.disable()
    assert not listener.start()
    listener.enable()
    assert listener.start()


def test_manager_replacement_stops_old_owner_and_invalidates_its_callback(backend):
    calls = []
    manager = hotkey.HotkeyManager()
    old = manager.add_listener("action", lambda: calls.append("old"), ["ctrl+f7"])
    assert old.start()
    stale = backend.callback("ctrl+f7")
    new = manager.add_listener("action", lambda: calls.append("new"), ["ctrl+f7"])
    assert not old.is_running
    assert backend.keys() == []
    assert new.start()
    stale()
    assert calls == []
    backend.callback("ctrl+f7")()
    assert calls == ["new"]


def test_manager_failed_replacement_and_removal_retain_original_owner(backend):
    manager = hotkey.HotkeyManager()
    old = manager.add_listener("action", lambda: None, ["ctrl+f7"])
    assert old.start()
    backend.fail_remove.add("ctrl+f7")
    with pytest.raises(RuntimeError, match="previous hotkey cleanup is pending"):
        manager.add_listener("action", lambda: None, ["ctrl+f8"])
    assert manager.get_listener("action") is old
    assert manager.remove_listener("action") is False
    assert manager.get_listener("action") is old
    backend.fail_remove.clear()
    assert manager.remove_listener("action") is True
    assert manager.get_listener("action") is None
    assert manager.remove_listener("action") is True


def test_manager_aggregate_operations_attempt_every_listener(backend):
    manager = hotkey.HotkeyManager()
    first = manager.add_listener("first", lambda: None, ["ctrl+f7"])
    second = manager.add_listener("second", lambda: None, ["ctrl+f8"])
    backend.fail_add.add("ctrl+f7")
    assert manager.start_all() is False
    assert not first.is_running and second.is_running
    backend.fail_add.clear()
    assert manager.start_all() is True
    backend.fail_remove.add("ctrl+f7")
    assert manager.stop_all() is False
    assert backend.keys() == ["ctrl+f7"]
    assert manager.get_listener("first") is first
    backend.fail_remove.clear()
    assert manager.stop_all() is True


def test_listener_registry_copy_cannot_drop_ownership(backend):
    manager = hotkey.HotkeyManager()
    listener = manager.add_listener("action", lambda: None, ["ctrl+f7"])
    snapshot = manager.get_all_listeners()
    snapshot.clear()
    assert manager.get_listener("action") is listener
