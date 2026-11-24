"""Hotkey policy tests without keyboard hooks or packet operations."""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from app.core.hotkey_settings import validate_hotkey_settings
from app.core.state import AppSettings, AppState


def test_defaults_are_safe_and_validate() -> None:
    settings = AppSettings()
    assert settings.disruption_hotkeys_enabled is False
    assert settings.disruption_start_hotkey_enabled is False
    assert validate_hotkey_settings(settings) == {
        "start": "ctrl+alt+f8", "stop": "ctrl+alt+f9", "panic": "ctrl+alt+x",
    }


def test_missing_fields_in_older_objects_use_safe_defaults() -> None:
    assert validate_hotkey_settings(SimpleNamespace()) == validate_hotkey_settings(AppSettings())


@pytest.mark.parametrize("field", [
    "disruption_hotkeys_enabled", "disruption_start_hotkey_enabled",
])
@pytest.mark.parametrize("value", ["true", "false", 1, 0, None, [], {}])
def test_enable_flags_require_actual_booleans(field, value) -> None:
    settings = AppSettings()
    setattr(settings, field, value)
    with pytest.raises(ValueError, match="must be a boolean"):
        validate_hotkey_settings(settings)


@pytest.mark.parametrize(("chord", "expected"), [
    (" ALT + CTRL + F8 ", "ctrl+alt+f8"),
    ("win + Shift + alt + Ctrl + J", "ctrl+alt+shift+win+j"),
    ("ctrl+0", "ctrl+0"),
    ("alt+9", "alt+9"),
    ("win+z", "win+z"),
    ("ctrl+f1", "ctrl+f1"),
    ("alt+f24", "alt+f24"),
])
def test_normalization_has_stable_order_and_does_not_mutate(chord, expected) -> None:
    settings = AppSettings(disruption_start_hotkey=chord)
    before = asdict(settings)
    assert validate_hotkey_settings(settings)["start"] == expected
    assert asdict(settings) == before


@pytest.mark.parametrize("chord", [
    "", " ", None, False, 12, [], "w", "f8", "shift+w", "shift+f8",
    "ctrl+ctrl+a", "ctrl++a", "ctrl+", "+ctrl+a", "ctrl+a+alt",
    "ctrl+a+b", "control+f8", "command+k", "alt+ctrl", "alt+space",
    "ctrl+f0", "ctrl+f25", "ctrl+f08", "ctrl+f12", "win+f12",
    "ctrl+é", "ctrl+f8,ctrl+f9", "ctrl+f8;ctrl+f9", "ctrl+f8\n",
    "ctrl+\tf8", "ctrl+f8\r", " " * 65 + "ctrl+f8",
])
def test_invalid_chords_are_rejected_even_while_disabled(chord) -> None:
    settings = AppSettings(disruption_start_hotkey=chord)
    assert not settings.disruption_hotkeys_enabled
    with pytest.raises(ValueError):
        validate_hotkey_settings(settings)


@pytest.mark.parametrize("chord", [
    "ctrl+s", "ctrl+e", "ctrl+shift+e", "ctrl+q", "ctrl+,", "ctrl+d",
    "ctrl+shift+p", "ctrl+alt+a", "ctrl+alt+shift+a", "ctrl+shift+c",
    "ctrl+f2", "ctrl+alt+x", "ctrl+1", "ctrl+2", "ctrl+3", "ctrl+4",
    "ctrl+shift+d",
])
def test_existing_app_and_tray_shortcuts_cannot_start_an_operation(chord) -> None:
    with pytest.raises(ValueError):
        validate_hotkey_settings(AppSettings(disruption_start_hotkey=chord))


@pytest.mark.parametrize("action", ["start", "stop"])
def test_local_panic_chord_is_reserved_for_panic_only(action) -> None:
    settings = AppSettings(disruption_panic_hotkey="ctrl+alt+p")
    setattr(settings, f"disruption_{action}_hotkey", "ctrl+alt+x")
    with pytest.raises(ValueError, match="existing DupeZ shortcut"):
        validate_hotkey_settings(settings)


@pytest.mark.parametrize(("first", "second"), [
    ("start", "stop"), ("start", "panic"), ("stop", "panic"),
])
def test_duplicate_assignments_are_rejected_after_normalizing(first, second) -> None:
    settings = AppSettings()
    setattr(settings, f"disruption_{first}_hotkey", "ctrl+alt+j")
    setattr(settings, f"disruption_{second}_hotkey", " ALT + CTRL + J ")
    with pytest.raises(ValueError, match="different chords"):
        validate_hotkey_settings(settings)


def test_settings_round_trip_through_persistence(tmp_path) -> None:
    path = str(tmp_path / "settings.json")
    state = AppState(config_file=path)
    state.settings = AppSettings(
        disruption_hotkeys_enabled=True,
        disruption_start_hotkey_enabled=False,
        disruption_start_hotkey="ctrl+alt+f10",
        disruption_stop_hotkey="ctrl+alt+f11",
        disruption_panic_hotkey="ctrl+shift+x",
    )
    assert state.save_settings() is True
    restored = AppState(config_file=path).settings
    assert asdict(restored) == asdict(state.settings)
    assert validate_hotkey_settings(restored)["stop"] == "ctrl+alt+f11"


def test_legacy_settings_file_keeps_hotkeys_opted_out(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"compact_view": true}', encoding="utf-8")
    restored = AppState(config_file=str(path)).settings
    assert restored.compact_view is True
    assert restored.disruption_hotkeys_enabled is False
    assert restored.disruption_start_hotkey_enabled is False
    assert validate_hotkey_settings(restored) == validate_hotkey_settings(AppSettings())
