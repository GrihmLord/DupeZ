#!/usr/bin/env python3
"""
DupeZ Project Setup Tool
Creates the basic project structure and files
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def create_directory_structure():
    """Create the complete directory structure"""
    directories = [
        'scripts/network',
        'scripts/maintenance', 
        'scripts/development',
        'tests/unit',
        'tests/integration',
        'tests/gui',
        'tests/network',
        'tests/fixtures',
        'docs/user_guides',
        'docs/developer',
        'docs/api',
        'tools',
        'logs'
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✓ Created directory: {directory}")

def move_scattered_files():
    """Move scattered files to their proper locations"""
    file_moves = [
        # PS5 restoration scripts
        ('restore_ethernet_connectivity.bat', 'scripts/network/'),
        ('unblock_mac_b40ad8b9bdb0.bat', 'scripts/network/'),
        ('fix_ps5_network_admin.bat', 'scripts/network/'),
        ('clear_all_ps5_blocks_comprehensive.bat', 'scripts/network/'),
        ('clear_all_ps5_blocks_comprehensive.py', 'scripts/network/'),
        ('restore_ps5_internet.py', 'scripts/network/'),
        ('restore_ps5_internet.bat', 'scripts/network/'),
        ('fix_ps5_network.bat', 'scripts/network/'),
        ('fix_ps5_dhcp.py', 'scripts/network/'),
        
        # Test files
        ('test_gui_working.py', 'tests/gui/'),
        ('test_device_health.py', 'tests/unit/'),
        ('test_device_health_fast.py', 'tests/unit/'),
        ('test_device_health_ultra_fast.py', 'tests/unit/'),
        ('test_privacy_features.py', 'tests/unit/'),
        ('comprehensive_test.py', 'tests/integration/'),
        
        # Documentation
        ('DEVICE_HEALTH_PROTECTION.md', 'docs/user_guides/'),
        ('PRIVACY_FEATURES.md', 'docs/user_guides/'),
        ('ETHERNET_SUPPORT_SUMMARY.md', 'docs/user_guides/'),
        
        # Development tools
        ('cleanup_lock.py', 'scripts/maintenance/'),
        ('cleanup_pulsedrop_lock.py', 'scripts/maintenance/'),
    ]
    
    for source, destination in file_moves:
        if os.path.exists(source):
            try:
                shutil.move(source, destination)
                print(f"✓ Moved {source} to {destination}")
            except Exception as e:
                print(f"✗ Failed to move {source}: {e}")

def create_init_files():
    """Create __init__.py files for Python packages"""
    init_dirs = [
        'scripts',
        'scripts/network',
        'scripts/maintenance',
        'scripts/development',
        'tests',
        'tests/unit',
        'tests/integration',
        'tests/gui',
        'tests/network',
        'tests/fixtures',
        'docs',
        'docs/user_guides',
        'docs/developer',
        'docs/api',
        'tools'
    ]
    
    for directory in init_dirs:
        init_file = os.path.join(directory, '__init__.py')
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write('"""DupeZ {} module"""\n'.format(directory.replace('/', '.')))
            print(f"✓ Created {init_file}")

def install_dependencies():
    """Install project dependencies"""
    print("\nInstalling dependencies...")
    
    # Check if pip is available
    try:
        subprocess.run([sys.executable, '-m', 'pip', '--version'], 
                      check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("✗ pip not available")
        return
    
    # Install requirements
    if os.path.exists('requirements.txt'):
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
                          check=True)
            print("✓ Installed requirements.txt")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install requirements: {e}")
    
    # Install test requirements
    if os.path.exists('requirements-test.txt'):
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements-test.txt'],
                          check=True)
            print("✓ Installed test requirements")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install test requirements: {e}")

def create_config_files():
    """Create configuration files"""
    
    # Create pytest configuration
    pytest_config = """[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
"""
    
    with open('pytest.ini', 'w') as f:
        f.write(pytest_config)
    print("✓ Created pytest.ini")
    
    # Create .gitignore
    gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Logs
*.log
logs/

# Test reports
test_report.json
.coverage
htmlcov/

# Build artifacts
build/
dist/
*.spec

# OS
.DS_Store
Thumbs.db

# Application specific
*.lock
cleanup_*.py
"""
    
    with open('.gitignore', 'w') as f:
        f.write(gitignore_content)
    print("✓ Created .gitignore")

def create_development_scripts():
    """Create development and testing scripts"""
    
    # Create test runner script
    test_runner = '''#!/usr/bin/env python3
"""
Quick test runner for DupeZ
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests'))

from run_all_tests import main

if __name__ == '__main__':
    main()
'''
    
    with open('run_tests.py', 'w') as f:
        f.write(test_runner)
    print("✓ Created run_tests.py")
    
    # Create development setup script
    dev_setup = '''#!/usr/bin/env python3
"""
Development environment setup
"""

import subprocess
import sys

def setup_dev_environment():
    """Set up development environment"""
    print("Setting up DupeZ development environment...")
    
    # Install development dependencies
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements-test.txt'])
    
    # Run tests
    subprocess.run([sys.executable, 'run_tests.py'])
    
    print("Development environment setup complete!")

if __name__ == '__main__':
    setup_dev_environment()
'''
    
    with open('setup_dev.py', 'w') as f:
        f.write(dev_setup)
    print("✓ Created setup_dev.py")

def main():
    """Main setup function"""
    print("DupeZ Project Setup")
    print("="*40)
    
    # Create directory structure
    print("\nCreating directory structure...")
    create_directory_structure()
    
    # Move scattered files
    print("\nOrganizing files...")
    move_scattered_files()
    
    # Create __init__.py files
    print("\nCreating Python package files...")
    create_init_files()
    
    # Install dependencies
    print("\nInstalling dependencies...")
    install_dependencies()
    
    # Create configuration files
    print("\nCreating configuration files...")
    create_config_files()
    
    # Create development scripts
    print("\nCreating development scripts...")
    create_development_scripts()
    
    print("\n" + "="*40)
    print("Project setup complete!")
    print("\nNext steps:")
    print("1. Run tests: python run_tests.py")
    print("2. Start development: python setup_dev.py")
    print("3. Run the application: python run.py")
    print("="*40)

if __name__ == '__main__':
    main() 