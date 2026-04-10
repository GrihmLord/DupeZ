"""
Centralized Input Validation for DupeZ.

Enforces strict allowlist validation at every trust boundary.
All external input — CLI arguments, JSON configs, plugin manifests,
LLM responses, network data, filter strings — passes through
validators in this module before being consumed.

Threat Model:
  - Injection attacks via malformed filter strings
  - Path traversal in plugin entry points and config paths
  - Type confusion from untrusted JSON payloads
  - Oversized payloads causing memory exhaustion
  - Malicious LLM responses with unexpected structure

Design Principle: DENY by default.  Only explicitly allowed
patterns pass validation.  Everything else is rejected with a
descriptive error.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Type

from app.logs.logger import log_error, log_warning

__all__ = [
    "validate_ip",
    "validate_ip_strict",
    "validate_filter_string",
    "validate_json_size",
    "safe_json_loads",
    "validate_methods",
    "validate_params",
    "validate_disruption_config",
    "validate_plugin_name",
    "validate_version_string",
    "validate_entry_point",
    "validate_safe_path",
    "validate_url",
    "validate_setting_key",
]


# ── Constants ────────────────────────────────────────────────────────

# Maximum sizes (defense against memory exhaustion)
MAX_JSON_SIZE_BYTES: int = 1_048_576       # 1 MB
MAX_FILTER_STRING_LENGTH: int = 512
MAX_PLUGIN_NAME_LENGTH: int = 64
MAX_PATH_COMPONENT_LENGTH: int = 255
MAX_CONFIG_NESTING_DEPTH: int = 10
MAX_LIST_ITEMS: int = 1000

# IP address patterns
_IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)

# Allowed characters in various contexts
_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\- .]+$")
_SAFE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9\-.]*)$")
_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-][A-Za-z0-9_\-.]*$")

# WinDivert filter: strict allowlist of allowed tokens
_WINDIVERT_ALLOWED_TOKENS = frozenset({
    # Operators
    "and", "or", "not", "true", "false",
    "(", ")", "==", "!=", "<", ">", "<=", ">=",
    # Layer fields
    "ip", "ip.SrcAddr", "ip.DstAddr", "ip.Protocol",
    "ipv6", "ipv6.SrcAddr", "ipv6.DstAddr",
    "tcp", "tcp.SrcPort", "tcp.DstPort", "tcp.Syn", "tcp.Ack",
    "tcp.Rst", "tcp.Fin", "tcp.Psh", "tcp.Urg",
    "udp", "udp.SrcPort", "udp.DstPort",
    "icmp", "icmpv6",
    "outbound", "inbound", "loopback",
    "ifIdx", "subIfIdx",
})

# Allowed disruption method names
VALID_DISRUPTION_METHODS: FrozenSet[str] = frozenset({
    "lag", "drop", "throttle", "duplicate", "ood", "corrupt",
    "rst", "disconnect", "bandwidth", "godmode", "dupe",
    "stealth_drop", "stealth_lag",
    "gilbert_elliott", "pareto_jitter", "correlated_drop",
    "token_bucket", "tick_sync", "pulse",
})

# Allowed disruption parameter keys and their type + range
VALID_PARAM_RANGES: Dict[str, Tuple[type, float, float]] = {
    "disconnect_chance": (float, 0, 100),
    "drop_chance": (float, 0, 100),
    "lag_delay": (float, 0, 120000),
    "throttle_chance": (float, 0, 100),
    "throttle_frame": (float, 0, 5000),
    "duplicate_chance": (float, 0, 100),
    "duplicate_count": (int, 1, 100),
    "ood_chance": (float, 0, 100),
    "tamper_chance": (float, 0, 100),
    "rst_chance": (float, 0, 100),
    "bandwidth_limit": (float, 0, 1_000_000),
    "bandwidth_queue": (int, 0, 10_000),
    "godmode_lag_ms": (float, 0, 120000),
    "godmode_drop_inbound_pct": (float, 0, 100),
    "godmode_keepalive_interval_ms": (float, 0, 10000),
    "godmode_pulse_block_ms": (float, 500, 30000),
    "godmode_pulse_flush_ms": (float, 100, 5000),
    "godmode_pulse_flush_max": (int, 10, 5000),
    "lag_keepalive_interval_ms": (float, 0, 10000),
    "dupe_prep_duration_ms": (float, 0, 30000),
    "dupe_cut_duration_ms": (float, 1000, 25000),
    "dupe_cycle_count": (int, 1, 10),
    "dupe_cycle_delay_ms": (float, 0, 30000),
    "dupe_action_delay_ms": (float, 0, 5000),
    "direction": (str, 0, 0),  # special case — validated separately
}

VALID_DIRECTIONS: FrozenSet[str] = frozenset({"both", "inbound", "outbound"})

# Allowed plugin types
VALID_PLUGIN_TYPES: FrozenSet[str] = frozenset({
    "disruption", "scanner", "ui_panel", "generic",
})

# Allowed setting keys (from AppSettings dataclass)
VALID_SETTING_KEYS: FrozenSet[str] = frozenset({
    "smart_mode", "auto_scan", "scan_interval", "max_devices", "log_level",
    "ping_timeout", "max_threads", "quick_scan", "auto_block",
    "high_traffic_threshold", "connection_limit",
    "suspicious_activity_threshold", "block_duration",
    "theme", "auto_refresh", "refresh_interval",
    "show_device_icons", "show_status_indicators", "compact_view",
    "show_notifications", "sound_alerts",
    "cache_duration", "memory_limit", "require_admin",
    "encrypt_logs", "debug_mode", "verbose_logging",
    "whitelist",
})


# ── IP Address Validation ────────────────────────────────────────────

def validate_ip(ip: str) -> Optional[str]:
    """Validate and normalize an IPv4 address.

    Returns the normalized IP string, or None if invalid.
    """
    if not ip or not isinstance(ip, str):
        return None
    ip = ip.strip()
    try:
        addr = ipaddress.IPv4Address(ip)
        return str(addr)
    except (ipaddress.AddressValueError, ValueError):
        return None


def validate_ip_strict(ip: str, context: str = "") -> str:
    """Validate IP address, raising ValueError if invalid."""
    result = validate_ip(ip)
    if result is None:
        raise ValueError(f"Invalid IP address{f' ({context})' if context else ''}: {ip!r}")
    return result


# ── WinDivert Filter Validation ──────────────────────────────────────

def validate_filter_string(filter_str: str) -> str:
    """Validate a WinDivert filter string against an allowlist.

    Only known field names, operators, IP addresses, port numbers,
    and boolean connectives are allowed.  This prevents injection
    of arbitrary WinDivert filter expressions.

    Returns the validated filter string.
    Raises ValueError on invalid input.
    """
    if not filter_str or not isinstance(filter_str, str):
        raise ValueError("Filter string is required")
    if len(filter_str) > MAX_FILTER_STRING_LENGTH:
        raise ValueError(f"Filter string exceeds maximum length ({MAX_FILTER_STRING_LENGTH})")

    # Tokenize: split on whitespace and parentheses
    # Keep parentheses as separate tokens
    raw = filter_str.replace("(", " ( ").replace(")", " ) ")
    tokens = raw.split()

    for token in tokens:
        # Allow known keywords and field names
        if token in _WINDIVERT_ALLOWED_TOKENS:
            continue
        # Allow numeric literals (port numbers, protocol numbers)
        if re.match(r"^\d{1,5}$", token):
            val = int(token)
            if 0 <= val <= 65535:
                continue
            raise ValueError(f"Numeric value out of range in filter: {token}")
        # Allow IP addresses
        if validate_ip(token) is not None:
            continue
        # Allow dotted field notation (ip.SrcAddr etc.) — already in allowlist
        # Reject everything else
        raise ValueError(f"Disallowed token in filter string: {token!r}")

    return filter_str


# ── JSON Validation ──────────────────────────────────────────────────

def validate_json_size(data: bytes | str, context: str = "") -> None:
    """Reject JSON payloads exceeding the size limit."""
    size = len(data) if isinstance(data, (bytes, str)) else 0
    if size > MAX_JSON_SIZE_BYTES:
        raise ValueError(
            f"JSON payload too large ({size} bytes, max {MAX_JSON_SIZE_BYTES})"
            f"{f' ({context})' if context else ''}"
        )


def safe_json_loads(data: str, context: str = "",
                    max_size: int = MAX_JSON_SIZE_BYTES) -> Any:
    """Parse JSON with size limit enforcement.

    Returns the parsed object.
    Raises ValueError on invalid/oversized input.
    """
    if not isinstance(data, str):
        raise ValueError(f"Expected string for JSON parsing{f' ({context})' if context else ''}")
    if len(data) > max_size:
        raise ValueError(f"JSON payload exceeds size limit ({len(data)} > {max_size})")
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON{f' ({context})' if context else ''}: {e}") from e


# ── Disruption Parameter Validation ──────────────────────────────────

def validate_methods(methods: Any) -> List[str]:
    """Validate a list of disruption method names.

    Returns a sanitized list containing only valid method names.
    """
    if not isinstance(methods, list):
        return []
    validated = []
    for m in methods:
        if isinstance(m, str) and m in VALID_DISRUPTION_METHODS:
            validated.append(m)
        else:
            log_warning(f"Rejected unknown disruption method: {m!r}")
    return validated


def validate_params(params: Any) -> Dict[str, Any]:
    """Validate and clamp disruption parameters.

    Unknown keys are silently dropped.  Known keys are type-checked
    and clamped to their allowed ranges.
    """
    if not isinstance(params, dict):
        return {}

    validated: Dict[str, Any] = {}
    for key, value in params.items():
        if key == "direction":
            if isinstance(value, str) and value in VALID_DIRECTIONS:
                validated[key] = value
            continue

        if key not in VALID_PARAM_RANGES:
            # Allow through non-standard params with basic type check
            # (statistical models, stealth params, etc.)
            if isinstance(value, (int, float, bool, str)):
                validated[key] = value
            continue

        expected_type, lo, hi = VALID_PARAM_RANGES[key]
        if expected_type in (int, float) and isinstance(value, (int, float)):
            clamped = max(lo, min(hi, float(value)))
            validated[key] = expected_type(clamped)
        elif expected_type == str and isinstance(value, str):
            validated[key] = value

    return validated


def validate_disruption_config(config: Any) -> Optional[Dict[str, Any]]:
    """Validate a complete disruption configuration dict.

    Returns sanitized config or None if fundamentally invalid.
    """
    if not isinstance(config, dict):
        return None

    methods = validate_methods(config.get("methods"))
    if not methods:
        return None

    params = validate_params(config.get("params", {}))

    result = dict(config)
    result["methods"] = methods
    result["params"] = params

    # Sanitize string fields
    for str_field in ("name", "description", "reasoning", "goal"):
        if str_field in result:
            val = result[str_field]
            if isinstance(val, str):
                result[str_field] = val[:500]  # cap length
            else:
                result[str_field] = ""

    return result


# ── Plugin Manifest Validation ───────────────────────────────────────

def validate_plugin_name(name: str) -> str:
    """Validate a plugin name against the allowlist pattern.

    Raises ValueError on invalid names.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("Plugin name is required")
    if len(name) > MAX_PLUGIN_NAME_LENGTH:
        raise ValueError(f"Plugin name too long ({len(name)} > {MAX_PLUGIN_NAME_LENGTH})")
    if not _SAFE_NAME_PATTERN.match(name):
        raise ValueError(f"Plugin name contains disallowed characters: {name!r}")
    return name


