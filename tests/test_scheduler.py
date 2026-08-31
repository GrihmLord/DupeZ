"""Tests for app.core.scheduler — rules, macros, and serialization."""

import threading

from app.core.scheduler import (
    DisruptionMacro,
    DisruptionScheduler,
    MacroStep,
    ScheduledRule,
)


TARGET = "198.51.100.5"


def _one_step_macro(name: str, macro_id: str) -> DisruptionMacro:
    return DisruptionMacro(
        macro_id=macro_id,
        name=name,
        target_ip=TARGET,
        steps=[MacroStep(methods=["lag"], duration_seconds=1)],
    )


class TestScheduledRule:
    """Test ScheduledRule dataclass."""

    def test_to_dict_round_trip(self):
        """to_dict and from_dict produce equivalent objects."""
        rule = ScheduledRule(
            name="test_rule",
            target_ip="198.51.100.5",
            methods=["lag", "drop"],
            params={"lag_delay": 1500, "drop_chance": 90},
            start_time="14:30",
            duration_seconds=120,
        )
        d = rule.to_dict()
        restored = ScheduledRule.from_dict(d)

        assert restored.name == "test_rule"
        assert restored.target_ip == "198.51.100.5"
        assert restored.methods == ["lag", "drop"]
        assert restored.duration_seconds == 120
        assert restored.params["lag_delay"] == 1500

    def test_from_dict_ignores_unknown(self):
        """from_dict ignores keys not in the dataclass."""
        d = {"name": "test", "future_field": True, "methods": ["lag"]}
        rule = ScheduledRule.from_dict(d)
        assert rule.name == "test"
        assert not hasattr(rule, "future_field")

    def test_defaults(self):
        """Default values are sensible."""
        rule = ScheduledRule()
        assert rule.enabled is True
        assert rule.repeat_interval == 0
        assert rule.duration_seconds == 60

    def test_duration_and_repeat_interval_are_bounded(self):
        rule = ScheduledRule(
            duration_seconds=999999,
            repeat_interval=999999,
        )
        assert rule.duration_seconds == 3600
        assert rule.repeat_interval == 86400


class TestMacroStep:
    """Test MacroStep dataclass."""

    def test_to_dict_round_trip(self):
        """Serialization round-trip preserves data."""
        step = MacroStep(
            methods=["bandwidth", "throttle"],
            params={"bandwidth_limit": 5, "throttle_chance": 80},
            duration_seconds=30,
        )
        d = step.to_dict()
        restored = MacroStep.from_dict(d)
        assert restored.methods == ["bandwidth", "throttle"]
        assert restored.duration_seconds == 30

    def test_defaults(self):
        """Default duration is 10 seconds."""
        step = MacroStep()
        assert step.duration_seconds == 10
        assert step.methods == []

    def test_duration_is_bounded(self):
        assert MacroStep(duration_seconds=0).duration_seconds == 1
        assert MacroStep(duration_seconds=999999).duration_seconds == 3600


class TestDisruptionMacro:
    """Test DisruptionMacro with nested steps."""

    def test_to_dict_with_steps(self):
        """Macro serializes steps correctly."""
        macro = DisruptionMacro(
            name="Quick Macro",
            repeat_count=2,
            steps=[
                MacroStep(methods=["lag"], params={"lag_delay": 500}, duration_seconds=10),
                MacroStep(methods=["drop"], params={"drop_chance": 95}, duration_seconds=20),
            ],
        )
        d = macro.to_dict()
        assert len(d["steps"]) == 2
        assert d["steps"][0]["methods"] == ["lag"]
        assert d["repeat_count"] == 2

    def test_from_dict_with_steps(self):
        """Macro deserializes steps from dicts."""
        d = {
            "name": "Restored",
            "repeat_count": 3,
            "steps": [
                {"methods": ["lag"], "params": {"lag_delay": 800}, "duration_seconds": 15},
            ],
        }
        macro = DisruptionMacro.from_dict(d)
        assert macro.name == "Restored"
        assert len(macro.steps) == 1
        assert isinstance(macro.steps[0], MacroStep)
        assert macro.steps[0].methods == ["lag"]

    def test_from_dict_does_not_mutate_input(self):
        """from_dict does not mutate the input dict."""
        d = {
            "name": "test",
            "steps": [{"methods": ["lag"], "duration_seconds": 10}],
        }
        original_steps = d["steps"].copy()
        DisruptionMacro.from_dict(d)
        assert d["steps"] == original_steps

    def test_repeat_count_and_step_count_are_bounded(self):
        macro = DisruptionMacro(
            repeat_count=0,
            steps=[MacroStep() for _ in range(150)],
        )
        assert macro.repeat_count == 1
        assert len(macro.steps) == 100


