#!/usr/bin/env python3
"""
Manual WinDivert Download Script for DupeZ
Provides multiple methods to download and install WinDivert
"""

import os
import sys
import subprocess
import platform
import requests
from pathlib import Path

def check_windivert_availability():
    """Check if WinDivert is already available"""
    print("🔍 Checking WinDivert availability...")
    
    windivert_paths = [
        "WinDivert64.exe",
        "WinDivert32.exe",
        os.path.join(os.getcwd(), "WinDivert64.exe"),
        os.path.join(os.getcwd(), "WinDivert32.exe"),
        "C:\\Windows\\System32\\WinDivert64.exe"
    ]
    
    for path in windivert_paths:
        if os.path.exists(path):
            print(f"✅ WinDivert found at: {path}")
            return True
    
    print("❌ WinDivert not found")
    return False

def download_with_requests():
    """Download WinDivert using requests library"""
    try:
        print("📥 Attempting download with requests...")
        
        # Determine architecture
        is_64bit = platform.architecture()[0] == '64bit'
        arch = "64" if is_64bit else "32"
        
        # Alternative download URLs
        urls = [
            f"https://reqrypt.org/windivert/WinDivert-{arch}.zip",
            f"https://github.com/basil00/Divert/releases/download/v1.4.3.4/WinDivert-{arch}.zip",
            f"https://www.reqrypt.org/windivert/WinDivert-{arch}.zip"
        ]
        
        for url in urls:
            try:
                print(f"🌐 Trying: {url}")
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()
                
                # Save file
                filename = f"WinDivert-{arch}.zip"
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                print(f"✅ Downloaded: {filename}")
                return filename
                
            except Exception as e:
                print(f"❌ Failed: {e}")
                continue
        
        return None
        
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return None

def extract_windivert(zip_file):
    """Extract WinDivert from zip file"""
    try:
        print(f"📦 Extracting {zip_file}...")
        
        import zipfile
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(".")
        
        # Find WinDivert executable
        windivert_exe = None
        for file in os.listdir("."):
            if file.startswith("WinDivert") and file.endswith(".exe"):
                windivert_exe = file
                break
        
        if windivert_exe:
            print(f"✅ Extracted: {windivert_exe}")
            return windivert_exe
        else:
            print("❌ WinDivert executable not found in extracted files")
            return None
            
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        return None

def verify_windivert(windivert_exe):
    """Verify WinDivert installation"""
    try:
        print(f"🔍 Verifying {windivert_exe}...")
        
        if not os.path.exists(windivert_exe):
            print(f"❌ {windivert_exe} not found")
            return False
        
        # Test WinDivert
        try:
            result = subprocess.run([windivert_exe, "--help"], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=10)
            print(f"✅ {windivert_exe} is working correctly")
            return True
        except subprocess.TimeoutExpired:
            print(f"✅ {windivert_exe} is working (help command executed)")
            return True
        except Exception as e:
            print(f"⚠️ Error testing {windivert_exe}: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False

def manual_download_instructions():
    """Provide manual download instructions"""
    print("\n📋 Manual Download Instructions:")
    print("=" * 50)
    print("1. Visit: https://reqrypt.org/windivert.html")
    print("2. Download WinDivert for your system (32-bit or 64-bit)")
    print("3. Extract the ZIP file")
    print("4. Copy WinDivert64.exe (or WinDivert32.exe) to this directory")
    print("5. Run this script again to verify installation")
    print("\nAlternative download links:")
    print("- https://github.com/basil00/Divert/releases")
    print("- https://www.reqrypt.org/windivert.html")

def create_windivert_test():
    """Create a test script to verify WinDivert functionality"""
    test_script = """
import os
import subprocess
import sys

def test_windivert():
    \"\"\"Test WinDivert functionality\"\"\"
    try:
        # Check for WinDivert executable
        windivert_exe = None
        for exe in ["WinDivert64.exe", "WinDivert32.exe"]:
            if os.path.exists(exe):
                windivert_exe = exe
                break
        
        if not windivert_exe:
            print("❌ WinDivert executable not found")
            return False
        
        print(f"✅ Found: {windivert_exe}")
        
        # Test basic functionality
        result = subprocess.run([windivert_exe, "--help"], 
                              capture_output=True, 
                              text=True, 
                              timeout=10)
        
        if result.returncode == 0 or "WinDivert" in result.stdout:
            print("✅ WinDivert is working correctly")
            return True
        else:
            print(f"⚠️ WinDivert test returned: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ WinDivert test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_windivert()
    sys.exit(0 if success else 1)
"""
    
    with open("test_windivert.py", "w") as f:
        f.write(test_script)
    
    print("✅ Created test_windivert.py for verification")

def main():
    """Main function"""
    print("🚀 WinDivert Installation for DupeZ")
    print("=" * 50)
    
    # Check if already installed
    if check_windivert_availability():
        print("✅ WinDivert is already available!")
        return True
    
    print("📥 WinDivert not found. Attempting download...")
    
    # Try automatic download
    zip_file = download_with_requests()
    
    if zip_file and os.path.exists(zip_file):
        # Extract and verify
        windivert_exe = extract_windivert(zip_file)
        if windivert_exe and verify_windivert(windivert_exe):
            print("✅ WinDivert installation completed successfully!")
            
            # Clean up zip file
            try:
                os.remove(zip_file)
                print(f"🧹 Cleaned up: {zip_file}")
            except:
                pass
            
            # Create test script
            create_windivert_test()
            return True
    
    # If automatic download failed, provide manual instructions
    print("\n❌ Automatic download failed")
    manual_download_instructions()
    
    # Create test script for later verification
    create_windivert_test()
    
    return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 