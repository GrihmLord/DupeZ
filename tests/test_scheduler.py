"""Tests for app.core.scheduler — rules, macros, and serialization."""

from app.core.scheduler import ScheduledRule, MacroStep, DisruptionMacro


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
