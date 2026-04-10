"""Tests for app.utils.helpers — utility functions."""

import sys
from unittest.mock import patch
from app.utils.helpers import (
    mask_ip, _NO_WINDOW, _MAC_ADDRESS_PATTERN,
    validate_ip_address, validate_mac_address,
    format_bytes, format_duration,
)


class TestMaskIp:
    """Test the mask_ip function."""

    def test_standard_ipv4(self):
        """Standard IPv4 masks last octet with 'x'."""
        assert mask_ip("192.168.1.42") == "192.168.1.x"

    def test_another_ip(self):
        """Different IP also masks correctly."""
        assert mask_ip("10.0.0.1") == "10.0.0.x"

    def test_short_input(self):
        """Non-IPv4 input returned unchanged."""
        assert mask_ip("invalid") == "invalid"

    def test_empty_string(self):
        """Empty string returned unchanged."""
        assert mask_ip("") == ""

    def test_three_octets(self):
        """Three-octet string returned unchanged (not valid IPv4)."""
        assert mask_ip("192.168.1") == "192.168.1"


class TestNoWindow:
    """Test the _NO_WINDOW constant."""

    def test_value_on_any_platform(self):
        """_NO_WINDOW is 0x08000000 on Windows, 0 elsewhere."""
        if sys.platform == "win32":
            assert _NO_WINDOW == 0x08000000
        else:
            assert _NO_WINDOW == 0

    def test_is_int(self):
        """_NO_WINDOW is an integer."""
        assert isinstance(_NO_WINDOW, int)


class TestValidateIpAddress:
    """Test IP validation."""

    def test_valid_ip(self):
        assert validate_ip_address("192.168.1.1") is True

    def test_loopback(self):
        assert validate_ip_address("127.0.0.1") is True

    def test_invalid_string(self):
        assert validate_ip_address("not.an.ip.addr") is False

    def test_empty(self):
        assert validate_ip_address("") is False

    def test_too_few_octets(self):
        assert validate_ip_address("192.168.1") is False


class TestValidateMacAddress:
    """Test MAC address validation."""

    def test_colon_separated(self):
        assert validate_mac_address("AA:BB:CC:DD:EE:FF") is True

    def test_dash_separated(self):
        assert validate_mac_address("AA-BB-CC-DD-EE-FF") is True

    def test_lowercase(self):
        assert validate_mac_address("aa:bb:cc:dd:ee:ff") is True

    def test_invalid(self):
        assert validate_mac_address("ZZZZ") is False

    def test_empty(self):
        assert validate_mac_address("") is False


class TestFormatBytes:
    """Test byte formatting."""

    def test_bytes(self):
        assert "B" in format_bytes(500)

    def test_kilobytes(self):
        result = format_bytes(2048)
        assert "KB" in result

    def test_zero(self):
        assert "0" in format_bytes(0)


class TestFormatDuration:
    """Test duration formatting."""

    def test_seconds(self):
        result = format_duration(45)
        assert "45" in result

    def test_minutes(self):
        result = format_duration(125)
        assert "2" in result  # 2 minutes
