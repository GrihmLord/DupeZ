# DupeZ iZurvive Map Integration

## Overview
This update integrates the full iZurvive DayZ map functionality directly into the DupeZ application, providing a professional-grade mapping experience for admin builds.

## Features

### 🗺️ Full iZurvive Integration
- **Real-time map loading** from iZurvive.com
- **Multiple map support**: Chernarus+, Livonia, Namalsk, Deer Isle, Valning, Esseker, Chiemsee, Rostow
- **Interactive map controls** with zoom, pan, and navigation
- **Professional mapping interface** identical to the web version

### 📍 Advanced Marker System
- **GPS coordinate system** for precise location tracking
- **Custom marker types**: Player, Base, Vehicle, Helicopter, Boat, Tent, Barrel, Crate, Medical, Military
- **Color-coded markers** for easy identification
- **Export/Import functionality** for data persistence

### 🎯 Enhanced Controls
- **Map selection dropdown** for switching between DayZ maps
- **GPS coordinate inputs** for manual coordinate entry
- **Refresh button** for updating map data
- **Marker management** with add/remove capabilities

## Installation

### Prerequisites
- Python 3.8+
- PyQt6
- PyQt6-WebEngine

### Quick Setup
1. **Install dependencies**:
   ```bash
   pip install -r requirements_webengine.txt
   ```

2. **Rebuild application**:
   - **Windows**: Run `rebuild_izurvive.bat` or `rebuild_izurvive.ps1`
   - **Manual**: Use PyInstaller with the provided configuration

## Usage

### Accessing the Map
1. Launch DupeZ application
2. Navigate to the "DayZ Map" tab
3. The iZurvive map will load automatically

### Adding Markers
1. Enter GPS coordinates in X/Y fields
2. Click "Update GPS" to set current location
3. Enter marker name and select type
4. Click "Add" to place marker on map

### Managing Maps
- Use the map dropdown to switch between different DayZ maps
- Click "Refresh Map" to reload the current map
- All markers are preserved when switching maps

### Data Management
- **Export**: Save all markers to JSON file
- **Import**: Load markers from previously exported files
- **Clear All**: Remove all markers (with confirmation)

## Technical Details

### Architecture
- **WebEngine Integration**: Uses PyQt6-WebEngine for seamless web content rendering
- **Real-time Loading**: Direct integration with iZurvive.com APIs
- **Responsive Design**: Adapts to different screen sizes and resolutions

### Performance
- **Optimized Loading**: Efficient map loading with progress indicators
- **Memory Management**: Smart cleanup of web resources
- **Caching**: Local storage of markers and preferences

### Compatibility
- **Windows**: Full support with admin privileges
- **Cross-platform**: Compatible with Linux and macOS
- **Browser Engine**: Uses Chromium-based rendering for maximum compatibility

## Troubleshooting

### Common Issues

#### Map Not Loading
- Ensure PyQt6-WebEngine is installed: `pip install PyQt6-WebEngine`
- Check internet connection for iZurvive.com access
- Verify admin privileges if running on Windows

#### Performance Issues
- Close other applications to free up system resources
- Ensure sufficient RAM (4GB+ recommended)
- Update graphics drivers for optimal WebEngine performance

#### Marker Issues
- Verify GPS coordinates are in correct format
- Check file permissions for marker data storage
- Ensure marker names are not empty

### Error Messages

#### "WebEngine not available"
- Install PyQt6-WebEngine: `pip install PyQt6-WebEngine`
- Restart application after installation

#### "Map load failed"
- Check internet connection
- Verify iZurvive.com is accessible
- Try refreshing the map

## Development

### File Structure
```
app/gui/
├── dayz_map_gui_new.py      # New iZurvive integration
├── dashboard.py              # Updated dashboard with new map
└── ...

rebuild_izurvive.bat         # Windows build script
rebuild_izurvive.ps1         # PowerShell build script
requirements_webengine.txt    # WebEngine dependencies
```

### Customization
- **Map URLs**: Modify `map_urls` dictionary in `load_izurvive_map()`
- **Marker Types**: Add new types to `marker_type_combo` items
- **Styling**: Update CSS styles in the UI setup methods

### Extending Functionality
- **Additional Maps**: Add new map entries to the dropdown
- **Custom Markers**: Implement new marker types and behaviors
- **Data Sources**: Integrate with other mapping services

## Support

### Getting Help
- Check the troubleshooting section above
- Review application logs for detailed error information
- Ensure all dependencies are properly installed

### Reporting Issues
- Include error messages and system information
- Specify the map being used when issues occur
- Provide steps to reproduce the problem

## License
This integration is part of the DupeZ application and follows the same licensing terms.

---

**Note**: This integration provides the same functionality as the professional iZurvive web interface, ensuring a consistent and reliable mapping experience for all users.
