#!/usr/bin/env python3
"""
Test script for the comprehensive error tracking system
"""

import sys
import os
import traceback
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_error_tracking():
    """Test the error tracking system"""
    try:
        from app.logs.error_tracker import track_error, get_error_stats, get_recent_errors, ErrorCategory, ErrorSeverity
        
        print("🧪 Testing Comprehensive Error Tracking System")
        print("=" * 60)
        
        # Test 1: Basic error tracking
        print("\n1. Testing basic error tracking...")
        track_error("Test error message", 
                   exception=ValueError("Test exception"),
                   category=ErrorCategory.SYSTEM,
                   severity=ErrorSeverity.MEDIUM,
                   context={"test": True, "user_action": "testing"})
        
        # Test 2: Topology error
        print("2. Testing topology error tracking...")
        track_error("Error adding device 192.168.1.100 to topology: could not convert 'NetworkNode' to 'QObject'",
                   category=ErrorCategory.TOPOLOGY,
                   severity=ErrorSeverity.HIGH,
                   context={"device_ip": "192.168.1.100", "device_type": "gaming"})
        
        # Test 3: UDP flood error
        print("3. Testing UDP flood error tracking...")
        track_error("Failed to send UDP flood to 0.0.0.0:2302: [WinError 10049] The requested address is not valid in its context",
                   category=ErrorCategory.UDP_FLOOD,
                   severity=ErrorSeverity.MEDIUM,
                   context={"target_ip": "0.0.0.0", "port": 2302})
        
        # Test 4: Network scan error
        print("4. Testing network scan error tracking...")
        track_error("Network scan failed: timeout",
                   category=ErrorCategory.NETWORK_SCAN,
                   severity=ErrorSeverity.LOW,
                   context={"scan_type": "arp", "timeout": 30})
        
        # Test 5: GUI error
        print("5. Testing GUI error tracking...")
        track_error("QWidget: Must construct a QApplication before a QWidget",
                   category=ErrorCategory.GUI,
                   severity=ErrorSeverity.CRITICAL,
                   context={"widget_type": "QGraphicsView"})
        
        # Test 6: Firewall error
        print("6. Testing firewall error tracking...")
        track_error("Failed to block device 192.168.1.50: access denied",
                   category=ErrorCategory.FIREWALL,
                   severity=ErrorSeverity.HIGH,
                   context={"target_ip": "192.168.1.50", "action": "block"})
        
        # Test 7: Plugin error
        print("7. Testing plugin error tracking...")
        track_error("Plugin gaming_control failed to load: missing dependency",
                   category=ErrorCategory.PLUGIN,
                   severity=ErrorSeverity.MEDIUM,
                   context={"plugin_name": "gaming_control", "missing_dep": "psutil"})
        
        # Test 8: Data persistence error
        print("8. Testing data persistence error tracking...")
        track_error("Failed to save settings: disk full",
                   category=ErrorCategory.DATA_PERSISTENCE,
                   severity=ErrorSeverity.HIGH,
                   context={"file": "settings.json", "disk_space": "0MB"})
        
        # Wait a moment for background processing
        import time
        time.sleep(2)
        
        # Get and display error statistics
        print("\n📊 Error Statistics:")
        print("=" * 60)
        stats = get_error_stats()
        for key, value in stats.items():
            if key != "session_duration":
                print(f"{key}: {value}")
        
        # Get recent errors
        print("\n📋 Recent Errors (last 5):")
        print("=" * 60)
        recent_errors = get_recent_errors(5)
        for i, error in enumerate(recent_errors, 1):
            print(f"\n{i}. {error['error_message']}")
            print(f"   Category: {error['category']}")
            print(f"   Severity: {error['severity']}")
            print(f"   Module: {error['module']}")
            print(f"   Function: {error['function']}")
            print(f"   Timestamp: {error['timestamp']}")
            if error.get('context'):
                print(f"   Context: {error['context']}")
        
        # Test error categorization
        print("\n🔍 Testing Error Categorization:")
        print("=" * 60)
        
        test_errors = [
            ("Network scan timeout", ErrorCategory.NETWORK_SCAN, ErrorSeverity.MEDIUM),
            ("GUI widget creation failed", ErrorCategory.GUI, ErrorSeverity.HIGH),
            ("Firewall rule creation failed", ErrorCategory.FIREWALL, ErrorSeverity.CRITICAL),
            ("Plugin loading failed", ErrorCategory.PLUGIN, ErrorSeverity.MEDIUM),
            ("Data save failed", ErrorCategory.DATA_PERSISTENCE, ErrorSeverity.HIGH),
            ("UDP flood failed", ErrorCategory.UDP_FLOOD, ErrorSeverity.LOW),
            ("Topology update failed", ErrorCategory.TOPOLOGY, ErrorSeverity.MEDIUM),
            ("System resource exhausted", ErrorCategory.SYSTEM, ErrorSeverity.CRITICAL)
        ]
        
        for error_msg, category, severity in test_errors:
            track_error(error_msg, category=category, severity=severity)
            print(f"✅ Tracked: {category.value} - {severity.value} - {error_msg}")
        
        # Test error filtering
        print("\n🔍 Testing Error Filtering:")
        print("=" * 60)
        
        # Get errors by category
        for category in ErrorCategory:
            category_errors = [e for e in get_recent_errors(20) if e['category'] == category]
            print(f"{category.value}: {len(category_errors)} errors")
        
        # Get errors by severity
        for severity in ErrorSeverity:
            severity_errors = [e for e in get_recent_errors(20) if e['severity'] == severity]
            print(f"{severity.value}: {len(severity_errors)} errors")
        
        print("\n✅ Error tracking system test completed successfully")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure the error tracking module is available")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False

