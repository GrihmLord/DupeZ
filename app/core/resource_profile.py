# app/core/resource_profile.py — Adaptive startup resource limits
"""Conservative startup tuning for low-resource Windows systems.

The detector is intentionally dependency-free so it can run during bootstrap
without importing psutil, QtWebEngine, or other heavy modules. Environment
variables provide explicit operator overrides while ``auto`` remains the safe
default.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Mapping, Optional

__all__ = ["StartupResourceProfile", "detect_startup_resource_profile"]

_GIB = 1024 ** 3
_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class StartupResourceProfile:
    """Resolved limits used by the GUI bootstrap."""

    cpu_count: int
    total_memory_bytes: Optional[int]
    available_memory_bytes: Optional[int]
    low_resource: bool
    prewarm_map: bool
    qt_max_threads: int
    qt_expiry_timeout_ms: int
    startup_timeout_ms: int
    reasons: tuple[str, ...]

    @property
    def total_memory_gib(self) -> Optional[float]:
        if self.total_memory_bytes is None:
            return None
        return self.total_memory_bytes / _GIB

    @property
    def available_memory_gib(self) -> Optional[float]:
        if self.available_memory_bytes is None:
            return None
        return self.available_memory_bytes / _GIB

    def summary(self) -> str:
        total = (
            f"{self.total_memory_gib:.1f} GiB"
            if self.total_memory_gib is not None
            else "unknown"
        )
        available = (
            f"{self.available_memory_gib:.1f} GiB"
            if self.available_memory_gib is not None
            else "unknown"
        )
        reason_text = ", ".join(self.reasons) if self.reasons else "normal capacity"
        return (
            f"cpu={self.cpu_count}, memory={total}, available={available}, "
            f"low_resource={self.low_resource}, prewarm_map={self.prewarm_map}, "
            f"qt_threads={self.qt_max_threads}, reason={reason_text}"
        )


def _parse_optional_bool(value: object) -> Optional[bool]:
    text = str(value or "").strip().lower()
    if not text or text == "auto":
        return None
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return None


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _physical_memory_bytes() -> tuple[Optional[int], Optional[int]]:
    """Return total and currently available physical memory, best effort."""

    if sys.platform == "win32":
        try:
            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys), int(status.ullAvailPhys)
        except Exception:
            pass

    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total_pages = int(os.sysconf("SC_PHYS_PAGES"))
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        return page_size * total_pages, page_size * available_pages
    except (AttributeError, OSError, TypeError, ValueError):
        return None, None


def detect_startup_resource_profile(
    *,
    cpu_count: Optional[int] = None,
    total_memory_bytes: Optional[int] = None,
    available_memory_bytes: Optional[int] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> StartupResourceProfile:
    """Resolve a deterministic startup profile.

    Automatic low-resource mode activates when any of these conditions hold:
    four or fewer logical CPUs, eight GiB or less total RAM, or two GiB or less
    currently available RAM. Operators can override detection with
    ``DUPEZ_LOW_RESOURCE=1`` or ``DUPEZ_LOW_RESOURCE=0``.
    """

    env: Mapping[str, str] = os.environ if environ is None else environ
    resolved_cpu = max(1, int(cpu_count or os.cpu_count() or 1))

    if total_memory_bytes is None or available_memory_bytes is None:
        detected_total, detected_available = _physical_memory_bytes()
        if total_memory_bytes is None:
            total_memory_bytes = detected_total
        if available_memory_bytes is None:
            available_memory_bytes = detected_available

    reasons: list[str] = []
    if resolved_cpu <= 4:
        reasons.append("cpu<=4")
    if total_memory_bytes is not None and total_memory_bytes <= 8 * _GIB:
        reasons.append("ram<=8GiB")
    if available_memory_bytes is not None and available_memory_bytes <= 2 * _GIB:
        reasons.append("available_ram<=2GiB")

    low_override = _parse_optional_bool(env.get("DUPEZ_LOW_RESOURCE", "auto"))
    low_resource = bool(reasons) if low_override is None else low_override
    if low_override is not None:
        reasons = ["operator override"]

    prewarm_override = _parse_optional_bool(env.get("DUPEZ_MAP_PREWARM", "auto"))
    prewarm_map = (not low_resource) if prewarm_override is None else prewarm_override

    default_threads = min(resolved_cpu, 2 if low_resource else 8)
    qt_max_threads = _bounded_int(
        env.get("DUPEZ_QT_MAX_THREADS", default_threads),
        default=default_threads,
        minimum=1,
        maximum=16,
    )
    qt_expiry_timeout_ms = 10_000 if low_resource else 30_000
    default_timeout_ms = 180_000 if low_resource else 120_000
    startup_timeout_ms = _bounded_int(
        env.get("DUPEZ_STARTUP_TIMEOUT_MS", default_timeout_ms),
        default=default_timeout_ms,
        minimum=30_000,
        maximum=600_000,
    )

    return StartupResourceProfile(
        cpu_count=resolved_cpu,
        total_memory_bytes=total_memory_bytes,
        available_memory_bytes=available_memory_bytes,
        low_resource=low_resource,
        prewarm_map=prewarm_map,
        qt_max_threads=qt_max_threads,
        qt_expiry_timeout_ms=qt_expiry_timeout_ms,
        startup_timeout_ms=startup_timeout_ms,
        reasons=tuple(reasons),
    )
