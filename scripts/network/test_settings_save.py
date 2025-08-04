#!/usr/bin/env python3
"""
Test Settings Save Script
This script tests the settings saving functionality.
"""

import sys
import os
import json

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.core.state import AppSettings, AppState

def test_settings_save():
    """Test settings saving functionality"""
    print("=" * 50)
    print("SETTINGS SAVE TEST")
    print("=" * 50)
    
    try:
        # Test 1: Create settings
        print("1. Creating test settings...")
        test_settings = AppSettings(
            smart_mode=True,
            auto_scan=True,
            scan_interval=30,
            max_devices=50,
            log_level="DEBUG",
            theme="hacker",
            auto_refresh=True,
            refresh_interval=60
        )
        print("✅ Test settings created")
        
        # Test 2: Create app state
        print("2. Creating app state...")
        test_config_file = "test_settings.json"
        app_state = AppState(test_config_file)
        print("✅ App state created")
        
        # Test 3: Save settings
        print("3. Saving settings...")
        app_state.settings = test_settings
        app_state.save_settings()
        print("✅ Settings saved")
        
        # Test 4: Load settings
        print("4. Loading settings...")
        app_state.load_settings()
        print("✅ Settings loaded")
        
        # Test 5: Verify settings
        print("5. Verifying settings...")
        loaded_settings = app_state.settings
        if (loaded_settings.smart_mode == test_settings.smart_mode and
            loaded_settings.auto_scan == test_settings.auto_scan and
            loaded_settings.scan_interval == test_settings.scan_interval and
            loaded_settings.theme == test_settings.theme):
            print("✅ Settings verification passed")
        else:
            print("❌ Settings verification failed")
            print(f"Expected smart_mode: {test_settings.smart_mode}, Got: {loaded_settings.smart_mode}")
            print(f"Expected auto_scan: {test_settings.auto_scan}, Got: {loaded_settings.auto_scan}")
            print(f"Expected scan_interval: {test_settings.scan_interval}, Got: {loaded_settings.scan_interval}")
            print(f"Expected theme: {test_settings.theme}, Got: {loaded_settings.theme}")
        
        # Test 6: Check if file exists
        print("6. Checking settings file...")
        if os.path.exists(test_config_file):
            print(f"✅ Settings file created: {test_config_file}")
            
            # Read and display file contents
            with open(test_config_file, 'r') as f:
                file_contents = json.load(f)
            print(f"File contents: {json.dumps(file_contents, indent=2)}")
        else:
            print(f"❌ Settings file not found: {test_config_file}")
        
        # Cleanup
        if os.path.exists(test_config_file):
            os.remove(test_config_file)
            print("✅ Test file cleaned up")
        
        print("\n" + "=" * 50)
        print("SETTINGS SAVE TEST COMPLETE")
        print("=" * 50)
        print()
        print("If settings saving is not working:")
        print("1. Check file permissions in app/config/ directory")
        print("2. Ensure the controller is properly passed to settings dialog")
        print("3. Verify the settings dialog calls controller.update_settings()")
        print("4. Check that the config file path is correct")
        print()
        
        return True
        
    except Exception as e:
        print(f"❌ Settings test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_settings_save() 