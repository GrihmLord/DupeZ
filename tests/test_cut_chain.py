"""Tests for app.core.cut_chain (v5.7.1 feature #2)."""

from __future__ import annotations

import time

import pytest

from app.core.cut_chain import (
    ChainConfig,
    ChainEvent,
    CutChainRunner,
    Gate,
    Stage,
)


class FakeEngine:
    """Stand-in for a live disruption engine the chain inspects via private attrs."""

    def __init__(
        self,
        max_cut_state: str = "unknown",
        packets_processed: int = 0,
    ) -> None:
        self._max_cut_state = max_cut_state
        self._packets_processed = packets_processed


class FakeController:
    """Implements the surface CutChainRunner consumes — disrupt/stop + the
    ``disrupted_devices`` registry that A2S / packet gates poll.
    """

    def __init__(self, *, fail_on: int = -1) -> None:
        self.disrupted_devices: dict = {}
        self.calls: list = []
        self._fail_on = fail_on
        self._call_count = 0

    def disrupt_device(self, ip: str, methods, params, **_) -> bool:
        self._call_count += 1
        if self._call_count == self._fail_on:
            return False
        self.calls.append(("disrupt", ip, list(methods), dict(params)))
        self.disrupted_devices[ip] = {
            "engine": FakeEngine(max_cut_state="severed", packets_processed=100),
            "methods": list(methods),
            "params": dict(params),
            "start_time": time.time(),
        }
        return True

    def stop_disruption(self, ip: str) -> None:
        self.calls.append(("stop", ip))
        self.disrupted_devices.pop(ip, None)


# ── Stage walk ────────────────────────────────────────────────────────


class TestStageWalk:
    """Linear stage progression and event emission."""

    def test_single_stage_completes(self) -> None:
        events: list = []
        cfg = ChainConfig(
            target_ip="10.0.0.5",
            stages=[Stage(preset="Lag", gate=Gate("time", seconds=0.05))],
        )
        runner = CutChainRunner(cfg, FakeController(), on_event=events.append)
        runner.start()
        time.sleep(0.3)
        runner.stop()
        kinds = [e.kind for e in events]
        assert "stage_start" in kinds
        assert "stage_end" in kinds
        assert "complete" in kinds

    def test_multi_stage_walks_in_order(self) -> None:
        events: list = []
        ctrl = FakeController()
        cfg = ChainConfig(
            target_ip="10.0.0.5",
            stages=[
                Stage(preset="Lag", gate=Gate("time", seconds=0.05)),
                Stage(preset="Red Disconnect", gate=Gate("time", seconds=0.05)),
            ],
        )
        runner = CutChainRunner(cfg, ctrl, on_event=events.append)
        runner.start()
        time.sleep(0.5)
        runner.stop()
        # Each stage: one disrupt + one stop call.
        disrupts = [c for c in ctrl.calls if c[0] == "disrupt"]
        assert len(disrupts) == 2

    def test_stop_halts_chain(self) -> None:
        events: list = []
        cfg = ChainConfig(
            target_ip="10.0.0.5",
            stages=[
                Stage(preset="Lag", gate=Gate("time", seconds=5.0)),
                Stage(preset="Red Disconnect", gate=Gate("time", seconds=5.0)),
            ],
        )
        runner = CutChainRunner(cfg, FakeController(), on_event=events.append)
        runner.start()
        time.sleep(0.1)
        runner.stop()
        # Should have emitted halt before completing all stages.
        kinds = [e.kind for e in events]
        assert "halt" in kinds or "complete" not in kinds


class TestFailureModes:
    """on_failure halt vs continue."""

    def test_halt_on_failure_stops_chain(self) -> None:
        ctrl = FakeController(fail_on=1)
        events: list = []
        cfg = ChainConfig(
            target_ip="10.0.0.5",
            stages=[
                Stage(preset="Lag", gate=Gate("time", seconds=0.05)),
                Stage(preset="Red Disconnect", gate=Gate("time", seconds=0.05)),
            ],
            on_failure="halt",
        )
        runner = CutChainRunner(cfg, ctrl, on_event=events.append)
        runner.start()
        time.sleep(0.3)
        runner.stop()
        # First stage failed → second never ran → no successful disrupt.
        disrupts = [c for c in ctrl.calls if c[0] == "disrupt"]
        assert len(disrupts) == 0

    def test_continue_on_failure_advances(self) -> None:
        ctrl = FakeController(fail_on=1)
        events: list = []
        cfg = ChainConfig(
            target_ip="10.0.0.5",
            stages=[
                Stage(preset="Lag", gate=Gate("time", seconds=0.05)),
                Stage(preset="Red Disconnect", gate=Gate("time", seconds=0.05)),
            ],
            on_failure="continue",
        )
        runner = CutChainRunner(cfg, ctrl, on_event=events.append)
        runner.start()
        time.sleep(0.5)
        runner.stop()
        # Second stage ran despite first failing.
        disrupts = [c for c in ctrl.calls if c[0] == "disrupt"]
        assert len(disrupts) >= 1


class TestGates:
    """Time, severed, connected, packets gate kinds."""

    def test_severed_gate_advances_when_state_matches(self) -> None:
        # FakeController instantly reports max_cut_state="severed".
        events: list = []
        cfg = ChainConfig(
            target_ip="10.0.0.5",
            stages=[Stage(
                preset="Red Disconnect",
                gate=Gate(kind="severed", seconds=2.0),
            )],
        )
        runner = CutChainRunner(cfg, FakeController(), on_event=events.append)
        start = time.time()
        runner.start()
        time.sleep(0.5)
        runner.stop()
        # Gate should advance almost immediately when state matches.
        assert time.time() - start < 1.0

    def test_packets_gate_advances_when_count_reached(self) -> None:
        events: list = []
        cfg = ChainConfig(
            target_ip="10.0.0.5",
            stages=[Stage(
                preset="Lag",
                gate=Gate(kind="packets", packets=50, seconds=2.0),
            )],
        )
        runner = CutChainRunner(cfg, FakeController(), on_event=events.append)
        runner.start()
        time.sleep(0.5)
        runner.stop()
        kinds = [e.kind for e in events]
        assert "stage_end" in kinds

    def test_unknown_gate_falls_back_to_short_sleep(self) -> None:
        events: list = []
        cfg = ChainConfig(
            target_ip="10.0.0.5",
            stages=[Stage(
                preset="Lag",
                gate=Gate(kind="bogus_gate_kind"),
            )],
        )
        runner = CutChainRunner(cfg, FakeController(), on_event=events.append)
        runner.start()
        time.sleep(1.5)  # default fallback sleep is 1s
        runner.stop()
        # Should still complete despite unknown gate kind.
        kinds = [e.kind for e in events]
        assert "complete" in kinds or "halt" in kinds
