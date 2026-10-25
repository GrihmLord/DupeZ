"""Tests for app.core.kill_switch (v5.7.0 feature #6)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.core.kill_switch import (
    AntiCheatProcessTrigger,
    KillSwitch,
    KillSwitchConfig,
    KillSwitchConfigurationError,
    ManualTrigger,
    PacketCounterTrigger,
    RiskScoreTrigger,
    build_kill_switch_config,
    sanitize_process_basenames,
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
        now = [0.0]
        t = PacketCounterTrigger(
            get_drop_counters=lambda: counters,
            max_drop_per_second=100,
            sustain_s=0.1,
            clock=lambda: now[0],
        )
        t.check()  # establish baseline
        now[0] = 1.0
        counters["a"] = 1
        assert t.check() is None

    def test_over_threshold_sustained_fires(self) -> None:
        counters = {"a": 0}
        now = [0.0]
        t = PacketCounterTrigger(
            get_drop_counters=lambda: counters,
            max_drop_per_second=100,
            sustain_s=0.05,  # tight window for the test
            clock=lambda: now[0],
        )
        t.check()  # baseline
        now[0] = 1.0
        counters["a"] = 100
        t.check()  # arms the over-threshold detector
        now[0] = 1.1
        counters["a"] = 200
        reason = t.check()
        assert reason is not None
        assert "drop rate" in reason

    def test_dropping_below_resets_over_window(self) -> None:
        counters = {"a": 0}
        now = [0.0]
        t = PacketCounterTrigger(
            get_drop_counters=lambda: counters,
            max_drop_per_second=100,
            sustain_s=0.2,
            clock=lambda: now[0],
        )
        t.check()
        now[0] = 0.1
        counters["a"] = 100
        t.check()
        now[0] = 1.1
        counters["a"] = 101
        t.check()
        now[0] = 1.2
        counters["a"] = 102
        reason = t.check()
        assert reason is None

    def test_counter_reset_establishes_a_new_baseline(self) -> None:
        counters = {"packets_dropped": 100}
        now = [0.0]
        trigger = PacketCounterTrigger(
            lambda: counters,
            max_drop_per_second=10,
            sustain_s=0.05,
            clock=lambda: now[0],
        )
        assert trigger.check() is None
        now[0] = 1.0
        counters["packets_dropped"] = 0
        assert trigger.check() is None
        assert trigger._over_since is None

    @pytest.mark.parametrize(
        "counters",
        [None, [], {"packets_dropped": True}, {"packets_dropped": -1}],
    )
    def test_invalid_counter_payloads_fail_closed_without_coercion(
        self,
        counters,
    ) -> None:
        trigger = PacketCounterTrigger(
            lambda: counters,
            max_drop_per_second=10,
            sustain_s=0.05,
        )
        assert trigger.check() is None


class TestPersistedConfiguration:
    def test_defaults_are_disabled_and_manual_is_always_present(self) -> None:
        config = build_kill_switch_config(
            SimpleNamespace(),
            get_drop_counters=lambda: {"packets_dropped": 0},
        )

        assert config.enabled is False
        assert any(isinstance(trigger, ManualTrigger) for trigger in config.triggers)

    def test_process_names_are_reduced_to_unique_lowercase_basenames(self) -> None:
        assert sanitize_process_basenames(
            [r"C:\Program Files\Vendor\Guard.EXE", "guard.exe", "AC Service.exe"]
        ) == ["guard.exe", "ac service.exe"]

    def test_process_watch_can_be_disabled_without_removing_other_triggers(self) -> None:
        config = build_kill_switch_config(
            SimpleNamespace(kill_switch_process_watch_enabled=False),
            get_drop_counters=lambda: {"packets_dropped": 0},
        )

        trigger_types = [trigger.type_id for trigger in config.triggers]
        assert "anticheat_process" not in trigger_types
        assert trigger_types == ["risk_score", "packet_counter", "manual"]

    @pytest.mark.parametrize(
        "values",
        ["guard.exe", ["*.exe"], [".."], ["bad\nname.exe"], [123]],
    )
    def test_invalid_process_name_settings_are_rejected(self, values) -> None:
        with pytest.raises(KillSwitchConfigurationError):
            sanitize_process_basenames(values)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("kill_switch_enabled", 1),
            ("kill_switch_process_watch_enabled", "yes"),
            ("kill_switch_risk_threshold", 101),
            ("kill_switch_packet_drop_ceiling", 0),
            ("kill_switch_packet_sustain_seconds", float("nan")),
            ("kill_switch_poll_interval_seconds", 0.01),
            ("kill_switch_cooldown_seconds", 3601),
        ],
    )
    def test_out_of_bounds_persisted_settings_are_rejected(
        self,
        key,
        value,
    ) -> None:
        settings = SimpleNamespace(**{key: value})
        with pytest.raises(KillSwitchConfigurationError):
            build_kill_switch_config(
                settings,
                get_drop_counters=lambda: {"packets_dropped": 0},
            )

    def test_config_constructor_adds_manual_trigger(self) -> None:
        config = KillSwitchConfig(enabled=False, triggers=[])
        assert len(config.triggers) == 1
        assert isinstance(config.triggers[0], ManualTrigger)


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
        ks.fire_manual("test")
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
        ks._tick()
        assert fired == []

    def test_first_non_manual_trigger_is_not_suppressed_by_cooldown(self) -> None:
        fired = []

        class AlwaysFires:
            type_id = "always"

            @staticmethod
            def check() -> str:
                return "first poll"

        ks = KillSwitch(
            KillSwitchConfig(
                enabled=True,
                cooldown_s=3600.0,
                triggers=[AlwaysFires()],  # type: ignore[list-item]
            ),
            stop_callback=fired.append,
        )

        ks._tick()

        assert fired == ["always: first poll"]

    def test_failed_stop_does_not_start_cooldown(self) -> None:
        attempts = []

        class AlwaysFires:
            type_id = "always"

            @staticmethod
            def check() -> str:
                return "unsafe state"

        def stop_callback(reason):
            attempts.append(reason)
            return len(attempts) > 1

        ks = KillSwitch(
            KillSwitchConfig(
                enabled=True,
                cooldown_s=3600.0,
                triggers=[AlwaysFires()],  # type: ignore[list-item]
            ),
            stop_callback=stop_callback,
        )

        ks._tick()
        assert ks._last_fire_ts is None
        ks._tick()

        assert len(attempts) == 2
        assert ks._last_fire_ts is not None

    def test_raised_stop_does_not_start_cooldown(self) -> None:
        attempts = []

        class AlwaysFires:
            type_id = "always"

            @staticmethod
            def check() -> str:
                return "unsafe state"

        def stop_callback(reason):
            attempts.append(reason)
            raise RuntimeError("restoration failed")

        ks = KillSwitch(
            KillSwitchConfig(
                enabled=True,
                cooldown_s=3600.0,
                triggers=[AlwaysFires()],  # type: ignore[list-item]
            ),
            stop_callback=stop_callback,
        )

        ks._tick()
        ks._tick()

        assert len(attempts) == 2
        assert ks._last_fire_ts is None

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
        ks.fire_manual("override")
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
        ks.fire_manual("direct fire")
        assert len(fired) == 1


class TestThreadLifecycle:
    """start()/stop() must not leak or duplicate the poll thread.

    Regression: stop() nulled _thread unconditionally and start() only
    checked ``_thread is not None``. A stop() whose join timed out left
    a live thread plus a None ref, so the next start() spawned a SECOND
    poll thread — two threads then raced on _last_fire_ts.
    """

    @staticmethod
    def _make() -> KillSwitch:
        return KillSwitch(
            KillSwitchConfig(enabled=True, poll_interval_s=0.05),
            stop_callback=lambda _reason: None,
        )

    def test_double_start_does_not_duplicate_thread(self) -> None:
        ks = self._make()
        ks.start()
        first = ks._thread
        ks.start()  # second start must be a no-op
        try:
            assert ks._thread is first, "second start() replaced the thread"
            assert ks.is_running is True
        finally:
            ks.stop()

    def test_clean_stop_clears_thread_ref(self) -> None:
        ks = self._make()
        ks.start()
        t = ks._thread
        ks.stop()
        # poll_interval is 0.05s, so the thread exits well within the
        # 2s join — a clean stop must null the reference.
        assert t is not None and not t.is_alive()
        assert ks._thread is None

    def test_stop_then_start_restarts_cleanly(self) -> None:
        ks = self._make()
        ks.start()
        ks.stop()
        ks.start()  # fresh start after a clean stop must work
        try:
            assert ks._thread is not None and ks._thread.is_alive()
        finally:
            ks.stop()

    def test_poll_loop_waits_once_instead_of_busy_spinning(self) -> None:
        ks = self._make()
        ticks = []
        waits = []

        class _StopAfterOneWait:
            @staticmethod
            def is_set() -> bool:
                return False

            @staticmethod
            def wait(interval: float) -> bool:
                waits.append(interval)
                return True

        ks._stop_event = _StopAfterOneWait()  # type: ignore[assignment]
        ks._tick = lambda: ticks.append(True)  # type: ignore[method-assign]

        ks._run()

        assert ticks == [True]
        assert waits == [0.05]

    def test_stop_interrupts_a_long_poll_interval(self) -> None:
        checked = threading.Event()

        class _ObservedTrigger:
            type_id = "observed"

            @staticmethod
            def check() -> None:
                checked.set()
                return None

        ks = KillSwitch(
            KillSwitchConfig(
                enabled=True,
                poll_interval_s=60.0,
                triggers=[_ObservedTrigger()],  # type: ignore[list-item]
            ),
            stop_callback=lambda _reason: None,
        )
        ks.start()
        assert checked.wait(timeout=1.0)

        started = time.monotonic()
        assert ks.stop() is True

        assert time.monotonic() - started < 0.5
        assert ks.is_running is False
