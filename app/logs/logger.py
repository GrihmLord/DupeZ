#!/usr/bin/env python3
"""
Enhanced Logging System for DupeZ
Provides comprehensive logging with rotation, different levels, and error handling
"""

import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import json

class DupeZLogger:
    """Enhanced logger for DupeZ with rotation and multiple handlers"""
    
    def __init__(self, name: str = "DupeZ", log_dir: str = "logs"):
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Prevent duplicate handlers
        if not self.logger.handlers:
            self._setup_handlers()
        
        # Performance tracking
        self.performance_data = {}
        self.error_count = 0
        self.warning_count = 0
        
    def _setup_handlers(self):
        """Setup logging handlers with rotation and formatting"""
        try:
            # Console handler with Unicode support
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(name)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(console_formatter)
            
            # Configure stdout for Unicode support
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                console_handler.setStream(sys.stdout)
            except Exception as e:
                print(f"Warning: Could not configure Unicode support: {e}")
            
            self.logger.addHandler(console_handler)
            
            # File handler with rotation
            log_file = self.log_dir / f"dupez_{datetime.now().strftime('%Y-%m-%d')}.log"
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
            
            # Error file handler
            error_file = self.log_dir / "errors.log"
            error_handler = logging.handlers.RotatingFileHandler(
                error_file,
                maxBytes=5*1024*1024,  # 5MB
                backupCount=3,
                encoding='utf-8'
            )
            error_handler.setLevel(logging.ERROR)
            error_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s\n'
                'Exception: %(exc_info)s\n',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            error_handler.setFormatter(error_formatter)
            self.logger.addHandler(error_handler)
            
            # Performance log handler
            perf_file = self.log_dir / "performance.log"
            perf_handler = logging.handlers.RotatingFileHandler(
                perf_file,
                maxBytes=2*1024*1024,  # 2MB
                backupCount=2,
                encoding='utf-8'
            )
            perf_handler.setLevel(logging.INFO)
            perf_formatter = logging.Formatter(
                '%(asctime)s - PERFORMANCE - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            perf_handler.setFormatter(perf_formatter)
            self.logger.addHandler(perf_handler)
            
        except Exception as e:
            print(f"Failed to setup logging handlers: {e}")
            # Fallback to basic logging
            basic_handler = logging.StreamHandler()
            basic_handler.setLevel(logging.INFO)
            basic_formatter = logging.Formatter('%(levelname)s - %(message)s')
            basic_handler.setFormatter(basic_formatter)
            self.logger.addHandler(basic_handler)
    
    def debug(self, message: str, **kwargs):
        """Log debug message with optional context"""
        self._log_with_context(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message with optional context"""
        self._log_with_context(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message with optional context"""
        self.warning_count += 1
        self._log_with_context(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, exception: Optional[Exception] = None, **kwargs):
        """Log error message with optional exception and context"""
        self.error_count += 1
        if exception:
            self.logger.error(f"{message} - Exception: {str(exception)}", 
                            exc_info=True, extra=kwargs)
        else:
            self._log_with_context(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, exception: Optional[Exception] = None, **kwargs):
        """Log critical message with optional exception and context"""
        self.error_count += 1
        if exception:
            self.logger.critical(f"{message} - Exception: {str(exception)}", 
                               exc_info=True, extra=kwargs)
        else:
            self._log_with_context(logging.CRITICAL, message, **kwargs)
    
    def _log_with_context(self, level: int, message: str, **kwargs):
        """Log message with additional context"""
        if kwargs:
            context_str = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            full_message = f"{message} | Context: {context_str}"
        else:
            full_message = message
        self.logger.log(level, full_message)
    
    def performance(self, operation: str, duration: float, **kwargs):
        """Log performance metrics"""
        self.performance_data[operation] = duration
        context = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
        self.logger.info(f"PERFORMANCE: {operation} took {duration:.3f}s | {context}")
    
    def network_scan(self, devices_found: int, scan_duration: float, **kwargs):
        """Log network scan results"""
        self.logger.info(f"NETWORK_SCAN: Found {devices_found} devices in {scan_duration:.2f}s | "
                        f"{' | '.join([f'{k}={v}' for k, v in kwargs.items()])}")
    
    def ps5_detection(self, ps5_count: int, total_devices: int, **kwargs):
        """Log PS5 detection results"""
        self.logger.info(f"PS5_DETECTION: Found {ps5_count} PS5 devices out of {total_devices} total | "
                        f"{' | '.join([f'{k}={v}' for k, v in kwargs.items()])}")
    
    def blocking_event(self, action: str, target: str, success: bool, **kwargs):
        """Log blocking events"""
        status = "SUCCESS" if success else "FAILED"
        self.logger.info(f"BLOCKING: {action} {target} - {status} | "
                        f"{' | '.join([f'{k}={v}' for k, v in kwargs.items()])}")
    
    def settings_event(self, action: str, setting_name: str, success: bool, **kwargs):
        """Log settings events"""
        status = "SUCCESS" if success else "FAILED"
        self.logger.info(f"SETTINGS: {action} {setting_name} - {status} | "
                        f"{' | '.join([f'{k}={v}' for k, v in kwargs.items()])}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get logging statistics"""
        return {
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "performance_data": self.performance_data,
            "log_files": {
                "main": str(self.log_dir / f"dupez_{datetime.now().strftime('%Y-%m-%d')}.log"),
                "errors": str(self.log_dir / "errors.log"),
                "performance": str(self.log_dir / "performance.log")
            }
        }
    
    def cleanup_old_logs(self, days_to_keep: int = 30):
        """Clean up old log files"""
        try:
            cutoff_date = datetime.now().timestamp() - (days_to_keep * 24 * 60 * 60)
            for log_file in self.log_dir.glob("*.log*"):
                if log_file.stat().st_mtime < cutoff_date:
                    log_file.unlink()
                    self.info(f"Cleaned up old log file: {log_file}")
        except Exception as e:
            self.error(f"Failed to cleanup old logs: {e}")

# Global logger instance
logger = DupeZLogger()

# Convenience functions for backward compatibility
def log_info(message: str, **kwargs):
    """Log info message"""
    logger.info(message, **kwargs)

def log_error(message: str, exception: Optional[Exception] = None, **kwargs):
    """Log error message with comprehensive tracking"""
    try:
        # Import error tracker
        from app.logs.error_tracker import track_error, ErrorCategory, ErrorSeverity
        
        # Determine category from kwargs or message
        category = kwargs.get('category')
        severity = kwargs.get('severity', ErrorSeverity.MEDIUM)
        context = kwargs.get('context', {})
        user_action = kwargs.get('user_action')
        
        # Track error with comprehensive details
        track_error(message, exception, category, severity, context, user_action)
        
        # Also log to regular logger
        logger.error(message, exception, **kwargs)
        
    except Exception as e:
        print(f"Error in error logging: {e}")
        # Fallback to basic logging
        logger.error(message, exception, **kwargs)

def log_warning(message: str, **kwargs):
    """Log warning message"""
    logger.warning(message, **kwargs)

def log_debug(message: str, **kwargs):
    """Log debug message"""
    logger.debug(message, **kwargs)

def log_critical(message: str, exception: Optional[Exception] = None, **kwargs):
    """Log critical message"""
    logger.critical(message, exception, **kwargs)

def log_performance(operation: str, duration: float, **kwargs):
    """Log performance metrics"""
    logger.performance(operation, duration, **kwargs)

def log_network_scan(devices_found: int, scan_duration: float, **kwargs):
    """Log network scan results"""
    logger.network_scan(devices_found, scan_duration, **kwargs)

def log_ps5_detection(ps5_count: int, total_devices: int, **kwargs):
    """Log PS5 detection results"""
    logger.ps5_detection(ps5_count, total_devices, **kwargs)

def log_blocking_event(action: str, target: str, success: bool, **kwargs):
    """Log blocking events"""
    logger.blocking_event(action, target, success, **kwargs)

def log_settings_event(action: str, setting_name: str, success: bool, **kwargs):
    """Log settings events"""
    logger.settings_event(action, setting_name, success, **kwargs)
