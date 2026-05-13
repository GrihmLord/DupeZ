"""Tests for app.core.kill_switch (v5.7.0 feature #6)."""

from __future__ import annotations

import threading
import time

import pytest

from app.core.kill_switch import (
    AntiCheatProcessTrigger,
    KillSwitch,
    KillSwitchConfig,
    ManualTrigger,
    PacketCounterTrigger,
    RiskScoreTrigger,
)


class TestManualTrigger:
    """Manual trigger fires when fire() is called; resets after read."""

    def test_initial_state_no_fire(self) -> None:
        t = ManualTrigger()
        assert t.check() is None

    def test_fire_then_check_returns_reason(self) -> None:
        t = ManualTrigger()
        t.fire("operator panic button")
        assert t.check() == "operator panic button"

    def test_check_after_fire_only_returns_once(self) -> None:
        # Idempotent: a fire fires exactly one time, then resets.
        t = ManualTrigger()
        t.fire("first")
        assert t.check() == "first"
        assert t.check() is None  # already consumed

    def test_default_reason(self) -> None:
        t = ManualTrigger()
        t.fire()
        assert t.check() == "manual trigger"


class TestAntiCheatProcessTrigger:
    """Anti-cheat trigger respects the configured name set."""

    def test_no_processes_configured_no_fire(self) -> None:
        # Empty config → trigger should never fire.
        t = AntiCheatProcessTrigger(processes=[])
        assert t.check() is None

    def test_unmatched_process_no_fire(self, monkeypatch: pytest.MonkeyPatch) -> None:
        t = AntiCheatProcessTrigger(processes=["nonexistent_ac.exe"])
        # psutil is real on this system — if "nonexistent_ac.exe"
        # isn't running, this should not fire. Don't mock.
        assert t.check() is None


class TestPacketCounterTrigger:
    """Token-bucket-style sustained drop-rate detector."""

    def test_first_sample_does_not_fire(self) -> None:
        # No previous sample to compute rate against.
        t = PacketCounterTrigger(
            get_drop_counters=lambda: {"a": 1000},
            max_drop_per_second=100,
            sustain_s=0.1,
        )
        assert t.check() is None

    def test_under_threshold_no_fire(self) -> None:
        counters = {"a": 0}
        t = PacketCounterTrigger(
            get_drop_counters=lambda: counters,
            max_drop_per_second=100,
            sustain_s=0.1,
        )
        t.check()  # establish baseline
        time.sleep(0.05)
        counters["a"] = 1  # 1 drop in 50ms = 20/sec, way under 100
        assert t.check() is None

    def test_over_threshold_sustained_fires(self) -> None:
        counters = {"a": 0}
        t = PacketCounterTrigger(
            get_drop_counters=lambda: counters,
            max_drop_per_second=100,
            sustain_s=0.05,  # tight window for the test
        )
        t.check()  # baseline
        # Spike: 100 drops in 0.05s = 2000/sec >> 100
        counters["a"] = 100
        time.sleep(0.05)
        t.check()  # arms the over-threshold detector
        # Sustain it — another 0.05s of high rate
        counters["a"] = 200
        time.sleep(0.06)
        reason = t.check()
        assert reason is not None
        assert "drop rate" in reason

    def test_dropping_below_resets_over_window(self) -> None:
        counters = {"a": 0}
        t = PacketCounterTrigger(
            get_drop_counters=lambda: counters,
            max_drop_per_second=100,
            sustain_s=0.2,
        )
        t.check()
        counters["a"] = 100; time.sleep(0.05); t.check()  # over
        # Now drop the rate
        counters["a"] = 101; time.sleep(0.2); t.check()  # near zero
        # Should NOT fire — the sustained window was broken.
        counters["a"] = 102; time.sleep(0.05); reason = t.check()
        assert reason is None


class TestKillSwitchOrchestrator:
    """KillSwitch polls triggers and calls stop_callback once per fire."""

    def test_manual_fire_invokes_callback(self) -> None:
        fired = []
        ks = KillSwitch(
            config=KillSwitchConfig(
                enabled=True,
                poll_interval_s=0.05,
                cooldown_s=10.0,  # long cooldown to verify single-fire
                triggers=[ManualTrigger()],
            ),
            stop_callback=fired.append,
        )
        ks.start()
        try:
            ks.fire_manual("test")
            time.sleep(0.2)
        finally:
            ks.stop()
        assert len(fired) == 1
        assert "manual" in fired[0]

    def test_disabled_blocks_non_manual_triggers(self) -> None:
        fired = []
        # A trigger that always reports, but kill switch is disabled.
        class AlwaysFires:
            type_id = "always"
            def check(self) -> str:
                return "should not fire"
        ks = KillSwitch(
            config=KillSwitchConfig(
                enabled=False,
                poll_interval_s=0.05,
                cooldown_s=10.0,
                triggers=[AlwaysFires()],  # type: ignore
            ),
            stop_callback=fired.append,
        )
        ks.start()
        try:
            time.sleep(0.2)
        finally:
            ks.stop()
        assert fired == []

    def test_manual_works_even_when_disabled(self) -> None:
        # Documented: ManualTrigger bypasses the disabled gate so
        # operators always have a panic button.
        fired = []
        ks = KillSwitch(
            config=KillSwitchConfig(
                enabled=False,
                poll_interval_s=0.05,
                cooldown_s=10.0,
                triggers=[ManualTrigger()],
            ),
            stop_callback=fired.append,
        )
        ks.start()
        try:
            ks.fire_manual("override")
            time.sleep(0.2)
        finally:
            ks.stop()
        assert len(fired) == 1

    def test_no_manual_trigger_fire_manual_still_works(self) -> None:
        # Even without a ManualTrigger in config, fire_manual() should
        # invoke the callback directly.
        fired = []
        ks = KillSwitch(
            config=KillSwitchConfig(
                enabled=False, poll_interval_s=0.05,
                cooldown_s=10.0, triggers=[],
            ),
            stop_callback=fired.append,
        )
        ks.start()
        try:
            ks.fire_manual("direct fire")
            time.sleep(0.1)
        finally:
            ks.stop()
        assert len(fired) == 1
