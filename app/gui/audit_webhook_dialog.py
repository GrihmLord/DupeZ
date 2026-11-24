"""Secret-safe UI for sealed audit-webhook configuration."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.audit_webhook_config import (
    audit_webhook_status,
    clear_audit_webhook,
    configure_audit_webhook_enabled,
    provision_audit_webhook,
)
from app.logs.logger import log_error, log_info

__all__ = ["AuditWebhookDialog", "SecretUrlLineEdit"]


class SecretUrlLineEdit(QLineEdit):
    """Password-mode URL input that never offers copy or cut operations."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setMaxLength(8192)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setDragEnabled(False)
        self.setInputMethodHints(
            Qt.InputMethodHint.ImhSensitiveData
            | Qt.InputMethodHint.ImhNoPredictiveText
            | Qt.InputMethodHint.ImhNoAutoUppercase
        )

    def copy(self) -> None:
        """Deliberately suppress copying bearer credentials."""

    def cut(self) -> None:
        """Deliberately suppress cutting bearer credentials."""

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.matches(
            QKeySequence.StandardKey.Copy
        ) or event.matches(QKeySequence.StandardKey.Cut):
            event.accept()
            return
        super().keyPressEvent(event)


class AuditWebhookDialog(QDialog):
    """Configure a webhook without routing its URL through application state."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        status_reader: Callable[..., dict[str, Any]] = audit_webhook_status,
        provisioner: Callable[..., None] = provision_audit_webhook,
        enabled_configurer: Callable[..., None] = configure_audit_webhook_enabled,
        clearer: Callable[..., None] = clear_audit_webhook,
        clear_confirmation: Callable[[QWidget], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._status_reader = status_reader
        self._provisioner = provisioner
        self._enabled_configurer = enabled_configurer
        self._clearer = clearer
        self._clear_confirmation = clear_confirmation or self._confirm_clear

        self.setWindowTitle("Audit Webhook")
        self.setModal(True)
        self.resize(620, 430)
        self.setAccessibleName("Audit webhook configuration")

        layout = QVBoxLayout(self)
        notice = QLabel(
            "The webhook URL is a bearer credential. DupeZ seals it in the "
            "current user's secret store and never displays the stored value."
        )
        notice.setWordWrap(True)
        notice.setAccessibleName("Webhook credential privacy notice")
        layout.addWidget(notice)

        self.configuration_status = QLabel()
        self.configuration_status.setWordWrap(True)
        self.configuration_status.setTextFormat(Qt.TextFormat.PlainText)
        self.configuration_status.setAccessibleName("Audit webhook status")
        layout.addWidget(self.configuration_status)

        form = QFormLayout()
        self.url_input = SecretUrlLineEdit()
        self.url_input.setPlaceholderText(
            "Paste the complete allowlisted HTTPS webhook URL"
        )
        self.url_input.setAccessibleName("Audit webhook secret URL")
        self.url_input.setAccessibleDescription(
            "Bearer credential entry; hidden by default and never copied"
        )
        form.addRow("Secret URL:", self.url_input)

        self.reveal_checkbox = QCheckBox("Reveal while editing")
        self.reveal_checkbox.setChecked(False)
        self.reveal_checkbox.setAccessibleName("Reveal webhook URL temporarily")
        self.reveal_checkbox.toggled.connect(self._set_revealed)
        form.addRow("Visibility:", self.reveal_checkbox)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Discord", "discord")
        self.kind_combo.addItem("Generic allowlisted host", "generic")
        self.kind_combo.setAccessibleName("Webhook type")
        form.addRow("Type:", self.kind_combo)

        self.rate_limit_spinbox = QSpinBox()
        self.rate_limit_spinbox.setRange(1, 600)
        self.rate_limit_spinbox.setValue(30)
        self.rate_limit_spinbox.setSuffix(" events/min")
        self.rate_limit_spinbox.setAccessibleName("Webhook rate limit")
        form.addRow("Rate limit:", self.rate_limit_spinbox)
        layout.addLayout(form)

        self.action_status = QLabel("No configuration action has run yet.")
        self.action_status.setWordWrap(True)
        self.action_status.setTextFormat(Qt.TextFormat.PlainText)
        self.action_status.setAccessibleName("Webhook action status")
        layout.addWidget(self.action_status)

        first_row = QHBoxLayout()
        self.apply_button = QPushButton("&Apply and Enable")
        self.apply_button.setAccessibleName("Apply and enable audit webhook")
        self.apply_button.clicked.connect(self.apply_and_enable)
        first_row.addWidget(self.apply_button)

        self.enable_button = QPushButton("Enable &Existing")
        self.enable_button.setAccessibleName("Enable existing audit webhook")
        self.enable_button.clicked.connect(self.enable_existing)
        first_row.addWidget(self.enable_button)

        self.disable_button = QPushButton("&Disable")
        self.disable_button.setAccessibleName("Disable audit webhook")
        self.disable_button.clicked.connect(self.disable_webhook)
        first_row.addWidget(self.disable_button)
        layout.addLayout(first_row)

        second_row = QHBoxLayout()
        self.clear_button = QPushButton("&Remove Credential…")
        self.clear_button.setAccessibleName(
            "Remove sealed audit webhook credential"
        )
        self.clear_button.clicked.connect(self.clear_webhook)
        second_row.addWidget(self.clear_button)
        second_row.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.setAccessibleName("Close audit webhook configuration")
        self.close_button.clicked.connect(self.reject)
        second_row.addWidget(self.close_button)
        layout.addLayout(second_row)

        self.refresh_status()

    def _set_revealed(self, revealed: bool) -> None:
        mode = (
            QLineEdit.EchoMode.Normal
            if revealed
            else QLineEdit.EchoMode.Password
        )
        self.url_input.setEchoMode(mode)

    def _scrub_secret_field(self) -> None:
        # setText() clears the QLineEdit undo/redo history, unlike an
        # interactive deletion which could restore the credential with Undo.
        self.url_input.setText("")
        self.reveal_checkbox.setChecked(False)
        self.url_input.setEchoMode(QLineEdit.EchoMode.Password)

    def done(self, result: int) -> None:
        self._scrub_secret_field()
        super().done(result)

    def _set_action_status(self, message: str, *, success: bool) -> None:
        self.action_status.setText(message)
        color = "#14833b" if success else "#b42318"
        self.action_status.setStyleSheet(f"color: {color};")

    def refresh_status(self) -> bool:
        """Read and display only URL-free backend status fields."""
        try:
            status = self._status_reader()
            if not isinstance(status, dict):
                raise TypeError("status must be an object")
            configured_value = status.get("configured")
            enabled_value = status.get("enabled")
            accessible_value = status.get("secret_store_accessible")
            if any(
                type(value) is not bool
                for value in (
                    configured_value,
                    enabled_value,
                    accessible_value,
                )
            ):
                raise TypeError("status flags must be true or false")
            configured = configured_value
            enabled = enabled_value
            store_accessible = accessible_value
            kind = status.get("kind")
            rate_limit = status.get("rate_limit_per_min")
            if kind not in {None, "discord", "generic"}:
                raise ValueError("invalid status kind")
            if rate_limit is not None and (
                isinstance(rate_limit, bool)
                or not isinstance(rate_limit, int)
                or not 1 <= rate_limit <= 600
            ):
                raise ValueError("invalid status rate limit")
            if enabled and not configured:
                raise ValueError("unconfigured webhook cannot be enabled")
            if configured and not store_accessible:
                raise ValueError("configured webhook store must be accessible")
            if configured and (
                kind not in {"discord", "generic"} or rate_limit is None
            ):
                raise ValueError("configured webhook status is incomplete")
        except Exception:
            log_error("Audit webhook status refresh failed")
            self.configuration_status.setText(
                "Audit webhook status is unavailable. No stored URL was read "
                "or displayed."
            )
            self.enable_button.setEnabled(False)
            self.disable_button.setEnabled(False)
            return False

        if configured:
            state = "enabled" if enabled else "disabled"
            kind_label = "Discord" if kind == "discord" else "Generic"
            self.configuration_status.setText(
                f"A sealed {kind_label} audit webhook is configured and "
                f"{state} at {rate_limit} events/minute. The URL is hidden."
            )
            self.kind_combo.setCurrentIndex(0 if kind == "discord" else 1)
            self.rate_limit_spinbox.setValue(rate_limit)
        elif store_accessible:
            self.configuration_status.setText(
                "No audit webhook credential is configured. The sealed secret "
                "store is accessible."
            )
        else:
            self.configuration_status.setText(
                "Audit webhook configuration could not be confirmed because "
                "the sealed secret store is unavailable."
            )

        self.enable_button.setEnabled(configured and not enabled)
        self.disable_button.setEnabled(configured and enabled)
        return True

    def apply_and_enable(self) -> bool:
        """Provision the entered URL and enable it, then erase the field."""
        url = self.url_input.text()
        if not url.strip():
            self._set_action_status(
                "Enter the complete webhook URL before applying.",
                success=False,
            )
            return False
        try:
            self._provisioner(
                url,
                kind=self.kind_combo.currentData(),
                rate_limit_per_min=self.rate_limit_spinbox.value(),
                enabled=True,
            )
        except Exception:
            log_error("Audit webhook apply failed")
            self._set_action_status(
                "Apply failed. The webhook was not enabled; verify the "
                "allowlisted HTTPS URL and secret-store availability.",
                success=False,
            )
            return False
        finally:
            url = ""
            self._scrub_secret_field()

        log_info("Audit webhook configuration applied through sealed storage")
        self.refresh_status()
        self._set_action_status(
            "Audit webhook applied and enabled successfully.",
            success=True,
        )
        return True

    def _configure_enabled(self, enabled: bool) -> bool:
        try:
            self._enabled_configurer(enabled)
        except Exception:
            log_error("Audit webhook enable-state change failed")
            action = "enable" if enabled else "disable"
            self._set_action_status(
                f"Could not {action} the audit webhook. Configuration was "
                "not reported as changed.",
                success=False,
            )
            return False
        finally:
            self._scrub_secret_field()

        self.refresh_status()
        state = "enabled" if enabled else "disabled"
        log_info(f"Audit webhook {state}")
        self._set_action_status(
            f"Audit webhook {state} successfully.",
            success=True,
        )
        return True

    def enable_existing(self) -> bool:
        return self._configure_enabled(True)

    def disable_webhook(self) -> bool:
        return self._configure_enabled(False)

    @staticmethod
    def _confirm_clear(parent: QWidget) -> bool:
        reply = QMessageBox.question(
            parent,
            "Remove Audit Webhook Credential",
            "Remove the sealed audit webhook credential? The webhook will be "
            "disabled first, and this action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def clear_webhook(self) -> bool:
        """Clear the sealed credential only after explicit confirmation."""
        self._scrub_secret_field()
        try:
            confirmed = self._clear_confirmation(self)
        except Exception:
            log_error("Audit webhook removal confirmation failed")
            self._set_action_status(
                "Credential removal was not confirmed; no removal was attempted.",
                success=False,
            )
            return False
        if not confirmed:
            self.action_status.setStyleSheet("")
            self.action_status.setText(
                "Credential removal canceled; configuration was not changed."
            )
            return False

        try:
            self._clearer()
        except Exception:
            log_error("Audit webhook credential removal failed")
            self._set_action_status(
                "Credential removal failed. The webhook remains disabled or "
                "unchanged; no stored URL was displayed.",
                success=False,
            )
            return False

        self.refresh_status()
        log_info("Audit webhook credential removal completed")
        self._set_action_status(
            "The sealed audit webhook credential was removed successfully.",
            success=True,
        )
        return True
