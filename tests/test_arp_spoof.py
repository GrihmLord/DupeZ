"""
Tests for app.network.arp_spoof — ARP cache poisoning subsystem.

The module is platform-bifurcated (Windows uses Npcap + ipconfig/arp/netsh;
Linux uses AF_PACKET + /proc + ip route). These tests focus on the pure
logic that doesn't need real sockets, real subprocess calls, or admin
privileges:

  1. Helpers — MAC encoding, network-membership, ARP frame layout
  2. Gateway / MAC discovery — mock safe_subprocess.run for both OSes
  3. IP-forwarding state — mock netsh on Windows, /proc on Linux
  4. ArpSpoofer lifecycle — mock the sender and forwarding helpers,
     assert start() resolves MACs and stop() restores ARP + forwarding

Tests run on Linux CI (sandbox) and Windows dev hosts. Where a code
path branches on platform, we monkeypatch _IS_WINDOWS instead of
spawning real Windows binaries.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
import types
from unittest.mock import MagicMock, patch

import pytest

from app.network import arp_spoof
from app.network.arp_spoof import (
    ArpSpoofer,
    _build_arp_reply,
    _mac_bytes_to_str,
    _mac_str_to_bytes,
    detect_wifi_same_network,
    get_default_gateway,
    get_local_mac,
    get_mac_for_ip,
    is_same_network,
)


# ── safe_subprocess result stub ──────────────────────────────────────

class _StubResult:
    """Mimics safe_subprocess.SubprocessResult — only stdout is read."""

    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode
        self.argv: tuple = ()
        self.duration_s = 0.0
        self.timed_out = False


# ── MAC encoding helpers ─────────────────────────────────────────────

class TestMacEncoding:
    def test_mac_str_to_bytes_colon(self):
        assert _mac_str_to_bytes("aa:bb:cc:dd:ee:ff") == \
            b"\xaa\xbb\xcc\xdd\xee\xff"

    def test_mac_str_to_bytes_dash(self):
        assert _mac_str_to_bytes("aa-bb-cc-dd-ee-ff") == \
            b"\xaa\xbb\xcc\xdd\xee\xff"

    def test_mac_str_to_bytes_uppercase(self):
        assert _mac_str_to_bytes("AA:BB:CC:DD:EE:FF") == \
            b"\xaa\xbb\xcc\xdd\xee\xff"

    def test_mac_str_to_bytes_invalid_octet_count(self):
        with pytest.raises(ValueError, match="6 octets"):
            _mac_str_to_bytes("aa:bb:cc")

    def test_mac_str_to_bytes_non_hex_raises(self):
        with pytest.raises(ValueError, match="non-hex"):
            _mac_str_to_bytes("zz:bb:cc:dd:ee:ff")

    def test_mac_bytes_to_str_roundtrip(self):
        for mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff",
                    "12:34:56:78:9a:bc", "de:ad:be:ef:ca:fe"):
            assert _mac_bytes_to_str(_mac_str_to_bytes(mac)) == mac


# ── is_same_network ─────────────────────────────────────────────────

class TestIsSameNetwork:
    def test_same_24(self):
        assert is_same_network("192.168.1.10", "192.168.1.250") is True

    def test_different_24(self):
        assert is_same_network("192.168.1.10", "192.168.2.10") is False

    def test_custom_prefix_8(self):
        assert is_same_network("10.0.0.1", "10.255.255.1",
                                prefix_len=8) is True

    def test_custom_prefix_30_boundary(self):
        # 192.168.1.0/30 == .0, .1, .2, .3
        assert is_same_network("192.168.1.1", "192.168.1.2",
                                prefix_len=30) is True
        assert is_same_network("192.168.1.3", "192.168.1.4",
                                prefix_len=30) is False

    def test_invalid_ips_return_false(self):
        assert is_same_network("not-an-ip", "192.168.1.1") is False
        assert is_same_network("192.168.1.1", "999.999.999.999") is False


# ── _build_arp_reply ─────────────────────────────────────────────────

class TestBuildArpReply:
    SRC_MAC = b"\xaa\xaa\xaa\xaa\xaa\xaa"
    DST_MAC = b"\xbb\xbb\xbb\xbb\xbb\xbb"
    SRC_IP = "192.168.1.10"
    DST_IP = "192.168.1.1"

    def test_frame_total_length(self):
        # Ethernet header (14) + ARP payload (28) = 42 bytes
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP)
        assert len(frame) == 42

    def test_ethernet_dst_is_target(self):
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP)
        assert frame[0:6] == self.DST_MAC

    def test_ethernet_src_defaults_to_arp_sender(self):
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP)
        assert frame[6:12] == self.SRC_MAC

    def test_ethernet_src_override(self):
        spoof_eth = b"\xcc\xcc\xcc\xcc\xcc\xcc"
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP,
                                  eth_src_mac=spoof_eth)
        assert frame[6:12] == spoof_eth
        # ARP payload sender stays as src_mac
        assert frame[22:28] == self.SRC_MAC

    def test_ethertype_arp(self):
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP)
        assert frame[12:14] == b"\x08\x06"  # 0x0806 ARP

    def test_arp_header_fields(self):
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP)
        # ARP payload starts at byte 14
        hw_type, proto_type, hw_len, proto_len, opcode = struct.unpack(
            "!HHBBH", frame[14:22]
        )
        assert hw_type == 1            # Ethernet
        assert proto_type == 0x0800    # IPv4
        assert hw_len == 6
        assert proto_len == 4
        assert opcode == 2             # reply (default)

    def test_arp_opcode_request_override(self):
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP,
                                  opcode=1)
        _, _, _, _, opcode = struct.unpack("!HHBBH", frame[14:22])
        assert opcode == 1

    def test_arp_sender_protocol_address(self):
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP)
        assert frame[28:32] == socket.inet_aton(self.SRC_IP)

    def test_arp_target_protocol_address(self):
        frame = _build_arp_reply(self.SRC_MAC, self.SRC_IP,
                                  self.DST_MAC, self.DST_IP)
        assert frame[38:42] == socket.inet_aton(self.DST_IP)


# ── Gateway discovery ────────────────────────────────────────────────

class TestGatewayDiscovery:
    def test_windows_parses_ipconfig(self, monkeypatch):
        ipconfig_out = (
            "Windows IP Configuration\n"
            "\n"
            "Wireless LAN adapter Wi-Fi:\n"
            "   IPv4 Address. . . . . . . . . . . : 192.168.1.50\n"
            "   Default Gateway . . . . . . . . . : 192.168.1.1\n"
        )
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        monkeypatch.setattr(arp_spoof, "_SP_IPCONFIG", r"C:\Windows\System32\ipconfig.exe")
        monkeypatch.setattr(
            arp_spoof.safe_subprocess, "run",
            lambda *a, **kw: _StubResult(ipconfig_out),
        )
        assert get_default_gateway() == "192.168.1.1"

    def test_windows_skips_zero_gateway(self, monkeypatch):
        ipconfig_out = "   Default Gateway . . . . . . . . . : 0.0.0.0\n"
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        monkeypatch.setattr(arp_spoof, "_SP_IPCONFIG", r"C:\Windows\System32\ipconfig.exe")
        monkeypatch.setattr(arp_spoof, "_SP_ROUTE", "")  # no fallback
        monkeypatch.setattr(
            arp_spoof.safe_subprocess, "run",
            lambda *a, **kw: _StubResult(ipconfig_out),
        )
        assert get_default_gateway() is None

    def test_windows_handles_missing_ipconfig(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        monkeypatch.setattr(arp_spoof, "_SP_IPCONFIG", "")
        assert get_default_gateway() is None

    def test_linux_parses_ip_route(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", False)
        monkeypatch.setattr("shutil.which", lambda name: "/usr/sbin/ip")
        monkeypatch.setattr(
            arp_spoof.safe_subprocess, "run",
            lambda *a, **kw: _StubResult(
                "default via 10.0.0.1 dev wlan0 proto dhcp metric 600\n"
            ),
        )
        assert get_default_gateway() == "10.0.0.1"

    def test_linux_no_ip_binary(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", False)
        monkeypatch.setattr("shutil.which", lambda name: None)
        assert get_default_gateway() is None


# ── MAC-for-IP from ARP cache ────────────────────────────────────────

class TestMacForIp:
    def test_windows_parses_arp_a(self, monkeypatch):
        arp_out = (
            "Interface: 192.168.1.50 --- 0x9\n"
            "  Internet Address      Physical Address      Type\n"
            "  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic\n"
        )
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        monkeypatch.setattr(arp_spoof, "_SP_ARP", r"C:\Windows\System32\arp.exe")
        monkeypatch.setattr(arp_spoof, "_SP_PING", r"C:\Windows\System32\PING.EXE")
        # Ping no-op; ARP parse returns the MAC.
        monkeypatch.setattr(
            arp_spoof.safe_subprocess, "run",
            lambda argv, **kw: _StubResult(arp_out),
        )
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)
        mac = get_mac_for_ip("192.168.1.1")
        assert mac == b"\xaa\xbb\xcc\xdd\xee\xff"

    def test_windows_skips_broadcast_mac(self, monkeypatch):
        arp_out = (
            "  192.168.1.1           ff-ff-ff-ff-ff-ff     static\n"
        )
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        monkeypatch.setattr(arp_spoof, "_SP_ARP", r"C:\Windows\System32\arp.exe")
        monkeypatch.setattr(arp_spoof, "_SP_PING", r"C:\Windows\System32\PING.EXE")
        monkeypatch.setattr(
            arp_spoof.safe_subprocess, "run",
            lambda argv, **kw: _StubResult(arp_out),
        )
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)
        assert get_mac_for_ip("192.168.1.1") is None

    def test_linux_parses_proc_net_arp(self, monkeypatch, tmp_path):
        proc_arp = tmp_path / "arp"
        proc_arp.write_text(
            "IP address       HW type     Flags       HW address            "
            "Mask     Device\n"
            "192.168.1.1      0x1         0x2         aa:bb:cc:dd:ee:ff     "
            "*        wlan0\n"
        )
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", False)
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)

        real_open = open

        def fake_open(path, *a, **kw):
            if path == "/proc/net/arp":
                return real_open(str(proc_arp), *a, **kw)
            return real_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", fake_open)
        # Skip ping (no real network in the sandbox)
        monkeypatch.setattr(arp_spoof, "_ping_once", lambda ip: None)
        mac = get_mac_for_ip("192.168.1.1")
        assert mac == b"\xaa\xbb\xcc\xdd\xee\xff"

    def test_linux_skips_incomplete_entry(self, monkeypatch, tmp_path):
        proc_arp = tmp_path / "arp"
        proc_arp.write_text(
            "IP address       HW type     Flags       HW address            "
            "Mask     Device\n"
            "192.168.1.1      0x1         0x0         00:00:00:00:00:00     "
            "*        wlan0\n"
        )
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", False)
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)
        real_open = open

        def fake_open(path, *a, **kw):
            if path == "/proc/net/arp":
                return real_open(str(proc_arp), *a, **kw)
            return real_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", fake_open)
        monkeypatch.setattr(arp_spoof, "_ping_once", lambda ip: None)
        assert get_mac_for_ip("192.168.1.1") is None


# ── IP forwarding state ──────────────────────────────────────────────

class TestIpForwarding:
    def test_linux_reads_proc(self, monkeypatch, tmp_path):
        ip_fwd = tmp_path / "ip_forward"
        ip_fwd.write_text("1\n")
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", False)
        real_open = open

        def fake_open(path, *a, **kw):
            if path == "/proc/sys/net/ipv4/ip_forward":
                return real_open(str(ip_fwd), *a, **kw)
            return real_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", fake_open)
        assert arp_spoof._get_ip_forwarding_state() is True

        ip_fwd.write_text("0\n")
        assert arp_spoof._get_ip_forwarding_state() is False

    def test_linux_set_writes_proc(self, monkeypatch, tmp_path):
        ip_fwd = tmp_path / "ip_forward"
        ip_fwd.write_text("0\n")
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", False)
        real_open = open

        def fake_open(path, *a, **kw):
            if path == "/proc/sys/net/ipv4/ip_forward":
                return real_open(str(ip_fwd), *a, **kw)
            return real_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", fake_open)
        assert arp_spoof._set_ip_forwarding(True) is True
        assert ip_fwd.read_text() == "1"
        assert arp_spoof._set_ip_forwarding(False) is True
        assert ip_fwd.read_text() == "0"

    def test_windows_get_parses_netsh(self, monkeypatch):
        # _get_ip_forwarding_state returns on the FIRST line containing
        # "forwarding" — so the test output must put forwarding+enabled
        # on the same line.
        netsh_out = (
            "General Global Parameters\n"
            "----------------------------------------------------------------\n"
            "IP Forwarding:                                Enabled\n"
        )
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        monkeypatch.setattr(arp_spoof, "_SP_NETSH", r"C:\Windows\System32\netsh.exe")
        monkeypatch.setattr(
            arp_spoof.safe_subprocess, "run",
            lambda *a, **kw: _StubResult(netsh_out),
        )
        assert arp_spoof._get_ip_forwarding_state() is True

    def test_windows_set_invokes_netsh(self, monkeypatch):
        seen = {}

        def _capture(argv, **kw):
            seen["argv"] = list(argv)
            return _StubResult("")

        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        monkeypatch.setattr(arp_spoof, "_SP_NETSH", r"C:\Windows\System32\netsh.exe")
        monkeypatch.setattr(arp_spoof.safe_subprocess, "run", _capture)
        assert arp_spoof._set_ip_forwarding(True) is True
        # Expect: ['netsh', 'interface', 'ipv4', 'set', 'global',
        #          'forwarding=enabled']
        assert "forwarding=enabled" in seen["argv"]


# ── detect_wifi_same_network ────────────────────────────────────────

class TestDetectWifiSameNetwork:
    def test_delegates_to_target_profile(self, monkeypatch):
        called = {}

        def _fake(ip):
            called["ip"] = ip
            return True

        fake_mod = types.ModuleType("app.firewall.target_profile")
        fake_mod._is_wifi_same_network = _fake
        monkeypatch.setitem(sys.modules,
                            "app.firewall.target_profile", fake_mod)
        assert detect_wifi_same_network("192.168.1.10") is True
        assert called["ip"] == "192.168.1.10"

    def test_fallback_rejects_loopback(self, monkeypatch):
        # Force the ImportError fallback path.
        monkeypatch.setitem(sys.modules,
                            "app.firewall.target_profile", None)
        assert detect_wifi_same_network("127.0.0.1") is False

    def test_fallback_rejects_invalid_ip(self, monkeypatch):
        monkeypatch.setitem(sys.modules,
                            "app.firewall.target_profile", None)
        assert detect_wifi_same_network("not-an-ip") is False


# ── ArpSpoofer lifecycle ─────────────────────────────────────────────

class _FakeSender:
    """Stand-in for NpcapSender that records frames sent."""

    def __init__(self) -> None:
        self.frames: list = []
        self.loaded = False
        self.opened = False
        self.closed = False

    def load(self) -> bool:
        self.loaded = True
        return True

    def open(self, target_ip: str) -> bool:
        self.opened = True
        return True

    def send(self, frame: bytes) -> bool:
        self.frames.append(bytes(frame))
        return True

    def close(self) -> None:
        self.closed = True


class TestArpSpooferConstruction:
    def test_uses_explicit_gateway(self):
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.254")
        assert spoofer.gateway_ip == "192.168.1.254"
        assert spoofer.target_ip == "192.168.1.10"
        assert spoofer.is_active is False
        assert spoofer.packets_sent == 0

    def test_falls_back_to_discovered_gateway(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "get_default_gateway",
                             lambda: "10.0.0.1")
        spoofer = ArpSpoofer(target_ip="10.0.0.50")
        assert spoofer.gateway_ip == "10.0.0.1"


class TestArpSpooferStart:
    """start() resolves MACs, enables forwarding, opens sender, and
    spawns the poison loop. Heavy mocking — we don't want to hit real
    sockets, real netsh, real Npcap on a sandboxed Linux runner.
    """

    @pytest.fixture
    def patched(self, monkeypatch):
        """Patch everything the spoofer touches and yield the spoofer +
        captured sender for assertions."""
        target_mac = b"\x11\x22\x33\x44\x55\x66"
        gateway_mac = b"\xaa\xbb\xcc\xdd\xee\xff"
        local_mac = b"\xde\xad\xbe\xef\xca\xfe"

        # Stop the poison loop from looping forever during the test.
        monkeypatch.setattr(arp_spoof, "_SPOOF_INTERVAL_SEC", 0.01)
        monkeypatch.setattr(arp_spoof, "_WARMUP_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof, "_RESTORE_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)

        monkeypatch.setattr(arp_spoof, "get_local_mac",
                             lambda target_ip=None: local_mac)

        def _mac_lookup(ip):
            return {
                "192.168.1.10": target_mac,
                "192.168.1.1": gateway_mac,
            }.get(ip)

        monkeypatch.setattr(arp_spoof, "get_mac_for_ip", _mac_lookup)
        monkeypatch.setattr(arp_spoof, "_get_ip_forwarding_state",
                             lambda: False)
        forwarding_calls: list = []
        monkeypatch.setattr(arp_spoof, "_set_ip_forwarding",
                             lambda enable: forwarding_calls.append(enable)
                                              or True)

        fake_sender = _FakeSender()
        monkeypatch.setattr(arp_spoof, "NpcapSender",
                             lambda: fake_sender)
        # Pretend we're on Windows so the spoofer uses the NpcapSender
        # branch instead of opening an AF_PACKET socket.
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)

        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        return spoofer, fake_sender, forwarding_calls

    def test_start_resolves_macs(self, patched):
        spoofer, sender, _ = patched
        assert spoofer.start() is True
        try:
            assert spoofer.is_active is True
            assert spoofer._local_mac == b"\xde\xad\xbe\xef\xca\xfe"
            assert spoofer._target_mac == b"\x11\x22\x33\x44\x55\x66"
            assert spoofer._gateway_mac == b"\xaa\xbb\xcc\xdd\xee\xff"
            assert sender.loaded and sender.opened
        finally:
            spoofer.stop()

    def test_start_enables_forwarding_when_off(self, patched):
        spoofer, _, forwarding_calls = patched
        assert spoofer.start() is True
        try:
            # The first call comes from start(); enable=True.
            assert True in forwarding_calls
        finally:
            spoofer.stop()

    def test_start_aborts_without_gateway(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "get_default_gateway",
                             lambda: None)
        spoofer = ArpSpoofer(target_ip="192.168.1.10")
        # gateway_ip is None now → start() bails.
        assert spoofer.start() is False
        assert spoofer.is_active is False

    def test_start_aborts_without_local_mac(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "get_local_mac",
                             lambda target_ip=None: None)
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        assert spoofer.start() is False
        assert spoofer.is_active is False

    def test_start_aborts_when_target_mac_unresolved(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "get_local_mac",
                             lambda target_ip=None: b"\x01" * 6)
        monkeypatch.setattr(arp_spoof, "get_mac_for_ip",
                             lambda ip: None)
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        assert spoofer.start() is False

    def test_idempotent_start(self, patched):
        spoofer, _, _ = patched
        try:
            assert spoofer.start() is True
            # Calling start() again is a no-op once running.
            assert spoofer.start() is True
        finally:
            spoofer.stop()


class TestArpSpooferStop:
    @pytest.fixture
    def started_spoofer(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "_SPOOF_INTERVAL_SEC", 0.01)
        monkeypatch.setattr(arp_spoof, "_WARMUP_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof, "_RESTORE_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)
        monkeypatch.setattr(arp_spoof, "get_local_mac",
                             lambda target_ip=None: b"\x01" * 6)
        monkeypatch.setattr(arp_spoof, "get_mac_for_ip",
                             lambda ip: b"\x02" * 6)
        monkeypatch.setattr(arp_spoof, "_get_ip_forwarding_state",
                             lambda: False)
        forwarding_calls: list = []
        monkeypatch.setattr(arp_spoof, "_set_ip_forwarding",
                             lambda enable: forwarding_calls.append(enable)
                                              or True)
        sender = _FakeSender()
        monkeypatch.setattr(arp_spoof, "NpcapSender", lambda: sender)
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        assert spoofer.start()
        return spoofer, sender, forwarding_calls

    def test_stop_disables_running_flag(self, started_spoofer):
        spoofer, _, _ = started_spoofer
        spoofer.stop()
        assert spoofer.is_active is False

    def test_stop_closes_sender(self, started_spoofer):
        spoofer, sender, _ = started_spoofer
        spoofer.stop()
        assert sender.closed is True

    def test_stop_restores_forwarding_when_was_off(self, started_spoofer):
        spoofer, _, forwarding_calls = started_spoofer
        spoofer.stop()
        # start() called set(True); stop() should call set(False)
        assert forwarding_calls[-1] is False

    def test_stop_sends_restore_frames(self, started_spoofer):
        spoofer, sender, _ = started_spoofer
        prev_count = len(sender.frames)
        spoofer.stop()
        # Each restore round sends 2 frames; default _RESTORE_ROUNDS=5
        # ⇒ at least 2 additional frames after stop()
        assert len(sender.frames) > prev_count

    def test_stop_is_idempotent(self, started_spoofer):
        spoofer, _, _ = started_spoofer
        spoofer.stop()
        # Second stop() must be a no-op (no exception)
        spoofer.stop()
        assert spoofer.is_active is False


class TestArpSpooferPacketCounter:
    """packets_sent is incremented from the poison thread; verify the
    lock-protected accessor reads safely after start()."""

    def test_counter_increments_on_warmup(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "_SPOOF_INTERVAL_SEC", 1.0)
        monkeypatch.setattr(arp_spoof, "_WARMUP_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof, "_WARMUP_ROUNDS", 3)
        monkeypatch.setattr(arp_spoof, "_RESTORE_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof, "_RESTORE_ROUNDS", 0)
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)
        monkeypatch.setattr(arp_spoof, "get_local_mac",
                             lambda target_ip=None: b"\x01" * 6)
        monkeypatch.setattr(arp_spoof, "get_mac_for_ip",
                             lambda ip: b"\x02" * 6)
        monkeypatch.setattr(arp_spoof, "_get_ip_forwarding_state",
                             lambda: True)  # already on; no restore call
        monkeypatch.setattr(arp_spoof, "_set_ip_forwarding",
                             lambda enable: True)
        sender = _FakeSender()
        monkeypatch.setattr(arp_spoof, "NpcapSender", lambda: sender)
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)

        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        assert spoofer.start()
        try:
            # 3 warmup rounds × 3 frames each (target + 2 gateway variants)
            assert spoofer.packets_sent >= 9
        finally:
            spoofer.stop()


# ── ArpSpoofer._send_frame edge cases ──────────────────────────────

class TestSendFrame:
    def test_send_frame_no_sender_returns_false(self):
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        # Neither sender nor linux_sock attached
        assert spoofer._send_frame(b"\x00" * 42) is False
        assert spoofer.packets_sent == 0

    def test_send_frame_records_success(self):
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        sender = _FakeSender()
        spoofer._sender = sender
        assert spoofer._send_frame(b"\xab" * 42) is True
        assert spoofer.packets_sent == 1
        assert sender.frames == [b"\xab" * 42]


# ── H1: ArpSpoofer.start() cleanup on exception ─────────────────────

class TestStartCleanupOnException:
    """If any sub-step of start() raises (ctypes / Npcap / socket layer),
    _cleanup_partial() must release the sender, the linux socket, and
    restore IP forwarding before propagating the failure.
    """

    @pytest.fixture
    def env(self, monkeypatch):
        monkeypatch.setattr(arp_spoof, "_SPOOF_INTERVAL_SEC", 0.01)
        monkeypatch.setattr(arp_spoof, "_WARMUP_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof, "_RESTORE_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)
        monkeypatch.setattr(arp_spoof, "get_local_mac",
                             lambda target_ip=None: b"\x01" * 6)
        monkeypatch.setattr(arp_spoof, "get_mac_for_ip",
                             lambda ip: b"\x02" * 6)
        monkeypatch.setattr(arp_spoof, "_get_ip_forwarding_state",
                             lambda: False)
        forwarding_calls: list = []
        monkeypatch.setattr(
            arp_spoof, "_set_ip_forwarding",
            lambda enable: forwarding_calls.append(enable) or True,
        )
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        return forwarding_calls

    def test_warmup_raise_releases_sender_and_forwarding(self, env, monkeypatch):
        """Simulate _poison_once raising during warmup. start() must
        return False, close the sender, and restore forwarding."""
        forwarding_calls = env
        sender = _FakeSender()
        monkeypatch.setattr(arp_spoof, "NpcapSender", lambda: sender)

        def _boom(self):
            raise RuntimeError("simulated ctypes failure")

        monkeypatch.setattr(ArpSpoofer, "_poison_once", _boom)

        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        assert spoofer.start() is False
        assert spoofer.is_active is False
        # Sender was closed
        assert sender.closed is True
        assert spoofer._sender is None
        # Forwarding was restored (turned off because it was off before)
        assert False in forwarding_calls

    def test_sender_load_raise_restores_forwarding(self, env, monkeypatch):
        forwarding_calls = env
        class _BoomSender:
            def load(self):
                raise OSError("dll load failure")
            def open(self, target_ip):
                return True
            def send(self, frame):
                return True
            def close(self):
                pass
        monkeypatch.setattr(arp_spoof, "NpcapSender", _BoomSender)
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        assert spoofer.start() is False
        assert False in forwarding_calls

    def test_sender_open_returns_false_releases_forwarding(self, env,
                                                            monkeypatch):
        """Existing path — open() returns False (not raise). Still must
        cleanup. Was already correct pre-H1 but pinned here so a future
        refactor can't regress it."""
        forwarding_calls = env
        sender = _FakeSender()
        sender.open = lambda target_ip: False  # type: ignore[assignment]
        monkeypatch.setattr(arp_spoof, "NpcapSender", lambda: sender)
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        assert spoofer.start() is False
        # Forwarding restored
        assert False in forwarding_calls
        # _running flag reset
        assert spoofer._running is False

    def test_cleanup_partial_is_idempotent(self):
        """_cleanup_partial() called twice (e.g. after a partial failure
        followed by stop()) must not raise."""
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        spoofer._cleanup_partial()
        spoofer._cleanup_partial()
        assert spoofer._running is False


