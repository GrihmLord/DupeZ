#!/usr/bin/env python3
"""
Stability Optimizer Module
Provides comprehensive stability improvements and crash prevention
"""

import gc
import psutil
import threading
import time
import weakref
from typing import Dict, List, Optional, Callable
from PyQt6.QtCore import QTimer, QObject, pyqtSignal
from app.logs.logger import log_info, log_error, log_warning

class StabilityOptimizer(QObject):
    """Comprehensive stability optimizer for DupeZ application"""
    
    # Signals for monitoring
    memory_warning = pyqtSignal(str)  # Memory usage warning
    stability_alert = pyqtSignal(str)  # Stability issue detected
    optimization_complete = pyqtSignal(str)  # Optimization completed
    
    def __init__(self):
        super().__init__()
        
        # Stability monitoring
        self.monitoring_active = False
        
        # Enhanced memory management for better stability
        self.memory_threshold_mb = 400  # Reduced threshold for more proactive cleanup
        self.critical_memory_threshold_mb = 600  # Reduced critical threshold
        self.last_memory_cleanup = time.time()
        self.memory_cleanup_interval = 20  # More frequent cleanup for stability
        
        # Performance tracking
        self.performance_metrics = {
            'memory_usage': [],
            'cpu_usage': [],
            'thread_count': [],
            'gc_collections': 0,
            'last_optimization': time.time()
        }
        
        # Resource cleanup
        self.cleanup_tasks = []
        self.weak_references = weakref.WeakSet()
        
        # Stability checks
        self.stability_checks = [
            self._check_memory_usage,
            self._check_thread_health,
            self._check_gc_health,
            self._check_system_resources
        ]
        
        # Initialize timers
        self._setup_timers()
        
    def _setup_timers(self):
        """Setup monitoring timers"""
        # Enhanced monitoring timers for better stability
        self.memory_timer = QTimer()
        self.memory_timer.timeout.connect(self._monitor_memory)
        self.memory_timer.start(5000)  # Check every 5 seconds for better stability
        
        # Stability check timer
        self.stability_timer = QTimer()
        self.stability_timer.timeout.connect(self._run_stability_checks)
        self.stability_timer.start(15000)  # More frequent stability checks
        
        # Cleanup timer
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self._perform_cleanup)
        self.cleanup_timer.start(30000)  # More frequent cleanup for stability
        
    def start_monitoring(self):
        """Start stability monitoring"""
        if self.monitoring_active:
            return
            
        self.monitoring_active = True
        
        log_info("Stability monitoring started")
        
    def stop_monitoring(self):
        """Stop stability monitoring"""
        try:
            # Stop all timers first
            if hasattr(self, 'memory_timer'):
                self.memory_timer.stop()
            if hasattr(self, 'stability_timer'):
                self.stability_timer.stop()
            if hasattr(self, 'cleanup_timer'):
                self.cleanup_timer.stop()
            
            # Set monitoring as inactive
            self.monitoring_active = False
                
            log_info("Stability monitoring stopped")
        except Exception as e:
            log_error(f"Error stopping stability monitoring: {e}")
                
    def _monitor_memory(self):
        """Monitor memory usage and trigger cleanup if needed"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            # Store memory usage
            self.performance_metrics['memory_usage'].append(memory_mb)
            if len(self.performance_metrics['memory_usage']) > 100:
                self.performance_metrics['memory_usage'] = self.performance_metrics['memory_usage'][-50:]
            
            # Check thresholds
            if memory_mb > self.critical_memory_threshold_mb:
                self.memory_warning.emit(f"Critical memory usage: {memory_mb:.1f}MB")
                self._emergency_cleanup()
            elif memory_mb > self.memory_threshold_mb:
                self.memory_warning.emit(f"High memory usage: {memory_mb:.1f}MB")
                self._trigger_cleanup()
                
        except Exception as e:
            log_error(f"Memory monitoring error: {e}")
            
    def _monitor_system_resources(self):
        """Monitor system resource usage"""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            self.performance_metrics['cpu_usage'].append(cpu_percent)
            if len(self.performance_metrics['cpu_usage']) > 100:
                self.performance_metrics['cpu_usage'] = self.performance_metrics['cpu_usage'][-50:]
            
            # Thread count
            thread_count = threading.active_count()
            self.performance_metrics['thread_count'].append(thread_count)
            if len(self.performance_metrics['thread_count']) > 100:
                self.performance_metrics['thread_count'] = self.performance_metrics['thread_count'][-50:]
                
            # Check for excessive resource usage
            if cpu_percent > 90:
                self.stability_alert.emit(f"High CPU usage: {cpu_percent:.1f}%")
                
            if thread_count > 100:
                self.stability_alert.emit(f"High thread count: {thread_count}")
                
        except Exception as e:
            log_error(f"System resource monitoring error: {e}")
            
    def _run_stability_checks(self):
        """Run all stability checks"""
        try:
            for check_func in self.stability_checks:
                try:
                    check_func()
                except Exception as e:
                    log_error(f"Stability check error in {check_func.__name__}: {e}")
                    
        except Exception as e:
            log_error(f"Stability checks error: {e}")
            
    def _check_memory_usage(self):
        """Check memory usage patterns"""
        try:
            if len(self.performance_metrics['memory_usage']) < 10:
                return
                
            recent_memory = self.performance_metrics['memory_usage'][-10:]
            avg_memory = sum(recent_memory) / len(recent_memory)
            
            # Check for memory leaks (consistent increase)
            if len(recent_memory) >= 5:
                trend = (recent_memory[-1] - recent_memory[0]) / len(recent_memory)
                if trend > 10:  # 10MB increase per check
                    self.stability_alert.emit(f"Potential memory leak detected: {trend:.1f}MB/check increase")
                    
        except Exception as e:
            log_error(f"Memory usage check error: {e}")
            
    def _check_thread_health(self):
        """Check thread health and stability"""
        try:
            if len(self.performance_metrics['thread_count']) < 5:
                return
                
            recent_threads = self.performance_metrics['thread_count'][-5:]
            avg_threads = sum(recent_threads) / len(recent_threads)
            
            # Check for thread explosion
            if avg_threads > 50:
                self.stability_alert.emit(f"High thread count detected: {avg_threads:.1f} average")
                
        except Exception as e:
            log_error(f"Thread health check error: {e}")
            
    def _check_gc_health(self):
        """Check garbage collector health"""
        try:
            # Force garbage collection and measure
            before_count = len(gc.get_objects())
            collected = gc.collect()
            after_count = len(gc.get_objects())
            
            self.performance_metrics['gc_collections'] += 1
            
            # Check if GC is effective
            if before_count - after_count < 100 and collected > 0:
                self.stability_alert.emit("Garbage collector may not be effective")
                
        except Exception as e:
            log_error(f"GC health check error: {e}")
            
    def _check_system_resources(self):
        """Check overall system resource availability"""
        try:
            # Check available memory
            available_memory = psutil.virtual_memory().available / 1024 / 1024
            if available_memory < 1000:  # Less than 1GB available
                self.stability_alert.emit(f"Low system memory: {available_memory:.1f}MB available")
                
            # Check disk space
            disk_usage = psutil.disk_usage('/')
            if disk_usage.percent > 90:
                self.stability_alert.emit(f"Low disk space: {disk_usage.percent:.1f}% used")
                
        except Exception as e:
            log_error(f"System resource check error: {e}")
            
    def _trigger_cleanup(self):
        """Trigger memory cleanup"""
        try:
            current_time = time.time()
            if current_time - self.last_memory_cleanup > self.memory_cleanup_interval:
                self._perform_cleanup()
                self.last_memory_cleanup = current_time
                
        except Exception as e:
            log_error(f"Cleanup trigger error: {e}")
            
    def _emergency_cleanup(self):
        """Emergency cleanup for critical memory situations"""
        try:
            log_warning("Performing emergency cleanup")
            
            # Force garbage collection multiple times
            for _ in range(3):
                gc.collect()
                
            # Clear performance metrics
            self.performance_metrics['memory_usage'] = self.performance_metrics['memory_usage'][-10:]
            self.performance_metrics['cpu_usage'] = self.performance_metrics['cpu_usage'][-10:]
            self.performance_metrics['thread_count'] = self.performance_metrics['thread_count'][-10:]
            
            # Run all cleanup tasks
            self._perform_cleanup()
            
            log_info("Emergency cleanup completed")
            
        except Exception as e:
            log_error(f"Emergency cleanup error: {e}")
            
    def _perform_cleanup(self):
        """Perform comprehensive cleanup"""
        try:
            log_info("Performing stability cleanup")
            
            # Run registered cleanup tasks
            for task in self.cleanup_tasks:
                try:
                    if callable(task):
                        task()
                except Exception as e:
                    log_error(f"Cleanup task error: {e}")
                    
            # Clear weak references
            self.weak_references.clear()
            
            # Force garbage collection
            collected = gc.collect()
            
            # Update metrics
            self.performance_metrics['last_optimization'] = time.time()
            
            log_info(f"Stability cleanup completed: {collected} objects collected")
            self.optimization_complete.emit(f"Cleanup completed: {collected} objects collected")
            
        except Exception as e:
            log_error(f"Cleanup error: {e}")
            
    def register_cleanup_task(self, task: Callable):
        """Register a cleanup task to be run during cleanup cycles"""
        try:
            if callable(task):
                self.cleanup_tasks.append(task)
                log_info(f"Registered cleanup task: {task.__name__}")
            else:
                log_warning("Attempted to register non-callable cleanup task")
                
        except Exception as e:
            log_error(f"Error registering cleanup task: {e}")
            
    def add_weak_reference(self, obj):
        """Add a weak reference for automatic cleanup"""
        try:
            self.weak_references.add(obj)
        except Exception as e:
            log_error(f"Error adding weak reference: {e}")
            
    def get_stability_report(self) -> Dict:
        """Get current stability status report"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return {
                'memory_usage_mb': memory_info.rss / 1024 / 1024,
                'cpu_usage_percent': psutil.cpu_percent(),
                'thread_count': threading.active_count(),
                'gc_collections': self.performance_metrics['gc_collections'],
                'last_optimization': self.performance_metrics['last_optimization'],
                'monitoring_active': self.monitoring_active,
                'cleanup_tasks_count': len(self.cleanup_tasks),
                'weak_references_count': len(self.weak_references)
            }
            
        except Exception as e:
            log_error(f"Error generating stability report: {e}")
            return {}
            
    def optimize_performance(self):
        """Trigger performance optimization"""
        try:
            log_info("Starting performance optimization")
            
            # Clear caches
            self._perform_cleanup()
            
            # Optimize garbage collection
            gc.set_threshold(700, 10, 10)  # More aggressive GC
            
            # Clear performance metrics
            self.performance_metrics['memory_usage'] = self.performance_metrics['memory_usage'][-20:]
            self.performance_metrics['cpu_usage'] = self.performance_metrics['cpu_usage'][-20:]
            self.performance_metrics['thread_count'] = self.performance_metrics['thread_count'][-20:]
            
            log_info("Performance optimization completed")
            self.optimization_complete.emit("Performance optimization completed")
            
        except Exception as e:
            log_error(f"Performance optimization error: {e}")

# Global stability optimizer instance
stability_optimizer = StabilityOptimizer()
