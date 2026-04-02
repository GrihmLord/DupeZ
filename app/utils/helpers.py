# app/utils/helpers.py

import os
import sys
import platform
import subprocess
import socket
import psutil
from typing import Dict, List, Optional, Tuple

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
        
        # Get memory info
        memory = psutil.virtual_memory()
        info["memory"] = {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent
        }
        
        # Get disk info
        disk = psutil.disk_usage('/')
        info["disk"] = {
            "total": disk.total,
            "free": disk.free,
            "percent": disk.percent
        }
        
        return info
    except Exception as e:
        print(f"Failed to get system info: {e}")
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
        print(f"Failed to get network interfaces: {e}")
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
                capture_output=True, text=True, timeout=timeout + 1
            )
        else:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)), host],
                capture_output=True, text=True, timeout=timeout + 1
            )
        
        if result.returncode == 0:
            # Extract response time from output
            import re
            time_match = re.search(r'time[=<](\d+(?:\.\d+)?)', result.stdout)
            response_time = float(time_match.group(1)) if time_match else 0.0
            return True, response_time
        else:
            return False, 0.0
    except Exception as e:
        print(f"Ping failed for {host}: {e}")
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
        print(f"Failed to get process info for PID {pid}: {e}")
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
        print(f"Failed to get network connections: {e}")
        return []

def validate_ip_address(ip: str) -> bool:
    """Validate IP address format"""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        for part in parts:
            if not part.isdigit() or not 0 <= int(part) <= 255:
                return False
        return True
    except Exception:
        return False

def validate_mac_address(mac: str) -> bool:
    """Validate MAC address format"""
    import re
    pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
    return bool(re.match(pattern, mac))

def get_file_size(file_path: str) -> int:
    """Get file size in bytes"""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0

def ensure_directory(path: str) -> bool:
    """Ensure directory exists, create if it doesn't"""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        print(f"Failed to create directory {path}: {e}")
        return False

