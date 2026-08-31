"""Regression tests for the frameless About dialog controls."""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QDialog, QPushButton, QVBoxLayout

from app.gui.dashboard import DupeZDashboard


def test_about_header_close_button_is_accessible_and_functional() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    layout = QVBoxLayout(dialog)

    DupeZDashboard._about_build_header(layout, dialog)

    close_buttons = [
        button
        for button in dialog.findChildren(QPushButton)
        if button.accessibleName() == "Close About DupeZ"
    ]
    assert len(close_buttons) == 1

    dialog.setResult(QDialog.DialogCode.Accepted)
    close_buttons[0].click()
    app.processEvents()

    assert dialog.result() == QDialog.DialogCode.Rejected
