# DupeZ - DayZ Admin Application

## Project Structure

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
│   ├── tests/             # Test suite
│   └── tools/             # Development tools
├── docs/                   # Documentation
├── logs/                   # Application logs
├── .venv/                  # Python virtual environment
├── .git/                   # Git repository
├── .gitignore             # Git ignore rules
├── DupeZ.exe              # Main executable
├── requirements.txt        # Python dependencies
├── run.py                  # Main launcher script
└── README.md               # Project overview
```

## Core Application Files (Root Directory)

The root directory contains **ONLY** the essential DupeZ application files:

- **`DupeZ.exe`** - Main application executable
- **`run.py`** - Python launcher script
- **`requirements.txt`** - Python dependencies
- **`README.md`** - Project documentation

## Development Files

All development, testing, and utility files are organized in the `development/` directory:

- **`development/scripts/`** - Utility and maintenance scripts
- **`development/tests/`** - Comprehensive test suite
- **`development/tools/`** - Development and setup tools

## Application Structure

- **`app/`** - Main application code and modules
- **`config/`** - Configuration files
- **`docs/`** - User guides and documentation
- **`logs/`** - Application logs and debugging

## Performance Monitor

The Performance Monitor has been reorganized from a main dashboard tab to a popup dialog accessible through:
- **Settings Dialog** → **Advanced Tab** → **Performance Monitor** → **🔍 Open Performance Monitor**

This provides better organization and keeps the main dashboard focused on core network management functions.

This structure ensures that the root directory contains only the essential files needed to run DupeZ, while keeping all development and testing tools organized in their respective directories.