# ── H2: Linux bind failure path ──────────────────────────────────────

class TestLinuxBindFailure:
    """The pre-H2 path opened an AF_PACKET socket, attempted bind, logged
    any failure, and silently continued — meaning the spoofer reported
    success while sending no actual frames. H2 makes that path honest:
    bind failure → start() returns False, cleanup runs.
    """

    def test_bind_returns_true_on_success(self, monkeypatch):
        """Sanity: when route probe + iface lookup + bind all succeed,
        _bind_linux_socket returns True without touching the socket
        beyond `bind()`."""
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        # Stub linux_sock so .bind() doesn't actually hit a kernel.
        bound: dict = {}

        class _S:
            def bind(self, args):
                bound["args"] = args

        spoofer._linux_sock = _S()

        # Route probe stub
        class _RouteSocket:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def connect(self, addr):
                pass
            def getsockname(self):
                return ("10.0.0.5", 0)

        monkeypatch.setattr(arp_spoof.socket, "socket",
                             lambda fam, kind: _RouteSocket())

        # ip route stub
        import subprocess as sp_real

        def _check_output(argv, **kw):
            return "1: lo inet 127.0.0.1\n2: wlan0 inet 10.0.0.5/24\n"

        monkeypatch.setattr(sp_real, "check_output", _check_output)
        assert spoofer._bind_linux_socket() is True
        assert bound["args"][0] == "wlan0"

    def test_bind_returns_false_when_iface_not_found(self, monkeypatch):
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")

        class _S:
            def bind(self, args):
                raise AssertionError("bind should not be called")

        spoofer._linux_sock = _S()

        class _RouteSocket:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def connect(self, addr):
                pass
            def getsockname(self):
                return ("10.99.99.99", 0)  # not in ip-route output

        monkeypatch.setattr(arp_spoof.socket, "socket",
                             lambda fam, kind: _RouteSocket())
        import subprocess as sp_real
        monkeypatch.setattr(
            sp_real, "check_output",
            lambda argv, **kw: "1: lo inet 127.0.0.1\n2: wlan0 inet 10.0.0.5/24\n",
        )
        assert spoofer._bind_linux_socket() is False

    def test_bind_returns_false_when_ip_binary_missing(self, monkeypatch):
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        spoofer._linux_sock = MagicMock()

        class _RouteSocket:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def connect(self, addr):
                pass
            def getsockname(self):
                return ("10.0.0.5", 0)

        monkeypatch.setattr(arp_spoof.socket, "socket",
                             lambda fam, kind: _RouteSocket())
        import subprocess as sp_real

        def _raise(*a, **kw):
            raise FileNotFoundError("ip")

        monkeypatch.setattr(sp_real, "check_output", _raise)
        assert spoofer._bind_linux_socket() is False

    def test_bind_returns_false_when_route_probe_fails(self, monkeypatch):
        spoofer = ArpSpoofer(target_ip="192.168.1.10",
                              gateway_ip="192.168.1.1")
        spoofer._linux_sock = MagicMock()

        class _RouteSocket:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def connect(self, addr):
                raise OSError("network unreachable")
            def getsockname(self):
                return ("0.0.0.0", 0)

        monkeypatch.setattr(arp_spoof.socket, "socket",
                             lambda fam, kind: _RouteSocket())
        assert spoofer._bind_linux_socket() is False


