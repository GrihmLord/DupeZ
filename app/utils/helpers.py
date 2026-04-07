# app/utils/helpers.py

import os
import re
import sys
import platform
import subprocess
import socket
import psutil
from typing import Dict, List, Optional, Tuple
def __log_error(msg):
    """Lazy import wrapper to break circular import with logger module."""
    from app.logs.logger import log_error as _le
    _le(msg)

# Suppress console window flash on Windows
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

def mask_ip(ip: str) -> str:
    """Mask the last octet of an IPv4 address for opsec in logs.
    '192.168.1.42' → '192.168.1.x'"""
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.x"
    return ip

def get_system_info() -> Dict:
    """Get comprehensive system information"""
    try:
        info = {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "architecture": platform.architecture()[0],
            "processor": platform.processor(),
            "hostname": platform.node(),
            "python_version": sys.version,
            "python_executable": sys.executable
        }

        memory = psutil.virtual_memory()
        info["memory"] = {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent
        }

        disk = psutil.disk_usage('/')
        info["disk"] = {
            "total": disk.total,
            "free": disk.free,
            "percent": disk.percent
        }

        return info
    except Exception as e:
        _log_error(f"Failed to get system info: {e}")
        return {}

def get_network_interfaces() -> List[Dict]:
    """Get list of network interfaces"""
    try:
        interfaces = []
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:  # IPv4
                    interfaces.append({
                        "name": interface,
                        "ip": addr.address,
                        "netmask": addr.netmask,
                        "broadcast": addr.broadcast
                    })
        return interfaces
    except Exception as e:
        _log_error(f"Failed to get network interfaces: {e}")
        return []

def is_admin() -> bool:
    """Check if running with administrator privileges"""
    try:
        if platform.system() == "Windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except Exception:
        return False

def format_bytes(bytes_value: int) -> str:
    """Format bytes into human readable string"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"

def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable string"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"

def ping_host(host: str, timeout: float = 1.0) -> Tuple[bool, float]:
    """Ping a host and return success status and response time"""
    try:
        if platform.system().lower() == "windows":
            result = subprocess.run(
                ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host],
                capture_output=True, text=True, timeout=timeout + 1,
                creationflags=_NO_WINDOW
            )
        else:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)), host],
                capture_output=True, text=True, timeout=timeout + 1
            )

        if result.returncode == 0:
            time_match = re.search(r'time[=<](\d+(?:\.\d+)?)', result.stdout)
            response_time = float(time_match.group(1)) if time_match else 0.0
            return True, response_time
        else:
            return False, 0.0
    except Exception as e:
        _log_error(f"Ping failed for {host}: {e}")
        return False, 0.0

def get_process_info(pid: int) -> Optional[Dict]:
    """Get information about a process"""
    try:
        process = psutil.Process(pid)
        return {
            "pid": pid,
            "name": process.name(),
            "cmdline": process.cmdline(),
            "cpu_percent": process.cpu_percent(),
            "memory_percent": process.memory_percent(),
            "status": process.status(),
            "create_time": process.create_time()
        }
    except psutil.NoSuchProcess:
        return None
    except Exception as e:
        _log_error(f"Failed to get process info for PID {pid}: {e}")
        return None

def get_network_connections() -> List[Dict]:
    """Get active network connections"""
    try:
        connections = []
        for conn in psutil.net_connections():
            if conn.status == 'ESTABLISHED':
                connections.append({
                    "local_address": f"{conn.laddr.ip}:{conn.laddr.port}",
                    "remote_address": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                    "status": conn.status,
                    "pid": conn.pid
                })
        return connections
    except Exception as e:
        _log_error(f"Failed to get network connections: {e}")
        return []

def validate_ip_address(ip: str) -> bool:
    """Validate IP address format"""
    try:
        socket.inet_aton(ip)
        return ip.count('.') == 3  # reject shorthand like "127.1"
    except (OSError, TypeError):
        return False

def validate_mac_address(mac: str) -> bool:
    """Validate MAC address format"""
    pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
    return bool(re.match(pattern, mac))

def get_file_size(file_path: str) -> int:
    """Get file size in bytes"""
    try: return os.path.getsize(file_path)
    except OSError: return 0

def ensure_directory(path: str) -> bool:
    """Ensure directory exists, create if it doesn't"""
    try: os.makedirs(path, exist_ok=True); return True
    except Exception as e: _log_error(f"Failed to create directory {path}: {e}"); return False

def get_application_path() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_resource_path(relative_path: str) -> str:
    return os.path.join(get_application_path(), relative_path)

def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is open on a host."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, port)) == 0
    except Exception:
        return False

def get_common_ports() -> Dict[str, int]:
    """Get dictionary of common service ports"""
    return {
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
        "Redis": 6379
    }

def safe_console_message(message: str) -> str:
    """
    Convert emoji and Unicode characters to console-safe text for Windows.
    Uses encode/decode with 'replace' which handles ALL non-ASCII characters
    in one pass — no need to enumerate every possible emoji.
    """
    if platform.system() == "Windows":
        try:
            # Try encoding to the console's code page; replace failures with '?'
            return message.encode('ascii', errors='replace').decode('ascii')
        except Exception:
            pass
    return message

