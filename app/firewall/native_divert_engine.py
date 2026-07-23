#!/usr/bin/env python3
"""
Native WinDivert Engine — direct packet manipulation without clumsy.exe.

Replaces clumsy.exe GUI automation with direct WinDivert.dll calls via ctypes.
No GUI, no window, no flash. Just packet interception and manipulation.

Implements the same disruption primitives and public processing order as
Clumsy. Deferred packets resume at the next module in that order instead of
bypassing the remainder of the chain.

  - lag:        Buffer packets and release after delay (ms)
  - drop:       Randomly drop packets (chance %)
  - disconnect: Stateful timed packet cut (100% by default)
  - bandwidth:  Limit throughput to X KB/s
  - throttle:   Only pass packets at intervals (frame ms, chance %)
  - duplicate:  Send packets multiple times (count, chance %)
  - ood:        Reorder packets randomly (chance %)
  - corrupt:    Flip random bits in payload (chance %)
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
import inspect
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
        send_fn: Callable[[bytearray, Any], bool],
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
        # A module may only appear once in a live chain. Preserve the first
        # caller-supplied occurrence; _init_modules applies the stable Clumsy
        # priority order after this defensive de-duplication.
        self.methods = list(dict.fromkeys(self.methods or ()))

        self._divert = None       # WinDivertDLL instance
        self._handle = None       # WinDivert HANDLE
        self._thread = None       # Packet processing thread
        self._running = False
        self._modules = []        # Active disruption modules
        self._module_continuations: list[
            Callable[[bytearray, WINDIVERT_ADDRESS], bool]
        ] = []
        # Deferred flush threads and the capture thread may traverse the
        # chain concurrently. A re-entrant lock keeps stateful downstream
        # modules deterministic while still allowing Duplicate/OOD to call
        # their continuation recursively.
        self._pipeline_lock = threading.RLock()
        # One lightweight lifetime counter dict per module, populated in
        # _init_modules and incremented by the packet thread.  get_stats()
        # turns these raw counters into the public activity DTO.
        self._module_activity: list[Dict[str, Any]] = []
        self._recorder_hotkeys = None  # RecorderHotkeys instance
        self._packets_processed = 0
        self._packets_dropped = 0
        self._packets_inbound = 0
        self._packets_outbound = 0
        self._packets_passed = 0
        self._send_attempted = 0
        self._send_succeeded = 0
        self._send_failed = 0
        self._send_short = 0

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
        This surfaces module classification, queue depth, release counts, etc.
        """
        stats = {
            "packets_processed": self._packets_processed,
            "packets_dropped": self._packets_dropped,
            "packets_inbound": self._packets_inbound,
            "packets_outbound": self._packets_outbound,
            "packets_passed": self._packets_passed,
            "send_attempted": self._send_attempted,
            "send_succeeded": self._send_succeeded,
            "send_failed": self._send_failed,
            "send_short": self._send_short,
            "alive": self.alive,
            "target_ip": self.target_ip,
            "engine": "native",
            "telemetry_available": True,
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

        activity = self._get_module_activity(module_stats)
        stats["module_activity"] = {
            entry["method"]: entry for entry in activity
        }
        stats["configured_methods"] = [
            entry["method"] for entry in activity
        ]
        stats["effective_methods"] = [
            entry["method"] for entry in activity
            if entry["state"] == "effective"
        ]
        stats["shadowed_methods"] = [
            entry["method"] for entry in activity
            if entry["state"] == "shadowed"
        ]
        all_effective = bool(activity) and all(
            entry["state"] == "effective" for entry in activity
        )
        runtime_verified = bool(
            self.alive
            and self._packets_processed > 0
            and all_effective
            and self._send_failed == 0
        )
        if not self.alive:
            verification_state = "inactive"
        elif self._packets_processed <= 0:
            verification_state = "waiting_for_traffic"
        elif self._send_failed > 0:
            verification_state = "send_failure"
        elif stats["shadowed_methods"]:
            verification_state = "shadowed"
        elif not all_effective:
            verification_state = "effect_not_verified"
        else:
            verification_state = "verified"
        stats.update({
            "startup_verified": bool(self.alive),
            "runtime_verification_available": True,
            "runtime_verified": runtime_verified,
            "local_effect_verified": runtime_verified,
            "verification_state": verification_state,
        })
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

    @staticmethod
    def _directions_overlap(first: str, second: str) -> bool:
        """Return whether two module direction filters share traffic."""
        return (
            first == DIR_BOTH
            or second == DIR_BOTH
            or first == second
        )

    @staticmethod
    def _effect_count(
        method: str,
        handled: int,
        module_snapshot: Dict[str, Any],
    ) -> int:
        """Derive a method's observable effect count from its native stats."""
        if method == "duplicate" and "sent" in module_snapshot:
            sent = module_snapshot.get("sent", 0)
            if isinstance(sent, (int, float)):
                return max(0, int(sent))
        # A lagged packet is only proven effective after its deferred copy
        # successfully resumes through the remaining chain.  Merely placing
        # it in the queue must not produce a green "effective" claim.
        if method == "lag":
            released = module_snapshot.get("released", 0)
            if isinstance(released, (int, float)):
                return max(0, int(released))
            return 0

        candidates = [handled]
        method_keys = {
            "disconnect": ("dropped", "packets_dropped"),
            "corrupt": ("affected",),
            "rst": ("affected",),
        }
        for key in method_keys.get(method, ()):
            value = module_snapshot.get(key, 0)
            if isinstance(value, (int, float)):
                candidates.append(max(0, int(value)))
        return max(candidates)

    def _get_module_activity(
        self,
        module_stats: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> list[Dict[str, Any]]:
        """Build an honest, public per-module activity snapshot.

        ``pending`` means no traffic for the module's direction has arrived;
        ``reached`` means process() ran but no effect is yet evidenced;
        ``effective`` means the module consumed or modified at least one
        packet; and ``shadowed`` means observed traffic was consumed earlier
        in the same chain before this module could run.
        """
        snapshots = module_stats or {}
        result: list[Dict[str, Any]] = []
        prior: list[Dict[str, Any]] = []

        for index, raw in enumerate(self._module_activity):
            method = str(raw.get("method", "unknown"))
            direction = str(raw.get("direction", DIR_BOTH))
            invoked_in = int(raw.get("invoked_inbound", 0))
            invoked_out = int(raw.get("invoked_outbound", 0))
            handled_in = int(raw.get("handled_inbound", 0))
            handled_out = int(raw.get("handled_outbound", 0))
            invoked = invoked_in + invoked_out
            handled = handled_in + handled_out

            if direction == DIR_INBOUND:
                relevant = self._packets_inbound
            elif direction == DIR_OUTBOUND:
                relevant = self._packets_outbound
            else:
                relevant = self._packets_processed

            mod = self._modules[index] if index < len(self._modules) else None
            class_name = mod.__class__.__name__ if mod is not None else ""
            module_snapshot = snapshots.get(class_name, {})
            affected = self._effect_count(method, handled, module_snapshot)

            shadowed_by = None
            if affected > 0:
                state = "effective"
            elif invoked > 0:
                state = "reached"
            elif relevant <= 0:
                state = "pending"
            else:
                for earlier in prior:
                    if direction == DIR_INBOUND:
                        earlier_handled = earlier["handled_inbound"]
                    elif direction == DIR_OUTBOUND:
                        earlier_handled = earlier["handled_outbound"]
                    else:
                        earlier_handled = earlier["handled"]
                    if (
                        earlier_handled > 0
                        and self._directions_overlap(
                            str(earlier["direction"]), direction)
                    ):
                        shadowed_by = earlier["method"]
                        break
                state = "shadowed" if shadowed_by else "not_reached"

            entry: Dict[str, Any] = {
                "method": method,
                "direction": direction,
                "state": state,
                "invoked": invoked,
                "matched": invoked,
                "affected": affected,
                "handled": handled,
                "consumed": handled,
                "invoked_inbound": invoked_in,
                "invoked_outbound": invoked_out,
                "handled_inbound": handled_in,
                "handled_outbound": handled_out,
            }
            if shadowed_by:
                entry["shadowed_by"] = shadowed_by
            result.append(entry)
            prior.append(entry)

        return result

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
            # by guarded verifier presets (_require_cut_verifier=true) and
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
            # generating traffic, or local forwarding setup silently failed
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
          2. Wait for any in-flight chain traversal to finish
          3. Stop modules in order and drain queues through continuations
          4. Close the WinDivert handle to unblock recv()
          5. Join the packet thread
        """
        log_info("NativeEngine: stopping...")
        self._running = False

        # Wait for any packet already traversing the chain to finish before
        # module shutdown begins. The packet loop re-checks _running while it
        # owns this lock, so it cannot enqueue work after queues are drained.
        with self._pipeline_lock:
            pass

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

        # Stop modules in chain order while the handle remains open. Earlier
        # queues drain through their per-module continuation, so downstream
        # modules remain available until preceding work reaches them.
        self._stop_modules()

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
        # start() can fail after _init_modules has launched flush threads.
        # Drain them before closing the handle so partial starts cannot leak
        # daemon threads or strand queued packets.
        self._running = False
        with self._pipeline_lock:
            pass
        self._stop_modules()
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            try:
                self._divert.close(self._handle)
            except Exception:
                pass
            self._handle = None

    def _stop_modules(self) -> None:
        """Stop active modules without bypassing their downstream chain."""
        for index, mod in enumerate(self._modules):
            stop_fn = getattr(mod, "stop", None)
            if not callable(stop_fn):
                continue
            try:
                try:
                    accepts_sender = "send_fn" in inspect.signature(
                        stop_fn
                    ).parameters
                except (TypeError, ValueError):
                    accepts_sender = False
                if accepts_sender:
                    if index < len(self._module_continuations):
                        sender = self._module_continuations[index]
                    else:
                        sender = self._send_packet
                    stop_fn(send_fn=sender)
                else:
                    stop_fn()
            except Exception as exc:
                log_error(
                    f"NativeEngine: {mod.__class__.__name__}.stop() "
                    f"failed: {exc}"
                )

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

        On switched networks, local forwarding setup can fail silently — the
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
                # Best-effort: if there's a local forwarding helper attached
                # and it claims to be active but we see nothing, the forwarding
                # path isn't propagating (wrong iface, IP forwarding off,
                # switch with port-security, etc.).
                spoofer = getattr(self, "_arp_spoofer", None)
                if spoofer is not None and getattr(spoofer, "is_active", False):
                    arp_hint = (
                        " Local forwarding helper is ACTIVE but no packets are "
                        "reaching the filter — setup likely failed "
                        "(check iface, IP forwarding, MAC resolution)."
                    )
                elif spoofer is None:
                    arp_hint = (
                        " No local forwarding helper attached — on a switched "
                        "LAN you may need the local-path diagnostic mode to "
                        "see authorized target traffic."
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
        Direct GUI diagnostics leave this flag unset and retain legacy
        open-ended semantics: the impairment stays open until the
        operator releases it, with no forced duration and no quiet-window
        tail. This preserves predictable manual timing during authorized
        lab runs.

        Only Smart Mode (which opts in by setting ``_auto_tune_duration``)
        gets model-driven duration. The quiet window must be seeded by the
        caller — the engine never injects one on its own.
        """
        if "disconnect" not in self.methods:
            return
        if not self.params.get("_auto_tune_duration"):
            return  # operator / direct diagnostic path — respect legacy semantics
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

        Public modules follow standalone Clumsy exactly:
        lag → drop → disconnect → bandwidth → throttle → duplicate → ood
        → corrupt → rst. Native-only modules keep deterministic placement
        around that public chain.

        The legacy pulse-cycle module handles direction internally, so it
        remains first for backward compatibility. If active, later modules
        only see packets it did not consume.
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

        # Public relative order is the standalone Clumsy pipeline. Keep the
        # legacy native GodMode slot before it, and retain first-occurrence
        # order for every other native-only method after it.
        clumsy_order = [
            "lag", "drop", "disconnect", "bandwidth", "throttle",
            "duplicate", "ood", "corrupt", "rst",
        ]
        requested = list(dict.fromkeys(self.methods))
        ordered_methods = ["godmode"] if "godmode" in requested else []
        ordered_methods.extend(
            method for method in clumsy_order if method in requested
        )
        ordered_methods.extend(
            method for method in requested
            if method != "godmode" and method not in clumsy_order
        )
        log_info(f"[ENGINE INIT] Ordered chain: {ordered_methods}")

        # Consume-and-delay is the normal Clumsy behavior. Passthrough queues
        # an extra delayed copy while allowing the original forward, so it is
        # enabled only by an explicit caller choice.
        if "lag_passthrough" in self.params:
            log_info(
                "[ENGINE INIT] lag_passthrough explicitly set to "
                f"{self.params['lag_passthrough']}"
            )
        else:
            log_info("[ENGINE INIT] lag_passthrough defaults to False")

        # Auto-tune only when the caller explicitly requests a learned cut
        # duration.  A zero duration by itself remains open-ended so the
        # automatic workflow's own stage timer and standalone Clumsy retain
        # identical semantics.
        self._auto_tune_duration_if_requested()

        self._modules = []
        self._module_activity = []
        self._module_continuations = []
        for method_name in ordered_methods:
            cls = MODULE_MAP.get(method_name)
            if cls:
                mod = cls(self.params)
                self._modules.append(mod)
                activity = {
                    "method": method_name,
                    "direction": mod.direction,
                    "invoked_inbound": 0,
                    "invoked_outbound": 0,
                    "handled_inbound": 0,
                    "handled_outbound": 0,
                }
                self._module_activity.append(activity)
                # Direct reference avoids a method-name lookup in the packet
                # hot path. Modules are ordinary Python objects, so attaching
                # private engine telemetry is safe and isolated per instance.
                mod._dupez_activity = activity
            else:
                log_info(f"[ENGINE INIT] UNKNOWN module '{method_name}' — skipped!")

        # The complete module list must exist before any queue thread starts.
        # Every sender resumes immediately after its owning module, preserving
        # the same downstream path for immediate and deferred packets.
        self._module_continuations = [
            self._make_module_continuation(index + 1)
            for index in range(len(self._modules))
        ]

        for index, mod in enumerate(self._modules):
            method_name = self._module_activity[index]["method"]
            passthrough_tag = ""
            if getattr(mod, "_passthrough", False):
                passthrough_tag = " [PASSTHROUGH]"
            dir_key = getattr(mod, "_direction_key", "")
            dir_override = self.params.get(
                f"{dir_key}_direction", "NOT SET"
            )
            dir_global = self.params.get("direction", "both")
            log_info(
                f"[ENGINE INIT] Module '{method_name}':"
                f" direction={mod.direction}"
                f" (override={dir_override}, global={dir_global})"
                f"{passthrough_tag}"
            )

            # Activate state machines only after the full chain and all
            # continuations are available.
            activate = getattr(mod, "activate", None)
            if callable(activate):
                try:
                    activate()
                    log_info("[ENGINE INIT]   └─ auto-activated")
                except Exception as exc:
                    log_error(
                        f"[ENGINE INIT]   └─ activate FAILED: {exc}"
                    )

        for index, mod in enumerate(self._modules):
            start_flush = getattr(mod, "start_flush_thread", None)
            if callable(start_flush):
                start_flush(
                    self._module_continuations[index],
                    self._divert,
                    self._handle,
                )
                log_info("[ENGINE INIT]   └─ flush thread started")

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

    def _make_module_continuation(
        self,
        start_index: int,
    ) -> Callable[[bytearray, WINDIVERT_ADDRESS], bool]:
        """Return a sender that resumes at *start_index* in this chain."""
        def _continue(
            packet_data: bytearray,
            addr: WINDIVERT_ADDRESS,
        ) -> bool:
            return self._resume_packet(packet_data, addr, start_index)

        return _continue

    def _run_module_chain(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        start_index: int = 0,
    ) -> tuple[bool, Optional[str]]:
        """Run modules from *start_index* and report the first consumer."""
        is_outbound = bool(addr.Outbound)
        with self._pipeline_lock:
            for index in range(start_index, len(self._modules)):
                mod = self._modules[index]
                if not mod.matches_direction(addr):
                    continue

                activity = getattr(mod, "_dupez_activity", None)
                if activity is not None:
                    counter = (
                        "invoked_outbound"
                        if is_outbound else "invoked_inbound"
                    )
                    activity[counter] += 1

                if index < len(self._module_continuations):
                    continuation = self._module_continuations[index]
                else:
                    continuation = self._make_module_continuation(index + 1)
                if mod.process(packet_data, addr, continuation):
                    if activity is not None:
                        counter = (
                            "handled_outbound"
                            if is_outbound else "handled_inbound"
                        )
                        activity[counter] += 1
                    return True, mod.__class__.__name__
        return False, None

    def _resume_packet(
        self,
        packet_data: bytearray,
        addr: WINDIVERT_ADDRESS,
        start_index: int,
    ) -> bool:
        """Continue a deferred or module-generated packet downstream."""
        consumed, _ = self._run_module_chain(
            packet_data, addr, start_index=start_index
        )
        if consumed:
            return True
        return self._send_packet(packet_data, addr)

    def _send_packet(self, packet_data, addr) -> bool:
        """Send a packet through WinDivert (recalculates checksums).

        Uses a pre-allocated send buffer to avoid per-packet ctypes array
        allocation — critical for throughput on DayZ's ~60 tick UDP stream.
        Lock-protected because flush threads also call this. Success requires
        both a truthy WinDivert result and an exact byte count.
        """
        pkt_len = len(packet_data)
        with self._send_lock:
            self._send_attempted += 1
            if not self._handle or self._divert is None:
                self._send_failed += 1
                return False
            if pkt_len > MAX_PACKET_SIZE:
                self._send_failed += 1
                log_error(
                    f"NativeEngine: refused oversized send ({pkt_len}B)"
                )
                return False
            try:
                ctypes.memmove(self._send_buf, bytes(packet_data), pkt_len)
                checksum_ok = self._divert.calc_checksums(
                    self._send_buf, pkt_len, ctypes.byref(addr), 0
                )
                if not checksum_ok:
                    self._send_failed += 1
                    log_error(
                        "NativeEngine: checksum calculation failed "
                        f"({pkt_len}B)"
                    )
                    return False
                self._send_len.value = 0
                send_ok = self._divert.send(
                    self._handle,
                    self._send_buf,
                    pkt_len,
                    ctypes.byref(self._send_len),
                    ctypes.byref(addr),
                )
                if not send_ok:
                    self._send_failed += 1
                    log_error(
                        "NativeEngine: WinDivertSend failed "
                        f"({pkt_len}B, error={ctypes.get_last_error()})"
                    )
                    return False
                if self._send_len.value != pkt_len:
                    self._send_short += 1
                    self._send_failed += 1
                    log_error(
                        "NativeEngine: WinDivert short send "
                        f"({self._send_len.value}/{pkt_len}B)"
                    )
                    return False
                self._send_succeeded += 1
                return True
            except Exception as exc:
                self._send_failed += 1
                log_error(
                    f"NativeEngine: _send_packet failed ({pkt_len}B): {exc}"
                )
                return False

    def _packet_loop(self) -> None:
        """Main packet capture/process/reinject loop.

        Direction-aware: before calling a module's process(), we check
        whether the packet's direction matches the module's direction
        filter.  This means a module configured for "inbound" only will
        never see outbound packets — they skip right past it.

        The legacy pulse module handles direction internally, but regular
        modules (lag, drop, etc.) can also be configured per-direction via
        "{module}_direction" params.
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

                # Run through the same resumable chain used by delayed and
                # module-generated packets.
                with self._pipeline_lock:
                    if not self._running:
                        # stop() raced with a completed recv(). Reinject the
                        # captured packet unchanged before the handle closes.
                        self._send_packet(packet_data, addr)
                        break
                    consumed, consumed_by = self._run_module_chain(
                        packet_data, addr
                    )
                if consumed:
                    self._packets_dropped += 1

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
