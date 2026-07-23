# app/gui/panels/clumsy_advanced_panel.py — full bundled-Clumsy controls
"""User-facing controls for fork settings not represented by module sliders.

The filter field is an additional predicate only.  The firewall runtime always
ANDs it with DupeZ's exact validated target scope, so the default ``true`` means
"no extra narrowing" rather than "capture every device".
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.clumsy_controls import (
    BANDWIDTH_KB,
    BANDWIDTH_MB,
    CLUMSY_DIRECTION_KEYS,
    CLUMSY_METHOD_LABELS,
    TRIGGER_TIMER,
    TRIGGER_TOGGLE,
    normalize_additional_filter,
    normalize_clumsy_label,
)
from app.logs.logger import log_error

__all__ = ["ClumsyAdvancedPanel"]


class ClumsyAdvancedPanel(QGroupBox):
    """Expose every remaining controllable Kalirenegade 0.3.4 setting."""

    settings_changed = pyqtSignal()

    def __init__(
        self,
        clumsy_view: Any,
        parent: Optional[QWidget] = None,
        *,
        settings: Optional[Any] = None,
    ) -> None:
        super().__init__("CLUMSY ADVANCED CONTROLS", parent)
        self._clumsy_view = clumsy_view
        self._settings = settings or QSettings("DupeZ", "DupeZ")
        self._event_panel: Optional[Any] = None
        self._direction_checks: dict[str, tuple[QCheckBox, QCheckBox]] = {}
        self._syncing_global_direction = False

        self.setStyleSheet(self._group_qss())
        self._build_ui()
        self._load_settings()
        self._install_param_adapter()
        self._wire_global_direction()
        self._sync_trigger_widgets()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(7)

        notice = QLabel(
            "The additional filter defaults to true. DupeZ always combines it "
            "with the selected private target's mandatory IP/port scope; it can "
            "never replace or broaden that scope."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet(self._muted_qss())
        layout.addWidget(notice)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Additional filter"))
        self.filter_predicate = QLineEdit("true")
        self.filter_predicate.setPlaceholderText("true")
        self.filter_predicate.setToolTip(
            "A bounded WinDivert predicate ANDed with the mandatory exact-target "
            "filter. Leave as true for no additional narrowing."
        )
        filter_row.addWidget(self.filter_predicate, 2)
        filter_row.addWidget(QLabel("Filter preset"))
        self.filter_name = QLineEdit("DupeZ Target")
        self.filter_name.setMaxLength(48)
        filter_row.addWidget(self.filter_name, 1)
        layout.addLayout(filter_row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Function preset"))
        self.function_preset_name = QLineEdit("DupeZ")
        self.function_preset_name.setMaxLength(48)
        preset_row.addWidget(self.function_preset_name, 1)

        preset_row.addWidget(QLabel("Bandwidth unit"))
        self.bandwidth_unit = QComboBox()
        self.bandwidth_unit.addItem("KB/s", BANDWIDTH_KB)
        self.bandwidth_unit.addItem("MB/s", BANDWIDTH_MB)
        preset_row.addWidget(self.bandwidth_unit)
        layout.addLayout(preset_row)

        trigger_row = QHBoxLayout()
        trigger_row.addWidget(QLabel("Trigger mode"))
        self.trigger_mode = QComboBox()
        self.trigger_mode.addItem("Toggle — run until stopped", TRIGGER_TOGGLE)
        self.trigger_mode.addItem("Timer — auto-stop", TRIGGER_TIMER)
        self.trigger_mode.currentIndexChanged.connect(self._sync_trigger_widgets)
        trigger_row.addWidget(self.trigger_mode, 1)

        trigger_row.addWidget(QLabel("Timer"))
        self.timer_seconds = QSpinBox()
        self.timer_seconds.setRange(1, 60)
        self.timer_seconds.setValue(3)
        self.timer_seconds.setSuffix(" s")
        self.timer_seconds.valueChanged.connect(self._sync_event_duration)
        trigger_row.addWidget(self.timer_seconds)
        layout.addLayout(trigger_row)

        direction_group = QGroupBox("PER-MODULE DIRECTION")
        direction_layout = QGridLayout(direction_group)
        direction_layout.addWidget(QLabel("Module"), 0, 0)
        direction_layout.addWidget(QLabel("Inbound"), 0, 1)
        direction_layout.addWidget(QLabel("Outbound"), 0, 2)

        for row, (method, label) in enumerate(
            CLUMSY_METHOD_LABELS.items(),
            start=1,
        ):
            direction_layout.addWidget(QLabel(label), row, 0)
            inbound = QCheckBox()
            outbound = QCheckBox()
            inbound.setChecked(True)
            outbound.setChecked(True)
            inbound.toggled.connect(
                lambda _checked, m=method, changed="inbound":
                self._ensure_direction(m, changed)
            )
            outbound.toggled.connect(
                lambda _checked, m=method, changed="outbound":
                self._ensure_direction(m, changed)
            )
            direction_layout.addWidget(inbound, row, 1)
            direction_layout.addWidget(outbound, row, 2)
            self._direction_checks[method] = (inbound, outbound)

        layout.addWidget(direction_group)

        rst_row = QHBoxLayout()
        self.rst_next_on_start = QCheckBox(
            "Arm RST next eligible TCP packet once after Start"
        )
        self.rst_next_on_start.setToolTip(
            "Requires Set TCP RST to be enabled. The fork consumes exactly one "
            "eligible TCP packet, then clears the one-shot counter."
        )
        rst_row.addWidget(self.rst_next_on_start, 1)
        self.rst_now_button = QPushButton("RST NEXT PACKET NOW")
        self.rst_now_button.clicked.connect(self._trigger_rst_next_packet)
        rst_row.addWidget(self.rst_now_button)
        layout.addLayout(rst_row)

        self.status_label = QLabel(
            "Advanced values apply to manual DISRUPT, Smart Ops, saved events, "
            "and the elevated helper."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(self._muted_qss())
        layout.addWidget(self.status_label)

        for widget in (
            self.filter_predicate,
            self.filter_name,
            self.function_preset_name,
        ):
            widget.editingFinished.connect(self._persist_settings)
        self.bandwidth_unit.currentIndexChanged.connect(self._persist_settings)
        self.trigger_mode.currentIndexChanged.connect(self._persist_settings)
        self.timer_seconds.valueChanged.connect(self._persist_settings)
        self.rst_next_on_start.toggled.connect(self._persist_settings)
        for inbound, outbound in self._direction_checks.values():
            inbound.toggled.connect(self._persist_settings)
            outbound.toggled.connect(self._persist_settings)

    def bind_event_panel(self, event_panel: Any) -> None:
        """Keep queued-event duration coherent with fork Timer mode."""

        self._event_panel = event_panel
        self._sync_event_duration()

    def _settings_value(self, key: str, default: Any) -> Any:
        try:
            return self._settings.value(f"clumsy_advanced/{key}", default)
        except Exception:
            return default

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _load_settings(self) -> None:
        try:
            predicate = normalize_additional_filter(
                self._settings_value("filter_predicate", "true")
            )
        except ValueError:
            predicate = "true"
        self.filter_predicate.setText(predicate)
        self.filter_name.setText(normalize_clumsy_label(
            self._settings_value("filter_name", "DupeZ Target"),
            default="DupeZ Target",
        ))
        self.function_preset_name.setText(normalize_clumsy_label(
            self._settings_value("function_preset_name", "DupeZ"),
            default="DupeZ",
        ))

        unit = str(self._settings_value("bandwidth_unit", BANDWIDTH_KB)).lower()
        index = self.bandwidth_unit.findData(
            unit if unit in {BANDWIDTH_KB, BANDWIDTH_MB} else BANDWIDTH_KB
        )
        self.bandwidth_unit.setCurrentIndex(max(0, index))

        mode = str(self._settings_value("trigger_mode", TRIGGER_TOGGLE)).lower()
        index = self.trigger_mode.findData(
            mode if mode in {TRIGGER_TOGGLE, TRIGGER_TIMER} else TRIGGER_TOGGLE
        )
        self.trigger_mode.setCurrentIndex(max(0, index))
        try:
            seconds = int(self._settings_value("timer_seconds", 3))
        except (TypeError, ValueError):
            seconds = 3
        self.timer_seconds.setValue(max(1, min(60, seconds)))
        self.rst_next_on_start.setChecked(self._as_bool(
            self._settings_value("rst_next_packet", False)
        ))

        for method, (inbound, outbound) in self._direction_checks.items():
            direction = str(self._settings_value(
                f"direction/{method}", "both"
            )).lower()
            inbound.setChecked(direction in {"both", "inbound"})
            outbound.setChecked(direction in {"both", "outbound"})
            if not inbound.isChecked() and not outbound.isChecked():
                inbound.setChecked(True)
                outbound.setChecked(True)

    def _persist_settings(self, *_args: Any) -> None:
        try:
            predicate = normalize_additional_filter(self.filter_predicate.text())
            self.filter_predicate.setText(predicate)
            self.filter_predicate.setStyleSheet("")
            self.status_label.setText(
                "Advanced settings saved; mandatory target scope remains active."
            )
        except ValueError as exc:
            self.filter_predicate.setStyleSheet("border: 1px solid #ff5555;")
            self.status_label.setText(str(exc))
            return

        values = {
            "filter_predicate": predicate,
            "filter_name": normalize_clumsy_label(
                self.filter_name.text(), default="DupeZ Target"
            ),
            "function_preset_name": normalize_clumsy_label(
                self.function_preset_name.text(), default="DupeZ"
            ),
            "bandwidth_unit": str(
                self.bandwidth_unit.currentData() or BANDWIDTH_KB
            ),
            "trigger_mode": str(
                self.trigger_mode.currentData() or TRIGGER_TOGGLE
            ),
            "timer_seconds": self.timer_seconds.value(),
            "rst_next_packet": self.rst_next_on_start.isChecked(),
        }
        for method in self._direction_checks:
            values[f"direction/{method}"] = self._direction_for(method)
        try:
            for key, value in values.items():
                self._settings.setValue(f"clumsy_advanced/{key}", value)
            if hasattr(self._settings, "sync"):
                self._settings.sync()
        except Exception as exc:
            log_error(f"Could not persist Clumsy advanced settings: {exc}")
        self.settings_changed.emit()

    def _direction_for(self, method: str) -> str:
        inbound, outbound = self._direction_checks[method]
        if inbound.isChecked() and outbound.isChecked():
            return "both"
        if inbound.isChecked():
            return "inbound"
        return "outbound"

    def _ensure_direction(self, method: str, changed: str) -> None:
        inbound, outbound = self._direction_checks[method]
        if inbound.isChecked() or outbound.isChecked():
            return
        selected = inbound if changed == "inbound" else outbound
        selected.blockSignals(True)
        try:
            selected.setChecked(True)
        finally:
            selected.blockSignals(False)

    def _wire_global_direction(self) -> None:
        inbound = getattr(self._clumsy_view, "dir_inbound", None)
        outbound = getattr(self._clumsy_view, "dir_outbound", None)
        if inbound is None or outbound is None:
            return

        # Match the fork's defaults: both directions enabled.
        inbound.blockSignals(True)
        outbound.blockSignals(True)
        try:
            inbound.setChecked(True)
            outbound.setChecked(True)
        finally:
            inbound.blockSignals(False)
            outbound.blockSignals(False)

        inbound.toggled.connect(self._sync_from_global_direction)
        outbound.toggled.connect(self._sync_from_global_direction)

    def _sync_from_global_direction(self, *_args: Any) -> None:
        if self._syncing_global_direction:
            return
        inbound_global = getattr(self._clumsy_view, "dir_inbound", None)
        outbound_global = getattr(self._clumsy_view, "dir_outbound", None)
        if inbound_global is None or outbound_global is None:
            return
        want_in = inbound_global.isChecked()
        want_out = outbound_global.isChecked()
        if not want_in and not want_out:
            outbound_global.setChecked(True)
            want_out = True

        self._syncing_global_direction = True
        try:
            for inbound, outbound in self._direction_checks.values():
                inbound.setChecked(want_in)
                outbound.setChecked(want_out)
        finally:
            self._syncing_global_direction = False
        self._persist_settings()

    def _sync_trigger_widgets(self, *_args: Any) -> None:
        timer_mode = self.trigger_mode.currentData() == TRIGGER_TIMER
        self.timer_seconds.setEnabled(timer_mode)
        self._sync_event_duration()

    def _sync_event_duration(self, *_args: Any) -> None:
        if (
            self._event_panel is not None
            and self.trigger_mode.currentData() == TRIGGER_TIMER
        ):
            self._event_panel.duration_spin.setValue(
                float(self.timer_seconds.value())
            )

    def augment_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add validated advanced values to a fresh engine parameter map."""

        routed = dict(params or {})
        routed["_clumsy_filter_predicate"] = normalize_additional_filter(
            self.filter_predicate.text()
        )
        routed["_clumsy_filter_name"] = normalize_clumsy_label(
            self.filter_name.text(), default="DupeZ Target"
        )
        routed["_clumsy_function_preset_name"] = normalize_clumsy_label(
            self.function_preset_name.text(), default="DupeZ"
        )
        routed["_clumsy_trigger_mode"] = str(
            self.trigger_mode.currentData() or TRIGGER_TOGGLE
        )
        routed["_clumsy_timer_seconds"] = self.timer_seconds.value()
        routed["bandwidth_size"] = str(
            self.bandwidth_unit.currentData() or BANDWIDTH_KB
        )
        routed["_clumsy_rst_next_packet"] = (
            self.rst_next_on_start.isChecked()
        )

        directions = []
        for method, parameter in CLUMSY_DIRECTION_KEYS.items():
            direction = self._direction_for(method)
            routed[parameter] = direction
            if method == "corrupt":
                routed["corrupt_direction"] = direction
            directions.append(direction)
        routed["direction"] = (
            directions[0]
            if directions and len(set(directions)) == 1
            else "both"
        )
        return routed

    def _install_param_adapter(self) -> None:
        view = self._clumsy_view
        original = view._collect_params

        def collect_with_advanced_controls() -> dict[str, Any]:
            return self.augment_params(original())

        view._clumsy_advanced_param_adapter = self
        view._collect_params = collect_with_advanced_controls

    def _trigger_rst_next_packet(self) -> None:
        targets = list(self._clumsy_view._get_targets())
        if len(targets) != 1:
            QMessageBox.warning(
                self,
                "One Target Required",
                "Select exactly one authorized private target.",
            )
            return
        controller = getattr(self._clumsy_view, "controller", None)
        manager = getattr(controller, "disruption_manager", None)
        if manager is None:
            manager = getattr(controller, "_disruption_manager", None)
        hotkey = getattr(manager, "hotkey_trigger", None)
        if not callable(hotkey):
            QMessageBox.warning(
                self,
                "Unavailable",
                "The active firewall architecture does not expose the "
                "authenticated Clumsy control action.",
            )
            return
        accepted = bool(hotkey(
            "clumsy_rst_next_packet",
            {"target_ip": targets[0]},
        ))
        self.status_label.setText(
            "RST one-shot armed for the next eligible target TCP packet."
            if accepted
            else "RST one-shot was refused; start explicit Clumsy with Set TCP "
            "RST enabled first."
        )

    @staticmethod
    def _group_qss() -> str:
        return (
            "QGroupBox { color: #00f0ff; font-weight: 700; "
            "border: 1px solid rgba(0,240,255,0.22); border-radius: 8px; "
            "margin-top: 12px; padding: 12px 8px 8px 8px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; "
            "padding: 0 6px; }"
        )

    @staticmethod
    def _muted_qss() -> str:
        return "color: #94a3b8; font-size: 10px; padding: 2px;"
