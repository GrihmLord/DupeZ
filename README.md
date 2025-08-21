# 🚀 DupeZ - Advanced Network Control & DayZ Integration

## 🎯 Overview

DupeZ is a professional-grade network control application with integrated DayZ mapping capabilities. Built for power users and administrators, it provides advanced network management tools alongside the full iZurvive DayZ map experience.

## ✨ Features

### 🌐 Network Control
- **Advanced Device Scanning**: Comprehensive network device discovery
- **Smart Blocking**: Intelligent device targeting and management
- **Network Manipulation**: Advanced traffic control and optimization
- **Real-time Monitoring**: Live network status and performance tracking

### 🗺️ DayZ Integration
- **Full iZurvive Maps**: Real-time loading from iZurvive.com
- **Multiple Map Support**: Chernarus+, Livonia, Namalsk, Deer Isle, Valning, Esseker, Chiemsee, Rostow
- **Interactive Mapping**: Zoom, pan, and navigate like the web version
- **Marker System**: GPS coordinates and custom marker management
- **Data Export/Import**: Save and load your mapping data

### 🎮 Gaming Features
- **DayZ Account Tracking**: Monitor and manage DayZ accounts
- **Gaming Dashboard**: Specialized tools for DayZ players
- **Performance Optimization**: Network optimization for gaming

## 🚀 Quick Start

### 1. Launch Application
```
dist\DupeZ_izurvive.exe
```

### 2. Access Features
- **Network Scanner**: Main device discovery and management
- **DayZ Map**: Full iZurvive integration with interactive maps
- **Gaming Tools**: DayZ-specific utilities and optimizations
- **Network Control**: Advanced traffic management

## 📁 Project Structure

```
DupeZ/
├── 📱 app/                          # Main application code
│   ├── 🎨 gui/                     # User interface components
│   │   ├── dashboard.py            # Main dashboard
│   │   ├── dayz_map_gui_new.py    # iZurvive integration
│   │   └── ...                     # Other GUI components
│   ├── 🔧 core/                    # Core functionality
│   ├── 🛡️ firewall/               # Network security tools
│   ├── 🌐 network/                 # Network management
│   └── ⚙️ config/                  # Configuration files
├── 🏗️ build/                       # Build artifacts
├── 📦 dist/                        # Distribution files
│   └── DupeZ_izurvive.exe         # Main executable
├── 📚 docs/                        # Documentation
│   ├── 📋 build_scripts/           # Build and deployment scripts
│   │   ├── rebuild_izurvive.bat   # Windows build script
│   │   └── rebuild_izurvive.ps1   # PowerShell build script
│   └── 🔗 integration/             # Integration documentation
│       ├── IZURVIVE_INTEGRATION_README.md
│       └── BUILD_SUCCESS_README.md
├── 🧪 development/                 # Development tools
│   └── tests/                      # Test files
│       └── test_izurvive.py       # iZurvive integration test
├── 📋 requirements/                 # Dependencies
│   ├── requirements.txt            # Main requirements
│   └── requirements_webengine.txt  # WebEngine dependencies
└── 📖 README.md                    # This file
```

## 🔧 Requirements

### System Requirements
- **OS**: Windows 10/11 (64-bit)
- **RAM**: 4GB+ recommended
- **Storage**: 500MB+ free space
- **Network**: Internet connection for iZurvive maps

### Python Dependencies
- **Python**: 3.8+
- **PyQt6**: 6.4.0+
- **PyQt6-WebEngine**: 6.4.0+ (for iZurvive integration)

## 🛠️ Installation

### Option 1: Use Pre-built Executable
1. Download `DupeZ_izurvive.exe` from the `dist/` folder
2. Run the executable (no installation required)
3. Enjoy full functionality immediately

### Option 2: Build from Source
1. Install Python dependencies:
   ```bash
   pip install -r requirements/requirements_webengine.txt
   ```

2. Run build script:
   ```bash
   # Windows
   docs\build_scripts\rebuild_izurvive.bat
   
   # PowerShell
   docs\build_scripts\rebuild_izurvive.ps1
   ```

## 🎮 Using DayZ Maps

### Accessing Maps
1. Launch DupeZ
2. Navigate to "DayZ Map" tab
3. Select your preferred map from the dropdown
4. Use mouse wheel to zoom, drag to pan

### Adding Markers
1. Enter GPS coordinates in X/Y fields
2. Click "Update GPS" to set location
3. Enter marker name and select type
4. Click "Add" to place marker

### Managing Data
- **Export**: Save markers to JSON file
- **Import**: Load previously saved data
- **Clear**: Remove all markers (with confirmation)

## 🔍 Network Features

### Device Discovery
- **Quick Scan**: Fast network overview
- **Deep Scan**: Comprehensive device analysis
- **Smart Detection**: Automatic device classification

### Network Control
- **Device Blocking**: Selective network access control
- **Traffic Management**: Advanced packet manipulation
- **Performance Monitoring**: Real-time network metrics

## 🆘 Troubleshooting

### iZurvive Maps Not Loading
- Ensure internet connection is active
- Check iZurvive.com accessibility
- Verify admin privileges if needed

### Performance Issues
- Close other applications
- Ensure sufficient RAM (4GB+)
- Update graphics drivers

### Build Issues
- Check Python version (3.8+)
- Verify PyQt6-WebEngine installation
- Run as administrator if needed

## 📚 Documentation

- **Integration Guide**: `docs/integration/IZURVIVE_INTEGRATION_README.md`
- **Build Guide**: `docs/integration/BUILD_SUCCESS_README.md`
- **Build Scripts**: `docs/build_scripts/`

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Make changes
4. Test thoroughly
5. Submit pull request

## 📄 License

This project is proprietary software. All rights reserved.

## 🎊 Acknowledgments

- **iZurvive Team**: For the excellent DayZ mapping service
- **PyQt6 Community**: For the robust GUI framework
- **DayZ Community**: For inspiration and feedback

---

**🎯 Ready to take control of your network and dominate DayZ? Launch DupeZ now!** 🚀🎮
