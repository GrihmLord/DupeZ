"""Process-wide ownership for the one active packet interception engine."""

from __future__ import annotations

import threading
import time
import weakref
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Optional

from app.firewall.disruption_request import DisruptionRequest
from app.firewall.execution_plan import ExecutionPlan

__all__ = [
    "EngineOwnerPhase",
    "EngineOwnershipError",
    "PacketEngineOwner",
    "PacketEngineSupervisor",
    "get_packet_engine_supervisor",
]


class EngineOwnerPhase(str, Enum):
    STARTING = "starting"
    ACTIVE = "active"
    RELEASING = "releasing"


class EngineOwnershipError(RuntimeError):
    """Raised when another live manager already owns packet interception."""


@dataclass(frozen=True)
class PacketEngineOwner:
    manager_id: int
    target_id: str
    generation: int
    backend: str
    capability_ids: tuple[str, ...]
    capture_layer: str
    request_id: str
    request_fingerprint: str
    filter_hash: str
    phase: EngineOwnerPhase
    pid: Optional[int] = None
    handle_attached: bool = False
    reserved_monotonic: float = 0.0
    activated_monotonic: float = 0.0

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("manager_id", None)
        result["phase"] = self.phase.value
        return result


@dataclass
class _Lease:
    owner: PacketEngineOwner
    manager_ref: weakref.ReferenceType[Any]


class PacketEngineSupervisor:
    """Serializes and describes the single process packet owner."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._lease: Optional[_Lease] = None

    def _discard_dead_manager(self) -> None:
        if self._lease is not None and self._lease.manager_ref() is None:
            self._lease = None

    def reserve(
        self,
        manager: Any,
        generation: int,
        request: DisruptionRequest,
        plan: ExecutionPlan,
    ) -> PacketEngineOwner:
        with self._lock:
            self._discard_dead_manager()
            if self._lease is not None:
                current = self._lease.owner
                raise EngineOwnershipError(
                    "packet interception is already owned by generation "
                    f"{current.generation} ({current.backend}, {current.phase.value})"
                )
            owner = PacketEngineOwner(
                manager_id=id(manager),
                target_id=request.target_id,
                generation=int(generation),
                backend=plan.backend.value,
                capability_ids=tuple(plan.capability_ids),
                capture_layer=request.capture_layer.value,
                request_id=request.request_id,
                request_fingerprint=request.public_fingerprint(),
                filter_hash=request.filter_hash,
                phase=EngineOwnerPhase.STARTING,
                reserved_monotonic=time.monotonic(),
            )
            self._lease = _Lease(owner, weakref.ref(manager))
            return owner

    def describe_request(
        self,
        manager: Any,
        generation: int,
        request: DisruptionRequest,
        plan: ExecutionPlan,
    ) -> PacketEngineOwner:
        """Replace preflight details with the exact finalized request."""

        with self._lock:
            owner = self._require(manager, generation)
            if (
                plan.backend.value != owner.backend
                or tuple(plan.capability_ids) != owner.capability_ids
                or request.target_id != owner.target_id
            ):
                raise EngineOwnershipError(
                    "final request changed target or backend capabilities "
                    "after packet ownership was reserved"
                )
            updated = replace(
                owner,
                target_id=request.target_id,
                backend=plan.backend.value,
                capability_ids=tuple(plan.capability_ids),
                capture_layer=request.capture_layer.value,
                request_id=request.request_id,
                request_fingerprint=request.public_fingerprint(),
                filter_hash=request.filter_hash,
            )
            self._lease.owner = updated
            return updated

    def activate(
        self,
        manager: Any,
        generation: int,
        *,
        pid: Optional[int],
        handle_attached: bool,
    ) -> PacketEngineOwner:
        with self._lock:
            owner = self._require(manager, generation)
            updated = replace(
                owner,
                phase=EngineOwnerPhase.ACTIVE,
                pid=int(pid) if pid is not None else None,
                handle_attached=bool(handle_attached),
                activated_monotonic=time.monotonic(),
            )
            self._lease.owner = updated
            return updated

    def mark_releasing(self, manager: Any, generation: int) -> bool:
        with self._lock:
            try:
                owner = self._require(manager, generation)
            except EngineOwnershipError:
                return False
            self._lease.owner = replace(owner, phase=EngineOwnerPhase.RELEASING)
            return True

    def transfer_generation(
        self,
        manager: Any,
        old_generation: int,
        new_generation: int,
        request: DisruptionRequest,
        plan: ExecutionPlan,
        *,
        pid: Optional[int],
        handle_attached: bool,
    ) -> PacketEngineOwner:
        with self._lock:
            owner = self._require(manager, old_generation)
            if (
                request.target_id != owner.target_id
                or plan.backend.value != owner.backend
                or tuple(plan.capability_ids) != owner.capability_ids
            ):
                raise EngineOwnershipError(
                    "replacement changed target or backend capabilities"
                )
            updated = replace(
                owner,
                generation=int(new_generation),
                target_id=request.target_id,
                backend=plan.backend.value,
                capability_ids=tuple(plan.capability_ids),
                capture_layer=request.capture_layer.value,
                request_id=request.request_id,
                request_fingerprint=request.public_fingerprint(),
                filter_hash=request.filter_hash,
                phase=EngineOwnerPhase.ACTIVE,
                pid=int(pid) if pid is not None else None,
                handle_attached=bool(handle_attached),
                activated_monotonic=time.monotonic(),
            )
            self._lease.owner = updated
            return updated

    def release(self, manager: Any, generation: int) -> bool:
        with self._lock:
            try:
                self._require(manager, generation)
            except EngineOwnershipError:
                return False
            self._lease = None
            return True

    def snapshot(
        self,
        *,
        manager: Any | None = None,
        generation: int | None = None,
    ) -> Optional[PacketEngineOwner]:
        with self._lock:
            self._discard_dead_manager()
            if self._lease is None:
                return None
            owner = self._lease.owner
            if manager is not None and owner.manager_id != id(manager):
                return None
            if generation is not None and owner.generation != int(generation):
                return None
            return owner

    def _require(self, manager: Any, generation: int) -> PacketEngineOwner:
        self._discard_dead_manager()
        if self._lease is None:
            raise EngineOwnershipError("packet ownership lease is absent")
        owner = self._lease.owner
        if owner.manager_id != id(manager) or owner.generation != int(generation):
            raise EngineOwnershipError("packet ownership lease is stale")
        return owner


_SUPERVISOR = PacketEngineSupervisor()


def get_packet_engine_supervisor() -> PacketEngineSupervisor:
    return _SUPERVISOR
