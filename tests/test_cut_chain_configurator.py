"""Strict schema, persistence, failure-policy, and Qt configurator contracts."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QComboBox, QSpinBox

from app.core.cut_chain import (
    CHAIN_SCHEMA,
    MAX_CHAIN_JSON_BYTES,
    ChainConfig,
    ChainValidationError,
    CutChainRunner,
    Gate,
    Stage,
    chain_config_from_dict,
    chain_config_to_dict,
    load_chain_config,
    save_chain_config,
)
from app.core.safety_policy import SafetyPolicy
from app.core.preset_store import CustomPreset
from app.gui.cut_chain_dialog import CutChainConfiguratorDialog


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _config(**changes) -> ChainConfig:
    values = {
        "target_ip": "192.168.1.25",
        "stages": [Stage("Lag", gate=Gate("time", seconds=0.01))],
        "on_failure": "halt",
        "global_timeout_s": 30.0,
    }
    values.update(changes)
    return ChainConfig(**values)


def test_strict_schema_round_trips_without_runtime_metadata() -> None:
    config = ChainConfig(
        target_ip="192.168.1.25",
        stages=[
            Stage(
                "Lag",
                methods=["lag"],
                params={"lag_delay": 750, "direction": "both"},
                gate=Gate("packets", seconds=12.5, packets=80),
                verify_method="lag",
                verify_minimum=2,
            )
        ],
        on_failure="continue",
        global_timeout_s=45.0,
        common_params={"lag_passthrough": False},
        disrupt_kwargs={"target_hostname": "lab-console"},
    )

    encoded = chain_config_to_dict(config)
    decoded = chain_config_from_dict(encoded)

    assert encoded["schema"] == CHAIN_SCHEMA
    assert "disrupt_kwargs" not in encoded
    assert chain_config_to_dict(decoded) == encoded
    assert decoded.disrupt_kwargs == {}


def test_valid_custom_preset_is_resolved_and_snapshotted_in_dialog(
    qapp: QApplication,
    monkeypatch,
) -> None:
    from app.core import cut_chain
    from app.gui import cut_chain_dialog

    custom = CustomPreset(
        name="Lab Custom",
        methods=["lag"],
        params={"lag_delay": 800, "direction": "both"},
    )
    monkeypatch.setattr(
        cut_chain,
        "get_custom_preset",
        lambda name: custom if name == custom.name else None,
    )
    monkeypatch.setattr(
        cut_chain_dialog,
        "list_custom_presets",
        lambda: [custom],
    )
    dialog = CutChainConfiguratorDialog("192.168.1.25")
    try:
        preset = dialog.stage_table.cellWidget(0, 0)
        assert isinstance(preset, QComboBox)
        preset.setCurrentText(custom.name)
        config = dialog._build_config(require_acknowledgement=False)
        assert config.stages[0].preset == custom.name
        assert config.stages[0].methods == ["lag"]
        assert config.stages[0].params == {
            "lag_delay": 800,
            "direction": "both",
        }
        assert chain_config_from_dict(
            chain_config_to_dict(config)
        ).stages[0].preset == custom.name
    finally:
        dialog.close()
        dialog.deleteLater()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"target_ip": "8.8.8.8"}, "local/private"),
        ({"target_ip": " 192.168.1.25 "}, "normalized"),
        ({"stages": []}, "between 1 and"),
        ({"on_failure": "rewind"}, "unsupported"),
        ({"on_failure": "ignore"}, "unsupported"),
        ({"global_timeout_s": float("nan")}, "between"),
        ({"global_timeout_s": 0}, "between"),
        ({"disrupt_kwargs": {"operation_timeout": "disabled"}}, "unsupported"),
    ],
)
def test_invalid_top_level_configuration_is_rejected(
    changes: dict,
    message: str,
) -> None:
    with pytest.raises(ChainValidationError, match=message):
        _config(**changes)


@pytest.mark.parametrize(
    ("stage", "message"),
    [
        (Stage("Lag", action="shell"), "action"),
        (Stage("Missing", methods=["lag"]), "preset"),
        (Stage("Lag", methods=["unknown"]), "methods"),
        (Stage("Lag", methods=["lag", "lag"]), "duplicates"),
        (Stage("Custom"), "at least one"),
        (Stage("Lag", halt_on=["severed"]), "halt_on"),
        (Stage("Lag", verify_method="drop"), "verify_method"),
        (Stage("Lag", params={"_force_self_disrupt": True}), "protected"),
        (Stage("Lag", gate=Gate("time", seconds=-1)), "gate seconds"),
        (Stage("Lag", gate=Gate("time", seconds=1, packets=1)), "packets"),
        (Stage("Lag", gate=Gate("severed", seconds=0)), "gate seconds"),
        (
            Stage("Lag", gate=Gate("packets", seconds=0, packets=1)),
            "gate seconds",
        ),
        (Stage("Lag", gate=Gate("packets", seconds=1, packets=0)), "between"),
    ],
)
def test_invalid_stage_actions_and_gates_are_rejected(
    stage: Stage,
    message: str,
) -> None:
    with pytest.raises(ChainValidationError, match=message):
        _config(stages=[stage])


def test_deserializer_rejects_every_unknown_field_layer() -> None:
    valid = chain_config_to_dict(_config())
    cases = []
    root = deepcopy(valid)
    root["unexpected"] = True
    cases.append(root)
    stage = deepcopy(valid)
    stage["stages"][0]["command"] = "anything"
    cases.append(stage)
    gate = deepcopy(valid)
    gate["stages"][0]["gate"]["fallback"] = "continue"
    cases.append(gate)

    for payload in cases:
        with pytest.raises(ChainValidationError, match="unknown keys"):
            chain_config_from_dict(payload)


def test_deserializer_rejects_unknown_action_gate_and_schema() -> None:
    valid = chain_config_to_dict(_config())
    action = deepcopy(valid)
    action["stages"][0]["action"] = "execute"
    gate = deepcopy(valid)
    gate["stages"][0]["gate"]["kind"] = "healthy"
    schema = deepcopy(valid)
    schema["schema"] = "dupez.cut-chain.v2"

    with pytest.raises(ChainValidationError, match="action"):
        chain_config_from_dict(action)
    with pytest.raises(ChainValidationError, match="gate kind"):
        chain_config_from_dict(gate)
    with pytest.raises(ChainValidationError, match="schema"):
        chain_config_from_dict(schema)


def test_zero_duration_is_explicitly_supported_only_for_time_gate() -> None:
    config = _config(stages=[Stage("Lag", gate=Gate("time", seconds=0))])
    assert config.stages[0].gate.seconds == 0


def test_chain_files_are_durable_bounded_and_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "lab.dupez-chain.json"
    save_chain_config(_config(), path)

    loaded = load_chain_config(path)

    assert chain_config_to_dict(loaded) == chain_config_to_dict(_config())
    assert not list(tmp_path.glob("*.tmp"))
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (MAX_CHAIN_JSON_BYTES + 1))
    with pytest.raises(ChainValidationError, match="exceeds"):
        load_chain_config(oversized)


def test_chain_loader_rejects_non_json_without_echoing_path(tmp_path: Path) -> None:
    path = tmp_path / "secret-looking-name.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ChainValidationError) as error:
        load_chain_config(path)
    assert str(path) not in str(error.value)


class _GateController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.disrupted_devices: dict = {}

    def disrupt_device(self, ip, _methods, _params, **_kwargs):
        self.calls.append(("disrupt", ip))
        self.disrupted_devices[ip] = {
            "engine": type("Engine", (), {"_packets_processed": 0})()
        }
        return True

    def stop_disruption(self, ip, **_kwargs):
        self.calls.append(("stop", ip))
        self.disrupted_devices.pop(ip, None)
        return True


class _ReleaseSequenceController(_GateController):
    def __init__(self, outcomes) -> None:
        super().__init__()
        self.outcomes = list(outcomes)

    def stop_disruption(self, ip, **_kwargs):
        self.calls.append(("stop", ip))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is True:
            self.disrupted_devices.pop(ip, None)
        return outcome

@pytest.mark.parametrize(
    ("policy", "expected_disrupts", "terminal"),
    [("halt", 1, "error"), ("continue", 2, "complete")],
)
def test_gate_timeout_obeys_supported_failure_policy(
    policy: str,
    expected_disrupts: int,
    terminal: str,
) -> None:
    controller = _GateController()
    events = []
    config = ChainConfig(
        target_ip="192.168.1.25",
        stages=[
            Stage("Lag", gate=Gate("packets", seconds=0.01, packets=1)),
            Stage("Red Disconnect", gate=Gate("time", seconds=0.01)),
        ],
        on_failure=policy,
        global_timeout_s=2.0,
    )
    runner = CutChainRunner(config, controller, on_event=events.append)
    runner.start()
    runner._thread.join(timeout=2.0)

    assert not runner.running
    assert len([call for call in controller.calls if call[0] == "disrupt"]) == (
        expected_disrupts
    )
    assert events[-1].kind == terminal
    assert any("timed out" in event.detail for event in events)
    assert controller.disrupted_devices == {}


def test_runner_revalidates_mutation_and_snapshots_valid_input() -> None:
    config = _config()
    controller = _GateController()
    runner = CutChainRunner(config, controller)
    config.stages[0].preset = "Red Disconnect"
    runner.start()
    runner._thread.join(timeout=2.0)
    assert not runner.running

    poisoned = _config()
    poisoned.stages[0].gate.kind = "unknown"
    with pytest.raises(ChainValidationError, match="gate kind"):
        CutChainRunner(poisoned, controller)


@pytest.mark.parametrize(
    "first_outcome",
    [False, None, RuntimeError("private backend detail")],
)
def test_unconfirmed_release_never_advances_or_completes(
    first_outcome,
) -> None:
    controller = _ReleaseSequenceController([first_outcome, True])
    events = []
    config = ChainConfig(
        target_ip="192.168.1.25",
        stages=[
            Stage("Lag", gate=Gate("time", seconds=0)),
            Stage("Red Disconnect", gate=Gate("time", seconds=0)),
        ],
        on_failure="continue",
        global_timeout_s=2,
    )
    runner = CutChainRunner(config, controller, on_event=events.append)
    runner.start()
    runner._thread.join(timeout=2)

    assert len([call for call in controller.calls if call[0] == "disrupt"]) == 1
    assert len([call for call in controller.calls if call[0] == "stop"]) == 2
    assert events[-1].kind == "error"
    assert "complete" not in [event.kind for event in events]
    assert runner.release_confirmed
    assert "private backend detail" not in events[-1].detail


def test_persistent_release_failure_retains_ownership_until_stop_retry() -> None:
    controller = _ReleaseSequenceController([False, False, True])
    events = []
    config = ChainConfig(
        target_ip="192.168.1.25",
        stages=[
            Stage("Lag", gate=Gate("time", seconds=0)),
            Stage("Red Disconnect", gate=Gate("time", seconds=0)),
        ],
        on_failure="continue",
        global_timeout_s=2,
    )
    runner = CutChainRunner(config, controller, on_event=events.append)
    runner.start()
    runner._thread.join(timeout=2)

    assert not runner.release_confirmed
    assert len([call for call in controller.calls if call[0] == "disrupt"]) == 1
    assert events[-1].kind == "error"
    assert runner.stop() is True
    assert runner.release_confirmed
    assert controller.disrupted_devices == {}


def test_dialog_defaults_are_safe_and_accessible(qapp: QApplication) -> None:
    dialog = CutChainConfiguratorDialog("192.168.1.25")
    try:
        assert dialog.accessibleName() == "Cut-chain configurator"
        assert dialog.target_edit.accessibleName()
        assert dialog.stage_table.accessibleDescription()
        assert dialog.scope_checkbox.accessibleDescription()
        assert dialog.stage_table.rowCount() == 1
        assert dialog.failure_combo.currentData() == "halt"
        assert not dialog.scope_checkbox.isChecked()
        assert not dialog.use_button.isEnabled()
        dialog.scope_checkbox.setChecked(True)
        assert dialog.use_button.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_builds_reorders_and_gates_rows(qapp: QApplication) -> None:
    dialog = CutChainConfiguratorDialog("192.168.1.25")
    try:
        dialog.add_stage(stage=Stage(
            "Red Disconnect",
            gate=Gate("packets", seconds=5, packets=77),
        ))
        packet_control = dialog.stage_table.cellWidget(1, 3)
        assert isinstance(packet_control, QSpinBox)
        assert packet_control.isEnabled()
        dialog._move_selected_stage(-1)
        preset = dialog.stage_table.cellWidget(0, 0)
        assert isinstance(preset, QComboBox)
        assert preset.currentText() == "Red Disconnect"

        dialog.scope_checkbox.setChecked(True)
        config = dialog._build_config(require_acknowledgement=True)
        assert [stage.preset for stage in config.stages] == [
            "Red Disconnect",
            "Lag",
        ]
        assert config.stages[0].gate.packets == 77
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_rechecks_narrow_scope_and_acknowledgement(
    qapp: QApplication,
) -> None:
    policy = SafetyPolicy(allowed_cidrs=("192.168.1.0/24",))
    dialog = CutChainConfiguratorDialog(
        "192.168.2.25",
        safety_policy=policy,
    )
    try:
        with pytest.raises(ChainValidationError, match="Confirm"):
            dialog._build_config(require_acknowledgement=True)
        dialog.scope_checkbox.setChecked(True)
        with pytest.raises(ChainValidationError, match="configured safety"):
            dialog._build_config(require_acknowledgement=True)
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_load_clears_consent_and_preserves_validated_overrides(
    qapp: QApplication,
) -> None:
    config = ChainConfig(
        target_ip="192.168.1.25",
        stages=[Stage(
            "Lag",
            methods=["lag"],
            params={"lag_delay": 900, "direction": "both"},
            gate=Gate("time", seconds=3),
            verify_method="lag",
            verify_minimum=3,
        )],
        global_timeout_s=20,
    )
    dialog = CutChainConfiguratorDialog("192.168.1.25")
    try:
        dialog.scope_checkbox.setChecked(True)
        dialog._load_config_into_form(config)
        assert not dialog.scope_checkbox.isChecked()
        loaded = dialog._build_config(require_acknowledgement=False)
        assert loaded.stages[0].methods == ["lag"]
        assert loaded.stages[0].params == {
            "lag_delay": 900,
            "direction": "both",
        }
        assert loaded.stages[0].verify_method == "lag"
        assert loaded.stages[0].verify_minimum == 3
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_accept_returns_defensive_copy(qapp: QApplication) -> None:
    dialog = CutChainConfiguratorDialog("192.168.1.25")
    try:
        dialog.scope_checkbox.setChecked(True)
        dialog._on_accept()
        first = dialog.selected_config()
        second = dialog.selected_config()
        assert first is not None and second is not None
        first.stages[0].preset = "Red Disconnect"
        assert second.stages[0].preset == "Lag"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_saved_payload_contains_no_python_only_values(tmp_path: Path) -> None:
    path = tmp_path / "chain.json"
    save_chain_config(_config(), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == chain_config_to_dict(_config())
