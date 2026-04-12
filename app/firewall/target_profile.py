#!/usr/bin/env python3
"""Target profile auto-detection.

Given a target IP (and optionally MAC / hostname / device_type from a
prior scan), returns the appropriate disruption profile name from the
``dayz.json`` ``disruption_presets`` section:

    pc_local       — DupeZ and the game are on the same PC (NETWORK layer).
    ps5_hotspot    — PS5 on the Windows Mobile Hotspot (NETWORK_FORWARD).
    xbox_hotspot   — Xbox on the Windows Mobile Hotspot (NETWORK_FORWARD).

Detection ladder:

1. **Layer** — subnet check against ``192.168.137.0/24`` (Windows ICS /
   Mobile Hotspot default). Any target inside that subnet must use the
   NETWORK_FORWARD layer; anything else is treated as PC-local.

2. **Platform** (only matters on the FORWARD layer):
   a. MAC OUI check against the Sony / Microsoft prefix tables.
   b. Hostname regex fallback (``ps5``, ``playstation``, ``sony`` vs
      ``xbox``, ``xboxone``).
   c. ``device_type`` hint from ``enhanced_scanner`` if the caller has
      already tagged it.
   d. If nothing matches → default to ``ps5_hotspot`` (most common use
      case for this tool, and the most conservative tuning for the
      DayZ 1.27+ freeze threshold).

The function is mostly pure. The ``_is_wifi_same_network`` helper
performs a UDP socket connect to determine the local interface IP,
but this is a local kernel operation (no actual traffic). All other
helpers are pure — no network I/O, no side effects — so the module
is trivial to unit-test against synthetic inputs.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Dict, List, Optional, Tuple

__all__ = [
    "HOTSPOT_SUBNET",
    "resolve_target_profile",
    "DetectionResult",
    "CONNECTION_MODE_HOTSPOT",
    "CONNECTION_MODE_WIFI_SAME_NET",
    "CONNECTION_MODE_LOCAL",
]

# ── Connection modes ─────────────────────────────────────────────────
CONNECTION_MODE_HOTSPOT = "hotspot"            # ICS/mobile hotspot — we ARE the gateway
CONNECTION_MODE_WIFI_SAME_NET = "wifi_same_net"  # Same WiFi LAN — need ARP spoofing
CONNECTION_MODE_LOCAL = "local"                 # Same machine — NETWORK layer


# ── Subnet constants ──────────────────────────────────────────────────

# Windows Mobile Hotspot / ICS default /24. If Microsoft ever changes
# the default or the user has reconfigured ICS, add additional subnets
# to this tuple — the layer check is a simple membership test.
HOTSPOT_SUBNETS: Tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("192.168.137.0/24"),
)

HOTSPOT_SUBNET = HOTSPOT_SUBNETS[0]  # legacy single-subnet alias


# ── Platform OUI tables ───────────────────────────────────────────────
# Separated from enhanced_scanner's merged list so we can distinguish
# Sony from Microsoft without a full regex pass.

_SONY_OUI_PREFIXES: frozenset[str] = frozenset((
    # PlayStation family
    "b4:0a:d8", "b4:0a:d9", "b4:0a:da", "b4:0a:db",
    "0c:fe:45",
    "f8:d0:ac",
    "a8:e3:ee",  # Sony Interactive Entertainment (PS5 batches)
    "d4:4b:5e",
    "fc:0f:e6",
    "00:1f:a7",
    "00:19:c5",
    "00:13:15",
    "00:15:c1",
    "00:1d:0d",
    "00:24:8d",
))

_MICROSOFT_OUI_PREFIXES: frozenset[str] = frozenset((
    # Xbox family
    "7c:ed:8d", "98:de:d0", "60:45:bd",
    "58:82:a8",  # Microsoft Corporation (Xbox Series batches)
    "d4:f5:ef",
    "dc:32:d1",
    "00:50:f2",  # Microsoft
    "00:12:5a",
    "00:15:5d",
    "00:17:fa",
    "00:1d:d8",
    "00:22:48",
    "00:25:ae",
))


# ── Hostname regex fallback ───────────────────────────────────────────

_SONY_HOST_RE = re.compile(
    r"(?:^|[^a-z])(ps[345]|playstation|psn|sony)(?:[^a-z]|$)",
    re.IGNORECASE,
)
_MICROSOFT_HOST_RE = re.compile(
    r"(?:^|[^a-z])(xbox(?:one|360)?|xsx|xss)(?:[^a-z]|$)",
    re.IGNORECASE,
)


# ── Result type ───────────────────────────────────────────────────────

class DetectionResult:
    """Lightweight container for profile-resolution output.

    Attributes:
        profile: One of ``pc_local`` / ``ps5_hotspot`` / ``xbox_hotspot``
            / ``ps5_wifi`` / ``xbox_wifi``.
        layer:   ``local`` or ``forward``.
        platform: ``pc`` / ``ps5`` / ``xbox`` / ``unknown``.
        connection_mode: ``hotspot`` / ``wifi_same_net`` / ``local``.
        needs_arp_spoof: True if ARP spoofing is required.
        reasons: Human-readable detection trace, suitable for logging.
    """

    __slots__ = ("profile", "layer", "platform", "connection_mode",
                 "needs_arp_spoof", "reasons")

    def __init__(self, profile: str, layer: str, platform: str,
                 reasons: List[str],
                 connection_mode: str = CONNECTION_MODE_LOCAL,
                 needs_arp_spoof: bool = False) -> None:
        self.profile = profile
        self.layer = layer
        self.platform = platform
        self.connection_mode = connection_mode
        self.needs_arp_spoof = needs_arp_spoof
        self.reasons = reasons

    def __repr__(self) -> str:
        return (f"DetectionResult(profile={self.profile!r}, "
                f"layer={self.layer!r}, platform={self.platform!r}, "
                f"connection_mode={self.connection_mode!r})")

    def as_dict(self) -> Dict[str, object]:
        return {
            "profile": self.profile,
            "layer": self.layer,
            "platform": self.platform,
            "connection_mode": self.connection_mode,
            "needs_arp_spoof": self.needs_arp_spoof,
            "reasons": list(self.reasons),
        }


# ── Helpers ───────────────────────────────────────────────────────────

def _normalize_mac(mac: Optional[str]) -> str:
    """Lowercase + colon-separated. Empty string if unparseable."""
    if not mac:
        return ""
    clean = mac.strip().lower().replace("-", ":")
    # Accept "aa:bb:cc:dd:ee:ff" or "aabb.ccdd.eeff" or raw hex
    if "." in clean:  # Cisco-style
        parts = clean.split(".")
        hex_only = "".join(parts)
        if len(hex_only) == 12:
            clean = ":".join(hex_only[i:i + 2] for i in range(0, 12, 2))
    elif ":" not in clean and len(clean) == 12:
        clean = ":".join(clean[i:i + 2] for i in range(0, 12, 2))
    return clean


def _oui_prefix(mac: str) -> str:
    """Return the first 8 characters (``aa:bb:cc``) or empty string."""
    if len(mac) >= 8 and mac[2] == ":" and mac[5] == ":":
        return mac[:8]
    return ""


def _is_in_hotspot_subnet(target_ip: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(target_ip)
    except (ipaddress.AddressValueError, ValueError):
        return False
    return any(addr in net for net in HOTSPOT_SUBNETS)


def _is_wifi_same_network(target_ip: str) -> bool:
    """Return True if *target_ip* is on the same /24 as our local IP.

    This covers the case where the target device is on the same WiFi
    network but NOT connected through our hotspot.  Traffic between the
    target and the internet bypasses this machine entirely, so we need
    ARP spoofing to redirect it through us.
    """
    try:
        addr = ipaddress.IPv4Address(target_ip)
    except (ipaddress.AddressValueError, ValueError):
        return False

    # Already a hotspot device — no ARP spoofing needed
    if _is_in_hotspot_subnet(target_ip):
        return False

    # Loopback or link-local — not a WiFi device
    if addr.is_loopback or addr.is_link_local:
        return False

    try:
        import socket as _sock
        with _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM) as s:
            s.connect((target_ip, 80))
            local_ip = s.getsockname()[0]
        # Same /24 → same LAN segment
        local_net = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        return addr in local_net
    except Exception:
        return False


def _match_platform_by_mac(mac: str) -> Optional[str]:
    prefix = _oui_prefix(mac)
    if not prefix:
        return None
    if prefix in _SONY_OUI_PREFIXES:
        return "ps5"
    if prefix in _MICROSOFT_OUI_PREFIXES:
        return "xbox"
    return None


def _match_platform_by_hostname(hostname: str) -> Optional[str]:
    if not hostname:
        return None
    if _SONY_HOST_RE.search(hostname):
        return "ps5"
    if _MICROSOFT_HOST_RE.search(hostname):
        return "xbox"
    return None


def _match_platform_by_device_type(device_type: str) -> Optional[str]:
    if not device_type:
        return None
    low = device_type.lower()
    if "playstation" in low or "ps5" in low or "ps4" in low:
        return "ps5"
    if "xbox" in low:
        return "xbox"
    return None


# ── Public API ────────────────────────────────────────────────────────

def resolve_target_profile(
    target_ip: str,
    mac: Optional[str] = None,
    hostname: Optional[str] = None,
    device_type: Optional[str] = None,
) -> DetectionResult:
    """Resolve the disruption profile for *target_ip*.

    Args:
        target_ip: IPv4 address of the target device.
        mac: Optional MAC address (any common formatting accepted).
        hostname: Optional hostname from DHCP / reverse DNS.
        device_type: Optional pre-tagged device-type string from
            ``enhanced_scanner`` (e.g. ``"PlayStation"``).

    Returns:
        DetectionResult with ``profile``, ``layer``, ``platform`` and a
        list of reason strings describing why each choice was made.
        The profile is always one of ``pc_local`` / ``ps5_hotspot``
        / ``xbox_hotspot``.
    """
    reasons: List[str] = []

    # ── Layer & connection-mode decision ──────────────────────────
    if _is_in_hotspot_subnet(target_ip):
        layer = "forward"
        connection_mode = CONNECTION_MODE_HOTSPOT
        needs_arp_spoof = False
        reasons.append(
            f"target {target_ip} in hotspot subnet {HOTSPOT_SUBNET} "
            f"→ NETWORK_FORWARD (hotspot, no ARP spoof needed)"
        )
    elif _is_wifi_same_network(target_ip):
        layer = "forward"
        connection_mode = CONNECTION_MODE_WIFI_SAME_NET
        needs_arp_spoof = True
        reasons.append(
            f"target {target_ip} on same WiFi /24 but NOT hotspot "
            f"→ NETWORK_FORWARD via ARP spoofing"
        )
    else:
        layer = "local"
        connection_mode = CONNECTION_MODE_LOCAL
        needs_arp_spoof = False
        reasons.append(
            f"target {target_ip} outside hotspot and local subnet "
            f"→ NETWORK (local)"
        )

    # Local layer: platform is irrelevant — always pc_local.
    if layer == "local":
        return DetectionResult(
            profile="pc_local",
            layer="local",
            platform="pc",
            reasons=reasons,
            connection_mode=connection_mode,
            needs_arp_spoof=False,
        )

    # ── Platform decision (forward layer — hotspot or WiFi) ──────
    normalized_mac = _normalize_mac(mac)
    platform: Optional[str] = None

    if normalized_mac:
        platform = _match_platform_by_mac(normalized_mac)
        if platform:
            reasons.append(
                f"MAC OUI {_oui_prefix(normalized_mac)} → {platform}"
            )

    if platform is None and hostname:
        platform = _match_platform_by_hostname(hostname)
        if platform:
            reasons.append(
                f"hostname {hostname!r} matched {platform} pattern"
            )

    if platform is None and device_type:
        platform = _match_platform_by_device_type(device_type)
        if platform:
            reasons.append(
                f"device_type {device_type!r} → {platform}"
            )

    if platform is None:
        platform = "unknown"
        if connection_mode == CONNECTION_MODE_WIFI_SAME_NET:
            reasons.append(
                "no MAC/hostname/device_type match — defaulting to "
                "ps5_wifi (most conservative WiFi-same-net tuning)"
            )
        else:
            reasons.append(
                "no MAC/hostname/device_type match — defaulting to "
                "ps5_hotspot (most conservative forward-layer tuning)"
            )

    # Build profile name.  Both hotspot and WiFi-same-net use the same
    # preset tuning (WiFi triggers ARP spoofing but the disruption
    # params are identical).  Map to the existing hotspot preset keys.
    profile = "xbox_hotspot" if platform == "xbox" else "ps5_hotspot"

    return DetectionResult(
        profile=profile,
        layer=layer,
        platform=platform,
        reasons=reasons,
        connection_mode=connection_mode,
        needs_arp_spoof=needs_arp_spoof,
    )
