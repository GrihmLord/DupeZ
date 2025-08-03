# PulseDropPro - Network Management & Security Tool

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
PulseDropPro/
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
│   ├── user_guides/              # User documentation
│   ├── developer/                # Developer documentation
│   └── api/                      # API documentation
├── tools/                        # Development and deployment tools
├── dist/                         # Distribution files
├── build/                        # Build artifacts
└── logs/                         # Application logs
```

## 🛠️ Installation

### Prerequisites
- Python 3.8 or higher
- Windows 10/11 (for full functionality)
- Administrator privileges (for network operations)

### Quick Setup
```bash
# Clone the repository
git clone <repository-url>
cd PulseDropPro

# Install dependencies
pip install -r requirements.txt

# Run the application
python run.py
```

### Development Setup
```bash
# Install development dependencies
pip install -r requirements-test.txt

# Set up development environment
python tools/project_setup.py

# Run tests
python run_tests.py
```

## 🧪 Testing

### Test Categories
- **Unit Tests**: Core functionality testing
- **Integration Tests**: Component interaction testing
- **GUI Tests**: User interface automation testing
- **Network Tests**: Network functionality testing

### Running Tests
```bash
# Run all tests
python run_tests.py

# Run specific test categories
python run_tests.py --category unit
python run_tests.py --category gui
python run_tests.py --category network

# Run with verbose output
python run_tests.py --verbose

# Generate test report
python run_tests.py --report test_results.json
```

### Test Coverage
- Core application logic: 95%+
- GUI components: 90%+
- Network functionality: 85%+
- Firewall operations: 80%+

## 🔧 Configuration

### Application Settings
The application uses a comprehensive settings system stored in `app/config/settings.json`:

```json
{
  "smart_mode": true,
  "auto_scan": true,
  "scan_interval": 300,
  "theme": "dark",
  "auto_refresh": true,
  "max_threads": 20,
  "ping_timeout": 2,
  "require_admin": true
}
```

### Network Configuration
- **Scan Methods**: ping, ARP, TCP connect, mDNS
- **Blocking Methods**: Firewall rules, hosts file, route table
- **PS5 Detection**: MAC address, hostname, vendor identification

## 🎮 PS5 Network Control

### Features
- **Automatic PS5 Detection**: Identifies PS5 devices using multiple methods
- **Selective Blocking**: Block/unblock specific PS5 devices
- **Internet Drop**: Complete internet connectivity control
- **Ethernet Support**: Full Ethernet connection management
- **Restoration Tools**: Comprehensive PS5 network restoration

### Usage
1. **Scan Network**: Click "Scan Network" to discover devices
2. **Identify PS5**: PS5 devices are automatically highlighted
3. **Block PS5**: Use "Block Selected" to block specific PS5 devices
4. **Drop Internet**: Use "🌐 Drop Internet" to toggle internet connectivity
5. **Restore Connection**: Use restoration scripts in `scripts/network/`

### Restoration Scripts
- `restore_ethernet_connectivity.bat`: Restore PS5 Ethernet connectivity
- `unblock_mac_b40ad8b9bdb0.bat`: Unblock specific MAC address
- `fix_ps5_network_admin.bat`: Comprehensive PS5 network fix

## 🎨 GUI Features

### Themes
- **Light Theme**: Clean, bright interface
- **Dark Theme**: Modern dark mode
- **Hacker Theme**: Cyberpunk-inspired design
- **Rainbow Theme**: Dynamic color-changing interface

### Responsive Design
- **Adaptive Layout**: Automatically adjusts to window size
- **Dynamic Columns**: Table columns resize with window
- **Modern Styling**: Contemporary UI with smooth animations
- **Accessibility**: Keyboard navigation and screen reader support

## 🔒 Security Features

### Privacy Protection
- **Data Encryption**: Sensitive data encryption
- **Log Management**: Comprehensive logging with privacy controls
- **Session Security**: Secure session management
- **Access Control**: Role-based access control

### Network Security
- **Firewall Integration**: Windows Firewall rule management
- **Traffic Analysis**: Real-time network traffic monitoring
- **Threat Detection**: Automatic suspicious activity detection
- **Blocking Methods**: Multiple network blocking techniques

## 📊 Monitoring & Analytics

### Device Health
- **Health Monitoring**: Real-time device health tracking
- **Performance Metrics**: Network performance analysis
- **Traffic Patterns**: Network traffic pattern analysis
- **Alert System**: Automated alerting for issues

### Network Analytics
- **Traffic Analysis**: Comprehensive network traffic analysis
- **Bandwidth Monitoring**: Real-time bandwidth usage tracking
- **Device Statistics**: Detailed device statistics and metrics
- **Historical Data**: Network activity historical data

## 🚀 Development

### Code Quality
- **Type Hints**: Comprehensive type annotations
- **Error Handling**: Robust error handling throughout
- **Logging**: Comprehensive logging system
- **Documentation**: Extensive code documentation

### Development Tools
- **Test Suite**: Comprehensive automated testing
- **Code Linting**: Automated code quality checks
- **Build System**: Automated build and packaging
- **CI/CD**: Continuous integration and deployment

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

## 📝 Documentation

### User Guides
- **Getting Started**: Quick start guide
- **PS5 Network Control**: PS5-specific features guide
- **Network Management**: Network management guide
- **Security Features**: Security features guide

### Developer Documentation
- **API Reference**: Complete API documentation
- **Architecture**: System architecture overview
- **Development Guide**: Development setup and guidelines
- **Testing Guide**: Testing framework and guidelines

## 🐛 Troubleshooting

### Common Issues
1. **Permission Errors**: Run as Administrator
2. **Network Issues**: Check firewall settings
3. **PS5 Connection**: Use restoration scripts
4. **GUI Issues**: Check theme settings

### Support
- **Documentation**: Check the docs/ directory
- **Issues**: Report issues on GitHub
- **Community**: Join the community forum

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

We welcome contributions! Please see our contributing guidelines in the docs/developer/ directory.

## 📞 Support

For support and questions:
- **Email**: support@pulsedroppro.com
- **GitHub**: Create an issue on GitHub
- **Documentation**: Check the docs/ directory

---

**PulseDropPro** - Advanced Network Management & Security Tool 