class TestSchedulerExecutionContracts:
    """Callback results remain authoritative for scheduler ownership."""

    def test_failed_rule_start_never_claims_active_ownership(self, tmp_path):
        starts = []

        def reject_start(ip, _methods, _params):
            starts.append(ip)
            return False

        scheduler = DisruptionScheduler(
            reject_start,
            lambda _ip: True,
            str(tmp_path),
        )
        rule = ScheduledRule(
            rule_id="rule-fails",
            name="Fails",
            target_ip=TARGET,
            methods=["lag"],
            start_time="100",
        )
        scheduler.add_rule(rule)

        scheduler._scheduler_tick(100.0, "00:00")

        assert starts == [TARGET]
        assert scheduler._active_rules == {}
        assert rule.last_run == 0.0

    def test_failed_rule_stop_retains_ownership_for_retry(self, tmp_path):
        stop_results = iter((False, True))
        scheduler = DisruptionScheduler(
            lambda _ip, _methods, _params: True,
            lambda _ip: next(stop_results),
            str(tmp_path),
        )
        rule = ScheduledRule(
            rule_id="rule-active",
            name="Active",
            target_ip=TARGET,
        )
        scheduler.add_rule(rule)
        scheduler._active_rules[rule.rule_id] = 10.0

        scheduler._scheduler_tick(11.0, "00:00")
        assert scheduler._active_rules == {rule.rule_id: 10.0}

        scheduler._scheduler_tick(12.0, "00:00")
        assert scheduler._active_rules == {}

    def test_shutdown_reports_and_retains_failed_rule_release(self, tmp_path):
        scheduler = DisruptionScheduler(
            lambda _ip, _methods, _params: True,
            lambda _ip: False,
            str(tmp_path),
        )
        rule = ScheduledRule(
            rule_id="rule-active",
            name="Active",
            target_ip=TARGET,
        )
        scheduler.add_rule(rule)
        scheduler._active_rules[rule.rule_id] = 10.0

        assert scheduler.stop() is False
        assert rule.rule_id in scheduler._active_rules

    def test_macro_failed_start_emits_failed_not_done(self, tmp_path):
        events = []
        finished = threading.Event()

        def record(event, _ip, info):
            events.append((event, info))
            if event in {"done", "cancelled", "failed"}:
                finished.set()

        scheduler = DisruptionScheduler(
            lambda _ip, _methods, _params: False,
            lambda _ip: True,
            str(tmp_path),
            record,
        )
        macro = _one_step_macro("Start fails", "macro-start-fails")
        scheduler.add_macro(macro)

        assert scheduler.run_macro(macro.macro_id) is True
        assert finished.wait(2)

        assert [event for event, _ in events] == ["failed"]
        assert events[0][1]["reason"] == "start_failed"
        assert scheduler.is_macro_running() is False

    def test_macro_cancellation_is_private_and_replacement_is_rejected(
        self,
        tmp_path,
    ):
        start_entered = threading.Event()
        allow_start_to_return = threading.Event()
        events = []
        starts = []

        def disrupt(ip, _methods, _params):
            starts.append(ip)
            start_entered.set()
            assert allow_start_to_return.wait(2)
            return True

        scheduler = DisruptionScheduler(
            disrupt,
            lambda _ip: True,
            str(tmp_path),
            lambda event, _ip, _info: events.append(event),
        )
        first = _one_step_macro("First", "macro-first")
        second = _one_step_macro("Second", "macro-second")
        scheduler.add_macro(first)
        scheduler.add_macro(second)

        assert scheduler.run_macro(first.macro_id) is True
        assert start_entered.wait(2)
        assert scheduler.stop_macro(timeout=0.01) is False
        assert scheduler.run_macro(second.macro_id) is False

        worker = scheduler._macro_thread
        assert worker is not None
        allow_start_to_return.set()
        worker.join(timeout=2)

        assert not worker.is_alive()
        assert starts == [TARGET]
        assert events == ["start", "stop", "cancelled"]
        assert scheduler.is_macro_running() is False

    def test_failed_macro_stop_retains_owner_and_blocks_replacement(
        self,
        tmp_path,
    ):
        started = threading.Event()
        stop_results = iter((False, True))
        events = []

        def record(event, _ip, info):
            events.append((event, info))
            if event == "start":
                started.set()

        scheduler = DisruptionScheduler(
            lambda _ip, _methods, _params: True,
            lambda _ip: next(stop_results),
            str(tmp_path),
            record,
        )
        first = _one_step_macro("First", "macro-first")
        second = _one_step_macro("Second", "macro-second")
        scheduler.add_macro(first)
        scheduler.add_macro(second)

        assert scheduler.run_macro(first.macro_id) is True
        assert started.wait(2)
        assert scheduler.stop_macro() is False
        assert scheduler.is_macro_running() is True
        assert scheduler.run_macro(second.macro_id) is False
        assert [event for event, _ in events] == ["start", "failed"]
        assert events[-1][1]["reason"] == "stop_failed"

        assert scheduler.stop_macro() is True
        assert scheduler.is_macro_running() is False
        assert [event for event, _ in events] == ["start", "failed", "stop"]
