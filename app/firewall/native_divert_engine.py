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

import os
import sys
import time
import random
import struct
import subprocess
import threading
import traceback
import ctypes
from ctypes import wintypes
from collections import deque
from typing import Dict, List, Optional
from app.logs.logger import log_info, log_error


# ======================================================================
# WinDivert Constants
# ======================================================================
WINDIVERT_LAYER_NETWORK         = 0
WINDIVERT_LAYER_NETWORK_FORWARD = 1
WINDIVERT_FLAG_NONE             = 0

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PACKET_SIZE      = 65535  # max IP packet

# TCP flags offset in TCP header (byte 13, counting from TCP header start)
TCP_FLAG_RST = 0x04


# ======================================================================
# WinDivert Address Structure (v2.x)
# ======================================================================
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

class WINDIVERT_DATA_SOCKET(ctypes.Structure):
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
    def Layer(self):
        return self._bitfield & 0xFF

    @property
    def Outbound(self):
        return bool(self._bitfield & (1 << 24))

    @Outbound.setter
    def Outbound(self, val):
        if val:
            self._bitfield |= (1 << 24)
        else:
            self._bitfield &= ~(1 << 24)


# ======================================================================
# WinDivert DLL Loader
# ======================================================================
class WinDivertDLL:
    """Thin ctypes wrapper around WinDivert.dll functions."""

    def __init__(self, dll_path: str):
        # Load the DLL
        self._dll = ctypes.WinDLL(dll_path)

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

    def open(self, filter_str: str, layer: int = WINDIVERT_LAYER_NETWORK,
             priority: int = 0, flags: int = WINDIVERT_FLAG_NONE):
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

    def calc_checksums(self, packet_buf, pkt_len, addr=None, flags=0):
        return self._dll.WinDivertHelperCalcChecksums(
            packet_buf, pkt_len, addr, flags
        )


# ======================================================================
# Disruption Modules
# ======================================================================
class DisruptionModule:
    """Base class for packet disruption modules."""

    def __init__(self, params: dict):
        self.params = params

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        """Process a packet. Return True if packet was handled (sent or dropped).
        Return False to pass through to next module or default send."""
        return False


class DropModule(DisruptionModule):
    """Randomly drop packets based on chance percentage."""

    def process(self, packet_data, addr, send_fn):
        chance = self.params.get("drop_chance", 95)
        if random.random() * 100 < chance:
            return True  # dropped — don't send
        return False


class LagModule(DisruptionModule):
    """Buffer packets and release them after a delay."""

    def __init__(self, params):
        super().__init__(params)
        self._lag_queue = deque(maxlen=10000)  # bounded to prevent memory leak
        self._lag_thread = None
        self._running = True

    def start_flush_thread(self, send_fn, divert_dll, handle):
        """Start background thread that flushes lagged packets."""
        self._send_fn = send_fn
        self._divert_dll = divert_dll
        self._handle = handle
        self._lag_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="LagFlush"
        )
        self._lag_thread.start()

    def _flush_loop(self):
        while self._running:
            now = time.time()
            while self._lag_queue and self._lag_queue[0][0] <= now:
                _, pkt_data, addr = self._lag_queue.popleft()
                try:
                    buf = (ctypes.c_uint8 * len(pkt_data))(*pkt_data)
                    send_len = wintypes.UINT(0)
                    self._divert_dll.send(
                        self._handle, buf, len(pkt_data),
                        ctypes.byref(send_len), ctypes.byref(addr)
                    )
                except Exception:
                    pass
            time.sleep(0.001)  # 1ms resolution

    def process(self, packet_data, addr, send_fn):
        delay_ms = self.params.get("lag_delay", 1500)
        release_time = time.time() + (delay_ms / 1000.0)
        # Deep copy addr for deferred send
        addr_copy = WINDIVERT_ADDRESS()
        ctypes.memmove(ctypes.byref(addr_copy), ctypes.byref(addr),
                        ctypes.sizeof(WINDIVERT_ADDRESS))
        self._lag_queue.append((release_time, bytearray(packet_data), addr_copy))
        return True  # handled — will be sent later

    def stop(self):
        self._running = False


