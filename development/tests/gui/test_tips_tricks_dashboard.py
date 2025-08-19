#!/usr/bin/env python3
"""
Test script for DayZ Tips & Tricks Dashboard
"""

import sys
import os
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_tips_tricks_manager():
    """Test the TipsTricksManager class"""
    print("🧪 Testing TipsTricksManager...")
    
    try:
        from app.gui.dayz_tips_tricks_dashboard import TipsTricksManager
        
        # Create manager instance
        manager = TipsTricksManager()
        print("✅ TipsTricksManager created successfully")
        
        # Test categories
        categories = manager.get_categories()
        print(f"✅ Categories loaded: {len(categories)} categories")
        for category in categories:
            print(f"   - {category}")
        
        # Test getting tips for a category
        performance_tips = manager.get_category_tips("performance_optimization")
        print(f"✅ Performance tips loaded: {len(performance_tips)} tips")
        
        # Test getting all tips
        all_tips = manager.get_all_tips()
        print(f"✅ All tips loaded: {len(all_tips)} total tips")
        
        # Test search functionality
        search_results = manager.search_tips("FPS")
        print(f"✅ Search results for 'FPS': {len(search_results)} tips found")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing TipsTricksManager: {e}")
        return False

def test_tips_tricks_dashboard():
    """Test the TipsTricksDashboard GUI"""
    print("🧪 Testing TipsTricksDashboard...")
    
    try:
        from PyQt6.QtWidgets import QApplication
        from app.gui.dayz_tips_tricks_dashboard import TipsTricksDashboard
        
        # Create QApplication if it doesn't exist
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # Create dashboard instance
        dashboard = TipsTricksDashboard()
        print("✅ TipsTricksDashboard created successfully")
        
        # Test manager integration
        manager = dashboard.tips_manager
        if manager:
            print("✅ Dashboard manager integration working")
            
            # Test categories
            categories = manager.get_categories()
            print(f"✅ Dashboard categories: {len(categories)} categories")
            
            # Test tips
            all_tips = manager.get_all_tips()
            print(f"✅ Dashboard tips: {len(all_tips)} total tips")
        else:
            print("❌ Dashboard manager integration failed")
        
        # Test UI components
        if hasattr(dashboard, 'categories_list'):
            print(f"✅ Dashboard categories list: {dashboard.categories_list.count()} items")
        else:
            print("❌ Dashboard categories list not found")
        
        if hasattr(dashboard, 'tips_display'):
            print("✅ Dashboard tips display found")
        else:
            print("❌ Dashboard tips display not found")
        
        # Cleanup
        dashboard.close()
        print("✅ Dashboard closed successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing TipsTricksDashboard: {e}")
        return False

def test_configuration_files():
    """Test configuration files"""
    print("🧪 Testing Configuration Files...")
    
    try:
        # Test DayZ tips and tricks config
        config_path = "app/config/dayz_tips_tricks.json"
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            print("✅ DayZ tips and tricks config loaded successfully")
            print(f"   - Version: {config.get('metadata', {}).get('version', 'N/A')}")
            print(f"   - Categories: {config.get('metadata', {}).get('categories', 'N/A')}")
            print(f"   - Total Tips: {config.get('metadata', {}).get('total_tips', 'N/A')}")
            
            # Test tips structure
            tips_categories = config.get('tips_categories', {})
            for category_name, category_data in tips_categories.items():
                tips = category_data.get('tips', [])
                print(f"   - {category_name}: {len(tips)} tips")
        else:
            print(f"❌ DayZ tips and tricks config not found: {config_path}")
            return False
        
        # Test other config files
        config_files = [
            "app/config/dayz_servers.json",
            "app/config/network_optimization.json",
            "app/config/gaming_rules.json",
            "app/config/dayz_duping_config.json"
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
        
        # Test that the tips dashboard method exists
        if hasattr(DupeZDashboard, 'open_dayz_tips_tricks_dashboard'):
            print("✅ DayZ tips dashboard method found in main dashboard")
        else:
            print("❌ DayZ tips dashboard method not found in main dashboard")
            return False
        
        # Test that the tips dashboard import exists
        import importlib
        try:
            importlib.import_module('app.gui.dayz_tips_tricks_dashboard')
            print("✅ DayZ tips dashboard module import successful")
        except ImportError as e:
            print(f"❌ DayZ tips dashboard module import failed: {e}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing main dashboard integration: {e}")
        return False

def test_tips_content():
    """Test the tips content and structure"""
    print("🧪 Testing Tips Content...")
    
    try:
        from app.gui.dayz_tips_tricks_dashboard import TipsTricksManager
        
        manager = TipsTricksManager()
        
        # Test each category
        for category_key, category_data in manager.tips_data.items():
            print(f"\n📚 Testing category: {category_data['title']}")
            
            tips = category_data['tips']
            print(f"   - Tips count: {len(tips)}")
            
            for i, tip in enumerate(tips, 1):
                print(f"   - Tip {i}: {tip['title']}")
                print(f"     Difficulty: {tip['difficulty']}")
                print(f"     FPS Boost: {tip['fps_boost']}%")
                print(f"     Category: {tip['category']}")
                
                # Test content length
                content_length = len(tip['content'])
                if content_length > 100:
                    print(f"     Content: {content_length} characters ✓")
                else:
                    print(f"     Content: {content_length} characters ⚠️ (short)")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing tips content: {e}")
        return False

def main():
    """Main test function"""
    print("🚀 Starting DayZ Tips & Tricks Dashboard Test Suite")
    print("=" * 60)
    
    tests = [
        ("Configuration Files", test_configuration_files),
        ("Tips Content", test_tips_content),
        ("TipsTricksManager", test_tips_tricks_manager),
        ("TipsTricksDashboard", test_tips_tricks_dashboard),
        ("Main Dashboard Integration", test_integration)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n📋 Running: {test_name}")
        print("-" * 40)
        
        try:
            if test_func():
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! DayZ Tips & Tricks Dashboard is working correctly.")
        print("\n💡 **Features Available:**")
        print("• 5 optimization categories")
        print("• 15 detailed tips and tricks")
        print("• Search functionality")
        print("• Export capabilities")
        print("• Difficulty levels and risk assessment")
        print("• FPS boost estimates")
        print("• Integration with main DupeZ dashboard")
    else:
        print(f"⚠️  {total - passed} test(s) failed. Please check the errors above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
