"""Bounded, direction-aware packet queue ownership."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, List

from app.firewall.extensions.godmode.direction import PacketDirection

__all__ = ["PacketEnvelope", "QueueManager"]


@dataclass(frozen=True)
class PacketEnvelope:
    captured_at: float
    packet: bytearray
    address: Any
    direction: PacketDirection


class QueueManager:
    def __init__(self, maximum: int) -> None:
        self.maximum = max(1, int(maximum))
        self._inbound: Deque[PacketEnvelope] = deque()
        self._outbound: Deque[PacketEnvelope] = deque()
        self._lock = threading.RLock()

    def enqueue(self, envelope: PacketEnvelope) -> bool:
        with self._lock:
            if len(self._inbound) + len(self._outbound) >= self.maximum:
                return False
            queue = (
                self._outbound
                if envelope.direction is PacketDirection.OUTBOUND
                else self._inbound
            )
            queue.append(envelope)
            return True

    def drain(self, limit: int | None = None) -> List[PacketEnvelope]:
        with self._lock:
            rows = list(self._inbound) + list(self._outbound)
            rows.sort(key=lambda item: item.captured_at)
            if limit is not None:
                rows = rows[:max(0, int(limit))]
            selected = {id(item) for item in rows}
            self._inbound = deque(
                item for item in self._inbound if id(item) not in selected
            )
            self._outbound = deque(
                item for item in self._outbound if id(item) not in selected
            )
            return rows

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._inbound) + len(self._outbound)
