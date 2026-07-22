# app/gui/panels/ai_panel.py — Consolidated AI / Smart Ops panel
"""Unified Smart Ops, direct engine, event, ML, and voice controls.

The owned sub-panels still bind to ``ClumsyControlView`` for target selection,
current effects, controller access, and outcome labels. This layout host adds
two orchestration surfaces:

* Direct Clumsy / Event Queue: explicit Auto, Clumsy, or Native routing plus
  ordered, toggleable events with delay, duration, layer, and failure policy.
* Smart Mode: Off, Learn, or Assist coordination for episode capture and
  model-informed tuning.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.gui.panels.disruption_event_panel import DisruptionEventPanel

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

        # Direct engine routing and user-owned events are intentionally first:
        # they affect both manual DISRUPT actions and queued event execution.
        self.event_panel = DisruptionEventPanel(clumsy_view, parent=inner)
        layout.addWidget(self.event_panel)

        mode_group = QGroupBox("SMART MODE")
        mode_group.setStyleSheet(self._group_qss())
        mode_layout = QVBoxLayout()
        mode_layout.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_label = QLabel("MODE:")
        mode_label.setStyleSheet(
            "color: #a855f7; font-weight: bold; font-size: 11px;"
        )
        mode_label.setFixedWidth(48)
        mode_row.addWidget(mode_label)

        self.smart_mode_combo = QComboBox()
        self.smart_mode_combo.addItem(
            "Off — manual only",
            SMART_MODE_OFF,
        )
        self.smart_mode_combo.addItem(
            "Learn — capture episodes",
            SMART_MODE_LEARN,
        )
        self.smart_mode_combo.addItem(
            "Assist — capture + auto-tune",
            SMART_MODE_ASSIST,
        )
        self.smart_mode_combo.setStyleSheet(
            "QComboBox { background: #0a1628; color: #e0e0e0; "
            "border: 1px solid #1a2a3a; border-radius: 4px; "
            "padding: 4px 6px; font-size: 11px; }"
            "QComboBox:hover { border-color: #a855f7; }"
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
        self.smart_mode_status.setStyleSheet(
            "color: #6b7280; font-size: 10px; padding: 4px 2px;"
        )
        mode_layout.addWidget(self.smart_mode_status)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        if smart_panel is not None:
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

    def _on_mode_changed(self, index: int) -> None:
        """Coordinate episode capture and bounded automatic tuning."""

        mode = self.smart_mode_combo.itemData(index)
        clumsy_view = self._clumsy_view

        if mode == SMART_MODE_OFF:
            self.smart_mode_status.setText(
                "Off — recommendations are advisory only. No episode capture."
            )
            self.smart_mode_status.setStyleSheet(
                "color: #6b7280; font-size: 10px; padding: 4px 2px;"
            )
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
                "episodes. SmartEngine recommendations apply on DISRUPT."
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
        )


def _set_checked(widget: Optional[QWidget], checked: bool) -> None:
    """Toggle a checkbox without emitting intermediate state signals."""

    if widget is None:
        return
    try:
        widget.blockSignals(True)
        widget.setChecked(bool(checked))
    finally:
        widget.blockSignals(False)
