"""Imported account text must not enter Qt's HTML/image resource parser."""

from __future__ import annotations

import os
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QMimeData, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QTextEdit, QWidget  # noqa: E402

from app.gui import dayz_account_tracker as tracker_module  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tracker(qapp):
    widget = tracker_module.DayZAccountTracker.__new__(tracker_module.DayZAccountTracker)
    QWidget.__init__(widget)
    widget.accounts = []
    widget.current_account = None
    yield widget
    widget.deleteLater()


@pytest.mark.parametrize("text", [
    '<html><body><img src="file:///C:/not-read.svg">literal</body></html>',
    '<p><img src="https://example.invalid/not-fetched.png">notes</p>',
    '<b>Keep these tags literally</b> & <unclosed',
    "plain notes\nsecond line",
])
def test_imported_editor_text_round_trips_without_rich_text_or_resource_loads(
    tracker, monkeypatch, text,
):
    resource_requests = []
    editors = []

    class RecordingEdit(QTextEdit):
        def __init__(self):
            super().__init__()
            editors.append(self)

        def loadResource(self, resource_type, name):
            resource_requests.append((resource_type, name.toString()))
            return None

    monkeypatch.setattr(tracker_module, "QTextEdit", RecordingEdit)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    result = tracker._show_account_dialog({"account": "Fixture", "holding": text, "notes": text})

    assert result is not None
    assert result["holding"] == text
    assert result["notes"] == text
    assert len(editors) == 2
    assert all(not editor.acceptRichText() for editor in editors)
    assert resource_requests == []


def test_paste_uses_plain_mime_text_and_does_not_insert_html_images(tracker, monkeypatch):
    editors = []

    def capture_and_paste(dialog):
        editors.extend(dialog.findChildren(QTextEdit))
        assert len(editors) == 2
        mime = QMimeData()
        mime.setText("visible clipboard text")
        mime.setHtml('<p><img src="file:///C:/not-read.svg">different markup</p>')
        for editor in editors:
            editor.insertFromMimeData(mime)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", capture_and_paste)
    result = tracker._show_account_dialog()

    assert result is not None
    assert result["holding"] == "visible clipboard text"
    assert result["notes"] == "visible clipboard text"
    assert all(not editor.acceptRichText() for editor in editors)


def test_account_status_labels_explicitly_render_plain_text(tracker):
    tracker._setup_account_table = Mock()
    panel = tracker._create_account_panel()
    text = '<img src="file:///C:/not-read.svg">account name'
    for label in (tracker.status_label, tracker.last_modified_label):
        assert label.textFormat() == Qt.TextFormat.PlainText
        label.setText(text)
        assert label.text() == text
    panel.deleteLater()


def test_delete_confirmation_preserves_names_as_plain_text_and_defaults_to_no(
    tracker, monkeypatch,
):
    message = 'Delete account \'<img src="file:///C:/not-read.svg">\'?'
    observed = []

    def inspect_dialog(box):
        observed.append(box.text())
        assert box.textFormat() == Qt.TextFormat.PlainText
        assert box.standardButtons() == (
            tracker_module.QMessageBox.StandardButton.Yes
            | tracker_module.QMessageBox.StandardButton.No
        )
        assert box.defaultButton() == box.button(tracker_module.QMessageBox.StandardButton.No)
        return tracker_module.QMessageBox.StandardButton.No

    monkeypatch.setattr(tracker_module.QMessageBox, "exec", inspect_dialog)
    assert tracker._confirm_account_deletion(message) == tracker_module.QMessageBox.StandardButton.No
    assert observed == [message]


def test_preset_description_widget_never_autodetects_imported_html(qapp):
    # Execute just the real label-construction fragment, without constructing
    # ClumsyControlView's controller, packet engines, or optional panels.
    source = Path(__file__).resolve().parents[1] / "app/gui/clumsy_control.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    build_ui = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_build_ui")
    start = next(index for index, node in enumerate(build_ui.body) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Attribute) and target.attr == "preset_desc" for target in node.targets))
    fragment = ast.Module(body=build_ui.body[start:start + 3], type_ignores=[])
    text = '<img src="file:///C:/not-read.svg">custom description'
    view = SimpleNamespace()
    exec(compile(fragment, str(source), "exec"), {"self": view, "QLabel": QLabel, "Qt": Qt,
         "PRESETS": {"fixture": {"description": text}}, "AUTOMATIC_CONNECTION_TEST": "fixture"})
    assert view.preset_desc.textFormat() == Qt.TextFormat.PlainText
    assert view.preset_desc.text() == text
    view.preset_desc.deleteLater()
