"""Focused settings UI coverage for the automatic kill switch."""

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


def test_automatic_kill_switch_controls_are_accessible_and_round_trip(
    qapp: QApplication,
) -> None:
    settings = AppSettings(
        kill_switch_enabled=True,
        kill_switch_process_watch_enabled=False,
        kill_switch_process_names=["guard.exe", "ac service.exe"],
        kill_switch_risk_threshold=72,
        kill_switch_packet_drop_ceiling=4321,
        kill_switch_packet_sustain_seconds=2.5,
        kill_switch_poll_interval_seconds=0.5,
        kill_switch_cooldown_seconds=45.0,
    )
    dialog = SettingsDialog(settings)
    try:
        values = dialog._read_widgets_to_dict()

        assert dialog.kill_switch_group.accessibleName() == (
            "Automatic Kill Switch settings"
        )
        assert dialog.kill_switch_enabled_checkbox.accessibleName()
        assert dialog.kill_switch_process_names_edit.accessibleDescription()
        assert values["kill_switch_enabled"] is True
        assert values["kill_switch_process_watch_enabled"] is False
        assert values["kill_switch_process_names"] == [
            "guard.exe",
            "ac service.exe",
        ]
        assert values["kill_switch_risk_threshold"] == 72
        assert values["kill_switch_packet_drop_ceiling"] == 4321
        assert values["kill_switch_packet_sustain_seconds"] == 2.5
        assert values["kill_switch_poll_interval_seconds"] == 0.5
        assert values["kill_switch_cooldown_seconds"] == 45.0
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_owns_one_confirmed_settings_transaction(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AppSettings()
    applied = []
    committed = []

    class Controller:
        @staticmethod
        def update_settings(candidate) -> None:
            applied.append(candidate)

    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    dialog = SettingsDialog(settings, controller=Controller())
    try:
        dialog.compact_view_checkbox.setChecked(True)
        dialog.settings_changed.connect(
            lambda values: committed.append(
                (values, list(applied), dialog.get_new_settings())
            )
        )
        dialog.save_settings()

        assert len(applied) == 1
        assert applied[0] is dialog.get_new_settings()
        assert len(committed) == 1
        assert committed[0][0]["compact_view"] is True
        assert committed[0][1] == applied
        assert committed[0][2] is applied[0]
        assert dialog.result() == QDialog.DialogCode.Accepted
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_does_not_accept_when_persistence_transaction_fails(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors = []
    committed = []

    class Controller:
        @staticmethod
        def update_settings(_candidate) -> None:
            raise RuntimeError("settings persistence was not confirmed")

    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *_args: errors.append(True),
    )
    dialog = SettingsDialog(AppSettings(), controller=Controller())
    try:
        original = dialog.get_new_settings()
        dialog.compact_view_checkbox.setChecked(True)
        dialog.settings_changed.connect(committed.append)
        dialog.save_settings()

        assert errors == [True]
        assert committed == []
        assert dialog.get_new_settings() is original
        assert original.compact_view is False
        assert dialog.result() != QDialog.DialogCode.Accepted
    finally:
        dialog.close()
        dialog.deleteLater()
