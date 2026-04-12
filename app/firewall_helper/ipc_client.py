# app/firewall_helper/ipc_client.py
"""
DisruptionManagerProxy — main-process drop-in replacement for
`app.firewall.clumsy_network_disruptor.disruption_manager` when
DUPEZ_ARCH=split.

Every method maps 1:1 to the in-process manager's API surface so that
`app/core/controller.py` can stay agnostic to transport. Each call:

    1. Builds a Request dataclass.
    2. Sends it via PipeClient.call().
    3. Unwraps the Response and returns result (or default on error).

Lazy-initialised singleton via get_proxy_manager(). The first call
spawns the helper (elevation bootstrap — wired up in Day 4, stubbed now)
and connects the pipe.

Day 1 status: this file is complete on the wire, but `_ensure_helper()`
currently only connects to an already-running helper. The elevation
bootstrap (ShellExecuteW runas + Job object) lands in Day 4 of the
ADR-0001 sprint. Until then, `DUPEZ_ARCH=split` requires the helper to
be started manually for testing — which is exactly what we want for
Day 1: zero changes to the production path.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from app.firewall_helper.protocol import (
    ERR_NONE,
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
from app.firewall_helper.transport import PipeClient

log = logging.getLogger(__name__)


class DisruptionManagerProxy:
    """Client-side façade with the same shape as the in-process manager.

    Matches the surface in app/core/controller.py:
        initialize()
        start()
        stop()
        disrupt_device(ip, methods, params, **kwargs) -> bool
        stop_device(ip) -> bool
        stop_all_devices() -> bool
        get_disrupted_devices() -> list[str]
        get_device_status(ip) -> dict
        get_status() -> dict
        get_engine_stats() -> dict
    """

    def __init__(self) -> None:
        self._client: Optional[PipeClient] = None
        self._lock = threading.Lock()
        self._connected = False
        # Spawn idempotency: once we've called ensure_helper_running() in
        # this process lifetime, never call it again. If the first spawn
        # succeeded the helper is still running (it watches parent PID);
        # if it failed, re-spawning would just prompt UAC again and hit
        # the same error. A second helper also collides on the named pipe
        # (FILE_FLAG_FIRST_PIPE_INSTANCE / max_instances=1 → ERROR 231).
        self._helper_spawn_attempted = False

    # ── Lifecycle ──────────────────────────────────────────────────

    def _ensure_helper(self) -> None:
        """Ensure the IPC client is connected to a running helper.

        Day 4: try to connect first (helper may already be running from a
        previous session or a manual launch). If connection fails, spawn
        the helper using the resolved elevation strategy (runas or
        scheduled_task), then retry the handshake.
        """
        if self._connected:
            return
        with self._lock:
            if self._connected:
                return

            import time as _time

            # First attempt: connect to any existing helper (previous
            # session or prior initialize() call in this session).
            self._client = PipeClient()
            try:
                self._client.connect(timeout_ms=1500)
                resp = self._client.call(Request(op=OP_PING))
                if resp.ok:
                    self._connected = True
                    log.info("DisruptionManagerProxy connected to existing helper")
                    return
            except Exception as e:
                log.info("no helper on pipe yet (%s)", e)

            # Spawn the helper — but only once per GUI process lifetime.
            # If a prior initialize() already attempted a spawn, don't
            # prompt UAC a second time; just keep retrying the connect
            # against the (presumably still-booting) existing helper.
            if not self._helper_spawn_attempted:
                try:
                    from app.firewall_helper.elevation import (
                        ElevationError,
                        ensure_helper_running,
                    )
                except Exception as e:
                    raise RuntimeError(f"elevation module unavailable: {e}") from e

                self._helper_spawn_attempted = True
                try:
                    ensure_helper_running()
                except ElevationError as e:
                    raise RuntimeError(f"helper elevation failed: {e}") from e
            else:
                log.info(
                    "helper spawn already attempted this session — "
                    "will only retry connect, not re-prompt UAC"
                )

            # Wait for the pipe to appear (helper boot + engine init).
            deadline = _time.monotonic() + 15.0
            last_err: Optional[Exception] = None
            while _time.monotonic() < deadline:
                try:
                    self._client = PipeClient()
                    self._client.connect(timeout_ms=2000)
                    resp = self._client.call(Request(op=OP_PING))
                    if resp.ok:
                        self._connected = True
                        log.info("DisruptionManagerProxy connected to new helper")
                        return
                    last_err = RuntimeError(resp.error_message or "ping failed")
                except Exception as e:
                    last_err = e
                _time.sleep(0.25)
            raise RuntimeError(
                f"helper did not become ready within 15s: {last_err}"
            )

    def _call(self, op: str, args: Optional[Dict[str, Any]] = None) -> Response:
        self._ensure_helper()
        assert self._client is not None
        request = Request(op=op, args=args or {})
        return self._client.call(request)

    # ── API — matches in-process manager 1:1 ───────────────────────

    def initialize(self) -> bool:
        try:
            resp = self._call(OP_INITIALIZE)
            return bool(resp.ok and resp.result)
        except Exception as e:
            log.error("proxy.initialize failed: %s", e)
            return False

    def start(self) -> None:
        """Activate the manager. Void-style to match the real manager's
        clean-interface contract — returns None; raises on hard failure."""
        try:
            resp = self._call(OP_START)
            if not resp.ok:
                log.error("proxy.start failed: %s", resp.error_message)
        except Exception as e:
            log.error("proxy.start failed: %s", e)

    def stop(self) -> None:
        """Deactivate the manager. Void-style to match the real contract."""
        try:
            resp = self._call(OP_STOP)
            if not resp.ok:
                log.error("proxy.stop failed: %s", resp.error_message)
        except Exception as e:
            log.error("proxy.stop failed: %s", e)

    def disrupt_device(
        self,
        ip: str,
        methods: Optional[List[str]] = None,
        params: Optional[Dict] = None,
        **kwargs: Any,
    ) -> bool:
        try:
            args = {
                "ip": ip,
                "methods": methods,
                "params": params,
                "kwargs": kwargs,
            }
            resp = self._call(OP_DISRUPT_DEVICE, args)
            return bool(resp.ok and resp.result)
        except Exception as e:
            log.error("proxy.disrupt_device failed: %s", e)
            return False

    def stop_device(self, ip: str) -> bool:
        try:
            resp = self._call(OP_STOP_DEVICE, {"ip": ip})
            return bool(resp.ok and resp.result)
        except Exception as e:
            log.error("proxy.stop_device failed: %s", e)
            return False

    def stop_all_devices(self) -> bool:
        try:
            resp = self._call(OP_STOP_ALL)
            return bool(resp.ok and resp.result)
        except Exception as e:
            log.error("proxy.stop_all_devices failed: %s", e)
            return False

    def get_disrupted_devices(self) -> List[str]:
        try:
            resp = self._call(OP_GET_DISRUPTED_DEVICES)
            if resp.ok and isinstance(resp.result, list):
                return [str(x) for x in resp.result]
            return []
        except Exception as e:
            log.error("proxy.get_disrupted_devices failed: %s", e)
            return []

    def get_device_status(self, ip: str) -> Dict:
        try:
            resp = self._call(OP_GET_DEVICE_STATUS, {"ip": ip})
            if resp.ok and isinstance(resp.result, dict):
                return resp.result
            return {}
        except Exception as e:
            log.error("proxy.get_device_status failed: %s", e)
            return {}

    def get_status(self) -> Dict:
        try:
            resp = self._call(OP_GET_STATUS)
            if resp.ok and isinstance(resp.result, dict):
                return resp.result
            return {}
        except Exception as e:
            log.error("proxy.get_status failed: %s", e)
            return {}

    def get_engine_stats(self) -> Dict:
        try:
            resp = self._call(OP_GET_ENGINE_STATS)
            if resp.ok and isinstance(resp.result, dict):
                return resp.result
            return {}
        except Exception as e:
            log.error("proxy.get_engine_stats failed: %s", e)
            return {}

    def hotkey_trigger(self, action: str, payload: Optional[Dict] = None) -> bool:
        """Recorder / GodMode hotkey bridge — main-side global hook fires
        this to the helper's module chain. Budget: p999 < 100 µs, which is
        negligible against the ~100 ms human-perception floor."""
        try:
            resp = self._call(
                OP_HOTKEY_TRIGGER,
                {"action": action, "payload": payload or {}},
            )
            return bool(resp.ok)
        except Exception as e:
            log.error("proxy.hotkey_trigger failed: %s", e)
            return False

    # ── Blocker (netsh) proxy methods ──────────────────────────────

    def block_device(self, ip: str, block: bool = True) -> bool:
        try:
            op = OP_BLOCK_DEVICE if block else OP_UNBLOCK_DEVICE
            resp = self._call(op, {"ip": ip})
            return bool(resp.ok and resp.result)
        except Exception as e:
            log.error("proxy.block_device failed: %s", e)
            return False

    def unblock_device(self, ip: str) -> bool:
        return self.block_device(ip, block=False)

    def is_ip_blocked(self, ip: str) -> bool:
        try:
            resp = self._call(OP_IS_IP_BLOCKED, {"ip": ip})
            return bool(resp.ok and resp.result)
        except Exception as e:
            log.error("proxy.is_ip_blocked failed: %s", e)
            return False

    def clear_all_dupez_blocks(self) -> bool:
        try:
            resp = self._call(OP_CLEAR_ALL_BLOCKS)
            return bool(resp.ok and resp.result)
        except Exception as e:
            log.error("proxy.clear_all_dupez_blocks failed: %s", e)
            return False

    def get_blocked_ips(self) -> List[str]:
        try:
            resp = self._call(OP_GET_BLOCKED_IPS)
            if resp.ok and isinstance(resp.result, list):
                return [str(x) for x in resp.result]
            return []
        except Exception as e:
            log.error("proxy.get_blocked_ips failed: %s", e)
            return []

    def shutdown_helper(self) -> None:
        """Ask the helper to exit cleanly. Used on GUI shutdown."""
        try:
            self._call(OP_SHUTDOWN)
        except Exception:
            pass
        if self._client is not None:
            self._client.close()
            self._client = None
        self._connected = False


# ── Singleton accessor ─────────────────────────────────────────────────

_proxy_singleton: Optional[DisruptionManagerProxy] = None
_proxy_lock = threading.Lock()


def get_proxy_manager() -> DisruptionManagerProxy:
    global _proxy_singleton
    if _proxy_singleton is None:
        with _proxy_lock:
            if _proxy_singleton is None:
                _proxy_singleton = DisruptionManagerProxy()
    return _proxy_singleton
