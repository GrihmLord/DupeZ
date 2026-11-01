"""Secret-handling and accessibility tests for the audit-webhook UI."""

from __future__ import annotations

import json
import os
from dataclasses import asdict

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit

from app.core.state import AppSettings
from app.gui.audit_webhook_dialog import AuditWebhookDialog


def _secret_url() -> str:
    return "https://discord.com/api/" + "webhooks/123/gui-secret-value"


def _status(*, configured=False, enabled=False, accessible=True):
    return {
        "configured": configured,
        "enabled": enabled,
        "kind": "discord" if configured else None,
        "rate_limit_per_min": 30 if configured else None,
        "secret_store_accessible": accessible,
    }


class _Backend:
    def __init__(self, *, configured=False, enabled=False) -> None:
        self.state = _status(configured=configured, enabled=enabled)
        self.provision_calls = []
        self.enabled_calls = []
        self.clear_calls = 0

    def status(self):
        return dict(self.state)

    def provision(self, url, **kwargs) -> None:
        self.provision_calls.append((url, kwargs))
        self.state = _status(configured=True, enabled=kwargs["enabled"])
        self.state["kind"] = kwargs["kind"]
        self.state["rate_limit_per_min"] = kwargs["rate_limit_per_min"]

    def configure(self, enabled: bool) -> None:
        self.enabled_calls.append(enabled)
        self.state["enabled"] = enabled

    def clear(self) -> None:
        self.clear_calls += 1
        self.state = _status()


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dialog(backend: _Backend, **kwargs) -> AuditWebhookDialog:
    return AuditWebhookDialog(
        status_reader=backend.status,
        provisioner=backend.provision,
        enabled_configurer=backend.configure,
        clearer=backend.clear,
        **kwargs,
    )


def test_secret_entry_and_actions_are_accessible_and_copy_protected(
    qapp: QApplication,
) -> None:
    backend = _Backend()
    dialog = _dialog(backend)
    clipboard = qapp.clipboard()
    clipboard.setText("clipboard sentinel")
    try:
        assert dialog.accessibleName() == "Audit webhook configuration"
        assert dialog.url_input.accessibleName() == "Audit webhook secret URL"
        assert dialog.apply_button.accessibleName() == (
            "Apply and enable audit webhook"
        )
        assert dialog.disable_button.accessibleName() == "Disable audit webhook"
        assert dialog.clear_button.accessibleName() == (
            "Remove sealed audit webhook credential"
        )
        assert dialog.url_input.echoMode() == QLineEdit.EchoMode.Password
        assert dialog.reveal_checkbox.isChecked() is False

        dialog.url_input.setText(_secret_url())
        dialog.reveal_checkbox.setChecked(True)
        assert dialog.url_input.echoMode() == QLineEdit.EchoMode.Normal
        dialog.url_input.selectAll()
        dialog.url_input.copy()
        QTest.keyClick(
            dialog.url_input,
            Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier,
        )

        assert clipboard.text() == "clipboard sentinel"
    finally:
        dialog.close()


def test_apply_passes_secret_only_to_backend_then_scrubs_ui_and_logs(
    qapp: QApplication,
    monkeypatch,
) -> None:
    from app.gui import audit_webhook_dialog as dialog_module

    backend = _Backend()
    app_settings = AppSettings()
    settings_before = asdict(app_settings)
    logs = []
    monkeypatch.setattr(dialog_module, "log_info", logs.append)
    monkeypatch.setattr(dialog_module, "log_error", logs.append)
    clipboard = qapp.clipboard()
    clipboard.setText("unchanged")
    secret = _secret_url()
    dialog = _dialog(backend)
    try:
        dialog.url_input.setText(secret)
        dialog.reveal_checkbox.setChecked(True)
        dialog.kind_combo.setCurrentIndex(1)
        dialog.rate_limit_spinbox.setValue(42)

        assert dialog.apply_and_enable() is True

        submitted, kwargs = backend.provision_calls[0]
        assert submitted == secret
        assert kwargs == {
            "kind": "generic",
            "rate_limit_per_min": 42,
            "enabled": True,
        }
        assert dialog.url_input.text() == ""
        dialog.url_input.undo()
        assert dialog.url_input.text() == ""
        assert dialog.url_input.echoMode() == QLineEdit.EchoMode.Password
        assert dialog.reveal_checkbox.isChecked() is False
        assert clipboard.text() == "unchanged"
        assert asdict(app_settings) == settings_before
        assert secret not in json.dumps(asdict(app_settings))
        assert secret not in "\n".join(logs)
        displayed = "\n".join(
            label.text() for label in dialog.findChildren(QLabel)
        )
        assert secret not in displayed
        assert "successfully" in dialog.action_status.text().lower()
    finally:
        dialog.close()


