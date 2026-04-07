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
import subprocess
import threading
import traceback
import ctypes
from ctypes import wintypes
from collections import deque
from typing import Dict
from app.logs.logger import log_info, log_error
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
    def Layer(self):
        return self._bitfield & 0xFF

    @property
    def Outbound(self):
        # WinDivert 2.x bitfield layout (from windivert.h):
        #   Layer(8) | Event(8) | Sniffed(1) | Outbound(1) | Loopback(1) | ...
        # On little-endian x86, Outbound is bit 17.
        return bool(self._bitfield & (1 << 17))

    @Outbound.setter
    def Outbound(self, val):
        if val:
            self._bitfield |= (1 << 17)
        else:
            self._bitfield &= ~(1 << 17)

    @property
    def Loopback(self):
        return bool(self._bitfield & (1 << 18))

    @property
    def IPv6(self):
        return bool(self._bitfield & (1 << 20))
class WinDivertDLL:
    """Thin ctypes wrapper around WinDivert.dll functions."""

    def __init__(self, dll_path: str):
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
DIR_BOTH     = "both"      # Module processes packets in both directions
DIR_INBOUND  = "inbound"   # Module only processes inbound packets (Outbound=False)
DIR_OUTBOUND = "outbound"  # Module only processes outbound packets (Outbound=True)
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

    For the NETWORK_FORWARD layer (ICS/hotspot), direction is relative to
    the Windows routing stack:
      Outbound=True  → packet leaving the gateway (from target to internet)
      Outbound=False → packet arriving at the gateway (from internet to target)

    So to freeze the target's view of YOU (God Mode), you lag INBOUND
    (packets flowing from internet → gateway → target).  Their outbound
    actions still reach the server in real time.
    """

    # Subclasses set this to their param prefix (e.g. "drop", "lag").
    # If set, __init__ checks for "{_direction_key}_direction" override.
    _direction_key: str = ""

    def __init__(self, params: dict):
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
    def _roll(chance) -> bool:
        """Return True if a chance% roll succeeds. 100% is deterministic."""
        return chance >= 100 or random.random() * 100 < chance

    def process(self, packet_data: bytearray, addr: WINDIVERT_ADDRESS,
                send_fn) -> bool:
        """Process a packet. Return True if packet was handled (sent or dropped).
        Return False to pass through to next module or default send."""
        return False

class DropModule(DisruptionModule):
    """Randomly drop packets based on chance percentage.

    When drop_chance is 100, ALL packets are dropped with zero leakage.
    This uses an exact comparison (>=) not probabilistic, so 100% means 100%.
    """
    _direction_key = "drop"

    def process(self, packet_data, addr, send_fn):
        return self._roll(self.params.get("drop_chance", 95))

class LagModule(DisruptionModule):
    """Buffer packets and release them after a delay.

    Behaviour modes (controlled by lag_passthrough):
    ================================================
    When lag is the ONLY disruption method or combined with drop/disconnect
    (methods that discard packets), lag should CONSUME the packet — queue it
    and return True so the original doesn't also arrive immediately.

    When lag is combined with duplicate/ood/corrupt (desync presets), lag
    should operate in PASSTHROUGH mode — queue a delayed COPY but return
    False so the original packet continues through the module chain to
    duplicate/ood/corrupt. This creates the desync effect: the target
    receives the real-time duplicated/reordered packets AND a delayed
    echo of the same data, causing DayZ's Enfusion engine to choke on
    conflicting state updates.

    The engine auto-detects this: if "duplicate" or "ood" are in the
    active methods list, lag_passthrough defaults to True.

    For God Mode, set lag_direction="inbound" so only packets flowing
    TO the target get delayed.  Their outbound packets pass through
    unmodified, meaning their actions register on the server in real time
    while their view of you freezes.

    DayZ note: DayZ uses UDP 2302 at ~60 tick.  Lagged packets are flushed
    via the engine's _send_packet() which recalculates checksums — critical
    because the network stack drops packets with bad checksums.
    """
    _direction_key = "lag"

    def __init__(self, params):
        super().__init__(params)
        self._lag_queue = deque(maxlen=10000)  # bounded to prevent memory leak
        self._lag_lock = threading.Lock()
        self._lag_thread = None
        self._running = True
        # Passthrough mode: queue a delayed copy but DON'T consume the packet.
        # Auto-enabled when stacked with duplicate/ood for desync combos.
        # Can be explicitly set via "lag_passthrough" param.
        self._passthrough = params.get("lag_passthrough", False)

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
            to_send = []
            with self._lag_lock:
                while self._lag_queue and self._lag_queue[0][0] <= now:
                    to_send.append(self._lag_queue.popleft())
            for _, pkt_data, addr in to_send:
                try:
                    # Use _send_fn (engine._send_packet) which recalculates
                    # checksums before sending — raw DLL send skips this and
                    # produces packets the network stack silently drops.
                    self._send_fn(pkt_data, addr)
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
        with self._lag_lock:
            self._lag_queue.append((release_time, bytearray(packet_data), addr_copy))

        if self._passthrough:
            # Passthrough mode: delayed copy queued, but let the original
            # continue through the module chain (duplicate, ood, etc.)
            # This creates temporal desync: target receives real-time
            # duplicated/reordered packets AND delayed echoes.
            return False
        return True  # consume mode: original held until delay expires

    def stop(self):
        self._running = False
        if self._lag_thread and self._lag_thread.is_alive():
            self._lag_thread.join(timeout=1.0)
        # Flush remaining queued packets so they aren't silently lost
        with self._lag_lock:
            remaining = list(self._lag_queue)
            self._lag_queue.clear()
        for _, pkt_data, addr in remaining:
            try:
                self._send_fn(pkt_data, addr)
            except Exception:
                pass

class DuplicateModule(DisruptionModule):
    """Send packets multiple times to cause desync via packet flooding.

    DayZ desync mechanism: DayZ's Enfusion engine uses sequence-dependent
    UDP state replication. When the client receives N copies of the same
    state update packet, it processes each one — but the game state has
    already advanced past that packet's sequence. The duplicate packets
    cause the client to re-apply stale state, creating inventory desync,
    position rubberbanding, and action duplication (the famous dupe glitch).

    duplicate_count=10 means the target receives 1 original + 10 copies = 11
    total deliveries of the same packet. Combined with lag (passthrough mode),
    they also get a delayed echo — compounding the desync window.
    """
    _direction_key = "duplicate"

    def process(self, packet_data, addr, send_fn):
        count = self.params.get("duplicate_count", 10)
        if self._roll(self.params.get("duplicate_chance", 80)):
            # Send the original first, then extra copies
            send_fn(packet_data, addr)
            for _ in range(count):
                send_fn(packet_data, addr)
            return True  # we handled the send (original + copies)
        return False  # chance didn't hit — let packet pass through normally

class ThrottleModule(DisruptionModule):
    """Only allow packets through at certain intervals."""
    _direction_key = "throttle"

    def __init__(self, params):
        super().__init__(params)
        self._last_send = 0

    def process(self, packet_data, addr, send_fn):
        frame_ms = self.params.get("throttle_frame", 400)
        now = time.time()
        if self._roll(self.params.get("throttle_chance", 100)):
            if (now - self._last_send) * 1000 < frame_ms:
                return True  # throttled — drop
            self._last_send = now
        return False

class CorruptModule(DisruptionModule):
    """Flip random bits in packet payload."""
    _direction_key = "tamper"

    def process(self, packet_data, addr, send_fn):
        if self._roll(self.params.get("tamper_chance", 60)) and len(packet_data) > 40:
            # Corrupt a random byte in the payload (skip IP+TCP headers)
            offset = random.randint(40, len(packet_data) - 1)
            packet_data[offset] ^= random.randint(1, 255)
            # Checksum will be recalculated before send
        return False  # still needs to be sent

class BandwidthModule(DisruptionModule):
    """Limit throughput to X KB/s."""
    _direction_key = "bandwidth"

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
    _direction_key = "ood"

    MAX_BUFFER = 64  # Prevent unbounded growth under heavy traffic

    def __init__(self, params):
        super().__init__(params)
        self._buffer = []

    def process(self, packet_data, addr, send_fn):
        if self._roll(self.params.get("ood_chance", 80)):
            # Deep copy
            addr_copy = WINDIVERT_ADDRESS()
            ctypes.memmove(ctypes.byref(addr_copy), ctypes.byref(addr),
                            ctypes.sizeof(WINDIVERT_ADDRESS))
            self._buffer.append((bytearray(packet_data), addr_copy))
            if len(self._buffer) >= 4:
                if len(self._buffer) < self.MAX_BUFFER:
                    random.shuffle(self._buffer)  # reorder; skip shuffle on safety flush
                for pkt, a in self._buffer:
                    send_fn(pkt, a)
                self._buffer.clear()
            return True
        return False

    def stop(self):
        """Flush any remaining buffered packets on shutdown."""
        self._buffer.clear()

class RSTModule(DisruptionModule):
    """Inject TCP RST packets to kill connections."""
    _direction_key = "rst"

    def process(self, packet_data, addr, send_fn):
        if self._roll(self.params.get("rst_chance", 90)) and len(packet_data) >= 40:
            # Check if TCP (protocol 6 in IP header byte 9)
            if packet_data[9] == 6:
                ihl = (packet_data[0] & 0x0F) * 4
                if ihl + 13 < len(packet_data):
                    # Set RST flag in TCP header (byte 13 from TCP start)
                    tcp_flags_offset = ihl + 13
                    packet_data[tcp_flags_offset] |= TCP_FLAG_RST
                    # Will be checksum'd before send
        return False

class DisconnectModule(DisruptionModule):
    """Hard disconnect — configurable drop rate, defaults to TRUE 100%.

    When disconnect_chance is 100 (default), every single packet is dropped.
    No random.random() call, no probability leak, no 1-in-100 slip-through.
    This is what ZeroDay meant: "when you drop 100% it actually drops 100%."

    Set disconnect_chance < 100 for a softer disconnect (e.g. 95% for the
    old clumsy behavior).
    """

    _direction_key = "disconnect"

    def process(self, packet_data, addr, send_fn):
        return self._roll(self.params.get("disconnect_chance", 100))

class GodModeModule(DisruptionModule):
    """God Mode — directional lag that freezes others' view of you.

    Packet flow on ICS/hotspot (NETWORK_FORWARD layer):
    =====================================================
    DayZ is UDP-only on port 2302. The server runs variable-tick simulation
    (~20-60 FPS) and replicates entity state to clients within a ~900m
    "network bubble". State updates are batched and sent as UDP datagrams.

    On an ICS hotspot (192.168.137.x), your laptop is the gateway. The
    target console's traffic is forwarded through your machine. WinDivert
    on NETWORK_FORWARD intercepts this transit traffic:

      - Outbound=True (target console → internet → game server):
        The target's movement inputs, action requests, and keepalives.
        We PASS these through untouched so their actions register on the
        server in real time — they can still move and shoot.

      - Outbound=False (game server → internet → your gateway → console):
        Server state replication: other players' positions (including YOURS),
        damage events, world state. We LAG these heavily so the target's
        game client freezes — they stop receiving updates about where you are.

    Net effect: you move freely and deal damage while being invisible to them.
    Their client freezes your last known position. When God Mode deactivates,
    all queued packets flush at once — DayZ's Enfusion engine reconciles
    the state delta and applies all pending damage/position updates.

    NAT keepalive strategy:
    =======================
    CRITICAL: WinDivert's NETWORK_FORWARD layer doesn't interact well with
    Windows NAT (official docs: "do not mix WinDivert at the forward layer
    with the Windows NAT implementation"). Long-delayed packets risk stale
    NAT mappings — the NAT table entry for the target's UDP flow can time
    out (Windows ICS NAT timeout is ~120s for UDP, but individual mappings
    can be shorter under load). If the mapping expires, flushed packets get
    silently dropped instead of forwarded to the target.

    To mitigate this, we use a NAT keepalive strategy:
      1. Every godmode_keepalive_interval_ms (default 800ms), we let ONE
         inbound packet pass through unlagged. This refreshes the NAT
         mapping without giving the target enough data to unfreeze — a
         single packet in DayZ's ~60-tick stream is just one frame update
         out of hundreds, causing at most a brief visual flicker.
      2. On flush (stop), packets are released in small bursts with brief
         pauses between them, rather than all at once. This prevents a
         packet storm that could overwhelm the NAT or trigger DayZ's
         anti-flood protection.

    Parameters:
      godmode_lag_ms: Delay applied to inbound packets (default: 2000ms)
      godmode_drop_inbound_pct: Optional % of inbound packets to drop (default: 0)
        Set >0 to make the freeze more aggressive (some packets never arrive).
      godmode_keepalive_interval_ms: How often to let one packet through for
        NAT keepalive (default: 800ms). Set 0 to disable (risky on long delays).
    """

    def __init__(self, params):
        super().__init__(params)
        # God Mode always targets both directions — it handles direction
        # internally (lag inbound, pass outbound).
        self.direction = DIR_BOTH
        # Safety cap: 10K packets in queue. If exceeded, oldest packets
        # are silently dropped — prevents unbounded memory on high traffic.
        self._lag_queue = deque(maxlen=10000)
        self._lag_lock = threading.Lock()
        self._lag_thread = None
        self._running = True
        self._inbound_lagged = 0
        self._inbound_dropped = 0
        self._inbound_keepalive = 0
        self._outbound_passed = 0
        # NAT keepalive: timestamp of last packet we let through unlagged
        keepalive_ms = params.get("godmode_keepalive_interval_ms", 800)
        self._keepalive_interval = max(0, keepalive_ms) / 1000.0
        self._last_keepalive = 0.0

    def start_flush_thread(self, send_fn, divert_dll, handle):
        """Start background thread that flushes lagged inbound packets."""
        self._send_fn = send_fn
        self._divert_dll = divert_dll
        self._handle = handle
        self._lag_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="GodModeFlush"
        )
        self._lag_thread.start()

    def _flush_loop(self):
        while self._running:
            now = time.time()
            to_send = []
            with self._lag_lock:
                while self._lag_queue and self._lag_queue[0][0] <= now:
                    to_send.append(self._lag_queue.popleft())

            for _, pkt_data, addr in to_send:
                try:
                    self._send_fn(pkt_data, addr)
                except Exception:
                    pass
            time.sleep(0.001)

    def process(self, packet_data, addr, send_fn):
        if addr.Outbound:
            # OUTBOUND — target's actions → server. Pass through untouched.
            self._outbound_passed += 1
            return False  # let it through

        # INBOUND — server state updates → target. Lag heavily.
        self._inbound_lagged += 1
        now = time.time()

        # NAT keepalive: periodically let one inbound packet through unlagged.
        # One packet per interval (~800ms) in DayZ's ~60-tick UDP stream is
        # ~1 out of 48 frames — not enough for the client to meaningfully
        # update, but enough to keep the NAT mapping alive.
        if self._keepalive_interval > 0:
            if now - self._last_keepalive >= self._keepalive_interval:
                self._last_keepalive = now
                self._inbound_keepalive += 1
                return False  # let this one through for NAT keepalive

        # Optional inbound drop for more aggressive freeze
        drop_pct = min(100, max(0, self.params.get("godmode_drop_inbound_pct", 0)))
        if drop_pct > 0 and self._roll(drop_pct):
            self._inbound_dropped += 1
            return True

        # Lag the inbound packet
        delay_ms = self.params.get("godmode_lag_ms", 2000)
        delay_ms = max(0, min(30000, delay_ms))  # clamp 0-30s safety
        release_time = now + (delay_ms / 1000.0)
        addr_copy = WINDIVERT_ADDRESS()
        ctypes.memmove(ctypes.byref(addr_copy), ctypes.byref(addr),
                        ctypes.sizeof(WINDIVERT_ADDRESS))
        with self._lag_lock:
            self._lag_queue.append((release_time, bytearray(packet_data), addr_copy))
        return True  # consumed — will be sent later

    def stop(self):
        self._running = False
        if self._lag_thread and self._lag_thread.is_alive():
            self._lag_thread.join(timeout=1.0)
        # Flush remaining queued packets so the target's client catches up.
        # Dropping them would cause permanent desync — the game server thinks
        # it sent those state updates but the client never received them.
        # Flushing lets DayZ's Enfusion engine reconcile naturally.
        #
        # Release in small bursts to avoid packet storm that could overwhelm
        # NAT or trigger DayZ anti-flood. ~50 packets per burst with 5ms
        # pause between bursts.
        flushed = 0
        with self._lag_lock:
            remaining = list(self._lag_queue)
            self._lag_queue.clear()
        BURST_SIZE = 50
        for i, (_, pkt_data, addr) in enumerate(remaining):
            try:
                self._send_fn(pkt_data, addr)
                flushed += 1
            except Exception:
                pass
            # Brief pause between bursts to avoid overwhelming NAT
            if (i + 1) % BURST_SIZE == 0 and i + 1 < len(remaining):
                time.sleep(0.005)  # 5ms between bursts
        log_info(f"GodMode stats: inbound_lagged={self._inbound_lagged}, "
                 f"inbound_dropped={self._inbound_dropped}, "
                 f"keepalive_passed={self._inbound_keepalive}, "
                 f"outbound_passed={self._outbound_passed}, "
                 f"queue_flushed={flushed}")

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
    "godmode":    GodModeModule,
}
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
        self._packets_inbound = 0
        self._packets_outbound = 0
        self._packets_passed = 0

        # Pre-allocated send buffer — avoids per-packet ctypes allocation.
        # Protected by _send_lock since flush threads also call _send_packet.
        self._send_buf = (ctypes.c_uint8 * MAX_PACKET_SIZE)()
        self._send_len = wintypes.UINT(0)
        self._send_lock = threading.Lock()

        # Target IP for stats reporting
        self.target_ip = params.get("_target_ip", "unknown")

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

    def get_stats(self) -> Dict:
        """Return live packet counters for this engine instance."""
        return {
            "packets_processed": self._packets_processed,
            "packets_dropped": self._packets_dropped,
            "packets_inbound": self._packets_inbound,
            "packets_outbound": self._packets_outbound,
            "packets_passed": self._packets_passed,
            "alive": self.alive,
            "target_ip": self.target_ip,
            "methods": list(self.methods),
        }

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

            try:
                kernel32 = ctypes.windll.kernel32
                kernel32.SetDllDirectoryW(dll_dir)
                log_info(f"NativeEngine: SetDllDirectoryW({dll_dir})")
            except Exception as e:
                log_error(f"NativeEngine: SetDllDirectoryW failed: {e}")
                # Fall back to adding to PATH
                os.environ["PATH"] = dll_dir + ";" + os.environ.get("PATH", "")

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
                hint = _WINDIVERT_ERR_HINTS.get(err, "unknown")
                log_error(f"NativeEngine: WinDivertOpen FAILED (error={err}: {hint})")
                return False

            log_info(f"NativeEngine: handle opened successfully ({self._handle})")

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

        # Stop modules first — flush threads need the handle still open
        # to send queued packets (GodMode flush, Lag flush)
        for mod in self._modules:
            if hasattr(mod, 'stop'):
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
        Order: godmode → disconnect → drop → bandwidth → throttle → lag → ood → duplicate → corrupt → rst

        God Mode is special: it handles direction internally (lag inbound,
        pass outbound) so it goes first.  If godmode is active, other
        modules only see packets that godmode didn't consume.
        """
        # Enforce optimal module order for maximum disruption
        PRIORITY_ORDER = [
            "godmode", "disconnect", "drop", "bandwidth", "throttle",
            "lag", "ood", "duplicate", "corrupt", "rst",
        ]
        ordered_methods = [m for m in PRIORITY_ORDER if m in self.methods]
        ordered_methods += [m for m in self.methods if m not in ordered_methods]

        # Auto-detect lag passthrough mode: if lag is stacked with
        # duplicate or ood, lag should NOT consume packets — it should
        # queue a delayed copy and let the original continue to downstream
        # modules. This is what creates desync combos.
        has_downstream = bool({"duplicate", "ood"} & set(self.methods))
        if has_downstream and "lag_passthrough" not in self.params:
            self.params["lag_passthrough"] = True
            log_info("NativeEngine: auto-enabled lag passthrough "
                     "(stacked with duplicate/ood for desync)")

        self._modules = []
        for method_name in ordered_methods:
            cls = MODULE_MAP.get(method_name)
            if cls:
                mod = cls(self.params)
                self._modules.append(mod)
                log_info(f"NativeEngine: module '{method_name}' initialized "
                         f"(direction={mod.direction})"
                         f"{' [passthrough]' if isinstance(mod, LagModule) and mod._passthrough else ''}")

                # Start flush threads for modules that need them
                if isinstance(mod, (LagModule, GodModeModule)):
                    mod.start_flush_thread(
                        self._send_packet, self._divert, self._handle
                    )
            else:
                log_info(f"NativeEngine: unknown module '{method_name}' — skip")
        log_info(f"NativeEngine: module chain = "
                 f"{[f'{m.__class__.__name__}({m.direction})' for m in self._modules]}")

    def _send_packet(self, packet_data, addr):
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
        except Exception:
            pass  # best-effort send

    def _packet_loop(self):
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

                # Track direction
                if addr.Outbound:
                    self._packets_outbound += 1
                else:
                    self._packets_inbound += 1

                # Copy packet data to mutable bytearray
                packet_data = bytearray(packet_buf[:pkt_len])

                # Run through disruption module chain.
                # Direction check: each module only processes packets that
                # match its direction filter.  Modules whose direction
                # doesn't match are silently skipped for this packet.
                #
                # If ANY module consumes the packet (returns True), the
                # packet is gone — no further modules see it.
                # Stacking example: disconnect(100%) + drop(95%) — if
                # disconnect catches it first, drop never runs.
                consumed = False
                for mod in self._modules:
                    # Skip module if direction doesn't match
                    if not mod.matches_direction(addr):
                        continue
                    result = mod.process(packet_data, addr, self._send_packet)
                    if result:
                        consumed = True
                        self._packets_dropped += 1
                        break  # packet consumed (dropped, deferred, or duplicated)

                # If no module consumed it, send it through
                if not consumed:
                    self._packets_passed += 1
                    self._send_packet(packet_data, addr)

            except Exception as e:
                if not self._running:
                    break
                log_error(f"NativeEngine: packet loop error: {e}")
                time.sleep(0.001)

        log_info("NativeEngine: packet loop exited")

