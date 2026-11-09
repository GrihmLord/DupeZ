"""Safety and backend-boundary tests for untrusted advisor output."""

from __future__ import annotations

import pytest

from app.ai.llm_advisor import LLMAdvisor, LLMConfig
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


def test_legacy_remote_llm_config_requires_https() -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        LLMConfig(provider="openai", base_url="http://example.com")


def test_legacy_llm_discards_plaintext_when_secret_store_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import secrets_manager

    class _FailingStore:
        def store(self, *_args, **_kwargs) -> bool:
            return False

        def retrieve(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        secrets_manager,
        "get_secrets_manager",
        lambda: _FailingStore(),
    )
    config = LLMConfig(
        provider="openai",
        base_url="https://example.com",
        api_key="plaintext-test-value",
    )

    assert config.api_key == ""
    assert config.get_api_key() == ""
