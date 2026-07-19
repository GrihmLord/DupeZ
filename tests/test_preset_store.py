"""Tests for app.core.preset_store (v5.6.9 feature #1).

Covers validation rules, persistence round-trip, name-collision handling
on import, and the reserved-name guard against built-in preset names.
Persistence is exercised against a temp ``app/data`` directory; the
real on-disk state is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from app.core.preset_store import (
    CustomPreset,
    PresetValidationError,
    RESERVED_PRESET_NAMES,
    VALID_DIRECTIONS,
    VALID_METHODS,
    delete_custom_preset,
    export_preset,
    get_custom_preset,
    import_preset,
    list_custom_presets,
    save_custom_preset,
    validate_preset,
)


# ── Validation ────────────────────────────────────────────────────────


class TestValidatePreset:
    """validate_preset() — schema, name, methods, params constraints."""

    def test_minimal_valid_preset_accepted(self) -> None:
        p = CustomPreset(name="Surgical", methods=["drop"])
        validate_preset(p)  # must not raise

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(PresetValidationError, match="cannot be empty"):
            validate_preset(CustomPreset(name="", methods=["drop"]))

    def test_whitespace_only_name_rejected(self) -> None:
        with pytest.raises(PresetValidationError, match="cannot be empty"):
            validate_preset(CustomPreset(name="   ", methods=["drop"]))

    def test_name_with_special_chars_rejected(self) -> None:
        # Slash and exclamation are not in the allowed set.
        with pytest.raises(PresetValidationError, match="invalid"):
            validate_preset(CustomPreset(name="my/preset!", methods=["drop"]))

    def test_name_with_parentheses_accepted(self) -> None:
        # Required so import_preset's auto-rename suffix "(2)" works.
        validate_preset(CustomPreset(name="Conflict (2)", methods=["drop"]))

    def test_name_starting_with_space_rejected(self) -> None:
        with pytest.raises(PresetValidationError, match="invalid"):
            validate_preset(CustomPreset(name=" leading", methods=["drop"]))

    def test_name_too_long_rejected(self) -> None:
        with pytest.raises(PresetValidationError, match="invalid"):
            validate_preset(CustomPreset(name="x" * 65, methods=["drop"]))

    def test_reserved_name_rejected_by_default(self) -> None:
        for reserved in RESERVED_PRESET_NAMES:
            with pytest.raises(PresetValidationError, match="reserved"):
                validate_preset(CustomPreset(name=reserved, methods=["drop"]))

    def test_reserved_name_allowed_with_flag(self) -> None:
        # Used by import_preset before name-conflict resolution.
        validate_preset(
            CustomPreset(name="Red Disconnect", methods=["drop"]),
            allow_reserved=True,
        )

    def test_unknown_method_rejected(self) -> None:
        with pytest.raises(PresetValidationError, match="unknown values"):
            validate_preset(CustomPreset(name="Bad", methods=["nuke"]))

    def test_all_documented_methods_accepted(self) -> None:
        # Sanity check: every method in the whitelist actually passes.
        for method in VALID_METHODS:
            p = CustomPreset(name="OK", methods=[method])
            validate_preset(p)

    def test_invalid_direction_rejected(self) -> None:
        p = CustomPreset(
            name="Bad", methods=["drop"],
            params={"direction": "sideways"},
        )
        with pytest.raises(PresetValidationError, match="direction invalid"):
            validate_preset(p)

    def test_all_documented_directions_accepted(self) -> None:
        for direction in VALID_DIRECTIONS:
            p = CustomPreset(
                name="OK", methods=["drop"],
                params={"direction": direction},
            )
            validate_preset(p)

    def test_port_int_in_range_accepted(self) -> None:
        p = CustomPreset(
            name="Ports", methods=["drop"],
            params={"_ports": [2302, 2303, 65535, 1]},
        )
        validate_preset(p)

    def test_port_int_zero_rejected(self) -> None:
        p = CustomPreset(
            name="ZeroPort", methods=["drop"],
            params={"_ports": [0]},
        )
        with pytest.raises(PresetValidationError, match="out of range"):
            validate_preset(p)

    def test_port_int_above_max_rejected(self) -> None:
        p = CustomPreset(
            name="HighPort", methods=["drop"],
            params={"_ports": [70000]},
        )
        with pytest.raises(PresetValidationError, match="out of range"):
            validate_preset(p)

    def test_port_dict_form_accepted(self) -> None:
        p = CustomPreset(
            name="ProtoPorts", methods=["drop"],
            params={"_ports": [
                {"proto": "tcp", "port": 2302},
                {"proto": "udp", "port": 2303},
            ]},
        )
        validate_preset(p)

    def test_port_dict_bad_proto_rejected(self) -> None:
        p = CustomPreset(
            name="BadProto", methods=["drop"],
            params={"_ports": [{"proto": "sctp", "port": 2302}]},
        )
        with pytest.raises(PresetValidationError, match="proto invalid"):
            validate_preset(p)

    def test_process_scope_invalid_rejected(self) -> None:
        p = CustomPreset(
            name="BadScope", methods=["drop"],
            params={"_process_scope": "bogus"},
        )
        with pytest.raises(PresetValidationError, match="_process_scope"):
            validate_preset(p)

    @pytest.mark.parametrize("scope", [None, ""])
    def test_empty_legacy_process_scope_is_tolerated(self, scope) -> None:
        p = CustomPreset(
            name="Scope", methods=["drop"],
            params={"_process_scope": scope} if scope is not None else {},
        )
        validate_preset(p)

    @pytest.mark.parametrize("scope", ["auto", "dayz"])
    def test_active_process_scope_fails_closed(self, scope) -> None:
        p = CustomPreset(
            name="Scope", methods=["drop"],
            params={"_process_scope": scope},
        )
        with pytest.raises(PresetValidationError, match="unsupported"):
            validate_preset(p)

    def test_description_too_long_rejected(self) -> None:
        p = CustomPreset(
            name="TooLong", methods=["drop"],
            description="x" * 257,
        )
        with pytest.raises(PresetValidationError, match="too long"):
            validate_preset(p)


# ── Round-trip ─────────────────────────────────────────────────────────


@pytest.fixture
def temp_preset_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect persistence_manager.data_directory to tmp_path for the test."""
    from app.core import data_persistence
    original = data_persistence.persistence_manager.data_directory
    monkeypatch.setattr(
        data_persistence.persistence_manager,
        "data_directory",
        tmp_path,
    )
    # Clear cache so subsequent reads pick up the new directory.
    data_persistence.persistence_manager._data_cache.pop("custom_presets", None)
    data_persistence.persistence_manager._dirty_data.discard("custom_presets")
    yield tmp_path
    # Restore the real path post-test.
    monkeypatch.setattr(
        data_persistence.persistence_manager,
        "data_directory",
        original,
    )


