# app/firewall_helper/server.py
"""
Helper-side request dispatcher.

This module lives IN THE HELPER PROCESS. It owns the real
`disruption_manager` singleton from `app.firewall.clumsy_network_disruptor`
(which in turn owns the WinDivert handle and the entire module chain).
Every IPC request is translated into a direct method call on that
singleton — so the hot path is bit-for-bit identical to `inproc` mode.

Critical invariant (ADR-0001 §1.2):
    The module chain runs inside this process. No packet bodies cross the
    IPC boundary. The only things that cross are small JSON control
    messages at ~10 Hz.

Day 1 status: handler table is complete, but the server is not yet wired
into a real helper entry point. `dupez_helper.py` (next file) launches
this with stub initialization. Day 2 will replace the stubbed imports
with real ones and add crash-safe lifecycle handling.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional

from app.firewall_helper.protocol import (
    ERR_BAD_REQUEST,
    ERR_INTERNAL,
    ERR_UNKNOWN_OP,
    OP_BLOCK_DEVICE,
    OP_CLEAR_ALL_BLOCKS,
    OP_DISRUPT_DEVICE,
    OP_GET_BLOCKED_IPS,
    OP_GET_DEVICE_STATUS,
    OP_GET_DISRUPTED_DEVICES,
    OP_GET_ENGINE_STATS,
    OP_GET_STATUS,
    OP_HOTKEY_TRIGGER,
    OP_INITIALIZE,
    OP_IS_IP_BLOCKED,
    OP_PING,
    OP_SHUTDOWN,
    OP_START,
    OP_STOP,
    OP_STOP_ALL,
    OP_STOP_DEVICE,
    OP_UNBLOCK_DEVICE,
    Request,
    Response,
)
from app.firewall_helper.transport import PipeServer

log = logging.getLogger(__name__)


class HelperDispatcher:
    """Translates IPC requests into disruption_manager method calls.

    The `disruption_manager` reference is injected at construction time
    so we can stub it in unit tests without importing WinDivert.
    """

    def __init__(
        self,
        disruption_manager: Any,
        blocker_module: Any = None,
    ) -> None:
        self._dm = disruption_manager
        self._blocker = blocker_module  # Optional: None => blocker ops noop
        self._shutdown_event = threading.Event()
        self._handlers: Dict[str, Callable[[Request], Response]] = {
            OP_PING: self._h_ping,
            OP_INITIALIZE: self._h_initialize,
            OP_START: self._h_start,
            OP_STOP: self._h_stop,
            OP_DISRUPT_DEVICE: self._h_disrupt_device,
            OP_STOP_DEVICE: self._h_stop_device,
            OP_STOP_ALL: self._h_stop_all,
            OP_GET_DISRUPTED_DEVICES: self._h_get_disrupted,
            OP_GET_DEVICE_STATUS: self._h_get_device_status,
            OP_GET_STATUS: self._h_get_status,
            OP_GET_ENGINE_STATS: self._h_get_engine_stats,
            OP_HOTKEY_TRIGGER: self._h_hotkey_trigger,
            OP_SHUTDOWN: self._h_shutdown,
            OP_BLOCK_DEVICE: self._h_block_device,
            OP_UNBLOCK_DEVICE: self._h_unblock_device,
            OP_IS_IP_BLOCKED: self._h_is_ip_blocked,
            OP_CLEAR_ALL_BLOCKS: self._h_clear_all_blocks,
            OP_GET_BLOCKED_IPS: self._h_get_blocked_ips,
        }

    @property
    def shutdown_event(self) -> threading.Event:
        return self._shutdown_event

    def dispatch(self, request: Request) -> Response:
        handler = self._handlers.get(request.op)
        if handler is None:
            return Response.failure(
                request_id=request.request_id,
                error_code=ERR_UNKNOWN_OP,
                error_message=f"unknown op: {request.op}",
            )
        try:
            return handler(request)
        except Exception as e:
            log.exception("dispatcher error on op=%s", request.op)
            return Response.failure(
                request_id=request.request_id,
                error_code=ERR_INTERNAL,
                error_message=f"{type(e).__name__}: {e}",
            )

    # ── Handlers ───────────────────────────────────────────────────

    def _h_ping(self, req: Request) -> Response:
        return Response.success(req.request_id, "pong")

    def _h_initialize(self, req: Request) -> Response:
        # initialize() returns bool per the real manager contract.
        return Response.success(req.request_id, bool(self._dm.initialize()))

    def _h_start(self, req: Request) -> Response:
        # The real manager's start() is a void method (returns None).
        # Treat "no exception raised" as success.
        result = self._dm.start()
        return Response.success(req.request_id, True if result is None else bool(result))

    def _h_stop(self, req: Request) -> Response:
        # Same void-method treatment as start().
        result = self._dm.stop()
        return Response.success(req.request_id, True if result is None else bool(result))

    def _h_disrupt_device(self, req: Request) -> Response:
        args = req.args or {}
        ip = args.get("ip")
        if not isinstance(ip, str) or not ip:
            return Response.failure(
                req.request_id, ERR_BAD_REQUEST, "missing 'ip'"
            )
        methods = args.get("methods")
        params = args.get("params")
        kwargs = args.get("kwargs") or {}
        if not isinstance(kwargs, dict):
            kwargs = {}
        result = self._dm.disrupt_device(ip, methods, params, **kwargs)
        return Response.success(req.request_id, bool(result))

    def _h_stop_device(self, req: Request) -> Response:
        ip = (req.args or {}).get("ip")
        if not isinstance(ip, str) or not ip:
            return Response.failure(
                req.request_id, ERR_BAD_REQUEST, "missing 'ip'"
            )
        return Response.success(req.request_id, bool(self._dm.stop_device(ip)))

    def _h_stop_all(self, req: Request) -> Response:
        return Response.success(
            req.request_id, bool(self._dm.stop_all_devices())
        )

    def _h_get_disrupted(self, req: Request) -> Response:
        return Response.success(
            req.request_id, list(self._dm.get_disrupted_devices())
        )

    def _h_get_device_status(self, req: Request) -> Response:
        ip = (req.args or {}).get("ip")
        if not isinstance(ip, str) or not ip:
            return Response.failure(
                req.request_id, ERR_BAD_REQUEST, "missing 'ip'"
            )
        return Response.success(req.request_id, dict(self._dm.get_device_status(ip)))

    def _h_get_status(self, req: Request) -> Response:
        return Response.success(req.request_id, dict(self._dm.get_status()))

    def _h_get_engine_stats(self, req: Request) -> Response:
        return Response.success(req.request_id, dict(self._dm.get_engine_stats()))

    def _h_hotkey_trigger(self, req: Request) -> Response:
        action = (req.args or {}).get("action")
        payload = (req.args or {}).get("payload") or {}
        if not isinstance(action, str) or not action:
            return Response.failure(
                req.request_id, ERR_BAD_REQUEST, "missing 'action'"
            )
        # Route to disruption_manager if it exposes a hotkey API; Day 2
        # will wire this to the GodMode recorder hook directly.
        hook = getattr(self._dm, "hotkey_trigger", None)
        if callable(hook):
            result = hook(action, payload)
            return Response.success(req.request_id, bool(result))
        # Safe no-op in Day 1 — GUI-side recorder still works in inproc.
        return Response.success(req.request_id, False)

    def _h_shutdown(self, req: Request) -> Response:
        self._shutdown_event.set()
        return Response.success(req.request_id, True)

    # ── Blocker ops (netsh) ────────────────────────────────────────

    def _require_blocker(self, req: Request) -> Optional[Response]:
        if self._blocker is None:
            return Response.failure(
                req.request_id,
                ERR_INTERNAL,
                "blocker module not wired into dispatcher",
            )
        return None

    def _h_block_device(self, req: Request) -> Response:
        err = self._require_blocker(req)
        if err is not None:
            return err
        ip = (req.args or {}).get("ip")
        if not isinstance(ip, str) or not ip:
            return Response.failure(
                req.request_id, ERR_BAD_REQUEST, "missing 'ip'"
            )
        result = self._blocker.block_device(ip, block=True)
        return Response.success(req.request_id, bool(result))

    def _h_unblock_device(self, req: Request) -> Response:
        err = self._require_blocker(req)
        if err is not None:
            return err
        ip = (req.args or {}).get("ip")
        if not isinstance(ip, str) or not ip:
            return Response.failure(
                req.request_id, ERR_BAD_REQUEST, "missing 'ip'"
            )
        result = self._blocker.block_device(ip, block=False)
        return Response.success(req.request_id, bool(result))

    def _h_is_ip_blocked(self, req: Request) -> Response:
        err = self._require_blocker(req)
        if err is not None:
            return err
        ip = (req.args or {}).get("ip")
        if not isinstance(ip, str) or not ip:
            return Response.failure(
                req.request_id, ERR_BAD_REQUEST, "missing 'ip'"
            )
        return Response.success(req.request_id, bool(self._blocker.is_ip_blocked(ip)))

    def _h_clear_all_blocks(self, req: Request) -> Response:
        err = self._require_blocker(req)
        if err is not None:
            return err
        return Response.success(
            req.request_id, bool(self._blocker.clear_all_dupez_blocks())
        )

    def _h_get_blocked_ips(self, req: Request) -> Response:
        err = self._require_blocker(req)
        if err is not None:
            return err
        return Response.success(
            req.request_id, list(self._blocker.get_blocked_ips())
        )


def run_helper_server(
    disruption_manager: Any,
    blocker_module: Any = None,
    shared_secret: Optional[bytes] = None,
) -> HelperDispatcher:
    """Start the pipe server and return the dispatcher.

    Caller is responsible for waiting on `dispatcher.shutdown_event`
    before tearing down the process. See `dupez_helper.py`.

    Auth:
        ``shared_secret`` MUST be a 32-byte token that the parent GUI
        wrote to the sentinel path (see auth.write_token_sentinel).
        If not provided, we attempt to read-and-consume the sentinel
        ourselves. Refuses to start without a secret — an
        unauthenticated helper is a local privilege-escalation pipe.
    """
    if shared_secret is None:
        from app.firewall_helper.auth import read_and_consume_token_sentinel
        shared_secret = read_and_consume_token_sentinel()
    if not shared_secret or len(shared_secret) != 32:
        raise RuntimeError(
            "run_helper_server refuses to start without a 32-byte shared "
            "secret. The parent GUI must call auth.generate_token() + "
            "auth.write_token_sentinel() before spawning the helper. "
            "Running without auth would expose every ALLOWED_OPS opcode "
            "to every Medium-IL process on the session."
        )
    dispatcher = HelperDispatcher(disruption_manager, blocker_module=blocker_module)
    server = PipeServer(handler=dispatcher.dispatch, shared_secret=shared_secret)
    server.start()
    log.info("run_helper_server: PipeServer started, dispatcher ready")
    return dispatcher
