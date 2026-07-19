"""Regression coverage for the small, backend-owned built-in presets."""

from app.core.builtin_presets import (
    AUTOMATIC_CONNECTION_TEST,
    BUILTIN_PRESETS,
    get_builtin_preset,
)


def test_automatic_connection_test_is_first_and_workflow_backed() -> None:
    assert next(iter(BUILTIN_PRESETS)) == AUTOMATIC_CONNECTION_TEST
    preset = BUILTIN_PRESETS[AUTOMATIC_CONNECTION_TEST]
    assert preset["methods"] == []
    assert preset["workflow"] == {
        "factory": "automatic_connection_test",
        "lag_mature_window_ms": 1000,
        "max_lag_delay_ms": 5000,
        "disconnect_duration_ms": 5000,
        "global_timeout_s": 20.0,
    }


def test_builtin_workflow_metadata_is_defensively_copied() -> None:
    resolved = get_builtin_preset(AUTOMATIC_CONNECTION_TEST)
    resolved["workflow"]["disconnect_duration_ms"] = 1
    assert (
        BUILTIN_PRESETS[AUTOMATIC_CONNECTION_TEST]["workflow"]
        ["disconnect_duration_ms"]
        == 5000
    )


def test_red_disconnect_is_a_pure_disconnect() -> None:
    preset = BUILTIN_PRESETS["Red Disconnect"]
    assert preset["methods"] == ["disconnect"]
    assert preset["params"] == {
        "direction": "both",
        "disconnect_chance": 100,
        "disconnect_arm_delay_ms": 0,
        "disconnect_duration_ms": 0,
    }
    description = preset["description"].lower()
    for removed_effect in ("lag", "bandwidth", "throttle"):
        assert removed_effect not in description


def test_lag_is_pure_packet_delay() -> None:
    preset = BUILTIN_PRESETS["Lag"]
    assert preset["methods"] == ["lag"]
    assert preset["params"] == {
        "lag_delay": 2500,
        "lag_passthrough": False,
        "lag_preserve_connection": False,
        "direction": "both",
    }
    description = preset["description"].lower()
    for removed_effect in ("drop", "bandwidth", "throttle", "disconnect"):
        assert removed_effect not in description


def test_custom_remains_empty() -> None:
    assert BUILTIN_PRESETS["Custom"]["methods"] == []
    assert BUILTIN_PRESETS["Custom"]["params"] == {}
