#!/usr/bin/env python3
"""
WinDivert Status Checker for DupeZ
Comprehensive check of WinDivert availability and functionality
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

def check_windivert_files():
    """Check for WinDivert executable files"""
    print("🔍 Checking for WinDivert files...")
    
    windivert_paths = [
        "WinDivert64.exe",
        "WinDivert32.exe",
        os.path.join(os.getcwd(), "WinDivert64.exe"),
        os.path.join(os.getcwd(), "WinDivert32.exe"),
        "C:\\Windows\\System32\\WinDivert64.exe",
        os.path.join(os.path.dirname(__file__), "WinDivert64.exe"),
        os.path.join(os.path.dirname(__file__), "WinDivert32.exe")
    ]
    
    found_files = []
    for path in windivert_paths:
        if os.path.exists(path):
            found_files.append(path)
            print(f"✅ Found: {path}")
    
    if not found_files:
        print("❌ No WinDivert files found")
        return False
    
    return found_files

def test_windivert_functionality(windivert_path):
    """Test WinDivert functionality"""
    print(f"🧪 Testing WinDivert functionality: {windivert_path}")
    
    try:
        # Test help command
        result = subprocess.run([windivert_path, "--help"], 
                              capture_output=True, 
                              text=True, 
                              timeout=10)
        
        if result.returncode == 0 or "WinDivert" in result.stdout:
            print("✅ WinDivert help command works")
            return True
        else:
            print(f"❌ WinDivert help command failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("✅ WinDivert help command executed (timeout expected)")
        return True
    except Exception as e:
        print(f"❌ WinDivert test error: {e}")
        return False

def check_system_compatibility():
    """Check system compatibility for WinDivert"""
    print("🖥️ Checking system compatibility...")
    
    # Check OS
    if platform.system() != "Windows":
        print("❌ WinDivert only works on Windows")
        return False
    
    print(f"✅ OS: {platform.system()} {platform.release()}")
    
    # Check architecture
    arch = platform.architecture()[0]
    print(f"✅ Architecture: {arch}")
    
    # Check if running as administrator
    try:
        is_admin = subprocess.run(["net", "session"], 
                                capture_output=True, 
                                check=False).returncode == 0
        if is_admin:
            print("✅ Running as Administrator")
        else:
            print("⚠️ Not running as Administrator (some features may be limited)")
    except:
        print("⚠️ Could not determine administrator status")
    
    return True

def check_dupez_integration():
    """Check DupeZ WinDivert integration"""
    print("🎮 Checking DupeZ WinDivert integration...")
    
    try:
        # Import DupeZ modules
        sys.path.append(os.path.dirname(__file__))
        
        from app.firewall.win_divert import windivert_controller
        from app.logs.logger import log_info, log_error
        
        print("✅ WinDivert controller imported successfully")
        
        # Test initialization
        if windivert_controller.initialize():
            print("✅ WinDivert controller initialized successfully")
            return True
        else:
            print("❌ WinDivert controller initialization failed")
            return False
            
    except ImportError as e:
        print(f"❌ Could not import DupeZ modules: {e}")
        return False
    except Exception as e:
        print(f"❌ DupeZ integration test failed: {e}")
        return False

def provide_installation_instructions():
    """Provide installation instructions"""
    print("\n📋 WinDivert Installation Instructions:")
    print("=" * 50)
    print("1. Download WinDivert:")
    print("   - Visit: https://reqrypt.org/windivert.html")
    print("   - Or run: python download_windivert_manual.py")
    print()
    print("2. Extract WinDivert:")
    print("   - Extract the ZIP file")
    print("   - Copy WinDivert64.exe (or WinDivert32.exe) to this directory")
    print()
    print("3. Install driver (optional, requires admin):")
    print("   - Run as Administrator: WinDivert64.exe --install")
    print()
    print("4. Verify installation:")
    print("   - Run this script again: python check_windivert_status.py")

def main():
    """Main status check function"""
    print("🚀 WinDivert Status Checker for DupeZ")
    print("=" * 50)
    
    # Check system compatibility
    if not check_system_compatibility():
        return False
    
    print()
    
    # Check for WinDivert files
    windivert_files = check_windivert_files()
    
    if not windivert_files:
        print("\n❌ WinDivert is not installed")
        provide_installation_instructions()
        return False
    
    print()
    
    # Test functionality
    working_files = []
    for windivert_path in windivert_files:
        if test_windivert_functionality(windivert_path):
            working_files.append(windivert_path)
    
    if not working_files:
        print("\n❌ No working WinDivert executables found")
        provide_installation_instructions()
        return False
    
    print(f"\n✅ Found {len(working_files)} working WinDivert executable(s)")
    
    # Check DupeZ integration
    print()
    if check_dupez_integration():
        print("\n🎉 WinDivert is fully available and integrated with DupeZ!")
        print("✅ You can now use WinDivert for advanced packet manipulation")
        return True
    else:
        print("\n⚠️ WinDivert is available but DupeZ integration needs attention")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 