"""One direction resolver for already-normalized WinDivert addresses."""

from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = ["PacketDirection", "DirectionResolver"]


class PacketDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class DirectionResolver:
    """Resolve capture direction after the Native engine's layer correction."""

    @staticmethod
    def resolve(address: Any) -> PacketDirection:
        return (
            PacketDirection.OUTBOUND
            if bool(getattr(address, "Outbound", False))
            else PacketDirection.INBOUND
        )
