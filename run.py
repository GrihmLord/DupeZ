#!/usr/bin/env python3
"""
DupeZ Launcher
Run this script from the project root directory to start the application.
"""

import sys
import os
import traceback
import logging
import signal
import gc
import psutil
import threading
import time
import tempfile
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer, QThread, QObject, pyqtSignal

# Configure logging with rotation
from logging.handlers import RotatingFileHandler

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure logging with rotation to prevent log file bloat and reduce console spam
logging.basicConfig(
    level=logging.WARNING,  # Reduced from INFO to WARNING to reduce spam
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('logs/dupez.log', maxBytes=1024*1024, backupCount=5),
        # Only log warnings and errors to console, not info messages
        logging.StreamHandler(sys.stdout)
    ]
)

# Set specific logger levels to reduce spam
logging.getLogger('app.network').setLevel(logging.WARNING)
logging.getLogger('app.firewall').setLevel(logging.WARNING)
logging.getLogger('app.core').setLevel(logging.WARNING)
logging.getLogger('root').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class SingleInstance:
    """Ensure only one instance of the application is running"""
    
    def __init__(self, lockfile_name="dupez.lock"):
        self.lockfile = os.path.join(tempfile.gettempdir(), lockfile_name)
        self.fd = None
        
    def __enter__(self):
        try:
            # Check if lock file exists and if the process is still running
            if os.path.exists(self.lockfile):
                try:
                    with open(self.lockfile, 'r') as f:
                        pid = int(f.read().strip())
                    # Check if process is still running
                    if psutil.pid_exists(pid):
                        raise RuntimeError("Another instance of DupeZ is already running!")
                    else:
                        # Process is dead, remove stale lock file
                        os.unlink(self.lockfile)
                except (ValueError, IOError):
                    # Invalid lock file, remove it
                    os.unlink(self.lockfile)
            
            # Create lock file
            self.fd = open(self.lockfile, 'w')
            self.fd.write(str(os.getpid()))
            self.fd.flush()
            return self
            
        except (IOError, OSError) as e:
            if self.fd:
                self.fd.close()
            raise RuntimeError("Another instance of DupeZ is already running!")
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd:
            try:
                self.fd.close()
                if os.path.exists(self.lockfile):
                    os.unlink(self.lockfile)
            except:
                pass

logger = logging.getLogger(__name__)

class MemoryMonitor(QObject):
    """Monitor memory usage and trigger cleanup when needed"""
    memory_warning = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.process = psutil.Process()
        self.warning_threshold = 500 * 1024 * 1024  # 500MB
        self.critical_threshold = 800 * 1024 * 1024  # 800MB
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_memory)
        self.timer.start(30000)  # Check every 30 seconds
    
    def check_memory(self):
        """Check memory usage and trigger cleanup if needed"""
        try:
            memory_info = self.process.memory_info()
            memory_usage = memory_info.rss  # Resident Set Size
            
            if memory_usage > self.critical_threshold:
                logger.warning(f"Critical memory usage: {memory_usage / 1024 / 1024:.1f}MB")
                self.force_cleanup()
                self.memory_warning.emit()
            elif memory_usage > self.warning_threshold:
                logger.warning(f"High memory usage: {memory_usage / 1024 / 1024:.1f}MB")
                self.cleanup()
        except Exception as e:
            logger.error(f"Memory monitoring error: {e}")
    
    def cleanup(self):
        """Perform memory cleanup"""
        try:
            # Force garbage collection
            collected = gc.collect()
            logger.info(f"Garbage collection freed {collected} objects")
            
            # Clear Python cache
            import importlib
            for module in list(sys.modules.keys()):
                if hasattr(sys.modules[module], '__file__'):
                    try:
                        importlib.reload(sys.modules[module])
                    except:
                        pass
        except Exception as e:
            logger.error(f"Memory cleanup error: {e}")
    
    def force_cleanup(self):
        """Force aggressive memory cleanup"""
        try:
            # Multiple garbage collection passes
            for _ in range(3):
                gc.collect()
            
            # Clear caches
            if hasattr(sys, 'gettotalrefcount'):
                logger.info("Clearing reference counts")
            
            # Force memory compaction if available
            if hasattr(gc, 'collect'):
                gc.collect(2)  # Full collection
                
        except Exception as e:
            logger.error(f"Force cleanup error: {e}")

class ProcessMonitor(QObject):
    """Monitor system resources and application health"""
    
    def __init__(self):
        super().__init__()
        self.timer = QTimer()
        self.timer.timeout.connect(self.monitor_system)
        self.timer.start(60000)  # Check every minute
        self.last_check = time.time()
    
    def monitor_system(self):
        """Monitor system resources"""
        try:
            # Check CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 90:
                logger.warning(f"High CPU usage: {cpu_percent}%")
            
            # Check disk space
            disk_usage = psutil.disk_usage('/')
            if disk_usage.percent > 90:
                logger.warning(f"Low disk space: {disk_usage.percent}% used")
            
            # Check network connections
            connections = len(psutil.net_connections())
            if connections > 1000:
                logger.warning(f"High number of network connections: {connections}")
                
        except Exception as e:
            logger.error(f"System monitoring error: {e}")

