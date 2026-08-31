"""Deterministic Qt tests for diagnostics support-bundle actions."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from app.core.diagnostics import CheckResult, CheckStatus
from app.core.support_bundle import SupportBundleResult
from app.gui.diagnostics_dialog import DiagnosticsDialog


class _Clipboard:
    def __init__(self, text: str = "") -> None:
        self.value = text

    def setText(self, value: str) -> None:
        self.value = value

    def text(self) -> str:
        return self.value


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def results() -> list[CheckResult]:
    return [
        CheckResult(
            name="Network",
            status=CheckStatus.WARN,
            message="target 192.168.1.55 uses aa:bb:cc:dd:ee:ff",
            fix_hint="review https://example.test/private?token=value",
        )
    ]


def test_dialog_actions_are_accessible_and_report_is_redacted(
    qapp: QApplication,
    results: list[CheckResult],
) -> None:
    dialog = DiagnosticsDialog(
        results,
        bundle_builder=lambda **_kwargs: {},
        bundle_writer=lambda **_kwargs: SupportBundleResult({}),
        default_save_path="C:/safe/support-bundle.json",
    )
    try:
        report = dialog.report_view.toPlainText()

        assert dialog.report_view.isReadOnly() is True
        assert dialog.report_view.accessibleName() == "Diagnostic check results"
        assert dialog.copy_button.accessibleName() == (
            "Copy redacted support bundle"
        )
        assert dialog.save_button.accessibleName() == (
            "Save redacted support bundle"
        )
        assert "192.168.1.55" not in report
        assert "192.168.1.x" in report
        assert "aa:bb:cc:dd:ee:ff" not in report
        assert "token=value" not in report
    finally:
        dialog.close()


def test_copy_uses_redacted_data_light_bundle_and_reports_success(
    qapp: QApplication,
    results: list[CheckResult],
) -> None:
    clipboard = _Clipboard()
    received = {}

    def build_bundle(**kwargs):
        received.update(kwargs)
        return {
            "schema": "dupez.support_bundle.v1",
            "message": (
                "target 192.168.1.55 aa:bb:cc:dd:ee:ff "
                "https://example.test/private?token=value"
            ),
        }

    dialog = DiagnosticsDialog(
        results,
        bundle_builder=build_bundle,
        clipboard=clipboard,
        default_save_path="C:/safe/support-bundle.json",
    )
    try:
        dialog.copy_button.click()
        qapp.processEvents()
        copied = clipboard.text()

        assert received["include_account_data"] is False
        assert received["include_file_list"] is False
        assert received["diagnostic_results"] == results
        assert json.loads(copied)["schema"] == "dupez.support_bundle.v1"
        assert "192.168.1.55" not in copied
        assert "aa:bb:cc:dd:ee:ff" not in copied
        assert "token=value" not in copied
        assert "Copied" in dialog.action_status.text()
    finally:
        dialog.close()


def test_copy_failure_does_not_replace_clipboard_or_expose_error(
    qapp: QApplication,
    results: list[CheckResult],
) -> None:
    clipboard = _Clipboard("keep me")
    dialog = DiagnosticsDialog(
        results,
        bundle_builder=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError(r"token=private C:\Users\Example\secret")
        ),
        clipboard=clipboard,
        default_save_path="C:/safe/support-bundle.json",
    )
    try:
        assert dialog.copy_support_bundle() is False

        feedback = dialog.action_status.text()
        assert clipboard.text() == "keep me"
        assert "failed" in feedback.lower()
        assert "private" not in feedback
        assert "Example" not in feedback
    finally:
        dialog.close()


def test_save_uses_safe_default_and_verifies_created_file(
    qapp: QApplication,
    results: list[CheckResult],
    tmp_path: Path,
) -> None:
    requested = tmp_path / "saved-support.json"
    default_path = tmp_path / "support-bundle-20260824T123456Z.json"
    received = {}

    def choose_path(_parent, initial: str) -> str:
        received["initial"] = initial
        return str(requested)

    def write_bundle(**kwargs) -> SupportBundleResult:
        received.update(kwargs)
        path = Path(kwargs["output_path"])
        path.write_text("{}", encoding="utf-8")
        return SupportBundleResult(payload={}, path=path)

    dialog = DiagnosticsDialog(
        results,
        bundle_writer=write_bundle,
        save_path_provider=choose_path,
        default_save_path=default_path,
    )
    try:
        assert dialog.save_support_bundle() is True

        assert received["initial"] == str(default_path)
        assert received["output_path"] == str(requested)
        assert received["include_account_data"] is False
        assert received["include_file_list"] is False
        assert received["diagnostic_results"] == results
        assert requested.is_file()
        assert "saved-support.json" in dialog.action_status.text()
        assert str(tmp_path) not in dialog.action_status.text()
    finally:
        dialog.close()


def test_save_cancel_and_failure_feedback_are_honest_and_redacted(
    qapp: QApplication,
    results: list[CheckResult],
    tmp_path: Path,
) -> None:
    writes = []
    canceled = DiagnosticsDialog(
        results,
        bundle_writer=lambda **kwargs: writes.append(kwargs),
        save_path_provider=lambda _parent, _initial: "",
        default_save_path=tmp_path / "default.json",
    )
    try:
        assert canceled.save_support_bundle() is False
        assert writes == []
        assert "canceled" in canceled.action_status.text().lower()
    finally:
        canceled.close()

    failed = DiagnosticsDialog(
        results,
        bundle_writer=lambda **_kwargs: (_ for _ in ()).throw(
            PermissionError(r"C:\Users\Example\token=private")
        ),
        save_path_provider=lambda _parent, _initial: str(tmp_path / "out.json"),
        default_save_path=tmp_path / "default.json",
    )
    try:
        assert failed.save_support_bundle() is False
        feedback = failed.action_status.text()
        assert "failed" in feedback.lower()
        assert "Example" not in feedback
        assert "private" not in feedback
    finally:
        failed.close()


def test_dashboard_opens_the_diagnostics_dialog(monkeypatch) -> None:
    from app.core import diagnostics
    from app.gui import diagnostics_dialog
    from app.gui.dashboard import DupeZDashboard

    expected = [
        CheckResult("Ready", CheckStatus.PASS, "all checks complete")
    ]
    opened = {}

    class _Dialog:
        def __init__(self, received, parent) -> None:
            opened["results"] = received
            opened["parent"] = parent

        def exec(self) -> None:
            opened["executed"] = True

    monkeypatch.setattr(diagnostics, "run_all_checks", lambda: expected)
    monkeypatch.setattr(diagnostics_dialog, "DiagnosticsDialog", _Dialog)
    parent = object()

    DupeZDashboard._show_diagnostics(parent)

    assert opened == {
        "results": expected,
        "parent": parent,
        "executed": True,
    }
