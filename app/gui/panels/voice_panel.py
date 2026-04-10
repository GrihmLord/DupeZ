# app/gui/panels/voice_panel.py — Voice control panel widget
"""Extracted from ClumsyControlView._build_voice_panel and voice handler methods."""

from __future__ import annotations

import time

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox,
)
from PyQt6.QtCore import pyqtSlot

from app.logs.logger import log_info, log_error

# Voice control — optional dependency.
#
# IMPORTANT: do NOT call is_voice_available() at module import time.
# It triggers an import chain into whisper → torch, and torch's c10.dll
# can crash the interpreter with an unrecoverable access violation
# (WinError 1114) on broken installs. That also breaks PyInstaller's
# isolated analyzer. Keep this import cheap; the real probe happens
# inside VoicePanel.__init__ (and is wrapped in try/except Exception).
try:
    from app.ai.voice_control import VoiceController, VoiceConfig, is_voice_available  # noqa: F401
    _VOICE_IMPORTABLE = True
except Exception:  # noqa: BLE001 — optional dep, any failure → disabled
    _VOICE_IMPORTABLE = False

# Deferred flag — populated on first VoicePanel instantiation.
VOICE_AVAILABLE: bool = False


def _probe_voice_available() -> bool:
    """Lazy, crash-safe probe of voice availability."""
    global VOICE_AVAILABLE
    if not _VOICE_IMPORTABLE:
        VOICE_AVAILABLE = False
        return False
    try:
        VOICE_AVAILABLE = bool(is_voice_available())
    except Exception as exc:  # noqa: BLE001
        log_error(f"voice_panel: is_voice_available() raised {type(exc).__name__}: {exc}")
        VOICE_AVAILABLE = False
    return VOICE_AVAILABLE

# LLM advisor for voice commands — optional
try:
    from app.ai.llm_advisor import LLMAdvisor
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

__all__ = ["VoicePanel"]