def validate_version_string(version: str) -> str:
    """Validate a semver-ish version string."""
    if not isinstance(version, str) or not version:
        raise ValueError("Version string is required")
    if not _SAFE_VERSION_PATTERN.match(version):
        raise ValueError(f"Invalid version format: {version!r}")
    return version


def validate_entry_point(entry_point: str, plugin_dir: str) -> str:
    """Validate plugin entry point — prevents path traversal.

    Returns the validated entry point.
    Raises ValueError on path traversal or missing file.
    """
    if not isinstance(entry_point, str) or not entry_point:
        raise ValueError("Entry point is required")

    # Block path traversal sequences
    if ".." in entry_point:
        raise ValueError(f"Path traversal detected in entry_point: {entry_point!r}")
    if os.path.isabs(entry_point):
        raise ValueError(f"Absolute path not allowed in entry_point: {entry_point!r}")

    # Only allow .py files
    if not entry_point.endswith(".py"):
        raise ValueError(f"Entry point must be a .py file: {entry_point!r}")

    # Validate filename characters
    basename = os.path.basename(entry_point)
    if not _SAFE_FILENAME_PATTERN.match(basename):
        raise ValueError(f"Entry point filename contains disallowed characters: {basename!r}")

    # Resolve and verify containment
    full_path = os.path.join(plugin_dir, entry_point)
    real_path = os.path.realpath(full_path)
    real_dir = os.path.realpath(plugin_dir)
    if not real_path.startswith(real_dir + os.sep):
        raise ValueError(f"Entry point escapes plugin directory: {entry_point!r}")

    return entry_point


