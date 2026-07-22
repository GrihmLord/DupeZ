# app/gui/panels/ai_panel.py — Consolidated AI / Smart Ops panel
"""Unified Smart Ops, direct engine, event, ML, voice, and provider controls."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ai.secure_llm_runtime import ConfiguredLLMAdvisor, SecureLLMConfig
from app.gui.panels.disruption_event_panel import DisruptionEventPanel
from app.logs.logger import log_error

__all__ = [
    "AIPanel",
    "SMART_MODE_OFF",
    "SMART_MODE_LEARN",
    "SMART_MODE_ASSIST",
]

SMART_MODE_OFF = "off"
SMART_MODE_LEARN = "learn"
SMART_MODE_ASSIST = "assist"


class AIPanel(QWidget):
    """Consolidated AI / Smart Ops tab."""

    _provider_result = pyqtSignal(int, bool, str)

    def __init__(
        self,
        clumsy_view: Any,
        smart_panel: Optional[QWidget] = None,
        ml_widget: Optional[QWidget] = None,
        voice_panel: Optional[QWidget] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._clumsy_view = clumsy_view
        self._smart_panel = smart_panel
        self._ml_widget = ml_widget
        self._voice_panel = voice_panel
        self._provider_generation = 0
        self._advisor = ConfiguredLLMAdvisor.from_settings()
        self._provider_result.connect(self._apply_provider_result)
        self.destroyed.connect(lambda _obj=None: self._advisor.cancel_pending())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: #0a0e1a; border: none; }"
        )

        inner = QWidget()
        inner.setStyleSheet("background: #0a0e1a;")
        layout = QVBoxLayout(inner)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # Direct engine routing affects manual actions, queued events, and
        # SmartEngine recommendations.
        self.event_panel = DisruptionEventPanel(clumsy_view, parent=inner)
        layout.addWidget(self.event_panel)

        layout.addWidget(self._build_provider_group(inner))
        layout.addWidget(self._build_mode_group(inner))

        if smart_panel is not None:
            self._install_advisor_and_routing(smart_panel)
            smart_panel.setParent(inner)
            layout.addWidget(smart_panel)

        if ml_widget is not None:
            ml_widget.setParent(inner)
            layout.addWidget(ml_widget)

        if voice_panel is not None:
            voice_panel.setParent(inner)
            layout.addWidget(voice_panel)

        layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def _build_provider_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("SMART OPS PROVIDER", parent)
        group.setStyleSheet(self._group_qss())
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Provider"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Ollama — local", "ollama")
        self.provider_combo.addItem("OpenAI-compatible — remote", "openai")
        self.provider_combo.addItem("Offline rules only", "none")
        self.provider_combo.currentIndexChanged.connect(
            self._sync_provider_fields
        )
        provider_row.addWidget(self.provider_combo, 1)

        provider_row.addWidget(QLabel("Model"))
        self.provider_model = QLineEdit()
        self.provider_model.setPlaceholderText("mistral")
        provider_row.addWidget(self.provider_model, 1)
        layout.addLayout(provider_row)

        endpoint_row = QHBoxLayout()
        endpoint_row.addWidget(QLabel("Root URL"))
        self.provider_url = QLineEdit()
        self.provider_url.setPlaceholderText("http://localhost:11434")
        endpoint_row.addWidget(self.provider_url, 2)

        endpoint_row.addWidget(QLabel("API key"))
        self.provider_key = QLineEdit()
        self.provider_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.provider_key.setPlaceholderText("encrypted; blank keeps existing")
        endpoint_row.addWidget(self.provider_key, 1)
        layout.addLayout(endpoint_row)

        action_row = QHBoxLayout()
        self.provider_save = QPushButton("SAVE PROVIDER")
        self.provider_save.clicked.connect(self._save_provider)
        action_row.addWidget(self.provider_save)
        self.provider_test = QPushButton("TEST CONNECTION")
        self.provider_test.clicked.connect(self._test_provider)
        action_row.addWidget(self.provider_test)
        self.provider_delete_key = QPushButton("DELETE KEY")
        self.provider_delete_key.clicked.connect(self._delete_provider_key)
        action_row.addWidget(self.provider_delete_key)
        layout.addLayout(action_row)

        self.provider_status = QLabel(
            "Provider checks run outside the Qt thread. Offline rules remain "
            "available when no model service is configured."
        )
        self.provider_status.setWordWrap(True)
        self.provider_status.setStyleSheet(self._muted_qss())
        layout.addWidget(self.provider_status)

        config = self._advisor.config
        self.provider_combo.setCurrentIndex(
            max(0, self.provider_combo.findData(config.provider))
        )
        self.provider_url.setText(config.base_url)
        self.provider_model.setText(config.model)
        self._sync_provider_fields()
        return group

    def _build_mode_group(self, parent: QWidget) -> QGroupBox:
        mode_group = QGroupBox("SMART MODE", parent)
        mode_group.setStyleSheet(self._group_qss())
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_label = QLabel("MODE:")
        mode_label.setStyleSheet(
            "color: #a855f7; font-weight: bold; font-size: 11px;"
        )
        mode_label.setFixedWidth(48)
        mode_row.addWidget(mode_label)

        self.smart_mode_combo = QComboBox()
        self.smart_mode_combo.addItem("Off — manual only", SMART_MODE_OFF)
        self.smart_mode_combo.addItem(
            "Learn — capture episodes",
            SMART_MODE_LEARN,
        )
        self.smart_mode_combo.addItem(
            "Assist — capture + auto-tune",
            SMART_MODE_ASSIST,
        )
        self.smart_mode_combo.setToolTip(
            "Off — no capture or auto-tune.\n"
            "Learn — record per-user JSONL training episodes.\n"
            "Assist — record episodes and apply bounded SmartEngine tuning."
        )
        self.smart_mode_combo.currentIndexChanged.connect(
            self._on_mode_changed
        )
        mode_row.addWidget(self.smart_mode_combo, 1)
        mode_layout.addLayout(mode_row)

        self.smart_mode_status = QLabel(
            "Off — recommendations are advisory only. Toggle to Learn to "
            "start capturing episodes."
        )
        self.smart_mode_status.setWordWrap(True)
        self.smart_mode_status.setStyleSheet(self._muted_qss())
        mode_layout.addWidget(self.smart_mode_status)
        return mode_group

    def _install_advisor_and_routing(self, smart_panel: QWidget) -> None:
        previous = getattr(smart_panel, "_smart_advisor", None)
        if previous is not None and hasattr(previous, "cancel_pending"):
            previous.cancel_pending()
        smart_panel._smart_advisor = self._advisor

        original = smart_panel.apply_and_disrupt
        if getattr(smart_panel, "_direct_route_wrapper", None) is None:
            def routed_apply(profile, recommendation):
                original_params = recommendation.params
                recommendation.params = self.event_panel.augment_params(
                    original_params
                )
                try:
                    return original(profile, recommendation)
                finally:
                    recommendation.params = original_params

            smart_panel._direct_route_wrapper = routed_apply
            smart_panel.apply_and_disrupt = routed_apply

    def _sync_provider_fields(self, _index: int = -1) -> None:
        provider = str(self.provider_combo.currentData() or "none")
        enabled = provider != "none"
        self.provider_url.setEnabled(enabled)
        self.provider_model.setEnabled(enabled)
        self.provider_key.setEnabled(provider == "openai")
        self.provider_delete_key.setEnabled(provider == "openai")
        if provider == "ollama" and not self.provider_url.text().strip():
            self.provider_url.setText("http://localhost:11434")
        elif provider == "openai" and not self.provider_url.text().strip():
            self.provider_url.setText("https://api.openai.com")

    def _current_provider_config(self) -> SecureLLMConfig:
        return SecureLLMConfig(
            provider=str(self.provider_combo.currentData() or "none"),
            base_url=self.provider_url.text().strip(),
            model=self.provider_model.text().strip(),
            api_key=self.provider_key.text(),
            temperature=self._advisor.config.temperature,
            max_tokens=self._advisor.config.max_tokens,
            timeout=self._advisor.config.timeout,
        )

    @pyqtSlot()
    def _save_provider(self, *, quiet: bool = False) -> bool:
        try:
            config = self._current_provider_config()
            self._advisor.reconfigure(config, persist=True)
            if self._smart_panel is not None:
                self._smart_panel._smart_advisor = self._advisor
            self.provider_key.clear()
            if not quiet:
                self.provider_status.setText(
                    "Provider settings saved. API keys are stored encrypted "
                    "and are never written to settings.json."
                )
            return True
        except Exception as exc:
            log_error(f"Smart Ops provider configuration failed: {exc}")
            self.provider_status.setText(f"Provider configuration failed: {exc}")
            return False

    @pyqtSlot()
    def _test_provider(self) -> None:
        if not self._save_provider(quiet=True):
            return
        self._provider_generation += 1
        generation = self._provider_generation
        self.provider_test.setEnabled(False)
        self.provider_status.setText("Checking provider connection…")

        def _done(available: bool) -> None:
            detail = (
                "Provider connected and model requests are enabled."
                if available
                else "Provider unavailable; Smart Ops will use offline rules."
            )
            self._provider_result.emit(generation, available, detail)

        self._advisor.refresh_availability_async(_done)

    @pyqtSlot(int, bool, str)
    def _apply_provider_result(
        self,
        generation: int,
        available: bool,
        detail: str,
    ) -> None:
        if generation != self._provider_generation:
            return
        self.provider_test.setEnabled(True)
        self.provider_status.setText(detail)
        self.provider_status.setStyleSheet(
            "color: #00ff88; font-size: 10px; padding: 4px 2px;"
            if available
            else "color: #fbbf24; font-size: 10px; padding: 4px 2px;"
        )

    @pyqtSlot()
    def _delete_provider_key(self) -> None:
        deleted = self._advisor.config.delete_api_key()
        self.provider_key.clear()
        self.provider_status.setText(
            "Encrypted API key deleted."
            if deleted
            else "No encrypted API key was deleted."
        )

    def _on_mode_changed(self, index: int) -> None:
        """Coordinate episode capture and bounded automatic tuning."""

        mode = self.smart_mode_combo.itemData(index)
        clumsy_view = self._clumsy_view

        if mode == SMART_MODE_OFF:
            self.smart_mode_status.setText(
                "Off — recommendations are advisory only. No episode capture."
            )
            self.smart_mode_status.setStyleSheet(self._muted_qss())
            _set_checked(
                getattr(clumsy_view, "record_episodes_cb", None),
                False,
            )
            clumsy_view._smart_mode_auto_tune = False

        elif mode == SMART_MODE_LEARN:
            self.smart_mode_status.setText(
                "Learn — each cut is recorded as a JSONL episode. Use the "
                "outcome controls to label real observations. Auto-tune is off."
            )
            self.smart_mode_status.setStyleSheet(
                "color: #00f0ff; font-size: 10px; padding: 4px 2px;"
            )
            _set_checked(
                getattr(clumsy_view, "record_episodes_cb", None),
                True,
            )
            clumsy_view._smart_mode_auto_tune = False

        elif mode == SMART_MODE_ASSIST:
            self.smart_mode_status.setText(
                "Assist — capture plus bounded duration tuning from learned "
                "episodes. SmartEngine recommendations use the selected direct "
                "engine and capture layer."
            )
            self.smart_mode_status.setStyleSheet(
                "color: #a855f7; font-size: 10px; padding: 4px 2px;"
            )
            _set_checked(
                getattr(clumsy_view, "record_episodes_cb", None),
                True,
            )
            clumsy_view._smart_mode_auto_tune = True

    @property
    def mode(self) -> str:
        index = self.smart_mode_combo.currentIndex()
        return self.smart_mode_combo.itemData(index) or SMART_MODE_OFF

    @staticmethod
    def _group_qss() -> str:
        return (
            "QGroupBox { background: #0f1626; color: #e0e0e0; "
            "border: 1px solid #1a2a3a; border-radius: 6px; "
            "margin-top: 10px; padding-top: 10px; font-weight: bold; "
            "font-size: 11px; }"
            "QGroupBox::title { subcontrol-origin: margin; "
            "subcontrol-position: top left; left: 8px; padding: 0 4px; "
            "color: #a855f7; }"
            "QLineEdit, QComboBox { background: #0a1628; color: #e2e8f0; "
            "border: 1px solid #26364a; border-radius: 5px; padding: 5px; }"
            "QPushButton { background: #132337; color: #e2e8f0; "
            "border: 1px solid #2b425d; border-radius: 5px; padding: 6px; }"
            "QPushButton:hover { border-color: #a855f7; }"
            "QLabel { color: #cbd5e1; font-weight: normal; }"
        )

    @staticmethod
    def _muted_qss() -> str:
        return "color: #6b7280; font-size: 10px; padding: 4px 2px;"


def _set_checked(widget: Optional[QWidget], checked: bool) -> None:
    """Toggle a checkbox without emitting intermediate state signals."""

    if widget is None:
        return
    try:
        widget.blockSignals(True)
        widget.setChecked(bool(checked))
    finally:
        widget.blockSignals(False)
