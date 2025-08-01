# app/logs/logger.py

import logging
import os
import time
from datetime import datetime
from typing import Optional

# Configure logging
def setup_logging():
    """Setup logging configuration with enhanced error tracking"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Configure logging format with timestamps and performance info
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Setup file handler with rotation
    file_handler = logging.FileHandler("logs/pulsedrop.log", encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # Setup console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Initialize logger
logger = setup_logging()

def log_info(message: str):
    """Log info message with performance tracking"""
    logger.info(f"[INFO] {message}")

def log_error(message: str, error: Optional[Exception] = None):
    """Log error message with enhanced error tracking"""
    if error:
        logger.error(f"[ERROR] {message}: {str(error)}")
        # Log stack trace for debugging
        import traceback
        logger.error(f"[STACK] {traceback.format_exc()}")
    else:
        logger.error(f"[ERROR] {message}")

def log_warning(message: str):
    """Log warning message"""
    logger.warning(f"[WARNING] {message}")

def log_debug(message: str):
    """Log debug message"""
    logger.debug(f"[DEBUG] {message}")

def log_performance(operation: str, duration: float):
    """Log performance metrics"""
    logger.info(f"[PERFORMANCE] {operation} took {duration:.3f}s")

def log_network_scan(devices_found: int, scan_duration: float):
    """Log network scan results"""
    logger.info(f"[NETWORK] Scan found {devices_found} devices in {scan_duration:.2f}s")

def log_device_action(action: str, device_ip: str, success: bool):
    """Log device-specific actions"""
    status = "SUCCESS" if success else "FAILED"
    logger.info(f"[DEVICE] {action} {device_ip}: {status}")

def log_security_event(event: str, details: str = ""):
    """Log security-related events"""
    logger.warning(f"[SECURITY] {event}: {details}")

def log_ui_event(event: str, component: str = ""):
    """Log UI-related events"""
    logger.debug(f"[UI] {component}: {event}")

def log_startup():
    """Log application startup"""
    logger.info("=" * 50)
    logger.info("PulseDrop Pro Starting...")
    logger.info(f"Startup Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

def log_shutdown():
    """Log application shutdown"""
    logger.info("=" * 50)
    logger.info("PulseDrop Pro Shutting Down...")
    logger.info(f"Shutdown Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)
