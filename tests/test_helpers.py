"""Tests for app.utils.helpers — utility functions."""

import sys
from unittest.mock import patch
from app.utils.helpers import (
    mask_ip, mask_ips_in_text, _NO_WINDOW, _MAC_ADDRESS_PATTERN,
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


class TestMaskIpsInText:
    """mask_ips_in_text scrubs IPv4 addresses embedded anywhere in a string.

    This is the centralized opsec masker behind the log scrubber, the
    audit-log PII scrub, and the Discord webhook scrub — every place an
    IP could leave the process.
    """

    def test_bare_ip_masked(self):
        assert mask_ips_in_text("10.0.0.9") == "10.0.0.x"

    def test_embedded_ip_masked(self):
        # The leak that key-based / whole-string maskers missed.
        assert mask_ips_in_text("cut on 192.168.1.50 failed") == \
            "cut on 192.168.1.x failed"

    def test_multiple_ips_all_masked(self):
        out = mask_ips_in_text("from 1.2.3.4 to 8.8.8.8")
        assert "1.2.3.4" not in out and "8.8.8.8" not in out
        assert out == "from 1.2.3.x to 8.8.8.x"

    def test_version_string_not_touched(self):
        # A 3-octet version must not be mistaken for an IP.
        assert mask_ips_in_text("DupeZ v5.7.4 ready") == "DupeZ v5.7.4 ready"

    def test_four_part_version_is_masked_conservatively(self):
        # A 4-part dotted number ("5.7.4.0") is byte-identical to an
        # IPv4 address — it is impossible to tell apart, so it IS
        # masked. This is deliberate: over-masking a rare 4-part build
        # string is acceptable; under-masking would be a leak. DupeZ's
        # runtime __version__ is 3-part, so this never bites in practice.
        # Do not "fix" this into an exception — that would open a hole.
        assert mask_ips_in_text("build 5.7.4.0") == "build 5.7.4.x"

    def test_ip_with_port_keeps_port(self):
        assert mask_ips_in_text("connect 10.0.0.9:8080") == "connect 10.0.0.x:8080"

    def test_idempotent_on_already_masked(self):
        assert mask_ips_in_text("target 10.0.0.x") == "target 10.0.0.x"

    def test_octet_over_255_not_masked(self):
        # 999 is not a valid octet — must not be treated as an IP.
        assert mask_ips_in_text("id 999.1.1.1 here") == "id 999.1.1.1 here"

    def test_no_ip_unchanged(self):
        assert mask_ips_in_text("nothing to see") == "nothing to see"

    def test_empty_string(self):
        assert mask_ips_in_text("") == ""


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
