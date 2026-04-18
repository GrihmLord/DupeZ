#!/usr/bin/env python3
"""
Native WinDivert Engine — direct packet manipulation without clumsy.exe.

Replaces clumsy.exe GUI automation with direct WinDivert.dll calls via ctypes.
No GUI, no window, no flash. Just packet interception and manipulation.

Implements the same disruption methods as clumsy:
  - drop:       Randomly drop packets (chance %)
  - lag:        Buffer packets and release after delay (ms)
  - throttle:   Only pass packets at intervals (frame ms, chance %)
  - duplicate:  Send packets multiple times (count, chance %)
  - ood:        Reorder packets randomly (chance %)
  - corrupt:    Flip random bits in payload (chance %)
  - bandwidth:  Limit throughput to X KB/s
  - disconnect: Drop nearly all packets (95%+ drop)
  - rst:        Inject TCP RST to kill connections (chance %)

WinDivert API (loaded from WinDivert.dll):
  WinDivertOpen(filter, layer, priority, flags) → HANDLE
  WinDivertRecv(handle, packet, len, recvLen, addr) → BOOL
  WinDivertSend(handle, packet, len, sendLen, addr) → BOOL
  WinDivertClose(handle) → BOOL
  WinDivertHelperCalcChecksums(packet, len, addr, flags) → BOOL
"""

from __future__ import annotations

import ctypes
import os
import random
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from ctypes import wintypes
from typing import Any, Callable, Dict, List, Optional

from app.logs.logger import log_info, log_error, log_warning
from app.utils.helpers import _NO_WINDOW

# safe_subprocess is loaded lazily — this module is Windows-only and we
# want imports to succeed on non-Windows hosts running unit tests.
try:
    from app.core import safe_subprocess as _safe_sp
    from app.core.safe_subprocess import SafeSubprocessError as _SafeSpErr
except Exception:  # pragma: no cover
    _safe_sp = None
    _SafeSpErr = Exception  # type: ignore[assignment,misc]

# Recorder hotkeys — event tagging during packet recording
try:
    from app.firewall.recorder_hotkeys import RecorderHotkeys
    _RECORDER_HOTKEYS_AVAILABLE = True
except ImportError:
    _RECORDER_HOTKEYS_AVAILABLE = False

# Traffic pattern analyzer — passive observer for live stats & game state
try:
    from app.ai.traffic_analyzer import TrafficPatternAnalyzer
    _TRAFFIC_ANALYZER_AVAILABLE = True
except ImportError:
    _TRAFFIC_ANALYZER_AVAILABLE = False

# Statistical models — Phase 1 v5 (lazy import to avoid circular deps)
_STATISTICAL_MODULES_LOADED = False
_STATISTICAL_MODULE_MAP = {}
_STATISTICAL_FLUSH_MODULES = ()
WINDIVERT_LAYER_NETWORK         = 0
WINDIVERT_LAYER_NETWORK_FORWARD = 1
WINDIVERT_FLAG_NONE             = 0

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PACKET_SIZE      = 65535  # max IP packet

# TCP flags offset in TCP header (byte 13, counting from TCP header start)
TCP_FLAG_RST = 0x04

# WinDivertOpen error → human hint mapping
_WINDIVERT_ERR_HINTS = {
    2: "WinDivert64.sys not found", 5: "not running as administrator",
    87: "invalid filter syntax", 577: "driver not signed / Secure Boot issue",
    1275: "driver blocked by system policy",
}

__all__ = [
    "WINDIVERT_LAYER_NETWORK",
    "WINDIVERT_LAYER_NETWORK_FORWARD",
    "WINDIVERT_FLAG_NONE",
    "INVALID_HANDLE_VALUE",
    "MAX_PACKET_SIZE",
    "TCP_FLAG_RST",
    "WINDIVERT_DATA_NETWORK",
    "WINDIVERT_DATA_FLOW",
    "WINDIVERT_DATA_SOCKET",
    "WINDIVERT_DATA_REFLECT",
    "WINDIVERT_DATA_UNION",
    "WINDIVERT_ADDRESS",
    "WinDivertDLL",
    "DisruptionModule",
    "NativeWinDivertEngine",
]


class WINDIVERT_DATA_NETWORK(ctypes.Structure):
    _fields_ = [
        ("IfIdx",    wintypes.UINT),
        ("SubIfIdx", wintypes.UINT),
    ]

class WINDIVERT_DATA_FLOW(ctypes.Structure):
    _fields_ = [
        ("EndpointId",  ctypes.c_uint64),
        ("ParentEndpointId", ctypes.c_uint64),
        ("ProcessId",   wintypes.UINT),
        ("LocalAddr",   wintypes.UINT * 4),
        ("RemoteAddr",  wintypes.UINT * 4),
        ("LocalPort",   wintypes.WORD),
        ("RemotePort",  wintypes.WORD),
        ("Protocol",    ctypes.c_uint8),
    ]

# Socket data has identical layout to Flow data
WINDIVERT_DATA_SOCKET = WINDIVERT_DATA_FLOW

class WINDIVERT_DATA_REFLECT(ctypes.Structure):
    _fields_ = [
        ("Timestamp", ctypes.c_int64),
        ("ProcessId", wintypes.UINT),
        ("Layer",     wintypes.UINT),
        ("Flags",     ctypes.c_uint64),
        ("Priority",  ctypes.c_int16),
    ]

class WINDIVERT_DATA_UNION(ctypes.Union):
    _fields_ = [
        ("Network", WINDIVERT_DATA_NETWORK),
        ("Flow",    WINDIVERT_DATA_FLOW),
        ("Socket",  WINDIVERT_DATA_SOCKET),
        ("Reflect", WINDIVERT_DATA_REFLECT),
        ("Reserved", ctypes.c_uint8 * 64),
    ]

class WINDIVERT_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("Timestamp",  ctypes.c_int64),
        ("_bitfield",  wintypes.UINT),  # Layer(8), Event(8), flags(16)
        ("_reserved",  wintypes.UINT),
        ("Union",      WINDIVERT_DATA_UNION),
    ]

    @property
    def Layer(self) -> Any:
        return self._bitfield & 0xFF

    @property
    def Outbound(self) -> bool:
        # WinDivert 2.x bitfield layout (from windivert.h):
        #   Layer(8) | Event(8) | Sniffed(1) | Outbound(1) | Loopback(1) | ...
        # On little-endian x86, Outbound is bit 17.
        return bool(self._bitfield & (1 << 17))

    @Outbound.setter
    def Outbound(self, val) -> None:
        if val:
            self._bitfield |= (1 << 17)
        else:
            self._bitfield &= ~(1 << 17)

    @property
    def Loopback(self) -> bool:
        return bool(self._bitfield & (1 << 18))

    @property
    def IPv6(self) -> bool:
        return bool(self._bitfield & (1 << 20))


