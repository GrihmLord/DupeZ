"""Tests for app.core.state — AppSettings and AppState."""

from app.core import state as state_module
from app.core.state import AppSettings, AppState


class TestAppSettings:
    """Test AppSettings dataclass."""

    def test_default_values(self):
        """Default settings have sensible values."""
        settings = AppSettings()
        # Should have default scan interval, theme, etc.
        d = settings.__dict__ if hasattr(settings, '__dict__') else {}
        # AppSettings is a dataclass — it should be instantiable
        assert settings is not None
        assert settings.kill_switch_enabled is False
        assert settings.kill_switch_process_watch_enabled is True
        assert settings.kill_switch_process_names == []
        assert settings.kill_switch_risk_threshold == 80
        assert settings.kill_switch_packet_drop_ceiling == 5000
        assert settings.kill_switch_packet_sustain_seconds == 5.0
        assert settings.kill_switch_poll_interval_seconds == 1.0
        assert settings.kill_switch_cooldown_seconds == 30.0

    def test_to_dict(self):
        """Settings can be serialized to dict."""
        settings = AppSettings()
        if hasattr(settings, 'to_dict'):
            d = settings.to_dict()
            assert isinstance(d, dict)

    def test_from_dict(self):
        """Settings can be deserialized from dict."""
        if hasattr(AppSettings, 'from_dict'):
            settings = AppSettings.from_dict({})
            assert settings is not None

    def test_legacy_renderer_preference_migrates_to_cpu(self):
        assert AppSettings(map_renderer="swiftshader").map_renderer == "software"

    def test_invalid_renderer_preference_falls_back_to_auto(self):
        assert AppSettings(map_renderer="not-a-renderer").map_renderer == "auto"

    def test_non_string_renderer_preference_is_type_safe(self):
        assert AppSettings(map_renderer=[]).map_renderer == "auto"
        assert AppSettings(map_renderer={"value": "gpu"}).map_renderer == "auto"

    def test_renderer_preference_is_normalized(self):
        assert AppSettings(map_renderer=" GPU ").map_renderer == "gpu"


def test_failed_settings_write_rolls_back_in_memory_value(
    tmp_path, monkeypatch
) -> None:
    state = AppState(str(tmp_path / "settings.json"))
    original = state.settings.theme
    notifications = []
    state.add_observer(lambda *args: notifications.append(args))
    monkeypatch.setattr(
        state_module.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("simulated replace failure")
        ),
    )

    assert state.update_setting("theme", "light") is False
    assert state.settings.theme == original
    assert notifications == []
    assert not (tmp_path / "settings.json.tmp").exists()
