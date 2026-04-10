"""
Example Logger Plugin — demonstrates the DupeZ GenericPlugin API.

This is a reference implementation for community plugin developers.
It hooks into the DupeZ controller on activation and tracks disruption
lifecycle events in an in-memory log.

Plugin Types Available:
    GenericPlugin      — background logic, logging, webhooks, integrations
    DisruptionPlugin   — add new packet disruption methods to the engine
    ScannerPlugin      — add new network scanning capabilities
    UIPanelPlugin      — add new sidebar views to the dashboard GUI

Lifecycle:
    1. PluginLoader discovers this folder via manifest.json
    2. PluginLoader imports this module and instantiates ExampleLoggerPlugin
    3. activate(controller) is called — plugin receives the AppController
    4. Plugin runs until deactivate() is called on shutdown or unload
"""

import time
from typing import Dict, List
from app.plugins.base import GenericPlugin
from app.logs.logger import log_info

__all__ = ["ExampleLoggerPlugin"]


class ExampleLoggerPlugin(GenericPlugin):
    """Logs disruption events for debugging and demonstration.

    Usage (automatic via PluginLoader):
        Plugin is discovered and loaded automatically when placed in
        the ``plugins/`` directory with a valid ``manifest.json``.

    Manual usage (for testing):
        >>> plugin = ExampleLoggerPlugin()
        >>> plugin.activate(controller)
        True
        >>> plugin.log_event("disruption_start", {"ip": "198.51.100.5"})
        >>> plugin.get_summary()
        {'disruption_start': 1, 'total': 1}
    """

    def __init__(self) -> None:
        super().__init__()
        self._events: List[Dict] = []
        self._start_time: float = 0.0

    def activate(self, controller) -> bool:
        """Called by PluginLoader when the plugin is loaded.

        Args:
            controller: The AppController instance — gives access to
                        device list, disruption state, settings, etc.

        Returns:
            True if activation succeeded.
        """
        self.controller = controller
        self._enabled = True
        self._start_time = time.time()
        self._events.clear()

        log_info("Example Logger plugin activated — tracking disruption events")
        self.log_event("plugin_activated", {
            "message": "Example Logger started successfully",
        })
        return True

    def deactivate(self) -> bool:
        """Called by PluginLoader on shutdown or manual unload.

        Returns:
            True if deactivation succeeded.
        """
        uptime = time.time() - self._start_time if self._start_time else 0
        summary = self.get_summary()
        log_info(
            f"Example Logger deactivating — "
            f"{summary.get('total', 0)} events logged over "
            f"{uptime:.0f}s"
        )
        self._enabled = False
        return True

    # ── Public API ───────────────────────────────────────────────────

    def log_event(self, event_type: str, details: Dict = None) -> None:
        """Record a disruption lifecycle event.

        Args:
            event_type: Category string, e.g. 'disruption_start',
                        'disruption_stop', 'scan_complete'.
            details:    Optional dict of event-specific metadata.

        Community developers can call this from other plugins or
        controller hooks to centralize event logging.
        """
        self._events.append({
            "type": event_type,
            "timestamp": time.time(),
            "details": details or {},
        })

    def get_summary(self) -> Dict:
        """Return a summary of all logged events.

        Returns:
            Dict with event type counts and a ``'total'`` key.

        Example::

            {'plugin_activated': 1, 'disruption_start': 3,
             'disruption_stop': 2, 'total': 6}
        """
        counts: Dict[str, int] = {}
        for event in self._events:
            t = event["type"]
            counts[t] = counts.get(t, 0) + 1
        counts["total"] = len(self._events)
        return counts

    def get_events(self, event_type: str = None, limit: int = 50) -> List[Dict]:
        """Return recent events, optionally filtered by type.

        Args:
            event_type: If set, only return events of this type.
            limit:      Maximum number of events to return (newest first).

        Returns:
            List of event dicts, most recent first.
        """
        events = self._events
        if event_type:
            events = [e for e in events if e["type"] == event_type]
        return list(reversed(events[-limit:]))
