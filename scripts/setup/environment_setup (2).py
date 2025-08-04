#!/usr/bin/env python3
"""
Environment Setup Script for PulseDrop Pro
Validates and configures the development environment
"""

import sys
import os
import subprocess
import platform
from pathlib import Path

def check_python_version():
    """Check if Python version is compatible"""
    print("🐍 Checking Python version...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"❌ Python {version.major}.{version.minor} is not supported. Please use Python 3.8+")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} is compatible")
    return True

def check_dependencies():
    """Check if required dependencies are installed"""
    print("\n📦 Checking dependencies...")
    
    required_packages = [
        'PyQt6',
        'psutil',
        'requests',
        'scapy'
    ]
    
    optional_packages = [
        'netifaces'  # Optional, requires C++ build tools
    ]
    
    missing_packages = []
    missing_optional = []
    
    for package in required_packages:
        try:
            __import__(package.lower().replace('-', '_'))
            print(f"✅ {package} is installed")
        except ImportError:
            print(f"❌ {package} is missing")
            missing_packages.append(package)
    
    for package in optional_packages:
        try:
            __import__(package.lower().replace('-', '_'))
            print(f"✅ {package} is installed (optional)")
        except ImportError:
            print(f"⚠️  {package} is missing (optional)")
            missing_optional.append(package)
    
    if missing_packages:
        print(f"\n⚠️  Missing required packages: {', '.join(missing_packages)}")
        print("Run: pip install -r requirements.txt")
        return False
    
    if missing_optional:
        print(f"\nℹ️  Missing optional packages: {', '.join(missing_optional)}")
        print("These are optional and won't affect core functionality")
    
    return True

def check_system_requirements():
    """Check system requirements"""
    print("\n💻 Checking system requirements...")
    
    # Check OS
    system = platform.system()
    if system == "Windows":
        print("✅ Windows detected")
    elif system == "Linux":
        print("✅ Linux detected")
    elif system == "Darwin":
        print("✅ macOS detected")
    else:
        print(f"⚠️  Unknown OS: {system}")
    
    # Check admin privileges (needed for firewall operations)
    try:
        if system == "Windows":
            result = subprocess.run(['net', 'session'], capture_output=True, text=True)
            if result.returncode == 0:
                print("✅ Running with administrator privileges")
            else:
                print("⚠️  Not running with administrator privileges (some features may not work)")
        else:
            result = subprocess.run(['sudo', '-n', 'true'], capture_output=True)
            if result.returncode == 0:
                print("✅ Running with sudo privileges")
            else:
                print("⚠️  Not running with sudo privileges (some features may not work)")
    except Exception as e:
        print(f"⚠️  Could not check privileges: {e}")
    
    return True

def check_network_interfaces():
    """Check available network interfaces"""
    print("\n🌐 Checking network interfaces...")
    
    try:
        import netifaces
        interfaces = netifaces.interfaces()
        
        print(f"✅ Found {len(interfaces)} network interfaces:")
        for interface in interfaces[:5]:  # Show first 5
            print(f"  📡 {interface}")
        
        if len(interfaces) > 5:
            print(f"  ... and {len(interfaces) - 5} more")
        
        return True
    except ImportError:
        print("⚠️  netifaces not available, skipping interface check")
        return True
    except Exception as e:
        print(f"❌ Error checking network interfaces: {e}")
        return False

def create_directories():
    """Create necessary directories"""
    print("\n📁 Creating directories...")
    
    directories = [
        'logs',
        'build',
        'dist',
        'tests/fixtures',
        'tests/performance',
        'scripts/maintenance',
        'docs/api',
        'config'
    ]
    
    for directory in directories:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        print(f"✅ Created {directory}")
    
    return True

def setup_logging():
    """Setup logging configuration"""
    print("\n📝 Setting up logging...")
    
    try:
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        
        # Create log files
        log_files = [
            'pulsedrop.log',
            'errors.log',
            'performance.log',
            'network.log'
        ]
        
        for log_file in log_files:
            log_path = log_dir / log_file
            if not log_path.exists():
                log_path.touch()
                print(f"✅ Created {log_file}")
        
        return True
    except Exception as e:
        print(f"❌ Error setting up logging: {e}")
        return False

def validate_project_structure():
    """Validate project structure"""
    print("\n🏗️  Validating project structure...")
    
    required_files = [
        'run.py',
        'requirements.txt',
        'README.md',
        'app/__init__.py',
        'app/main.py',
        'app/gui/dashboard.py',
        'app/network/enhanced_scanner.py',
        'app/firewall/blocker.py',
        'app/logs/logger.py'
    ]
    
    missing_files = []
    
    for file_path in required_files:
        if not Path(file_path).exists():
            missing_files.append(file_path)
            print(f"❌ Missing: {file_path}")
        else:
            print(f"✅ Found: {file_path}")
    
    if missing_files:
        print(f"\n⚠️  Missing {len(missing_files)} required files")
        return False
    
    return True

def run_basic_tests():
    """Run basic functionality tests"""
    print("\n🧪 Running basic tests...")
    
    try:
        # Add project root to Python path
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.path.insert(0, project_root)
        
        from app.logs.logger import log_info
        from app.network.enhanced_scanner import EnhancedNetworkScanner
        
        # Test logger
        log_info("Environment setup test")
        print("✅ Logger test passed")
        
        # Test scanner
        scanner = EnhancedNetworkScanner(max_threads=5, timeout=1)
        print("✅ Scanner initialization test passed")
        
        # Test basic scan
        devices = scanner._scan_arp_table()
        print(f"✅ ARP scan test passed (found {len(devices)} devices)")
        
        return True
    except Exception as e:
        print(f"❌ Basic tests failed: {e}")
        return False

def main():
    """Main setup function"""
    print("🚀 PulseDrop Pro Environment Setup")
    print("=" * 50)
    
    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        ("System Requirements", check_system_requirements),
        ("Network Interfaces", check_network_interfaces),
        ("Directories", create_directories),
        ("Logging", setup_logging),
        ("Project Structure", validate_project_structure),
        ("Basic Tests", run_basic_tests)
    ]
    
    passed = 0
    total = len(checks)
    
    for name, check_func in checks:
        try:
            if check_func():
                passed += 1
            else:
                print(f"❌ {name} check failed")
        except Exception as e:
            print(f"❌ {name} check failed with error: {e}")
    
    print("\n" + "=" * 50)
    print(f"📊 Setup Results: {passed}/{total} checks passed")
    
    if passed == total:
        print("🎉 Environment setup completed successfully!")
        print("\n🚀 You can now run the application with:")
        print("   python run.py")
        print("\n🧪 Run tests with:")
        print("   python -m pytest tests/")
    else:
        print("⚠️  Some checks failed. Please fix the issues above.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 