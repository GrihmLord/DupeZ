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
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

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


_IPV4_IN_TEXT_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)
_MAC_IN_TEXT_RE = re.compile(
    r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"
)
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_BEARER_SECRET_RE = re.compile(
    r"(?i)\b(?P<scheme>bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"
)
_LABELED_SECRET_RE = re.compile(
    r"(?ix)"
    r"(?P<label>"
    r"(?P<key_quote>[\"']?)"
    r"\b(?:api[_-]?key|password|passwd|secret|token|credential|"
    r"private[_-]?key|auth|authorization)\b"
    r"(?P=key_quote)\s*[:=]\s*"
    r")"
    r"(?:"
    r"(?P<value_quote>[\"'])(?P<quoted>[^\r\n]*?)(?P=value_quote)"
    r"|(?P<plain>[^\s,;}\]\r\n]+)"
    r")"
)
_STANDALONE_SECRET_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}\b"
    ),
)
_QUOTED_LOCAL_PATH_RE = re.compile(
    r"(?P<quote>[\"'])"
    r"(?:(?:[A-Z]:[\\/])|/(?:Users|home|tmp|var/tmp|workspace)/)"
    r"[^\"'<>|\r\n]*"
    r"(?P=quote)",
    re.IGNORECASE,
)
_LOCAL_PATH_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)([A-Z]:[\\/]Users[\\/])[^\\/\"'<>|\r\n]+"),
        r"\1<REDACTED>",
    ),
    (re.compile(r"(/Users/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    (re.compile(r"(/home/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
)


def _safe_console_message(message: str) -> str:
    """Return console-safe text without importing the general helper module."""
    if os.name == "nt":
        try:
            return message.encode("ascii", errors="replace").decode("ascii")
        except Exception:
            pass
    return message


def _redact_url(value: str) -> str:
    """Reduce a URL to a non-sensitive origin without app dependencies."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("URL has no log-safe origin")
        host = parsed.hostname
        if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in host):
            raise ValueError("URL host contains control characters")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
    except (TypeError, ValueError):
        return "[REDACTED URL]"
    return f"{parsed.scheme}://{host}{port}/[REDACTED]"


def _redact_labeled_secret(match: re.Match[str]) -> str:
    value_quote = match.group("value_quote") or ""
    return f"{match.group('label')}{value_quote}[REDACTED]{value_quote}"


def _builtin_scrub_log_message(message: str) -> str:
    """Apply the logger's dependency-free, fail-safe redaction floor."""
    scrubbed = _URL_IN_TEXT_RE.sub(
        lambda match: _redact_url(match.group(0)),
        message,
    )
    scrubbed = _BEARER_SECRET_RE.sub(
        lambda match: f"{match.group('scheme')} [REDACTED]",
        scrubbed,
    )
    scrubbed = _LABELED_SECRET_RE.sub(_redact_labeled_secret, scrubbed)
    for pattern in _STANDALONE_SECRET_RES:
        scrubbed = pattern.sub("[REDACTED]", scrubbed)

    scrubbed = _QUOTED_LOCAL_PATH_RE.sub(
        lambda match: f"{match.group('quote')}[REDACTED PATH]{match.group('quote')}",
        scrubbed,
    )
    replacements: list[tuple[str, str]] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        replacements.append((local_appdata, "%LOCALAPPDATA%"))
    try:
        replacements.append((str(Path.home()), "~"))
    except Exception:
        pass
    for raw, marker in replacements:
        if raw:
            scrubbed = scrubbed.replace(raw, marker)
            scrubbed = scrubbed.replace(raw.replace("\\", "\\\\"), marker)
            scrubbed = scrubbed.replace(raw.replace("\\", "/"), marker)
    for pattern, replacement in _LOCAL_PATH_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)

    scrubbed = _IPV4_IN_TEXT_RE.sub(
        lambda match: match.group(0).rsplit(".", 1)[0] + ".x",
        scrubbed,
    )

    def _mask_mac(match: re.Match[str]) -> str:
        token = match.group(0)
        separator = ":" if ":" in token else "-"
        parts = token.lower().replace("-", ":").split(":")
        return separator.join((*parts[:3], "**", "**", "**"))

    return _MAC_IN_TEXT_RE.sub(_mask_mac, scrubbed)


def _scrub_log_message(message: str) -> str:
    """Scrub credentials, URLs, local paths, IPs, and MACs before output.

    Registered secret values require the secrets manager. If that optional
    layer is unavailable or circular, discard the complete record: a local
    pattern cannot prove that an arbitrary registered value is safe. The
    dependency-free scrubber then provides a deterministic final boundary.
    """
    if not isinstance(message, str):
        return "[REDACTED: invalid log message]"
    try:
        from app.core.secrets_manager import scrub_message

        scrubbed = scrub_message(message)
        if not isinstance(scrubbed, str):
            raise TypeError("secret scrubber returned a non-string value")
    except Exception:
        return "[REDACTED: secret scrubber unavailable]"
    return _builtin_scrub_log_message(scrubbed)


class _ScrubbingFormatter(logging.Formatter):
    """Formatter that scrubs every fully-rendered log record.

    Attached to all handlers so that NO log line can write a raw IP
    address or a credential to disk or console — including the
    ``error()``/``critical()`` exception paths that bypass
    ``_log_with_context`` and the traceback rendered from ``exc_info``.
    """

    def format(self, record: logging.LogRecord) -> str:
        rendered = _scrub_log_message(super().format(record))
        if record.exc_text is not None:
            record.exc_text = _scrub_log_message(record.exc_text)
        return rendered

    def formatException(self, ei: Any) -> str:
        """Scrub exception text before logging caches it on the record."""
        return _scrub_log_message(super().formatException(ei))

    def formatStack(self, stack_info: str) -> str:
        """Scrub stack paths before logging caches or reuses them."""
        return _scrub_log_message(super().formatStack(stack_info))


class SafeConsoleHandler(logging.StreamHandler):
    """Console handler that replaces non-ASCII characters on Windows."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if hasattr(record, "msg") and isinstance(record.msg, str):
                record.msg = _safe_console_message(record.msg)
            super().emit(record)
        except Exception:
            super().emit(record)


def _resolve_log_directory() -> str:
    """Return a writable log directory for both dev and frozen exe."""
    from app.core.app_paths import logs_dir

    return str(logs_dir())


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
        self.log_dir.mkdir(parents=True, exist_ok=True)

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
            console_handler.setFormatter(_ScrubbingFormatter(
                "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
                datefmt=self._DATEFMT,
            ))

            try:
                _console_stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception as exc:
                print(
                    "Warning: Could not configure Unicode support "
                    f"({type(exc).__name__})",
                    file=sys.stderr,
                )

            self.logger.addHandler(console_handler)

            for path_fn, max_bytes, backup_count, level, fmt in self._FILE_HANDLERS:
                handler = logging.handlers.RotatingFileHandler(
                    path_fn(self.log_dir),
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
                handler.setLevel(level)
                handler.setFormatter(
                    _ScrubbingFormatter(fmt, datefmt=self._DATEFMT)
                )
                self.logger.addHandler(handler)

        except Exception as exc:
            print(
                "Failed to setup logging handlers "
                f"({type(exc).__name__})"
            )
            basic = logging.StreamHandler()
            basic.setLevel(logging.INFO)
            basic.setFormatter(_ScrubbingFormatter("%(levelname)s - %(message)s"))
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
                "DupeZ operation failed with exception type %s",
                type(exception).__name__,
            )
        else:
            self._log_with_context(logging.ERROR, message, **kwargs)

    def critical(self, message: str, exception: Optional[Exception] = None,
                 **kwargs: Any) -> None:
        with self._stats_lock:
            self._error_count += 1
        if exception:
            self.logger.critical(
                "Critical DupeZ operation failed with exception type %s",
                type(exception).__name__,
            )
        else:
            self._log_with_context(logging.CRITICAL, message, **kwargs)

    def _log_with_context(self, level: int, message: str, **kwargs: Any) -> None:
        """Log *message*, appending keyword context if provided.

        All output is passed through the secret scrubber to prevent
        accidental leakage of API keys, tokens, or credentials.
        """
        if kwargs:
            ctx = " | ".join(
                f"{k}={_scrub_log_message(str(v))}" for k, v in kwargs.items()
            )
            full_message = f"{message} | Context: {ctx}"
        else:
            full_message = message
        # Scrub secrets before writing to any log sink
        full_message = _scrub_log_message(full_message)
        self.logger.log(level, full_message)

    # ── Structured event logging ──────────────────────────────────

    @staticmethod
    def _ctx(**kwargs: Any) -> str:
        return " | ".join(
            f"{k}={_scrub_log_message(str(v))}" for k, v in kwargs.items()
        )

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
