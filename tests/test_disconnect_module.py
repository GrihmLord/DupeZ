"""State-machine tests for app.firewall.modules.disconnect.DisconnectModule.

These pin down the invariants that the ML data pipeline depends on:

    * ``arm_delay=0``         → initial state is CUTTING
    * ``arm_delay>0``         → initial state is ARMED, transitions to
                                CUTTING after the delay elapses
    * ``duration=0``          → stays in CUTTING forever (legacy behavior)
    * ``duration>0``          → auto-transitions to DONE after duration
    * ``attach_event_sink()`` → replays cut_start if already CUTTING
    * ``force_cut_end()``     → closes an open cut from outside the module
    * default config          → every packet is dropped (100% chance)
    * ``disconnect_chance=0`` → every packet passes through

Run with::

    python -m pytest tests/test_disconnect_module.py -v
"""

from __future__ import annotations

import time
from typing import List, Tuple

import pytest

from app.firewall.modules.disconnect import (
    DisconnectModule,
    STATE_ARMED,
    STATE_CUTTING,
    STATE_QUIET,
    STATE_DONE,
)


class _FakeAddr:
    Outbound = True


class _InboundAddr:
    Outbound = False


def _noop_send(_data, _addr):
    pass


def _drive(mod: DisconnectModule, n: int = 50) -> Tuple[int, int]:
    """Feed ``n`` packets and return (dropped, passed)."""
    dropped = 0
    for _ in range(n):
        if mod.process(bytearray(64), _FakeAddr(), _noop_send):
            dropped += 1
    return dropped, n - dropped


# ── initial state ─────────────────────────────────────────────────────

def test_default_starts_in_cutting():
    m = DisconnectModule({})
    assert m.state == STATE_CUTTING


def test_arm_delay_starts_in_armed():
    m = DisconnectModule({"disconnect_arm_delay_ms": 50})
    assert m.state == STATE_ARMED


# ── drop behavior ─────────────────────────────────────────────────────

def test_default_drops_every_packet():
    m = DisconnectModule({})
    dropped, passed = _drive(m, 100)
    assert dropped == 100
    assert passed == 0


def test_chance_zero_passes_everything():
    m = DisconnectModule({"disconnect_chance": 0})
    dropped, passed = _drive(m, 100)
    assert dropped == 0
    assert passed == 100


def test_chance_clamped_to_valid_range():
    # Non-numeric → falls back to default 100
    m = DisconnectModule({"disconnect_chance": "not-a-number"})
    dropped, _ = _drive(m, 10)
    assert dropped == 10
    # Over 100 → clamped to 100
    m2 = DisconnectModule({"disconnect_chance": 250})
    assert m2._chance == 100  # type: ignore[attr-defined]
    # Negative → clamped to 0
    m3 = DisconnectModule({"disconnect_chance": -5})
    assert m3._chance == 0  # type: ignore[attr-defined]


# ── transitions ───────────────────────────────────────────────────────

def test_armed_to_cutting_transition_fires_cut_start():
    events: List[str] = []
    m = DisconnectModule({"disconnect_arm_delay_ms": 30})
    m.attach_event_sink(lambda name, **_: events.append(name))
    # Before delay elapses — still ARMED, packets pass
    m.process(bytearray(10), _FakeAddr(), _noop_send)
    assert m.state == STATE_ARMED
    time.sleep(0.05)
    m.process(bytearray(10), _FakeAddr(), _noop_send)
    assert m.state == STATE_CUTTING
    assert events.count("cut_start") == 1


def test_cutting_to_done_transition_fires_cut_end():
    events: List[str] = []
    m = DisconnectModule({"disconnect_duration_ms": 40})
    m.attach_event_sink(lambda name, **_: events.append(name))
    # Immediate replay from sink attach
    assert events[:1] == ["cut_start"]
    time.sleep(0.06)
    m.process(bytearray(10), _FakeAddr(), _noop_send)
    assert m.state == STATE_DONE
    assert "cut_end" in events


def test_duration_zero_stays_cutting_forever():
    m = DisconnectModule({"disconnect_duration_ms": 0})
    time.sleep(0.05)
    _drive(m, 10)
    assert m.state == STATE_CUTTING
    assert m.packets_dropped == 10