def test_enable_and_disable_use_metadata_only_backend_actions(
    qapp: QApplication,
) -> None:
    backend = _Backend(configured=True, enabled=False)
    dialog = _dialog(backend)
    try:
        assert dialog.enable_button.isEnabled() is True
        assert dialog.enable_existing() is True
        assert backend.enabled_calls == [True]
        assert dialog.disable_button.isEnabled() is True

        dialog.url_input.setText(_secret_url())
        assert dialog.disable_webhook() is True

        assert backend.enabled_calls == [True, False]
        assert dialog.url_input.text() == ""
        assert "disabled successfully" in dialog.action_status.text().lower()
    finally:
        dialog.close()


def test_clear_requires_confirmation_and_cancel_attempts_no_removal(
    qapp: QApplication,
) -> None:
    backend = _Backend(configured=True, enabled=True)
    confirmations = []

    def decline(_parent) -> bool:
        confirmations.append(True)
        return False

    dialog = _dialog(backend, clear_confirmation=decline)
    try:
        dialog.url_input.setText(_secret_url())

        assert dialog.clear_webhook() is False

        assert confirmations == [True]
        assert backend.clear_calls == 0
        assert dialog.url_input.text() == ""
        assert "canceled" in dialog.action_status.text().lower()
    finally:
        dialog.close()


def test_confirmed_clear_removes_sealed_credential_and_refreshes_status(
    qapp: QApplication,
) -> None:
    backend = _Backend(configured=True, enabled=True)
    dialog = _dialog(
        backend,
        clear_confirmation=lambda _parent: True,
    )
    try:
        assert dialog.clear_webhook() is True

        assert backend.clear_calls == 1
        assert backend.state["configured"] is False
        assert "removed successfully" in dialog.action_status.text().lower()
        assert "No audit webhook credential" in dialog.configuration_status.text()
    finally:
        dialog.close()


@pytest.mark.parametrize("action", ["apply", "disable", "clear"])
def test_backend_failures_are_fixed_generic_messages_without_secrets(
    qapp: QApplication,
    monkeypatch,
    action: str,
) -> None:
    from app.gui import audit_webhook_dialog as dialog_module

    secret = _secret_url()
    logs = []
    monkeypatch.setattr(dialog_module, "log_error", logs.append)

    def fail(*_args, **_kwargs):
        raise RuntimeError(f"backend exposed {secret}")

    backend = _Backend(configured=True, enabled=True)
    dialog = AuditWebhookDialog(
        status_reader=backend.status,
        provisioner=fail if action == "apply" else backend.provision,
        enabled_configurer=fail if action == "disable" else backend.configure,
        clearer=fail if action == "clear" else backend.clear,
        clear_confirmation=lambda _parent: True,
    )
    try:
        dialog.url_input.setText(secret)
        if action == "apply":
            result = dialog.apply_and_enable()
        elif action == "disable":
            result = dialog.disable_webhook()
        else:
            result = dialog.clear_webhook()

        feedback = dialog.action_status.text()
        assert result is False
        assert "failed" in feedback.lower() or "could not" in feedback.lower()
        assert secret not in feedback
        assert secret not in "\n".join(logs)
        assert dialog.url_input.text() == ""
    finally:
        dialog.close()


def test_status_failure_and_dialog_cancel_never_display_or_restore_secret(
    qapp: QApplication,
) -> None:
    secret = _secret_url()
    dialog = AuditWebhookDialog(
        status_reader=lambda: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    dialog.url_input.setText(secret)
    dialog.reveal_checkbox.setChecked(True)

    assert secret not in dialog.configuration_status.text()
    dialog.reject()

    assert dialog.url_input.text() == ""
    dialog.url_input.undo()
    assert dialog.url_input.text() == ""
    assert dialog.url_input.echoMode() == QLineEdit.EchoMode.Password


def test_unknown_secret_bearing_status_fields_are_never_displayed(
    qapp: QApplication,
) -> None:
    secret = _secret_url()
    status = _status(configured=True, enabled=True)
    status["url"] = secret
    status["nested"] = {"token": secret}
    dialog = AuditWebhookDialog(status_reader=lambda: status)
    try:
        displayed = "\n".join(
            label.text() for label in dialog.findChildren(QLabel)
        )
        assert secret not in displayed
        assert "configured and enabled" in dialog.configuration_status.text()
    finally:
        dialog.close()


def test_dashboard_opens_sealed_webhook_dialog(monkeypatch) -> None:
    from app.gui import audit_webhook_dialog
    from app.gui.dashboard import DupeZDashboard

    opened = {}

    class _Dialog:
        def __init__(self, parent) -> None:
            opened["parent"] = parent

        def exec(self) -> None:
            opened["executed"] = True

    monkeypatch.setattr(audit_webhook_dialog, "AuditWebhookDialog", _Dialog)
    parent = object()

    DupeZDashboard._show_audit_webhook_config(parent)

    assert opened == {"parent": parent, "executed": True}
