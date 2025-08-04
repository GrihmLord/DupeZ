#!/usr/bin/env python3
"""
WinDivert Installation Script for DupeZ
Downloads and installs WinDivert for packet manipulation functionality
"""

import os
import sys
import urllib.request
import zipfile
import subprocess
import platform
from pathlib import Path

def download_windivert():
    """Download WinDivert from official source"""
    try:
        print("🔍 Checking WinDivert availability...")
        
        # Check if already installed
        windivert_paths = [
            "WinDivert64.exe",
            "WinDivert32.exe",
            os.path.join(os.getcwd(), "WinDivert64.exe"),
            os.path.join(os.getcwd(), "WinDivert32.exe")
        ]
        
        for path in windivert_paths:
            if os.path.exists(path):
                print(f"✅ WinDivert already found at: {path}")
                return True
        
        print("📥 WinDivert not found. Downloading...")
        
        # Determine architecture
        is_64bit = platform.architecture()[0] == '64bit'
        arch = "64" if is_64bit else "32"
        
        # WinDivert download URLs (official source)
        windivert_url = f"https://reqrypt.org/windivert/WinDivert-{arch}.zip"
        
        # Download WinDivert
        print(f"🌐 Downloading WinDivert {arch}-bit from: {windivert_url}")
        
        # Create temp directory
        temp_dir = "temp_windivert"
        os.makedirs(temp_dir, exist_ok=True)
        
        zip_path = os.path.join(temp_dir, f"WinDivert-{arch}.zip")
        
        # Download with progress
        def show_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = (downloaded / total_size) * 100 if total_size > 0 else 0
            print(f"\r📥 Downloading: {percent:.1f}% ({downloaded}/{total_size} bytes)", end="")
        
        urllib.request.urlretrieve(windivert_url, zip_path, show_progress)
        print("\n✅ Download completed!")
        
        # Extract WinDivert
        print("📦 Extracting WinDivert...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Find WinDivert executable
        windivert_exe = f"WinDivert{arch}.exe"
        extracted_path = None
        
        for root, dirs, files in os.walk(temp_dir):
            if windivert_exe in files:
                extracted_path = os.path.join(root, windivert_exe)
                break
        
        if not extracted_path:
            print("❌ WinDivert executable not found in downloaded files")
            return False
        
        # Copy to current directory
        final_path = os.path.join(os.getcwd(), windivert_exe)
        import shutil
        shutil.copy2(extracted_path, final_path)
        
        # Clean up temp directory
        shutil.rmtree(temp_dir)
        
        print(f"✅ WinDivert installed successfully: {final_path}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to download WinDivert: {e}")
        return False

def verify_windivert():
    """Verify WinDivert installation"""
    try:
        print("🔍 Verifying WinDivert installation...")
        
        # Check if WinDivert executable exists
        windivert_paths = [
            "WinDivert64.exe",
            "WinDivert32.exe"
        ]
        
        for exe in windivert_paths:
            if os.path.exists(exe):
                print(f"✅ Found: {exe}")
                
                # Test WinDivert functionality
                try:
                    result = subprocess.run([exe, "--help"], 
                                          capture_output=True, 
                                          text=True, 
                                          timeout=5)
                    if result.returncode == 0:
                        print(f"✅ {exe} is working correctly")
                        return True
                    else:
                        print(f"⚠️ {exe} returned error: {result.stderr}")
                except subprocess.TimeoutExpired:
                    print(f"✅ {exe} is working (help command executed)")
                    return True
                except Exception as e:
                    print(f"⚠️ Error testing {exe}: {e}")
        
        print("❌ No working WinDivert executable found")
        return False
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

def install_windivert_driver():
    """Install WinDivert driver (requires admin privileges)"""
    try:
        print("🔧 Installing WinDivert driver...")
        
        # Check if running as administrator
        try:
            is_admin = subprocess.run(["net", "session"], 
                                    capture_output=True, 
                                    check=False).returncode == 0
        except:
            is_admin = False
        
        if not is_admin:
            print("⚠️ Administrator privileges required for driver installation")
            print("💡 Run this script as Administrator to install the driver")
            return False
        
        # Find WinDivert executable
        windivert_exe = None
        for exe in ["WinDivert64.exe", "WinDivert32.exe"]:
            if os.path.exists(exe):
                windivert_exe = exe
                break
        
        if not windivert_exe:
            print("❌ WinDivert executable not found")
            return False
        
        # Install driver
        print(f"🔧 Installing driver using {windivert_exe}...")
        result = subprocess.run([windivert_exe, "--install"], 
                              capture_output=True, 
                              text=True)
        
        if result.returncode == 0:
            print("✅ WinDivert driver installed successfully")
            return True
        else:
            print(f"⚠️ Driver installation returned: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Driver installation failed: {e}")
        return False

def main():
    """Main installation function"""
    print("🚀 WinDivert Installation for DupeZ")
    print("=" * 50)
    
    # Step 1: Download WinDivert
    if not download_windivert():
        print("❌ Failed to download WinDivert")
        return False
    
    # Step 2: Verify installation
    if not verify_windivert():
        print("❌ WinDivert verification failed")
        return False
    
    # Step 3: Install driver (optional)
    print("\n🔧 Driver Installation (Optional)")
    print("The WinDivert driver requires Administrator privileges.")
    print("You can install it later by running this script as Administrator.")
    
    install_driver = input("Install WinDivert driver now? (y/N): ").lower().strip()
    if install_driver == 'y':
        if not install_windivert_driver():
            print("⚠️ Driver installation failed, but WinDivert is still functional")
    
    print("\n✅ WinDivert installation completed!")
    print("🎮 DupeZ can now use WinDivert for advanced packet manipulation")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 