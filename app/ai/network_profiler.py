#!/usr/bin/env python3
"""
Network Profiler — real-time characterization of target connections.

Probes a target IP and builds a NetworkProfile containing:
  - avg_rtt / min_rtt / max_rtt / jitter  (ICMP ping)
  - estimated_bandwidth                    (TCP throughput probe)
  - packet_loss_rate                       (ICMP loss %)
  - protocol_distribution                  (TCP vs UDP vs other)
  - hop_count                              (TTL-based estimate)
  - connection_type                        (local / LAN / WAN / hotspot)
  - device_type                            (console / PC / mobile / router)
  - port_fingerprint                       (open ports for identification)

The profile is the input to SmartDisruptionEngine — it decides
what settings will be most effective against THIS specific connection.
"""

from __future__ import annotations

import re
import sys
import time
import socket
import threading
import statistics
import subprocess
from dataclasses import dataclass, field, asdict
from typing import List
from app.logs.logger import log_info, log_error
from app.utils.helpers import mask_ip, _NO_WINDOW

__all__ = ["NetworkProfile", "NetworkProfiler"]

@dataclass
class NetworkProfile:
    """Complete characterization of a target connection."""

    target_ip: str = ""
    timestamp: float = 0.0

    # Latency
    avg_rtt_ms: float = 0.0
    min_rtt_ms: float = 0.0
    max_rtt_ms: float = 0.0
    jitter_ms: float = 0.0
    rtt_samples: List[float] = field(default_factory=list)

    # Reliability
    packet_loss_pct: float = 0.0
    packets_sent: int = 0
    packets_received: int = 0

    # Throughput
    estimated_bandwidth_kbps: float = 0.0

    # Topology
    hop_count: int = 0
    connection_type: str = "unknown"   # local, lan, hotspot, wan
    is_behind_nat: bool = False

    # Device identification
    device_type: str = "unknown"       # console, pc, mobile, router, iot
    device_hint: str = ""              # e.g. "PlayStation", "Xbox", "iPhone"
    open_ports: List[int] = field(default_factory=list)

    # Platform identification (v5.1 — drives platform-specific config)
    platform: str = "unknown"          # ps5, ps4, xbox_series, xbox_one, pc
    interception_layer: str = "NETWORK_FORWARD"  # from game profile platform_support
    recommended_keepalive_ms: int = 800           # NAT keepalive from platform config

    # Protocol mix (from brief traffic capture if available)
    tcp_pct: float = 50.0
    udp_pct: float = 50.0

    # Derived quality score (0-100, higher = better connection)
    quality_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class NetworkProfiler:
    """Probes a target IP and builds a NetworkProfile."""

    # Common gaming ports to fingerprint
    _GAME_PORTS = [
        3074,   # Xbox Live / PSN
        3478, 3479, 3480,  # PSN / STUN
        9306, 9308,        # DayZ
        27015, 27016,      # Steam / Source
        25565,             # Minecraft
        7777, 7778,        # Unreal / ARK
        30000, 30001,      # Various
    ]
    _COMMON_PORTS = [80, 443, 22, 53, 8080, 3389, 5353]

    def __init__(self, ping_count: int = 10, ping_timeout: float = 2.0,
                 port_scan_enabled: bool = True) -> None:
        self.ping_count = ping_count
        self.ping_timeout = ping_timeout
        self.port_scan_enabled = port_scan_enabled

    def profile(self, target_ip: str, device_info: dict = None) -> NetworkProfile:
        """Run full profiling suite on target IP. Blocks until complete."""
        log_info(f"NetworkProfiler: profiling {mask_ip(target_ip)}...")
        start = time.time()

        profile = NetworkProfile(
            target_ip=target_ip,
            timestamp=time.time(),
        )

        # 1. Ping probe (RTT, jitter, loss)
        self._probe_ping(profile)

        # 2. Connection type detection
        self._detect_connection_type(profile)

        # 3. Hop count (TTL analysis)
        self._estimate_hops(profile)

        # 4. Port fingerprint (parallel, fast)
        if self.port_scan_enabled:
            self._scan_ports(profile)

        # 5. Device type inference
        self._infer_device_type(profile, device_info)

        # 6. Bandwidth estimation (lightweight)
        self._estimate_bandwidth(profile)

        # 7. Compute quality score
        self._compute_quality_score(profile)

        elapsed = time.time() - start
        log_info(f"NetworkProfiler: {mask_ip(target_ip)} profiled in {elapsed:.1f}s "
                 f"(rtt={profile.avg_rtt_ms:.1f}ms, loss={profile.packet_loss_pct:.0f}%, "
                 f"quality={profile.quality_score:.0f}/100, type={profile.connection_type}, "
                 f"device={profile.device_type})")
        return profile

    def profile_async(self, target_ip: str, callback=None,
                      device_info: dict = None) -> None:
        """Profile in background thread, call callback(profile) when done."""
        def _run():
            result = self.profile(target_ip, device_info)
            if callback:
                callback(result)
        t = threading.Thread(target=_run, daemon=True, name=f"Profile-{target_ip}")
        t.start()
        return t

    # Probe: ICMP Ping
    def _probe_ping(self, profile: NetworkProfile) -> None:
        """Send ICMP pings via system ping command and parse results."""
        try:
            # Windows ping: -n count, -w timeout_ms
            cmd = ["ping", "-n", str(self.ping_count),
                   "-w", str(int(self.ping_timeout * 1000)),
                   profile.target_ip]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                creationflags=_NO_WINDOW,
            )
            output = result.stdout

            # Parse RTT values from "time=XXms" or "time<1ms"
            rtt_matches = re.findall(r'time[=<](\d+)ms', output)
            if rtt_matches:
                rtts = [float(x) for x in rtt_matches]
                profile.rtt_samples = rtts
                profile.avg_rtt_ms = statistics.mean(rtts)
                profile.min_rtt_ms = min(rtts)
                profile.max_rtt_ms = max(rtts)
                if len(rtts) > 1:
                    profile.jitter_ms = statistics.stdev(rtts)

            # Parse loss
            loss_match = re.search(r'(\d+)% loss', output)
            if loss_match:
                profile.packet_loss_pct = float(loss_match.group(1))

            profile.packets_sent = self.ping_count
            profile.packets_received = len(profile.rtt_samples)

            # Parse TTL for hop estimation
            ttl_match = re.search(r'TTL=(\d+)', output)
            if ttl_match:
                ttl = int(ttl_match.group(1))
                # Common initial TTLs: 64 (Linux/Mac/PS), 128 (Windows/Xbox), 255 (router)
                if ttl <= 64:
                    profile.hop_count = 64 - ttl
                elif ttl <= 128:
                    profile.hop_count = 128 - ttl
                else:
                    profile.hop_count = 255 - ttl

        except subprocess.TimeoutExpired:
            log_error(f"NetworkProfiler: ping to {mask_ip(profile.target_ip)} timed out")
            profile.packet_loss_pct = 100.0
        except Exception as e:
            log_error(f"NetworkProfiler: ping failed: {e}")
            profile.packet_loss_pct = 100.0

    # Connection Type Detection
    def _detect_connection_type(self, profile: NetworkProfile) -> None:
        """Determine if target is local, LAN, hotspot, or WAN."""
        ip = profile.target_ip
        if ip.startswith("127.") or ip == "::1":
            profile.connection_type = "local"
        elif ip.startswith("192.168.137."):
            # Windows ICS / Mobile Hotspot subnet
            profile.connection_type = "hotspot"
        elif (ip.startswith("192.168.") or ip.startswith("10.") or
              self._is_172_private(ip)):
            profile.connection_type = "lan"
        else:
            profile.connection_type = "wan"

    @staticmethod
    def _is_172_private(ip: str) -> bool:
        """Check if IP is in the 172.16.0.0/12 private range (172.16-31.x.x)."""
        if not ip.startswith("172."):
            return False
        try:
            second_octet = int(ip.split(".")[1])
            return 16 <= second_octet <= 31
        except (IndexError, ValueError):
            return False

    # Hop Count Estimation
    def _estimate_hops(self, profile: NetworkProfile) -> None:
        """Already extracted from ping TTL. Add traceroute if needed."""
        # hop_count was set in _probe_ping from TTL
        if profile.hop_count == 0 and profile.connection_type in ("lan", "hotspot"):
            profile.hop_count = 1  # reasonable default for local devices

    # Port Scanning
    def _scan_ports(self, profile: NetworkProfile) -> None:
        """Quick TCP connect scan on gaming + common ports."""
        ports_to_scan = self._GAME_PORTS + self._COMMON_PORTS
        open_ports = []
        lock = threading.Lock()

        def _check_port(port):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.5)
                    if sock.connect_ex((profile.target_ip, port)) == 0:
                        with lock:
                            open_ports.append(port)
            except Exception:
                pass

        threads = []
        for port in ports_to_scan:
            t = threading.Thread(target=_check_port, args=(port,), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=2.0)

        profile.open_ports = sorted(open_ports)

    # Device Type Inference
    def _infer_device_type(self, profile: NetworkProfile,
                           device_info: dict = None) -> None:
        """Infer device type from ports, TTL, and scanner info.

        v5.1: Also sets platform identifier (ps5, xbox_series, pc, etc.)
        and loads platform-specific config from the game profile.
        """
        # Map keywords → (device_type, hint, platform_key)
        _DTYPE_MAP = {
            'ps5': ('console', 'PlayStation 5', 'ps5'),
            'playstation 5': ('console', 'PlayStation 5', 'ps5'),
            'ps4': ('console', 'PlayStation 4', 'ps4'),
            'playstation 4': ('console', 'PlayStation 4', 'ps4'),
            'playstation': ('console', 'PlayStation', 'ps5'),  # assume PS5 if ambiguous
            'xbox series': ('console', 'Xbox Series X|S', 'xbox_series'),
            'xbox one': ('console', 'Xbox One', 'xbox_one'),
            'xbox': ('console', 'Xbox', 'xbox_series'),  # assume Series if ambiguous
            'nintendo': ('console', 'Nintendo', 'pc'),  # no DayZ on Nintendo, treat as generic
            'switch': ('console', 'Nintendo', 'pc'),
            'iphone': ('mobile', 'iPhone', 'pc'),
            'android': ('mobile', 'Android', 'pc'),
            'mobile': ('mobile', 'Mobile', 'pc'),
            'pc': ('pc', 'PC', 'pc'),
            'windows': ('pc', 'Windows PC', 'pc'),
            'computer': ('pc', 'PC', 'pc'),
        }
        if device_info:
            dtype = device_info.get("device_type", "").lower()
            for kw, (dev_type, hint, plat) in _DTYPE_MAP.items():
                if kw in dtype:
                    profile.device_type = dev_type
                    profile.device_hint = hint
                    profile.platform = plat
                    self._apply_platform_config(profile)
                    return

        # Port-based heuristics
        gaming_ports_open = set(profile.open_ports) & set(self._GAME_PORTS)
        if gaming_ports_open:
            # PSN / XBL distinction
            psn_ports = {3478, 3479, 3480}
            xbl_ports = {3074}
            if psn_ports & set(profile.open_ports):
                profile.device_type = "console"
                profile.device_hint = "PlayStation (PSN ports detected)"
                profile.platform = "ps5"
            elif xbl_ports & set(profile.open_ports) and not (psn_ports & set(profile.open_ports)):
                profile.device_type = "console"
                profile.device_hint = "Xbox (XBL port 3074 detected)"
                profile.platform = "xbox_series"
            else:
                profile.device_type = "pc"
                profile.device_hint = "Gaming PC (game server ports open)"
                profile.platform = "pc"
        elif 3389 in profile.open_ports:
            profile.device_type = "pc"
            profile.device_hint = "Windows PC (RDP open)"
            profile.platform = "pc"
        elif 80 in profile.open_ports and 443 not in profile.open_ports:
            profile.device_type = "iot"
            profile.device_hint = "IoT/Router (HTTP only)"
            profile.platform = "pc"
        else:
            profile.device_type = "unknown"
            # Default to console on hotspot (most common DupeZ use case)
            if profile.connection_type == "hotspot":
                profile.platform = "ps5"
            else:
                profile.platform = "pc"

        self._apply_platform_config(profile)

    def _apply_platform_config(self, profile: NetworkProfile) -> None:
        """Load platform-specific settings from game profile."""
        try:
            from app.config.game_profiles import get_platform_config
            plat_cfg = get_platform_config("dayz", profile.platform)
            if plat_cfg:
                profile.interception_layer = plat_cfg.get(
                    "interception_layer", "NETWORK_FORWARD")
                profile.recommended_keepalive_ms = plat_cfg.get(
                    "keepalive_interval_ms", 800)
                log_info(f"NetworkProfiler: platform={profile.platform} — "
                         f"layer={profile.interception_layer}, "
                         f"keepalive={profile.recommended_keepalive_ms}ms")
        except Exception:
            # Fall back to defaults already set on NetworkProfile
            pass

    # Bandwidth Estimation
    def _estimate_bandwidth(self, profile: NetworkProfile) -> None:
        """Lightweight bandwidth estimate based on RTT and connection type."""
        # Full bandwidth probing would require a cooperative endpoint.
        # Instead, estimate from connection type and RTT characteristics.
        # (rtt_threshold, bandwidth) pairs — first match wins; fallback is last value
        _BW_TABLE = {
            "local":   [(float('inf'), 1000000)],
            "hotspot": [(5, 25000), (20, 10000), (float('inf'), 5000)],
            "lan":     [(2, 100000), (float('inf'), 50000)],
            "wan":     [(30, 50000), (100, 10000), (float('inf'), 2000)],
        }
        for threshold, bw in _BW_TABLE.get(profile.connection_type, _BW_TABLE["wan"]):
            if profile.avg_rtt_ms < threshold:
                profile.estimated_bandwidth_kbps = bw
                break

    # Quality Score
    def _compute_quality_score(self, profile: NetworkProfile) -> None:
        """Compute connection quality 0-100 (higher = better = harder to disrupt)."""
        score = 100.0

        # Penalize high RTT (>50ms starts hurting)
        if profile.avg_rtt_ms > 50:
            score -= min(30, (profile.avg_rtt_ms - 50) * 0.3)

        # Penalize jitter
        if profile.jitter_ms > 10:
            score -= min(20, profile.jitter_ms * 0.5)

        # Penalize packet loss
        score -= profile.packet_loss_pct * 0.5

        # Penalize low bandwidth
        if profile.estimated_bandwidth_kbps < 5000:
            score -= 15
        elif profile.estimated_bandwidth_kbps < 10000:
            score -= 5

        # Bonus for direct connections (fewer hops = more control)
        if profile.hop_count <= 1:
            score += 5

        profile.quality_score = max(0, min(100, score))

