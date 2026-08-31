"""Accessible editor for bounded, authorized cut-chain configurations."""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.builtin_presets import BUILTIN_PRESETS
from app.core.cut_chain import (
    MAX_CHAIN_STAGES,
    MAX_CHAIN_TIMEOUT_SECONDS,
    MAX_GATE_PACKETS,
    MAX_GATE_SECONDS,
    ChainConfig,
    ChainValidationError,
    Gate,
    Stage,
    load_chain_config,
    save_chain_config,
)
from app.core.preset_store import list_custom_presets, validate_preset
from app.core.safety_policy import SafetyPolicy

__all__ = ["CutChainConfiguratorDialog"]


_GATE_LABELS = (
    ("Wait for a duration", "time"),
    ("Wait until severed", "severed"),
    ("Wait until connected", "connected"),
    ("Wait for packet count", "packets"),
)

_FAILURE_LABELS = (
    ("Stop and release on any failure", "halt"),
    ("Release failed stage and continue", "continue"),
)


class CutChainConfiguratorDialog(QDialog):
    """Build one validated multi-stage sequence without executing it."""

    configuration_ready = pyqtSignal(object)

    def __init__(
        self,
        target_ip: str = "",
        *,
        config: Optional[ChainConfig] = None,
        safety_policy: Optional[SafetyPolicy] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._safety_policy = safety_policy
        self._selected_config: Optional[ChainConfig] = None
        self._preset_definitions = self._load_preset_definitions()
        self.setWindowTitle("Cut-Chain Configurator")
        self.setModal(True)
        self.setMinimumSize(860, 540)
        self.resize(940, 600)
        self.setAccessibleName("Cut-chain configurator")
        self.setAccessibleDescription(
            "Creates a bounded sequence of diagnostic presets for one "
            "owned or explicitly authorized private-network target."
        )
        self._build_ui()
        if config is None:
            self.target_edit.setText(target_ip)
            self.add_stage()
        else:
            self._load_config_into_form(config)
        self.scope_checkbox.setChecked(False)
        self._refresh_summary()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Multi-stage connection diagnostic")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        title.setAccessibleName("Cut-chain configurator title")
        root.addWidget(title)

        scope_notice = QLabel(
            "Authorized scope only: choose one private IPv4 device that you "
            "own or have explicit permission to test. Every stage is bounded, "
            "released before the next stage, and rechecked by the controller's "
            "configured safety policy before execution."
        )
        scope_notice.setWordWrap(True)
        scope_notice.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        scope_notice.setAccessibleName("Authorized-use and release policy")
        root.addWidget(scope_notice)

        form = QFormLayout()
        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText("192.168.1.50")
        self.target_edit.setClearButtonEnabled(True)
        self.target_edit.setAccessibleName("Authorized target IPv4 address")
        self.target_edit.setAccessibleDescription(
            "A private or link-local IPv4 address inside the configured "
            "safety scope. Public targets are rejected."
        )
        form.addRow("Target device:", self.target_edit)

        self.failure_combo = QComboBox()
        for label, policy in _FAILURE_LABELS:
            self.failure_combo.addItem(label, policy)
        self.failure_combo.setAccessibleName("Stage failure policy")
        self.failure_combo.setAccessibleDescription(
            "Stop is the safe default. Continue always releases a failed "
            "stage before attempting the next one. Rewind is not supported."
        )
        form.addRow("If a stage fails:", self.failure_combo)

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.1, MAX_CHAIN_TIMEOUT_SECONDS)
        self.timeout_spin.setDecimals(1)
        self.timeout_spin.setSingleStep(5.0)
        self.timeout_spin.setValue(60.0)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setAccessibleName("Whole-chain automatic release time")
        self.timeout_spin.setAccessibleDescription(
            "Hard upper deadline for the entire sequence. The application "
            "safety policy may shorten this value."
        )
        form.addRow("Release deadline:", self.timeout_spin)
        root.addLayout(form)

        table_label = QLabel("Stages (each stage applies one preset)")
        table_label.setAccessibleName("Cut-chain stage editor heading")
        root.addWidget(table_label)

        self.stage_table = QTableWidget(0, 4)
        self.stage_table.setHorizontalHeaderLabels([
            "Preset",
            "Advance gate",
            "Duration / timeout",
            "Packet count",
        ])
        self.stage_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.stage_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.stage_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.stage_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.stage_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.stage_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.stage_table.setAccessibleName("Ordered cut-chain stages")
        self.stage_table.setAccessibleDescription(
            "Select a row to remove it or move it earlier or later. Only "
            "known preset actions and gate types are available."
        )
        root.addWidget(self.stage_table, 1)

        stage_buttons = QHBoxLayout()
        self.add_button = QPushButton("Add Stage")
        self.remove_button = QPushButton("Remove Stage")
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        for button, accessible_name in (
            (self.add_button, "Add a cut-chain stage"),
            (self.remove_button, "Remove the selected cut-chain stage"),
            (self.up_button, "Move selected stage earlier"),
            (self.down_button, "Move selected stage later"),
        ):
            button.setAccessibleName(accessible_name)
            stage_buttons.addWidget(button)
        stage_buttons.addStretch(1)
        self.load_button = QPushButton("Load Chain…")
        self.save_button = QPushButton("Save Chain…")
        self.load_button.setAccessibleName("Load a cut-chain JSON file")
        self.save_button.setAccessibleName("Save this cut-chain as JSON")
        stage_buttons.addWidget(self.load_button)
        stage_buttons.addWidget(self.save_button)
        root.addLayout(stage_buttons)

        self.add_button.clicked.connect(self.add_stage)
        self.remove_button.clicked.connect(self._remove_selected_stage)
        self.up_button.clicked.connect(lambda: self._move_selected_stage(-1))
        self.down_button.clicked.connect(lambda: self._move_selected_stage(1))
        self.load_button.clicked.connect(self._on_load)
        self.save_button.clicked.connect(self._on_save)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setAccessibleName("Cut-chain configuration summary")
        root.addWidget(self.summary_label)

        self.scope_checkbox = QCheckBox(
            "I confirm this target is mine or explicitly authorized for "
            "active network testing"
        )
        self.scope_checkbox.setAccessibleName(
            "Confirm owned or explicitly authorized target"
        )
        self.scope_checkbox.setAccessibleDescription(
            "Required before the configuration can be handed to the "
            "controller for execution. It is cleared after every file load."
        )
        root.addWidget(self.scope_checkbox)

        buttons = QDialogButtonBox()
        self.use_button = buttons.addButton(
            "Use Configuration",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        cancel_button = buttons.addButton(
            "Cancel",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.use_button.setEnabled(False)
        self.use_button.setAccessibleName("Use validated cut-chain configuration")
        cancel_button.setAccessibleName("Cancel cut-chain configuration")
        self.scope_checkbox.toggled.connect(self.use_button.setEnabled)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _load_preset_definitions() -> dict[str, dict]:
        definitions = {
            name: deepcopy(definition)
            for name, definition in BUILTIN_PRESETS.items()
            if definition.get("methods")
        }
        try:
            custom_presets = list_custom_presets()
        except Exception:
            custom_presets = []
        for preset in custom_presets:
            try:
                validate_preset(preset)
            except ValueError:
                continue
            if preset.name in definitions or not preset.methods:
                continue
            definitions[preset.name] = {
                "methods": deepcopy(preset.methods),
                "params": deepcopy(preset.params),
            }
        return definitions

    def _preset_names(self) -> list[str]:
        return list(self._preset_definitions)

    def add_stage(
        self,
        _checked: bool = False,
        *,
        stage: Optional[Stage] = None,
    ) -> None:
        if self.stage_table.rowCount() >= MAX_CHAIN_STAGES:
            QMessageBox.warning(
                self,
                "Stage Limit",
                f"A chain may contain at most {MAX_CHAIN_STAGES} stages.",
            )
            return
        stage = stage or Stage(
            preset="Lag",
            gate=Gate("time", seconds=2.0),
        )
        row = self.stage_table.rowCount()
        self.stage_table.insertRow(row)

        preset_combo = QComboBox()
        preset_combo.addItems(self._preset_names())
        preset_combo.setCurrentText(stage.preset)
        # Preserve validated advanced overrides when a chain is loaded. If the
        # operator changes the preset, the old preset's overrides are dropped
        # instead of being applied to an unrelated action.
        preset_combo._loaded_preset = stage.preset
        preset_combo._chain_methods = deepcopy(stage.methods)
        preset_combo._chain_params = deepcopy(stage.params)
        preset_combo._chain_verify_method = stage.verify_method
        preset_combo._chain_verify_minimum = stage.verify_minimum
        preset_combo.setAccessibleName(f"Stage {row + 1} preset")
        self.stage_table.setCellWidget(row, 0, preset_combo)

        gate_combo = QComboBox()
        for label, kind in _GATE_LABELS:
            gate_combo.addItem(label, kind)
        gate_index = gate_combo.findData(stage.gate.kind)
        if gate_index >= 0:
            gate_combo.setCurrentIndex(gate_index)
        gate_combo.setAccessibleName(f"Stage {row + 1} advance gate")
        self.stage_table.setCellWidget(row, 1, gate_combo)

        seconds_spin = QDoubleSpinBox()
        seconds_spin.setRange(0.0, MAX_GATE_SECONDS)
        seconds_spin.setDecimals(2)
        seconds_spin.setSingleStep(0.5)
        seconds_spin.setValue(float(stage.gate.seconds))
        seconds_spin.setSuffix(" s")
        seconds_spin.setAccessibleName(
            f"Stage {row + 1} duration or timeout seconds"
        )
        self.stage_table.setCellWidget(row, 2, seconds_spin)

        packets_spin = QSpinBox()
        packets_spin.setRange(1, MAX_GATE_PACKETS)
        packets_spin.setValue(max(1, int(stage.gate.packets or 100)))
        packets_spin.setGroupSeparatorShown(True)
        packets_spin.setAccessibleName(f"Stage {row + 1} packet threshold")
        self.stage_table.setCellWidget(row, 3, packets_spin)

        def sync_controls() -> None:
            kind = gate_combo.currentData()
            packets_spin.setEnabled(kind == "packets")
            if kind != "time" and seconds_spin.value() <= 0:
                seconds_spin.setValue(30.0)
            packets_spin.setAccessibleDescription(
                "Enabled only for a packet-count gate."
            )

        gate_combo.currentIndexChanged.connect(sync_controls)
        sync_controls()
        self.stage_table.selectRow(row)
        self._refresh_summary()

    def _stage_at(self, row: int) -> Stage:
        preset = self.stage_table.cellWidget(row, 0)
        gate = self.stage_table.cellWidget(row, 1)
        seconds = self.stage_table.cellWidget(row, 2)
        packets = self.stage_table.cellWidget(row, 3)
        if not isinstance(preset, QComboBox) or not isinstance(gate, QComboBox):
            raise ChainValidationError(f"stage {row + 1} editor is incomplete")
        if not isinstance(seconds, QDoubleSpinBox) or not isinstance(
            packets, QSpinBox
        ):
            raise ChainValidationError(f"stage {row + 1} editor is incomplete")
        kind = str(gate.currentData())
        preset_name = preset.currentText()
        unchanged = preset_name == getattr(preset, "_loaded_preset", None)
        selected_definition = self._preset_definitions.get(preset_name, {})
        custom_methods = (
            deepcopy(selected_definition.get("methods"))
            if preset_name not in BUILTIN_PRESETS
            else None
        )
        custom_params = (
            deepcopy(selected_definition.get("params"))
            if preset_name not in BUILTIN_PRESETS
            else None
        )
        return Stage(
            action="apply_preset",
            preset=preset_name,
            methods=(
                deepcopy(getattr(preset, "_chain_methods", None))
                if unchanged
                else custom_methods
            ),
            params=(
                deepcopy(getattr(preset, "_chain_params", None))
                if unchanged
                else custom_params
            ),
            gate=Gate(
                kind=kind,
                seconds=float(seconds.value()),
                packets=int(packets.value()) if kind == "packets" else 0,
            ),
            verify_method=(
                getattr(preset, "_chain_verify_method", None)
                if unchanged
                else None
            ),
            verify_minimum=(
                int(getattr(preset, "_chain_verify_minimum", 1))
                if unchanged
                else 1
            ),
        )

    def _remove_selected_stage(self) -> None:
        row = self.stage_table.currentRow()
        if row < 0:
            return
        if self.stage_table.rowCount() == 1:
            QMessageBox.information(
                self,
                "Stage Required",
                "A chain must keep at least one stage.",
            )
            return
        self.stage_table.removeRow(row)
        self.stage_table.selectRow(min(row, self.stage_table.rowCount() - 1))
        self._refresh_summary()

    def _move_selected_stage(self, offset: int) -> None:
        row = self.stage_table.currentRow()
        destination = row + offset
        if row < 0 or not 0 <= destination < self.stage_table.rowCount():
            return
        stages = [
            self._stage_at(index)
            for index in range(self.stage_table.rowCount())
        ]
        stages[row], stages[destination] = stages[destination], stages[row]
        self._replace_stages(stages)
        self.stage_table.selectRow(destination)

    def _replace_stages(self, stages: list[Stage]) -> None:
        self.stage_table.setRowCount(0)
        for stage in stages:
            self.add_stage(stage=stage)
        self._refresh_summary()

    def _build_config(self, *, require_acknowledgement: bool) -> ChainConfig:
        if require_acknowledgement and not self.scope_checkbox.isChecked():
            raise ChainValidationError(
                "Confirm the owned-or-authorized target scope first."
            )
        stages = [
            self._stage_at(row)
            for row in range(self.stage_table.rowCount())
        ]
        config = ChainConfig(
            target_ip=self.target_edit.text().strip(),
            stages=stages,
            on_failure=str(self.failure_combo.currentData()),
            global_timeout_s=float(self.timeout_spin.value()),
        )
        if self._safety_policy is not None:
            try:
                self._safety_policy.validate_target(config.target_ip)
            except ValueError as exc:
                raise ChainValidationError(
                    "Target is outside the configured safety scope."
                ) from exc
        return config

    def selected_config(self) -> Optional[ChainConfig]:
        """Return an isolated accepted configuration, if one exists."""
        return deepcopy(self._selected_config)

    def _load_config_into_form(self, config: ChainConfig) -> None:
        # Round-trip through public construction validation before changing UI.
        validated = deepcopy(config)
        ChainConfig(
            target_ip=validated.target_ip,
            stages=validated.stages,
            on_failure=validated.on_failure,
            global_timeout_s=validated.global_timeout_s,
            common_params=validated.common_params,
            disrupt_kwargs=validated.disrupt_kwargs,
        )
        self.target_edit.setText(validated.target_ip)
        policy_index = self.failure_combo.findData(validated.on_failure)
        self.failure_combo.setCurrentIndex(max(0, policy_index))
        self.timeout_spin.setValue(float(validated.global_timeout_s))
        self._replace_stages(list(validated.stages))
        self.scope_checkbox.setChecked(False)
        self._selected_config = None
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        count = self.stage_table.rowCount()
        noun = "stage" if count == 1 else "stages"
        self.summary_label.setText(
            f"{count} {noun}; stages release between transitions. "
            "Saving does not execute traffic changes."
        )

    def _on_save(self) -> None:
        try:
            config = self._build_config(require_acknowledgement=False)
        except ChainValidationError as exc:
            QMessageBox.warning(self, "Invalid Chain", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Cut Chain",
            "connection-diagnostic.dupez-chain.json",
            "DupeZ Cut Chain (*.json)",
        )
        if not path:
            return
        try:
            save_chain_config(config, path)
        except ChainValidationError:
            QMessageBox.critical(
                self,
                "Save Failed",
                "The chain was not saved. Check the destination and try again.",
            )
            return
        QMessageBox.information(self, "Chain Saved", "The chain was saved.")

    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Cut Chain",
            "",
            "DupeZ Cut Chain (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            config = load_chain_config(path)
            self._load_config_into_form(config)
        except ChainValidationError as exc:
            QMessageBox.warning(self, "Load Failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Chain Loaded",
            "Review the target and stages, then confirm authorization again.",
        )

    def _on_accept(self) -> None:
        try:
            config = self._build_config(require_acknowledgement=True)
        except ChainValidationError as exc:
            QMessageBox.warning(self, "Invalid Chain", str(exc))
            return
        self._selected_config = deepcopy(config)
        self.configuration_ready.emit(deepcopy(config))
        self.accept()
