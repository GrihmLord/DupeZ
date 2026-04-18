#!/usr/bin/env python3
"""
Enhanced Logging System for DupeZ.

Provides rotating file handlers (daily main log, error log, performance
log), a Windows-safe console handler, and module-level convenience
functions that form the public logging API.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.helpers import safe_console_message

__all__ = [
    "SafeConsoleHandler",
    "DupeZLogger",
    "logger",
    "log_info",
    "log_warning",
    "log_debug",
    "log_error",
    "log_critical",
    "log_performance",
    "log_network_scan",
    "log_device_detection",
    "log_blocking_event",
    "log_settings_event",
    "log_ps5_detection",
    "log_startup",
    "log_shutdown",
]


def _scrub_log_message(message: str) -> str:
    """Pass message through the secrets scrubber if available.

    Lazy import to avoid circular dependency — the secrets manager
    imports from logger, so we only resolve it at call time.
    """
    try:
        from app.core.secrets_manager import scrub_message
        return scrub_message(message)
    except Exception:
        return message


class SafeConsoleHandler(logging.StreamHandler):
    """Console handler that replaces non-ASCII characters on Windows."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if hasattr(record, "msg") and isinstance(record.msg, str):
                record.msg = safe_console_message(record.msg)
            super().emit(record)
        except Exception:
            super().emit(record)


