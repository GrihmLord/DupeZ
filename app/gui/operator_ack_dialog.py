"""First-run authorization and safety acknowledgement."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from app.core.operator_acknowledgement import ACKNOWLEDGEMENT_TEXT


class OperatorAcknowledgementDialog(QDialog):
    """Require an explicit owned-network acknowledgement before startup."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Authorized Use Required")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setAccessibleName("DupeZ authorized-use acknowledgement")
        self.setAccessibleDescription(
            "Confirms that active network testing is limited to owned or "
            "explicitly authorized local networks and devices."
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("Use DupeZ only in an owned or authorized lab")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        title.setAccessibleName("Authorized-use requirement")
        layout.addWidget(title)

        explanation = QLabel(
            "DupeZ can deliberately alter or interrupt network traffic. "
            "Before continuing, confirm the scope in which you will operate."
        )
        explanation.setWordWrap(True)
        explanation.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(explanation)

        policy = QLabel(
            "• Only devices and local networks you own or have explicit "
            "permission to test\n"
            "• Never public servers or third-party devices\n"
            "• Use Dry Run first and keep the automatic stop deadline enabled\n"
            "• Follow applicable law and platform terms"
        )
        policy.setWordWrap(True)
        policy.setAccessibleName("Authorized-use policy summary")
        layout.addWidget(policy)

        self.confirm_checkbox = QCheckBox(
            "I understand and will use DupeZ only in this authorized scope"
        )
        self.confirm_checkbox.setAccessibleName(
            "I accept the authorized-use policy"
        )
        self.confirm_checkbox.setAccessibleDescription(
            f"{ACKNOWLEDGEMENT_TEXT} Check to enable the Continue button."
        )
        layout.addWidget(self.confirm_checkbox)

        buttons = QDialogButtonBox()
        self.continue_button = buttons.addButton(
            "Continue",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        buttons.addButton("Exit", QDialogButtonBox.ButtonRole.RejectRole)
        self.continue_button.setEnabled(False)
        self.continue_button.setAccessibleName("Continue to DupeZ")
        self.confirm_checkbox.toggled.connect(
            self.continue_button.setEnabled
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
