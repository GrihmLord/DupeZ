# PulseDropPro Root Directory Organization

## Purpose
The root directory contains only the essential files needed to launch and build the PulseDropPro application.

## Root Directory Contents

### Main Launcher Files
- **`run.py`** - Main Python launcher for the GUI application
- **`run.bat`** - Windows batch launcher with dependency checks

### Configuration Files
- **`requirements.txt`** - Python dependencies for the main application
- **`.gitignore`** - Git ignore rules
- **`README.md`** - Project documentation

### Build and Distribution
- **`build/`** - Build artifacts and compiled files
- **`dist/`** - Distribution files

### Application Structure
- **`app/`** - Main application code
- **`logs/`** - Application logs
- **`scripts/`** - Utility scripts
- **`tests/`** - Test files and test configuration
- **`tools/`** - Development tools
- **`docs/`** - Documentation

## Organization Rules

### What Belongs in Root
- Main launcher files (`run.py`, `run.bat`)
- Core configuration files (`requirements.txt`, `.gitignore`)
- Project documentation (`README.md`)
- Build directories (`build/`, `dist/`)

### What Should Be Moved
- Test files → `tests/`
- Development tools → `tools/`
- Documentation → `docs/`
- Logs → `logs/`
- Scripts → `scripts/`

## Usage

### To Run the Application
```bash
# Using Python directly
python run.py

# Using batch file (Windows)
run.bat
```

### To Install Dependencies
```bash
pip install -r requirements.txt
```

### To Run Tests
```bash
cd tests
python run_tests.py
```

## File Organization Status

### ✅ Properly Organized
- `run.py` - Main launcher
- `run.bat` - Windows launcher
- `requirements.txt` - Dependencies
- `README.md` - Documentation
- `app/` - Application code
- `logs/` - Log files
- `scripts/` - Utility scripts
- `tests/` - Test files
- `tools/` - Development tools
- `docs/` - Documentation

### 📁 Directory Structure
```
PulseDropPro/
├── run.py                 # Main launcher
├── run.bat               # Windows launcher
├── requirements.txt      # Dependencies
├── README.md            # Documentation
├── .gitignore           # Git ignore
├── app/                 # Application code
├── logs/                # Application logs
├── scripts/             # Utility scripts
├── tests/               # Test files
├── tools/               # Development tools
├── docs/                # Documentation
├── build/               # Build artifacts
└── dist/                # Distribution files
```

This organization ensures that the root directory is clean and only contains essential files for launching and building the application. 