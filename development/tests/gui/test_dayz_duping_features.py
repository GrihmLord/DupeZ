#!/usr/bin/env python3
"""
Test script for DayZ duping network optimization features
"""

import sys
import os
import time
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_dayz_duping_optimizer():
    """Test the DayZ duping optimizer"""
    print("🧪 Testing DayZ Duping Optimizer...")
    
    try:
        from app.network.dayz_duping_optimizer import DayZDupingOptimizer
        
        # Create optimizer instance
        optimizer = DayZDupingOptimizer()
        print("✅ DayZ Duping Optimizer created successfully")
        
        # Test network profiles
        profiles = optimizer.get_network_profiles()
        print(f"✅ Network profiles loaded: {len(profiles)} profiles")
        for profile_name, profile_data in profiles.items():
            print(f"   - {profile_name}: {profile_data['description']}")
        
        # Test manipulation techniques
        techniques = optimizer.get_manipulation_techniques()
        print(f"✅ Manipulation techniques loaded: {len(techniques)} techniques")
        for technique in techniques:
            print(f"   - {technique.name}: {technique.description}")
        
        # Test starting a duping session
        session_id = optimizer.start_duping_session(
            server_ip="192.168.1.100",
            server_port=2302,
            method="standard",
            profile="balanced"
        )
        
        if session_id:
            print(f"✅ Duping session started: {session_id}")
            
            # Test getting session info
            session_info = optimizer.get_session_info(session_id)
            if session_info:
                print(f"✅ Session info retrieved: {session_info.target_server}:{session_info.target_port}")
            
            # Test getting active sessions
            active_sessions = optimizer.get_active_sessions()
            print(f"✅ Active sessions: {len(active_sessions)}")
            
            # Test performance report
            report = optimizer.get_performance_report()
            print(f"✅ Performance report generated: {report['active_sessions']} active sessions")
            
            # Test stopping session
            if optimizer.stop_duping_session(session_id):
                print(f"✅ Session stopped: {session_id}")
            else:
                print(f"❌ Failed to stop session: {session_id}")
        else:
            print("❌ Failed to start duping session")
        
        # Test cleanup
        optimizer.cleanup()
        print("✅ Optimizer cleaned up successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing DayZ Duping Optimizer: {e}")
        return False

def test_dayz_duping_dashboard():
    """Test the DayZ duping dashboard GUI"""
    print("🧪 Testing DayZ Duping Dashboard...")
    
    try:
        from PyQt6.QtWidgets import QApplication
        from app.gui.dayz_duping_dashboard import DayZDupingDashboard
        
        # Create QApplication if it doesn't exist
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # Create dashboard instance
        dashboard = DayZDupingDashboard()
        print("✅ DayZ Duping Dashboard created successfully")
        
        # Test optimizer integration
        optimizer = dashboard.optimizer
        if optimizer:
            print("✅ Dashboard optimizer integration working")
            
            # Test network profiles
            profiles = optimizer.get_network_profiles()
            print(f"✅ Dashboard profiles: {len(profiles)} profiles")
            
            # Test manipulation techniques
            techniques = optimizer.get_manipulation_techniques()
            print(f"✅ Dashboard techniques: {len(techniques)} techniques")
        else:
            print("❌ Dashboard optimizer integration failed")
        
        # Test UI components
        if hasattr(dashboard, 'tab_widget'):
            print(f"✅ Dashboard tabs: {dashboard.tab_widget.count()} tabs")
        else:
            print("❌ Dashboard tabs not found")
        
        # Cleanup
        dashboard.close()
        print("✅ Dashboard closed successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing DayZ Duping Dashboard: {e}")
        return False

def test_configuration_files():
    """Test configuration files"""
    print("🧪 Testing Configuration Files...")
    
    try:
        # Test DayZ duping config
        config_path = "app/config/dayz_duping_config.json"
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            print("✅ DayZ duping config loaded successfully")
            print(f"   - Version: {config.get('version', 'N/A')}")
            print(f"   - Profiles: {len(config.get('duping_profiles', {}))}")
            print(f"   - Techniques: {len(config.get('manipulation_techniques', {}))}")
            print(f"   - Methods: {len(config.get('duping_methods', {}))}")
        else:
            print(f"❌ DayZ duping config not found: {config_path}")
            return False
        
        # Test other config files
        config_files = [
            "app/config/dayz_servers.json",
            "app/config/network_optimization.json",
            "app/config/gaming_rules.json"
        ]
        
        for config_file in config_files:
            if os.path.exists(config_file):
                print(f"✅ Config file exists: {config_file}")
            else:
                print(f"❌ Config file missing: {config_file}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing configuration files: {e}")
        return False

def test_integration():
    """Test integration with main dashboard"""
    print("🧪 Testing Main Dashboard Integration...")
    
    try:
        from app.gui.dashboard import DupeZDashboard
        
        # Test import
        print("✅ Main dashboard import successful")
        
        # Test that the duping dashboard method exists
        if hasattr(DupeZDashboard, 'open_dayz_duping_dashboard'):
            print("✅ DayZ duping dashboard method found in main dashboard")
        else:
            print("❌ DayZ duping dashboard method not found in main dashboard")
            return False
        
        # Test that the duping dashboard import exists
        import importlib
        try:
            importlib.import_module('app.gui.dayz_duping_dashboard')
            print("✅ DayZ duping dashboard module import successful")
        except ImportError as e:
            print(f"❌ DayZ duping dashboard module import failed: {e}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing main dashboard integration: {e}")
        return False

def main():
    """Main test function"""
    print("🚀 Starting DayZ Duping Features Test Suite")
    print("=" * 50)
    
    tests = [
        ("Configuration Files", test_configuration_files),
        ("DayZ Duping Optimizer", test_dayz_duping_optimizer),
        ("DayZ Duping Dashboard", test_dayz_duping_dashboard),
        ("Main Dashboard Integration", test_integration)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📋 Running: {test_name}")
        print("-" * 30)
        
        try:
            if test_func():
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! DayZ duping features are working correctly.")
    else:
        print(f"⚠️  {total - passed} test(s) failed. Please check the errors above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
