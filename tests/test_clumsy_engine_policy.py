"""Focused policy and verified-start tests for Clumsy compatibility."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.firewall import clumsy_network_disruptor as cnd
from app.firewall.clumsy_network_disruptor import (
    ENGINE_AUTO,
    ENGINE_CLUMSY,
    ENGINE_NATIVE,
    ClumsyEngine,
    ClumsyNetworkDisruptor,
    assess_clumsy_compatibility,
)


def _engine(methods, params=None) -> ClumsyEngine:
    effective_params = {"direction": "both"}
    effective_params.update(params or {})
    return ClumsyEngine(
        "clumsy.exe",
        ".",
        "true",
        list(methods),
        effective_params,
    )


def test_representable_decision_is_pure_and_deduplicates_methods():
    methods = ["lag", "lag", "drop"]
    params = {
        "direction": "both",
        "lag_delay": 1500,
        "lag_passthrough": False,
        "lag_preserve_connection": False,
    }
    original_params = dict(params)

    decision = assess_clumsy_compatibility(methods, params)

    assert decision.representable is True
    assert decision.methods == ("lag", "drop")
    assert decision.reasons == ()
    assert methods == ["lag", "lag", "drop"]
    assert params == original_params


@pytest.mark.parametrize("method", ["godmode", "statistical_burst", "pulse"])
def test_decision_rejects_non_core_methods(method):
    decision = assess_clumsy_compatibility(
        [method],
        {"direction": "both"},
    )

    assert decision.representable is False
    assert "no equivalent core module" in decision.reason


@pytest.mark.parametrize(
    "params, expected_reason",
    [
        ({"direction": "inbound"}, "direction='both'"),
        (
            {"direction": "both", "lag_direction": "outbound"},
            "lag_direction",
        ),
    ],
)
def test_decision_rejects_asymmetric_direction(params, expected_reason):
    decision = assess_clumsy_compatibility(["lag"], params)

    assert decision.representable is False
    assert expected_reason in decision.reason


@pytest.mark.parametrize(
    "override, expected_reason",
    [
        ({"disconnect_chance": 50}, "disconnect_chance"),
        ({"disconnect_arm_delay_ms": 1}, "disconnect_arm_delay_ms"),
        ({"disconnect_duration_ms": 1}, "disconnect_duration_ms"),
        ({"disconnect_quiet_after_ms": 1}, "disconnect_quiet_after_ms"),
        ({"_auto_tune_duration": True}, "automatic disconnect duration"),
    ],
)
def test_decision_rejects_native_only_disconnect_behavior(
    override,
    expected_reason,
):
    params = {"direction": "both", "disconnect_chance": 100}
    params.update(override)

    decision = assess_clumsy_compatibility(["disconnect"], params)

    assert decision.representable is False
    assert expected_reason in decision.reason


def test_stacked_lag_defaults_to_clumsy_compatible_consume_mode():
    decision = assess_clumsy_compatibility(
        ["lag", "duplicate"],
        {
            "direction": "both",
            "lag_delay": 1500,
            "lag_preserve_connection": False,
        },
    )

    assert decision.representable is True


def test_explicitly_disabled_lag_passthrough_is_representable():
    decision = assess_clumsy_compatibility(
        ["lag", "duplicate"],
        {
            "direction": "both",
            "lag_delay": 1500,
            "lag_passthrough": False,
            "lag_preserve_connection": False,
        },
    )

    assert decision.representable is True


def test_explicit_native_lag_passthrough_is_not_representable():
    decision = assess_clumsy_compatibility(
        ["lag", "duplicate"],
        {
            "direction": "both",
            "lag_delay": 1500,
            "lag_passthrough": True,
        },
    )

    assert decision.representable is False
    assert "lag passthrough" in decision.reason


def test_high_delay_does_not_implicitly_enable_connection_preservation():
    decision = assess_clumsy_compatibility(
        ["lag"],
        {"direction": "both", "lag_delay": 5000},
    )

    assert decision.representable is True


def test_explicitly_disabled_connection_preservation_allows_high_delay():
    decision = assess_clumsy_compatibility(
        ["lag"],
        {
            "direction": "both",
            "lag_delay": 5000,
            "lag_preserve_connection": False,
        },
    )

    assert decision.representable is True


def test_explicit_connection_preservation_is_not_representable():
    decision = assess_clumsy_compatibility(
        ["lag"],
        {
            "direction": "both",
            "lag_delay": 5000,
            "lag_preserve_connection": True,
        },
    )

    assert decision.representable is False
    assert "connection preservation" in decision.reason


def test_auto_prefers_clumsy_for_standalone_compatible_effects(
    monkeypatch,
):
    manager = ClumsyNetworkDisruptor()
    native_constructor = MagicMock()
    clumsy = MagicMock()
    clumsy.start.return_value = True
    clumsy_constructor = MagicMock(return_value=clumsy)
    manager.clumsy_exe = __file__
    monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(cnd, "NativeWinDivertEngine", native_constructor)
    monkeypatch.setattr(cnd, "ClumsyEngine", clumsy_constructor)

    engine, actual, requested = manager._start_selected_engine(
        filter_str="true",
        methods=["lag", "duplicate"],
        params={"_engine_preference": ENGINE_AUTO, "direction": "both"},
    )

    assert engine is clumsy
    assert actual == ENGINE_CLUMSY
    assert requested == ENGINE_AUTO
    clumsy_constructor.assert_called_once()
    native_constructor.assert_not_called()


def test_auto_uses_native_equivalent_if_clumsy_start_fails(monkeypatch):
    manager = ClumsyNetworkDisruptor()
    native = MagicMock()
    native.start.return_value = True
    clumsy = MagicMock()
    clumsy.start.return_value = False
    manager.clumsy_exe = __file__
    monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(
        cnd,
        "NativeWinDivertEngine",
        MagicMock(return_value=native),
    )
    monkeypatch.setattr(
        cnd,
        "ClumsyEngine",
        MagicMock(return_value=clumsy),
    )

    engine, actual, requested = manager._start_selected_engine(
        filter_str="true",
        methods=["lag", "duplicate"],
        params={"_engine_preference": ENGINE_AUTO, "direction": "both"},
    )

    assert engine is native
    assert (actual, requested) == (ENGINE_NATIVE, ENGINE_AUTO)
    clumsy.stop.assert_called_once()


def test_auto_refuses_semantic_change_after_clumsy_failure(monkeypatch):
    manager = ClumsyNetworkDisruptor()
    native_constructor = MagicMock()
    clumsy = MagicMock()
    clumsy.start.return_value = False
    manager.clumsy_exe = __file__
    monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(cnd, "NativeWinDivertEngine", native_constructor)
    monkeypatch.setattr(
        cnd,
        "ClumsyEngine",
        MagicMock(return_value=clumsy),
    )

    engine, actual, requested = manager._start_selected_engine(
        filter_str="true",
        methods=["bandwidth"],
        params={"_engine_preference": ENGINE_AUTO, "direction": "both"},
    )

    assert engine is None
    assert (actual, requested) == ("", ENGINE_AUTO)
    native_constructor.assert_not_called()


def test_explicit_clumsy_fails_closed_before_constructing_engine(monkeypatch):
    manager = ClumsyNetworkDisruptor()
    native_constructor = MagicMock()
    clumsy_constructor = MagicMock()
    monkeypatch.setattr(cnd, "NativeWinDivertEngine", native_constructor)
    monkeypatch.setattr(cnd, "ClumsyEngine", clumsy_constructor)

    engine, actual, requested = manager._start_selected_engine(
        filter_str="true",
        methods=["disconnect"],
        params={
            "_engine_preference": ENGINE_CLUMSY,
            "direction": "both",
            "disconnect_chance": 100,
            "disconnect_duration_ms": 250,
        },
    )

    assert engine is None
    assert actual == ""
    assert requested == ENGINE_CLUMSY
    native_constructor.assert_not_called()
    clumsy_constructor.assert_not_called()


def test_explicit_native_override_still_runs_unrepresentable_request(
    monkeypatch,
):
    manager = ClumsyNetworkDisruptor()
    native = MagicMock()
    native.start.return_value = True
    native_constructor = MagicMock(return_value=native)
    clumsy_constructor = MagicMock()
    monkeypatch.setattr(cnd, "NATIVE_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(cnd, "NativeWinDivertEngine", native_constructor)
    monkeypatch.setattr(cnd, "ClumsyEngine", clumsy_constructor)

    engine, actual, requested = manager._start_selected_engine(
        filter_str="true",
        methods=["disconnect"],
        params={
            "_engine_preference": ENGINE_NATIVE,
            "direction": "both",
            "disconnect_chance": 100,
            "disconnect_duration_ms": 250,
        },
    )

    assert engine is native
    assert (actual, requested) == (ENGINE_NATIVE, ENGINE_NATIVE)
    native_constructor.assert_called_once()
    clumsy_constructor.assert_not_called()


def test_manager_passes_deduplicated_methods_to_clumsy(
    monkeypatch,
    tmp_path,
):
    executable = tmp_path / "clumsy.exe"
    executable.write_bytes(b"stub")
    manager = ClumsyNetworkDisruptor()
    manager.clumsy_exe = str(executable)
    clumsy = MagicMock()
    clumsy.start.return_value = True
    constructor = MagicMock(return_value=clumsy)
    monkeypatch.setattr(cnd, "ClumsyEngine", constructor)

    engine, actual, requested = manager._start_selected_engine(
        filter_str="true",
        methods=["drop", "drop"],
        params={
            "_engine_preference": ENGINE_CLUMSY,
            "direction": "both",
        },
    )

    assert engine is clumsy
    assert (actual, requested) == (ENGINE_CLUMSY, ENGINE_CLUMSY)
    assert constructor.call_args.kwargs["methods"] == ["drop"]


def test_numeric_setter_verifies_only_active_module_controls(monkeypatch):
    engine = _engine(["lag"], {"lag_delay": 2345, "drop_chance": 17})
    monkeypatch.setattr(cnd, "_get_edit_controls_sorted", lambda _hwnd: [10, 11])
    monkeypatch.setattr(cnd, "_get_window_text", lambda _hwnd: "old")
    type_value = MagicMock(return_value="2345")
    monkeypatch.setattr(cnd, "_type_into_edit", type_value)

    assert engine._set_input_values() is True
    type_value.assert_called_once_with(11, "2345")


def test_numeric_setter_uses_and_verifies_active_default(monkeypatch):
    engine = _engine(["lag"])
    monkeypatch.setattr(cnd, "_get_edit_controls_sorted", lambda _hwnd: [10, 11])
    monkeypatch.setattr(cnd, "_get_window_text", lambda _hwnd: "old")
    type_value = MagicMock(return_value="1500")
    monkeypatch.setattr(cnd, "_type_into_edit", type_value)

    assert engine._set_input_values() is True
    type_value.assert_called_once_with(11, "1500")


def test_duplicate_extra_count_is_translated_to_clumsy_total(monkeypatch):
    engine = _engine(
        ["duplicate"],
        {"duplicate_count": 2, "duplicate_chance": 100},
    )
    edits = list(range(12))
    monkeypatch.setattr(cnd, "_get_edit_controls_sorted", lambda _hwnd: edits)
    monkeypatch.setattr(cnd, "_get_window_text", lambda _hwnd: "old")
    typed = []

    def _type(hwnd, value):
        typed.append((hwnd, value))
        return value

    monkeypatch.setattr(cnd, "_type_into_edit", _type)

    assert engine._set_input_values() is True
    assert (7, "3") in typed
    assert (8, "100") in typed


def test_duplicate_presets_file_uses_clumsy_total_count(tmp_path):
    engine = ClumsyEngine(
        "clumsy.exe",
        str(tmp_path),
        "true",
        ["duplicate"],
        {
            "direction": "both",
            "duplicate_count": 2,
            "duplicate_chance": 100,
        },
    )

    engine._write_presets()

    content = (tmp_path / "presets.ini").read_text(encoding="utf-8")
    assert "Duplicate_Count = 3" in content


@pytest.mark.parametrize("count", [0, 50])
def test_clumsy_rejects_unrepresentable_extra_duplicate_count(count):
    decision = assess_clumsy_compatibility(
        ["duplicate"],
        {"direction": "both", "duplicate_count": count},
    )

    assert decision.representable is False
    assert "1 to 49 extra copies" in decision.reason


def test_clumsy_rejects_lag_above_bundled_limit():
    decision = assess_clumsy_compatibility(
        ["lag"],
        {"direction": "both", "lag_delay": 15_001},
    )

    assert decision.representable is False
    assert "0 to 15000ms" in decision.reason


def test_runtime_rejects_process_scope_before_engine_initialization():
    manager = ClumsyNetworkDisruptor()
    manager.initialize = MagicMock(return_value=True)

    started = manager.disconnect_device_clumsy(
        "192.168.1.42",
        methods=["lag"],
        params={
            "direction": "both",
            "lag_delay": 100,
            "_process_scope": "dayz",
        },
        preset="pc_local",
    )

    assert started is False
    manager.initialize.assert_not_called()


def test_numeric_setter_fails_on_readback_mismatch(monkeypatch):
    engine = _engine(["lag"], {"lag_delay": 2345})
    monkeypatch.setattr(cnd, "_get_edit_controls_sorted", lambda _hwnd: [10, 11])
    monkeypatch.setattr(cnd, "_get_window_text", lambda _hwnd: "old")
    monkeypatch.setattr(cnd, "_type_into_edit", lambda _hwnd, _value: "999")

    assert engine._set_input_values() is False


@pytest.mark.parametrize("verified", [True, False])
def test_sub_checkbox_setter_returns_click_verification(monkeypatch, verified):
    engine = _engine(["throttle"], {"throttle_drop": True})
    engine._find_checkbox = MagicMock(return_value=22)
    engine._click_and_verify = MagicMock(return_value=verified)

    assert engine._click_sub_checkboxes() is verified
    engine._click_and_verify.assert_called_once_with(
        22,
        "Drop Throttled",
        expected_state=cnd.BST_CHECKED,
    )


def test_sub_checkbox_setter_verifies_default_state(monkeypatch):
    engine = _engine(["throttle"], {"throttle_drop": False})
    engine._find_checkbox = MagicMock(return_value=22)
    engine._click_and_verify = MagicMock()
    state_check = MagicMock(return_value=True)
    monkeypatch.setattr(cnd, "_checkbox_matches_state", state_check)

    assert engine._click_sub_checkboxes() is True
    state_check.assert_called_once_with(22, 0)
    engine._click_and_verify.assert_not_called()


@pytest.mark.parametrize(
    "failed_step",
    ["_click_sub_checkboxes", "_set_input_values"],
)
def test_gui_start_aborts_when_requested_controls_are_unverified(
    monkeypatch,
    failed_step,
):
    engine = _engine(["disconnect"], {"disconnect_chance": 100})
    engine._proc = MagicMock(pid=123)
    engine._proc.poll.return_value = None
    monkeypatch.setattr(cnd, "_find_window_by_pid", lambda *_args, **_kwargs: 100)
    monkeypatch.setattr(cnd, "_get_window_text", lambda _hwnd: "clumsy")
    engine._select_network_layer = MagicMock(return_value=True)
    engine._enable_modules = MagicMock(return_value=True)
    engine._click_sub_checkboxes = MagicMock(return_value=True)
    engine._set_input_values = MagicMock(return_value=True)
    setattr(engine, failed_step, MagicMock(return_value=False))
    engine._click_start_button = MagicMock(return_value=True)
    engine._cleanup = MagicMock()

    assert engine._start_gui_automation() is False
    engine._click_start_button.assert_not_called()
    engine._cleanup.assert_called_once()


def test_verified_gui_start_is_reported_without_runtime_claim(monkeypatch):
    engine = _engine(["disconnect"], {"disconnect_chance": 100})
    engine._proc = MagicMock(pid=123)
    engine._proc.poll.return_value = None
    monkeypatch.setattr(cnd, "_find_window_by_pid", lambda *_args, **_kwargs: 100)
    monkeypatch.setattr(cnd, "_get_window_text", lambda _hwnd: "clumsy")
    monkeypatch.setattr(cnd, "_hide_window", lambda _hwnd: True)
    monkeypatch.setattr(cnd.time, "sleep", lambda _seconds: None)
    engine._select_network_layer = MagicMock(return_value=True)
    engine._enable_modules = MagicMock(return_value=True)
    engine._click_sub_checkboxes = MagicMock(return_value=True)
    engine._set_input_values = MagicMock(return_value=True)
    engine._click_start_button = MagicMock(return_value=True)

    assert engine._start_gui_automation() is True
    stats = engine.get_stats()
    assert stats["startup_verified"] is True
    assert stats["runtime_verified"] is False
    assert stats["telemetry_available"] is False


def test_direct_clumsy_start_rejects_request_before_killing_processes(
    monkeypatch,
):
    engine = _engine(
        ["lag", "duplicate"],
        {"lag_passthrough": True},
    )
    kill_all = MagicMock()
    monkeypatch.setattr(cnd, "_kill_all_clumsy", kill_all)

    assert engine.start() is False
    kill_all.assert_not_called()
