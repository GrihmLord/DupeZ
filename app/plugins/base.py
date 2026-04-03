# app/plugins/base.py — Plugin Base Classes
"""
Base classes for DupeZ plugins.

Plugin types:
  - DisruptionPlugin: Adds new packet disruption methods to the engine.
  - ScannerPlugin:    Adds new network scanning capabilities.
  - UIPanelPlugin:    Adds new sidebar views to the dashboard.
  - GenericPlugin:    Runs background logic with controller access.

All plugins receive a reference to AppController on activation.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class PluginBase(ABC):
    """Base class all plugins must inherit from."""

    def __init__(self):
        self.controller = None  # Set by PluginLoader on activate()
        self._enabled = False

    @abstractmethod
    def activate(self, controller) -> bool:
        """Called when the plugin is loaded. Return True if successful."""
        ...

    @abstractmethod
    def deactivate(self) -> bool:
        """Called when the plugin is unloaded. Clean up resources."""
        ...

    @property
    def enabled(self) -> bool:
        return self._enabled


class DisruptionPlugin(PluginBase):
    """Plugin that adds new disruption methods to the engine.

    Subclass and implement:
      - get_methods(): return dict of method_name -> description
      - apply(ip, method, params): apply disruption
      - remove(ip, method): remove disruption
    """

    @abstractmethod
    def get_methods(self) -> Dict[str, str]:
        """Return {method_name: description} for each disruption method this plugin provides."""
        ...

    @abstractmethod
    def apply(self, ip: str, method: str, params: Dict = None) -> bool:
        """Apply a disruption method to a target IP. Return True on success."""
        ...

    @abstractmethod
    def remove(self, ip: str, method: str) -> bool:
        """Remove a disruption method from a target IP. Return True on success."""
        ...


class ScannerPlugin(PluginBase):
    """Plugin that adds new network scanning capabilities.

    Subclass and implement:
      - scan(params): run the scan and return results
      - get_scan_types(): return available scan type names
    """

    @abstractmethod
    def get_scan_types(self) -> List[str]:
        """Return list of scan type names this plugin provides."""
        ...

    @abstractmethod
    def scan(self, scan_type: str, params: Dict = None) -> List[Dict]:
        """Run a scan and return list of result dicts."""
        ...


class UIPanelPlugin(PluginBase):
    """Plugin that adds a new sidebar view to the dashboard.

    Subclass and implement:
      - get_panel_info(): return dict with icon, tooltip, title
      - create_widget(parent): return a QWidget for the view stack
    """

    @abstractmethod
    def get_panel_info(self) -> Dict[str, str]:
        """Return {'icon': '🔌', 'tooltip': 'My Panel', 'title': 'My Panel'}."""
        ...

    @abstractmethod
    def create_widget(self, parent=None):
        """Return a QWidget instance to be added to the dashboard view stack."""
        ...


class GenericPlugin(PluginBase):
    """Plugin that runs background logic with access to the controller.

    Good for: automation, logging, webhooks, integrations.
    """

    def activate(self, controller) -> bool:
        self.controller = controller
        self._enabled = True
        return True

    def deactivate(self) -> bool:
        self._enabled = False
        return True
