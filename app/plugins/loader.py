# app/plugins/loader.py — Plugin Discovery, Validation, and Lifecycle

import os
import sys
import json
import importlib
import importlib.util
import traceback
from typing import Dict, List, Optional, Any
from app.plugins.base import PluginBase, DisruptionPlugin, ScannerPlugin, UIPanelPlugin, GenericPlugin
from app.logs.logger import log_info, log_error, log_warning

# Manifest schema version this loader supports
MANIFEST_VERSION = "1.0"

# Required manifest fields
REQUIRED_FIELDS = {"name", "version", "description", "type", "entry_point"}
VALID_TYPES = {"disruption", "scanner", "ui_panel", "generic"}

# Type -> expected base class
TYPE_CLASS_MAP = {
    "disruption": DisruptionPlugin,
    "scanner": ScannerPlugin,
    "ui_panel": UIPanelPlugin,
    "generic": GenericPlugin,
}


class PluginManifest:
    """Parsed and validated plugin manifest."""

    def __init__(self, data: Dict, plugin_dir: str):
        self.name: str = data["name"]
        self.version: str = data["version"]
        self.description: str = data["description"]
        self.plugin_type: str = data["type"]
        self.entry_point: str = data["entry_point"]
        self.author: str = data.get("author", "Unknown")
        self.url: str = data.get("url", "")
        self.min_dupez_version: str = data.get("min_dupez_version", "4.0.0")
        self.dependencies: List[str] = data.get("dependencies", [])
        self.plugin_dir: str = plugin_dir

    def __repr__(self):
        return f"<PluginManifest {self.name} v{self.version} ({self.plugin_type})>"


class LoadedPlugin:
    """Container for a loaded plugin instance + its manifest."""

    def __init__(self, manifest: PluginManifest, instance: PluginBase):
        self.manifest = manifest
        self.instance = instance
        self.active = False
        self.error: Optional[str] = None

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def plugin_type(self) -> str:
        return self.manifest.plugin_type

    def __repr__(self):
        state = "active" if self.active else "inactive"
        return f"<LoadedPlugin {self.name} [{state}]>"