# ── H3 / H4: IP and MAC masking in logs ────────────────────────────

class TestLogMasking:
    """Critical opsec: the disruptor masks every IP it logs, but
    arp_spoof and wifi_probe historically logged raw IPs and full MAC
    addresses. These tests pin the masking so future regressions are
    caught."""

    def test_start_logs_masked_target_and_gateway(self, monkeypatch, caplog):
        # Patch everything so start() succeeds enough to hit the log line
        monkeypatch.setattr(arp_spoof, "_WARMUP_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof, "_RESTORE_INTERVAL_SEC", 0.0)
        monkeypatch.setattr(arp_spoof.time, "sleep", lambda s: None)
        monkeypatch.setattr(arp_spoof, "get_local_mac",
                             lambda target_ip=None: b"\xaa\xbb\xcc\xdd\xee\xff")
        monkeypatch.setattr(arp_spoof, "get_mac_for_ip",
                             lambda ip: b"\x11\x22\x33\x44\x55\x66")
        monkeypatch.setattr(arp_spoof, "_get_ip_forwarding_state",
                             lambda: True)
        monkeypatch.setattr(arp_spoof, "_set_ip_forwarding",
                             lambda enable: True)
        monkeypatch.setattr(arp_spoof, "NpcapSender", lambda: _FakeSender())
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)

        import logging
        with caplog.at_level(logging.INFO, logger="DupeZ"):
            spoofer = ArpSpoofer(target_ip="192.168.1.42",
                                  gateway_ip="192.168.1.1")
            assert spoofer.start() is True
            try:
                joined = "\n".join(r.getMessage() for r in caplog.records)
                # Last octet must be masked
                assert "192.168.1.42" not in joined
                assert "192.168.1.x" in joined
                # MAC OUI preserved, device portion masked
                assert "aa:bb:cc:**:**:**" in joined
                assert "11:22:33:**:**:**" in joined
                # Raw MACs must NOT appear
                assert "aa:bb:cc:dd:ee:ff" not in joined
            finally:
                spoofer.stop()

    def test_target_mac_failure_logs_masked_ip(self, monkeypatch, caplog):
        monkeypatch.setattr(arp_spoof, "get_local_mac",
                             lambda target_ip=None: b"\x01" * 6)
        # Target MAC resolution fails
        monkeypatch.setattr(arp_spoof, "get_mac_for_ip", lambda ip: None)
        monkeypatch.setattr(arp_spoof, "_IS_WINDOWS", True)
        import logging
        with caplog.at_level(logging.ERROR, logger="DupeZ"):
            spoofer = ArpSpoofer(target_ip="10.20.30.40",
                                  gateway_ip="10.20.30.1")
            assert spoofer.start() is False
            joined = "\n".join(r.getMessage() for r in caplog.records)
            assert "10.20.30.40" not in joined
            assert "10.20.30.x" in joined