def get_application_path() -> str:
    """Get the application's base directory"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_resource_path(relative_path: str) -> str:
    """Get absolute path for a resource file"""
    base_path = get_application_path()
    return os.path.join(base_path, relative_path)

def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is open on a host"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
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
    Convert emoji and Unicode characters to console-safe text for Windows
    This prevents UnicodeEncodeError when logging to console
    """
    if platform.system() == "Windows":
        # Replace common emojis with text equivalents
        emoji_replacements = {
            "🧹": "[CLEAN]",
            "✅": "[SUCCESS]",
            "🛑": "[STOP]",
            "🚀": "[START]",
            "📊": "[STATS]",
            "🔍": "[SEARCH]",
            "⚡": "[POWER]",
            "🐛": "[DEBUG]",
            "💾": "[SAVE]",
            "🌐": "[NETWORK]",
            "🖥️": "[SYSTEM]",
            "💿": "[DISK]",
            "📱": "[DEVICE]",
            "🔒": "[SECURITY]",
            "⚠️": "[WARNING]",
            "❌": "[ERROR]",
            "ℹ️": "[INFO]",
            "🎯": "[TARGET]",
            "🔄": "[REFRESH]",
            "⏱️": "[TIMER]",
            "🛡️": "[SHIELD]",
            "🚨": "[ALERT]",
            "🎮": "[GAMING]",
            "🔧": "[TOOLS]",
            "📈": "[CHART]",
            "🎪": "[CIRCUS]",
            "🏆": "[TROPHY]",
            "💡": "[IDEA]",
            "🔮": "[MAGIC]",
            "🎭": "[THEATER]",
            "🎨": "[ART]",
            "🎵": "[MUSIC]",
            "🎬": "[MOVIE]",
            "🎲": "[DICE]",
            "🎸": "[GUITAR]",
            "🎹": "[PIANO]",
            "🎺": "[TRUMPET]",
            "🎻": "[VIOLIN]",
            "🥁": "[DRUM]",
            "🎤": "[MICROPHONE]",
            "🎧": "[HEADPHONES]",
            "📺": "[TV]",
            "📻": "[RADIO]",
            "📱": "[PHONE]",
            "💻": "[LAPTOP]",
            "⌨️": "[KEYBOARD]",
            "🖱️": "[MOUSE]",
            "🖨️": "[PRINTER]",
            "📷": "[CAMERA]",
            "🎥": "[VIDEO]",
            "📹": "[CAMCORDER]",
            "📼": "[TAPE]",
            "💿": "[CD]",
            "📀": "[DVD]",
            "💾": "[FLOPPY]",
            "🗜️": "[COMPRESS]",
            "📁": "[FOLDER]",
            "📂": "[OPEN_FOLDER]",
            "🗂️": "[CARD_INDEX]",
            "📅": "[CALENDAR]",
            "📆": "[TEAR_CALENDAR]",
            "🗓️": "[SPIRAL_CALENDAR]",
            "📇": "[CARD_INDEX]",
            "🗃️": "[CARD_BOX]",
            "📋": "[CLIPBOARD]",
            "📌": "[PUSHPIN]",
            "📍": "[ROUND_PUSHPIN]",
            "🎯": "[BULLSEYE]",
            "🎪": "[CIRCUS_TENT]",
            "🎨": "[ARTIST_PALETTE]",
            "🎭": "[PERFORMING_ARTS]",
            "🎬": "[CLAPPER_BOARD]",
            "🎤": "[MICROPHONE]",
            "🎧": "[HEADPHONE]",
            "🎼": "[MUSICAL_SCORE]",
            "🎹": "[MUSICAL_KEYBOARD]",
            "🎸": "[GUITAR]",
            "🎺": "[TRUMPET]",
            "🎻": "[VIOLIN]",
            "🥁": "[DRUM]",
            "🎷": "[SAXOPHONE]",
            "📺": "[TELEVISION]",
            "📻": "[RADIO]",
            "📱": "[MOBILE_PHONE]",
            "💻": "[LAPTOP_COMPUTER]",
            "🖥️": "[DESKTOP_COMPUTER]",
            "⌨️": "[KEYBOARD]",
            "🖱️": "[COMPUTER_MOUSE]",
            "🖨️": "[PRINTER]",
            "📷": "[CAMERA]",
            "🎥": "[MOVIE_CAMERA]",
            "📹": "[VIDEOCASSETTE]",
            "📼": "[VIDEOCASSETTE]",
            "💿": "[OPTICAL_DISC]",
            "📀": "[DVD]",
            "💾": "[FLOPPY_DISK]",
            "🗜️": "[COMPRESSION]",
            "📁": "[FILE_FOLDER]",
            "📂": "[OPEN_FILE_FOLDER]",
            "🗂️": "[CARD_INDEX_DIVIDERS]",
            "📅": "[TEAR_OFF_CALENDAR]",
            "📆": "[SPIRAL_CALENDAR]",
            "🗓️": "[SPIRAL_CALENDAR]",
            "📇": "[CARD_INDEX]",
            "🗃️": "[CARD_FILE_BOX]",
            "📋": "[CLIPBOARD]",
            "📌": "[PUSHPIN]",
            "📍": "[ROUND_PUSHPIN]",
            # Add more emojis that appear in the logs
            "🚀": "[ROCKET]",
            "🎯": "[TARGET]",
            "⏱️": "[TIMER]",
            "🚨": "[ALERT]",
            "🎮": "[GAMING]",
            "🔧": "[TOOLS]",
            "📈": "[CHART]",
            "🎪": "[CIRCUS]",
            "🏆": "[TROPHY]",
            "💡": "[IDEA]",
            "🔮": "[MAGIC]",
            "🎭": "[THEATER]",
            "🎨": "[ART]",
            "🎵": "[MUSIC]",
            "🎬": "[MOVIE]",
            "🎲": "[DICE]",
            "🎸": "[GUITAR]",
            "🎹": "[PIANO]",
            "🎺": "[TRUMPET]",
            "🎻": "[VIOLIN]",
            "🥁": "[DRUM]",
            "🎷": "[SAXOPHONE]",
            "🎤": "[MICROPHONE]",
            "🎧": "[HEADPHONE]",
            "📺": "[TELEVISION]",
            "📻": "[RADIO]",
            "📱": "[MOBILE_PHONE]",
            "💻": "[LAPTOP_COMPUTER]",
            "🖥️": "[DESKTOP_COMPUTER]",
            "⌨️": "[KEYBOARD]",
            "🖱️": "[COMPUTER_MOUSE]",
            "🖨️": "[PRINTER]",
            "📷": "[CAMERA]",
            "🎥": "[MOVIE_CAMERA]",
            "📹": "[VIDEOCASSETTE]",
            "📼": "[VIDEOCASSETTE]",
            "💿": "[OPTICAL_DISC]",
            "📀": "[DVD]",
            "💾": "[FLOPPY_DISK]",
            "🗜️": "[COMPRESSION]",
            "📁": "[FILE_FOLDER]",
            "📂": "[OPEN_FILE_FOLDER]",
            "🗂️": "[CARD_INDEX_DIVIDERS]",
            "📅": "[TEAR_OFF_CALENDAR]",
            "📆": "[SPIRAL_CALENDAR]",
            "🗓️": "[SPIRAL_CALENDAR]",
            "📇": "[CARD_INDEX]",
            "🗃️": "[CARD_FILE_BOX]",
            "📋": "[CLIPBOARD]",
            "📌": "[PUSHPIN]",
            "📍": "[ROUND_PUSHPIN]"
        }
        
        for emoji, replacement in emoji_replacements.items():
            message = message.replace(emoji, replacement)
    
    return message
