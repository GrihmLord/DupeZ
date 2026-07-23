# app/firewall/clumsy_preset_wire.py — safe IUP preset-name adapter
"""Bridge user-facing preset labels to the fork's fragile IUP attribute syntax.

Kalirenegade Clumsy 0.3.4 reads ``PresetName`` from ``presets.ini`` and later
constructs one unquoted ``IupSetAttributes`` string containing all five names.
IUP requires values containing spaces (or parser-significant characters) to be
quoted. The fork does not quote them, so a label such as ``DupeZ Full Matrix``
does not become an exact native combobox item.

DupeZ therefore keeps the requested label for its own UI/status while using a
bounded wire alias such as ``DupeZ_Full_Matrix`` inside ``presets.ini`` and the
owned Clumsy process. No packet/filter semantics are changed.
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.core.clumsy_controls import normalize_clumsy_label
from app.firewall import clumsy_network_disruptor as legacy
from app.firewall.direct_clumsy_manager import (
    DirectClumsyNetworkDisruptor,
    ManagedClumsyEngine,
)
from app.logs.logger import log_error, log_info

__all__ = [
    "normalize_function_preset_wire_name",
    "prepare_function_preset_params",
    "install_clumsy_preset_wire_compatibility",
]

_WIRE_SPACE = re.compile(r"\s+")
_WIRE_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_PRESET_COMBO_TIMEOUT_SECONDS = 1.0


def normalize_function_preset_wire_name(
    value: Any,
    *,
    default: str = "DupeZ",
) -> str:
    """Return an IUP-attribute-safe, human-readable preset alias.

    The fork interpolates this value without quotes into a comma-separated
    ``IupSetAttributes`` string. Whitespace is therefore converted to
    underscores and every remaining parser-significant character is removed.
    """

    display = normalize_clumsy_label(value, default=default)
    wire = _WIRE_SPACE.sub("_", display)
    wire = _WIRE_UNSAFE.sub("", wire)[:48].strip("._-")
    if wire:
        return wire
    fallback = _WIRE_UNSAFE.sub("", default)[:48].strip("._-")
    return fallback or "DupeZ"


def prepare_function_preset_params(params: Any) -> dict[str, Any]:
    """Copy *params* and add separate display/wire preset names."""

    effective = dict(params or {})
    requested = normalize_clumsy_label(
        effective.get(
            "_clumsy_function_preset_display_name",
            effective.get("_clumsy_function_preset_name"),
        ),
        default="DupeZ",
    )
    wire = normalize_function_preset_wire_name(requested, default="DupeZ")
    effective["_clumsy_function_preset_display_name"] = requested
    effective["_clumsy_function_preset_name"] = wire
    return effective


def _sync_wire_function_preset(engine: ManagedClumsyEngine) -> bool:
    """Select and verify the generated wire alias with bounded diagnostics."""

    from app.firewall import clumsy_full_controls as controls

    desired = normalize_function_preset_wire_name(
        engine.params.get("_clumsy_function_preset_name"),
        default="DupeZ",
    )
    deadline = time.monotonic() + _PRESET_COMBO_TIMEOUT_SECONDS
    observed: list[tuple[str, ...]] = []

    while time.monotonic() < deadline:
        observed = []
        for combo in legacy._find_children_by_class(engine._hwnd, "COMBOBOX"):
            items = tuple(legacy._combobox_items(combo))
            if len(items) != 5:
                continue
            observed.append(items)
            if any(item.strip().lower() == desired.lower() for item in items):
                if controls._select_combo_text(combo, desired):
                    log_info(
                        "Clumsy function preset confirmed: "
                        f"wire={desired!r}, display="
                        f"{engine.params.get('_clumsy_function_preset_display_name', desired)!r}"
                    )
                    return True
        time.sleep(0.03)

    engine._last_error = (
        f"Clumsy function preset wire alias {desired!r} was not found or "
        f"selected; observed five-item comboboxes={observed!r}"
    )
    log_error(engine._last_error)
    return False


def install_clumsy_preset_wire_compatibility() -> None:
    """Install the wire-label adapter after full controls, exactly once."""

    if getattr(
        DirectClumsyNetworkDisruptor,
        "_clumsy_preset_wire_installed",
        False,
    ):
        return

    from app.firewall import clumsy_full_controls as controls

    original_start_selected = DirectClumsyNetworkDisruptor._start_selected_engine
    original_get_stats = ManagedClumsyEngine.get_stats

    def start_selected_with_wire_name(
        manager: DirectClumsyNetworkDisruptor,
        *,
        filter_str: str,
        methods: list[str],
        params: dict[str, Any],
    ):
        effective = prepare_function_preset_params(params)
        return original_start_selected(
            manager,
            filter_str=filter_str,
            methods=methods,
            params=effective,
        )

    def get_stats_with_display_name(engine: ManagedClumsyEngine) -> dict[str, Any]:
        stats = dict(original_get_stats(engine))
        display = normalize_clumsy_label(
            engine.params.get(
                "_clumsy_function_preset_display_name",
                engine.params.get("_clumsy_function_preset_name"),
            ),
            default="DupeZ",
        )
        wire = normalize_function_preset_wire_name(
            engine.params.get("_clumsy_function_preset_name", display),
            default="DupeZ",
        )
        stats["function_preset"] = display
        stats["function_preset_wire"] = wire
        return stats

    controls._sync_function_preset = _sync_wire_function_preset
    DirectClumsyNetworkDisruptor._start_selected_engine = (
        start_selected_with_wire_name
    )
    ManagedClumsyEngine.get_stats = get_stats_with_display_name
    DirectClumsyNetworkDisruptor._clumsy_preset_wire_installed = True
