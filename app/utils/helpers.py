# app/utils/helpers.py

import os
import re
import sys
import platform
import subprocess
import socket
import psutil
from typing import Dict, List, Optional, Tuple


def _log_error(msg: str) -> None:
    """Lazy import wrapper to break circular import with logger module."""
    from app.logs.logger import log_error as _le
    _le(msg)


# Suppress console window flash on Windows subprocess calls
_NO_WINDOW: int = 0x08000000 if sys.platform == "win32" else 0

# Pre-compiled MAC address validation pattern
_MAC_ADDRESS_PATTERN: re.Pattern = re.compile(
    r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
)

# Ping response time extraction pattern
_PING_TIME_PATTERN: re.Pattern = re.compile(r'time[=<](\d+(?:\.\d+)?)')

# Well-known service ports (immutable — no reason to rebuild per call)
COMMON_PORTS: Dict[str, int] = {
    "HTTP": 80,
    "HTTPS": 443,
    "FTP": 21,
    "SSH": 22,
    "Telnet": 23,
    "SMTP": 25,
    "DNS": 53,
    "DHCP": 67,
    "HTTP-Alt": 8080,
    "MySQL": 3306,
    "PostgreSQL": 5432,
    "MongoDB": 27017,
    "Redis": 6379,
}

_BYTE_UNITS: Tuple[str, ...] = ('B', 'KB', 'MB', 'GB', 'TB', 'PB')


def mask_ip(ip: str) -> str:
    """Mask the last octet of an IPv4 address for opsec in logs.

    '192.168.1.42' -> '192.168.1.x'
    """
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.x"
    return ip


def is_admin() -> bool:
    """Check if the current process has administrator/root privileges."""
    try:
        if platform.system() == "Windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        return os.geteuid() == 0
    except Exception:
        return False


def get_system_info() -> Dict:
    """Collect platform, memory, and disk information."""
    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "architecture": platform.architecture()[0],
            "processor": platform.processor(),
            "hostname": platform.node(),
            "python_version": sys.version,
            "python_executable": sys.executable,
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "percent": memory.percent,
            },
            "disk": {
                "total": disk.total,
                "free": disk.free,
                "percent": disk.percent,
            },
        }
    except Exception as e:
        _log_error(f"Failed to get system info: {e}")
        return {}


def get_network_interfaces() -> List[Dict]:
    """Return all IPv4 network interfaces with address details."""
    try:
        interfaces = []
        for interface_name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    interfaces.append({
                        "name": interface_name,
                        "ip": addr.address,
                        "netmask": addr.netmask,
                        "broadcast": addr.broadcast,
                    })
        return interfaces
    except Exception as e:
        _log_error(f"Failed to get network interfaces: {e}")
        return []


def format_bytes(byte_count: int) -> str:
    """Format a byte count into a human-readable string (e.g. '2.4 GB')."""
    value = float(byte_count)
    for unit in _BYTE_UNITS:
        if value < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} {_BYTE_UNITS[-1]}"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to a compact human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def ping_host(host: str, timeout: float = 1.0) -> Tuple[bool, float]:
    """Ping a host and return (reachable, response_time_ms).

    Uses the system ping command. Returns (False, 0.0) on failure.
    """
    try:
        timeout_ms = str(int(timeout * 1000))
        if platform.system().lower() == "windows":
            cmd = ["ping", "-n", "1", "-w", timeout_ms, host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), host]

        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout + 1, creationflags=_NO_WINDOW,
        )

        if result.returncode == 0:
            time_match = _PING_TIME_PATTERN.search(result.stdout)
            response_time = float(time_match.group(1)) if time_match else 0.0
            return True, response_time
        return False, 0.0

    except Exception as e:
        _log_error(f"Ping failed for {host}: {e}")
        return False, 0.0


def get_process_info(pid: int) -> Optional[Dict]:
    """Return process metadata for a given PID, or None if not found."""
    try:
        process = psutil.Process(pid)
        return {
            "pid": pid,
            "name": process.name(),
            "cmdline": process.cmdline(),
            "cpu_percent": process.cpu_percent(),
            "memory_percent": process.memory_percent(),
            "status": process.status(),
            "create_time": process.create_time(),
        }
    except psutil.NoSuchProcess:
        return None
    except Exception as e:
        _log_error(f"Failed to get process info for PID {pid}: {e}")
        return None


def get_network_connections() -> List[Dict]:
    """Return all ESTABLISHED network connections."""
    try:
        connections = []
        for conn in psutil.net_connections():
            if conn.status == 'ESTABLISHED':
                connections.append({
                    "local_address": f"{conn.laddr.ip}:{conn.laddr.port}",
                    "remote_address": (
                        f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A"
                    ),
                    "status": conn.status,
                    "pid": conn.pid,
                })
        return connections
    except Exception as e:
        _log_error(f"Failed to get network connections: {e}")
        return []


def validate_ip_address(ip: str) -> bool:
    """Return True if ip is a valid dotted-quad IPv4 address."""
    try:
        socket.inet_aton(ip)
        return ip.count('.') == 3
    except (OSError, TypeError):
        return False


def validate_mac_address(mac: str) -> bool:
    """Return True if mac matches XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX."""
    return bool(_MAC_ADDRESS_PATTERN.match(mac))


def get_file_size(file_path: str) -> int:
    """Return file size in bytes, or 0 if the file does not exist."""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0


def ensure_directory(path: str) -> bool:
    """Create directory (and parents) if it does not exist. Return success."""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        _log_error(f"Failed to create directory {path}: {e}")
        return False


def get_application_path() -> str:
    """Return the app/ directory path."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path: str) -> str:
    """Resolve a path relative to the application root."""
    return os.path.join(get_application_path(), relative_path)


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, port)) == 0
    except Exception:
        return False


def get_common_ports() -> Dict[str, int]:
    """Return a copy of the well-known service port mapping."""
    return dict(COMMON_PORTS)


def safe_console_message(message: str) -> str:
    """Replace non-ASCII characters with '?' for safe Windows console output."""
    if platform.system() == "Windows":
        try:
            return message.encode('ascii', errors='replace').decode('ascii')
        except Exception:
            pass
    return message
