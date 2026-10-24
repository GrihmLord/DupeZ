"""Controller settings validation, without hooks, services, or packet I/O."""

from __future__ import annotations

import threading
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.controller import AppController
from app.core.safety_policy import SafetyPolicy
from app.core.state import AppSettings


@pytest.fixture
def controller() -> AppController:
    # Do not run construction/startup: this isolates the settings transaction
    # and proves rejection precedes every service/persistence boundary.
    result = AppController.__new__(AppController)
    result.state = SimpleNamespace(settings=AppSettings(), save_settings=Mock(return_value=True))
    result._safety_policy_injected = False
    result.safety_policy = SafetyPolicy.from_settings(result.state.settings)
    result._lifecycle_lock = threading.Lock()
    result._kill_switch_config_error = None
    result._build_kill_switch_config = Mock(return_value=object())
    result._install_kill_switch = Mock(return_value=(None, False))
    result._restore_kill_switch = Mock()
    result.stop_all_disruptions = Mock(return_value=True)
    return result


@pytest.mark.parametrize(("field", "value"), [
    ("disruption_hotkeys_enabled", "false"),
    ("disruption_hotkeys_enabled", 1),
    ("disruption_start_hotkey_enabled", "true"),
    ("disruption_start_hotkey_enabled", None),
    ("disruption_start_hotkey", "w"),
    ("disruption_start_hotkey", "ctrl+f12"),
    ("disruption_stop_hotkey", "ctrl+shift+d"),
    ("disruption_panic_hotkey", "ctrl+alt+f9"),
    ("disruption_stop_hotkey", "ctrl+f8,ctrl+f9"),
])
def test_invalid_hotkeys_do_not_mutate_persist_or_activate(controller, field, value) -> None:
    original = controller.state.settings
    original_values = asdict(original)
    candidate = AppSettings(kill_switch_process_names=[" C:/Tools/guard.exe "])
    setattr(candidate, field, value)
    supplied = asdict(candidate)
    with pytest.raises(ValueError):
        controller.update_settings(candidate)
    assert controller.state.settings is original
    assert asdict(original) == original_values
    assert asdict(candidate) == supplied
    controller.state.save_settings.assert_not_called()
    controller._build_kill_switch_config.assert_not_called()
    controller._install_kill_switch.assert_not_called()
    controller._restore_kill_switch.assert_not_called()
    controller.stop_all_disruptions.assert_not_called()


def test_valid_hotkeys_are_normalized_before_persisting(controller) -> None:
    saved = []
    controller.state.save_settings.side_effect = lambda: saved.append(controller.state.settings) or True
    candidate = AppSettings(
        disruption_hotkeys_enabled=True,
        disruption_start_hotkey_enabled=False,
        disruption_start_hotkey=" ALT + CTRL + F10 ",
        disruption_stop_hotkey="CTRL + ALT + F11",
        disruption_panic_hotkey="SHIFT + CTRL + X",
    )
    supplied = asdict(candidate)
    controller.update_settings(candidate)
    assert len(saved) == 1
    committed = saved[0]
    assert committed is controller.state.settings
    assert committed is not candidate
    assert committed.disruption_hotkeys_enabled is True
    assert committed.disruption_start_hotkey_enabled is False
    assert committed.disruption_start_hotkey == "ctrl+alt+f10"
    assert committed.disruption_stop_hotkey == "ctrl+alt+f11"
    assert committed.disruption_panic_hotkey == "ctrl+shift+x"
    assert asdict(candidate) == supplied
    controller._build_kill_switch_config.assert_called_once_with(committed)
    controller._install_kill_switch.assert_called_once()
    controller._restore_kill_switch.assert_not_called()
    controller.stop_all_disruptions.assert_not_called()


def test_failed_persistence_restores_original_hotkeys(controller) -> None:
    original = controller.state.settings
    controller.state.save_settings.return_value = False
    with pytest.raises(RuntimeError, match="persistence was not confirmed"):
        controller.update_settings(AppSettings(disruption_start_hotkey="ctrl+alt+f10"))
    assert controller.state.settings is original
    assert original.disruption_start_hotkey == "ctrl+alt+f8"
    controller._restore_kill_switch.assert_called_once_with(None, False)


def test_single_setting_api_uses_the_same_validation(controller) -> None:
    original = controller.state.settings
    with pytest.raises(ValueError):
        controller.update_setting("disruption_start_hotkey", "w")
    assert controller.state.settings is original
    controller.state.save_settings.assert_not_called()
    controller._install_kill_switch.assert_not_called()
    controller.update_setting("disruption_start_hotkey", "ALT + CTRL + F10")
    assert controller.state.settings.disruption_start_hotkey == "ctrl+alt+f10"
    controller.state.save_settings.assert_called_once()
