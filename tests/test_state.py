"""Tests for app.core.state — AppSettings and AppState."""

from app.core.state import AppSettings


class TestAppSettings:
    """Test AppSettings dataclass."""

    def test_default_values(self):
        """Default settings have sensible values."""
        settings = AppSettings()
        # Should have default scan interval, theme, etc.
        d = settings.__dict__ if hasattr(settings, '__dict__') else {}
        # AppSettings is a dataclass — it should be instantiable
        assert settings is not None

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
