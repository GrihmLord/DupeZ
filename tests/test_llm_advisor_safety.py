"""Safety and backend-boundary tests for untrusted advisor output."""

from __future__ import annotations

from app.ai.llm_advisor import LLMAdvisor
from app.core.validation import validate_disruption_config


def test_offline_resilience_intent_uses_only_custom_lag_extension() -> None:
    result = LLMAdvisor()._fallback_interpret("connection resilience lab")
    assert result["methods"] == ["dupez.custom_lag"]
    assert result["params"]["lag_max_active_ms"] == 25_000


def test_offline_godmode_intent_uses_canonical_extension_schema() -> None:
    result = LLMAdvisor()._fallback_interpret("god mode lab")
    assert result["methods"] == ["dupez.godmode"]
    assert result["params"]["extension_active_ms"] == 25_000
    assert "godmode_block_ms" not in result["params"]
    assert validate_disruption_config(result) is not None


def test_untrusted_config_drops_hidden_control_parameters() -> None:
    result = validate_disruption_config({
        "methods": ["lag"],
        "params": {
            "direction": "both",
            "lag_delay": 500,
            "_engine_preference": "native",
            "_process_scope": "anything",
            "unreviewed_switch": True,
        },
    })
    assert result is not None
    assert result["params"] == {"direction": "both", "lag_delay": 500.0}


def test_untrusted_mixed_backend_config_is_rejected() -> None:
    assert validate_disruption_config({
        "methods": ["lag", "dupez.godmode"],
        "params": {"direction": "both"},
    }) is None
