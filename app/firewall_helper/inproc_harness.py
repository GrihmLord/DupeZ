# app/firewall_helper/inproc_harness.py
"""
In-process harness for the HelperDispatcher.

This module lets us exercise the full request/response path WITHOUT a
real named pipe, which means:

* CI on Linux can run the smoke tests without pywin32.
* Integration tests can verify dispatcher wiring against a lightweight
  fake disruption_manager.
* Day 5 latency regression benchmark can reuse the same harness to
  measure overhead of the JSON encode/decode roundtrip in isolation.

This is NOT a production code path. It's only imported by tests.

Usage:
    from app.firewall_helper.inproc_harness import LoopbackClient
    client = LoopbackClient(fake_disruption_manager)
    assert client.initialize() is True
    assert client.disrupt_device("10.0.0.5", ["lag"]) is True
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.firewall_helper.ipc_client import DisruptionManagerProxy
from app.firewall_helper.protocol import Request, Response
from app.firewall_helper.server import HelperDispatcher


class _LoopbackPipeClient:
    """Stand-in for PipeClient that shortcuts directly to a dispatcher.

    Reuses the exact same encode/decode path as the real pipe so the
    harness exercises every byte of the production serialization.
    """

    def __init__(self, dispatcher: HelperDispatcher) -> None:
        self._dispatcher = dispatcher

    def connect(self, timeout_ms: int = 0) -> None:  # pragma: no cover
        return None

    def close(self) -> None:  # pragma: no cover
        return None

    def call(self, request: Request) -> Response:
        # Roundtrip through encode/decode so any protocol bugs surface
        # in the harness exactly the same way they would on the wire.
        wire = request.encode().rstrip(b"\n")
        decoded_req = Request.decode(wire)
        response = self._dispatcher.dispatch(decoded_req)
        wire_resp = response.encode().rstrip(b"\n")
        return Response.decode(wire_resp)


class LoopbackClient(DisruptionManagerProxy):
    """DisruptionManagerProxy subclass that skips the real pipe.

    Lets tests drive the full proxy API (initialize, disrupt_device,
    get_engine_stats, etc.) against a fake manager with zero Windows
    dependencies.
    """

    def __init__(self, disruption_manager: Any) -> None:
        super().__init__()
        self._dispatcher = HelperDispatcher(disruption_manager)
        self._client = _LoopbackPipeClient(self._dispatcher)
        self._connected = True  # bypass _ensure_helper

    def _ensure_helper(self) -> None:
        # No-op: the in-process dispatcher is always "connected".
        return None

    @property
    def dispatcher(self) -> HelperDispatcher:
        return self._dispatcher