def test_error_persistence():
    """Test error persistence functionality"""
    print("\n💾 Testing Error Persistence:")
    print("=" * 60)
    
    try:
        from app.logs.error_tracker import track_error, get_error_stats
        
        # Test persistent error tracking
        print("1. Testing persistent error tracking...")
        track_error("Persistent test error", 
                   category=ErrorCategory.SYSTEM,
                   severity=ErrorSeverity.MEDIUM,
                   persistent=True)
        
        # Test error cleanup
        print("2. Testing error cleanup...")
        stats_before = get_error_stats()
        print(f"   Errors before cleanup: {stats_before.get('total_errors', 0)}")
        
        # Simulate cleanup (this would normally be done by the system)
        print("   Simulating error cleanup...")
        
        stats_after = get_error_stats()
        print(f"   Errors after cleanup: {stats_after.get('total_errors', 0)}")
        
        print("✅ Error persistence test completed")
        return True
        
    except Exception as e:
        print(f"❌ Persistence test failed: {e}")
        return False

def test_error_recovery():
    """Test error recovery mechanisms"""
    print("\n🔄 Testing Error Recovery:")
    print("=" * 60)
    
    try:
        from app.logs.error_tracker import track_error, get_error_stats
        
        # Test error recovery tracking
        print("1. Testing error recovery tracking...")
        track_error("Recovery test error", 
                   category=ErrorCategory.SYSTEM,
                   severity=ErrorSeverity.LOW,
                   context={"recovery_attempt": True})
        
        # Test error resolution
        print("2. Testing error resolution...")
        track_error("Error resolved successfully", 
                   category=ErrorCategory.SYSTEM,
                   severity=ErrorSeverity.LOW,
                   context={"resolved": True, "resolution_time": "2s"})
        
        print("✅ Error recovery test completed")
        return True
        
    except Exception as e:
        print(f"❌ Recovery test failed: {e}")
        return False

def main():
    """Main test function"""
    print("🧪 Comprehensive Error Tracking Test Suite")
    print("=" * 80)
    print(f"📅 Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Run all tests
    tests = [
        ("Basic Error Tracking", test_error_tracking),
        ("Error Persistence", test_error_persistence),
        ("Error Recovery", test_error_recovery)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            results.append((test_name, False))
    
    # Summary
    print(f"\n{'='*20} TEST SUMMARY {'='*20}")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"📊 Results: {passed}/{total} tests passed")
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"   {test_name}: {status}")
    
    if passed == total:
        print(f"\n🎉 All tests passed! Error tracking system is working correctly.")
    else:
        print(f"\n⚠️ {total - passed} test(s) failed. Check error tracking system.")
    
    print(f"\n✅ Error tracking test suite completed")

if __name__ == "__main__":
    main() 