class DuplicateModule(DisruptionModule):
    """Send packets multiple times."""

    def process(self, packet_data, addr, send_fn):
        chance = self.params.get("duplicate_chance", 80)
        count = self.params.get("duplicate_count", 10)
        if random.random() * 100 < chance:
            # Send the original + extra copies
            for _ in range(count):
                send_fn(packet_data, addr)
            return True  # we handled the send
        return False


class ThrottleModule(DisruptionModule):
    """Only allow packets through at certain intervals."""

    def __init__(self, params):
        super().__init__(params)
        self._last_send = 0

    def process(self, packet_data, addr, send_fn):
        chance = self.params.get("throttle_chance", 100)
        frame_ms = self.params.get("throttle_frame", 400)
        now = time.time()
        if random.random() * 100 < chance:
            if (now - self._last_send) * 1000 < frame_ms:
                return True  # throttled — drop
            self._last_send = now
        return False


class CorruptModule(DisruptionModule):
    """Flip random bits in packet payload."""

    def process(self, packet_data, addr, send_fn):
        chance = self.params.get("tamper_chance", 60)
        if random.random() * 100 < chance and len(packet_data) > 40:
            # Corrupt a random byte in the payload (skip IP+TCP headers)
            offset = random.randint(40, len(packet_data) - 1)
            packet_data[offset] ^= random.randint(1, 255)
            # Checksum will be recalculated before send
        return False  # still needs to be sent


class BandwidthModule(DisruptionModule):
    """Limit throughput to X KB/s."""

    def __init__(self, params):
        super().__init__(params)
        self._bytes_sent = 0
        self._window_start = time.time()

    def process(self, packet_data, addr, send_fn):
        limit_kbps = self.params.get("bandwidth_limit", 1)
        limit_bytes = limit_kbps * 1024
        now = time.time()

        # Reset window every second
        if now - self._window_start >= 1.0:
            self._bytes_sent = 0
            self._window_start = now

        if self._bytes_sent + len(packet_data) > limit_bytes:
            return True  # over budget — drop
        self._bytes_sent += len(packet_data)
        return False


class OODModule(DisruptionModule):
    """Out of order — buffer a few packets and release in random order."""

    def __init__(self, params):
        super().__init__(params)
        self._buffer = []

    def process(self, packet_data, addr, send_fn):
        chance = self.params.get("ood_chance", 80)
        if random.random() * 100 < chance:
            # Deep copy
            addr_copy = WINDIVERT_ADDRESS()
            ctypes.memmove(ctypes.byref(addr_copy), ctypes.byref(addr),
                            ctypes.sizeof(WINDIVERT_ADDRESS))
            self._buffer.append((bytearray(packet_data), addr_copy))
            if len(self._buffer) >= 4:
                random.shuffle(self._buffer)
                for pkt, a in self._buffer:
                    send_fn(pkt, a)
                self._buffer.clear()
            return True
        return False

    def stop(self):
        """Flush any remaining buffered packets on shutdown."""
        # Drop remaining buffer — no send_fn available at stop time,
        # and the WinDivert handle may already be closed.
        self._buffer.clear()


class RSTModule(DisruptionModule):
    """Inject TCP RST packets to kill connections."""

    def process(self, packet_data, addr, send_fn):
        chance = self.params.get("rst_chance", 90)
        if random.random() * 100 < chance and len(packet_data) >= 40:
            # Check if TCP (protocol 6 in IP header byte 9)
            if packet_data[9] == 6:
                # Get IP header length
                ihl = (packet_data[0] & 0x0F) * 4
                if ihl + 13 < len(packet_data):
                    # Set RST flag in TCP header (byte 13 from TCP start)
                    tcp_flags_offset = ihl + 13
                    packet_data[tcp_flags_offset] |= TCP_FLAG_RST
                    # Will be checksum'd before send
        return False


class DisconnectModule(DisruptionModule):
    """Drop 99% of packets — hard disconnect that sustains for full duration."""

    def process(self, packet_data, addr, send_fn):
        if random.random() < 0.99:
            return True  # dropped
        return False


