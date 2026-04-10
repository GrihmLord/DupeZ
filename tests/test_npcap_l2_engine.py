"""
Phase 1 tests for NpcapL2Engine.

These tests do NOT require Npcap to be installed or admin privileges —
they exercise the import surface, dataclasses, and availability
reporting. Integration tests against a real LAN are manual-only
(see ``_smoke_test`` in ``app/firewall/npcap_l2_engine.py``).
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

from app.firewall import npcap_l2_engine as eng_mod
from app.firewall.npcap_l2_engine import (
    LanDevice,
    NpcapL2Engine,
    NpcapUnavailableError,
    PoisonSession,
)


# ── Import surface ──────────────────────────────────────────────────


def test_module_exports_expected_symbols():
    assert hasattr(eng_mod, "NpcapL2Engine")
    assert hasattr(eng_mod, "LanDevice")
    assert hasattr(eng_mod, "PoisonSession")
    assert hasattr(eng_mod, "NpcapUnavailableError")


def test_exceptions_inherit_correctly():
    assert issubclass(NpcapUnavailableError, RuntimeError)


# ── Dataclasses ─────────────────────────────────────────────────────


def test_lan_device_defaults_and_str():
    d = LanDevice(ip="192.168.1.10", mac="aa:bb:cc:dd:ee:ff")
    assert d.ip == "192.168.1.10"
    assert d.mac == "aa:bb:cc:dd:ee:ff"
    assert d.vendor == ""
    assert d.first_seen <= time.time() + 0.1
    assert d.last_seen <= time.time() + 0.1
    s = str(d)
    assert "192.168.1.10" in s
    assert "aa:bb:cc:dd:ee:ff" in s


def test_lan_device_with_vendor_in_str():
    d = LanDevice(ip="10.0.0.5", mac="11:22:33:44:55:66", vendor="TP-Link")
    assert "TP-Link" in str(d)


def test_poison_session_defaults():
    s = PoisonSession(
        target_ip="192.168.1.42",
        target_mac="de:ad:be:ef:00:01",
        gateway_ip="192.168.1.1",
        gateway_mac="de:ad:be:ef:00:02",
        interval=1.0,
        iface="Ethernet",
    )
    assert isinstance(s.stop_event, threading.Event)
    assert s.stop_event.is_set() is False
    assert s.thread is None
    assert s.packets_sent == 0
    assert s.started_at <= time.time() + 0.1


# ── Availability behaviour when Scapy is missing ────────────────────


def test_engine_reports_unavailable_when_scapy_import_failed(monkeypatch):
    """Simulate a machine without Npcap/Scapy."""
    monkeypatch.setattr(
        eng_mod, "_SCAPY_IMPORT_ERROR", ImportError("no npcap"),
    )
    e = NpcapL2Engine()
    assert e.available is False
    reason = e.unavailable_reason
    assert "Scapy" in reason or "Npcap" in reason
    assert "npcap.com" in reason  # install link is surfaced


def test_engine_require_scapy_raises_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        eng_mod, "_SCAPY_IMPORT_ERROR", ImportError("no npcap"),
    )
    e = NpcapL2Engine()
    with pytest.raises(NpcapUnavailableError):
        e._require_scapy()


# ── Session bookkeeping (no network I/O) ────────────────────────────


def test_is_poisoning_and_active_sessions_start_empty():
    e = NpcapL2Engine()
    assert e.is_poisoning("192.168.1.42") is False
    assert e.active_sessions == []


def test_devices_property_starts_empty():
    e = NpcapL2Engine()
    assert e.devices == []


def test_restore_nonexistent_target_returns_false(monkeypatch):
    """restore() on an unknown target must be idempotent."""
    monkeypatch.setattr(
        eng_mod, "_SCAPY_IMPORT_ERROR", None,  # pretend scapy imported OK
    )
    e = NpcapL2Engine()
    assert e.restore("10.10.10.10") is False


def test_shutdown_with_no_sessions_is_noop(monkeypatch):
    monkeypatch.setattr(eng_mod, "_SCAPY_IMPORT_ERROR", None)
    e = NpcapL2Engine()
    e.shutdown()  # must not raise


# ── Hot-reload of interval on re-poison ─────────────────────────────


def test_poison_reload_updates_interval_without_new_thread(monkeypatch):
    """Second poison() call on same target hot-reloads interval."""
    monkeypatch.setattr(eng_mod, "_SCAPY_IMPORT_ERROR", None)

    e = NpcapL2Engine()
    # Pre-seed a fake session so poison() takes the hot-reload branch.
    fake_session = PoisonSession(
        target_ip="192.168.1.42",
        target_mac="aa:aa:aa:aa:aa:aa",
        gateway_ip="192.168.1.1",
        gateway_mac="bb:bb:bb:bb:bb:bb",
        interval=1.0,
        iface="Ethernet",
    )
    e._sessions["192.168.1.42"] = fake_session
    e._iface = "Ethernet"
    e._iface_ip = "192.168.1.50"
    e._iface_mac = "cc:cc:cc:cc:cc:cc"
    e._gateway_ip = "192.168.1.1"
    e._gateway_mac = "bb:bb:bb:bb:bb:bb"

    # Patch _arp_lookup so poison() doesn't touch the network.
    with mock.patch.object(e, "_arp_lookup",
                           return_value="aa:aa:aa:aa:aa:aa"):
        returned = e.poison("192.168.1.42", interval=0.25)

    assert returned is fake_session
    assert fake_session.interval == 0.25
    # No new thread should have been spawned.
    assert fake_session.thread is None


# ── Corrective ARP burst count constant guardrail ───────────────────


def test_restore_burst_count_is_positive_integer():
    assert isinstance(NpcapL2Engine.RESTORE_BURST_COUNT, int)
    assert NpcapL2Engine.RESTORE_BURST_COUNT >= 1


def test_default_poison_interval_is_reasonable():
    assert 0.1 <= NpcapL2Engine.DEFAULT_POISON_INTERVAL <= 5.0
