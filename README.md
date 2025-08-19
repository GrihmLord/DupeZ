# ⚡ DupeZ ⚡

**Advanced LagSwitch Tool - Hacker Edition v2.0.0**

A powerful, optimized network lag control and device management tool designed for advanced users and network administrators. **Fully optimized for stability and performance with clean, minimal UI.**

## 🚀 **Current Status - FULLY OPTIMIZED**

### ✅ **What's Been Accomplished**
- **🎯 Clean Home Screen**: Only essential "Network Scanner" tab remains
- **🚫 Performance Monitoring Removed**: All resource-heavy monitoring tabs eliminated
- **🌊 Traffic Graphs Removed**: No more traffic visualization overhead
- **⚡ Application Stability**: Fixed all crashes and "not responding" errors
- **🧹 Emoji-Free UI**: Professional, clean interface without visual clutter
- **💾 Memory Optimized**: Reduced memory usage and improved performance
- **🔒 Admin-Ready**: Works consistently whether run as user or administrator

### 🎯 **Current Home Screen Features**
- **Network Scanner**: Enhanced device discovery and management
- **Tips Ticker**: Scrolling tips at bottom (like NASDAQ ticker)
- **Sidebar**: Status indicators and control panel
- **Clean Menu**: Essential tools only, no unnecessary features

## 🚀 **LagSwitch Features**

### Core LagSwitch Functionality
- **🎯 Advanced Device Targeting**: Precise control over network devices
- **🧠 Smart Mode**: Intelligent traffic analysis and automatic blocking
- **🚫 Mass Blocking**: Block multiple devices simultaneously
- **⚡ Quick Scan**: Rapid network analysis and device discovery
- **🔒 Security Features**: Hide sensitive data and encrypt information
- **🎮 Gaming Device Detection**: Automatic identification of gaming consoles
- **🔍 Network Tools**: Port scanning, ping testing, and connectivity analysis

### Advanced LagSwitch Features
- **mDNS Discovery**: Enhanced device discovery using multicast DNS
- **Vendor Detection**: Identify device manufacturers from MAC addresses
- **Traffic Analysis**: Monitor bandwidth usage and connection patterns
- **Settings Persistence**: Save and restore application settings
- **Event-driven Architecture**: Real-time updates and notifications
- **Hotkey Support**: Quick access to all lagswitch functions

### 🔌 Plugin System
- **Custom Rules Engine**: Create custom blocking and monitoring rules
- **Plugin Manager**: Easy plugin installation, enabling, and management
- **Gaming Control Plugin**: Advanced gaming device management with time-based restrictions
- **Extensible Architecture**: Build your own plugins for specialized functionality
- **Rule Conditions**: Time-based, device-type, traffic threshold, and IP range conditions
- **Automated Actions**: Block, unblock, alert, and log based on custom rules

## 📋 **Requirements**

- Windows 10/11
- Python 3.8+
- Administrator privileges (for firewall control)

## 🛠️ **Installation**

### Option 1: Run from Source (Recommended for Development)

#### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/DupeZ.git
cd DupeZ
```

#### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 3. Run the Application
```bash
python -m app.main
```

**Note**: This runs the current source and reflects all latest UI optimizations.

### Option 2: Use the Executable (Recommended for Users)

#### 1. Run the Executable
- Double-click `DupeZ.exe`
- The executable includes all optimizations and doesn't require building

**Note**: The executable requires Administrator privileges for firewall control.

#### 2. Rebuild the Executable (to include latest changes)
```powershell
# Stop any running instances
taskkill /IM DupeZ.exe /F 2>$null
taskkill /IM python.exe /F 2>$null

# Clean build directories
rmdir /s /q build dist 2>$null
del DupeZ.spec 2>$null

# Install/upgrade PyInstaller
python -m pip install --upgrade pyinstaller

