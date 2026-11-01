"""Untrusted display text must not introduce Qt image/HTML resource loads."""

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QMimeData, Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QApplication, QLabel, QTextEdit

from app.gui.panels.smart_mode_panel import SmartModePanel

ROOT = Path(__file__).resolve().parents[1]
TEXT = '<img src="file:///C:/never-read.svg"> <b>literal</b> & "quotes"'


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _widget_fragment(relative, attribute):
    """Execute the real construction/format statements without packet engines."""
    path = ROOT / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for index, node in enumerate(function.body):
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Attribute) and target.attr == attribute for target in node.targets):
                scope = {"self": SimpleNamespace(), "QLabel": QLabel, "QTextEdit": QTextEdit, "Qt": Qt}
                exec(compile(ast.Module(body=function.body[index:index + 2], type_ignores=[]), str(path), "exec"), scope)
                return getattr(scope["self"], attribute)
    raise AssertionError(attribute)


def _assert_literal_html(rendered):
    requests = []

    class Document(QTextDocument):
        def loadResource(self, kind, name):
            requests.append(name.toString())
            return None

    doc = Document()
    doc.setHtml(rendered)
    doc.adjustSize()
    assert TEXT in doc.toPlainText()
    assert "<img" not in rendered
    assert requests == []


def test_model_result_escapes_all_dynamic_rich_text_fields(qapp):
    harness = SimpleNamespace(smart_llm_input=Mock(), smart_info_label=QLabel(),
                              smart_confidence_bar=Mock(), _view=SimpleNamespace(_apply_recommendation=Mock()))
    SmartModePanel.apply_llm_result(harness, {"name": TEXT, "description": TEXT, "methods": [TEXT], "reasoning": TEXT})
    _assert_literal_html(harness.smart_info_label.text())
    assert harness.smart_info_label.text().count("&lt;img") == 4
    harness.smart_info_label.deleteLater()


def test_profile_and_recommendation_escape_network_strings(qapp):
    harness = SimpleNamespace(btn_smart_profile=Mock(), btn_smart_disrupt=Mock(), smart_info_label=QLabel(),
                              smart_confidence_bar=Mock(), _format_severance_line=lambda profile, rec: "",
                              _view=SimpleNamespace(_apply_recommendation=Mock()))
    profile = SimpleNamespace(avg_rtt_ms=1, jitter_ms=2, packet_loss_pct=3, quality_score=4,
                              connection_type=TEXT, device_type=TEXT, device_hint=TEXT)
    rec = SimpleNamespace(name=TEXT, goal=TEXT, methods=[TEXT], reasoning=[TEXT], confidence=0.5, estimated_effectiveness=20)
    SmartModePanel.update_ui(harness, profile, rec)
    _assert_literal_html(harness.smart_info_label.text())
    assert harness.smart_info_label.text().count("&lt;img") == 7
    harness.smart_info_label.deleteLater()


@pytest.mark.parametrize("relative,attribute", [
    ("app/gui/clumsy_control.py", "sched_status"),
    ("app/gui/clumsy_control.py", "suggest_status"),
    ("app/gui/clumsy_control.py", "outcome_status"),
    ("app/gui/clumsy_control.py", "clumsy_status_label"),
    ("app/gui/panels/lan_cut_panel.py", "a2s_badge"),
])
def test_dynamic_status_labels_remain_plain_text(qapp, relative, attribute):
    widget = _widget_fragment(relative, attribute)
    assert widget.textFormat() == Qt.TextFormat.PlainText
    widget.setText(TEXT)
    assert widget.text() == TEXT
    widget.deleteLater()


@pytest.mark.parametrize("relative,attribute", [
    ("app/gui/dialogs/preset_editor_dialog.py", "params_edit"),
    ("app/gui/settings_dialog.py", "whitelist_edit"),
    ("app/gui/settings_dialog.py", "allowed_target_cidrs_edit"),
    ("app/gui/settings_dialog.py", "kill_switch_process_names_edit"),
])
def test_configuration_paste_uses_plain_mime_text(qapp, relative, attribute):
    widget = _widget_fragment(relative, attribute)
    assert widget.acceptRichText() is False
    mime = QMimeData()
    mime.setHtml(TEXT)
    mime.setText("literal clipboard value")
    widget.insertFromMimeData(mime)
    assert widget.toPlainText() == "literal clipboard value"
    assert "<img" not in widget.toHtml()
    widget.deleteLater()
