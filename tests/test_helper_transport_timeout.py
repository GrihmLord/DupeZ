"""Bounded-response behavior for the split helper transport."""

from __future__ import annotations

import threading
import time

import pytest

from app.firewall_helper import transport
from app.firewall_helper.ipc_client import DisruptionManagerProxy
from app.firewall_helper.protocol import (
    OP_DISRUPT_DEVICE,
    OP_PING,
    Request,
    Response,
)


class _Win32File:
    def __init__(self, closed: threading.Event) -> None:
        self.closed = closed
        self.handles = []

    def CloseHandle(self, handle) -> None:
        self.handles.append(handle)
        self.closed.set()


def test_pipe_call_times_out_and_poisons_connection(monkeypatch) -> None:
    closed = threading.Event()
    win32file = _Win32File(closed)
    client = transport.PipeClient(shared_secret=b"x" * 32)
    client._handle = 123
    client._win32file = win32file
    client._pywintypes = object()
    monkeypatch.setattr(transport, "_write_frame", lambda *_args: None)

    def _blocked_read(*_args):
        closed.wait(timeout=1.0)
        return None

    monkeypatch.setattr(transport, "_read_frame", _blocked_read)
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="op=ping"):
        client.call(Request(op=OP_PING), timeout_ms=20)

    assert time.monotonic() - started < 0.5
    assert client._handle is None
    assert win32file.handles == [123]


def test_proxy_resets_poisoned_client_after_timeout() -> None:
    class _TimedOutClient:
        def __init__(self) -> None:
            self.closed = False

        def call(self, _request, *, timeout_ms):
            del timeout_ms
            raise TimeoutError("stalled helper")

        def close(self):
            self.closed = True

    client = _TimedOutClient()
    proxy = DisruptionManagerProxy()
    proxy._client = client
    proxy._connected = True
    proxy._helper_spawn_attempted = True

    with pytest.raises(TimeoutError, match="stalled helper"):
        proxy._call(OP_PING)

    assert client.closed is True
    assert proxy._client is None
    assert proxy._connected is False
    assert proxy._helper_spawn_attempted is False


def test_proxy_start_surfaces_helper_rejection(monkeypatch) -> None:
    proxy = DisruptionManagerProxy()
    monkeypatch.setattr(
        proxy,
        "_call",
        lambda _op: Response.failure(
            request_id=1,
            error_code=4,
            error_message="engine not ready",
        ),
    )

    with pytest.raises(RuntimeError, match="engine not ready"):
        proxy.start()


def test_proxy_uses_longer_bounded_timeout_for_disruption_start() -> None:
    calls = []

    class _Client:
        def call(self, request, *, timeout_ms):
            calls.append((request.op, timeout_ms))
            return Response.success(request.request_id, True)

    proxy = DisruptionManagerProxy()
    proxy._client = _Client()
    proxy._connected = True

    assert proxy.disrupt_device("192.168.1.42", ["lag"]) is True
    assert calls == [(OP_DISRUPT_DEVICE, transport.MUTATION_TIMEOUT_MS)]


def test_proxy_keeps_status_queries_on_short_timeout() -> None:
    calls = []

    class _Client:
        def call(self, request, *, timeout_ms):
            calls.append((request.op, timeout_ms))
            return Response.success(request.request_id, {})

    proxy = DisruptionManagerProxy()
    proxy._client = _Client()
    proxy._connected = True

    proxy._call(OP_PING)

    assert calls == [(OP_PING, transport.FRAME_TIMEOUT_MS)]


def test_proxy_state_getter_never_turns_transport_failure_into_empty_state(
    monkeypatch,
) -> None:
    proxy = DisruptionManagerProxy()
    monkeypatch.setattr(
        proxy,
        "_call",
        lambda _op: (_ for _ in ()).throw(TimeoutError("helper stalled")),
    )

    with pytest.raises(TimeoutError, match="helper stalled"):
        proxy.get_disrupted_devices()
