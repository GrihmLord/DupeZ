"""
Base classes for disruption engines and the disruption manager.

Two ABCs are defined here:

  DisruptionEngineBase — per-IP engine interface (NativeWinDivertEngine,
    ClumsyEngine). Handles packet interception and module processing for
    a single target.

  DisruptionManagerBase — orchestrator interface. Manages engine lifecycle,
    selects the best available engine, tracks per-device disruption state.
    The controller and GUI depend on this interface exclusively.

Engine lifecycle:
    1. Check ``available`` — are dependencies (DLLs, admin rights) met?
    2. ``start(ip, methods, params)`` — begin disruption on a target
    3. ``get_stats()`` / ``get_status()`` — monitor engine health
    4. ``stop(ip)`` or ``stop_all()`` — teardown
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

__all__ = ["DisruptionEngineBase", "DisruptionManagerBase"]


class DisruptionEngineBase(ABC):
    """Abstract base for packet disruption engines.

    Subclasses must implement every abstract method.  The controller only
    interacts with engines through this interface.

    Example usage::

        engine = NativeWinDivertEngine()
        if engine.available:
            engine.start("198.51.100.5", ["lag", "drop"],
                         {"lag_delay": 1500, "drop_chance": 90})
    """

    # ── Lifecycle ────────────────────────────────────────────────────

    @abstractmethod
    def start(self, ip: str, methods: List[str], params: Dict) -> bool:
        """Start disruption on *ip* using the given *methods* and *params*.

        Returns ``True`` if the engine successfully started disruption.
        Calling ``start`` on an already-disrupted IP should update the
        active configuration (hot-reload).
        """
        ...

    @abstractmethod
    def stop(self, ip: str) -> bool:
        """Stop disruption on *ip*.

        Returns ``True`` if the disruption was running and has been stopped.
        No-op (returns ``False``) if *ip* was not being disrupted.
        """
        ...

    @abstractmethod
    def stop_all(self) -> None:
        """Stop all active disruptions immediately."""
        ...

    # ── Queries ──────────────────────────────────────────────────────

    @abstractmethod
    def is_disrupting(self, ip: str) -> bool:
        """Return ``True`` if *ip* is currently being disrupted."""
        ...

    @abstractmethod
    def get_disrupted_ips(self) -> List[str]:
        """Return a list of IPs currently under active disruption."""
        ...

    @abstractmethod
    def get_stats(self) -> Dict:
        """Return engine-wide statistics.

        Expected keys (engines may add more):
            ``packets_processed``  — total packets handled
            ``packets_dropped``    — total packets dropped
            ``packets_passed``     — total packets forwarded
            ``packets_inbound``    — inbound packet count
            ``packets_outbound``   — outbound packet count
            ``active_engines``     — number of per-IP engine threads
            ``per_device``         — ``{ip: {packets_processed, ...}}``
        """
        ...

    @abstractmethod
    def get_status(self) -> Dict:
        """Return engine health / readiness information.

        Expected keys:
            ``is_admin``              — running with admin privileges
            ``clumsy_exe_exists``     — (ClumsyEngine only)
            ``windivert_dll_exists``  — WinDivert.dll found
            ``disrupted_devices_count`` — number of active disruptions
        """
        ...

    # ── Identity ─────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name, e.g. ``'NativeWinDivert'``."""
        ...

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether this engine can operate (dependencies met, admin, etc.)."""
        ...


class DisruptionManagerBase(ABC):
    """Abstract interface for the disruption orchestrator.

    The manager is responsible for engine selection, per-device tracking,
    and exposing a clean API that the controller and GUI consume. All
    method names use engine-agnostic terminology.

    Implementations:
      - ClumsyNetworkDisruptor (app.firewall.clumsy_network_disruptor)
    """

    # ── Lifecycle ────────────────────────────────────────────────────

    @abstractmethod
    def initialize(self) -> bool:
        """Verify prerequisites (admin, drivers, DLLs).

        Returns True if the manager is ready to accept disruption requests.
        """

    @abstractmethod
    def start(self) -> None:
        """Activate the manager (mark as running, log engine type)."""

    @abstractmethod
    def stop(self) -> None:
        """Deactivate the manager, stopping all active disruptions."""

    # ── Per-device disruption ────────────────────────────────────────

    @abstractmethod
    def disrupt_device(self, ip: str,
                       methods: Optional[List[str]] = None,
                       params: Optional[Dict] = None,
                       **kwargs) -> bool:
        """Start disruption on a target IP.

        If the device is already disrupted, the existing disruption is
        stopped and replaced with the new configuration.

        Additional ``**kwargs`` (``target_mac``, ``target_hostname``,
        ``target_device_type``) may be supplied to support auto-detection
        of the appropriate disruption profile at the engine layer.

        Returns True if disruption was started successfully.
        """

    @abstractmethod
    def stop_device(self, ip: str) -> bool:
        """Stop disruption on a specific target IP.

        Idempotent — returns True even if the device was not disrupted.
        """

    @abstractmethod
    def stop_all_devices(self) -> bool:
        """Stop all active disruptions across all targets."""

    # ── Queries ──────────────────────────────────────────────────────

    @abstractmethod
    def get_disrupted_devices(self) -> List[str]:
        """Return list of IPs currently under active disruption."""

    @abstractmethod
    def get_device_status(self, ip: str) -> Dict:
        """Return detailed status for a specific target IP.

        Returns at minimum ``{"disrupted": bool}``.
        """

    @abstractmethod
    def get_status(self) -> Dict:
        """Return overall manager status (initialization, engine info, etc.)."""

    @abstractmethod
    def get_engine_stats(self) -> Dict:
        """Return aggregated packet processing statistics from all engines."""
