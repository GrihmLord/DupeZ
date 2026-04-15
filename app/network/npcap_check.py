# app/network/npcap_check.py — Npcap availability detector
"""Check whether Npcap (or legacy WinPcap) is installed so ARP-spoof
based features (LAN Cut, WiFi same-network interception) can work.

On non-Windows platforms this module reports the equivalent raw-socket
capability (AF_PACKET / root). No side effects, no imports of the
NpcapSender class — we only probe for the DLL.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from typing import Optional

__all__ = ["NpcapStatus", "check_npcap"]


_WPCAP_PATHS = (
    r"C:\Windows\System32\Npcap\wpcap.dll",
    r"C:\Windows\System32\wpcap.dll",
    r"C:\Windows\SysWOW64\Npcap\wpcap.dll",
    r"C:\Windows\SysWOW64\wpcap.dll",
)


@dataclass(frozen=True)
class NpcapStatus:
    available: bool
    dll_path: Optional[str]
    platform: str
    reason: str

    @property
    def install_url(self) -> str:
        return "https://npcap.com/#download"

    def short(self) -> str:
        if self.available:
            return f"Npcap OK ({self.dll_path or self.platform})"
        return f"Npcap MISSING — {self.reason}"


def check_npcap() -> NpcapStatus:
    """Return an NpcapStatus describing whether raw-packet send is available."""
    sysname = platform.system().lower()
    if sysname != "windows":
        # Linux / macOS: AF_PACKET / BPF — assume available when root.
        try:
            is_root = (os.geteuid() == 0)  # type: ignore[attr-defined]
        except AttributeError:
            is_root = False
        if is_root:
            return NpcapStatus(
                available=True, dll_path=None, platform=sysname,
                reason="AF_PACKET available (root)",
            )
        return NpcapStatus(
            available=False, dll_path=None, platform=sysname,
            reason="AF_PACKET requires root",
        )

    for path in _WPCAP_PATHS:
        if os.path.exists(path):
            return NpcapStatus(
                available=True, dll_path=path, platform="windows",
                reason="wpcap.dll found",
            )

    return NpcapStatus(
        available=False, dll_path=None, platform="windows",
        reason="wpcap.dll not found — install Npcap (WinPcap-compat mode)",
    )
