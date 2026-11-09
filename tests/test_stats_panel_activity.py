"""Pure formatting tests for honest per-module status labels."""

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from app.gui.panels.stats_panel import StatsPanel


def test_shadowed_module_is_not_rendered_as_effective() -> None:
    text, tooltip = StatsPanel._format_module_activity({
        "configured_methods": ["disconnect", "lag"],
        "module_activity": {
            "disconnect": {
                "state": "effective", "invoked": 12, "affected": 12,
                "direction": "both",
            },
            "lag": {
                "state": "shadowed", "invoked": 0, "affected": 0,
                "direction": "both", "shadowed_by": "disconnect",
            },
        },
    })
    assert "disconnect ✓" in text
    assert "lag blocked" in text
    assert "blocked by disconnect" in tooltip


def test_clumsy_methods_are_labeled_unverified_without_fake_counters() -> None:
    text, tooltip = StatsPanel._format_module_activity({
        "engine": "clumsy_compatibility",
        "telemetry_available": False,
        "methods": ["lag", "duplicate"],
    })
    assert text == "lag, duplicate (unverified)"
    assert "does not expose" in tooltip


def test_device_banner_surfaces_actual_engine_and_arp_state() -> None:
    banner = StatsPanel._format_device_banner(
        display_ip="192.168.1.x",
        detection={"profile": "pc_local", "layer": "local"},
        arp_active=True,
        arp_packets=7,
        cut_state="severed",
        engine="clumsy_compatibility",
        verification_state="runtime_unobservable",
    )
    assert "ENGINE:clumsy_compatibility" in banner
    assert "VERIFY:RUNTIME_UNOBSERVABLE" in banner
    assert "ARP:ACTIVE(7)" in banner


@pytest.mark.parametrize("field", ["display_ip", "profile", "layer", "engine", "verification_state", "arp_packets"])
def test_device_banner_escapes_dynamic_html_but_preserves_fixed_led_markup(field):
    from html import escape

    hostile = '<img src="file:///C:/not-read.svg">&data'
    arguments = {
        "display_ip": "192.168.1.x", "detection": {"profile": "pc_local", "layer": "local"},
        "arp_active": True, "arp_packets": 7, "cut_state": "severed",
        "engine": "packet", "verification_state": "observed",
    }
    if field in {"profile", "layer"}:
        arguments["detection"][field] = hostile
    else:
        arguments[field] = hostile
    banner = StatsPanel._format_device_banner(**arguments)
    assert "<img" not in banner.casefold()
    expected = hostile.upper() if field == "verification_state" else hostile
    assert escape(expected) in banner
    assert "<span style='color:#ff4444" in banner
    assert "CUT:SEVERED</span>" in banner


def test_stop_refresh_invalidates_late_worker_generation() -> None:
    panel = SimpleNamespace(
        _stats_generation=4,
        _stats_in_flight=True,
    )

    StatsPanel.stop_refresh(panel)

    assert panel._stats_generation == 5
    assert panel._stats_in_flight is False
