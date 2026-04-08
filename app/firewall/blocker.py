#!/usr/bin/env python3
"""
Firewall Blocker Module

Manages Windows netsh advfirewall rules for per-IP blocking.
All DupeZ rules use the naming convention ``DupeZBlock_<ip>_(In|Out)``
so they can be enumerated and cleaned up reliably.
"""

import subprocess
import threading
import time
from typing import Dict, List

from app.logs.logger import log_error, log_info, log_warning
from app.utils.helpers import _NO_WINDOW, is_admin


# ── netsh helper ──────────────────────────────────────────────────────

def _netsh(*args: str, timeout: int = 3) -> bool:
    """Run a ``netsh advfirewall firewall`` command.

    Returns True only when the process exits with code 0.
    """
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", *args],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log_warning(f"netsh timed out after {timeout}s: {' '.join(args[:3])}")
        return False
    except Exception as e:
        log_error(f"netsh execution error: {e}")
        return False


# ── Throttled log helper ──────────────────────────────────────────────

_throttle_last: float = 0.0


def _throttled_log(msg: str) -> None:
    """Log *msg* at most every 2 seconds to reduce spam during rapid ops."""
    global _throttle_last
    now = time.time()
    if now - _throttle_last > 2.0:
        log_info(msg)
        _throttle_last = now


# ── Rule name helper ──────────────────────────────────────────────────

def _rule_base(ip: str) -> str:
    """Return the base rule name for an IP, e.g. ``DupeZBlock_192_168_1_5``."""
    return f"DupeZBlock_{ip.replace('.', '_')}"


# ── Public API — block / unblock / query ──────────────────────────────

def block_device(ip: str, block: bool = True) -> bool:
    """Block or unblock a device via Windows netsh firewall rules.

    Creates paired inbound + outbound rules when *block* is True,
    deletes them when False.  Returns True on success.
    """
    try:
        if not is_admin():
            log_error("Firewall blocking requires administrator privileges")
            return False

        import platform
        if platform.system() != "Windows":
            log_error("Firewall blocking is only implemented for Windows")
            return False

        base = _rule_base(ip)

        if block:
            ok = (
                _netsh("add", "rule", f"name={base}_In", "dir=in",
                       "action=block", f"remoteip={ip}", "enable=yes")
                and _netsh("add", "rule", f"name={base}_Out", "dir=out",
                           "action=block", f"remoteip={ip}", "enable=yes")
            )
            if ok:
                _throttled_log(f"Blocked device: {ip} (TEMPORARY)")
            else:
                log_error(f"Failed to create firewall rules for {ip}")
            return ok
        else:
            ok = (
                _netsh("delete", "rule", f"name={base}_In")
                and _netsh("delete", "rule", f"name={base}_Out")
            )
            if ok:
                _throttled_log(f"Unblocked device: {ip}")
            else:
                log_error(f"Failed to delete firewall rules for {ip}")
            return ok

    except Exception as e:
        log_error(f"Error blocking device {ip}: {e}", exception=e)
        return False


def unblock_device(ip: str) -> bool:
    """Remove firewall block rules for *ip*."""
    return block_device(ip, block=False)


def is_ip_blocked(ip: str) -> bool:
    """Return True if a DupeZ inbound block rule exists for *ip*."""
    try:
        import platform
        if platform.system() != "Windows":
            return False

        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             f"name={_rule_base(ip)}_In"],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        return "No rules match the specified criteria" not in result.stdout
    except Exception:
        return False


def clear_all_dupez_blocks() -> bool:
    """Delete every DupeZ firewall rule.

    ``netsh`` does NOT support wildcards in the ``name=`` parameter, so
    we enumerate all rules first and delete each by exact name.
    """
    try:
        if not is_admin():
            log_error("Clearing firewall blocks requires administrator privileges")
            return False

        import platform
        if platform.system() != "Windows":
            log_error("Firewall clearing is only implemented for Windows")
            return False

        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=all"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )

        rule_names: List[str] = []
        for line in result.stdout.splitlines():
            if "Rule Name:" in line and "DupeZBlock" in line:
                name = line.split("Rule Name:")[1].strip()
                rule_names.append(name)

        if not rule_names:
            log_info("No DupeZ firewall blocks to clear")
            return True

        deleted = sum(1 for name in rule_names if _netsh("delete", "rule", f"name={name}"))
        log_info(f"Cleared {deleted}/{len(rule_names)} DupeZ firewall blocks")
        return True

    except subprocess.TimeoutExpired:
        log_error("Timeout enumerating firewall rules for cleanup")
        return False
    except Exception as e:
        log_error(f"Error clearing firewall blocks: {e}", exception=e)
        return False


