# app/firewall_helper/__init__.py
"""
DupeZ Split-Elevation Firewall Helper (ADR-0001)

This package implements the `split` architecture variant where:

* The main GUI process runs at Medium integrity level (unelevated), which
  allows Chromium GPU initialization so the embedded DayZ map can use
  hardware rasterization.
* An elevated helper process (dupez_helper.exe) owns the WinDivert handle
  and the entire `app.firewall` module chain. No packet ever crosses the
  IPC boundary — only control-plane calls do (disrupt_device, stop_device,
  get_status, get_engine_stats, hotkey triggers).

The split path is gated behind the `DUPEZ_ARCH` environment variable:

    DUPEZ_ARCH=inproc   (default) run firewall in-process, admin main       - TODAY
    DUPEZ_ARCH=split    run firewall in helper process, unelevated main     - NEW

The goal of this package is to be a drop-in replacement for
`app.firewall.clumsy_network_disruptor.disruption_manager` when
`DUPEZ_ARCH=split` is set. Under `inproc` this package is not imported.

Non-negotiable invariant (ADR-0001 §1.2):
    The control-plane split MUST NOT affect duping-feature behaviour or
    timing. The hot packet loop stays 100% in-process inside the helper.
    Latency regression on p50/p99/p999 is a hard fail.

See docs/adr/ADR-0001-split-elevation-for-gpu-map.md for full rationale.
"""

from app.firewall_helper.feature_flag import (
    ARCH_INPROC,
    ARCH_SPLIT,
    get_arch,
    is_split_mode,
)

__all__ = [
    "ARCH_INPROC",
    "ARCH_SPLIT",
    "get_arch",
    "is_split_mode",
]
