"""Common metadata contract for DupeZ Native packet extensions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet

__all__ = ["ExtensionDescriptor"]


@dataclass(frozen=True)
class ExtensionDescriptor:
    capability_id: str
    implementation_version: str
    minimum_engine_version: str
    supported_layers: FrozenSet[str]
    composable_with: FrozenSet[str]
    required_parameters: FrozenSet[str]
    optional_parameters: FrozenSet[str]
    experimental: bool = True
