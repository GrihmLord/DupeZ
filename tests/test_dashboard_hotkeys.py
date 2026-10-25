"""Dashboard hotkeys use mocked actions/hooks, never live packet operations."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import sip
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QMenu, QMenuBar, QMessageBox, QPushButton

from app.gui import dashboard as module
from app.gui.dashboard import DupeZDashboard


@pytest.fixture
def window():
    application = QApplication.instance() or QApplication([])
    dashboard = DupeZDashboard.__new__(DupeZDashboard)
    QMainWindow.__init__(dashboard)
    dashboard._hotkeys_closing = False
    dashboard.clumsy_view = SimpleNamespace(_on_disrupt=Mock())
    dashboard._panic_stop_action = QAction("Panic Stop", dashboard)
    yield dashboard
    sip.delete(dashboard)
    application.processEvents()


@pytest.mark.parametrize("guard", ["_hotkeys_closing", "_update_launch_in_flight", "_update_cleanup_confirmed"])
def test_start_rejects_shutdown_and_update_handoff(window, guard):
    setattr(window, guard, True)
    window._start_disruption_hotkey()
    window.clumsy_view._on_disrupt.assert_not_called()


def test_start_uses_existing_action_without_altering_targets(window, monkeypatch):
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: None)
    window._start_disruption_hotkey()
    window.clumsy_view._on_disrupt.assert_called_once_with()


def test_start_rejects_modal_and_disabled_window(window, monkeypatch):
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: object())
    window._start_disruption_hotkey()
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: None)
    window.setEnabled(False)
    window._start_disruption_hotkey()
    window.clumsy_view._on_disrupt.assert_not_called()


@pytest.mark.parametrize("active", [[], ["ctrl+alt+x"], ["ctrl+alt+f10"]])
def test_local_panic_only_suspended_for_matching_registered_global(window, active):
    window._disruption_hotkeys = SimpleNamespace(active_keys=lambda _action: active)
    window._sync_panic_shortcut()
    assert window._panic_stop_action.shortcut().toString() == (
        "" if "ctrl+alt+x" in active else "Ctrl+Alt+X"
    )
    assert window._panic_stop_action.isEnabled()


def test_menu_shortcuts_do_not_repeat(window):
    menu = QMenu(window)
    action = window._add_action(menu, "Stop", "Ctrl+D", Mock())
    assert not action.autoRepeat()


@pytest.mark.parametrize("failure", [False, True, "raises"])
def test_hook_cleanup_is_independent_and_restores_local_panic(window, monkeypatch, failure):
    events = []

    def close_owner():
        assert window._hotkeys_closing
        events.append("owner")
        if failure == "raises":
            raise RuntimeError("fixture")
        return not failure

    window._disruption_hotkeys = SimpleNamespace(close=close_owner, active_keys=lambda _a: [])
    monkeypatch.setattr(module, "hotkey_manager", SimpleNamespace(
        stop_all=lambda: events.append("manager") or True,
    ))
    assert window._stop_global_hotkeys() is (failure is False)
    assert events == ["owner", "manager"]
    assert window._panic_stop_action.shortcut().toString() == "Ctrl+Alt+X"


def test_tray_registration_starts_only_its_owner_and_reports_failure(monkeypatch):
    listener = SimpleNamespace(start=Mock(return_value=False), last_error="refused")
    manager = SimpleNamespace(add_listener=Mock(return_value=listener), start_all=Mock())
    monkeypatch.setattr(module, "hotkey_manager", manager)
    monkeypatch.setattr(module, "KEYBOARD_AVAILABLE", True)
    monkeypatch.setenv("QT_QPA_PLATFORM", "fixture")
    warning = Mock()
    monkeypatch.setattr(module, "log_warning", warning)
    dashboard = SimpleNamespace(_minimize_to_tray=True, _hotkey_toggle_visibility=Mock())
    DupeZDashboard._setup_tray_hotkey(dashboard)
    listener.start.assert_called_once_with()
    manager.start_all.assert_not_called()
    assert "refused" in warning.call_args.args[0]


@pytest.mark.parametrize("accepted", [False, True])
def test_settings_rebind_only_after_successful_save(window, monkeypatch, accepted):
    window.controller = SimpleNamespace(state=SimpleNamespace(load_settings=Mock(), settings=object()))
    dialog = SimpleNamespace(exec=lambda: QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected)
    monkeypatch.setattr(module, "SettingsDialog", lambda *_args, **_kwargs: dialog)
    apply = Mock()
    window._apply_disruption_hotkeys = apply
    window._open_settings()
    assert apply.call_count == int(accepted)


def test_f1_separates_scope_and_escapes_registration_errors(window, monkeypatch):
    window._custom_menubar = QMenuBar(window)
    menu = window._custom_menubar.addMenu("Tools")
    window._add_action(menu, "Window Stop", "Ctrl+D", Mock())
    window._disruption_hotkeys = SimpleNamespace(status=lambda: [{
        "action": "panic", "configured": "ctrl+alt+f10", "active": ["ctrl+alt+x"],
        "state": "Previous chord retained", "error": "<refused>&fixture",
    }])
    monkeypatch.setattr(module, "hotkey_manager", SimpleNamespace(get_listener=lambda _name: None))
    info = Mock()
    monkeypatch.setattr(QMessageBox, "information", info)
    window._show_hotkeys()
    body = info.call_args.args[2]
    assert "DupeZ window shortcuts" in body and "Global hooks" in body
    assert "Disabled / unavailable" in body and "Previous chord retained" in body
    assert "&lt;refused&gt;&amp;fixture" in body
    assert "<refused>" not in body


def test_shutdown_blocks_settings_rearming(window):
    window._hotkeys_closing = True
    window._disruption_hotkeys = SimpleNamespace(configure=Mock())
    window._apply_disruption_hotkeys()
    window._disruption_hotkeys.configure.assert_not_called()


@pytest.mark.parametrize("name", ["btn_stop", "btn_stop_all"])
def test_panel_stop_press_cancels_pending_starts_before_existing_cleanup(window, monkeypatch, name):
    events = []
    owner = SimpleNamespace(cancel_pending_starts=lambda: events.append("cancel"))
    monkeypatch.setattr(module, "DisruptionHotkeys", lambda *_args, **_kwargs: owner)
    window._apply_disruption_hotkeys = Mock()
    button = QPushButton(window)
    setattr(window.clumsy_view, name, button)
    button.clicked.connect(lambda: events.append("cleanup"))

    window._setup_disruption_hotkeys()
    button.click()

    assert events == ["cancel", "cleanup"]
