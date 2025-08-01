# ⚡ PulseDrop Pro - Executable Version ⚡

## 🚀 Quick Start

### Running the Executable

1. **Direct Launch**: Double-click `PulseDropPro.exe` in the `dist` folder
2. **Batch File**: Run `run_pulsedrop.bat` for automatic startup
3. **Command Line**: Execute `.\dist\PulseDropPro.exe` from the project directory

### System Requirements

- **OS**: Windows 10/11 (64-bit)
- **RAM**: Minimum 4GB, Recommended 8GB+
- **Storage**: 100MB free space
- **Permissions**: Administrator privileges required for firewall control
- **Network**: Active internet connection for device scanning

## 🔧 Installation & Setup

### First Run Setup

1. **Run as Administrator**: Right-click the executable and select "Run as administrator"
2. **Firewall Permissions**: Allow the application through Windows Firewall when prompted
3. **Network Access**: Grant network access permissions if requested

### Configuration

The application will automatically create configuration files in:
- `%APPDATA%\PulseDropPro\` (Settings and logs)
- `%USERPROFILE%\Documents\PulseDropPro\` (Exported data)

## 🎯 Features Available in Executable

### Core LagSwitch Features
- ✅ **Network Device Scanning**: Automatic discovery of all network devices
- ✅ **Mass Block/Unblock**: Control multiple devices simultaneously
- ✅ **Quick Scan**: Fast network scanning for immediate results
- ✅ **Device Search**: Find specific devices by IP, hostname, or MAC
- ✅ **Smart Mode**: Intelligent traffic analysis and automatic blocking
- ✅ **Hotkey Support**: Keyboard shortcuts for quick actions

### Advanced Features
- ✅ **Traffic Analysis**: Real-time network traffic monitoring
- ✅ **Network Topology**: Visual network map with device relationships
- ✅ **Plugin System**: Extensible architecture for custom rules
- ✅ **Settings Dialog**: Comprehensive configuration options
- ✅ **Data Export**: Export device lists and traffic reports

### Security Features
- ✅ **Encryption**: Secure data storage and transmission
- ✅ **Admin Checks**: Automatic privilege verification
- ✅ **Logging**: Comprehensive activity logging
- ✅ **Error Handling**: Graceful error recovery

## 🎮 Gaming Console Support

The executable includes enhanced detection for:
- **PlayStation 5**: Automatic PS5 detection and management
- **Xbox Series X/S**: Xbox console identification
- **Nintendo Switch**: Switch device recognition
- **PC Gaming**: Gaming PC optimization

## ⌨️ Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+S` | Scan Network |
| `Ctrl+Shift+S` | Quick Scan |
| `Ctrl+B` | Mass Block |
| `Ctrl+U` | Mass Unblock |
| `Ctrl+F` | Search Devices |
| `Ctrl+T` | Traffic Analysis |
| `Ctrl+N` | Network Topology |
| `Ctrl+P` | Plugin Manager |
| `Ctrl+E` | Export Data |
| `Ctrl+,` | Settings |
| `Ctrl+Q` | Exit |

## 🛠️ Troubleshooting

### Common Issues

**Application Won't Start**
- Ensure you're running as Administrator
- Check Windows Defender isn't blocking the executable
- Verify all dependencies are included (should be automatic)

**Network Scanning Issues**
- Check firewall settings
- Ensure network adapter is active
- Try running as Administrator

**Device Detection Problems**
- Restart the application
- Check network connectivity
- Verify target devices are online

**Performance Issues**
- Close other network-intensive applications
- Reduce scan frequency in settings
- Check available system resources

### Log Files

Log files are located in:
- `%APPDATA%\PulseDropPro\logs\`
- `logs\` (project directory)

Check these files for detailed error information.

## 🔒 Security Notes

### Administrator Privileges
- The application requires admin rights for firewall control
- This is normal and expected behavior
- No data is sent to external servers

### Network Access
- The application only accesses your local network
- No internet communication except for device scanning
- All data is stored locally

### Firewall Rules
- Temporary firewall rules are created during blocking
- Rules are automatically removed when unblocking
- No permanent changes to system firewall

## 📁 File Structure

```
PulseDropPro/
├── dist/
│   └── PulseDropPro.exe          # Main executable
├── run_pulsedrop.bat             # Easy launcher
├── PulseDropPro.spec             # PyInstaller configuration
├── file_version_info.txt         # Version information
└── EXECUTABLE_README.md          # This file
```

## 🔄 Updates

### Rebuilding the Executable

To create a new executable after code changes:

1. Install dependencies: `pip install -r requirements.txt`
2. Build executable: `python -m PyInstaller PulseDropPro.spec`
3. New executable will be in `dist\PulseDropPro.exe`

### Version Information

- **Current Version**: 1.0.0.0
- **Build Date**: Latest build
- **Python Version**: 3.12.10
- **PyInstaller Version**: 6.14.2

## 📞 Support

### Getting Help

1. **Check Logs**: Review log files for error details
2. **Read Documentation**: See main README.md for feature details
3. **Test Network**: Ensure network connectivity is working
4. **Restart Application**: Try closing and reopening the app

### Known Limitations

- **Windows Only**: Currently supports Windows 10/11 only
- **Admin Required**: Administrator privileges are mandatory
- **Local Network**: Only works on local network devices
- **Real-time Only**: No persistent blocking across restarts

## 🎯 Performance Tips

### Optimizing Performance

1. **Reduce Scan Frequency**: Lower scan intervals in settings
2. **Limit Device Count**: Set reasonable max device limits
3. **Close Unused Tabs**: Close topology/graph tabs if not needed
4. **Monitor Resources**: Check CPU/memory usage during operation

### Recommended Settings

- **Scan Interval**: 30-60 seconds
- **Max Devices**: 50-100 devices
- **Quick Scan**: Enable for faster results
- **Smart Mode**: Enable for automatic management

---

**⚡ PulseDrop Pro - Advanced LagSwitch Tool - Hacker Edition ⚡**

*Built with PyQt6, PyInstaller, and advanced networking technologies* 