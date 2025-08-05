#!/usr/bin/env python3
"""
Test script for the comprehensive error tracking system
"""

import sys
import os
import traceback
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
            print(f"   Line: {error['line_number']}")
            print(f"   Timestamp: {error['timestamp']}")
        
        # Test error categorization
        print("\n🏷️ Error Categorization Test:")
        print("=" * 60)
        
        test_messages = [
            ("could not convert 'NetworkNode' to 'QObject'", "topology"),
            ("Failed to send UDP flood to 0.0.0.0", "udp_flood"),
            ("Network scan timeout", "network_scan"),
            ("QWidget error", "gui"),
            ("Firewall rule failed", "firewall"),
            ("Plugin load error", "plugin"),
            ("Save data failed", "data_persistence"),
            ("Memory allocation failed", "system"),
            ("Unknown error message", "unknown")
        ]
        
        for message, expected_category in test_messages:
            track_error(message)
        
        # Final statistics
        print("\n✅ Final Error Statistics:")
        print("=" * 60)
        final_stats = get_error_stats()
        print(f"Total errors tracked: {final_stats['total_errors']}")
        print(f"Errors by category: {final_stats['errors_by_category']}")
        print(f"Errors by severity: {final_stats['errors_by_severity']}")
        print(f"Session duration: {final_stats['session_duration']}")
        
        print("\n✅ Error tracking test completed successfully!")
        print("📁 Check the logs directory for detailed error logs:")
        print("   - comprehensive_errors.log")
        print("   - error_summary.log")
        print("   - critical_errors.log")
        print("   - errors_topology.log")
        print("   - errors_udp_flood.log")
        print("   - etc...")
        
        return True
        
    except Exception as e:
        print(f"❌ Error tracking test failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_error_tracking()
    sys.exit(0 if success else 1) 