# ── mask_mac helper ─────────────────────────────────────────────────

class TestMaskMacHelper:
    def test_colon_separated(self):
        from app.utils.helpers import mask_mac
        assert mask_mac("aa:bb:cc:dd:ee:ff") == "aa:bb:cc:**:**:**"

    def test_dash_separated(self):
        from app.utils.helpers import mask_mac
        assert mask_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:**:**:**"

    def test_bytes_input(self):
        from app.utils.helpers import mask_mac
        assert mask_mac(b"\xde\xad\xbe\xef\xca\xfe") == "de:ad:be:**:**:**"

    def test_raw_hex_input(self):
        from app.utils.helpers import mask_mac
        assert mask_mac("aabbccddeeff") == "aa:bb:cc:**:**:**"

    def test_none_input(self):
        from app.utils.helpers import mask_mac
        assert mask_mac(None) == "??:??:??:**:**:**"

    def test_garbage_input(self):
        from app.utils.helpers import mask_mac
        assert mask_mac("not a mac") == "??:??:??:**:**:**"
        assert mask_mac("aa:bb") == "??:??:??:**:**:**"
        assert mask_mac(b"\x00\x01") == "??:??:??:**:**:**"

    def test_integer_input_does_not_crash(self):
        from app.utils.helpers import mask_mac
        assert mask_mac(12345) == "??:??:??:**:**:**"