# Module name → class mapping
MODULE_MAP = {
    "drop":       DropModule,
    "lag":        LagModule,
    "duplicate":  DuplicateModule,
    "throttle":   ThrottleModule,
    "corrupt":    CorruptModule,
    "bandwidth":  BandwidthModule,
    "ood":        OODModule,
    "rst":        RSTModule,
    "disconnect": DisconnectModule,
}


# ======================================================================
# Native WinDivert Engine
# ======================================================================
class NativeWinDivertEngine:
    """Direct WinDivert packet engine — no clumsy.exe, no GUI, no window.

    Drop-in replacement for ClumsyEngine. Same interface:
      .start() → bool
      .stop()
      .alive → bool
      .pid → int (returns thread ID since there's no subprocess)
    """

    def __init__(self, dll_path: str, filter_str: str,
                 methods: list, params: dict):
        self.dll_path = dll_path
        self.filter_str = filter_str
        self.methods = methods
        self.params = params

        self._divert = None       # WinDivertDLL instance
        self._handle = None       # WinDivert HANDLE
        self._thread = None       # Packet processing thread
        self._running = False
        self._modules = []        # Active disruption modules
        self._packets_processed = 0
        self._packets_dropped = 0

        # Emulate subprocess-like interface for compatibility
        self._proc = self  # self acts as the "process"

    @property
    def pid(self):
        """Return thread ID (no subprocess PID since we're native)."""
        if self._thread:
            return self._thread.ident
        return 0

    @property
    def alive(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def poll(self):
        """Mimic subprocess.poll() — return None if alive, 0 if stopped."""
        if self.alive:
            return None
        return 0

    def start(self) -> bool:
        """Open WinDivert handle and start packet processing thread."""
        try:
            # Kill any existing clumsy.exe first — only one process can
            # hold a WinDivert handle at a time
            try:
                subprocess.Popen(
                    ["taskkill", "/F", "/IM", "clumsy.exe"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
                time.sleep(0.05)  # brief pause — just enough for handle release
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

            # Add to DLL search path (Windows 7+ API)
            try:
                kernel32 = ctypes.windll.kernel32
                kernel32.SetDllDirectoryW(dll_dir)
                log_info(f"NativeEngine: SetDllDirectoryW({dll_dir})")
            except Exception as e:
                log_error(f"NativeEngine: SetDllDirectoryW failed: {e}")
                # Fall back to adding to PATH
                os.environ["PATH"] = dll_dir + ";" + os.environ.get("PATH", "")

            # Load WinDivert.dll
            log_info(f"NativeEngine: loading WinDivert.dll from {self.dll_path}")
            self._divert = WinDivertDLL(self.dll_path)

            # Open handle with filter
            # Use NETWORK_FORWARD layer for hotspot/ICS traffic (packets being
            # forwarded through the system to other devices on 192.168.137.x).
            # This matches clumsy.exe's default behavior (NetworkType=0 → else → FORWARD).
            # Only use NETWORK layer if explicitly targeting local machine.
            direction = self.params.get("direction", "both")
            use_local = self.params.get("_network_local", False)
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
                log_error(f"NativeEngine: WinDivertOpen FAILED (error={err})")
                log_error("  Error 2 = WinDivert64.sys not found")
                log_error("  Error 5 = not running as administrator")
                log_error("  Error 87 = invalid filter syntax")
                log_error("  Error 577 = driver not signed / Secure Boot issue")
                log_error("  Error 1275 = driver blocked by system policy")
                return False

            log_info(f"NativeEngine: handle opened successfully ({self._handle})")

            # Initialize disruption modules
            self._init_modules()

            # Start packet processing thread
            self._running = True
            self._thread = threading.Thread(
                target=self._packet_loop,
                daemon=True,
                name="NativeWinDivert"
            )
            self._thread.start()

            log_info(f"NativeEngine RUNNING: methods={self.methods}, "
                     f"filter={self.filter_str}")
            return True

        except Exception as e:
            log_error(f"NativeEngine start failed: {e}")
            log_error(traceback.format_exc())
            self._cleanup()
            return False

    def stop(self):
        """Stop packet processing and close WinDivert handle."""
        log_info("NativeEngine: stopping...")
        self._running = False

        # Stop lag module flush thread
        for mod in self._modules:
            if hasattr(mod, 'stop'):
                mod.stop()

        # Close WinDivert handle (this will unblock any pending recv)
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            try:
                self._divert.close(self._handle)
                log_info("NativeEngine: WinDivert handle closed")
            except Exception as e:
                log_error(f"NativeEngine: close error: {e}")
            self._handle = None

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        log_info(f"NativeEngine stopped (processed={self._packets_processed}, "
                 f"dropped={self._packets_dropped})")

    def _cleanup(self):
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            try:
                self._divert.close(self._handle)
            except Exception:
                pass
            self._handle = None
        self._running = False

    def _init_modules(self):
        """Create disruption module instances based on selected methods.

        Module order matters — aggressive droppers go first to maximize
        disruption. Packets that survive early modules hit later ones.
        Order: disconnect → drop → bandwidth → throttle → lag → ood → duplicate → corrupt → rst
        """
        # Enforce optimal module order for maximum disruption
        PRIORITY_ORDER = [
            "disconnect", "drop", "bandwidth", "throttle",
            "lag", "ood", "duplicate", "corrupt", "rst",
        ]
        ordered_methods = [m for m in PRIORITY_ORDER if m in self.methods]
        # Add any unknown methods at the end
        ordered_methods += [m for m in self.methods if m not in ordered_methods]

        self._modules = []
        for method_name in ordered_methods:
            cls = MODULE_MAP.get(method_name)
            if cls:
                mod = cls(self.params)
                self._modules.append(mod)
                log_info(f"NativeEngine: module '{method_name}' initialized")

                # Start lag flush thread if needed
                if isinstance(mod, LagModule):
                    mod.start_flush_thread(
                        self._send_packet, self._divert, self._handle
                    )
            else:
                log_info(f"NativeEngine: unknown module '{method_name}' — skip")
        log_info(f"NativeEngine: module chain = {[m.__class__.__name__ for m in self._modules]}")

    def _send_packet(self, packet_data, addr):
        """Send a packet through WinDivert (recalculates checksums)."""
        try:
            buf = (ctypes.c_uint8 * len(packet_data))(*packet_data)
            # Recalculate checksums (important after corruption/RST injection)
            self._divert.calc_checksums(buf, len(packet_data),
                                         ctypes.byref(addr), 0)
            send_len = wintypes.UINT(0)
            self._divert.send(self._handle, buf, len(packet_data),
                               ctypes.byref(send_len), ctypes.byref(addr))
        except Exception:
            pass  # best-effort send

    def _packet_loop(self):
        """Main packet capture/process/reinject loop."""
        packet_buf = (ctypes.c_uint8 * MAX_PACKET_SIZE)()
        recv_len = wintypes.UINT(0)
        addr = WINDIVERT_ADDRESS()

        log_info("NativeEngine: packet loop started")

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
                    log_error(f"NativeEngine: recv error={err}")
                    continue

                pkt_len = recv_len.value
                if pkt_len == 0:
                    continue

                self._packets_processed += 1

                # Copy packet data to mutable bytearray
                packet_data = bytearray(packet_buf[:pkt_len])

                # Run through ALL disruption modules in chain.
                # Each module gets a chance to drop/defer the packet.
                # If ANY module consumes it, it's gone — no further processing.
                # This means disconnect(95%) + drop(95%) stack: only 0.25%
                # of packets survive both.
                consumed = False
                for mod in self._modules:
                    result = mod.process(packet_data, addr, self._send_packet)
                    if result:
                        consumed = True
                        self._packets_dropped += 1
                        break  # packet consumed (dropped, deferred, or duplicated)

                # If no module consumed it, send it through
                if not consumed:
                    self._send_packet(packet_data, addr)

            except Exception as e:
                if not self._running:
                    break
                log_error(f"NativeEngine: packet loop error: {e}")
                time.sleep(0.001)

        log_info("NativeEngine: packet loop exited")
