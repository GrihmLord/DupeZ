# DupeZ - Network Management & Security Tool

A comprehensive network management and security application with advanced device scanning, blocking capabilities, and PS5-specific network control features.

## 🚀 Features

### Core Functionality
- **Advanced Network Scanning**: Multi-method device discovery (ping, ARP, TCP, mDNS)
- **PS5-Specific Control**: Specialized blocking and unblocking for PlayStation 5 devices
- **Internet Drop Toggle**: Complete internet connectivity control with one-click toggle
- **Smart Mode**: Intelligent traffic analysis and automatic threat detection
- **Responsive GUI**: Modern, responsive interface with multiple themes

### Network Management
- **Device Discovery**: Comprehensive network device scanning and identification
- **Traffic Analysis**: Real-time network traffic monitoring and analysis
- **Blocking System**: Advanced device blocking with multiple methods (firewall, hosts, routes)
- **Bandwidth Control**: Network bandwidth limiting and restoration
- **Health Monitoring**: Device health tracking and protection

### Security Features
- **Privacy Protection**: Advanced privacy features and data protection
- **Firewall Integration**: Windows Firewall rule management
- **Route Table Control**: Network route manipulation for advanced blocking
- **DNS Management**: DNS cache and server control
- **ARP Cache Management**: ARP table manipulation and monitoring

## 📁 Project Structure

```
DupeZ/
├── app/                          # Main application
│   ├── core/                     # Core application logic
│   ├── gui/                      # GUI components
│   ├── network/                  # Network scanning and management
│   ├── firewall/                 # Firewall and blocking functionality
│   ├── health/                   # Device health monitoring
│   ├── privacy/                  # Privacy features
│   ├── ps5/                      # PS5-specific functionality
│   ├── plugins/                  # Plugin system
│   ├── themes/                   # UI themes
│   ├── config/                   # Configuration files
│   ├── utils/                    # Utility functions
│   ├── logs/                     # Logging system
│   └── assets/                   # Application assets
├── scripts/                      # Utility and maintenance scripts
│   ├── network/                  # Network restoration scripts
│   ├── maintenance/              # System maintenance scripts
│   └── development/              # Development utilities
├── tests/                        # Comprehensive test suite
│   ├── unit/                     # Unit tests
│   ├── integration/              # Integration tests
│   ├── gui/                      # GUI tests
│   ├── network/                  # Network functionality tests
│   └── fixtures/                 # Test data and fixtures
├── docs/                         # Documentation
│   ├── api/                      # API documentation
│   ├── developer/                # Developer guides
│   └── user_guides/              # User guides
├── tools/                        # Development tools
├── build/                        # Build artifacts
├── dist/                         # Distribution files
├── requirements.txt              # Python dependencies
├── run.py                       # Application launcher
└── README.md                    # Project documentation
```

## 🛠️ Installation

### Prerequisites
- Windows 10/11
- Python 3.8+
- Administrator privileges (for firewall control)

### Quick Start
```bash
git clone https://github.com/yourusername/DupeZ.git
cd DupeZ
pip install -r requirements.txt
python run.py
```

### Building Executable
```bash
python -m PyInstaller DupeZ.spec
```

## 🎮 Usage

### Basic Operation
1. **Launch Application**: Run `python run.py` from project root
2. **Scan Network**: Click "Scan Network" or wait for auto-scan
3. **Select Device**: Click on a device in the list to select it
4. **Toggle Blocking**: Use "Block Selected" button or right-click menu
5. **Smart Mode**: Enable intelligent automatic blocking based on traffic patterns

### Advanced Features
- **Network Topology**: Visual network map with device relationships
- **Traffic Analysis**: Real-time bandwidth monitoring and analysis
- **Plugin System**: Extensible architecture for custom functionality
- **Settings Management**: Persistent configuration and theme support

## 🔧 Configuration

### Settings File
Configuration is stored in `app/config/settings.json`:
```json
{
  "smart_mode": false,
  "auto_scan": true,
  "scan_interval": 300,
  "max_devices": 100,
  "log_level": "INFO",
  "theme": "dark"
}
```

### Themes
The application supports multiple themes:
- `app/themes/dark.qss`: Dark theme (default)
- `app/themes/light.qss`: Light theme
- `app/themes/hacker.qss`: Hacker theme
- `app/themes/rainbow.qss`: Rainbow theme

## 🐛 Troubleshooting

### Common Issues

**"No module named 'app'" Error**
- Run the application from the project root directory
- Use `python run.py` instead of `python app/main.py`

**Permission Denied Errors**
- Run the application as Administrator
- Ensure Windows Firewall is enabled

**Device Scanning Issues**
- Check your network connection
- Ensure no antivirus is blocking the application
- Try running as Administrator

### Logs
Application logs are written to:
- `logs/dupez.log`: Main application log
- `logs/errors.log`: Error-specific log
- `logs/performance.log`: Performance metrics

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
DupeZ/
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
pyinstaller DupeZ.spec
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
- **Email**: support@dupez.com
- **GitHub**: Create an issue on GitHub
- **Documentation**: Check the docs/ directory

---

**DupeZ** - Advanced Network Management & Security Tool 