class VoicePanel(QWidget):
    """Voice control UI: init, listen, push-to-talk, model/mic selectors."""

    def __init__(self, parent_view, parent=None) -> None:
        super().__init__(parent)
        self._view = parent_view
        self._voice_controller = None
        # Lazy probe — first panel instantiation. Crash-safe.
        _probe_voice_available()
        self._setup_ui()

    @property
    def voice_controller(self) -> Any:
        return self._voice_controller

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        voice_group = self._view._card("VOICE CONTROL")
        vl = QVBoxLayout()
        vl.setSpacing(6)

        if not VOICE_AVAILABLE:
            missing_label = QLabel("Install sounddevice + openai-whisper to enable")
            missing_label.setStyleSheet(
                "color: #6b7280; font-size: 10px; font-style: italic;")
            vl.addWidget(missing_label)
            voice_group.setLayout(vl)
            layout.addWidget(voice_group)
            return

        # Status row
        status_row = QHBoxLayout()
        self.voice_status_label = QLabel("Voice: Not initialized")
        self.voice_status_label.setStyleSheet(self._status_qss("#94a3b8"))
        status_row.addWidget(self.voice_status_label, 1)
        vl.addLayout(status_row)

        # Controls row
        ctrl_row = QHBoxLayout()

        self.btn_voice_init = self._view._make_btn("INIT", "#e040fb", "#0a1628", h=28)
        self.btn_voice_init.clicked.connect(self._on_voice_init)
        ctrl_row.addWidget(self.btn_voice_init)

        self.btn_voice_listen = self._view._make_btn(
            "LISTEN", "#00ff88", "#0a1628", h=28,
            tip="Toggle continuous listening — say 'stop listening' to deactivate",
            enabled=False)
        self.btn_voice_listen.clicked.connect(self._on_voice_listen_toggle)
        ctrl_row.addWidget(self.btn_voice_listen)

        self.btn_voice_ptt = self._view._make_btn(
            "PTT", "#6b7280", "#0a1628", h=28,
            tip="Push-to-talk: hold to record, release to transcribe",
            enabled=False)
        self.btn_voice_ptt.pressed.connect(self._on_voice_ptt_press)
        self.btn_voice_ptt.released.connect(self._on_voice_ptt_release)
        ctrl_row.addWidget(self.btn_voice_ptt)

        vl.addLayout(ctrl_row)

        # Model + Mic selectors
        for attr, label_text, items in [
            ("voice_model_combo", "MODEL:", [("tiny",), ("base",), ("small",)]),
            ("voice_mic_combo", "MIC:", [("System Default", None)]),
        ]:
            row = QHBoxLayout()
            row.addWidget(self._view._lbl(label_text, bold=True, w=48))
            combo = QComboBox()
            for item in items:
                combo.addItem(*item) if len(item) > 1 else combo.addItem(item[0])
            combo.setStyleSheet(self._view._COMBO_QSS)
            setattr(self, attr, combo)
            row.addWidget(combo, 1)
            vl.addLayout(row)

        voice_group.setLayout(vl)
        layout.addWidget(voice_group)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _on_voice_init(self) -> None:
        """Initialize the voice engine."""
        if not VOICE_AVAILABLE:
            return

        model_name = self.voice_model_combo.currentText()
        self.voice_status_label.setText(f"Loading {model_name} model...")
        self.voice_status_label.setStyleSheet(self._status_qss("#e040fb"))
        self.btn_voice_init.setEnabled(False)

        advisor = LLMAdvisor() if _LLM_AVAILABLE else None
        config = VoiceConfig(model_name=model_name)

        mic_data = self.voice_mic_combo.currentData()
        if mic_data is not None:
            config.input_device = mic_data

        self._voice_controller = VoiceController(
            advisor=advisor,
            on_command=self._on_voice_command,
            on_status=self._on_voice_status_update,
            on_listening_changed=self._on_voice_listening_changed,
            config=config,
        )

        self._voice_controller.initialize(
            callback=lambda ok: self._view._invoke_main(
                "_panel_voice_init_done", ok))

    @pyqtSlot(object)
    def voice_init_done(self, ok) -> None:
        self.btn_voice_init.setEnabled(True)
        if ok:
            self.btn_voice_listen.setEnabled(True)
            self.btn_voice_ptt.setEnabled(True)
            self.voice_status_label.setText(
                "Voice ready — click LISTEN or hold PTT")
            self.voice_status_label.setStyleSheet(self._status_qss("#00ff88"))

            if self._voice_controller:
                devices = self._voice_controller.list_input_devices()
                self.voice_mic_combo.clear()
                self.voice_mic_combo.addItem("System Default", None)
                for dev in devices:
                    self.voice_mic_combo.addItem(dev["name"], dev["index"])
        else:
            self.voice_status_label.setText("Voice init failed — check logs")
            self.voice_status_label.setStyleSheet(self._status_qss("#ff4444"))

    def _on_voice_listen_toggle(self) -> None:
        if not self._voice_controller:
            return
        self._voice_controller.toggle_listening()

    def _on_voice_listening_changed(self, listening: bool) -> None:
        self._view._invoke_main("_panel_voice_listening_changed", listening)

    @pyqtSlot(object)
    def update_listen_btn(self, listening) -> None:
        if not hasattr(self, 'btn_voice_listen'):
            return
        if listening:
            self.btn_voice_listen.setText("LISTENING")
            self.btn_voice_listen.setStyleSheet(
                self._view._btn_style("#ff4444", "#0a1628"))
            self.voice_status_label.setText(
                "Listening... say 'stop listening' to deactivate")
            self.voice_status_label.setStyleSheet(self._status_qss("#ff4444"))
        else:
            self.btn_voice_listen.setText("LISTEN")
            self.btn_voice_listen.setStyleSheet(
                self._view._btn_style("#00ff88", "#0a1628"))
            self.voice_status_label.setText(
                "Voice ready — click LISTEN or hold PTT")
            self.voice_status_label.setStyleSheet(self._status_qss("#00ff88"))

    def _on_voice_ptt_press(self) -> None:
        if self._voice_controller:
            self._voice_controller.push_to_talk_press()

    def _on_voice_ptt_release(self) -> None:
        if self._voice_controller:
            self._voice_controller.push_to_talk_release()

    def _on_voice_command(self, config: dict) -> None:
        self._view._invoke_main("_panel_voice_apply_command", config)

    @pyqtSlot(object)
    def apply_command(self, config) -> None:
        """Apply voice command on the main thread (Qt-safe)."""
        action = config.get("action")
        if action == "stop":
            self._view._on_stop()
            return
        if action == "start":
            self._view._on_disrupt()
            return

        methods = config.get("methods", [])
        params = config.get("params", {})
        if methods and self._view.selected_ip and self._view.controller:
            log_info(f"VoiceCommand: applying {config.get('name', 'voice config')}")
            self._view.controller.disrupt_device(
                self._view.selected_ip, methods, params)
            self._view._disruption_timers[self._view.selected_ip] = time.time()
            self._view._refresh_device_table_status()

    def _on_voice_status_update(self, msg: str) -> None:
        self._view._invoke_main("_panel_voice_set_status", msg)

    @pyqtSlot(object)
    def set_status(self, msg) -> None:
        if hasattr(self, 'voice_status_label'):
            self.voice_status_label.setText(msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _status_qss(color: str) -> str:
        return (f"color: {color}; font-size: 10px; padding: 4px 8px; "
                f"background: rgba(8,12,22,0.6); border: 1px solid {color}; "
                f"border-radius: 6px; font-weight: 600;")