class TestRoundTrip:
    """Save / load / delete / import / export against a temp persistence dir."""

    def test_save_then_get(self, temp_preset_dir: Path) -> None:
        p = CustomPreset(name="TestSave", methods=["drop"])
        assert save_custom_preset(p)
        loaded = get_custom_preset("TestSave")
        assert loaded is not None
        assert loaded.name == "TestSave"
        assert loaded.methods == ["drop"]
        # Save adds timestamps.
        assert loaded.created_at
        assert loaded.updated_at

    def test_save_overwrites_existing(self, temp_preset_dir: Path) -> None:
        p1 = CustomPreset(name="Override", methods=["drop"])
        save_custom_preset(p1)
        p2 = CustomPreset(name="Override", methods=["lag", "drop"])
        save_custom_preset(p2)
        loaded = get_custom_preset("Override")
        assert loaded is not None
        assert set(loaded.methods) == {"drop", "lag"}

    def test_list_returns_all(self, temp_preset_dir: Path) -> None:
        for n in ("A", "B", "C"):
            save_custom_preset(CustomPreset(name=n, methods=["drop"]))
        names = {p.name for p in list_custom_presets()}
        assert names == {"A", "B", "C"}

    def test_delete_removes_entry(self, temp_preset_dir: Path) -> None:
        save_custom_preset(CustomPreset(name="ToDelete", methods=["drop"]))
        assert delete_custom_preset("ToDelete") is True
        assert get_custom_preset("ToDelete") is None
        # Idempotent: second delete returns False, not an exception.
        assert delete_custom_preset("ToDelete") is False

    def test_export_then_import_round_trips(
        self, temp_preset_dir: Path, tmp_path: Path
    ) -> None:
        original = CustomPreset(
            name="ExportMe",
            description="Test description",
            methods=["drop", "disconnect"],
            params={"direction": "both", "_ports": [2302]},
        )
        save_custom_preset(original)
        out_path = tmp_path / "exported.json"
        assert export_preset(original, str(out_path))
        # Verify the on-disk shape.
        with out_path.open() as f:
            doc = json.load(f)
        assert doc["version"] == 1
        assert len(doc["presets"]) == 1
        # Delete then re-import.
        delete_custom_preset("ExportMe")
        imported = import_preset(str(out_path))
        assert imported.name == "ExportMe"
        assert imported.description == "Test description"
        assert set(imported.methods) == {"drop", "disconnect"}

    def test_import_renames_on_collision(
        self, temp_preset_dir: Path, tmp_path: Path
    ) -> None:
        # Order matters: seed the store FIRST, then export a separate
        # file. If we export before seeding, the export emits with
        # timestamps that the seed call then overrides. Once seeded,
        # importing the file should rename due to the collision.
        save_custom_preset(CustomPreset(name="Conflict", methods=["lag"]))
        p = CustomPreset(name="Conflict", methods=["drop"])
        path = tmp_path / "bundle.json"
        export_preset(p, str(path))
        imported = import_preset(str(path))
        assert imported.name == "Conflict (2)"

    def test_import_rejects_malformed_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all", encoding="utf-8")
        with pytest.raises(PresetValidationError, match="cannot read"):
            import_preset(str(bad))

    def test_import_rejects_missing_presets_list(self, tmp_path: Path) -> None:
        bad = tmp_path / "empty.json"
        bad.write_text('{"version": 1, "presets": []}', encoding="utf-8")
        with pytest.raises(PresetValidationError, match="non-empty list"):
            import_preset(str(bad))
