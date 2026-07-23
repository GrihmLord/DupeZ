"""Coverage for user-facing versus native Clumsy preset names."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.firewall import clumsy_full_controls as controls
from app.firewall import clumsy_network_disruptor as legacy
from app.firewall.clumsy_preset_wire import (
    _sync_wire_function_preset,
    normalize_function_preset_wire_name,
    prepare_function_preset_params,
)
from app.firewall.direct_clumsy_manager import ManagedClumsyEngine


def _engine(tmp_path, params):
    executable = tmp_path / "clumsy.exe"
    executable.write_bytes(b"preset-wire-test")
    return ManagedClumsyEngine(
        str(executable),
        str(tmp_path),
        "ip.SrcAddr == 192.168.137.2 or ip.DstAddr == 192.168.137.2",
        ["lag"],
        params,
    )


def test_wire_name_removes_unquoted_iup_attribute_syntax():
    assert normalize_function_preset_wire_name(
        "DupeZ Full Matrix"
    ) == "DupeZ_Full_Matrix"
    assert normalize_function_preset_wire_name(
        "  My   Preset, = Dangerous  "
    ) == "My_Preset_Dangerous"
    assert " " not in normalize_function_preset_wire_name("A B")
    assert "," not in normalize_function_preset_wire_name("A,B")
    assert "=" not in normalize_function_preset_wire_name("A=B")


def test_prepare_params_preserves_display_name_and_adds_wire_alias():
    original = {
        "lag_delay": 170,
        "_clumsy_function_preset_name": "DupeZ Full Matrix",
    }

    prepared = prepare_function_preset_params(original)

    assert prepared is not original
    assert original["_clumsy_function_preset_name"] == "DupeZ Full Matrix"
    assert prepared["_clumsy_function_preset_display_name"] == (
        "DupeZ Full Matrix"
    )
    assert prepared["_clumsy_function_preset_name"] == (
        "DupeZ_Full_Matrix"
    )


def test_full_preset_writer_uses_wire_alias(tmp_path):
    params = prepare_function_preset_params({
        "direction": "both",
        "lag_delay": 170,
        "_clumsy_function_preset_name": "DupeZ Full Matrix",
    })
    engine = _engine(tmp_path, params)

    controls._write_full_presets(engine)

    content = (tmp_path / "presets.ini").read_text(encoding="utf-8")
    assert "PresetName = DupeZ_Full_Matrix" in content
    assert "PresetName = DupeZ Full Matrix" not in content


def test_wire_preset_sync_selects_exact_native_item(monkeypatch):
    engine = SimpleNamespace(
        _hwnd=99,
        _last_error="",
        params={
            "_clumsy_function_preset_display_name": "DupeZ Full Matrix",
            "_clumsy_function_preset_name": "DupeZ_Full_Matrix",
        },
    )
    monkeypatch.setattr(
        legacy,
        "_find_children_by_class",
        lambda _parent, _class: [501],
    )
    monkeypatch.setattr(
        legacy,
        "_combobox_items",
        lambda _combo: [
            "DupeZ_Full_Matrix",
            "Preset_2",
            "Preset_3",
            "Preset_4",
            "Preset_5",
        ],
    )
    select = MagicMock(return_value=True)
    monkeypatch.setattr(controls, "_select_combo_text", select)

    assert _sync_wire_function_preset(engine) is True
    select.assert_called_once_with(501, "DupeZ_Full_Matrix")
    assert engine._last_error == ""


def test_wire_preset_sync_reports_observed_items(monkeypatch):
    engine = SimpleNamespace(
        _hwnd=99,
        _last_error="",
        params={"_clumsy_function_preset_name": "Missing_Name"},
    )
    monkeypatch.setattr(
        legacy,
        "_find_children_by_class",
        lambda _parent, _class: [501],
    )
    monkeypatch.setattr(
        legacy,
        "_combobox_items",
        lambda _combo: ["Preset1", "Preset2", "Preset3", "Preset4", "Preset5"],
    )
    monkeypatch.setattr(
        "app.firewall.clumsy_preset_wire._PRESET_COMBO_TIMEOUT_SECONDS",
        0.0,
    )

    assert _sync_wire_function_preset(engine) is False
    assert "Missing_Name" in engine._last_error
    assert "observed five-item comboboxes" in engine._last_error
