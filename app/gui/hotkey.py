"""Owned global hotkeys with truthful registration and retryable cleanup.

The optional ``keyboard`` backend already owns its event thread. Registrations
are synchronous; callbacks run on the backend's thread, so GUI callers must
queue their work to Qt. No binding is armed unless keys are explicitly supplied.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, List, Optional

from app.logs.logger import log_error, log_info

try:
    import keyboard
    _KEYBOARD_AVAILABLE = True
except ImportError:
    keyboard = None
    _KEYBOARD_AVAILABLE = False
    log_error("keyboard module not available — hotkeys disabled")

__all__ = ["HotkeyListener", "HotkeyManager", "KEYBOARD_AVAILABLE"]
KEYBOARD_AVAILABLE = _KEYBOARD_AVAILABLE


def _normalise_keys(keys: Optional[List[str]]) -> List[str]:
    if keys is None:
        return []
    if isinstance(keys, (str, bytes)):
        raise ValueError("Hotkeys must be supplied as a list of key combinations")
    result = []
    for key in keys:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Hotkey combinations must be non-empty strings")
        key = key.strip().lower()
        if key not in result:
            result.append(key)
    return result


def _validated_cooldown(value: object) -> float:
    cooldown = float(value)
    if not math.isfinite(cooldown):
        raise ValueError("Hotkey cooldown must be finite")
    return max(0.1, cooldown)


class HotkeyListener:
    """Own explicit global bindings for one callback.

    ``start`` succeeds only after every requested key is registered. A failed
    removal is kept for a later ``stop`` attempt, but its callback is disabled.
    Release-triggering defaults on to avoid held-key repeat. Callbacks accepted
    before ``stop`` may finish; callbacks arriving after invalidation cannot
    begin another invocation. Callers queuing work must also guard their queue.
    """

    def __init__(
        self,
        callback: Callable[[], None],
        keys: Optional[List[str]] = None,
        config: Optional[Dict] = None,
    ) -> None:
        if not callable(callback):
            raise TypeError("Hotkey callback must be callable")
        self._callback = callback
        self._keys = _normalise_keys(keys)
        self._config = dict(config or {})
        self._lock = threading.RLock()
        self._running = False
        self._hotkey_handles: Dict[str, object] = {}
        self._registration_tokens: Dict[str, object] = {}
        self._active_tokens: Dict[str, object] = {}
        self._generation = 0
        self._cooldown = _validated_cooldown(self._config.get("cooldown", 0.5))
        self._last_trigger: Optional[float] = None
        self._enabled = bool(self._config.get("enabled", True))
        self._trigger_on_release = bool(self._config.get("trigger_on_release", True))
        self._last_error = ""

    def _fail(self, message: str) -> bool:
        self._last_error = message
        log_error(message)
        return False

    def _register(self, key: str) -> None:
        """Register under the ownership lock; publication arms it separately."""
        token = object()
        generation = self._generation
        handle = keyboard.add_hotkey(
            key,
            lambda: self._on_trigger(key, generation, token),
            suppress=False,
            trigger_on_release=self._trigger_on_release,
        )
        self._hotkey_handles[key] = handle
        self._registration_tokens[key] = token

    def _remove(self, keys: List[str]) -> List[str]:
        """Remove all requested registrations, retaining failures for retry."""
        failures = []
        for key in keys:
            if key not in self._hotkey_handles:
                continue
            try:
                keyboard.remove_hotkey(self._hotkey_handles[key])
            except Exception as exc:
                failures.append(f"{key}: {exc}")
            else:
                self._hotkey_handles.pop(key)
                self._registration_tokens.pop(key, None)
        return failures

    def start(self) -> bool:
        """Synchronously register every configured key, or roll back."""
        with self._lock:
            if not self._enabled:
                return self._fail("Hotkeys are disabled")
            if not _KEYBOARD_AVAILABLE or keyboard is None:
                return self._fail("Keyboard backend is unavailable")
            if self._running:
                return True
            if self._hotkey_handles:
                return self._fail("Previous hotkey cleanup is pending; retry stop first")
            if not self._keys:
                return self._fail("No hotkey combinations are configured")
            self._generation += 1
            self._last_trigger = None
            try:
                for key in self._keys:
                    self._register(key)
            except Exception as exc:
                self._generation += 1
                failures = self._remove(list(self._hotkey_handles))
                suffix = f"; cleanup pending: {'; '.join(failures)}" if failures else ""
                return self._fail(f"Hotkey registration failed: {exc}{suffix}")
            self._active_tokens = dict(self._registration_tokens)
            self._running = True
            self._last_error = ""
            log_info(f"Hotkey listener started: {', '.join(self._keys)}")
            return True

    def stop(self) -> bool:
        """Disarm callbacks and unregister every owned handle; retry on False."""
        with self._lock:
            self._running = False
            self._generation += 1
            self._active_tokens.clear()
            failures = self._remove(list(self._hotkey_handles))
            if failures:
                return self._fail(f"Hotkey cleanup pending: {'; '.join(failures)}")
            self._last_error = ""
            return True

    def _on_trigger(
        self, key: str, generation: Optional[int] = None, token: object = None,
    ) -> None:
        with self._lock:
            if not self._running or not self._enabled:
                return
            if generation != self._generation or self._active_tokens.get(key) is not token:
                return
            now = time.monotonic()
            if self._last_trigger is not None and now - self._last_trigger < self._cooldown:
                return
            self._last_trigger = now
            callback = self._callback
        # Never hold the ownership lock across application work. The callback
        # may queue GUI work, stop itself, or acquire another owner's lock.
        try:
            callback()
        except Exception as exc:
            log_error(f"Hotkey callback error: {exc}")

    def set_callback(self, callback: Callable[[], None]) -> None:
        """Replace future callbacks without relabeling an accepted invocation."""
        with self._lock:
            if not callable(callback):
                raise TypeError("Hotkey callback must be callable")
            self._callback = callback

    def set_keys(self, keys: List[str]) -> bool:
        """Rebind transactionally; retain the old binding on ordinary failure.

        New chords are staged without arming them. Shared chords are not
        registered twice (the keyboard backend cannot safely remove duplicate
        registrations). If restoring the previous bindings fails, disarm the
        whole listener and retain any cleanup ownership for ``stop`` retry.
        """
        with self._lock:
            try:
                requested = _normalise_keys(keys)
            except (TypeError, ValueError) as exc:
                return self._fail(f"Invalid hotkey configuration: {exc}")
            if not self._running:
                if self._hotkey_handles:
                    return self._fail("Previous hotkey cleanup is pending; retry stop first")
                self._keys = requested
                self._last_error = ""
                return True
            if set(self._hotkey_handles) != set(self._active_tokens):
                return self._fail("Previous hotkey cleanup is pending; retry stop before rebinding")
            previous = list(self._keys)
            added = [key for key in requested if key not in self._hotkey_handles]
            removed = [key for key in previous if key not in requested]
            try:
                for key in added:
                    self._register(key)
            except Exception as exc:
                failures = self._remove(added)
                suffix = f"; cleanup pending: {'; '.join(failures)}" if failures else ""
                return self._fail(f"Hotkey rebind failed: {exc}{suffix}")

            failures = self._remove(removed)
            if failures:
                restore_errors = []
                for key in removed:
                    if key in self._hotkey_handles:
                        continue
                    try:
                        self._register(key)
                        self._active_tokens[key] = self._registration_tokens[key]
                    except Exception as exc:
                        restore_errors.append(f"{key}: {exc}")
                failures.extend(self._remove(added))
                if restore_errors:
                    self._running = False
                    self._generation += 1
                    self._active_tokens.clear()
                    failures.extend(self._remove(list(self._hotkey_handles)))
                    failures.extend(f"restore failed: {error}" for error in restore_errors)
                return self._fail(f"Hotkey rebind rolled back: {'; '.join(failures)}")

            self._keys = requested
            self._active_tokens = {
                key: self._registration_tokens[key] for key in requested
            }
            self._running = bool(requested)
            self._last_error = ""
            return True

    def add_key(self, key: str) -> bool:
        with self._lock:
            return self.set_keys([*self._keys, key])

    def remove_key(self, key: str) -> bool:
        with self._lock:
            return self.set_keys([item for item in self._keys if item != key.strip().lower()])

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def get_active_keys(self) -> List[str]:
        """Return actual armed bindings, not failed/configured-only keys."""
        with self._lock:
            return [key for key in self._keys if key in self._active_tokens] if self._running else []

    def get_owned_keys(self) -> List[str]:
        """Include inert handles whose backend cleanup still needs retrying."""
        with self._lock:
            return list(self._hotkey_handles)

    def set_cooldown(self, cooldown: float) -> None:
        value = _validated_cooldown(cooldown)
        with self._lock:
            self._cooldown = value

    def enable(self) -> None:
        """Enable future starts; a missing backend still cannot be started."""
        with self._lock:
            self._enabled = True

    def disable(self) -> bool:
        with self._lock:
            self._enabled = False
            return self.stop()


class HotkeyManager:
    """Named owners; failed cleanup retains ownership for another attempt."""

    def __init__(self) -> None:
        self._listeners: Dict[str, HotkeyListener] = {}
        self._lock = threading.RLock()

    def add_listener(
        self,
        name: str,
        callback: Callable[[], None],
        keys: Optional[List[str]] = None,
        config: Optional[Dict] = None,
    ) -> HotkeyListener:
        listener = HotkeyListener(callback, keys, config)
        with self._lock:
            previous = self._listeners.get(name)
            if previous is not None and not previous.stop():
                raise RuntimeError(f"Cannot replace '{name}': previous hotkey cleanup is pending")
            self._listeners[name] = listener
        return listener

    def remove_listener(self, name: str) -> bool:
        with self._lock:
            listener = self._listeners.get(name)
            if listener is None:
                return True
            if not listener.stop():
                return False
            del self._listeners[name]
            return True

    def start_all(self) -> bool:
        with self._lock:
            results = [listener.start() for listener in self._listeners.values()]
            return all(results)

    def stop_all(self) -> bool:
        with self._lock:
            results = [listener.stop() for listener in self._listeners.values()]
            return all(results)

    def get_listener(self, name: str) -> Optional[HotkeyListener]:
        with self._lock:
            return self._listeners.get(name)

    def get_all_listeners(self) -> Dict[str, HotkeyListener]:
        with self._lock:
            return dict(self._listeners)


hotkey_manager = HotkeyManager()


def create_hotkey_listener(
    callback: Callable[[], None],
    keys: Optional[List[str]] = None,
    config: Optional[Dict] = None,
) -> HotkeyListener:
    return HotkeyListener(callback, keys, config)


def get_hotkey_manager() -> HotkeyManager:
    return hotkey_manager