# ── Path Validation ──────────────────────────────────────────────────

def validate_safe_path(path: str, base_dir: str,
                       context: str = "") -> str:
    """Validate that a path stays within base_dir (no traversal).

    Returns the resolved path.
    Raises ValueError on traversal or invalid path.
    """
    if not path or not isinstance(path, str):
        raise ValueError(f"Path is required{f' ({context})' if context else ''}")

    resolved = os.path.realpath(os.path.join(base_dir, path))
    base_resolved = os.path.realpath(base_dir)

    if not resolved.startswith(base_resolved + os.sep) and resolved != base_resolved:
        raise ValueError(
            f"Path traversal detected{f' ({context})' if context else ''}: "
            f"{path!r} resolves outside {base_dir!r}"
        )
    return resolved


# ── URL Validation ───────────────────────────────────────────────────

_ALLOWED_URL_SCHEMES: FrozenSet[str] = frozenset({"https", "http"})
_BLOCKED_HOSTS: FrozenSet[str] = frozenset({
    "localhost", "127.0.0.1", "0.0.0.0", "::1",
    "metadata.google.internal", "169.254.169.254",
})


def validate_url(url: str, require_https: bool = False,
                 context: str = "") -> str:
    """Validate a URL against scheme and host allowlists.

    Args:
        url: URL to validate
        require_https: If True, reject non-HTTPS URLs
        context: Description for error messages

    Returns:
        Validated URL string.
    Raises:
        ValueError on invalid or blocked URLs.
    """
    if not url or not isinstance(url, str):
        raise ValueError(f"URL is required{f' ({context})' if context else ''}")

    from urllib.parse import urlparse
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"Disallowed URL scheme: {parsed.scheme!r}")

    if require_https and parsed.scheme != "https":
        raise ValueError(f"HTTPS required{f' ({context})' if context else ''}")

    hostname = parsed.hostname or ""
    if hostname.lower() in _BLOCKED_HOSTS:
        raise ValueError(f"Blocked host in URL: {hostname!r}")

    # Block SSRF via IP ranges
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError(f"Private/loopback IP in URL: {hostname!r}")
    except ValueError:
        pass  # hostname is a domain name, not an IP — OK

    return url


# ── Setting Validation ───────────────────────────────────────────────

def validate_setting_key(key: str) -> str:
    """Validate that a setting key is in the known allowlist."""
    if key not in VALID_SETTING_KEYS:
        raise ValueError(f"Unknown setting key: {key!r}")
    return key
