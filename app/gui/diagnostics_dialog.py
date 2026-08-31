"""Accessible diagnostics dialog and redacted support-bundle actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.diagnostics import CheckStatus
from app.core.support_bundle import (
    SupportBundleResult,
    build_support_bundle,
    default_support_bundle_path,
    sanitize_support_value,
    write_support_bundle,
)
from app.logs.logger import log_error, log_info

__all__ = ["DiagnosticsDialog", "format_diagnostics_report"]


def _safe_text(value: Any) -> str:
    sanitized = sanitize_support_value(str(value or ""))
    return sanitized if isinstance(sanitized, str) else ""


def format_diagnostics_report(results: Iterable[Any]) -> str:
    """Format diagnostic results after applying support-bundle redaction."""
    entries = list(results)
    icons = {
        CheckStatus.PASS: "[OK]  ",
        CheckStatus.WARN: "[WARN]",
        CheckStatus.FAIL: "[FAIL]",
    }
    failures = sum(
        1 for result in entries if result.status == CheckStatus.FAIL
    )
    lines = [
        f"{len(entries)} checks — {failures} failing",
        "=" * 40,
        "",
    ]
    for result in entries:
        lines.append(
            f"{icons.get(result.status, '[?]')} {_safe_text(result.name)}"
        )
        lines.append(f"        {_safe_text(result.message)}")
        if result.fix_hint:
            lines.append(f"        fix: {_safe_text(result.fix_hint)}")
        lines.append("")
    return "\n".join(lines).rstrip()


class DiagnosticsDialog(QDialog):
    """Show checks and export only the redacted support-bundle payload."""

    def __init__(
        self,
        results: Iterable[Any],
        parent: QWidget | None = None,
        *,
        bundle_builder: Callable[..., dict[str, Any]] = build_support_bundle,
        bundle_writer: Callable[..., SupportBundleResult] = write_support_bundle,
        save_path_provider: Callable[[QWidget, str], str] | None = None,
        default_save_path: Path | str | None = None,
        clipboard: Any = None,
    ) -> None:
        super().__init__(parent)
        self._results = list(results)
        self._bundle_builder = bundle_builder
        self._bundle_writer = bundle_writer
        self._save_path_provider = save_path_provider or self._choose_save_path
        self._default_save_path = default_save_path
        self._clipboard = clipboard

        self.setWindowTitle("DupeZ Diagnostics")
        self.setModal(True)
        self.resize(720, 560)
        self.setAccessibleName("DupeZ Diagnostics")

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Review local checks below. Copy and Save create a redacted JSON "
            "support bundle; account data and file listings are omitted."
        )
        intro.setWordWrap(True)
        intro.setAccessibleName("Support bundle privacy notice")
        layout.addWidget(intro)

        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setPlainText(format_diagnostics_report(self._results))
        self.report_view.setAccessibleName("Diagnostic check results")
        self.report_view.setAccessibleDescription(
            "Read-only, redacted results from local diagnostic checks"
        )
        layout.addWidget(self.report_view, 1)

        self.action_status = QLabel("No support bundle action has run yet.")
        self.action_status.setWordWrap(True)
        self.action_status.setTextFormat(Qt.TextFormat.PlainText)
        self.action_status.setAccessibleName("Support bundle action status")
        layout.addWidget(self.action_status)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("&Copy Bundle")
        self.copy_button.setAccessibleName("Copy redacted support bundle")
        self.copy_button.setToolTip(
            "Copy redacted support bundle JSON to the clipboard"
        )
        self.copy_button.clicked.connect(self.copy_support_bundle)
        buttons.addWidget(self.copy_button)

        self.save_button = QPushButton("&Save Bundle…")
        self.save_button.setAccessibleName("Save redacted support bundle")
        self.save_button.setToolTip("Save a redacted JSON support bundle")
        self.save_button.clicked.connect(self.save_support_bundle)
        buttons.addWidget(self.save_button)

        buttons.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.setAccessibleName("Close diagnostics")
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    @staticmethod
    def _choose_save_path(parent: QWidget, initial_path: str) -> str:
        selected, _filter = QFileDialog.getSaveFileName(
            parent,
            "Save Redacted Support Bundle",
            initial_path,
            "JSON files (*.json)",
        )
        return selected

    def _set_action_status(self, message: str, *, success: bool) -> None:
        self.action_status.setText(message)
        color = "#14833b" if success else "#b42318"
        self.action_status.setStyleSheet(f"color: {color};")

    def _bundle_kwargs(self) -> dict[str, Any]:
        return {
            "include_account_data": False,
            "include_file_list": False,
            "diagnostic_results": self._results,
        }

    def copy_support_bundle(self) -> bool:
        """Build, re-sanitize, and copy JSON without exposing raw failures."""
        try:
            payload = self._bundle_builder(**self._bundle_kwargs())
            safe_payload = sanitize_support_value(payload)
            if not isinstance(safe_payload, dict):
                raise TypeError("support bundle payload must be an object")
            rendered = json.dumps(
                safe_payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            clipboard = self._clipboard or QApplication.clipboard()
            clipboard.setText(rendered)
            read_text = getattr(clipboard, "text", None)
            if callable(read_text) and read_text() != rendered:
                raise OSError("clipboard did not retain support bundle text")
        except Exception as exc:
            log_error(
                "Support bundle copy failed "
                f"({type(exc).__name__})"
            )
            self._set_action_status(
                "Copy failed. No support bundle was copied; try again.",
                success=False,
            )
            return False

        log_info("Redacted support bundle copied to clipboard")
        self._set_action_status(
            "Copied the redacted support bundle JSON to the clipboard.",
            success=True,
        )
        return True

    def save_support_bundle(self) -> bool:
        """Prompt for an exclusive JSON destination and verify the result."""
        try:
            initial = self._default_save_path or default_support_bundle_path()
            selected = self._save_path_provider(self, str(initial))
        except Exception as exc:
            log_error(
                "Support bundle destination selection failed "
                f"({type(exc).__name__})"
            )
            self._set_action_status(
                "Save failed before a destination could be selected.",
                success=False,
            )
            return False

        if not selected:
            self.action_status.setStyleSheet("")
            self.action_status.setText("Save canceled; no file was written.")
            return False

        try:
            result = self._bundle_writer(
                output_path=selected,
                **self._bundle_kwargs(),
            )
            saved_path = Path(result.path) if result.path is not None else None
            if saved_path is None or not saved_path.is_file():
                raise OSError("support bundle writer did not create a file")
        except Exception as exc:
            log_error(
                "Support bundle save failed "
                f"({type(exc).__name__})"
            )
            self._set_action_status(
                "Save failed. No support bundle was confirmed; choose a new "
                "JSON filename and check folder permissions.",
                success=False,
            )
            return False

        log_info("Redacted support bundle saved")
        safe_name = _safe_text(saved_path.name) or "the selected JSON file"
        self._set_action_status(
            f"Saved the redacted support bundle as {safe_name}.",
            success=True,
        )
        return True
