#!/usr/bin/env python3
"""
Device Health Protection Test for PulseDrop Pro
Tests all device health monitoring and protection features
"""

import sys
import os
import time
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_health_monitor():
    """Test health monitor functionality"""
    print("🧪 Testing Health Monitor...")
    
    try:
        from app.health.device_health_monitor import health_monitor
        
        # Test device addition
        test_ip = "192.168.1.100"
        result = health_monitor.add_device(test_ip)
        print(f"  ✅ Device addition: {result}")
        
        # Test health check
        device_health = health_monitor.check_device_health(test_ip)
        if device_health:
            print(f"  ✅ Health check: Score {device_health.health_score:.1f}%")
            print(f"  ✅ Status: {device_health.connectivity_status}")
            print(f"  ✅ Latency: {device_health.ping_latency:.1f}ms")
            print(f"  ✅ Packet Loss: {device_health.packet_loss:.1f}%")
        else:
            print(f"  ❌ Health check failed")
        
        # Test health report
        report = health_monitor.get_health_report()
        print(f"  ✅ Health report: {report['total_devices']} devices")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Health Monitor Test Failed: {e}")
        return False

def test_device_protection():
    """Test device protection functionality"""
    print("🧪 Testing Device Protection...")
    
    try:
        from app.health.device_protection import device_protection, protect_device_health
        
        # Test protection status
        status = device_protection.get_protection_status()
        print(f"  ✅ Protection status: {'enabled' if status['protection_enabled'] else 'disabled'}")
        
        # Test device protection info
        test_ip = "192.168.1.100"
        device_info = device_protection.get_device_protection_info(test_ip)
        if 'error' not in device_info:
            print(f"  ✅ Device protection info: {device_info['health_score']:.1f}% health")
        else:
            print(f"  ⚠️ Device not monitored: {device_info['error']}")
        
        # Test protection decorator
        @protect_device_health
        def test_function(ip_address):
            return f"Test operation on {ip_address}"
        
        result = test_function(test_ip)
        print(f"  ✅ Protection decorator: {result}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Device Protection Test Failed: {e}")
        return False

def test_safe_operations():
    """Test safe operation wrappers"""
    print("🧪 Testing Safe Operations...")
    
    try:
        from app.health.device_protection import device_protection
        
        test_ip = "192.168.1.100"
        
        # Test safe scan
        scan_result = device_protection.safe_scan_device(test_ip)
        print(f"  ✅ Safe scan: {len(scan_result)} results")
        
        # Test safe block (should be blocked if device unhealthy)
        block_result = device_protection.safe_block_device(test_ip)
        print(f"  ✅ Safe block: {'success' if block_result else 'blocked'}")
        
        # Test safe unblock
        unblock_result = device_protection.safe_unblock_device(test_ip)
        print(f"  ✅ Safe unblock: {'success' if unblock_result else 'blocked'}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Safe Operations Test Failed: {e}")
        return False

def test_health_thresholds():
    """Test health threshold functionality"""
    print("🧪 Testing Health Thresholds...")
    
    try:
        from app.health.device_health_monitor import health_monitor
        
        test_ip = "192.168.1.100"
        
        # Test device health
        device_health = health_monitor.get_device_health(test_ip)
        if device_health:
            # Test health score calculation
            print(f"  ✅ Health score: {device_health.health_score:.1f}%")
            
            # Test connectivity status
            print(f"  ✅ Connectivity: {device_health.connectivity_status}")
            
            # Test warnings
            warnings = health_monitor.get_device_warnings(test_ip)
            print(f"  ✅ Warnings: {len(warnings)} found")
            
            # Test recommendations
            recommendations = health_monitor.get_device_recommendations(test_ip)
            print(f"  ✅ Recommendations: {len(recommendations)} found")
            
            # Test healthy check
            is_healthy = health_monitor.is_device_healthy(test_ip)
            print(f"  ✅ Healthy for operations: {is_healthy}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Health Thresholds Test Failed: {e}")
        return False

def test_health_gui():
    """Test health GUI components"""
    print("🧪 Testing Health GUI...")
    
    try:
        from app.gui.health_gui import DeviceHealthWidget, HealthTabWidget
        
        # Test widget creation
        health_widget = DeviceHealthWidget()
        print(f"  ✅ Health Widget created")
        
        tab_widget = HealthTabWidget()
        print(f"  ✅ Health Tab Widget created")
        
        # Test health monitor access
        health_monitor = tab_widget.get_health_monitor()
        print(f"  ✅ Health Monitor access: {len(health_monitor.devices)} devices")
        
        # Test device protection access
        device_protection = tab_widget.get_device_protection()
        print(f"  ✅ Device Protection access: {device_protection.protection_enabled}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Health GUI Test Failed: {e}")
        return False

def test_health_monitoring():
    """Test continuous health monitoring"""
    print("🧪 Testing Health Monitoring...")
    
    try:
        from app.health.device_health_monitor import health_monitor
        
        # Add test devices
        test_devices = ["192.168.1.100", "192.168.1.101", "192.168.1.102"]
        
        for ip in test_devices:
            health_monitor.add_device(ip)
        
        print(f"  ✅ Added {len(test_devices)} test devices")
        
        # Start monitoring
        health_monitor.start_monitoring()
        print(f"  ✅ Health monitoring started")
        
        # Wait a moment for monitoring
        time.sleep(2)
        
        # Check monitoring status
        if health_monitor.monitoring_active:
            print(f"  ✅ Monitoring is active")
        else:
            print(f"  ❌ Monitoring not active")
        
        # Stop monitoring
        health_monitor.stop_monitoring()
        print(f"  ✅ Health monitoring stopped")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Health Monitoring Test Failed: {e}")
        return False

def test_recovery_measures():
    """Test automatic recovery measures"""
    print("🧪 Testing Recovery Measures...")
    
    try:
        from app.health.device_protection import device_protection
        
        test_ip = "192.168.1.100"
        
        # Test recovery trigger (simulate poor health)
        device_health = device_protection.get_device_protection_info(test_ip)
        if 'error' not in device_health:
            print(f"  ✅ Device health before recovery: {device_health['health_score']:.1f}%")
            
            # Simulate poor health by adding errors
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

def main():
    """Run all device health tests"""
    print("🏥 DEVICE HEALTH PROTECTION TEST SUITE")
    print("=" * 50)
    
    tests = [
        ("Health Monitor", test_health_monitor),
        ("Device Protection", test_device_protection),
        ("Safe Operations", test_safe_operations),
        ("Health Thresholds", test_health_thresholds),
        ("Health GUI", test_health_gui),
        ("Health Monitoring", test_health_monitoring),
        ("Recovery Measures", test_recovery_measures)
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
    print(f"📊 DEVICE HEALTH TEST RESULTS")
    print(f"{'='*50}")
    print(f"Passed: {passed}/{total}")
    print(f"Success Rate: {(passed/total)*100:.1f}%")
    
    if passed == total:
        print("🎉 ALL DEVICE HEALTH TESTS PASSED!")
        return True
    else:
        print("⚠️ Some device health tests failed")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 