# Build the executable
pyinstaller --noconfirm --windowed --name DupeZ --icon app/assets/icon.ico --add-data "app/assets;app/assets" --add-data "app/config;app/config" --add-data "app/themes;app/themes" app/main.py
```

Then run:
```powershell
./dist/DupeZ/DupeZ.exe
```

## 🎮 **Usage**

### Basic Operation
1. **Launch the Application**: Run `python -m app.main` from the project directory
2. **Scan Network**: Click "Scan Network" or wait for auto-scan
3. **Select Device**: Click on a device in the list to select it
4. **Toggle Blocking**: Use the "Block Selected" button or right-click menu
5. **Smart Mode**: Enable intelligent automatic blocking based on traffic patterns

### LagSwitch Hotkeys
- `W` (default): Toggle blocking for selected device
- `Ctrl+S`: Scan network
- `Ctrl+Shift+S`: Quick scan
- `Ctrl+B`: Mass block all devices
- `Ctrl+U`: Mass unblock all devices
- `Ctrl+E`: Export device data
- `Ctrl+F`: Search devices
- `Ctrl+,`: Open settings
- `Ctrl+Shift+T`: Toggle sidebar
- `Ctrl+Q`: Exit application
- `F1`: Show hotkeys help

### Smart Mode
Smart mode automatically detects and blocks devices based on:
- High traffic usage
- Suspicious connection patterns
- Burst traffic detection
- Connection limit violations

## 🏗️ **Architecture**

### Core Components
- **AppController**: Main application logic and state management
- **AppState**: Event-driven state management with observer pattern
- **SmartModeEngine**: Intelligent traffic analysis and automatic blocking
- **DeviceScanner**: Multi-threaded network device discovery
- **FirewallBlocker**: Windows Firewall and WinDivert integration

### GUI Components
- **DupeZDashboard**: Main application window with clean, minimal interface
- **EnhancedDeviceList**: Advanced device list with context menus and real-time updates
- **Sidebar**: Status indicators and control panel
- **TipsTicker**: Scrolling tips display at bottom

### Network Components
- **DeviceScanner**: Parallel network scanning with ping and ARP
- **MDNSDiscovery**: Multicast DNS device discovery
- **NetworkHelpers**: Utility functions for network operations

## 🔧 **Configuration**

### Settings File
Configuration is stored in `app/config/settings.json`:
```json
{
  "smart_mode": false,
  "auto_scan": true,
  "scan_interval": 300,
  "max_devices": 100,
  "log_level": "INFO"
}
```

### Memory Optimization
Configuration for memory and storage optimization in `app/config/memory_optimization.json`:
```json
{
  "cleanup_interval": 45000,
  "monitoring_interval": 5000,
  "log_rotation_size_mb": 10,
  "max_log_files": 5
}
```

### Themes
The application supports both light and dark themes:
- `app/themes/dark.qss`: Dark theme (default)
- `app/themes/light.qss`: Light theme

## 🐛 **Troubleshooting**

### Common Issues

**"No module named 'app'" Error**
- Run the application from the project root directory
- Use `python -m app.main` instead of `python app/main.py`

**Permission Denied Errors**
- Run the application as Administrator
- Ensure Windows Firewall is enabled

**Hotkeys Not Working**
- Install the keyboard module: `pip install keyboard`
- Run as Administrator for global hotkey support

**Device Scanning Issues**
- Check your network connection
- Ensure no antivirus is blocking the application
- Try running as Administrator

**Application Crashes**
- Clear `__pycache__` directories: `Get-ChildItem -Recurse -Directory -Name "__pycache__" | Remove-Item -Recurse -Force`
- Ensure you have the latest code
- Run as Administrator

### Logs
Application logs are written to the console and can be found in the application output. Look for messages starting with timestamps like `[02:13:47]`.

## 🔒 **Security**

### Firewall Integration
The application uses Windows Firewall rules for device blocking:
- Creates temporary firewall rules for target devices
- Automatically removes rules when unblocking
- Falls back to WinDivert for advanced packet filtering

### Administrator Requirements
Some features require Administrator privileges:
- Firewall rule creation/removal
- Global hotkey registration
- Network interface monitoring

## 🧪 **Development**

### Project Structure
```
DupeZ/
├── app/                    # Main application code
│   ├── core/              # Core functionality
│   ├── firewall/          # Firewall and network security
│   ├── gui/               # User interface components
│   ├── logs/              # Logging system
│   └── plugins/           # Plugin system
├── config/                 # Configuration files
├── development/            # Development and testing tools
│   ├── scripts/           # Utility scripts
│   ├── tests/             # Comprehensive test suite
│   │   ├── gui/           # GUI component tests
│   │   ├── network/       # Network functionality tests
│   │   ├── performance/   # Performance and optimization tests
│   │   ├── integration/   # Integration tests
│   │   ├── unit/          # Unit tests
│   │   └── fixtures/      # Test data and fixtures
│   └── tools/             # Development and setup tools
├── docs/                   # Documentation
├── logs/                   # Application logs
├── .venv/                  # Python virtual environment
├── .git/                   # Git repository
├── .gitignore             # Git ignore rules
├── DupeZ.exe              # Main application executable
├── requirements.txt        # Python dependencies
├── config.py               # Centralized configuration
└── README.md               # Project overview
```

### Running Tests
```bash
# Run all tests
python -m pytest development/tests/