class CrashHandler:
    """Handle application crashes gracefully"""
    
    @staticmethod
    def handle_exception(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions"""
        if issubclass(exc_type, KeyboardInterrupt):
            # Handle Ctrl+C gracefully
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        # Log the error to file only - no popups
        error_msg = f"Uncaught exception: {exc_type.__name__}: {exc_value}"
        logger.error(error_msg, exc_info=(exc_type, exc_value, exc_traceback))
        
        # Write detailed error to separate error log file
        try:
            with open('logs/errors.log', 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Exception: {exc_type.__name__}: {exc_value}\n")
                f.write(f"Traceback:\n{traceback.format_exc()}\n")
                f.write(f"{'='*80}\n")
        except Exception as log_error:
            logger.error(f"Failed to write to error log: {log_error}")
        
        # Don't show popups - just log and continue
        # This prevents popup spam while still capturing errors

def signal_handler(signum, frame):
    """Handle system signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    app = QApplication.instance()
    if app:
        app.quit()

def cleanup_resources():
    """Clean up resources before exit"""
    try:
        logger.info("Cleaning up resources...")
        
        # Clean up network scan resources
        try:
            from app.network.device_scan import cleanup_resources as cleanup_network
            cleanup_network()
        except:
            pass
        
        # Force garbage collection
        gc.collect()
        
        # Clear caches
        import importlib
        for module_name in list(sys.modules.keys()):
            if module_name.startswith('app.'):
                try:
                    del sys.modules[module_name]
                except:
                    pass
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

def initialize_application():
    """Initialize application with proper error handling"""
    try:
        logger.info("Initializing DupeZ...")
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Set up global exception handler
        sys.excepthook = CrashHandler.handle_exception
        
        # Add the current directory to Python path
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        # Import required modules
        from app.gui.dashboard import DupeZDashboard
        from app.core.controller import AppController
        
        # Set Qt attribute for WebEngine before creating QApplication
        from PyQt6.QtCore import Qt
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        
        # Create QApplication
        app = QApplication(sys.argv)
        app.setApplicationName("DupeZ")
        app.setApplicationVersion("1.0.0")
        
        # Initialize theme manager early and apply default theme
        try:
            from app.themes.theme_manager import theme_manager
            success = theme_manager.apply_theme("dark")
            if success:
                logger.info("Theme manager initialized and dark theme applied successfully")
            else:
                logger.error("Failed to apply dark theme")
        except Exception as e:
            logger.error(f"Failed to initialize theme manager: {e}")
        
        # Set up memory monitoring
        memory_monitor = MemoryMonitor()
        
        # Set up process monitoring
        process_monitor = ProcessMonitor()
        
        # Initialize controller with error handling
        try:
            controller = AppController()
            logger.info("Controller initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize controller: {e}")
            # Log error but don't show popup - just continue with None controller
            controller = None
        
        # Create dashboard with controller
        try:
            window = DupeZDashboard(controller=controller)
            window.show()
            logger.info("Dashboard created and shown successfully")
        except Exception as e:
            logger.error(f"Failed to create dashboard: {e}")
            raise
        
        # Set up cleanup on exit
        app.aboutToQuit.connect(cleanup_resources)
        
        # Set up auto-save timer
        from app.core.data_persistence import save_all_data
        from PyQt6.QtCore import QTimer
        
        auto_save_timer = QTimer()
        auto_save_timer.timeout.connect(save_all_data)
        auto_save_timer.start(30000)  # Save every 30 seconds
        logger.info("Auto-save timer initialized")
        
        # Set up memory warning handler
        memory_monitor.memory_warning.connect(lambda: logger.warning("Memory warning triggered"))
        
        # Start the application
        logger.info("Application started successfully")
        return app.exec()
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        print(f"Import error: {e}")
        print("Make sure you're running this script from the project root directory.")
        print("Current directory:", os.getcwd())
        return 1
    except Exception as e:
        logger.error(f"Error starting application: {e}")
        print(f"Error starting application: {e}")
        
        # Log error to file instead of showing popup
        try:
            with open('logs/startup_errors.log', 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Startup Error: {e}\n")
                f.write(f"Traceback:\n{traceback.format_exc()}\n")
                f.write(f"{'='*80}\n")
        except Exception as log_error:
            logger.error(f"Failed to write to startup error log: {log_error}")
        
        return 1

def main():
    """Main application entry point with advanced error handling"""
    try:
        # Ensure only one instance is running
        with SingleInstance():
            return initialize_application()
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Critical error in main: {e}")
        print(f"Critical error: {e}")
        return 1
    finally:
        cleanup_resources()

if __name__ == "__main__":
    sys.exit(main()) 