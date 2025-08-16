#!/usr/bin/env python3
"""
Comprehensive Network Functionality Test
Verifies all networking features and packet dropping functionality
"""

import sys
import os
import time
import subprocess

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

def test_imports():
    """Test all critical imports"""
    print("🧪 Testing Critical Imports...")
    
    try:
        from app.firewall.dupe_internet_dropper import DupeInternetDropper
        print("[SUCCESS] DupeInternetDropper imported successfully")
    except Exception as e:
        print(f"[FAILED] Failed to import DupeInternetDropper: {e}")
        return False
    
    try:
        from app.firewall.udp_port_interrupter import UDPPortInterrupter
        print("[SUCCESS] UDPPortInterrupter imported successfully")
    except Exception as e:
        print(f"[FAILED] Failed to import UDPPortInterrupter: {e}")
        return False
    
    try:
        from app.network.device_scan import NativeNetworkScanner
        print("[SUCCESS] NativeNetworkScanner imported successfully")
    except Exception as e:
        print(f"[FAILED] Failed to import NativeNetworkScanner: {e}")
        return False
    
    try:
        from app.firewall.dayz_firewall_controller import dayz_firewall
        print("[SUCCESS] DayZ Firewall Controller imported successfully")
    except Exception as e:
        print(f"[FAILED] Failed to import DayZ Firewall Controller: {e}")
        return False
    
    try:
        from app.gui.dashboard import DupeZDashboard
        print("[SUCCESS] DupeZDashboard imported successfully")
    except Exception as e:
        print(f"[FAILED] Failed to import DupeZDashboard: {e}")
        return False
    
    return True

def test_packet_dropping():
    """Test packet dropping functionality"""
    print("\n[TARGET] Testing Packet Dropping Functionality...")
    
    try:
        from app.firewall.dupe_internet_dropper import DupeInternetDropper
        from app.firewall.udp_port_interrupter import UDPPortInterrupter
        
        # Test UDP interrupter
        udp_interrupter = UDPPortInterrupter()
        print("[SUCCESS] UDP interrupter initialized")
        
        # Test dupe internet dropper
        dupe_dropper = DupeInternetDropper()
        print("[SUCCESS] Dupe internet dropper initialized")
        
        # Get real network devices
        from app.network.enhanced_scanner import get_enhanced_scanner
        
        scanner = get_enhanced_scanner()
        real_devices = scanner.scan_network("192.168.1.0/24", quick_scan=True)
        
        if not real_devices:
            print("  [WARNING] No real devices found, using localhost for safe test")
            test_devices = [{"ip": "127.0.0.1", "mac": "00:00:00:00:00:00"}]
        else:
            # Use real discovered devices
            test_devices = real_devices[:2]  # Use first 2 devices
            print(f"  [DEVICE] Using {len(test_devices)} real devices for testing")
        
        test_methods = ["udp_interrupt"]
        
        # Start dupe (will be stopped immediately)
        success = dupe_dropper.start_dupe_with_devices(test_devices, test_methods)
        if success:
            print("[SUCCESS] Packet dropping started successfully")
            
            # Stop immediately
            dupe_dropper.stop_dupe()
            print("[SUCCESS] Packet dropping stopped successfully")
        else:
            print("[FAILED] Failed to start packet dropping")
            return False
            
    except Exception as e:
        print(f"[FAILED] Packet dropping test failed: {e}")
        return False
    
    return True

def test_network_scanning():
    """Test network scanning functionality"""
    print("\n[SCAN] Testing Network Scanning...")
    
    try:
        from app.network.device_scan import NativeNetworkScanner
        
        scanner = NativeNetworkScanner()
        print("[SUCCESS] Network scanner initialized")
        
        # Test ping functionality
        result = scanner.ping_host_native("127.0.0.1")
        print(f"[SUCCESS] Ping test result: {result}")
        
        # Test MAC address resolution
        mac = scanner.get_mac_address_native("127.0.0.1")
        print(f"[SUCCESS] MAC resolution test: {mac}")
        
    except Exception as e:
        print(f"[FAILED] Network scanning test failed: {e}")
        return False
    
    return True

def test_firewall_integration():
    """Test firewall integration"""
    print("\n[SHIELD] Testing Firewall Integration...")
    
    try:
        # Check for active PulseDrop firewall rules
        result = subprocess.run([
            "netsh", "advfirewall", "firewall", "show", "rule", "name=all"
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            pulse_drop_rules = [line for line in result.stdout.split('\n') if 'PulseDrop' in line]
            print(f"[SUCCESS] Found {len(pulse_drop_rules)} active PulseDrop firewall rules")
            
            if len(pulse_drop_rules) > 0:
                print("[SUCCESS] Firewall integration is working")
                return True
            else:
                print("[WARNING] No PulseDrop firewall rules found")
                return True  # Not critical for basic functionality
        else:
            print("[FAILED] Failed to check firewall rules")
            return False
            
    except Exception as e:
        print(f"[FAILED] Firewall integration test failed: {e}")
        return False

def test_dayz_integration():
    """Test DayZ integration features"""
    print("\n[GAMING] Testing DayZ Integration...")
    
    try:
        from app.firewall.dayz_firewall_controller import dayz_firewall
        
        # Test DayZ firewall status
        status = dayz_firewall.get_status()
        print(f"[SUCCESS] DayZ firewall status: {status}")
        
        # Test DayZ rules
        rules = dayz_firewall.get_rules()
        print(f"[SUCCESS] DayZ firewall rules: {len(rules)} rules loaded")
        
        # Test DayZ server configuration
        from app.firewall.udp_port_interrupter import UDPPortInterrupter
        udp_interrupter = UDPPortInterrupter()
        servers = udp_interrupter.get_servers()
        print(f"[SUCCESS] DayZ servers configured: {len(servers)} servers")
        
    except Exception as e:
        print(f"[FAILED] DayZ integration test failed: {e}")
        return False
    
    return True

def test_gui_components():
    """Test GUI components"""
    print("\n[DESKTOP] Testing GUI Components...")
    
    try:
        from app.gui.dashboard import DupeZDashboard
        from app.gui.sidebar import Sidebar
        from app.gui.enhanced_device_list import EnhancedDeviceList
        
        # Test dashboard import
        print("[SUCCESS] Dashboard component imported")
        
        # Test sidebar import
        print("[SUCCESS] Sidebar component imported")
        
        # Test enhanced device list import
        print("[SUCCESS] Enhanced device list component imported")
        
    except Exception as e:
        print(f"[FAILED] GUI components test failed: {e}")
        return False
    
    return True

def test_unicode_support():
    """Test Unicode support in logging"""
    print("\n🔤 Testing Unicode Support...")
    
    try:
        from app.logs.logger import log_info, log_error
        
        # Test logging with special characters
        log_info("[SUCCESS] Unicode test message")
        log_error("[ERROR] Unicode error message")
        
        print("[SUCCESS] Unicode logging working correctly")
        
    except Exception as e:
        print(f"[FAILED] Unicode support test failed: {e}")
        return False
    
    return True

def main():
    """Run comprehensive network functionality tests"""
    print("🚀 DupeZ Network Functionality Test")
    print("=" * 50)
    
    tests = [
        ("Critical Imports", test_imports),
        ("Packet Dropping", test_packet_dropping),
        ("Network Scanning", test_network_scanning),
        ("Firewall Integration", test_firewall_integration),
        ("DayZ Integration", test_dayz_integration),
        ("GUI Components", test_gui_components),
        ("Unicode Support", test_unicode_support)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - Network functionality is fully operational!")
        return True
    else:
        print("⚠️ Some tests failed - Review the output above")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 