class PluginLoader:
    """Discovers, loads, validates, and manages plugins.

    Usage:
        loader = PluginLoader(plugins_dir="plugins")
        loader.discover()
        loader.load_all(controller)
    """

    def __init__(self, plugins_dir: str = None):
        if plugins_dir is None:
            # Default: <project_root>/plugins
            if getattr(sys, 'frozen', False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            plugins_dir = os.path.join(base, "plugins")

        self.plugins_dir = plugins_dir
        self.manifests: Dict[str, PluginManifest] = {}   # name -> manifest
        self.plugins: Dict[str, LoadedPlugin] = {}        # name -> loaded plugin
        self._controller = None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover(self) -> List[PluginManifest]:
        """Scan plugins directory for valid plugin folders with manifest.json."""
        self.manifests.clear()

        if not os.path.isdir(self.plugins_dir):
            log_info(f"Plugins directory not found: {self.plugins_dir}")
            os.makedirs(self.plugins_dir, exist_ok=True)
            return []

        found = []
        for entry in os.listdir(self.plugins_dir):
            plugin_dir = os.path.join(self.plugins_dir, entry)
            if not os.path.isdir(plugin_dir):
                continue

            manifest_path = os.path.join(plugin_dir, "manifest.json")
            if not os.path.isfile(manifest_path):
                log_warning(f"Plugin folder '{entry}' missing manifest.json — skipping")
                continue

            manifest = self._parse_manifest(manifest_path, plugin_dir)
            if manifest:
                self.manifests[manifest.name] = manifest
                found.append(manifest)
                log_info(f"Discovered plugin: {manifest.name} v{manifest.version} ({manifest.plugin_type})")

        log_info(f"Plugin discovery complete: {len(found)} plugin(s) found")
        return found

    def _parse_manifest(self, path: str, plugin_dir: str) -> Optional[PluginManifest]:
        """Parse and validate a manifest.json file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log_error(f"Failed to read manifest at {path}: {e}")
            return None

        # Validate required fields
        missing = REQUIRED_FIELDS - set(data.keys())
        if missing:
            log_error(f"Manifest at {path} missing fields: {missing}")
            return None

        # Validate type
        if data["type"] not in VALID_TYPES:
            log_error(f"Manifest at {path} has invalid type '{data['type']}' — must be one of {VALID_TYPES}")
            return None

        # Validate entry_point file exists
        entry_file = os.path.join(plugin_dir, data["entry_point"])
        if not os.path.isfile(entry_file):
            log_error(f"Manifest at {path} references missing entry_point: {data['entry_point']}")
            return None

        return PluginManifest(data, plugin_dir)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_all(self, controller) -> List[LoadedPlugin]:
        """Load and activate all discovered plugins."""
        self._controller = controller
        loaded = []

        for name, manifest in self.manifests.items():
            plugin = self._load_plugin(manifest)
            if plugin:
                self.plugins[name] = plugin
                loaded.append(plugin)

        log_info(f"Plugin loading complete: {len(loaded)}/{len(self.manifests)} loaded successfully")
        return loaded

    def load_plugin(self, name: str, controller=None) -> Optional[LoadedPlugin]:
        """Load a single plugin by name."""
        if controller:
            self._controller = controller

        manifest = self.manifests.get(name)
        if not manifest:
            log_error(f"Plugin '{name}' not found in discovered manifests")
            return None

        plugin = self._load_plugin(manifest)
        if plugin:
            self.plugins[name] = plugin
        return plugin

    def _load_plugin(self, manifest: PluginManifest) -> Optional[LoadedPlugin]:
        """Import the plugin module, instantiate the class, and activate it."""
        entry_path = os.path.join(manifest.plugin_dir, manifest.entry_point)

        try:
            # Dynamic import from file path
            module_name = f"dupez_plugin_{manifest.name.replace(' ', '_').replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(module_name, entry_path)
            if spec is None or spec.loader is None:
                log_error(f"Failed to create module spec for {entry_path}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module

            # Add plugin dir to sys.path temporarily for relative imports
            if manifest.plugin_dir not in sys.path:
                sys.path.insert(0, manifest.plugin_dir)

            spec.loader.exec_module(module)

            # Find the plugin class — look for a class that inherits from PluginBase
            expected_base = TYPE_CLASS_MAP.get(manifest.plugin_type, PluginBase)
            plugin_class = None

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, expected_base)
                        and attr is not expected_base
                        and attr is not PluginBase
                        and attr is not DisruptionPlugin
                        and attr is not ScannerPlugin
                        and attr is not UIPanelPlugin
                        and attr is not GenericPlugin):
                    plugin_class = attr
                    break

            if plugin_class is None:
                log_error(f"Plugin '{manifest.name}' has no class inheriting from {expected_base.__name__}")
                return None

            # Instantiate and activate
            instance = plugin_class()
            success = instance.activate(self._controller)

            loaded = LoadedPlugin(manifest, instance)
            loaded.active = success

            if success:
                log_info(f"Plugin '{manifest.name}' activated successfully")
            else:
                loaded.error = "activate() returned False"
                log_warning(f"Plugin '{manifest.name}' activate() returned False")

            return loaded

        except Exception as e:
            log_error(f"Failed to load plugin '{manifest.name}': {e}\n{traceback.format_exc()}")
            return None

    # ------------------------------------------------------------------
    # Unloading
    # ------------------------------------------------------------------
    def unload_plugin(self, name: str) -> bool:
        """Deactivate and unload a plugin by name."""
        plugin = self.plugins.get(name)
        if not plugin:
            log_warning(f"Plugin '{name}' not loaded — nothing to unload")
            return False

        try:
            if plugin.active:
                plugin.instance.deactivate()
                plugin.active = False
            del self.plugins[name]
            log_info(f"Plugin '{name}' unloaded")
            return True
        except Exception as e:
            log_error(f"Error unloading plugin '{name}': {e}")
            return False

    def unload_all(self):
        """Deactivate and unload all plugins."""
        for name in list(self.plugins.keys()):
            self.unload_plugin(name)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_active_plugins(self) -> List[LoadedPlugin]:
        """Return all currently active plugins."""
        return [p for p in self.plugins.values() if p.active]

    def get_plugins_by_type(self, plugin_type: str) -> List[LoadedPlugin]:
        """Return all active plugins of a given type."""
        return [p for p in self.plugins.values() if p.active and p.plugin_type == plugin_type]

    def get_disruption_plugins(self) -> List[LoadedPlugin]:
        return self.get_plugins_by_type("disruption")

    def get_scanner_plugins(self) -> List[LoadedPlugin]:
        return self.get_plugins_by_type("scanner")

    def get_ui_panel_plugins(self) -> List[LoadedPlugin]:
        return self.get_plugins_by_type("ui_panel")

    def get_plugin(self, name: str) -> Optional[LoadedPlugin]:
        return self.plugins.get(name)

    def get_plugin_info(self) -> List[Dict]:
        """Return summary info for all discovered plugins."""
        info = []
        for name, manifest in self.manifests.items():
            loaded = self.plugins.get(name)
            info.append({
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "type": manifest.plugin_type,
                "author": manifest.author,
                "loaded": loaded is not None,
                "active": loaded.active if loaded else False,
                "error": loaded.error if loaded else None,
            })
        return info
