"""Fail-closed safety policy for active network operations."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Iterable, Optional

from app.core.validation import validate_local_target_ip

DEFAULT_ALLOWED_CIDRS = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
)
DEFAULT_MAX_OPERATION_SECONDS = 300
HARD_MAX_OPERATION_SECONDS = 3600


@dataclass(frozen=True)
class SafetyPolicy:
    """Validated scope and deadline policy for active operations."""

    allowed_cidrs: tuple[str, ...] = DEFAULT_ALLOWED_CIDRS
    dry_run: bool = False
    max_operation_seconds: int = DEFAULT_MAX_OPERATION_SECONDS

    def __post_init__(self) -> None:
        if not self.networks:
            raise ValueError("at least one allowed target CIDR is required")
        limit = int(self.max_operation_seconds)
        if not 1 <= limit <= HARD_MAX_OPERATION_SECONDS:
            raise ValueError(
                f"max_operation_seconds must be between 1 and "
                f"{HARD_MAX_OPERATION_SECONDS}"
            )

    @property
    def networks(self) -> tuple[ipaddress.IPv4Network, ...]:
        parsed = []
        defaults = tuple(
            ipaddress.ip_network(cidr) for cidr in DEFAULT_ALLOWED_CIDRS
        )
        for cidr in self.allowed_cidrs:
            network = ipaddress.ip_network(str(cidr), strict=True)
            if not isinstance(network, ipaddress.IPv4Network):
                raise ValueError(f"IPv6 target scope is unsupported: {cidr!r}")
            if not any(network.subnet_of(default) for default in defaults):
                raise ValueError(f"public target scope is forbidden: {cidr!r}")
            parsed.append(network)
        return tuple(parsed)

    def validate_target(self, ip: str) -> str:
        normalized = validate_local_target_ip(ip, context="safety scope")
        addr = ipaddress.IPv4Address(normalized)
        if not any(addr in network for network in self.networks):
            raise ValueError(f"target is outside the configured safety scope: {ip!r}")
        return normalized

    def bounded_timeout(self, requested: Optional[float] = None) -> float:
        maximum = float(self.max_operation_seconds)
        if requested is None:
            return maximum
        try:
            value = float(requested)
        except (TypeError, ValueError) as exc:
            raise ValueError("operation timeout must be numeric") from exc
        if value <= 0:
            raise ValueError("operation timeout must be greater than zero")
        return min(value, maximum)

    @classmethod
    def from_settings(
        cls,
        settings,
        *,
        dry_run_override: Optional[bool] = None,
        allowed_cidrs_override: Optional[Iterable[str]] = None,
        max_seconds_override: Optional[float] = None,
    ) -> "SafetyPolicy":
        cidrs = tuple(
            allowed_cidrs_override
            if allowed_cidrs_override is not None
            else getattr(settings, "allowed_target_cidrs", DEFAULT_ALLOWED_CIDRS)
        )
        dry_run = (
            bool(dry_run_override)
            if dry_run_override is not None
            else bool(getattr(settings, "safety_dry_run", False))
        )
        maximum = (
            int(max_seconds_override)
            if max_seconds_override is not None
            else int(getattr(
                settings,
                "max_operation_seconds",
                DEFAULT_MAX_OPERATION_SECONDS,
            ))
        )
        return cls(
            allowed_cidrs=cidrs,
            dry_run=dry_run,
            max_operation_seconds=maximum,
        )
