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

import os
import sys
import time
import socket
import struct
import threading
import statistics
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from app.logs.logger import log_info, log_error


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

    # Protocol mix (from brief traffic capture if available)
    tcp_pct: float = 50.0
    udp_pct: float = 50.0

    # Derived quality score (0-100, higher = better connection)
    quality_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_feature_vector(self) -> List[float]:
        """Convert profile to numeric feature vector for the ML model."""
        conn_type_map = {"local": 0, "lan": 1, "hotspot": 2, "wan": 3, "unknown": 2}
        dev_type_map = {"console": 0, "pc": 1, "mobile": 2, "router": 3, "iot": 4, "unknown": 2}

        return [
            self.avg_rtt_ms,
            self.jitter_ms,
            self.packet_loss_pct,
            self.estimated_bandwidth_kbps,
            self.hop_count,
            conn_type_map.get(self.connection_type, 2),
            dev_type_map.get(self.device_type, 2),
            self.tcp_pct,
            self.udp_pct,
            self.quality_score,
            len(self.open_ports),
            1.0 if self.is_behind_nat else 0.0,
        ]


class NetworkProfiler:
    """Probes a target IP and builds a NetworkProfile.

    Usage:
        profiler = NetworkProfiler()
        profile = profiler.profile("192.168.137.5")
        # or async:
        profiler.profile_async("192.168.137.5", callback=on_done)
    """

    def __init__(self, ping_count: int = 10, ping_timeout: float = 2.0,
                 port_scan_enabled: bool = True):
        self.ping_count = ping_count
        self.ping_timeout = ping_timeout
        self.port_scan_enabled = port_scan_enabled

        # Common gaming ports to fingerprint
        self._game_ports = [
            3074,   # Xbox Live / PSN
            3478, 3479, 3480,  # PSN / STUN
            9306, 9308,        # DayZ
            27015, 27016,      # Steam / Source
            25565,             # Minecraft
            7777, 7778,        # Unreal / ARK
            30000, 30001,      # Various
        ]
        self._common_ports = [80, 443, 22, 53, 8080, 3389, 5353]

    def profile(self, target_ip: str, device_info: dict = None) -> NetworkProfile:
        """Run full profiling suite on target IP. Blocks until complete."""
        log_info(f"NetworkProfiler: profiling {target_ip}...")
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
        log_info(f"NetworkProfiler: {target_ip} profiled in {elapsed:.1f}s "
                 f"(rtt={profile.avg_rtt_ms:.1f}ms, loss={profile.packet_loss_pct:.0f}%, "
                 f"quality={profile.quality_score:.0f}/100, type={profile.connection_type}, "
                 f"device={profile.device_type})")
        return profile

    def profile_async(self, target_ip: str, callback=None,
                      device_info: dict = None):
        """Profile in background thread, call callback(profile) when done."""
        def _run():
            result = self.profile(target_ip, device_info)
            if callback:
                callback(result)
        t = threading.Thread(target=_run, daemon=True, name=f"Profile-{target_ip}")
        t.start()
        return t

    # ------------------------------------------------------------------
    # Probe: ICMP Ping
    # ------------------------------------------------------------------
    def _probe_ping(self, profile: NetworkProfile):
        """Send ICMP pings via system ping command and parse results."""
        try:
            # Windows ping: -n count, -w timeout_ms
            cmd = ["ping", "-n", str(self.ping_count),
                   "-w", str(int(self.ping_timeout * 1000)),
                   profile.target_ip]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            output = result.stdout

            # Parse RTT values from "time=XXms" or "time<1ms"
            import re
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
            log_error(f"NetworkProfiler: ping to {profile.target_ip} timed out")
            profile.packet_loss_pct = 100.0
        except Exception as e:
            log_error(f"NetworkProfiler: ping failed: {e}")
            profile.packet_loss_pct = 100.0

    # ------------------------------------------------------------------
    # Connection Type Detection
    # ------------------------------------------------------------------
    def _detect_connection_type(self, profile: NetworkProfile):
        """Determine if target is local, LAN, hotspot, or WAN."""
        ip = profile.target_ip
        if ip.startswith("127.") or ip == "::1":
            profile.connection_type = "local"
        elif ip.startswith("192.168.137."):
            # Windows ICS / Mobile Hotspot subnet
            profile.connection_type = "hotspot"
        elif (ip.startswith("192.168.") or ip.startswith("10.") or
              ip.startswith("172.16.") or ip.startswith("172.17.") or
              ip.startswith("172.18.") or ip.startswith("172.19.") or
              ip.startswith("172.2") or ip.startswith("172.30.") or
              ip.startswith("172.31.")):
            profile.connection_type = "lan"
        else:
            profile.connection_type = "wan"

    # ------------------------------------------------------------------
    # Hop Count Estimation
    # ------------------------------------------------------------------
    def _estimate_hops(self, profile: NetworkProfile):
        """Already extracted from ping TTL. Add traceroute if needed."""
        # hop_count was set in _probe_ping from TTL
        if profile.hop_count == 0 and profile.connection_type in ("lan", "hotspot"):
            profile.hop_count = 1  # reasonable default for local devices

    # ------------------------------------------------------------------
    # Port Scanning
    # ------------------------------------------------------------------
    def _scan_ports(self, profile: NetworkProfile):
        """Quick TCP connect scan on gaming + common ports."""
        ports_to_scan = self._game_ports + self._common_ports
        open_ports = []
        lock = threading.Lock()

        def _check_port(port):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex((profile.target_ip, port))
                sock.close()
                if result == 0:
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

    # ------------------------------------------------------------------
    # Device Type Inference
    # ------------------------------------------------------------------
    def _infer_device_type(self, profile: NetworkProfile,
                           device_info: dict = None):
        """Infer device type from ports, TTL, and scanner info."""
        # If the scanner already identified the device, use that
        if device_info:
            dtype = device_info.get("device_type", "").lower()
            if "playstation" in dtype or "ps5" in dtype or "ps4" in dtype:
                profile.device_type = "console"
                profile.device_hint = "PlayStation"
                return
            elif "xbox" in dtype:
                profile.device_type = "console"
                profile.device_hint = "Xbox"
                return
            elif "nintendo" in dtype or "switch" in dtype:
                profile.device_type = "console"
                profile.device_hint = "Nintendo"
                return
            elif "iphone" in dtype or "android" in dtype or "mobile" in dtype:
                profile.device_type = "mobile"
                profile.device_hint = dtype.title()
                return

        # Port-based heuristics
        gaming_ports_open = set(profile.open_ports) & set(self._game_ports)
        if gaming_ports_open:
            # PSN ports
            if {3074, 3478, 3479, 3480} & set(profile.open_ports):
                profile.device_type = "console"
                profile.device_hint = "PlayStation/Xbox (PSN/XBL ports)"
            else:
                profile.device_type = "pc"
                profile.device_hint = "Gaming PC (game server ports open)"
        elif 3389 in profile.open_ports:
            profile.device_type = "pc"
            profile.device_hint = "Windows PC (RDP open)"
        elif 80 in profile.open_ports and 443 not in profile.open_ports:
            profile.device_type = "iot"
            profile.device_hint = "IoT/Router (HTTP only)"
        else:
            # TTL-based guess
            if profile.hop_count >= 0:
                # Low TTL start = Linux/PS (64), High = Windows/Xbox (128)
                # This is already normalized to hops, so use raw for inference
                pass
            profile.device_type = "unknown"

    # ------------------------------------------------------------------
    # Bandwidth Estimation
    # ------------------------------------------------------------------
    def _estimate_bandwidth(self, profile: NetworkProfile):
        """Lightweight bandwidth estimate based on RTT and connection type."""
        # Full bandwidth probing would require a cooperative endpoint.
        # Instead, estimate from connection type and RTT characteristics.
        if profile.connection_type == "local":
            profile.estimated_bandwidth_kbps = 1000000  # loopback
        elif profile.connection_type == "hotspot":
            # Mobile hotspot: typically 5-50 Mbps shared
            # Use RTT as a rough indicator of congestion
            if profile.avg_rtt_ms < 5:
                profile.estimated_bandwidth_kbps = 25000
            elif profile.avg_rtt_ms < 20:
                profile.estimated_bandwidth_kbps = 10000
            else:
                profile.estimated_bandwidth_kbps = 5000
        elif profile.connection_type == "lan":
            if profile.avg_rtt_ms < 2:
                profile.estimated_bandwidth_kbps = 100000  # gigabit
            else:
                profile.estimated_bandwidth_kbps = 50000
        else:  # wan
            if profile.avg_rtt_ms < 30:
                profile.estimated_bandwidth_kbps = 50000
            elif profile.avg_rtt_ms < 100:
                profile.estimated_bandwidth_kbps = 10000
            else:
                profile.estimated_bandwidth_kbps = 2000

    # ------------------------------------------------------------------
    # Quality Score
    # ------------------------------------------------------------------
    def _compute_quality_score(self, profile: NetworkProfile):
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