class WinDivertDLL:
    """Thin ctypes wrapper around WinDivert.dll functions."""

    def __init__(self, dll_path: str) -> None:
        self._dll = ctypes.WinDLL(dll_path)
        self.batch_available = False

        # WinDivertOpen
        self._dll.WinDivertOpen.argtypes = [
            ctypes.c_char_p,   # filter
            ctypes.c_int,      # layer
            ctypes.c_int16,    # priority
            ctypes.c_uint64,   # flags
        ]
        self._dll.WinDivertOpen.restype = wintypes.HANDLE

        # WinDivertRecv
        self._dll.WinDivertRecv.argtypes = [
            wintypes.HANDLE,    # handle
            ctypes.c_void_p,    # pPacket
            wintypes.UINT,      # packetLen
            ctypes.POINTER(wintypes.UINT),  # pRecvLen
            ctypes.POINTER(WINDIVERT_ADDRESS),  # pAddr
        ]
        self._dll.WinDivertRecv.restype = wintypes.BOOL

        # WinDivertSend
        self._dll.WinDivertSend.argtypes = [
            wintypes.HANDLE,    # handle
            ctypes.c_void_p,    # pPacket
            wintypes.UINT,      # packetLen
            ctypes.POINTER(wintypes.UINT),  # pSendLen
            ctypes.POINTER(WINDIVERT_ADDRESS),  # pAddr
        ]
        self._dll.WinDivertSend.restype = wintypes.BOOL

        # WinDivertClose
        self._dll.WinDivertClose.argtypes = [wintypes.HANDLE]
        self._dll.WinDivertClose.restype = wintypes.BOOL

        # WinDivertHelperCalcChecksums
        self._dll.WinDivertHelperCalcChecksums.argtypes = [
            ctypes.c_void_p,    # pPacket
            wintypes.UINT,      # packetLen
            ctypes.POINTER(WINDIVERT_ADDRESS),  # pAddr
            ctypes.c_uint64,    # flags
        ]
        self._dll.WinDivertHelperCalcChecksums.restype = wintypes.BOOL

        # Try to set up batch API
        self._setup_batch_api()

    def open(self, filter_str: str, layer: int = WINDIVERT_LAYER_NETWORK,
             priority: int = 0, flags: int = WINDIVERT_FLAG_NONE) -> None:
        return self._dll.WinDivertOpen(
            filter_str.encode('ascii'), layer, priority, flags
        )

    def recv(self, handle, packet_buf, buf_len, recv_len, addr):
        return self._dll.WinDivertRecv(handle, packet_buf, buf_len,
                                        recv_len, addr)

    def send(self, handle, packet_buf, pkt_len, send_len, addr):
        return self._dll.WinDivertSend(handle, packet_buf, pkt_len,
                                        send_len, addr)

    def close(self, handle):
        return self._dll.WinDivertClose(handle)

    # ── Batch API (WinDivert 2.x) ────────────────────────────
    # RecvEx/SendEx process up to 255 packets per syscall, dramatically
    # reducing kernel transitions on high-throughput DayZ streams.

    def recv_ex(self, handle, packet_buf, buf_len, recv_len, flags,
                addr_array, addr_len_ptr, overlapped=None) -> None:
        """WinDivertRecvEx — batch receive up to 255 packets.

        Args:
            packet_buf: Buffer for concatenated packet data
            buf_len: Size of packet_buf
            recv_len: Pointer to UINT receiving total bytes read
            flags: Reserved (must be 0)
            addr_array: Array of WINDIVERT_ADDRESS structs
            addr_len_ptr: Pointer to UINT with byte size of addr_array
                          (updated to actual bytes written)
            overlapped: Optional OVERLAPPED for async I/O (None = sync)

        Returns:
            True on success, False on failure.
        """
        try:
            fn = self._dll.WinDivertRecvEx
        except AttributeError:
            return False  # DLL doesn't have RecvEx — old version
        return fn(handle, packet_buf, buf_len, recv_len, flags,
                  addr_array, addr_len_ptr, overlapped)

    def send_ex(self, handle, packet_buf, pkt_len, send_len, flags,
                addr_array, addr_len, overlapped=None) -> None:
        """WinDivertSendEx — batch send multiple packets.

        Args:
            packet_buf: Buffer with concatenated packet data
            pkt_len: Total bytes in packet_buf
            send_len: Pointer to UINT receiving bytes sent
            flags: Reserved (must be 0)
            addr_array: Array of WINDIVERT_ADDRESS structs
            addr_len: Byte size of addr_array
            overlapped: Optional OVERLAPPED for async I/O (None = sync)

        Returns:
            True on success, False on failure.
        """
        try:
            fn = self._dll.WinDivertSendEx
        except AttributeError:
            return False
        return fn(handle, packet_buf, pkt_len, send_len, flags,
                  addr_array, addr_len, overlapped)

    def _setup_batch_api(self) -> None:
        """Set up argtypes/restype for RecvEx/SendEx if available."""
        try:
            self._dll.WinDivertRecvEx.argtypes = [
                wintypes.HANDLE,    # handle
                ctypes.c_void_p,    # pPacket
                wintypes.UINT,      # packetLen
                ctypes.POINTER(wintypes.UINT),  # pRecvLen
                ctypes.c_uint64,    # flags
                ctypes.c_void_p,    # pAddr (array)
                ctypes.POINTER(wintypes.UINT),  # pAddrLen
                ctypes.c_void_p,    # lpOverlapped
            ]
            self._dll.WinDivertRecvEx.restype = wintypes.BOOL

            self._dll.WinDivertSendEx.argtypes = [
                wintypes.HANDLE,    # handle
                ctypes.c_void_p,    # pPacket
                wintypes.UINT,      # packetLen
                ctypes.POINTER(wintypes.UINT),  # pSendLen
                ctypes.c_uint64,    # flags
                ctypes.c_void_p,    # pAddr (array)
                wintypes.UINT,      # addrLen
                ctypes.c_void_p,    # lpOverlapped
            ]
            self._dll.WinDivertSendEx.restype = wintypes.BOOL
            self.batch_available = True
            log_info("WinDivert batch API (RecvEx/SendEx) available")
        except AttributeError:
            self.batch_available = False
            log_info("WinDivert batch API not available — using single-packet mode")

    def calc_checksums(self, packet_buf, pkt_len, addr=None, flags=0):
        return self._dll.WinDivertHelperCalcChecksums(
            packet_buf, pkt_len, addr, flags
        )
DIR_BOTH: str = "both"       # Module processes packets in both directions
DIR_INBOUND: str = "inbound"   # Module only processes inbound packets (Outbound=False)
DIR_OUTBOUND: str = "outbound" # Module only processes outbound packets (Outbound=True)


class DisruptionModule:
    """Base class for packet disruption modules.

    Direction-aware: each module has a ``direction`` attribute that controls
    which packets it acts on.  The engine's packet loop checks this BEFORE
    calling ``process()``, so modules themselves don't need to inspect the
    address direction — they can assume every packet they see is in-scope.

    Direction mapping:
      "both"     → process all packets
      "inbound"  → only packets where addr.Outbound is False
      "outbound" → only packets where addr.Outbound is True

    Direction detection (two modes):

      REMOTE (NETWORK_FORWARD + ICS/hotspot — PS5, Xbox, remote PC):
        addr.Outbound is TRUE for ALL forwarded packets regardless of
        actual direction. Corrected via IPv4 header inspection:
          src_ip == target_ip → outbound (device → server)
          dst_ip == target_ip → inbound  (server → device)

      PC-LOCAL (NETWORK layer — DayZ on same machine):
        addr.Outbound is CORRECT — WinDivert knows true direction.
        target_ip = game server IP (not device IP).

      Correction happens BEFORE ``matches_direction()`` is called,
      so all modules get correct direction filtering automatically.
    """

    # Subclasses set this to their param prefix (e.g. "drop", "lag").
    # If set, __init__ checks for "{_direction_key}_direction" override.
    _direction_key: str = ""

    def __init__(self, params: dict) -> None:
        self.params = params
        # Per-module direction — check "{module}_direction" then global.
        if self._direction_key:
            self.direction = params.get(
                f"{self._direction_key}_direction",
                params.get("direction", DIR_BOTH))
        else:
            self.direction = params.get("direction", DIR_BOTH)

    def matches_direction(self, addr: WINDIVERT_ADDRESS) -> bool:
        """Check if this packet matches the module's direction filter.
        Called by the engine before process() — returns True if the
        module should act on this packet."""
        if self.direction == DIR_BOTH:
            return True
        if self.direction == DIR_OUTBOUND:
            return addr.Outbound
        if self.direction == DIR_INBOUND:
            return not addr.Outbound
        return True  # unknown → process

    @staticmethod
    def _roll(chance: int) -> bool:
        """Return True if a chance% roll succeeds. 100% is deterministic."""
        if chance <= 0:
            return False
        return chance >= 100 or random.random() * 100 < chance

    def process(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        send_fn: Callable[[bytearray, Any], None],
    ) -> bool:
        """Process a packet. Return True if packet was handled (sent or dropped).
        Return False to pass through to next module or default send."""
        return False

# ═══════════════════════════════════════════════════════════════════════
# Core disruption modules — extracted to app/firewall/modules/
# Imported lazily to break the circular dependency:
#   native_divert_engine → modules → native_divert_engine
# ═══════════════════════════════════════════════════════════════════════
MODULE_MAP: Dict[str, type] = {}
_MODULES_INITIALIZED = False


def _ensure_modules_loaded() -> None:
    """Lazily load all module classes and populate MODULE_MAP.

    Called once on first engine start.  Deferred import breaks the circular
    dependency between this module and app.firewall.modules.
    """
    global _MODULES_INITIALIZED, _STATISTICAL_MODULES_LOADED
    global _STATISTICAL_MODULE_MAP, _STATISTICAL_FLUSH_MODULES, _STEALTH_FLUSH_MODULES

    if _MODULES_INITIALIZED:
        return

    # Core modules
    from app.firewall.modules import CORE_MODULE_MAP
    MODULE_MAP.update(CORE_MODULE_MAP)

    # Statistical models (Phase 1 v5)
    try:
        from app.firewall.statistical_models import (
            STATISTICAL_MODULE_MAP, FLUSH_THREAD_MODULES)
        _STATISTICAL_MODULE_MAP = STATISTICAL_MODULE_MAP
        _STATISTICAL_FLUSH_MODULES = FLUSH_THREAD_MODULES
        MODULE_MAP.update(STATISTICAL_MODULE_MAP)
        _STATISTICAL_MODULES_LOADED = True
        log_info(f"Statistical models loaded: {list(STATISTICAL_MODULE_MAP.keys())}")
    except ImportError as e:
        log_info(f"Statistical models not available: {e}")
        _STATISTICAL_MODULES_LOADED = True

    # Tick-sync modules (Phase 3 v5)
    try:
        from app.firewall.tick_sync import TICK_SYNC_MODULE_MAP
        MODULE_MAP.update(TICK_SYNC_MODULE_MAP)
        log_info(f"Tick-sync models loaded: {list(TICK_SYNC_MODULE_MAP.keys())}")
    except ImportError as e:
        log_info(f"Tick-sync models not available: {e}")

    # Stealth modules (Phase 7 v5)
    try:
        from app.firewall.stealth import STEALTH_MODULE_MAP, STEALTH_FLUSH_MODULES as _sfm
        MODULE_MAP.update(STEALTH_MODULE_MAP)
        _STEALTH_FLUSH_MODULES = _sfm
        log_info(f"Stealth models loaded: {list(STEALTH_MODULE_MAP.keys())}")
    except ImportError as e:
        log_info(f"Stealth models not available: {e}")

    _MODULES_INITIALIZED = True
    log_info(f"Module registry: {list(MODULE_MAP.keys())}")


