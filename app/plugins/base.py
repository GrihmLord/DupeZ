# app/plugins/base.py — Plugin Base Classes
"""
Base classes for DupeZ plugins.

Plugin types:

* :class:`DisruptionPlugin` — Adds new packet disruption methods to the engine.
* :class:`ScannerPlugin`    — Adds new network scanning capabilities.
* :class:`UIPanelPlugin`    — Adds new sidebar views to the dashboard.
* :class:`GenericPlugin`    — Runs background logic with controller access.

All plugins receive a reference to ``AppController`` on activation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

__all__ = [
    "PluginBase",
    "DisruptionPlugin",
    "ScannerPlugin",
    "UIPanelPlugin",
    "GenericPlugin",
]


class PluginBase(ABC):
    """Base class all plugins must inherit from."""

    def __init__(self) -> None:
        self.controller: Any = None  # Set by PluginLoader on activate()
        self._enabled: bool = False

    @abstractmethod
    def activate(self, controller: Any) -> bool:
        """Called when the plugin is loaded.  Return ``True`` if successful."""
        ...

    @abstractmethod
    def deactivate(self) -> bool:
        """Called when the plugin is unloaded.  Clean up resources."""
        ...

    @property
    def enabled(self) -> bool:
        return self._enabled


class DisruptionPlugin(PluginBase):
    """Plugin that adds new disruption methods to the engine.

    Subclass and implement:

    * ``get_methods()`` — return dict of ``method_name -> description``
    * ``apply(ip, method, params)`` — apply disruption
    * ``remove(ip, method)`` — remove disruption
    """

    @abstractmethod
    def get_methods(self) -> Dict[str, str]:
        """Return ``{method_name: description}`` for each method this plugin provides."""
        ...

    @abstractmethod
    def apply(self, ip: str, method: str, params: Optional[Dict] = None) -> bool:
        """Apply a disruption method to *ip*.  Return ``True`` on success."""
        ...

    @abstractmethod
    def remove(self, ip: str, method: str) -> bool:
        """Remove a disruption method from *ip*.  Return ``True`` on success."""
        ...


class ScannerPlugin(PluginBase):
    """Plugin that adds new network scanning capabilities.

    Subclass and implement:

    * ``get_scan_types()`` — return available scan type names
    * ``scan(scan_type, params)`` — run the scan and return results
    """

    @abstractmethod
    def get_scan_types(self) -> List[str]:
        """Return list of scan type names this plugin provides."""
        ...

    @abstractmethod
    def scan(self, scan_type: str, params: Optional[Dict] = None) -> List[Dict]:
        """Run a scan and return list of result dicts."""
        ...


class UIPanelPlugin(PluginBase):
    """Plugin that adds a new sidebar view to the dashboard.

    Subclass and implement:

    * ``get_panel_info()`` — return dict with ``icon``, ``tooltip``, ``title``
    * ``create_widget(parent)`` — return a ``QWidget`` for the view stack
    """

    @abstractmethod
    def get_panel_info(self) -> Dict[str, str]:
        """Return ``{'icon': '...', 'tooltip': '...', 'title': '...'}``.."""
        ...

    @abstractmethod
    def create_widget(self, parent: Any = None) -> Any:
        """Return a ``QWidget`` instance to be added to the dashboard view stack."""
        ...


class GenericPlugin(PluginBase):
    """Plugin that runs background logic with access to the controller.

    Good for: automation, logging, webhooks, integrations.
    Provides default ``activate``/``deactivate`` so subclasses only need
    to override what they need.
    """

    def activate(self, controller: Any) -> bool:
        self.controller = controller
        self._enabled = True
        return True

    def deactivate(self) -> bool:
        self._enabled = False
        return True
