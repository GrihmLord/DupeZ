# app/firewall/blocker.py

import subprocess
import platform
import ctypes
from .win_divert import start_divert, stop_divert

_active_ip = None
_using_divert = False

def is_admin():
    if platform.system() == "Windows":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False
    return False

def is_blocking():
    return _active_ip is not None

def block_ip(ip: str):
    global _active_ip, _using_divert
    _active_ip = ip
    _using_divert = False

    if platform.system() == "Windows" and is_admin():
        try:
            # Try Windows Firewall first
            subprocess.run([
                "netsh", "advfirewall", "firewall", "add", "rule",
                "name=PulseDropBlock", f"dir=out", f"action=block",
                f"remoteip={ip}", "enable=yes"
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            # Fallback to WinDivert
            start_divert(ip)
            _using_divert = True
    else:
        # On non-Windows or no admin, use WinDivert
        start_divert(ip)
        _using_divert = True

def unblock_ip():
    global _active_ip, _using_divert

    if _active_ip:
        if _using_divert:
            stop_divert()
        else:
            try:
                subprocess.run([
                    "netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=PulseDropBlock"
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                pass

    _active_ip = None
    _using_divert = False
