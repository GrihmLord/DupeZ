# app/gui/panels/smart_mode_panel.py — AI Auto-Tune panel widget
"""Extracted from ClumsyControlView smart mode section and handler methods."""

from __future__ import annotations

import time

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QComboBox,
    QGroupBox, QLineEdit, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSlot

from app.logs.logger import log_info, log_error

# Smart engine — optional dependency
try:
    from app.ai.network_profiler import NetworkProfiler
    from app.ai.smart_engine import SmartDisruptionEngine, DisruptionRecommendation
    from app.ai.llm_advisor import LLMAdvisor
    from app.ai.session_tracker import SessionTracker
    SMART_ENGINE_AVAILABLE = True
except ImportError:
    SMART_ENGINE_AVAILABLE = False

__all__ = ["SmartModePanel"]


class SmartModePanel(QWidget):
    """AI auto-tune panel: profiling, smart disruption, LLM advisor."""

    def __init__(self, parent_view, parent=None) -> None:
        super().__init__(parent)
        self._view = parent_view
        self._active_session_id = None

        if SMART_ENGINE_AVAILABLE:
            self._smart_profiler = NetworkProfiler(ping_count=6, ping_timeout=2.0)
            self._smart_engine = SmartDisruptionEngine()
            self._smart_tracker = SessionTracker()
            self._smart_advisor = LLMAdvisor()
        else:
            self._smart_profiler = None
            self._smart_engine = None
            self._smart_tracker = None
            self._smart_advisor = None

        self._setup_ui()

    @property
    def available(self) -> bool:
        return SMART_ENGINE_AVAILABLE

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        if not SMART_ENGINE_AVAILABLE:
            return  # nothing to render

        smart_group = self._view._card("AI AUTO-TUNE")
        smart_layout = QVBoxLayout()
        smart_layout.setSpacing(6)

        # Goal selector
        goal_row = QHBoxLayout()
        goal_label = QLabel("GOAL:")
        goal_label.setStyleSheet(self._view._LABEL_BOLD_QSS)
        goal_label.setFixedWidth(40)
        goal_row.addWidget(goal_label)

        self.smart_goal_combo = QComboBox()
        self.smart_goal_combo.addItems([
            "Auto", "Disconnect", "Lag", "Desync",
            "Throttle", "Chaos", "God Mode"])
        self.smart_goal_combo.setStyleSheet(self._view._COMBO_QSS)
        goal_row.addWidget(self.smart_goal_combo, 1)
        smart_layout.addLayout(goal_row)

        # Intensity slider
        intensity_row = QHBoxLayout()
        int_label = QLabel("POWER:")
        int_label.setStyleSheet(self._view._LABEL_BOLD_QSS)
        int_label.setFixedWidth(48)
        intensity_row.addWidget(int_label)

        self.smart_intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.smart_intensity_slider.setRange(0, 100)
        self.smart_intensity_slider.setValue(80)
        self.smart_intensity_slider.setStyleSheet(
            self._view._SLIDER_QSS
            .replace("#00d9ff", "#a855f7")
            .replace("rgba(0,217,255,0.3)", "rgba(168,85,247,0.3)"))
        intensity_row.addWidget(self.smart_intensity_slider, 1)

        self.smart_intensity_label = QLabel("80%")
        self.smart_intensity_label.setFixedWidth(35)
        self.smart_intensity_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.smart_intensity_label.setStyleSheet(
            "color: #a855f7; font-weight: bold; font-size: 11px;")
        intensity_row.addWidget(self.smart_intensity_label)
        self.smart_intensity_slider.valueChanged.connect(
            lambda v: self.smart_intensity_label.setText(f"{v}%"))
        smart_layout.addLayout(intensity_row)

        # LLM prompt input
        self.smart_llm_input = QLineEdit()
        llm_row = QHBoxLayout()
        llm_label = self._view._lbl("ASK AI:", bold=True, size=11, w=48)
        llm_row.addWidget(llm_label)

        self.smart_llm_input.setPlaceholderText(
            "e.g. desync a PS5 on my hotspot playing DayZ")
        self.smart_llm_input.setStyleSheet("""
            QLineEdit {
                background: #0a1628; color: #e0e0e0; border: 1px solid #1a2a3a;
                border-radius: 4px; padding: 6px 8px; font-size: 11px;
            }
            QLineEdit:focus { border-color: #a855f7; }
        """)
        self.smart_llm_input.returnPressed.connect(self._on_smart_llm_ask)
        llm_row.addWidget(self.smart_llm_input, 1)
        smart_layout.addLayout(llm_row)

        # Action buttons
        smart_btn_row = QHBoxLayout()
        smart_btn_row.setSpacing(6)

        for attr, text, color, handler, tip in [
            ("btn_smart_profile", "PROFILE", "#a855f7",
             self._on_smart_profile, "Probe target and analyze connection"),
            ("btn_smart_disrupt", "SMART DISRUPT", "#e040fb",
             self._on_smart_disrupt,
             "Profile + auto-tune + disrupt in one click"),
        ]:
            btn = self._view._make_btn(text, color, "#1a0a2a", h=32, tip=tip)
            btn.clicked.connect(handler)
            setattr(self, attr, btn)
            smart_btn_row.addWidget(btn)
        smart_layout.addLayout(smart_btn_row)

        # AI recommendation display
        self.smart_info_label = QLabel(
            "Select a target and click PROFILE or SMART DISRUPT")
        self.smart_info_label.setWordWrap(True)
        self.smart_info_label.setStyleSheet(
            "color: #6b7280; font-size: 10px; padding: 4px; "
            "background: #0a0f18; border: 1px solid #1a2a3a; border-radius: 4px;")
        self.smart_info_label.setMinimumHeight(50)
        smart_layout.addWidget(self.smart_info_label)

        # Confidence bar
        self.smart_confidence_bar = self._view._progress_bar(
            "Confidence: %p%", 16, "#a855f7", "#e040fb")
        smart_layout.addWidget(self.smart_confidence_bar)

        smart_group.setLayout(smart_layout)
        layout.addWidget(smart_group)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _smart_run(self, label: str, color: str, slot: str) -> None:
        """Shared: validate target, show status, profile → slot."""
        if not SMART_ENGINE_AVAILABLE:
            return
        if not self._view.selected_ip:
            QMessageBox.warning(
                self._view, "No Target",
                "Select a device from the list first.")
            return
        self.smart_info_label.setText(label)
        self.smart_info_label.setStyleSheet(
            f"color: {color}; font-size: 10px; padding: 4px; "
            f"background: #0a0f18; border: 1px solid {color}; "
            f"border-radius: 4px;")
        self.btn_smart_profile.setEnabled(False)
        self.btn_smart_disrupt.setEnabled(False)

        def _on_profile_done(profile):
            goal = self.smart_goal_combo.currentText().lower()
            intensity = self.smart_intensity_slider.value() / 100.0
            rec = self._smart_engine.recommend(
                profile, goal=goal, intensity=intensity)
            self._view._invoke_main(slot, profile, rec)

        self._smart_profiler.profile_async(
            self._view.selected_ip, callback=_on_profile_done)

    def _on_smart_profile(self) -> None:
        self._smart_run(
            f"Profiling {self._view.selected_ip}...",
            "#a855f7", "_panel_smart_update_ui")

    def _on_smart_disrupt(self) -> None:
        self._smart_run(
            f"Smart disrupting {self._view.selected_ip}...",
            "#e040fb", "_panel_smart_apply_and_disrupt")

    def _on_smart_llm_ask(self) -> None:
        if not SMART_ENGINE_AVAILABLE or not self.smart_llm_input:
            return
        prompt = self.smart_llm_input.text().strip()
        if not prompt:
            return
        self.smart_info_label.setText("Asking AI advisor...")
        self.smart_llm_input.setEnabled(False)
        self._smart_advisor.ask_async(
            prompt,
            callback=lambda r: self._view._invoke_main(
                "_panel_smart_apply_llm_result", r))

    @pyqtSlot(object, object)
    def update_ui(self, profile, rec) -> None:
        """Update Smart Mode UI with profiling results (main thread)."""
        self.btn_smart_profile.setEnabled(True)
        self.btn_smart_disrupt.setEnabled(True)

        info_lines = [
            "<b style='color:#a855f7'>TARGET ANALYSIS</b>",
            f"<span style='color:#94a3b8'>RTT:</span> "
            f"<b>{profile.avg_rtt_ms:.0f}ms</b> "
            f"(jitter: {profile.jitter_ms:.0f}ms) &nbsp; "
            f"<span style='color:#94a3b8'>Loss:</span> "
            f"<b>{profile.packet_loss_pct:.0f}%</b>",
            f"<span style='color:#94a3b8'>Type:</span> "
            f"{profile.connection_type} / {profile.device_type} "
            f"{'(' + profile.device_hint + ')' if profile.device_hint else ''}",
            f"<span style='color:#94a3b8'>Quality:</span> "
            f"<b>{profile.quality_score:.0f}/100</b>",
            "",
            f"<b style='color:#e040fb'>RECOMMENDATION: {rec.name}</b> "
            f"<span style='color:#6b7280'>(goal: {rec.goal})</span>",
            f"<span style='color:#94a3b8'>Modules:</span> "
            f"{' + '.join(rec.methods)}",
        ]
        for reason in rec.reasoning[:3]:
            info_lines.append(
                f"<span style='color:#6b7280'>• {reason}</span>")

        self.smart_info_label.setText("<br>".join(info_lines))
        self.smart_info_label.setStyleSheet(
            "color: #e0e0e0; font-size: 10px; padding: 6px; "
            "background: #0a0f18; border: 1px solid #1a2a3a; "
            "border-radius: 4px;")

        conf_pct = int(rec.confidence * 100)
        self.smart_confidence_bar.setValue(conf_pct)
        self.smart_confidence_bar.setFormat(
            f"Confidence: {conf_pct}% | "
            f"Effectiveness: {rec.estimated_effectiveness:.0f}%")

        self._view._apply_recommendation(rec)

    @pyqtSlot(object, object)
    def apply_and_disrupt(self, profile, rec) -> None:
        """Apply recommendation and start disruption (main thread)."""
        self.update_ui(profile, rec)

        if self._view.controller and self._view.selected_ip:
            success = self._view.controller.disrupt_device(
                self._view.selected_ip, rec.methods, rec.params)
            if success:
                self._view._disruption_timers[self._view.selected_ip] = (
                    time.time())
                log_info(
                    f"Smart disruption started on {self._view.selected_ip}: "
                    f"{rec.name} ({rec.methods})")
                self._view._refresh_device_table_status()

                self._active_session_id = self._smart_tracker.start_session(
                    profile, rec,
                    intensity=self.smart_intensity_slider.value() / 100.0)
            else:
                QMessageBox.warning(
                    self._view, "Failed",
                    f"Smart disruption failed on {self._view.selected_ip}.\n"
                    "Check admin privileges, WinDivert files, and logs.")

    @pyqtSlot(object)
    def apply_llm_result(self, result) -> None:
        """Apply LLM advisor result to the controls (main thread)."""
        self.smart_llm_input.setEnabled(True)
        if not result:
            self.smart_info_label.setText(
                "AI advisor returned no result. Try rephrasing.")
            return

        rec = DisruptionRecommendation(
            name=result.get("name", "AI Recommendation"),
            description=result.get("description", ""),
            methods=result.get("methods", []),
            params=result.get("params", {}),
            reasoning=[result.get("reasoning", "")],
            confidence=0.7,
            estimated_effectiveness=75,
        )
        self._view._apply_recommendation(rec)

        info_lines = [
            f"<b style='color:#a855f7'>AI ADVISOR: {rec.name}</b>",
            f"<span style='color:#94a3b8'>{rec.description}</span>",
            f"<span style='color:#94a3b8'>Modules:</span> "
            f"{' + '.join(rec.methods)}",
            f"<span style='color:#6b7280'>"
            f"{rec.reasoning[0] if rec.reasoning else ''}</span>",
        ]
        self.smart_info_label.setText("<br>".join(info_lines))
        self.smart_confidence_bar.setValue(70)
        self.smart_confidence_bar.setFormat(
            "AI Advisor — apply with DISRUPT button")
