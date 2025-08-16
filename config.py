#!/usr/bin/env python3
"""
DupeZ Configuration File
Central configuration for all application settings
"""

import os
from pathlib import Path

# ============================================================================
# APPLICATION SETTINGS
# ============================================================================

# Application Information
APP_NAME = "DupeZ"
APP_VERSION = "2.0.0"
APP_DESCRIPTION = "Advanced Network Management and Gaming Control Tool"
APP_AUTHOR = "DupeZ Team"
APP_WEBSITE = "https://dupez.com"

# ============================================================================
# PATHS AND DIRECTORIES
# ============================================================================

# Base paths
BASE_DIR = Path(__file__).parent
APP_DIR = BASE_DIR / "app"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
TEMP_DIR = BASE_DIR / "temp"

# Ensure directories exist
for directory in [LOGS_DIR, DATA_DIR, CONFIG_DIR, TEMP_DIR]:
    directory.mkdir(exist_ok=True)

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Logging settings
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5
LOG_FILE = LOGS_DIR / "dupez.log"
LOG_CONSOLE_ENABLED = True
LOG_FILE_ENABLED = True

# Unicode handling
UNICODE_SAFE_CONSOLE = True
EMOJI_REPLACEMENT_ENABLED = True

# ============================================================================
# GUI CONFIGURATION
# ============================================================================

# Window settings
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
WINDOW_MIN_WIDTH = 800
WINDOW_MIN_HEIGHT = 600
WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}"

# Theme settings
DEFAULT_THEME = "dark"
AVAILABLE_THEMES = ["light", "dark", "hacker", "rainbow"]
THEME_AUTO_SWITCH = False
THEME_SWITCH_INTERVAL = 3600  # seconds

# Performance Monitor settings
PERF_MONITOR_UPDATE_INTERVAL = 1000  # milliseconds
PERF_MONITOR_AUTO_SCAN_INTERVAL = 30000  # milliseconds
PERF_MONITOR_MAX_PROCESSES = 50
PERF_MONITOR_LOG_LINES = 100

# ============================================================================
# NETWORK CONFIGURATION
# ============================================================================

# Network scanning
NETWORK_SCAN_TIMEOUT = 1.0  # seconds
NETWORK_SCAN_RANGE = "24"  # subnet mask
NETWORK_MAX_DEVICES = 254
NETWORK_PING_COUNT = 1
NETWORK_PING_TIMEOUT = 100  # milliseconds

# Network monitoring
NETWORK_MONITOR_INTERVAL = 1000  # milliseconds
NETWORK_BANDWIDTH_MAX = 1000  # Mbps
NETWORK_LATENCY_TARGET = "8.8.8.8"
NETWORK_LATENCY_PORT = 53

# Firewall settings
FIREWALL_RULES_FILE = CONFIG_DIR / "firewall_rules.json"
FIREWALL_AUTO_UPDATE = True
FIREWALL_LOG_ENABLED = True

# ============================================================================
# GAMING CONTROL SETTINGS
# ============================================================================

# DayZ specific settings
DAYZ_FIREWALL_RULES = [
    "DayZ_Server_Block",
    "DayZ_Client_Block", 
    "DayZ_Voice_Block",
    "DayZ_Update_Block"
]

# Gaming network control
GAMING_NETWORK_PRIORITY = True
GAMING_BANDWIDTH_LIMIT = 100  # Mbps
GAMING_LATENCY_OPTIMIZATION = True

# ============================================================================
# PERFORMANCE SETTINGS
# ============================================================================

# System monitoring
SYSTEM_MONITOR_ENABLED = True
SYSTEM_MONITOR_INTERVAL = 1000  # milliseconds
SYSTEM_TEMP_WARNING = 80  # Celsius
SYSTEM_TEMP_CRITICAL = 90  # Celsius
SYSTEM_MEMORY_WARNING = 80  # percent
SYSTEM_MEMORY_CRITICAL = 90  # percent
SYSTEM_DISK_WARNING = 85  # percent
SYSTEM_DISK_CRITICAL = 95  # percent

# Process management
PROCESS_MONITOR_ENABLED = True
PROCESS_MAX_DISPLAY = 50
PROCESS_UPDATE_INTERVAL = 5000  # milliseconds
PROCESS_KILL_CONFIRMATION = True

# ============================================================================
# SECURITY SETTINGS
# ============================================================================

# Access control
ADMIN_REQUIRED = False
USER_PERMISSIONS = {
    "network_control": True,
    "firewall_management": True,
    "process_management": True,
    "system_monitoring": True,
    "gaming_control": True
}

# Logging security
LOG_SENSITIVE_DATA = False
LOG_USER_ACTIONS = True
LOG_SYSTEM_CHANGES = True

# ============================================================================
# DATA PERSISTENCE
# ============================================================================

# Auto-save settings
AUTO_SAVE_ENABLED = True
AUTO_SAVE_INTERVAL = 300  # seconds
AUTO_SAVE_ON_EXIT = True

# Data files
ACCOUNTS_FILE = DATA_DIR / "dayz_accounts.json"
DEVICES_FILE = DATA_DIR / "network_devices.json"
SETTINGS_FILE = DATA_DIR / "user_settings.json"
HISTORY_FILE = DATA_DIR / "activity_history.json"

# ============================================================================
# DEVELOPMENT SETTINGS
# ============================================================================

# Debug mode
DEBUG_MODE = False
DEVELOPMENT_MODE = False
TESTING_MODE = False

# Development tools
PROFILING_ENABLED = False
MEMORY_LEAK_DETECTION = False
PERFORMANCE_PROFILING = False

