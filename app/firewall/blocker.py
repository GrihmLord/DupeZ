# app/firewall/blocker.py

import subprocess
import platform
import ctypes
from .win_divert import start_divert, stop_divert
from .network_disruptor import network_disruptor
from .netcut_blocker import netcut_blocker
from typing import Dict
from app.logs.logger import log_info, log_error

_active_ip = None
_using_divert = False
_blocked_ips = set()  # Track multiple blocked IPs

def is_admin():
    if platform.system() == "Windows":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False
    return False

def initialize_network_disruptor():
    """Initialize the network disruptor system"""
    try:
        if network_disruptor.initialize():
            network_disruptor.start()
            log_info("✅ Network Disruptor initialized successfully")
            return True
        else:
            log_error("❌ Failed to initialize Network Disruptor")
            return False
    except Exception as e:
        log_error(f"Error initializing Network Disruptor: {e}")
        return False

def is_blocking():
    return _active_ip is not None

def is_ip_blocked(ip: str):
    """Check if a specific IP is currently blocked"""
    return ip in _blocked_ips or ip in network_disruptor.get_disrupted_devices()

def block_ip(ip: str):
    global _active_ip, _using_divert
    _active_ip = ip
    _using_divert = False

    if platform.system() == "Windows" and is_admin():
        try:
            # Try Windows Firewall first with silent execution
            result = subprocess.run([
                "netsh", "advfirewall", "firewall", "add", "rule",
                "name=PulseDropBlock", f"dir=out", f"action=block",
                f"remoteip={ip}", "enable=yes"
            ], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                _blocked_ips.add(ip)
                log_info(f"🔒 Blocked {ip} using Windows Firewall")
                return True
            else:
                log_error(f"Windows Firewall block failed: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            log_error(f"Windows Firewall block timeout for {ip}")
            return False
        except Exception as e:
            log_error(f"Windows Firewall block error: {e}")
            # Fallback to WinDivert
            start_divert(ip)
            _using_divert = True
            _blocked_ips.add(ip)
            return True
    else:
        # On non-Windows or no admin, use WinDivert
        start_divert(ip)
        _using_divert = True
        _blocked_ips.add(ip)
        return True

def unblock_ip():
    global _active_ip, _using_divert

    if _active_ip:
        if _using_divert:
            stop_divert()
        else:
            try:
                result = subprocess.run([
                    "netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=PulseDropBlock"
                ], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    log_info(f"🔓 Unblocked {_active_ip} using Windows Firewall")
                else:
                    log_error(f"Windows Firewall unblock failed: {result.stderr}")
            except subprocess.TimeoutExpired:
                log_error(f"Windows Firewall unblock timeout for {_active_ip}")
            except Exception as e:
                log_error(f"Windows Firewall unblock error: {e}")

    _active_ip = None
    _using_divert = False

def block_device(ip: str):
    """Block a device using NetCut-style methods for REAL disconnection"""
    try:
        log_info(f"🚫 NetCut-style blocking device: {ip}")
        
        # Add to blocked IPs set
        _blocked_ips.add(ip)
        log_info(f"📝 Added {ip} to blocked IPs set")
        
        # Initialize NetCut blocker if not already done
        if not netcut_blocker.running:
            log_info(f"🔧 Initializing NetCut blocker...")
            if netcut_blocker.initialize():
                netcut_blocker.start()
                log_info(f"✅ NetCut blocker initialized and started")
            else:
                log_error(f"❌ Failed to initialize NetCut blocker")
        
        # Use NetCut-style blocking (primary method)
        if netcut_blocker.running:
            success = netcut_blocker.block_device(ip)
            if success:
                log_info(f"🎯 NetCut-style blocking successful for {ip}")
                return True
            else:
                log_error(f"❌ NetCut blocking failed for {ip}")
        
        # Fallback to network disruptor
        log_info(f"🔄 Falling back to network disruptor for {ip}")
        if not network_disruptor.is_running:
            if network_disruptor.initialize():
                network_disruptor.start()
                log_info(f"✅ Network disruptor initialized")
        
        if network_disruptor.is_running:
            success = network_disruptor.disconnect_device(ip)
            if success:
                log_info(f"🎯 Network disruptor blocking successful for {ip}")
                return True
            else:
                log_error(f"❌ Network disruptor blocking failed for {ip}")
        
        # Final fallback to basic methods
        log_info(f"🔄 Using basic fallback methods for {ip}")
        success_count = 0
        
        # Windows Firewall fallback
        if platform.system() == "Windows":
            try:
                result = subprocess.run([
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name=NetCutBlock_{ip}", "dir=out", "action=block", f"remoteip={ip}"
                ], capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    success_count += 1
                    log_info(f"✅ Windows Firewall blocking for {ip}")
            except Exception as e:
                log_error(f"❌ Windows Firewall failed: {e}")
        
        # WinDivert fallback
        try:
            start_divert(ip)
            success_count += 1
            log_info(f"✅ WinDivert blocking for {ip}")
        except Exception as e:
            log_error(f"❌ WinDivert failed: {e}")
        
        if success_count > 0:
            log_info(f"🎯 Basic blocking successful for {ip}")
            return True
        else:
            log_error(f"❌ All blocking methods failed for {ip}")
            return False
            
    except Exception as e:
        log_error(f"Error blocking device {ip}: {e}")
        return False

def unblock_device(ip: str):
    """Unblock a device using NetCut-style methods"""
    try:
        log_info(f"🔓 NetCut-style unblocking device: {ip}")
        
        global _blocked_ips
        if ip in _blocked_ips:
            _blocked_ips.remove(ip)
            log_info(f"📝 Removed {ip} from blocked IPs set")
        
        success_count = 0
        
        # Use NetCut-style unblocking (primary method)
        if netcut_blocker.running:
            success = netcut_blocker.unblock_device(ip)
            if success:
                log_info(f"🎯 NetCut-style unblocking successful for {ip}")
                success_count += 1
            else:
                log_error(f"❌ NetCut unblocking failed for {ip}")
        
        # Fallback to network disruptor
        if network_disruptor.is_running:
            success = network_disruptor.reconnect_device(ip)
            if success:
                log_info(f"🎯 Network disruptor unblocking successful for {ip}")
                success_count += 1
            else:
                log_error(f"❌ Network disruptor unblocking failed for {ip}")
        
        # Basic fallback methods
        log_info(f"🔄 Using basic fallback unblocking methods for {ip}")
        
        # Remove Windows Firewall rules
        if platform.system() == "Windows":
            try:
                result = subprocess.run([
                    "netsh", "advfirewall", "firewall", "delete", "rule", f"name=NetCutBlock_{ip}"
                ], capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    success_count += 1
                    log_info(f"✅ Windows Firewall rule removed for {ip}")
            except Exception as e:
                log_error(f"❌ Windows Firewall removal failed: {e}")
        
        # Remove route blocking
        try:
            result = subprocess.run([
                "route", "delete", ip
            ], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                success_count += 1
                log_info(f"✅ Route blocking removed for {ip}")
        except Exception as e:
            log_error(f"❌ Route removal failed: {e}")
        
        # Stop WinDivert
        try:
            stop_divert(ip)
            success_count += 1
            log_info(f"✅ WinDivert unblocking for {ip}")
        except Exception as e:
            log_error(f"❌ WinDivert unblocking failed: {e}")
        
        if success_count > 0:
            log_info(f"🎯 Successfully unblocked {ip} using {success_count} methods")
            return True
        else:
            log_error(f"❌ All unblocking methods failed for {ip}")
            return False
            
    except Exception as e:
        log_error(f"Error unblocking device {ip}: {e}")
        return False


def get_blocked_ips():
    """Get list of currently blocked IPs"""
    basic_blocked = list(_blocked_ips)
    disrupted = network_disruptor.get_disrupted_devices()
    netcut_blocked = netcut_blocker.get_blocked_devices()
    return list(set(basic_blocked + disrupted + netcut_blocked))

def clear_all_blocks():
    """Clear all blocked IPs and disruptions"""
    global _active_ip, _using_divert, _blocked_ips
    try:
        # Clear NetCut blocker
        if netcut_blocker.running:
            netcut_blocker.stop()
            log_info("✅ NetCut blocker cleared")
        
        # Clear network disruptor
        if network_disruptor.is_running:
            network_disruptor.clear_all_disruptions()
            log_info("✅ Network disruptor cleared")
        
        # Clear basic blocking
        if _using_divert:
            stop_divert()
            log_info("✅ WinDivert cleared")
        else:
            # Remove all Windows Firewall rules with silent execution
            for ip in _blocked_ips:
                try:
                    result = subprocess.run([
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        "name=NetCutBlock"
                    ], capture_output=True, text=True, timeout=5)
                    if result.returncode != 0:
                        log_error(f"Failed to remove firewall rule for {ip}")
                except subprocess.TimeoutExpired:
                    log_error(f"Timeout removing firewall rule for {ip}")
                except Exception as e:
                    log_error(f"Error removing firewall rule for {ip}: {e}")
        
        _active_ip = None
        _using_divert = False
        _blocked_ips.clear()
        log_info("✅ All blocking systems cleared")
        return True
    except Exception as e:
        log_error(f"Error clearing all blocks: {e}")
        return False

def get_blocking_status() -> Dict[str, any]:
    """Get comprehensive blocking status"""
    return {
        "blocked_ips": list(_blocked_ips),
        "disrupted_devices": network_disruptor.get_disrupted_devices(),
        "active_ip": _active_ip,
        "using_divert": _using_divert,
        "network_disruptor_running": network_disruptor.is_running,
        "is_admin": is_admin(),
        "platform": platform.system()
    }

def get_device_disruption_status(ip: str) -> Dict:
    """Get detailed disruption status for a specific device"""
    return network_disruptor.get_device_status(ip)
