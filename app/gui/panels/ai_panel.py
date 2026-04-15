# app/gui/panels/ai_panel.py — Consolidated AI / Smart Ops panel
"""Unified container for Smart Mode, ML data capture, Auto-tune, and Voice
Control. Rendered as a tab inside NetworkToolsView rather than as separate
collapsible cards on ClumsyControlView, so the disruption view stays focused
on targeting and the AI surface area lives alongside Traffic Monitor /
Latency / Scanner / Mapper.

The panels themselves (SmartModePanel, VoicePanel, ML capture QGroupBox) are
still *owned* by ClumsyControlView — all their event handlers point at
ClumsyControlView methods (controller access, selected_ip, disrupt, etc.).
AIPanel is a pure layout host. Reparenting only.

The one new piece of logic here is the Smart Mode tri-state orchestrator
(Off / Learn / Assist) which flips two params on ClumsyControlView at once:

  Off    — no episode capture, no auto-tune, manual recommendations only
  Learn  — _record_episodes=True, no auto-tune (first-run data gathering)
  Assist — _record_episodes=True, _auto_tune_duration=True, SmartEngine
           recommendations auto-applied to params on DISRUPT

This collapses three separate toggles into one coherent control so users
can't accidentally capture episodes without outcome labels, or run
auto-tune on an empty episode history.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox,
    QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt

__all__ = ["AIPanel", "SMART_MODE_OFF", "SMART_MODE_LEARN", "SMART_MODE_ASSIST"]


SMART_MODE_OFF = "off"
SMART_MODE_LEARN = "learn"
SMART_MODE_ASSIST = "assist"


class AIPanel(QWidget):
    """Consolidated AI / Smart Ops tab.

    Composition (top to bottom):
      1. Smart Mode tri-state combo  (Off / Learn / Assist)
      2. SmartModePanel              (profiler, recommendations, LLM advisor)
      3. ML data capture QGroupBox   (episode toggle, outcome labels, suggest-duration)
      4. VoicePanel                  (voice control subsystem)

    All four sections are reparented here from ClumsyControlView. No event
    handlers are rewired.
    """

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

        # Scroll wrapper — stacked sub-panels can exceed window height
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #0a0e1a; border: none; }")

        inner = QWidget()
        inner.setStyleSheet("background: #0a0e1a;")
        layout = QVBoxLayout(inner)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Smart Mode tri-state header ────────────────────────────
        mode_group = QGroupBox("SMART MODE")
        mode_group.setStyleSheet(self._group_qss())
        mode_layout = QVBoxLayout()
        mode_layout.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_label = QLabel("MODE:")
        mode_label.setStyleSheet("color: #a855f7; font-weight: bold; font-size: 11px;")
        mode_label.setFixedWidth(48)
        mode_row.addWidget(mode_label)

        self.smart_mode_combo = QComboBox()
        self.smart_mode_combo.addItem("Off — manual only",               SMART_MODE_OFF)
        self.smart_mode_combo.addItem("Learn — capture episodes",        SMART_MODE_LEARN)
        self.smart_mode_combo.addItem("Assist — capture + auto-tune",    SMART_MODE_ASSIST)
        self.smart_mode_combo.setStyleSheet(
            "QComboBox { background: #0a1628; color: #e0e0e0; "
            "border: 1px solid #1a2a3a; border-radius: 4px; "
            "padding: 4px 6px; font-size: 11px; }"
            " QComboBox:hover { border-color: #a855f7; }"
        )
        self.smart_mode_combo.setToolTip(
            "Off    — no capture, no auto-tune. Manual recommendations only.\n"
            "Learn  — records JSONL episodes to app/data/episodes/ for training.\n"
            "Assist — capture + auto-tune duration + apply SmartEngine recs on DISRUPT."
        )
        self.smart_mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.smart_mode_combo, 1)
        mode_layout.addLayout(mode_row)

        self.smart_mode_status = QLabel(
            "Off — recommendations are advisory only. Toggle to Learn to start "
            "capturing episodes."
        )
        self.smart_mode_status.setWordWrap(True)
        self.smart_mode_status.setStyleSheet(
            "color: #6b7280; font-size: 10px; padding: 4px 2px;"
        )
        mode_layout.addWidget(self.smart_mode_status)

        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # ── SmartModePanel (reparented) ────────────────────────────
        if smart_panel is not None:
            smart_panel.setParent(inner)
            layout.addWidget(smart_panel)

        # ── ML data capture widget (reparented) ────────────────────
        if ml_widget is not None:
            ml_widget.setParent(inner)
            layout.addWidget(ml_widget)

        # ── VoicePanel (reparented) ────────────────────────────────
        if voice_panel is not None:
            voice_panel.setParent(inner)
            layout.addWidget(voice_panel)

        layout.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------
    # Smart Mode tri-state orchestration
    # ------------------------------------------------------------------
    def _on_mode_changed(self, index: int) -> None:
        """Flip ClumsyControlView flags based on mode selection.

        The engine reads these via params dict on DISRUPT, so we just need
        the widget states on ClumsyControlView to be correct when
        _collect_params() runs.
        """
        mode = self.smart_mode_combo.itemData(index)
        cv = self._clumsy_view

        if mode == SMART_MODE_OFF:
            self.smart_mode_status.setText(
                "Off — recommendations are advisory only. No episode capture."
            )
            self.smart_mode_status.setStyleSheet(
                "color: #6b7280; font-size: 10px; padding: 4px 2px;")
            _set_checked(getattr(cv, "record_episodes_cb", None), False)
            cv._smart_mode_auto_tune = False

        elif mode == SMART_MODE_LEARN:
            self.smart_mode_status.setText(
                "Learn — every cut is recorded as a JSONL episode. "
                "Use MARK DUPE SUCCESS / FAIL to label outcomes. Auto-tune off."
            )
            self.smart_mode_status.setStyleSheet(
                "color: #00f0ff; font-size: 10px; padding: 4px 2px;")
            _set_checked(getattr(cv, "record_episodes_cb", None), True)
            cv._smart_mode_auto_tune = False

        elif mode == SMART_MODE_ASSIST:
            self.smart_mode_status.setText(
                "Assist — capture + auto-tune duration from learned episodes. "
                "DISRUPT pulls SmartEngine recommendations automatically."
            )
            self.smart_mode_status.setStyleSheet(
                "color: #a855f7; font-size: 10px; padding: 4px 2px;")
            _set_checked(getattr(cv, "record_episodes_cb", None), True)
            cv._smart_mode_auto_tune = True

    @property
    def mode(self) -> str:
        idx = self.smart_mode_combo.currentIndex()
        return self.smart_mode_combo.itemData(idx) or SMART_MODE_OFF

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    @staticmethod
    def _group_qss() -> str:
        return (
            "QGroupBox { background: #0f1626; color: #e0e0e0; "
            "border: 1px solid #1a2a3a; border-radius: 6px; "
            "margin-top: 10px; padding-top: 10px; font-weight: bold; "
            "font-size: 11px; }"
            " QGroupBox::title { subcontrol-origin: margin; "
            "subcontrol-position: top left; left: 8px; padding: 0 4px; "
            "color: #a855f7; }"
        )


def _set_checked(widget: Optional[QWidget], checked: bool) -> None:
    """Safely toggle a checkbox without triggering signal loops."""
    if widget is None:
        return
    try:
        widget.blockSignals(True)
        widget.setChecked(bool(checked))
    finally:
        widget.blockSignals(False)
