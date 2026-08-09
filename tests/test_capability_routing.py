"""Deterministic request and backend ownership contract tests."""

from __future__ import annotations

import pytest

from app.firewall.capabilities import CapabilityError, canonicalize_capabilities
from app.firewall.disruption_request import DisruptionRequest, EnginePolicy
from app.firewall.execution_plan import (
    Backend,
    UnsupportedExecutionPlan,
    resolve_execution_plan,
)


def _request(methods, params=None) -> DisruptionRequest:
    return DisruptionRequest.from_legacy(
        target_id="192.0.2.10",
        filter_string="ip.SrcAddr == 192.0.2.10",
        methods=methods,
        params={"direction": "both", **(params or {})},
    )


def test_legacy_standard_aliases_resolve_only_to_kalirenegade() -> None:
    plan = resolve_execution_plan(_request(["lag", "drop", "lag"]))
    assert plan.backend is Backend.KALIRENEGADE
    assert plan.capability_ids == ("kali.lag", "kali.drop")
    assert plan.backend_methods == ("lag", "drop")


@pytest.mark.parametrize("method", ["godmode", "dupez.godmode", "custom_lag"])
def test_extension_aliases_resolve_only_to_native(method: str) -> None:
    plan = resolve_execution_plan(_request([method]))
    assert plan.backend is Backend.NATIVE_EXTENSION
    assert plan.capability_ids[0].startswith("dupez.")


def test_mixed_standard_and_extension_request_is_rejected() -> None:
    with pytest.raises(UnsupportedExecutionPlan, match="cannot be mixed"):
        resolve_execution_plan(_request(["lag", "dupez.godmode"]))


def test_unknown_capability_is_rejected_before_planning() -> None:
    with pytest.raises(CapabilityError, match="unknown packet capability"):
        canonicalize_capabilities(["not-a-real-effect"])


def test_explicit_native_cannot_substitute_for_standard_effect() -> None:
    with pytest.raises(UnsupportedExecutionPlan, match="must use Kalirenegade"):
        resolve_execution_plan(_request(
            ["lag"], {"_engine_preference": EnginePolicy.NATIVE_EXTENSION.value}
        ))


def test_explicit_clumsy_cannot_run_extension() -> None:
    with pytest.raises(UnsupportedExecutionPlan, match="not supported"):
        resolve_execution_plan(_request(
            ["dupez.godmode"],
            {"_engine_preference": EnginePolicy.KALIRENEGADE.value},
        ))


def test_request_parameters_are_deeply_immutable() -> None:
    source = {"direction": "both", "nested": {"ports": [2302, 2303]}}
    request = _request(["lag"], source)
    source["nested"]["ports"].append(9999)

    assert request.parameters["nested"]["ports"] == (2302, 2303)
    with pytest.raises(TypeError):
        request.parameters["direction"] = "inbound"
    with pytest.raises(TypeError):
        request.parameters["nested"]["other"] = True
