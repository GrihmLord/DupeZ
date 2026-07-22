# app/gui/panels/clumsy_event_ui_policy.py — full-control UI compatibility
"""Align legacy event controls with the complete Clumsy 0.3.4 contract.

The event panel previously locked the global direction to Both because the old
runtime only verified bidirectional requests. The owned runtime now verifies
per-module Inbound/Outbound callbacks, so that lock is both inaccurate and
counterproductive. This adapter also applies exact fork slider limits only
while explicit Clumsy is selected, restoring the broader Native/Auto ranges
when the operator switches away.
"""

from __future__ import annotations

from typing import Any

from app.core.disruption_events import ENGINE_CLUMSY, ENGINE_NATIVE
from app.gui.panels.clumsy_advanced_panel import ClumsyAdvancedPanel
from app.gui.panels.disruption_event_panel import DisruptionEventPanel

__all__ = ["install_clumsy_event_ui_policy"]

# Exact public-slider bounds for the bundled fork. Fields omitted here already
# match the shared 0..100 chance limits.
_CLUMSY_SLIDER_LIMITS = {
    "lag_delay": (0, 15_000),
    "bandwidth_limit": (0, 99_999),
    "bandwidth_queue": (0, 99_999),
    "throttle_frame": (0, 1_000),
    "duplicate_count": (1, 49),
    # The fork's Disconnect module has no chance or timing controls.
    "disconnect_chance": (100, 100),
    "disconnect_arm_delay_ms": (0, 0),
    "disconnect_duration_ms": (0, 0),
}


def _apply_clumsy_slider_policy(panel: Any) -> None:
    view = getattr(panel, "_clumsy_view", None)
    sliders = getattr(view, "sliders", None)
    if not isinstance(sliders, dict):
        return

    original = getattr(view, "_clumsy_original_slider_ranges", None)
    if original is None:
        original = {
            key: (slider.minimum(), slider.maximum())
            for key, slider in sliders.items()
        }
        view._clumsy_original_slider_ranges = original

    explicit = getattr(panel, "engine_preference", "auto") == ENGINE_CLUMSY
    saved = getattr(view, "_clumsy_saved_slider_values", None)

    if explicit and saved is None:
        view._clumsy_saved_slider_values = {
            key: slider.value() for key, slider in sliders.items()
        }
    elif not explicit and saved is not None:
        for key, slider in sliders.items():
            minimum, maximum = original.get(
                key,
                (slider.minimum(), slider.maximum()),
            )
            slider.setRange(minimum, maximum)
            if key in saved:
                slider.setValue(saved[key])
        view._clumsy_saved_slider_values = None
        return

    if not explicit:
        for key, slider in sliders.items():
            minimum, maximum = original.get(
                key,
                (slider.minimum(), slider.maximum()),
            )
            slider.setRange(minimum, maximum)
        return

    for key, (minimum, maximum) in _CLUMSY_SLIDER_LIMITS.items():
        slider = sliders.get(key)
        if slider is None:
            continue
        slider.setRange(minimum, maximum)
        slider.setValue(max(minimum, min(maximum, slider.value())))


def _allow_verified_per_module_directions(
    panel: Any,
    *_signal_args: Any,
) -> None:
    """Keep global direction editable; advanced rows provide final authority."""

    inbound = getattr(panel._clumsy_view, "dir_inbound", None)
    outbound = getattr(panel._clumsy_view, "dir_outbound", None)
    if inbound is None or outbound is None:
        return
    if not inbound.isChecked() and not outbound.isChecked():
        outbound.blockSignals(True)
        try:
            outbound.setChecked(True)
        finally:
            outbound.blockSignals(False)
    inbound.setEnabled(True)
    outbound.setEnabled(True)


def _route_status(panel: Any, _index: int = -1) -> None:
    _allow_verified_per_module_directions(panel)
    _apply_clumsy_slider_policy(panel)

    engine = panel.engine_preference
    layer = panel.network_layer
    if engine == ENGINE_CLUMSY:
        engine_text = (
            "Direct Clumsy is explicit: each enabled module's direction, "
            "numeric values, sub-options, function preset, trigger mode, and "
            "Start state are verified; no engine substitution is allowed and "
            "only one owned Clumsy event may be active per helper."
        )
    elif engine == ENGINE_NATIVE:
        engine_text = (
            "Native WinDivert is explicit: Clumsy-specific preset, timer, "
            "bandwidth-unit, and RST-next controls do not trigger fallback."
        )
    else:
        engine_text = (
            "Auto prefers fully verified Clumsy controls when the requested "
            "semantics are exact, then uses Native only for a bounded equivalent."
        )
    layer_text = (
        "Target profile chooses Local/Remote."
        if layer == "auto"
        else f"Capture layer is explicitly pinned to {layer}."
    )
    panel.route_status.setText(f"{engine_text} {layer_text}")


def _refresh_bandwidth_label(advanced_panel: ClumsyAdvancedPanel) -> None:
    view = getattr(advanced_panel, "_clumsy_view", None)
    if view is None or not hasattr(view, "findChildren"):
        return
    try:
        from PyQt6.QtWidgets import QLabel

        unit = str(advanced_panel.bandwidth_unit.currentData() or "kb").upper()
        desired = f"Limit ({unit}/s)"
        for label in view.findChildren(QLabel):
            if label.text() in {"Limit (KB/s)", "Limit (MB/s)"}:
                label.setText(desired)
    except Exception:
        return


def install_clumsy_event_ui_policy() -> None:
    """Install event/advanced UI policy exactly once per Qt process."""

    if getattr(DisruptionEventPanel, "_full_clumsy_ui_policy_installed", False):
        return

    original_set_queue_running = DisruptionEventPanel._set_queue_running
    original_advanced_init = ClumsyAdvancedPanel.__init__
    original_advanced_persist = ClumsyAdvancedPanel._persist_settings

    def set_queue_running(panel: Any, running: bool) -> None:
        original_set_queue_running(panel, running)
        advanced = getattr(
            panel._clumsy_view,
            "_clumsy_advanced_param_adapter",
            None,
        )
        if advanced is not None:
            advanced.setEnabled(not running)

    def advanced_init(panel: ClumsyAdvancedPanel, *args: Any, **kwargs: Any) -> None:
        original_advanced_init(panel, *args, **kwargs)
        _refresh_bandwidth_label(panel)

    def advanced_persist(panel: ClumsyAdvancedPanel, *args: Any) -> None:
        original_advanced_persist(panel, *args)
        _refresh_bandwidth_label(panel)

    DisruptionEventPanel._enforce_clumsy_direction = (
        _allow_verified_per_module_directions
    )
    DisruptionEventPanel._update_route_status = _route_status
    DisruptionEventPanel._set_queue_running = set_queue_running
    ClumsyAdvancedPanel.__init__ = advanced_init
    ClumsyAdvancedPanel._persist_settings = advanced_persist
    DisruptionEventPanel._full_clumsy_ui_policy_installed = True
