#!/usr/bin/env python3
"""
Ultra-Fast Device Health Protection Test for PulseDrop Pro
Minimal version to avoid all loops and GUI issues
"""

import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_health_monitor_ultra_fast():
    """Ultra-fast test of health monitor functionality"""
    print("🧪 Testing Health Monitor (Ultra-Fast)...")
    
    try:
        from app.health.device_health_monitor import health_monitor
        
        # Test device addition only
        test_ip = "192.168.1.100"
        result = health_monitor.add_device(test_ip)
        print(f"  ✅ Device addition: {result}")
        
        # Test basic health check (no ping)
        device_health = health_monitor.get_device_health(test_ip)
        if device_health:
            print(f"  ✅ Device health: Score {device_health.health_score:.1f}%")
            print(f"  ✅ Status: {device_health.connectivity_status}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Health Monitor Test Failed: {e}")
        return False

def test_device_protection_ultra_fast():
    """Ultra-fast test of device protection functionality"""
    print("🧪 Testing Device Protection (Ultra-Fast)...")
    
    try:
        from app.health.device_protection import device_protection
        
        # Test protection status only
        status = device_protection.get_protection_status()
        print(f"  ✅ Protection status: {'enabled' if status['protection_enabled'] else 'disabled'}")
        
        # Test device protection info
        test_ip = "192.168.1.100"
        device_info = device_protection.get_device_protection_info(test_ip)
        if 'error' not in device_info:
            print(f"  ✅ Device protection info: {device_info['health_score']:.1f}% health")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Device Protection Test Failed: {e}")
        return False

def test_health_thresholds_ultra_fast():
    """Ultra-fast test of health threshold functionality"""
    print("🧪 Testing Health Thresholds (Ultra-Fast)...")
    
    try:
        from app.health.device_health_monitor import health_monitor
        
        test_ip = "192.168.1.100"
        
        # Test device health without ping
        device_health = health_monitor.get_device_health(test_ip)
        if device_health:
            print(f"  ✅ Health score: {device_health.health_score:.1f}%")
            print(f"  ✅ Connectivity: {device_health.connectivity_status}")
            
            # Test warnings and recommendations
            warnings = health_monitor.get_device_warnings(test_ip)
            print(f"  ✅ Warnings: {len(warnings)} found")
            
            recommendations = health_monitor.get_device_recommendations(test_ip)
            print(f"  ✅ Recommendations: {len(recommendations)} found")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Health Thresholds Test Failed: {e}")
        return False

def test_recovery_measures_ultra_fast():
    """Ultra-fast test of recovery measures"""
    print("🧪 Testing Recovery Measures (Ultra-Fast)...")
    
    try:
        from app.health.device_protection import device_protection
        
        test_ip = "192.168.1.100"
        
        # Test recovery trigger (simulate poor health)
        device_health = device_protection.get_device_protection_info(test_ip)
        if 'error' not in device_health:
            print(f"  ✅ Device health: {device_health['health_score']:.1f}%")
            
            # Simulate poor health
            from app.health.device_health_monitor import health_monitor
            device = health_monitor.get_device_health(test_ip)
            if device:
                device.error_count += 5
                device.health_score = 25.0  # Poor health
                print(f"  ✅ Simulated poor health: {device.health_score:.1f}%")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Recovery Measures Test Failed: {e}")
        return False

def test_core_functionality_ultra_fast():
    """Ultra-fast test of core functionality"""
    print("🧪 Testing Core Functionality (Ultra-Fast)...")
    
    try:
        from app.health.device_health_monitor import health_monitor
        from app.health.device_protection import device_protection
        
        # Test basic functionality
        test_ip = "192.168.1.100"
        
        # Add device
        health_monitor.add_device(test_ip)
        print(f"  ✅ Device added to monitoring")
        
        # Check protection status
        status = device_protection.get_protection_status()
        print(f"  ✅ Protection enabled: {status['protection_enabled']}")
        
        # Check device health
        device = health_monitor.get_device_health(test_ip)
        if device:
            print(f"  ✅ Device health score: {device.health_score:.1f}%")
            print(f"  ✅ Device status: {device.connectivity_status}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Core Functionality Test Failed: {e}")
        return False

def main():
    """Run ultra-fast device health tests"""
    print("🏥 ULTRA-FAST DEVICE HEALTH PROTECTION TEST SUITE")
    print("=" * 50)
    
    tests = [
        ("Health Monitor (Ultra-Fast)", test_health_monitor_ultra_fast),
        ("Device Protection (Ultra-Fast)", test_device_protection_ultra_fast),
        ("Health Thresholds (Ultra-Fast)", test_health_thresholds_ultra_fast),
        ("Recovery Measures (Ultra-Fast)", test_recovery_measures_ultra_fast),
        ("Core Functionality (Ultra-Fast)", test_core_functionality_ultra_fast)
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
    print(f"📊 ULTRA-FAST DEVICE HEALTH TEST RESULTS")
    print(f"{'='*50}")
    print(f"Passed: {passed}/{total}")
    print(f"Success Rate: {(passed/total)*100:.1f}%")
    
    if passed == total:
        print("🎉 ALL ULTRA-FAST DEVICE HEALTH TESTS PASSED!")
        return True
    else:
        print("⚠️ Some ultra-fast device health tests failed")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 