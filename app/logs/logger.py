# app/logs/logger.py

import logging
import os
import time
from datetime import datetime
from typing import Optional
from logging.handlers import RotatingFileHandler

# Add privacy protection
try:
    from app.privacy.privacy_manager import privacy_manager
    PRIVACY_ENABLED = True
except ImportError:
    PRIVACY_ENABLED = False

# Configure logging
def setup_logging():
    """Setup logging configuration with enhanced error tracking"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Configure logging format with timestamps and performance info
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Setup file handler with rotation (fixed to prevent permission errors)
    try:
        file_handler = RotatingFileHandler(
            "logs/pulsedrop.log", 
            maxBytes=5*1024*1024,  # 5MB max file size (reduced)
            backupCount=3,  # Keep 3 backup files (reduced)
            encoding='utf-8',
            delay=True  # Delay file creation until first write
        )
        file_handler.setFormatter(logging.Formatter(log_format, date_format))
    except Exception as e:
        # Fallback to simple file handler if rotation fails
        print(f"Warning: Could not setup rotating log handler: {e}")
        file_handler = logging.FileHandler("logs/pulsedrop.log", encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # Setup console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear existing handlers to prevent duplicates
    logger.handlers.clear()
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Initialize logger
logger = setup_logging()

def log_info(message: str):
    """Log info message with performance tracking"""
    # Apply privacy protection if enabled
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("info_log", {"message": message})
    logger.info(f"[INFO] {message}")

def log_error(message: str, error: Optional[Exception] = None):
    """Log error message with enhanced error tracking"""
    if error:
        error_msg = f"[ERROR] {message}: {str(error)}"
        logger.error(error_msg)
        # Log stack trace for debugging
        import traceback
        logger.error(f"[STACK] {traceback.format_exc()}")
        
        # Apply privacy protection if enabled
        if PRIVACY_ENABLED:
            privacy_manager.log_privacy_event("error_log", {
                "message": message,
                "error": str(error)
            }, sensitive=True)
    else:
        logger.error(f"[ERROR] {message}")
        if PRIVACY_ENABLED:
            privacy_manager.log_privacy_event("error_log", {"message": message})

def log_warning(message: str):
    """Log warning message"""
    logger.warning(f"[WARNING] {message}")
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("warning_log", {"message": message})

def log_debug(message: str):
    """Log debug message"""
    logger.debug(f"[DEBUG] {message}")

def log_performance(operation: str, duration: float):
    """Log performance metrics"""
    logger.info(f"[PERFORMANCE] {operation} took {duration:.3f}s")
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("performance_log", {
            "operation": operation,
            "duration": duration
        })

def log_network_scan(devices_found: int, scan_duration: float):
    """Log network scan results"""
    logger.info(f"[NETWORK] Scan found {devices_found} devices in {scan_duration:.2f}s")
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("network_scan", {
            "devices_found": devices_found,
            "scan_duration": scan_duration
        }, sensitive=True)

def log_device_action(action: str, device_ip: str, success: bool):
    """Log device-specific actions"""
    status = "SUCCESS" if success else "FAILED"
    logger.info(f"[DEVICE] {action} {device_ip}: {status}")
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("device_action", {
            "action": action,
            "device_ip": device_ip,
            "success": success
        }, sensitive=True)

def log_security_event(event: str, details: str = ""):
    """Log security-related events"""
    logger.warning(f"[SECURITY] {event}: {details}")
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("security_event", {
            "event": event,
            "details": details
        }, sensitive=True)

def log_ui_event(event: str, component: str = ""):
    """Log UI-related events"""
    logger.debug(f"[UI] {component}: {event}")
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("ui_event", {
            "event": event,
            "component": component
        })

def log_startup():
    """Log application startup"""
    logger.info("=" * 50)
    logger.info("PulseDrop Pro Starting...")
    logger.info(f"Startup Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("application_startup", {
            "startup_time": datetime.now().isoformat()
        })

def log_shutdown():
    """Log application shutdown"""
    logger.info("=" * 50)
    logger.info("PulseDrop Pro Shutting Down...")
    logger.info(f"Shutdown Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)
    if PRIVACY_ENABLED:
        privacy_manager.log_privacy_event("application_shutdown", {
            "shutdown_time": datetime.now().isoformat()
        })
        # Clear privacy data on shutdown if enabled
        if privacy_manager.settings.clear_logs_on_exit:
            privacy_manager.clear_privacy_data()