# Run specific test categories
python -m pytest development/tests/gui/          # GUI tests
python -m pytest development/tests/network/      # Network functionality tests
python -m pytest development/tests/performance/  # Performance tests
python -m pytest development/tests/integration/  # Integration tests
python -m pytest development/tests/unit/         # Unit tests

# Run with coverage
python -m pytest development/tests/ --cov=app --cov-report=html
```

### Building
See the Executable rebuild section above.

## 🎮 **DayZ Gaming Integration**

### Gaming Control Plugin
The application includes a DayZ Gaming Control Plugin that provides:
- **Server Management**: Whitelist/blacklist DayZ servers
- **Performance Monitoring**: Real-time gaming performance metrics
- **Network Optimization**: Automatic QoS and bandwidth prioritization
- **Time-based Rules**: Gaming restrictions during work/school hours

### Network Optimization for Gaming
- **Port Prioritization**: TCP/UDP ports 2302-2310 get highest priority
- **Bandwidth Reservation**: Configurable bandwidth reservation for gaming
- **Latency Optimization**: Automatic network path optimization
- **Anti-DDoS Protection**: Gaming-specific DDoS protection rules

## 🚀 **Improvement Roadmap**

### **Phase 1: Enhanced Network Management (Next 2-4 weeks)**
- [ ] **Multi-threaded Network Discovery**
  - Parallel ping scanning for faster results
  - Port scanning capabilities
  - Service detection
  - MAC address resolution and vendor identification

- [ ] **Network Topology Mapping**
  - Visual network map with device relationships
  - Connection path visualization
  - Bandwidth usage between devices

### **Phase 2: Advanced Gaming Control (Next 4-6 weeks)**
- [ ] **Multi-Game Support**
  - Configuration templates for different games
  - Auto-detection of running games
  - Game-specific network rules
  - Performance presets

- [ ] **Anti-Cheat Integration**
  - Process monitoring for suspicious activity
  - Memory scanning for modifications
  - Network traffic analysis for cheats

### **Phase 3: Advanced Monitoring & Analytics (Next 6-8 weeks)**
- [ ] **Real-Time Analytics**
  - Customizable widget system
  - Real-time graphs and charts
  - Historical data analysis
  - Performance trend identification

## 📄 **License**

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 **Contributing**

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📞 **Support**

For issues and questions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the logs for error messages

## 🎯 **Recent Achievements**

- [x] **Complete UI Cleanup**: Removed all performance monitoring and traffic graph tabs
- [x] **Application Stability**: Fixed all crashes and stability issues
- [x] **Memory Optimization**: Reduced memory usage and improved performance
- [x] **Clean Interface**: Professional, emoji-free UI design
- [x] **Admin Compatibility**: Consistent behavior regardless of privileges
- [x] **Performance Optimization**: Removed resource-heavy features
- [x] **Code Consolidation**: Unified launcher and simplified structure

---

**DupeZ v2.0.0** - Take control of your network lag with a clean, stable, and optimized interface! 🎮

*Last Updated: August 19, 2025 - Full UI optimization and stability improvements completed*
