"""Offscreen settings UI coverage; never installs a global keyboard hook."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from app.core.state import AppSettings
from app.gui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qapp: QApplication):
    widget = SettingsDialog(AppSettings())
    yield widget
    widget.close()
    widget.deleteLater()


def test_hotkey_controls_are_accessible_and_round_trip(dialog) -> None:
    settings = AppSettings(
        disruption_hotkeys_enabled=True,
        disruption_start_hotkey_enabled=True,
        disruption_start_hotkey="ctrl+alt+f10",
        disruption_stop_hotkey="ctrl+alt+f11",
        disruption_panic_hotkey="ctrl+shift+x",
    )
    dialog._apply_settings_to_widgets(settings)
    values = dialog._read_widgets_to_dict()
    assert "Hotkeys" in [dialog.tab_widget.tabText(i) for i in range(dialog.tab_widget.count())]
    assert dialog.hotkeys_group.accessibleName()
    for field in (
        "disruption_hotkeys_enabled", "disruption_start_hotkey_enabled",
        "disruption_start_hotkey", "disruption_stop_hotkey", "disruption_panic_hotkey",
    ):
        assert values[field] == getattr(settings, field)
    for control in (
        dialog.disruption_hotkeys_enabled_checkbox,
        dialog.disruption_start_hotkey_enabled_checkbox,
        dialog.disruption_start_hotkey_edit,
        dialog.disruption_stop_hotkey_edit,
        dialog.disruption_panic_hotkey_edit,
    ):
        assert control.accessibleName()
        assert control.accessibleDescription()
    assert "selected target" in dialog.hotkeys_help_label.text()
    assert "F1" in dialog.hotkeys_help_label.text()


def test_save_normalizes_before_the_controller_transaction(dialog, monkeypatch) -> None:
    applied = []

    class Controller:
        @staticmethod
        def update_settings(settings):
            applied.append(settings)

    dialog.controller = Controller()
    dialog.disruption_hotkeys_enabled_checkbox.setChecked(True)
    dialog.disruption_start_hotkey_edit.setText(" ALT + CTRL + F10 ")
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    dialog.save_settings()
    assert len(applied) == 1
    assert applied[0] is dialog.get_new_settings()
    assert applied[0].disruption_start_hotkey == "ctrl+alt+f10"
    assert applied[0].disruption_hotkeys_enabled is True
    assert applied[0].disruption_start_hotkey_enabled is False
    assert dialog.result() == QDialog.DialogCode.Accepted


@pytest.mark.parametrize("bad_chord", ["w", "ctrl+shift+d", "ctrl+alt+f9", "ctrl+f12"])
def test_invalid_disabled_definition_never_reaches_persistence(dialog, monkeypatch, bad_chord) -> None:
    calls = []
    errors = []

    class Controller:
        @staticmethod
        def update_settings(_settings):
            calls.append(True)

    dialog.controller = Controller()
    original = dialog.get_new_settings()
    dialog.disruption_start_hotkey_edit.setText(bad_chord)
    assert not dialog.disruption_hotkeys_enabled_checkbox.isChecked()
    assert dialog.disruption_start_hotkey_edit.isEnabled()
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: errors.append(True))
    dialog.save_settings()
    assert errors == [True]
    assert not calls
    assert dialog.get_new_settings() is original
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_malformed_loaded_definition_remains_visible_and_correctable(dialog, monkeypatch) -> None:
    dialog._apply_settings_to_widgets(AppSettings(disruption_start_hotkey="w"))
    assert dialog.disruption_start_hotkey_edit.text() == "w"
    assert dialog.disruption_start_hotkey_edit.isEnabled()
    dialog.disruption_start_hotkey_edit.setText("ctrl+alt+f10")
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    dialog.save_settings()
    assert dialog.get_new_settings().disruption_start_hotkey == "ctrl+alt+f10"
    assert dialog.get_new_settings().disruption_hotkeys_enabled is False


def test_reset_restores_disabled_defaults_without_registering(dialog, monkeypatch) -> None:
    dialog._apply_settings_to_widgets(AppSettings(
        disruption_hotkeys_enabled=True,
        disruption_start_hotkey_enabled=True,
        disruption_start_hotkey="ctrl+alt+f10",
    ))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog.reset_to_defaults()
    values = dialog._read_widgets_to_dict()
    for key in (
        "disruption_hotkeys_enabled", "disruption_start_hotkey_enabled",
        "disruption_start_hotkey", "disruption_stop_hotkey", "disruption_panic_hotkey",
    ):
        assert values[key] == getattr(AppSettings(), key)