def _resolve_log_directory() -> str:
    """Return a writable log directory for both dev and frozen exe."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
    return os.path.join(base, "logs")


class DupeZLogger:
    """Enhanced logger with rotation, multiple handlers, and thread-safe counters.

    The date-stamped main log file name is fixed at handler creation
    time.  If the application runs past midnight, entries still go to
    the original day's file until restart.
    """

    _DATEFMT = "%Y-%m-%d %H:%M:%S"
    _FILE_HANDLERS = [
        # (path_fn, maxBytes, backupCount, level, format_str)
        (
            lambda d: d / f"dupez_{datetime.now().strftime('%Y-%m-%d')}.log",
            10 * 1024 * 1024, 5, logging.DEBUG,
            "%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s",
        ),
        (
            lambda d: d / "errors.log",
            5 * 1024 * 1024, 3, logging.ERROR,
            "%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s\n"
            "Exception: %(exc_info)s\n",
        ),
        (
            lambda d: d / "performance.log",
            2 * 1024 * 1024, 2, logging.INFO,
            "%(asctime)s - PERFORMANCE - %(message)s",
        ),
    ]

    def __init__(self, name: str = "DupeZ", log_dir: str = "") -> None:
        self.name = name
        self.log_dir = Path(log_dir or _resolve_log_directory())
        self.log_dir.mkdir(exist_ok=True)

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        if not self.logger.handlers:
            self._setup_handlers()

        # Thread-safe performance / error tracking
        self._stats_lock = threading.Lock()
        self._performance_data: Dict[str, float] = {}
        self._error_count: int = 0
        self._warning_count: int = 0

    # ── Handler setup ─────────────────────────────────────────────

    def _setup_handlers(self) -> None:
        """Create console + rotating file handlers.

        Offsec CLI path: when ``DUPEZ_OFFSEC_CLI=1`` (or the process
        was started via ``python -m app.offsec.runner``), INFO-level
        chatter is routed to stderr instead of stdout so that the
        caller's JSON output on stdout remains machine-parseable.
        Warnings and errors always go to stderr regardless.
        """
        try:
            # Task #19: route INFO chatter to stderr for offsec CLI
            # paths so stdout can carry clean JSON to a consumer.
            _offsec_mode = (
                os.environ.get("DUPEZ_OFFSEC_CLI") == "1"
                or any("offsec" in a for a in sys.argv[:3])
            )
            _console_stream = sys.stderr if _offsec_mode else sys.stdout
            console_handler = SafeConsoleHandler(_console_stream)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
                datefmt=self._DATEFMT,
            ))

            try:
                _console_stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"Warning: Could not configure Unicode support: {e}",
                      file=sys.stderr)

            self.logger.addHandler(console_handler)

            for path_fn, max_bytes, backup_count, level, fmt in self._FILE_HANDLERS:
                handler = logging.handlers.RotatingFileHandler(
                    path_fn(self.log_dir),
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
                handler.setLevel(level)
                handler.setFormatter(logging.Formatter(fmt, datefmt=self._DATEFMT))
                self.logger.addHandler(handler)

        except Exception as e:
            print(f"Failed to setup logging handlers: {e}")
            basic = logging.StreamHandler()
            basic.setLevel(logging.INFO)
            basic.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
            self.logger.addHandler(basic)

    # ── Core logging methods ──────────────────────────────────────

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log_with_context(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log_with_context(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        with self._stats_lock:
            self._warning_count += 1
        self._log_with_context(logging.WARNING, message, **kwargs)

    def error(self, message: str, exception: Optional[Exception] = None,
              **kwargs: Any) -> None:
        with self._stats_lock:
            self._error_count += 1
        if exception:
            self.logger.error(
                f"{message} - Exception: {exception}",
                exc_info=True, extra=kwargs,
            )
        else:
            self._log_with_context(logging.ERROR, message, **kwargs)

    def critical(self, message: str, exception: Optional[Exception] = None,
                 **kwargs: Any) -> None:
        with self._stats_lock:
            self._error_count += 1
        if exception:
            self.logger.critical(
                f"{message} - Exception: {exception}",
                exc_info=True, extra=kwargs,
            )
        else:
            self._log_with_context(logging.CRITICAL, message, **kwargs)

    def _log_with_context(self, level: int, message: str, **kwargs: Any) -> None:
        """Log *message*, appending keyword context if provided.

        All output is passed through the secret scrubber to prevent
        accidental leakage of API keys, tokens, or credentials.
        """
        if kwargs:
            ctx = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            full_message = f"{message} | Context: {ctx}"
        else:
            full_message = message
        # Scrub secrets before writing to any log sink
        full_message = _scrub_log_message(full_message)
        self.logger.log(level, full_message)

    # ── Structured event logging ──────────────────────────────────

    @staticmethod
    def _ctx(**kwargs: Any) -> str:
        return " | ".join(f"{k}={v}" for k, v in kwargs.items())

    def performance(self, operation: str, duration: float, **kwargs: Any) -> None:
        """Record a performance measurement."""
        with self._stats_lock:
            self._performance_data[operation] = duration
        self.logger.info(
            f"PERFORMANCE: {operation} took {duration:.3f}s | {self._ctx(**kwargs)}"
        )

    def network_scan(self, devices_found: int, scan_duration: float,
                     **kwargs: Any) -> None:
        self.logger.info(
            f"NETWORK_SCAN: Found {devices_found} devices in {scan_duration:.2f}s"
            f" | {self._ctx(**kwargs)}"
        )

    def device_detection(self, detected_count: int, total_devices: int,
                         **kwargs: Any) -> None:
        self.logger.info(
            f"DEVICE_DETECTION: Found {detected_count}/{total_devices} matching"
            f" | {self._ctx(**kwargs)}"
        )

    def blocking_event(self, action: str, target: str, success: bool,
                       **kwargs: Any) -> None:
        self.logger.info(
            f"BLOCKING: {action} {target} - {'SUCCESS' if success else 'FAILED'}"
            f" | {self._ctx(**kwargs)}"
        )

    def settings_event(self, action: str, setting_name: str, success: bool,
                       **kwargs: Any) -> None:
        self.logger.info(
            f"SETTINGS: {action} {setting_name} - {'SUCCESS' if success else 'FAILED'}"
            f" | {self._ctx(**kwargs)}"
        )

    # ── Stats / diagnostics ───────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return a snapshot of logging statistics."""
        with self._stats_lock:
            return {
                "error_count": self._error_count,
                "warning_count": self._warning_count,
                "performance_data": dict(self._performance_data),
                "log_files": {
                    "main": str(self.log_dir / f"dupez_{datetime.now().strftime('%Y-%m-%d')}.log"),
                    "errors": str(self.log_dir / "errors.log"),
                    "performance": str(self.log_dir / "performance.log"),
                },
            }

    @property
    def error_count(self) -> int:
        with self._stats_lock:
            return self._error_count

    @property
    def warning_count(self) -> int:
        with self._stats_lock:
            return self._warning_count

    def cleanup_old_logs(self, days_to_keep: int = 30) -> None:
        """Delete log files older than *days_to_keep* days."""
        try:
            cutoff = datetime.now().timestamp() - (days_to_keep * 86400)
            for log_file in self.log_dir.glob("*.log*"):
                if log_file.stat().st_mtime < cutoff:
                    log_file.unlink()
                    self.info(f"Cleaned up old log file: {log_file}")
        except Exception as e:
            self.error(f"Failed to cleanup old logs: {e}")


# ── Global logger instance ────────────────────────────────────────────

logger = DupeZLogger()

# ── Convenience functions (backward-compat public API) ────────────────

log_info = logger.info
log_warning = logger.warning
log_debug = logger.debug
log_error = logger.error
log_critical = logger.critical
log_performance = logger.performance
log_network_scan = logger.network_scan
log_device_detection = logger.device_detection
log_blocking_event = logger.blocking_event
log_settings_event = logger.settings_event

# Legacy alias — kept for backwards compatibility
log_ps5_detection = log_device_detection


def log_startup() -> None:
    """Log application startup with environment info."""
    logger.info(
        "DupeZ Starting",
        startup_time=datetime.now().isoformat(),
        python_version=sys.version,
        platform=sys.platform,
    )


def log_shutdown() -> None:
    """Log application shutdown with final stats."""
    logger.info("DupeZ Shutting Down", shutdown_time=datetime.now().isoformat())
    stats = logger.get_stats()
    logger.info("Final stats", **stats)
