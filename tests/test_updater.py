"""Tests for app.core.updater — version parsing and constants."""

from app.core.updater import _parse_version, CURRENT_VERSION


class TestParseVersion:
    """Test the _parse_version helper."""

    def test_simple_version(self):
        """Standard semver string produces correct tuple."""
        assert _parse_version("4.0.0") == (4, 0, 0)

    def test_v_prefix(self):
        """Leading 'v' is stripped."""
        assert _parse_version("v4.1.0") == (4, 1, 0)

    def test_uppercase_v_prefix(self):
        """Leading 'V' is also stripped."""
        assert _parse_version("V3.2.1") == (3, 2, 1)

    def test_beta_suffix(self):
        """Non-numeric suffix is stripped from each segment."""
        assert _parse_version("v4.1.0-beta1") == (4, 1, 0)

    def test_two_part_version(self):
        """Two-part version string works."""
        assert _parse_version("4.1") == (4, 1)

    def test_single_number(self):
        """Single number returns single-element tuple."""
        assert _parse_version("5") == (5,)

    def test_empty_string(self):
        """Empty string returns tuple with zero."""
        assert _parse_version("") == (0,)

    def test_version_comparison(self):
        """Higher version compares greater."""
        assert _parse_version("4.1.0") > _parse_version("4.0.0")
        assert _parse_version("4.0.1") > _parse_version("4.0.0")
        assert _parse_version("5.0.0") > _parse_version("4.9.9")

    def test_equal_versions(self):
        """Same version strings compare equal."""
        assert _parse_version("4.0.0") == _parse_version("v4.0.0")


class TestCurrentVersion:
    """Test the CURRENT_VERSION constant."""

    def test_format(self):
        """CURRENT_VERSION is a valid dotted version string."""
        parts = CURRENT_VERSION.split(".")
        assert len(parts) >= 2
        for part in parts:
            assert part.isdigit()

    def test_parseable(self):
        """CURRENT_VERSION can be parsed by _parse_version."""
        result = _parse_version(CURRENT_VERSION)
        assert len(result) >= 2
        assert all(isinstance(x, int) for x in result)
