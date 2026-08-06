"""Deterministic capability resolver for DupeZ packet backends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from app.firewall.capabilities import (
    KALIRENEGADE_CAPABILITIES,
    NATIVE_EXTENSION_CAPABILITIES,
    backend_method_for,
)
from app.firewall.disruption_request import DisruptionRequest, EnginePolicy

__all__ = [
    "Backend",
    "ExecutionPlan",
    "UnsupportedExecutionPlan",
    "resolve_execution_plan",
]


class Backend(str, Enum):
    KALIRENEGADE = "clumsy"
    NATIVE_EXTENSION = "native"


class UnsupportedExecutionPlan(ValueError):
    """Raised before launch when no single backend owns all capabilities."""


@dataclass(frozen=True)
class ExecutionPlan:
    request: DisruptionRequest
    backend: Backend
    capability_ids: Tuple[str, ...]
    backend_methods: Tuple[str, ...]


def resolve_execution_plan(request: DisruptionRequest) -> ExecutionPlan:
    capabilities = tuple(effect.capability_id for effect in request.effects)
    standard = tuple(
        item for item in capabilities if item in KALIRENEGADE_CAPABILITIES
    )
    extensions = tuple(
        item for item in capabilities if item in NATIVE_EXTENSION_CAPABILITIES
    )

    if len(standard) + len(extensions) != len(capabilities):
        raise UnsupportedExecutionPlan("request contains an unknown capability")
    if standard and extensions:
        raise UnsupportedExecutionPlan(
            "standard Kalirenegade effects cannot be mixed with DupeZ "
            "Native extensions until the one-process engine is available"
        )
    backend = (
        Backend.KALIRENEGADE if standard else Backend.NATIVE_EXTENSION
    )

    if (
        request.engine_policy is EnginePolicy.KALIRENEGADE
        and backend is not Backend.KALIRENEGADE
    ):
        raise UnsupportedExecutionPlan(
            "the requested DupeZ extension is not supported by Kalirenegade"
        )
    if (
        request.engine_policy is EnginePolicy.NATIVE_EXTENSION
        and backend is not Backend.NATIVE_EXTENSION
    ):
        raise UnsupportedExecutionPlan(
            "standard effects must use Kalirenegade; Native substitution is disabled"
        )

    return ExecutionPlan(
        request=request,
        backend=backend,
        capability_ids=capabilities,
        backend_methods=tuple(backend_method_for(item) for item in capabilities),
    )
