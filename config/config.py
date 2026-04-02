#!/usr/bin/env python3
"""
DupeZ Configuration — Central settings for all modules.
"""

import os
from pathlib import Path

# ============================================================================
# APPLICATION
# ============================================================================

APP_NAME = "DupeZ"
APP_VERSION = "3.0.0"
APP_DESCRIPTION = "Network Disruption Toolkit for DayZ"
APP_AUTHOR = "GrihmLord"
APP_WEBSITE = "https://github.com/GrihmLord/DupeZ"

# ============================================================================
# PATHS
# ============================================================================

BASE_DIR = Path(__file__).parent
APP_DIR = BASE_DIR / "app"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
TEMP_DIR = BASE_DIR / "temp"

for directory in [LOGS_DIR, DATA_DIR, CONFIG_DIR, TEMP_DIR]:
    directory.mkdir(exist_ok=True)

# ============================================================================
# LOGGING
# ============================================================================

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5
LOG_FILE = LOGS_DIR / "dupez.log"
LOG_CONSOLE_ENABLED = True
LOG_FILE_ENABLED = True

UNICODE_SAFE_CONSOLE = True
EMOJI_REPLACEMENT_ENABLED = True

# ============================================================================
# GUI
# ============================================================================

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
WINDOW_MIN_WIDTH = 800
WINDOW_MIN_HEIGHT = 600
WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}"

DEFAULT_THEME = "dark"
AVAILABLE_THEMES = ["light", "dark", "hacker", "rainbow"]

PERF_MONITOR_UPDATE_INTERVAL = 1000
PERF_MONITOR_AUTO_SCAN_INTERVAL = 30000
PERF_MONITOR_MAX_PROCESSES = 50
PERF_MONITOR_LOG_LINES = 100

# ============================================================================
# NETWORK
# ============================================================================

NETWORK_SCAN_TIMEOUT = 1.0
NETWORK_SCAN_RANGE = "24"
NETWORK_MAX_DEVICES = 254
NETWORK_PING_COUNT = 1
NETWORK_PING_TIMEOUT = 100

NETWORK_MONITOR_INTERVAL = 1000
NETWORK_BANDWIDTH_MAX = 1000
NETWORK_LATENCY_TARGET = "8.8.8.8"
NETWORK_LATENCY_PORT = 53

FIREWALL_RULES_FILE = CONFIG_DIR / "firewall_rules.json"
FIREWALL_AUTO_UPDATE = True
FIREWALL_LOG_ENABLED = True

# ============================================================================
# GAMING / DAYZ
# ============================================================================

DAYZ_FIREWALL_RULES = [
    "DayZ_Server_Block",
    "DayZ_Client_Block",
    "DayZ_Voice_Block",
    "DayZ_Update_Block",
]

GAMING_NETWORK_PRIORITY = True
GAMING_BANDWIDTH_LIMIT = 100
GAMING_LATENCY_OPTIMIZATION = True

# ============================================================================
# SYSTEM MONITORING
# ============================================================================

SYSTEM_MONITOR_ENABLED = True
SYSTEM_MONITOR_INTERVAL = 1000
SYSTEM_TEMP_WARNING = 80
SYSTEM_TEMP_CRITICAL = 90
SYSTEM_MEMORY_WARNING = 80
SYSTEM_MEMORY_CRITICAL = 90
SYSTEM_DISK_WARNING = 85
SYSTEM_DISK_CRITICAL = 95

PROCESS_MONITOR_ENABLED = True
PROCESS_MAX_DISPLAY = 50
PROCESS_UPDATE_INTERVAL = 5000
PROCESS_KILL_CONFIRMATION = True

# ============================================================================
# SECURITY
# ============================================================================

ADMIN_REQUIRED = True
LOG_SENSITIVE_DATA = False
LOG_USER_ACTIONS = True

# ============================================================================
# DATA PERSISTENCE
# ============================================================================

AUTO_SAVE_ENABLED = True
AUTO_SAVE_INTERVAL = 300
AUTO_SAVE_ON_EXIT = True

ACCOUNTS_FILE = DATA_DIR / "dayz_accounts.json"
DEVICES_FILE = DATA_DIR / "network_devices.json"
SETTINGS_FILE = DATA_DIR / "user_settings.json"
HISTORY_FILE = DATA_DIR / "activity_history.json"

# ============================================================================
# EXPORT
# ============================================================================

EXPORT_FORMATS = ["txt", "csv", "json", "xlsx"]
EXPORT_DEFAULT_FORMAT = "csv"
EXPORT_INCLUDE_TIMESTAMP = True
EXPORT_INCLUDE_METADATA = True

# ============================================================================
# NOTIFICATIONS
# ============================================================================

DESKTOP_NOTIFICATIONS = True
NOTIFICATION_SOUND = True
NOTIFICATION_DURATION = 5000

ALERT_CPU_HIGH = 90
ALERT_MEMORY_HIGH = 90
ALERT_DISK_HIGH = 90
ALERT_NETWORK_HIGH = 80

# ============================================================================
# DEVELOPMENT (off by default)
# ============================================================================

DEBUG_MODE = False
DEVELOPMENT_MODE = False
TESTING_MODE = False

# ============================================================================
# ENVIRONMENT OVERRIDES
# ============================================================================

def load_environment_overrides():
    """Load configuration overrides from environment variables."""
    global DEBUG_MODE, DEVELOPMENT_MODE, LOG_LEVEL

    if os.getenv("DUPEZ_DEBUG", "").lower() in ("true", "1", "yes"):
        DEBUG_MODE = True

    if os.getenv("DUPEZ_DEVELOPMENT", "").lower() in ("true", "1", "yes"):
        DEVELOPMENT_MODE = True

    env_log = os.getenv("DUPEZ_LOG_LEVEL", "").upper()
    if env_log in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        LOG_LEVEL = env_log


load_environment_overrides()

# ============================================================================
# VALIDATION
# ============================================================================

def validate_config():
    """Validate configuration settings."""
    errors = []
    for directory in [LOGS_DIR, DATA_DIR, CONFIG_DIR, TEMP_DIR]:
        if not directory.exists():
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Failed to create directory {directory}: {e}")
    return errors


config_errors = validate_config()
if config_errors and DEBUG_MODE:
    raise ValueError(f"Configuration validation failed: {config_errors}")