_STEALTH_FLUSH_MODULES: tuple = ()


class NativeWinDivertEngine:
    """Direct WinDivert packet engine — no clumsy.exe, no GUI, no window.

    Drop-in replacement for ClumsyEngine. Same interface:
      .start() → bool
      .stop()
      .alive → bool
      .pid → int (returns thread ID since there's no subprocess)
    """

    def __init__(self, dll_path: str, filter_str: str,
                 methods: list, params: dict) -> None:
        self.dll_path = dll_path
        # Validate filter string against allowlist before use
        try:
            from app.core.validation import validate_filter_string
            self.filter_str = validate_filter_string(filter_str)
        except (ValueError, ImportError) as e:
            log_error(f"NativeEngine: filter validation failed: {e} — using raw filter")
            self.filter_str = filter_str
        # Validate methods and params
        try:
            from app.core.validation import validate_methods, validate_params
            self.methods = validate_methods(methods)
            self.params = validate_params(params)
        except ImportError:
            self.methods = methods
            self.params = params

        self._divert = None       # WinDivertDLL instance
        self._handle = None       # WinDivert HANDLE
        self._thread = None       # Packet processing thread
        self._running = False
        self._modules = []        # Active disruption modules
        self._recorder_hotkeys = None  # RecorderHotkeys instance
        self._packets_processed = 0
        self._packets_dropped = 0
        self._packets_inbound = 0
        self._packets_outbound = 0
        self._packets_passed = 0

        # Pre-allocated send buffer — avoids per-packet ctypes allocation.
        # Protected by _send_lock since flush threads also call _send_packet.
        self._send_buf = (ctypes.c_uint8 * MAX_PACKET_SIZE)()
        self._send_len = wintypes.UINT(0)
        self._send_lock = threading.Lock()

        # ── Telemetry / ML data capture (opt-in) ──────────────────
        # When params["_record_episodes"] is truthy, the packet loop feeds
        # a FeatureExtractor and asynchronously writes feature-vector
        # windows plus cut_start/cut_end events to
        # app/data/episodes/episode_<tag>.jsonl. Off by default so the
        # hot path stays identical for users who don't opt in.
        self._feature_extractor = None
        self._episode_recorder = None
        # A2S probe — optional external oracle that auto-labels cut outcomes
        # when the server roster drops our character (P2 from competitive audit).
        self._a2s_probe = None
        self._a2s_auto_labeled: bool = False
        # Cut verifier — active ICMP/A2S liveness probe that flips the GUI
        # status light SEVERED when the target goes dark (P3).
        self._cut_verifier = None
        # Flush predictor (P5) — live countdown of safe cut window.
        # Lazy-init: None until first get_stats() call during a cut, so
        # sessions without a recording bucket don't pay import cost.
        self._flush_predictor = None
        # Server-IP auto-detect: forward-layer (hotspot) packet flow exposes
        # the remote endpoint (game server) as the non-target side of each
        # packet. We sample the first few outbound packets, pick the modal
        # remote on a UDP game port, and late-start the A2S probe.
        self._server_ip_hint: Optional[str] = None
        self._server_ip_candidates: Dict[str, int] = {}
        self._server_ip_resolved: bool = False
        self._server_ip_deadline_ts: float = 0.0  # set by start()
        self._window_interval_s: float = float(
            params.get("_window_interval_ms", 200)
        ) / 1000.0
        self._last_window_close: float = 0.0
        # Operator-supplied outcome for the currently-open cut. The GUI
        # "Mark dupe success/fail" button writes this; stop() flushes it
        # into the cut_end event so the survival trainer has a label.
        self._pending_cut_outcome: Optional[bool] = None
        if params.get("_record_episodes"):
            try:
                from app.ai.feature_extractor import FeatureExtractor
                from app.ai.episode_recorder import EpisodeRecorder
                self._feature_extractor = FeatureExtractor()
                self._episode_recorder = EpisodeRecorder(
                    session_tag=params.get("_episode_tag", "")
                )
            except Exception as exc:  # pragma: no cover
                log_warning(f"[EPISODE] Failed to initialize recorder: {exc}")
                self._feature_extractor = None
                self._episode_recorder = None

        # Target IP for stats reporting
        self.target_ip = params.get("_target_ip", "unknown")

        # Precomputed u32 form of target_ip for zero-allocation hot-path
        # direction detection on the FORWARD layer. Recomputed on every
        # start() so hot-reloads pick up a new target. 0 means "unset".
        self._target_ip_u32: int = 0
        try:
            if self.target_ip and self.target_ip != "unknown":
                self._target_ip_u32 = int.from_bytes(
                    socket.inet_aton(self.target_ip), "big")
        except OSError:
            self._target_ip_u32 = 0

        # Precompute layer mode flag so the hot path skips a dict lookup
        # per packet. Updated in start() if params mutate.
        self._use_local_layer: bool = bool(params.get("_network_local", False))

        # Traffic pattern analyzer — passive observer fed from packet loop
        self._traffic_analyzer: Optional[TrafficPatternAnalyzer] = None
        if _TRAFFIC_ANALYZER_AVAILABLE:
            try:
                self._traffic_analyzer = TrafficPatternAnalyzer(
                    window_sec=2.0, snapshot_interval=1.0)
                log_info("NativeEngine: TrafficPatternAnalyzer attached")
            except Exception as exc:
                log_error(f"NativeEngine: TrafficPatternAnalyzer init failed: {exc}")

        # Emulate subprocess-like interface for compatibility
        self._proc = self  # self acts as the "process"

    @property
    def pid(self) -> Any:
        """Return thread ID (no subprocess PID since we're native)."""
        if self._thread:
            return self._thread.ident
        return 0

    @property
    def alive(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def poll(self) -> Optional[int]:
        """Mimic subprocess.poll() — return None if alive, 0 if stopped."""
        if self.alive:
            return None
        return 0

    def get_stats(self) -> Dict:
        """Return live packet counters for this engine instance.

        Includes per-module stats for any module that implements ``get_stats()``.
        This surfaces God Mode classification, queue depth, flush counts, etc.
        """
        stats = {
            "packets_processed": self._packets_processed,
            "packets_dropped": self._packets_dropped,
            "packets_inbound": self._packets_inbound,
            "packets_outbound": self._packets_outbound,
            "packets_passed": self._packets_passed,
            "alive": self.alive,
            "target_ip": self.target_ip,
            "methods": list(self.methods),
        }
        # Collect per-module stats (godmode, lag, dupe, etc.)
        module_stats = {}
        for mod in self._modules:
            if hasattr(mod, 'get_stats'):
                try:
                    mod_name = mod.__class__.__name__
                    module_stats[mod_name] = mod.get_stats()
                except Exception as exc:
                    log_error(f"NativeEngine: {mod.__class__.__name__}.get_stats() failed: {exc}")
        if module_stats:
            stats["module_stats"] = module_stats
        # Attach traffic analyzer stats if available
        if self._traffic_analyzer is not None:
            try:
                stats["traffic_analysis"] = self._traffic_analyzer.get_stats()
            except Exception:
                pass
        # Attach cut verifier state (for GUI SEVERED/CONNECTED light)
        if self._cut_verifier is not None:
            try:
                stats["cut_state"] = self._cut_verifier.state().value
            except Exception:
                pass
        # Attach flush-prediction countdown if a DisconnectModule is
        # currently CUTTING. This is what the GUI renders as the
        # live HOLD / WARN / STOP_NOW badge.
        try:
            from app.firewall.modules.disconnect import (
                DisconnectModule, STATE_CUTTING,
            )
            _started_at = 0.0
            for mod in self._modules:
                if isinstance(mod, DisconnectModule) and mod.state == STATE_CUTTING:
                    _s = mod.stats().get("cut_started_at", 0.0)
                    if _s > 0.0:
                        _started_at = max(_started_at, _s)
            if _started_at > 0.0:
                import time as _t
                elapsed_s = max(0.0, _t.monotonic() - _started_at)
                if self._flush_predictor is None:
                    from app.ai.flush_predictor import FlushPredictor
                    self._flush_predictor = FlushPredictor()
                # Derive bucket keys from stashed profile metadata
                _goal = "disconnect"  # DisconnectModule is by definition disconnect
                pred = self._flush_predictor.predict(
                    target_profile=self.params.get("_target_profile", "unknown"),
                    goal=_goal,
                    elapsed_s=elapsed_s,
                    network_class=self.params.get("_network_class", "unknown"),
                )
                if pred is not None:
                    stats["flush_prediction"] = {
                        "action": pred.action.value,
                        "elapsed_s": round(pred.elapsed_s, 2),
                        "recommended_stop_s": pred.recommended_stop_s,
                        "safe_ceiling_s": pred.safe_ceiling_s,
                        "danger_floor_s": pred.danger_floor_s,
                        "p_flush_at_elapsed": pred.p_flush_at_elapsed,
                        "sample_size": pred.sample_size,
                        "success_count": pred.success_count,
                        "fail_count": pred.fail_count,
                        "reason": pred.reason,
                    }
                else:
                    stats["flush_prediction"] = {
                        "action": "unknown",
                        "elapsed_s": round(elapsed_s, 2),
                        "reason": "insufficient labeled episodes in bucket",
                    }
        except Exception:
            pass
        # Attach A2S snapshot (baseline vs current player count)
        if self._a2s_probe is not None:
            try:
                snap = self._a2s_probe.latest()
                baseline = self._a2s_probe.baseline_count()
                if snap is not None:
                    stats["a2s"] = {
                        "reachable": snap.reachable,
                        "player_count": snap.player_count,
                        "baseline_count": baseline,
                        "dropped": self._a2s_probe.count_dropped(),
                        "server_name": snap.server_name,
                    }
            except Exception:
                pass
        return stats

    def start(self) -> bool:
        """Open WinDivert handle and start packet processing thread."""
        try:
            # Kill any existing clumsy.exe first — only one process can
            # hold a WinDivert handle at a time. Routed through
            # safe_subprocess so the spawn is audit-logged and the
            # taskkill binary is resolved from System32 (no PATH hijack).
            try:
                if _safe_sp is not None:
                    taskkill_path = _safe_sp.resolve_system_binary("taskkill")
                    _safe_sp.run(
                        [taskkill_path, "/F", "/IM", "clumsy.exe"],
                        timeout=5.0,
                        expect_returncode=None,  # rc=128 if no process — fine
                        intent="native_divert.kill_preexisting_clumsy",
                    )
                    time.sleep(0.05)  # brief pause — handle release
            except _SafeSpErr:
                pass
            except Exception:
                pass

            # Add DLL directory to search path so WinDivert.dll can find
            # WinDivert64.sys (which must be in the same directory)
            dll_dir = os.path.dirname(os.path.abspath(self.dll_path))
            log_info(f"NativeEngine: DLL directory = {dll_dir}")

            # Verify WinDivert64.sys exists alongside the DLL
            sys_path = os.path.join(dll_dir, "WinDivert64.sys")
            if not os.path.exists(sys_path):
                log_error(f"NativeEngine: WinDivert64.sys NOT FOUND at {sys_path}")
                return False

            try:
                kernel32 = ctypes.windll.kernel32
                kernel32.SetDllDirectoryW(dll_dir)
                log_info(f"NativeEngine: SetDllDirectoryW({dll_dir})")
            except Exception as e:
                log_error(f"NativeEngine: SetDllDirectoryW failed: {e}")
                # Fall back to adding to PATH
                os.environ["PATH"] = dll_dir + ";" + os.environ.get("PATH", "")

            # Runtime integrity: verify DLL hasn't been tampered with
            try:
                from app.core.crypto import compute_file_integrity
                dll_hash = compute_file_integrity(self.dll_path)
                sys_hash = compute_file_integrity(sys_path)
                log_info(f"NativeEngine: DLL integrity SHA-384={dll_hash[:16]}...")
                log_info(f"NativeEngine: SYS integrity SHA-384={sys_hash[:16]}...")
            except Exception as ie:
                log_error(f"NativeEngine: integrity check failed: {ie}")

            log_info(f"NativeEngine: loading WinDivert.dll from {self.dll_path}")
            self._divert = WinDivertDLL(self.dll_path)

            # Open handle with filter
            # Use NETWORK_FORWARD layer for hotspot/ICS traffic (packets being
            # forwarded through the system to other devices on 192.168.137.x).
            # This matches clumsy.exe's default behavior (NetworkType=0 → else → FORWARD).
            # Only use NETWORK layer if explicitly targeting local machine.
            direction = self.params.get("direction", "both")
            use_local = self.params.get("_network_local", False)
            # Refresh hot-path cache in case params mutated since __init__
            self._use_local_layer = bool(use_local)
            try:
                if self.target_ip and self.target_ip != "unknown":
                    self._target_ip_u32 = int.from_bytes(
                        socket.inet_aton(self.target_ip), "big")
            except OSError:
                self._target_ip_u32 = 0
            layer = WINDIVERT_LAYER_NETWORK if use_local else WINDIVERT_LAYER_NETWORK_FORWARD
            layer_name = "NETWORK" if layer == WINDIVERT_LAYER_NETWORK else "NETWORK_FORWARD"
            log_info(f"NativeEngine: opening handle with filter='{self.filter_str}', layer={layer_name}")
            self._handle = self._divert.open(self.filter_str, layer=layer)

            # Check for INVALID_HANDLE_VALUE (-1 as pointer)
            handle_val = self._handle
            if isinstance(handle_val, int):
                is_invalid = (handle_val == -1 or handle_val == 0xFFFFFFFF or
                              handle_val == 0xFFFFFFFFFFFFFFFF)
            else:
                is_invalid = (not handle_val)

            if is_invalid:
                err = ctypes.get_last_error()
                hint = _WINDIVERT_ERR_HINTS.get(err, "unknown")
                log_error(f"NativeEngine: WinDivertOpen FAILED (error={err}: {hint})")
                return False

            log_info(f"NativeEngine: handle opened successfully ({self._handle})")

            self._init_modules()

            # Wire recorder hotkeys to GodModeModule (if present)
            if _RECORDER_HOTKEYS_AVAILABLE and "godmode" in self.methods:
                for mod in self._modules:
                    if mod.__class__.__name__ == "GodModeModule":
                        self._recorder_hotkeys = RecorderHotkeys(godmode_module=mod)
                        if self._recorder_hotkeys.start():
                            log_info("[Engine] RecorderHotkeys active — "
                                     "F5=record, F9=kill, F10=hit, F11=death, F12=inv")
                        else:
                            log_info("[Engine] RecorderHotkeys failed to start "
                                     "(keyboard module may not be available)")
                            self._recorder_hotkeys = None
                        break

            # Wire DisconnectModule state transitions into the recorder
            # so cut_start / cut_end are labeled alongside feature windows.
            if self._episode_recorder is not None:
                try:
                    from app.firewall.modules.disconnect import DisconnectModule
                    sink = self._episode_recorder.record_event
                    for mod in self._modules:
                        if isinstance(mod, DisconnectModule):
                            mod.attach_event_sink(sink)
                    # Derive the goal from active methods so the learning
                    # loop can bucket (profile, goal) correctly without
                    # requiring callers to pass a goal explicitly.
                    _m = set(self.methods or ())
                    if "disconnect" in _m:
                        _goal = "disconnect"
                    elif "lag" in _m:
                        _goal = "lag"
                    elif "drop" in _m or "pulse" in _m:
                        _goal = "desync"
                    else:
                        _goal = "other"

                    # Direction: per-module override wins when disconnect is
                    # the goal (see dayz.json disconnect_direction); fall
                    # back to global.
                    _direction = self.params.get(
                        "disconnect_direction"
                        if _goal == "disconnect"
                        else "direction",
                        self.params.get("direction", "both"),
                    )

                    self._episode_recorder.record_event(
                        "engine_start",
                        target_ip=self.target_ip,
                        methods=list(self.methods),
                        target_profile=self.params.get(
                            "_target_profile", "unknown"),
                        network_class=self.params.get(
                            "_network_class", "unknown"),
                        platform=self.params.get("_platform", "unknown"),
                        goal=_goal,
                        direction=_direction,
                    )
                except Exception as exc:
                    log_warning(f"[EPISODE] Event sink wiring failed: {exc}")

            # Start A2S probe if a query port is configured. The probe
            # establishes a baseline player_count on first reachable poll,
            # then watches for drops during the cut. On drop it writes a
            # cut_outcome(persisted=false) event so the learning loop gets
            # a labeled episode without the operator pressing MARK DUPE.
            # Host resolution order:
            #   1. Explicit a2s_host / server_ip params (operator override)
            #   2. target_ip when WinDivert is on NETWORK layer (PC-local
            #      mode: target IS the server endpoint already).
            #   3. Deferred: auto-detect from UDP flow on forward layer.
            _a2s_host = self.params.get("a2s_host") or self.params.get("server_ip")
            _defer_a2s = False
            if not _a2s_host:
                if self._use_local_layer and self.target_ip and self.target_ip != "unknown":
                    _a2s_host = self.target_ip
                else:
                    # Forward layer (hotspot) — defer to the resolver
                    _defer_a2s = True
            _a2s_port = (
                self.params.get("a2s_port")
                or self.params.get("query_port")
                or 27016
            )
            if not self.params.get("a2s_enabled", True):
                _a2s_host = None
                _defer_a2s = False
            if (_a2s_host or _defer_a2s) and _a2s_port:
                try:
                    from app.network.a2s_probe import A2SProbe

                    def _on_snap(snap, _self=self) -> None:
                        # Auto-label once per engine session on first drop
                        if _self._a2s_auto_labeled:
                            return
                        if _self._a2s_probe is None:
                            return
                        if _self._a2s_probe.count_dropped(threshold=1):
                            _self._a2s_auto_labeled = True
                            log_info(
                                f"[A2S] roster drop detected "
                                f"(count={snap.player_count}, "
                                f"baseline={_self._a2s_probe.baseline_count()}) "
                                "→ auto-labeling cut as dupe success"
                            )
                            if _self._episode_recorder is not None:
                                try:
                                    _self._episode_recorder.record_event(
                                        "cut_outcome",
                                        persisted=False,
                                        source="a2s_probe",
                                        player_count=snap.player_count,
                                        baseline=_self._a2s_probe.baseline_count(),
                                    )
                                except Exception:
                                    pass
                            # Also stash as pending so engine_stop flushes it
                            # into cut_end. Semantics: _pending_cut_outcome
                            # stores `persisted`; False = hive did NOT flush
                            # = dupe success.
                            _self._pending_cut_outcome = False

                    # Shared factory so deferred start uses the same config
                    def _spawn_a2s(host: str, _self=self,
                                   _port=int(_a2s_port),
                                   _on_snap=_on_snap) -> None:
                        try:
                            probe = A2SProbe(
                                host=str(host),
                                port=_port,
                                interval_s=float(_self.params.get("a2s_interval_s", 1.0)),
                                timeout_s=float(_self.params.get("a2s_timeout_s", 1.0)),
                                include_roster=bool(_self.params.get("a2s_include_roster", False)),
                            )
                            probe.subscribe(_on_snap)
                            probe.start()
                            _self._a2s_probe = probe
                            # Late-attach to cut verifier if it exists
                            if _self._cut_verifier is not None:
                                try:
                                    _self._cut_verifier._a2s_probe = probe  # noqa: SLF001
                                except Exception:
                                    pass
                        except Exception as _exc:
                            log_warning(f"[A2S] deferred start failed: {_exc}")

                    if _a2s_host:
                        _spawn_a2s(str(_a2s_host))
                    else:
                        # Forward layer — start resolver thread that waits
                        # up to a2s_resolve_timeout_s for modal server IP.
                        _resolve_s = float(self.params.get("a2s_resolve_timeout_s", 3.0))
                        self._server_ip_deadline_ts = time.monotonic() + _resolve_s

                        def _resolver(_self=self,
                                      _deadline=self._server_ip_deadline_ts,
                                      _spawn=_spawn_a2s) -> None:
                            # Poll every 250ms until we have a clear modal
                            # winner (≥5 samples and ≥2× runner-up) or
                            # timeout. Minimum floor so we don't latch on
                            # the first stray packet.
                            while (
                                _self._running
                                and not _self._server_ip_resolved
                                and time.monotonic() < _deadline
                            ):
                                time.sleep(0.25)
                                cands = dict(_self._server_ip_candidates)
                                if not cands:
                                    continue
                                ranked = sorted(
                                    cands.items(), key=lambda kv: kv[1], reverse=True,
                                )
                                top_ip, top_n = ranked[0]
                                runner = ranked[1][1] if len(ranked) > 1 else 0
                                if top_n >= 5 and top_n >= 2 * max(1, runner):
                                    _self._server_ip_hint = top_ip
                                    _self._server_ip_resolved = True
                                    log_info(
                                        f"[A2S] resolved server IP → {top_ip} "
                                        f"(n={top_n}, runner={runner})"
                                    )
                                    _spawn(top_ip)
                                    return
                            # Timeout — pick best we have if any
                            if not _self._server_ip_resolved and _self._server_ip_candidates:
                                ranked = sorted(
                                    _self._server_ip_candidates.items(),
                                    key=lambda kv: kv[1], reverse=True,
                                )
                                top_ip, top_n = ranked[0]
                                _self._server_ip_hint = top_ip
                                _self._server_ip_resolved = True
                                log_info(
                                    f"[A2S] resolver timed out, using "
                                    f"best candidate {top_ip} (n={top_n})"
                                )
                                _spawn(top_ip)
                            elif not _self._server_ip_resolved:
                                log_warning(
                                    "[A2S] resolver saw no UDP flow — "
                                    "probe skipped (target not sending?)"
                                )

                        threading.Thread(
                            target=_resolver, name="A2SResolver", daemon=True,
                        ).start()
                except Exception as exc:
                    log_warning(f"[A2S] probe init failed: {exc}")
                    self._a2s_probe = None

            # Cut verifier: active ICMP probe against target_ip. Required
            # by MAXIMUM CUT preset (_require_cut_verifier=true) and
            # optional elsewhere (opt in with params["enable_cut_verifier"]).
            _want_verifier = bool(
                self.params.get("enable_cut_verifier")
                or self.params.get("_require_cut_verifier")
            )
            if _want_verifier and self.target_ip and self.target_ip != "unknown":
                try:
                    from app.network.cut_verifier import CutVerifier
                    self._cut_verifier = CutVerifier(
                        target_ip=self.target_ip,
                        interval_s=float(self.params.get("cut_verify_interval_s", 0.5)),
                        fail_threshold=int(self.params.get("cut_verify_fail_threshold", 2)),
                        a2s_probe=self._a2s_probe,
                    )

                    # Wire cut-state transitions into episode recorder so the
                    # learning loop can distinguish "cut never severed"
                    # (preset ineffective) from "cut severed but no dupe"
                    # (preset works, hive flushed anyway).
                    def _on_verdict(verdict, _self=self, _last=[None]) -> None:
                        if verdict.state == _last[0]:
                            return
                        _last[0] = verdict.state
                        if _self._episode_recorder is not None:
                            try:
                                _self._episode_recorder.record_event(
                                    "cut_verified",
                                    state=verdict.state.value,
                                    reason=verdict.reason,
                                    ping_ok=verdict.ping_ok,
                                    a2s_dropped=verdict.a2s_dropped,
                                )
                            except Exception:
                                pass
                        # Track max severity reached for engine stop summary
                        _order = {"unknown": 0, "connected": 1,
                                  "degraded": 2, "severed": 3}
                        cur = _order.get(verdict.state.value, 0)
                        prev = _order.get(
                            getattr(_self, "_max_cut_state", "unknown"), 0)
                        if cur > prev:
                            _self._max_cut_state = verdict.state.value

                    self._max_cut_state = "unknown"
                    self._cut_verifier.subscribe(_on_verdict)
                    self._cut_verifier.start()
                except Exception as exc:
                    log_warning(f"[VERIFY] init failed: {exc}")
                    self._cut_verifier = None

            # Start packet processing thread
            self._running = True
            self._last_window_close = time.monotonic()
            self._thread = threading.Thread(
                target=self._packet_loop,
                daemon=True,
                name="NativeWinDivert"
            )
            self._thread.start()

            # Flow-health watchdog: if we don't see ANY packets within
            # 3 s of start, the filter is wrong, the target isn't
            # generating traffic, or ARP poisoning silently failed
            # (most common dupe-failure cause on switched networks).
            # Runs once, fire-and-forget.
            threading.Thread(
                target=self._flow_health_check,
                args=(3.0,),
                daemon=True,
                name="NativeWinDivertHealth",
            ).start()

            log_info(f"NativeEngine RUNNING: methods={self.methods}, "
                     f"filter={self.filter_str}")

            # Audit trail
            try:
                from app.logs.audit import audit_event
                audit_event("disruption_start", {
                    "target_ip": self.target_ip,
                    "methods": list(self.methods),
                    "filter": self.filter_str,
                })
            except Exception:
                pass

            return True

        except Exception as e:
            log_error(f"NativeEngine start failed: {e}")
            log_error(traceback.format_exc())
            self._cleanup()
            return False

    def stop(self) -> None:
        """Stop packet processing and close WinDivert handle.

        Shutdown order matters:
          1. Set _running=False so packet loop stops processing new packets
          2. Close WinDivert handle to unblock recv() in packet loop
          3. Join packet thread — loop exits on closed handle
          4. Stop modules (flush queued lag/godmode packets through handle)
             NOTE: modules flush via _send_packet which needs _divert but
             the handle is closed, so we reopen briefly or skip.
             Actually: we stop modules BEFORE closing handle so flushes work.
        """
        log_info("NativeEngine: stopping...")
        self._running = False

        # Audit trail
        try:
            from app.logs.audit import audit_event
            audit_event("disruption_stop", {
                "target_ip": self.target_ip,
                "methods": list(self.methods),
                "packets_processed": self._packets_processed,
                "packets_dropped": self._packets_dropped,
            })
        except Exception:
            pass

        # Stop cut verifier first (depends on A2S probe).
        if self._cut_verifier is not None:
            try:
                self._cut_verifier.stop()
            except Exception as exc:
                log_warning(f"[VERIFY] stop failed: {exc}")
            self._cut_verifier = None

        # Stop A2S probe early so it doesn't race with recorder shutdown.
        if self._a2s_probe is not None:
            try:
                self._a2s_probe.stop()
            except Exception as exc:
                log_warning(f"[A2S] probe stop failed: {exc}")
            self._a2s_probe = None

        # Stop recorder hotkeys before modules shut down
        if self._recorder_hotkeys is not None:
            try:
                self._recorder_hotkeys.stop()
                log_info("[Engine] RecorderHotkeys stopped")
            except Exception:
                pass
            self._recorder_hotkeys = None

        # Stop modules first — flush threads need the handle still open
        # to send queued packets (GodMode flush, Lag flush, OOD flush)
        for mod in self._modules:
            if hasattr(mod, 'stop'):
                try:
                    mod.stop(send_fn=self._send_packet)
                except TypeError:
                    # Module.stop() doesn't accept send_fn — call without it
                    mod.stop()

        # Now close handle to unblock the packet loop's recv()
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            try:
                self._divert.close(self._handle)
                log_info("NativeEngine: WinDivert handle closed")
            except Exception as e:
                log_error(f"NativeEngine: close error: {e}")
            self._handle = None

        # Wait for packet thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                log_error("NativeEngine: packet thread did not exit within 2s timeout")

        log_info(f"NativeEngine stopped ("
                 f"processed={self._packets_processed}, "
                 f"inbound={self._packets_inbound}, "
                 f"outbound={self._packets_outbound}, "
                 f"dropped={self._packets_dropped}, "
                 f"passed={self._packets_passed})")

        # Flush the episode recorder last so the final window + engine_stop
        # event land on disk before we return. Close any in-progress cut
        # first so open-ended cuts (duration_ms=0) get a cut_end label.
        # The pending persisted outcome (set via mark_last_cut_outcome)
        # propagates into the cut_end event so the survival trainer can
        # use it without a separate label pass.
        if self._episode_recorder is not None:
            try:
                from app.firewall.modules.disconnect import DisconnectModule
                pending = self._pending_cut_outcome
                self._pending_cut_outcome = None
                for mod in self._modules:
                    if isinstance(mod, DisconnectModule):
                        try:
                            mod.force_cut_end(persisted=pending)
                        except Exception:
                            pass
                self._episode_recorder.record_event(
                    "engine_stop",
                    processed=self._packets_processed,
                    dropped=self._packets_dropped,
                    inbound=self._packets_inbound,
                    outbound=self._packets_outbound,
                    max_cut_state=getattr(self, "_max_cut_state", "unknown"),
                )
                self._episode_recorder.stop()
            except Exception as exc:
                log_warning(f"[EPISODE] Recorder stop failed: {exc}")
            self._episode_recorder = None
            self._feature_extractor = None

    def _cleanup(self) -> None:
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            try:
                self._divert.close(self._handle)
            except Exception:
                pass
            self._handle = None
        self._running = False

    # ── ML integration ────────────────────────────────────────────────

    def mark_last_cut_outcome(self, persisted: bool) -> None:
        """Tag the currently-open (or most recent) cut with its outcome.

        ``persisted=False`` means the cut prevented the hive from
        flushing — the dupe succeeded. ``persisted=True`` means the hive
        still wrote — the dupe failed. This is what the survival model
        uses as the event label during training.

        The GUI "Mark dupe success/fail" buttons call this. If the cut
        is still open, the outcome is stashed and flushed into the
        cut_end event by stop(). If the cut already closed, we fire a
        standalone cut_outcome event so the trainer can still pick it up.
        """
        self._pending_cut_outcome = bool(persisted)
        if self._episode_recorder is None:
            return
        try:
            from app.firewall.modules.disconnect import (
                DisconnectModule, STATE_DONE,
            )
            # If every DisconnectModule has already closed its cut, emit
            # a standalone cut_outcome event so the label isn't lost.
            any_open = False
            for mod in self._modules:
                if isinstance(mod, DisconnectModule) and mod.state != STATE_DONE:
                    any_open = True
                    break
            if not any_open:
                self._episode_recorder.record_event(
                    "cut_outcome", persisted=bool(persisted),
                )
        except Exception as exc:
            log_warning(f"[EPISODE] mark_last_cut_outcome failed: {exc}")

    def _flow_health_check(self, window_s: float) -> None:
        """Warn loudly if the WinDivert filter sees zero packets in *window_s*.

        On switched networks, ARP poisoning can fail silently — the
        spoof thread reports success but no target traffic actually
        flows through us, so every cut is a no-op. This watchdog
        catches that case and surfaces it instead of leaving the
        operator wondering why cuts don't work.
        """
        try:
            start_count = self._packets_processed
            start_ts = time.monotonic()
            # Sample in short ticks so a clean stop() exits fast.
            while self._running and (time.monotonic() - start_ts) < window_s:
                time.sleep(0.25)
            if not self._running:
                return
            delta = self._packets_processed - start_count
            if delta > 0:
                log_info(
                    f"[HEALTH] flow OK — {delta} packets in first "
                    f"{window_s:.1f}s"
                )
                return

            # Zero packets. Try to tell the operator why.
            arp_hint = ""
            try:
                # Best-effort: if there's an ArpSpoofer attached and it
                # claims to be active but we see nothing, the poison
                # isn't propagating (wrong iface, IP forwarding off,
                # switch with port-security, etc.).
                spoofer = getattr(self, "_arp_spoofer", None)
                if spoofer is not None and getattr(spoofer, "is_active", False):
                    arp_hint = (
                        " ARP spoofer is ACTIVE but no packets are "
                        "reaching the filter — poison likely failed "
                        "(check iface, IP forwarding, MAC resolution)."
                    )
                elif spoofer is None:
                    arp_hint = (
                        " No ARP spoofer attached — on a switched LAN "
                        "you may need one to see target traffic."
                    )
            except Exception:
                pass

            log_warning(
                f"[HEALTH] ZERO packets in {window_s:.1f}s for target "
                f"{self.target_ip} filter='{self.filter_str}'. Cuts "
                f"will be no-ops until traffic flows through the "
                f"filter.{arp_hint}"
            )
            # Emit a labeled event so the trainer sees the miss.
            if self._episode_recorder is not None:
                try:
                    self._episode_recorder.record_event(
                        "flow_health_miss",
                        window_s=window_s,
                        target_ip=self.target_ip,
                    )
                except Exception:
                    pass
        except Exception as exc:
            log_warning(f"[HEALTH] watchdog crashed: {exc}")

    def _auto_tune_duration_if_requested(self) -> None:
        """Populate params['disconnect_duration_ms'] from the survival model.

        STRICTLY gated on ``params["_auto_tune_duration"]`` being truthy.
        Direct GUI cuts (clone-dupe workflow) leave this flag unset and
        retain legacy open-ended semantics: cut stays open until the
        operator releases it, no forced duration, no quiet-window tail.
        The clone-dupe protocol requires an instant clean release synced
        to the account-switch beat — any forced duration or quiet window
        sabotages that timing.

        Only Smart Mode (which opts in by setting ``_auto_tune_duration``)
        gets model-driven duration. The quiet window must be seeded by the
        caller — the engine never injects one on its own.
        """
        if "disconnect" not in self.methods:
            return
        if not self.params.get("_auto_tune_duration"):
            return  # operator / direct-cut path — respect legacy semantics
        current = self.params.get("disconnect_duration_ms", 0) or 0
        if current > 0:
            return  # operator pinned a value, respect it

        # ── Step 1: learned median from prior successful cuts ─────────
        # If the LearningLoop has ≥5 labeled episodes for this
        # (target_profile, goal) bucket, trust its median duration over
        # the survival model. This closes the feedback loop: real in-game
        # outcomes > baseline population model.
        try:
            from app.ai.learning_loop import LearningLoop
            _ll = LearningLoop()
            rec = _ll.recommend(
                target_profile=self.params.get("_target_profile", "unknown"),
                goal="disconnect",
                network_class=self.params.get("_network_class", "unknown"),
            )
            if rec is not None and rec.best_duration_s > 0:
                self.params["disconnect_duration_ms"] = int(
                    round(rec.best_duration_s * 1000)
                )
                log_info(
                    f"[AUTO-TUNE] disconnect_duration_ms="
                    f"{self.params['disconnect_duration_ms']} "
                    f"(learned: n={rec.sample_size}, "
                    f"success_rate={rec.success_rate:.0%}, "
                    f"conf={rec.confidence:.2f})"
                )
                return
        except Exception as exc:
            log_warning(f"[AUTO-TUNE] learning loop unavailable: {exc}")

        # ── Step 2: fall back to population survival model ─────────────
        try:
            from app.ai.feature_extractor import FEATURE_DIM
            from app.ai.models.survival_model import (
                load_default, HIVE_FLUSH_FLOOR_S, HARD_KICK_FLOOR_S,
            )
            try:
                model = load_default()
            except Exception:
                model = None

            if model is None or not getattr(model, "ready", False):
                log_info("[AUTO-TUNE] survival model not ready — "
                         "leaving duration=0 (open-ended, operator releases)")
                return

            target_p = float(self.params.get("_auto_tune_target_p", 0.9))
            target_p = max(0.5, min(0.99, target_p))

            baseline = [0.0] * FEATURE_DIM
            pred = float(model.quantile_duration(baseline, p=target_p))
            secs = max(HARD_KICK_FLOOR_S, pred)

            self.params["disconnect_duration_ms"] = int(round(secs * 1000))
            log_info(
                f"[AUTO-TUNE] disconnect_duration_ms="
                f"{self.params['disconnect_duration_ms']} "
                f"(survival model p={target_p:.2f}, "
                f"hive_floor={HIVE_FLUSH_FLOOR_S}s, "
                f"kick_floor={HARD_KICK_FLOOR_S}s)"
            )
        except Exception as exc:
            log_warning(f"[AUTO-TUNE] failed: {exc}")

    def _init_modules(self) -> None:
        """Create disruption module instances based on selected methods.

        Module order matters — aggressive droppers go first to maximize
        disruption. Packets that survive early modules hit later ones.
        Order: godmode → disconnect → drop → bandwidth → throttle → lag → ood → duplicate → corrupt → rst

        God Mode is special: it handles direction internally (lag inbound,
        pass outbound) so it goes first.  If godmode is active, other
        modules only see packets that godmode didn't consume.
        """
        _ensure_modules_loaded()

        log_info("=" * 60)
        log_info(f"[ENGINE INIT] Methods requested: {self.methods}")
        log_info(f"[ENGINE INIT] Params received ({len(self.params)} keys):")
        # Log direction params
        dir_p = {k: v for k, v in self.params.items() if "direction" in k}
        log_info(f"[ENGINE INIT]   Directions: {dir_p}")
        # Log key disruption values
        for key in ("drop_chance", "disconnect_chance", "bandwidth_limit",
                     "throttle_chance", "lag_delay", "duplicate_chance",
                     "lag_passthrough", "lag_preserve_connection"):
            if key in self.params:
                log_info(f"[ENGINE INIT]   {key} = {self.params[key]}")

        # Enforce optimal module order for maximum disruption.
        # ("dupe" removed — duplication now runs through the disconnect module.)
        PRIORITY_ORDER = [
            "godmode", "disconnect", "drop", "bandwidth", "throttle",
            "lag", "ood", "duplicate", "corrupt", "rst",
        ]
        ordered_methods = [m for m in PRIORITY_ORDER if m in self.methods]
        ordered_methods += [m for m in self.methods if m not in ordered_methods]
        log_info(f"[ENGINE INIT] Ordered chain: {ordered_methods}")

        # Auto-detect lag passthrough mode: if lag is stacked with
        # duplicate or ood, lag queues a delayed copy but lets the original
        # continue to downstream modules (creates desync combos).
        #
        # SKIP auto-enable when lag_passthrough is explicitly set in params
        # (e.g. God Mode presets set it to False because they use duplicate
        # on outbound-only while lag must consume inbound packets).
        has_downstream = bool({"duplicate", "ood"} & set(self.methods))
        lag_pt_explicit = "lag_passthrough" in self.params
        if has_downstream and not lag_pt_explicit:
            self.params["lag_passthrough"] = True
            log_info("[ENGINE INIT] AUTO-ENABLED lag passthrough "
                     "(duplicate/ood present, lag_passthrough not set)")
        elif has_downstream and lag_pt_explicit:
            log_info(f"[ENGINE INIT] lag_passthrough explicitly set to "
                     f"{self.params['lag_passthrough']} — auto-detect skipped")
        else:
            log_info("[ENGINE INIT] No duplicate/ood — lag passthrough not needed")

        # Auto-tune: if the caller asked for a survival-model-predicted
        # cut duration (either implicitly by leaving disconnect_duration_ms
        # at 0, or explicitly via params["_auto_tune_duration"]), query
        # the trained model and fill the param in. Falls through to the
        # legacy open-ended cut semantics if the model isn't ready.
        self._auto_tune_duration_if_requested()

        self._modules = []
        for method_name in ordered_methods:
            cls = MODULE_MAP.get(method_name)
            if cls:
                mod = cls(self.params)
                self._modules.append(mod)

                # Detailed per-module debug
                passthrough_tag = ""
                if hasattr(mod, '_passthrough') and mod._passthrough:
                    passthrough_tag = " [PASSTHROUGH]"
                dir_key = getattr(mod, '_direction_key', '')
                dir_override = self.params.get(f"{dir_key}_direction", "NOT SET")
                dir_global = self.params.get("direction", "both")
                log_info(f"[ENGINE INIT] Module '{method_name}':"
                         f" direction={mod.direction}"
                         f" (override={dir_override}, global={dir_global})"
                         f"{passthrough_tag}")

                # Start flush threads for modules that have them
                if hasattr(mod, 'start_flush_thread'):
                    mod.start_flush_thread(
                        self._send_packet, self._divert, self._handle
                    )
                    log_info(f"[ENGINE INIT]   └─ flush thread started")

                # Auto-activate modules with state machines (e.g. DupeEngine)
                if hasattr(mod, 'activate') and callable(getattr(mod, 'activate')):
                    try:
                        mod.activate()
                        log_info(f"[ENGINE INIT]   └─ auto-activated")
                    except Exception as ae:
                        log_error(f"[ENGINE INIT]   └─ activate FAILED: {ae}")
            else:
                log_info(f"[ENGINE INIT] UNKNOWN module '{method_name}' — skipped!")

        log_info(f"[ENGINE INIT] Final chain: "
                 f"{[f'{m.__class__.__name__}(dir={m.direction})' for m in self._modules]}")
        # Predict packet behavior
        for direction_name, is_out in [("INBOUND", False), ("OUTBOUND", True)]:
            active = []
            for mod in self._modules:
                if mod.direction == DIR_BOTH:
                    active.append(mod.__class__.__name__)
                elif mod.direction == DIR_OUTBOUND and is_out:
                    active.append(mod.__class__.__name__)
                elif mod.direction == DIR_INBOUND and not is_out:
                    active.append(mod.__class__.__name__)
            if active:
                log_info(f"[ENGINE INIT] {direction_name} packets will hit: {active}")
            else:
                log_info(f"[ENGINE INIT] {direction_name} packets: NO modules match → pass through")
        log_info("=" * 60)

    def _send_packet(self, packet_data, addr) -> None:
        """Send a packet through WinDivert (recalculates checksums).

        Uses a pre-allocated send buffer to avoid per-packet ctypes array
        allocation — critical for throughput on DayZ's ~60 tick UDP stream.
        Lock-protected because flush threads also call this.
        """
        if not self._handle:
            return  # handle closed, nothing to send to
        try:
            pkt_len = len(packet_data)
            with self._send_lock:
                ctypes.memmove(self._send_buf, bytes(packet_data), pkt_len)
                self._divert.calc_checksums(self._send_buf, pkt_len,
                                             ctypes.byref(addr), 0)
                self._send_len.value = 0
                self._divert.send(self._handle, self._send_buf, pkt_len,
                                   ctypes.byref(self._send_len), ctypes.byref(addr))
        except Exception as exc:
            log_error(f"NativeEngine: _send_packet failed ({len(packet_data)}B): {exc}")

    def _packet_loop(self) -> None:
        """Main packet capture/process/reinject loop.

        Direction-aware: before calling a module's process(), we check
        whether the packet's direction matches the module's direction
        filter.  This means a module configured for "inbound" only will
        never see outbound packets — they skip right past it.

        This is what makes God Mode work: the GodModeModule handles
        direction internally, but regular modules (lag, drop, etc.) can
        also be configured per-direction via "{module}_direction" params.
        """
        packet_buf = (ctypes.c_uint8 * MAX_PACKET_SIZE)()
        recv_len = wintypes.UINT(0)
        addr = WINDIVERT_ADDRESS()

        log_info("[PKTLOOP] Packet loop started")
        log_info(f"[PKTLOOP] Module chain: "
                 f"{[(m.__class__.__name__, m.direction) for m in self._modules]}")

        # Periodic stats logging
        _stats_interval = 5.0  # log stats every 5 seconds
        _last_stats_time = time.time()
        _last_stats_processed = 0
        # Per-direction consumed/passed counters for debug
        _inbound_consumed = 0
        _inbound_passed = 0
        _outbound_consumed = 0
        _outbound_passed = 0
        # Track which module consumed, for first 20 packets of each direction
        _inbound_trace_count = 0
        _outbound_trace_count = 0
        _TRACE_LIMIT = 20  # detailed trace for first N packets per direction

        while self._running:
            try:
                # Receive next packet (blocks until packet arrives or handle closed)
                ok = self._divert.recv(
                    self._handle,
                    packet_buf,
                    MAX_PACKET_SIZE,
                    ctypes.byref(recv_len),
                    ctypes.byref(addr),
                )

                if not ok:
                    if not self._running:
                        break  # handle was closed, we're shutting down
                    err = ctypes.get_last_error()
                    if err == 995:  # ERROR_OPERATION_ABORTED — handle closed
                        break
                    log_error(f"[PKTLOOP] recv error={err}")
                    continue

                pkt_len = recv_len.value
                if pkt_len == 0:
                    continue

                self._packets_processed += 1

                # Copy packet data to mutable bytearray
                packet_data = bytearray(packet_buf[:pkt_len])

                # ── Direction detection ───────────────────────────────
                # Two modes depending on WinDivert layer:
                #
                # PC-LOCAL (NETWORK layer):
                #   addr.Outbound is CORRECT — WinDivert knows real direction.
                #   target_ip = game server IP.
                #   outbound = local machine → server, inbound = server → local.
                #
                # REMOTE (NETWORK_FORWARD layer, ICS/hotspot):
                #   addr.Outbound is TRUE for ALL forwarded packets.
                #   Must parse IPv4 src/dst to determine real direction.
                #   target_ip = device IP (PS5/Xbox/remote PC).
                #   src == target → outbound (device → server)
                #   dst == target → inbound  (server → device)
                # Zero-allocation direction detection:
                #   _use_local_layer and _target_ip_u32 are precomputed once
                #   in __init__/start(), so the hot path does no dict lookups
                #   and no string allocations per packet. On the FORWARD
                #   layer we unpack src/dst into u32 via bit-shifts and
                #   compare ints — no inet_ntoa() allocation churn.
                if self._use_local_layer:
                    # PC-local: addr.Outbound is reliable
                    is_outbound = bool(addr.Outbound)
                elif self._target_ip_u32 and len(packet_data) >= 20 and (packet_data[0] >> 4) & 0xF == 4:
                    _src_u32 = (
                        (packet_data[12] << 24)
                        | (packet_data[13] << 16)
                        | (packet_data[14] << 8)
                        | packet_data[15]
                    )
                    _dst_u32 = (
                        (packet_data[16] << 24)
                        | (packet_data[17] << 16)
                        | (packet_data[18] << 8)
                        | packet_data[19]
                    )
                    if _src_u32 == self._target_ip_u32:
                        is_outbound = True
                        addr.Outbound = True
                        # Capture candidate server IP (dst of outbound pkt)
                        # during the short resolution window. Only UDP (17).
                        if (
                            not self._server_ip_resolved
                            and len(packet_data) >= 20
                            and packet_data[9] == 17
                        ):
                            _remote = (
                                f"{packet_data[16]}.{packet_data[17]}."
                                f"{packet_data[18]}.{packet_data[19]}"
                            )
                            self._server_ip_candidates[_remote] = (
                                self._server_ip_candidates.get(_remote, 0) + 1
                            )
                    elif _dst_u32 == self._target_ip_u32:
                        is_outbound = False
                        addr.Outbound = False
                        if (
                            not self._server_ip_resolved
                            and len(packet_data) >= 20
                            and packet_data[9] == 17
                        ):
                            _remote = (
                                f"{packet_data[12]}.{packet_data[13]}."
                                f"{packet_data[14]}.{packet_data[15]}"
                            )
                            self._server_ip_candidates[_remote] = (
                                self._server_ip_candidates.get(_remote, 0) + 1
                            )
                    else:
                        is_outbound = bool(addr.Outbound)
                else:
                    is_outbound = bool(addr.Outbound)

                # Track direction
                if is_outbound:
                    self._packets_outbound += 1
                else:
                    self._packets_inbound += 1

                # Feed traffic analyzer (passive — no packet modification)
                if self._traffic_analyzer is not None:
                    self._traffic_analyzer.record_packet(
                        time.time(), pkt_len, is_outbound)

                # Feature extraction for ML training corpus (opt-in).
                # Classification is cheap (header inspection only) and only
                # runs when the recorder is active, so the default hot path
                # is untouched.
                if self._feature_extractor is not None:
                    try:
                        from app.firewall.modules._packet_utils import classify_packet
                        _pkt_cls, _proto, _sp, _dp = classify_packet(
                            packet_data, is_target=True
                        )
                        _mono = time.monotonic()
                        self._feature_extractor.observe(
                            _pkt_cls, pkt_len, not is_outbound,
                            _dp if is_outbound else _sp, _mono,
                        )
                        if _mono - self._last_window_close >= self._window_interval_s:
                            _vec = self._feature_extractor.close_window(_mono)
                            if self._episode_recorder is not None:
                                self._episode_recorder.record_window(_vec)
                            self._last_window_close = _mono
                    except Exception as _fx_exc:
                        # Never let telemetry break the packet loop.
                        if not hasattr(self, "_fx_err_logged"):
                            log_warning(f"[EPISODE] Feature extract error: {_fx_exc}")
                            self._fx_err_logged = True

                # Determine if we should trace this packet
                dir_label = "OUT" if is_outbound else "IN"
                trace_count = _outbound_trace_count if is_outbound else _inbound_trace_count
                do_trace = trace_count < _TRACE_LIMIT

                # Run through disruption module chain.
                consumed = False
                consumed_by = None
                for mod in self._modules:
                    # Skip module if direction doesn't match
                    matches = mod.matches_direction(addr)
                    if do_trace:
                        mod_name = mod.__class__.__name__
                        if not matches:
                            pass  # don't log skips to avoid spam
                        # log when module processes
                    if not matches:
                        continue
                    result = mod.process(packet_data, addr, self._send_packet)
                    if result:
                        consumed = True
                        consumed_by = mod.__class__.__name__
                        self._packets_dropped += 1
                        break  # packet consumed

                # Detailed trace for first N packets per direction
                if do_trace:
                    if consumed:
                        log_info(f"[PKTLOOP] #{self._packets_processed} {dir_label} "
                                 f"{pkt_len}B → CONSUMED by {consumed_by}")
                    else:
                        log_info(f"[PKTLOOP] #{self._packets_processed} {dir_label} "
                                 f"{pkt_len}B → PASSED (no module consumed)")
                    if is_outbound:
                        _outbound_trace_count += 1
                    else:
                        _inbound_trace_count += 1

                # Track per-direction stats
                if consumed:
                    if is_outbound:
                        _outbound_consumed += 1
                    else:
                        _inbound_consumed += 1
                else:
                    self._packets_passed += 1
                    self._send_packet(packet_data, addr)
                    if is_outbound:
                        _outbound_passed += 1
                    else:
                        _inbound_passed += 1

                # Periodic stats dump
                now = time.time()
                if now - _last_stats_time >= _stats_interval:
                    new_pkts = self._packets_processed - _last_stats_processed
                    pps = new_pkts / (now - _last_stats_time) if now > _last_stats_time else 0
                    log_info(f"[PKTLOOP STATS] {pps:.0f} pkt/s | "
                             f"total={self._packets_processed} | "
                             f"IN: consumed={_inbound_consumed} passed={_inbound_passed} | "
                             f"OUT: consumed={_outbound_consumed} passed={_outbound_passed}")
                    _last_stats_time = now
                    _last_stats_processed = self._packets_processed

            except Exception as e:
                if not self._running:
                    break
                log_error(f"[PKTLOOP] packet loop error: {e}")
                time.sleep(0.001)

        log_info(f"[PKTLOOP] Loop exited. Final stats: "
                 f"processed={self._packets_processed} "
                 f"IN(consumed={_inbound_consumed}, passed={_inbound_passed}) "
                 f"OUT(consumed={_outbound_consumed}, passed={_outbound_passed})")
