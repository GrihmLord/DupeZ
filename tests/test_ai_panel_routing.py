"""Focused wiring tests for the consolidated AI/Event panel."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.gui.panels.ai_panel import AIPanel


def test_smart_apply_proxy_is_rebound_to_full_clumsy_route_wrapper():
    original_calls = []

    def original_apply(profile, recommendation):
        original_calls.append(
            (profile, dict(recommendation.params))
        )
        return "applied"

    smart_panel = SimpleNamespace(
        apply_and_disrupt=original_apply,
        _smart_advisor=SimpleNamespace(cancel_pending=MagicMock()),
    )
    clumsy_view = SimpleNamespace(
        _panel_smart_apply_and_disrupt=original_apply,
    )
    advanced_panel = SimpleNamespace(
        augment_params=lambda params: {
            **params,
            "_clumsy_filter_predicate": "true",
            "lag_direction": "both",
        }
    )
    event_panel = SimpleNamespace(
        augment_params=lambda params: {
            **params,
            "_engine_preference": "clumsy",
            "_network_local": True,
            "_network_layer_explicit": True,
        }
    )
    panel = SimpleNamespace(
        _advisor=object(),
        _clumsy_view=clumsy_view,
        clumsy_advanced_panel=advanced_panel,
        event_panel=event_panel,
    )

    AIPanel._install_advisor_and_routing(panel, smart_panel)

    assert (
        clumsy_view._panel_smart_apply_and_disrupt
        is smart_panel._direct_route_wrapper
    )
    recommendation = SimpleNamespace(params={"lag_delay": 900})
    result = clumsy_view._panel_smart_apply_and_disrupt(
        {"platform": "pc"},
        recommendation,
    )

    assert result == "applied"
    assert original_calls == [
        (
            {"platform": "pc"},
            {
                "lag_delay": 900,
                "_clumsy_filter_predicate": "true",
                "lag_direction": "both",
                "_engine_preference": "clumsy",
                "_network_local": True,
                "_network_layer_explicit": True,
            },
        )
    ]
    # The recommendation object remains reusable and does not retain transient
    # UI routing or advanced-control metadata after the call.
    assert recommendation.params == {"lag_delay": 900}


def test_existing_route_wrapper_is_reused_by_cached_click_proxy():
    wrapper = MagicMock(return_value=True)
    smart_panel = SimpleNamespace(
        apply_and_disrupt=wrapper,
        _direct_route_wrapper=wrapper,
        _smart_advisor=None,
    )
    clumsy_view = SimpleNamespace(
        _panel_smart_apply_and_disrupt=MagicMock(),
    )
    panel = SimpleNamespace(
        _advisor=object(),
        _clumsy_view=clumsy_view,
        event_panel=SimpleNamespace(),
    )

    AIPanel._install_advisor_and_routing(panel, smart_panel)

    assert clumsy_view._panel_smart_apply_and_disrupt is wrapper


def test_live_controller_manager_is_exposed_without_creating_a_second_one():
    selected_manager = object()
    controller = SimpleNamespace(_disruption_manager=selected_manager)
    panel = SimpleNamespace(
        _clumsy_view=SimpleNamespace(controller=controller),
    )

    AIPanel._expose_live_disruption_manager(panel)

    assert controller.disruption_manager is selected_manager