def get_blocked_ips() -> List[str]:
    """Return a list of IPs currently blocked by DupeZ rules.

    Enumerates all firewall rules (netsh does not support wildcards)
    and extracts IPs from inbound DupeZBlock rule names.
    """
    try:
        import platform
        if platform.system() != "Windows":
            return []

        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=all"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )

        blocked_ips: List[str] = []
        for line in result.stdout.splitlines():
            if "Rule Name:" in line and "DupeZBlock" in line and "_In" in line:
                rule_name = line.split("Rule Name:")[1].strip()
                ip = (rule_name
                      .replace("DupeZBlock_", "")
                      .replace("_In", "")
                      .replace("_", "."))
                blocked_ips.append(ip)

        return blocked_ips
    except Exception as e:
        log_error(f"Error getting blocked IPs: {e}", exception=e)
        return []


# ── Backwards-compatibility aliases ───────────────────────────────────

block_ip = block_device
unblock_ip = unblock_device
is_blocking = is_ip_blocked


# ── NetworkBlocker class (test-compat wrapper) ────────────────────────

class NetworkBlocker:
    """Stateful wrapper around the module-level blocking functions.

    Keeps a local set of blocked IPs for fast lookup and exposes a
    status dict.  Thread-safe via an internal lock.
    """

    def __init__(self) -> None:
        self._blocked_ips: set[str] = set()
        self._lock = threading.Lock()
        self.is_active: bool = False

    def block_ip(self, ip: str) -> bool:
        """Block *ip* and track it locally."""
        try:
            success = block_device(ip, block=True)
            if success:
                with self._lock:
                    self._blocked_ips.add(ip)
                    self.is_active = True
                log_info(f"NetworkBlocker blocked IP: {ip}")
            return success
        except Exception as e:
            log_error(f"NetworkBlocker block error: {e}", exception=e)
            return False

    def unblock_ip(self, ip: str) -> bool:
        """Unblock *ip* and remove from local tracking."""
        try:
            success = block_device(ip, block=False)
            if success:
                with self._lock:
                    self._blocked_ips.discard(ip)
                    self.is_active = bool(self._blocked_ips)
                log_info(f"NetworkBlocker unblocked IP: {ip}")
            return success
        except Exception as e:
            log_error(f"NetworkBlocker unblock error: {e}", exception=e)
            return False

    def is_ip_blocked(self, ip: str) -> bool:
        """Check whether *ip* has a DupeZ firewall block rule."""
        try:
            return is_ip_blocked(ip)
        except Exception as e:
            log_error(f"NetworkBlocker check blocked error: {e}", exception=e)
            return False

    def get_blocked_ips(self) -> List[str]:
        """Return the locally-tracked blocked IP list."""
        with self._lock:
            return list(self._blocked_ips)

    def clear_all_blocks(self) -> bool:
        """Remove all DupeZ firewall rules and reset local state."""
        try:
            success = clear_all_dupez_blocks()
            if success:
                with self._lock:
                    self._blocked_ips.clear()
                    self.is_active = False
                log_info("NetworkBlocker cleared all blocks")
            return success
        except Exception as e:
            log_error(f"NetworkBlocker clear all error: {e}", exception=e)
            return False

    def get_active(self) -> bool:
        """Return whether any IPs are currently blocked."""
        return self.is_active

    def get_status(self) -> Dict:
        """Return a status snapshot."""
        with self._lock:
            return {
                "is_active": self.is_active,
                "blocked_ips": list(self._blocked_ips),
                "total_blocked": len(self._blocked_ips),
            }
