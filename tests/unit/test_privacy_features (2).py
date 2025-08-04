#!/usr/bin/env python3
"""
Privacy Features Test for PulseDrop Pro
Tests all privacy protection features
"""

import sys
import os
import time
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_privacy_manager():
    """Test privacy manager functionality"""
    print("🧪 Testing Privacy Manager...")
    
    try:
        from app.privacy.privacy_manager import privacy_manager
        
        # Test session ID generation
        print(f"  ✅ Session ID: {privacy_manager.session_id}")
        
        # Test MAC anonymization
        test_mac = "AA:BB:CC:DD:EE:FF"
        anonymized_mac = privacy_manager.anonymize_mac(test_mac)
        print(f"  ✅ MAC Anonymization: {test_mac} -> {anonymized_mac}")
        
        # Test IP anonymization
        test_ip = "192.168.1.100"
        anonymized_ip = privacy_manager.anonymize_ip(test_ip)
        print(f"  ✅ IP Anonymization: {test_ip} -> {anonymized_ip}")
        
        # Test device name anonymization
        test_device = "My-PS5-Device"
        anonymized_device = privacy_manager.anonymize_device_name(test_device)
        print(f"  ✅ Device Anonymization: {test_device} -> {anonymized_device}")
        
        # Test privacy event logging
        privacy_manager.log_privacy_event("test_event", {
            "test_data": "sample",
            "timestamp": time.time()
        })
        print(f"  ✅ Privacy Event Logging: {len(privacy_manager.privacy_log)} events")
        
        # Test privacy report
        report = privacy_manager.get_privacy_report()
        print(f"  ✅ Privacy Report: {report['privacy_level']} level")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Privacy Manager Test Failed: {e}")
        return False

def test_privacy_settings():
    """Test privacy settings functionality"""
    print("🧪 Testing Privacy Settings...")
    
    try:
        from app.privacy.privacy_manager import privacy_manager
        
        # Test privacy level changes
        levels = ["low", "medium", "high", "maximum"]
        
        for level in levels:
            privacy_manager.set_privacy_level(level)
            current_level = privacy_manager.settings.privacy_level
            print(f"  ✅ Privacy Level: {level} -> {current_level}")
            
            # Verify settings
            if level == "high":
                assert privacy_manager.settings.anonymize_mac_addresses == True
                assert privacy_manager.settings.anonymize_ip_addresses == True
                assert privacy_manager.settings.encrypt_logs == True
                print(f"    ✅ High level settings verified")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Privacy Settings Test Failed: {e}")
        return False

def test_privacy_integration():
    """Test privacy integration with existing modules"""
    print("🧪 Testing Privacy Integration...")
    
    try:
        from app.privacy.privacy_integration import (
            anonymize_device_data, 
            anonymize_network_data,
            privacy_protect
        )
        
        # Test device data anonymization
        test_device = {
            "name": "My-PS5",
            "ip": "192.168.1.100",
            "mac": "AA:BB:CC:DD:EE:FF"
        }
        
        anonymized_device = anonymize_device_data(test_device)
        print(f"  ✅ Device Data Anonymization:")
        print(f"    Original: {test_device}")
        print(f"    Anonymized: {anonymized_device}")
        
        # Test network data anonymization
        test_network = {
            "gateway": "192.168.1.1",
            "devices": [
                {"ip": "192.168.1.100", "name": "Device1"},
                {"ip": "192.168.1.101", "name": "Device2"}
            ]
        }
        
        anonymized_network = anonymize_network_data(test_network)
        print(f"  ✅ Network Data Anonymization:")
        print(f"    Original: {test_network}")
        print(f"    Anonymized: {anonymized_network}")
        
        # Test privacy decorator
        @privacy_protect
        def test_function():
            return "test_result"
        
        result = test_function()
        print(f"  ✅ Privacy Decorator: {result}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Privacy Integration Test Failed: {e}")
        return False

def test_privacy_gui():
    """Test privacy GUI components"""
    print("🧪 Testing Privacy GUI...")
    
    try:
        from app.gui.privacy_gui import PrivacySettingsWidget, PrivacyTabWidget
        
        # Test widget creation
        settings_widget = PrivacySettingsWidget()
        print(f"  ✅ Privacy Settings Widget created")
        
        tab_widget = PrivacyTabWidget()
        print(f"  ✅ Privacy Tab Widget created")
        
        # Test privacy manager access
        privacy_manager = tab_widget.get_privacy_manager()
        print(f"  ✅ Privacy Manager access: {privacy_manager.session_id}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Privacy GUI Test Failed: {e}")
        return False

def test_privacy_logging():
    """Test privacy-aware logging"""
    print("🧪 Testing Privacy Logging...")
    
    try:
        from app.logs.logger import log_info, log_error, log_blocking_event
        
        # Test privacy-aware logging
        log_info("Test privacy info message")
        log_error("Test privacy error message")
        log_blocking_event("block", "192.168.1.100", True)
        
        print(f"  ✅ Privacy-aware logging functions called")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Privacy Logging Test Failed: {e}")
        return False

def test_privacy_cleanup():
    """Test privacy data cleanup"""
    print("🧪 Testing Privacy Cleanup...")
    
    try:
        from app.privacy.privacy_manager import privacy_manager
        
        # Test data cleanup
        initial_events = len(privacy_manager.privacy_log)
        privacy_manager.clear_privacy_data()
        final_events = len(privacy_manager.privacy_log)
        
        print(f"  ✅ Privacy Cleanup: {initial_events} -> {final_events} events")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Privacy Cleanup Test Failed: {e}")
        return False

def main():
    """Run all privacy tests"""
    print("🛡️ PRIVACY FEATURES TEST SUITE")
    print("=" * 50)
    
    tests = [
        ("Privacy Manager", test_privacy_manager),
        ("Privacy Settings", test_privacy_settings),
        ("Privacy Integration", test_privacy_integration),
        ("Privacy GUI", test_privacy_gui),
        ("Privacy Logging", test_privacy_logging),
        ("Privacy Cleanup", test_privacy_cleanup)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        if test_func():
            passed += 1
            print(f"  ✅ {test_name} PASSED")
        else:
            print(f"  ❌ {test_name} FAILED")
    
    print(f"\n{'='*50}")
    print(f"📊 PRIVACY TEST RESULTS")
    print(f"{'='*50}")
    print(f"Passed: {passed}/{total}")
    print(f"Success Rate: {(passed/total)*100:.1f}%")
    
    if passed == total:
        print("🎉 ALL PRIVACY TESTS PASSED!")
        return True
    else:
        print("⚠️ Some privacy tests failed")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 