# ── sink replay + force_cut_end ───────────────────────────────────────

def test_attach_sink_replays_cut_start_when_already_cutting():
    events: List[str] = []
    m = DisconnectModule({})           # defaults → starts CUTTING
    m.attach_event_sink(lambda name, **_: events.append(name))
    assert events == ["cut_start"]


def test_attach_sink_while_armed_does_not_replay():
    events: List[str] = []
    m = DisconnectModule({"disconnect_arm_delay_ms": 50})
    m.attach_event_sink(lambda name, **_: events.append(name))
    assert events == []


def test_force_cut_end_closes_open_cut():
    events: List[str] = []
    m = DisconnectModule({"disconnect_duration_ms": 0})
    m.attach_event_sink(lambda name, **_: events.append(name))
    assert m.state == STATE_CUTTING
    m.force_cut_end()
    assert m.state == STATE_DONE
    assert events == ["cut_start", "cut_end"]


def test_force_cut_end_on_done_is_idempotent():
    events: List[str] = []
    m = DisconnectModule({})
    m.attach_event_sink(lambda name, **_: events.append(name))
    m.force_cut_end()
    m.force_cut_end()  # should not re-emit cut_end
    assert events.count("cut_end") == 1


def test_reset_restarts_cycle():
    m = DisconnectModule({})
    _drive(m, 20)
    assert m.packets_dropped == 20
    m.reset()
    assert m.packets_dropped == 0
    assert m.state == STATE_CUTTING


# ── sink resilience ──────────────────────────────────────────────────

def test_sink_exception_does_not_break_hot_path():
    def bad_sink(*_a, **_k):
        raise RuntimeError("telemetry exploded")
    m = DisconnectModule({})
    m.attach_event_sink(bad_sink)
    # Must not raise
    dropped, _ = _drive(m, 10)
    assert dropped == 10


# ── stats snapshot ──────────────────────────────────────────────────

def test_stats_snapshot_reports_expected_keys():
    m = DisconnectModule({"disconnect_chance": 50, "disconnect_duration_ms": 1000})
    snap = m.stats()
    assert set(snap) >= {
        "state", "dropped", "passed",
        "cut_started_at", "cut_ended_at",
        "chance", "duration_s", "arm_delay_s",
    }
    assert snap["chance"] == 50
    assert snap["duration_s"] == pytest.approx(1.0)


# ── post-cut quiet window ────────────────────────────────────────────

def test_quiet_window_transitions_cutting_to_quiet_to_done():
    m = DisconnectModule({
        "disconnect_duration_ms": 30,
        "disconnect_quiet_after_ms": 30,
    })
    assert m.state == STATE_CUTTING
    time.sleep(0.05)  # exceed duration
    # trigger transition via a packet
    m.process(bytearray(64), _FakeAddr(), _noop_send)
    assert m.state == STATE_QUIET
    time.sleep(0.05)  # exceed quiet
    m.process(bytearray(64), _FakeAddr(), _noop_send)
    assert m.state == STATE_DONE


def test_quiet_window_drops_inbound_passes_outbound():
    m = DisconnectModule({
        "disconnect_duration_ms": 30,
        "disconnect_quiet_after_ms": 200,
    })
    time.sleep(0.05)  # force CUTTING → QUIET
    m.process(bytearray(64), _FakeAddr(), _noop_send)
    assert m.state == STATE_QUIET
    # Outbound packets pass during QUIET
    out_dropped = 0
    in_dropped = 0
    for _ in range(40):
        if m.process(bytearray(64), _FakeAddr(), _noop_send):
            out_dropped += 1
        if m.process(bytearray(64), _InboundAddr(), _noop_send):
            in_dropped += 1
    assert out_dropped == 0, "outbound must pass during quiet window"
    assert in_dropped > 30, "inbound must be dropped during quiet window"


def test_quiet_zero_skips_state():
    m = DisconnectModule({
        "disconnect_duration_ms": 30,
        "disconnect_quiet_after_ms": 0,
    })
    time.sleep(0.05)
    m.process(bytearray(64), _FakeAddr(), _noop_send)
    assert m.state == STATE_DONE
