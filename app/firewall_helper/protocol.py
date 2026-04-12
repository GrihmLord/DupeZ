# app/firewall_helper/protocol.py
"""
IPC protocol for DupeZ split-elevation architecture (ADR-0001 §4.2).

Design goals:
    * Small, versioned, line-delimited JSON for control-plane messages.
    * Request/response correlated by monotonic request_id.
    * No packet data ever crosses this protocol — packets stay in-helper.
    * Explicit opcode allow-list on server side (defence in depth vs any
      compromise of the main GUI process).

Frame format:
    <JSON payload>\n

Every frame is a single JSON object, UTF-8 encoded, terminated by LF.
The server reads until LF, parses JSON, dispatches, and writes a single
response frame terminated by LF.

Max frame size enforced at 64 KiB — we never send packet bodies here, so
this is plenty for control messages.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 64 * 1024
FRAME_TERMINATOR = b"\n"

# ── Opcodes (control plane only — no packet ops on this wire) ───────────

OP_PING = "ping"
OP_INITIALIZE = "initialize"
OP_START = "start"
OP_STOP = "stop"
OP_DISRUPT_DEVICE = "disrupt_device"
OP_STOP_DEVICE = "stop_device"
OP_STOP_ALL = "stop_all_devices"
OP_GET_DISRUPTED_DEVICES = "get_disrupted_devices"
OP_GET_DEVICE_STATUS = "get_device_status"
OP_GET_STATUS = "get_status"
OP_GET_ENGINE_STATS = "get_engine_stats"
OP_HOTKEY_TRIGGER = "hotkey_trigger"
OP_SHUTDOWN = "shutdown"

# Firewall blocker (netsh) ops — also admin-required, so they live in
# the helper alongside WinDivert. See ADR-0001 §11 action item 12.
OP_BLOCK_DEVICE = "block_device"
OP_UNBLOCK_DEVICE = "unblock_device"
OP_IS_IP_BLOCKED = "is_ip_blocked"
OP_CLEAR_ALL_BLOCKS = "clear_all_blocks"
OP_GET_BLOCKED_IPS = "get_blocked_ips"

ALLOWED_OPS = frozenset({
    OP_PING,
    OP_INITIALIZE,
    OP_START,
    OP_STOP,
    OP_DISRUPT_DEVICE,
    OP_STOP_DEVICE,
    OP_STOP_ALL,
    OP_GET_DISRUPTED_DEVICES,
    OP_GET_DEVICE_STATUS,
    OP_GET_STATUS,
    OP_GET_ENGINE_STATS,
    OP_HOTKEY_TRIGGER,
    OP_SHUTDOWN,
    OP_BLOCK_DEVICE,
    OP_UNBLOCK_DEVICE,
    OP_IS_IP_BLOCKED,
    OP_CLEAR_ALL_BLOCKS,
    OP_GET_BLOCKED_IPS,
})

# ── Error codes ─────────────────────────────────────────────────────────

ERR_NONE = 0
ERR_UNKNOWN_OP = 1
ERR_BAD_REQUEST = 2
ERR_INTERNAL = 3
ERR_NOT_READY = 4
ERR_TIMEOUT = 5


# ── Request / response dataclasses ──────────────────────────────────────

_id_lock = threading.Lock()
_next_id = 0


def next_request_id() -> int:
    """Thread-safe monotonic request id allocator."""
    global _next_id
    with _id_lock:
        _next_id += 1
        return _next_id


@dataclass
class Request:
    op: str
    request_id: int = field(default_factory=next_request_id)
    args: Dict[str, Any] = field(default_factory=dict)
    version: int = PROTOCOL_VERSION

    def encode(self) -> bytes:
        return (json.dumps(asdict(self), separators=(",", ":")) + "\n").encode("utf-8")

    @staticmethod
    def decode(raw: bytes) -> "Request":
        if len(raw) > MAX_FRAME_BYTES:
            raise ValueError(f"request frame too large: {len(raw)} bytes")
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("request frame must be JSON object")
        op = obj.get("op")
        if op not in ALLOWED_OPS:
            raise ValueError(f"unknown or disallowed op: {op!r}")
        return Request(
            op=op,
            request_id=int(obj.get("request_id", 0)),
            args=obj.get("args") or {},
            version=int(obj.get("version", PROTOCOL_VERSION)),
        )


@dataclass
class Response:
    request_id: int
    ok: bool
    result: Any = None
    error_code: int = ERR_NONE
    error_message: str = ""
    version: int = PROTOCOL_VERSION

    def encode(self) -> bytes:
        return (json.dumps(asdict(self), separators=(",", ":")) + "\n").encode("utf-8")

    @staticmethod
    def decode(raw: bytes) -> "Response":
        if len(raw) > MAX_FRAME_BYTES:
            raise ValueError(f"response frame too large: {len(raw)} bytes")
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("response frame must be JSON object")
        return Response(
            request_id=int(obj.get("request_id", 0)),
            ok=bool(obj.get("ok", False)),
            result=obj.get("result"),
            error_code=int(obj.get("error_code", ERR_NONE)),
            error_message=str(obj.get("error_message", "")),
            version=int(obj.get("version", PROTOCOL_VERSION)),
        )

    @classmethod
    def success(cls, request_id: int, result: Any = None) -> "Response":
        return cls(request_id=request_id, ok=True, result=result)

    @classmethod
    def failure(
        cls,
        request_id: int,
        error_code: int,
        error_message: str,
    ) -> "Response":
        return cls(
            request_id=request_id,
            ok=False,
            error_code=error_code,
            error_message=error_message,
        )
