"""Tests for active-operation safety boundaries."""

import time

import pytest

from app.core.safety_policy import SafetyPolicy


def test_policy_rejects_public_scope_configuration() -> None:
    with pytest.raises(ValueError, match="public target scope"):
        SafetyPolicy(allowed_cidrs=("0.0.0.0/0",))


def test_policy_restricts_target_to_configured_subnet() -> None:
    policy = SafetyPolicy(allowed_cidrs=("192.168.50.0/24",))

    assert policy.validate_target("192.168.50.12") == "192.168.50.12"
    with pytest.raises(ValueError, match="outside"):
        policy.validate_target("192.168.51.12")


def test_policy_bounds_requested_timeout() -> None:
    policy = SafetyPolicy(max_operation_seconds=30)

    assert policy.bounded_timeout() == 30
    assert policy.bounded_timeout(10) == 10
    assert policy.bounded_timeout(300) == 30


def test_policy_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        SafetyPolicy().bounded_timeout(0)
