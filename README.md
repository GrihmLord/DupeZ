# ⚡ PulseDrop Pro ⚡

**Advanced LagSwitch Tool - Hacker Edition**

A powerful network lag control and device management tool designed for advanced users and network administrators.

## 🚀 LagSwitch Features

### Core LagSwitch Functionality
- **🎯 Advanced Device Targeting**: Precise control over network devices
- **🧠 Smart Mode**: Intelligent traffic analysis and automatic blocking
- **🚫 Mass Blocking**: Block multiple devices simultaneously
- **⚡ Quick Scan**: Rapid network analysis and device discovery
- **🔒 Security Features**: Hide sensitive data and encrypt information
- **📊 Real-time Monitoring**: Live traffic visualization and analysis
- **🎮 Gaming Device Detection**: Automatic identification of gaming consoles
- **🔍 Network Tools**: Port scanning, ping testing, and connectivity analysis

### Advanced LagSwitch Features
- **mDNS Discovery**: Enhanced device discovery using multicast DNS
- **Vendor Detection**: Identify device manufacturers from MAC addresses
- **Traffic Analysis**: Monitor bandwidth usage and connection patterns
- **Settings Persistence**: Save and restore application settings
- **Event-driven Architecture**: Real-time updates and notifications
- **Hotkey Support**: Quick access to all lagswitch functions

## 📋 Requirements

- Windows 10/11
- Python 3.8+
- Administrator privileges (for firewall control)

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/PulseDropPro.git
cd PulseDropPro
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the Application
```bash
python run.py
```

## 🎮 Usage

### Basic Operation
1. **Launch the Application**: Run `python run.py` from the project directory
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
- `Ctrl+Shift+T`: Toggle sidebar
- `Ctrl+G`: Toggle graph
- `Ctrl+C`: Clear data
- `Ctrl+Q`: Exit application
- `F1`: Show hotkeys help

### Smart Mode
Smart mode automatically detects and blocks devices based on:
- High traffic usage
- Suspicious connection patterns
- Burst traffic detection
- Connection limit violations

## 🏗️ Architecture

### Core Components
- **AppController**: Main application logic and state management
- **AppState**: Event-driven state management with observer pattern
- **SmartModeEngine**: Intelligent traffic analysis and automatic blocking
- **DeviceScanner**: Multi-threaded network device discovery
- **FirewallBlocker**: Windows Firewall and WinDivert integration

### GUI Components
- **PulseDropDashboard**: Main application window with menu and status bar
- **DeviceList**: Enhanced device list with context menus and real-time updates
- **PacketGraph**: Real-time traffic visualization with custom drawing
- **Sidebar**: Status indicators and control panel

### Network Components
- **DeviceScanner**: Parallel network scanning with ping and ARP
- **MDNSDiscovery**: Multicast DNS device discovery
- **NetworkHelpers**: Utility functions for network operations

## 🔧 Configuration

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

### Themes
The application supports both light and dark themes:
- `app/themes/dark.qss`: Dark theme
- `app/themes/light.qss`: Light theme

## 🐛 Troubleshooting

### Common Issues

**"No module named 'app'" Error**
- Run the application from the project root directory
- Use `python run.py` instead of `python app/main.py`

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

### Logs
Application logs are written to the console and can be found in the application output. Look for messages starting with timestamps like `[02:13:47]`.

## 🔒 Security

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

## 🧪 Development

### Project Structure
```
PulseDropPro/
├── app/
│   ├── core/           # Core application logic
│   ├── gui/            # User interface components
│   ├── network/        # Network scanning and discovery
│   ├── firewall/       # Firewall and packet filtering
│   ├── logs/           # Logging system
│   ├── utils/          # Utility functions
│   ├── themes/         # UI themes
│   └── config/         # Configuration files
├── tests/              # Unit tests
├── requirements.txt    # Python dependencies
└── run.py             # Application launcher
```

### Running Tests
```bash
python -m pytest tests/
```

### Building
```bash
pyinstaller PulseDropPro.spec
```

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📞 Support

For issues and questions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the logs for error messages

## 🎯 Roadmap

- [ ] Settings dialog implementation
- [ ] Advanced traffic analysis
- [ ] Network topology visualization
- [ ] Plugin system for custom rules
- [ ] Mobile companion app
- [ ] Cloud synchronization
- [ ] Advanced reporting features

---

**PulseDrop Pro** - Take control of your network lag! 🎮