# ============================================================================
# EXPORT AND REPORTING
# ============================================================================

# Export formats
EXPORT_FORMATS = ["txt", "csv", "json", "xml"]
EXPORT_DEFAULT_FORMAT = "csv"
EXPORT_INCLUDE_TIMESTAMP = True
EXPORT_INCLUDE_METADATA = True

# Report generation
REPORT_GENERATION_ENABLED = True
REPORT_TEMPLATES_DIR = CONFIG_DIR / "report_templates"
REPORT_AUTO_GENERATE = False
REPORT_SCHEDULE = "daily"  # daily, weekly, monthly

# ============================================================================
# INTEGRATION SETTINGS
# ============================================================================

# External services
EXTERNAL_API_ENABLED = False
EXTERNAL_API_KEY = ""
EXTERNAL_API_URL = ""

# Plugin system
PLUGIN_SYSTEM_ENABLED = True
PLUGIN_DIR = BASE_DIR / "plugins"
PLUGIN_AUTO_LOAD = True
PLUGIN_VERIFICATION = True

# ============================================================================
# NOTIFICATION SETTINGS
# ============================================================================

# Desktop notifications
DESKTOP_NOTIFICATIONS = True
NOTIFICATION_SOUND = True
NOTIFICATION_DURATION = 5000  # milliseconds

# Alert thresholds
ALERT_CPU_HIGH = 90  # percent
ALERT_MEMORY_HIGH = 90  # percent
ALERT_DISK_HIGH = 90  # percent
ALERT_NETWORK_HIGH = 80  # percent

# ============================================================================
# BACKUP AND RECOVERY
# ============================================================================

# Backup settings
BACKUP_ENABLED = True
BACKUP_INTERVAL = 86400  # seconds (24 hours)
BACKUP_RETENTION_DAYS = 30
BACKUP_DIR = BASE_DIR / "backups"

# Recovery options
RECOVERY_POINTS_ENABLED = True
RECOVERY_AUTO_CREATE = True
RECOVERY_MAX_POINTS = 10

# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def validate_config():
    """Validate configuration settings"""
    errors = []
    
    # Check required directories
    for directory in [LOGS_DIR, DATA_DIR, CONFIG_DIR, TEMP_DIR]:
        if not directory.exists():
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Failed to create directory {directory}: {e}")
    
    # Validate numeric values
    numeric_settings = [
        ("WINDOW_WIDTH", WINDOW_WIDTH, 100, 3000),
        ("WINDOW_HEIGHT", WINDOW_HEIGHT, 100, 2000),
        ("PERF_MONITOR_UPDATE_INTERVAL", PERF_MONITOR_UPDATE_INTERVAL, 100, 10000),
        ("NETWORK_SCAN_TIMEOUT", NETWORK_SCAN_TIMEOUT, 0.1, 10.0),
        ("SYSTEM_TEMP_WARNING", SYSTEM_TEMP_WARNING, 0, 200),
        ("SYSTEM_TEMP_CRITICAL", SYSTEM_TEMP_CRITICAL, 0, 200)
    ]
    
    for name, value, min_val, max_val in numeric_settings:
        if not min_val <= value <= max_val:
            errors.append(f"{name} must be between {min_val} and {max_val}, got {value}")
    
    # Validate file paths
    file_settings = [
        ("LOG_FILE", LOG_FILE),
        ("FIREWALL_RULES_FILE", FIREWALL_RULES_FILE),
        ("ACCOUNTS_FILE", ACCOUNTS_FILE)
    ]
    
    for name, file_path in file_settings:
        if not file_path.parent.exists():
            errors.append(f"Parent directory for {name} does not exist: {file_path.parent}")
    
    return errors

def get_config_summary():
    """Get a summary of current configuration"""
    return {
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "debug_mode": DEBUG_MODE,
        "development_mode": DEVELOPMENT_MODE,
        "log_level": LOG_LEVEL,
        "default_theme": DEFAULT_THEME,
        "network_scan_enabled": NETWORK_SCAN_TIMEOUT > 0,
        "performance_monitoring": SYSTEM_MONITOR_ENABLED,
        "auto_save": AUTO_SAVE_ENABLED,
        "backup_enabled": BACKUP_ENABLED
    }

# ============================================================================
# ENVIRONMENT OVERRIDES
# ============================================================================

def load_environment_overrides():
    """Load configuration overrides from environment variables"""
    global DEBUG_MODE, DEVELOPMENT_MODE, LOG_LEVEL
    
    # Environment variable overrides
    if os.getenv("DUPEZ_DEBUG"):
        DEBUG_MODE = os.getenv("DUPEZ_DEBUG").lower() in ("true", "1", "yes")
    
    if os.getenv("DUPEZ_DEVELOPMENT"):
        DEVELOPMENT_MODE = os.getenv("DUPEZ_DEVELOPMENT").lower() in ("true", "1", "yes")
    
    if os.getenv("DUPEZ_LOG_LEVEL"):
        log_level = os.getenv("DUPEZ_LOG_LEVEL").upper()
        if log_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            LOG_LEVEL = log_level

# Load environment overrides
load_environment_overrides()

# Validate configuration on import
config_errors = validate_config()
if config_errors:
    print(f"Configuration validation errors: {config_errors}")
    if DEBUG_MODE:
        raise ValueError(f"Configuration validation failed: {config_errors}")

if __name__ == "__main__":
    # Print configuration summary
    summary = get_config_summary()
    print("DupeZ Configuration Summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    if config_errors:
        print(f"\nConfiguration errors: {config_errors}")
    else:
        print("\nConfiguration is valid!")
