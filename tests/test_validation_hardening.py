"""Regression tests for trust-boundary validation."""

from pathlib import Path

import pytest

from app.core.validation import (
    validate_entry_point,
    validate_local_target_ip,
    validate_safe_path,
    validate_url,
)


@pytest.mark.parametrize(
    "ip",
    ["10.0.0.8", "172.16.4.9", "192.168.1.50", "169.254.10.20"],
)
def test_local_target_accepts_local_ranges(ip: str) -> None:
    assert validate_local_target_ip(ip) == ip


@pytest.mark.parametrize(
    "ip",
    ["8.8.8.8", "127.0.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255"],
)
def test_local_target_rejects_out_of_scope_addresses(ip: str) -> None:
    with pytest.raises(ValueError, match="local/private"):
        validate_local_target_ip(ip)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.2/resource",
        "http://10.0.0.8/resource",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/resource",
        "http://0.0.0.0/resource",
    ],
)
def test_url_validator_rejects_non_routable_ip_literals(url: str) -> None:
    with pytest.raises(ValueError):
        validate_url(url)


def test_url_validator_accepts_public_https_domain() -> None:
    assert validate_url("https://example.com/releases", require_https=True)


def test_safe_path_rejects_sibling_prefix_collision(tmp_path: Path) -> None:
    base = tmp_path / "plugin"
    sibling = tmp_path / "plugin-evil" / "payload.py"
    base.mkdir()
    sibling.parent.mkdir()

    with pytest.raises(ValueError, match="traversal"):
        validate_safe_path(str(sibling), str(base))


def test_entry_point_rejects_plugin_directory_itself(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()

    with pytest.raises(ValueError):
        validate_entry_point(".", str(plugin_dir))
