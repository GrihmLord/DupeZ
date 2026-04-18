# app/plugins/loader.py — Plugin Discovery, Validation, and Lifecycle
"""Plugin discovery, manifest validation, and lifecycle management.

Discovers plugins in the ``plugins/`` directory, validates each against
a manifest schema, and provides load/unload lifecycle hooks.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional, Type

from app.core.validation import validate_json_size
from app.logs.logger import log_info, log_error, log_warning
from app.plugins.base import (
    DisruptionPlugin,
    GenericPlugin,
    PluginBase,
    ScannerPlugin,
    UIPanelPlugin,
)
from app.plugins.sandbox import (
    SandboxViolation,
    activate_sandbox,
    plugin_scope,
)
from app.plugins.signing import (
    PluginSigError,
    PluginSigState,
    SignedPluginManifest,
    verify_plugin_manifest,
)

__all__ = [
    "MANIFEST_VERSION",
    "REQUIRED_FIELDS",
    "VALID_TYPES",
    "PluginManifest",
    "LoadedPlugin",
    "PluginLoader",
]

# Manifest schema version this loader supports
MANIFEST_VERSION = "1.0"

# Required manifest fields
REQUIRED_FIELDS = {"name", "version", "description", "type", "entry_point"}
VALID_TYPES = {"disruption", "scanner", "ui_panel", "generic"}

# Type -> expected base class
TYPE_CLASS_MAP: Dict[str, Type[PluginBase]] = {
    "disruption": DisruptionPlugin,
    "scanner": ScannerPlugin,
    "ui_panel": UIPanelPlugin,
    "generic": GenericPlugin,
}

class PluginManifest:
    """Parsed and validated plugin manifest.

    Carries the signature-verification state
    (:class:`PluginSigState`) alongside the parsed fields so callers can
    render a "verified vs dev-unsigned" badge in the UI and refuse to
    activate anything outside those two states.
    """

    def __init__(
        self,
        data: Dict,
        plugin_dir: str,
        *,
        signed: Optional[SignedPluginManifest] = None,
    ) -> None:
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
        self.capabilities: frozenset = (
            signed.capabilities if signed else frozenset()
        )
        self.sig_state: PluginSigState = (
            signed.sig_state if signed else PluginSigState.REJECTED
        )
        self.entry_sha384: str = signed.entry_sha384 if signed else ""

    def __repr__(self) -> Any:
        return (
            f"<PluginManifest {self.name} v{self.version} "
            f"({self.plugin_type}) {self.sig_state.value}>"
        )

class LoadedPlugin:
    """Container for a loaded plugin instance + its manifest."""

    def __init__(self, manifest: PluginManifest, instance: PluginBase, module_name: str = "") -> None:
        self.manifest = manifest
        self.instance = instance
        self.module_name = module_name  # For cleanup on unload
        self.active = False
        self.error: Optional[str] = None

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def plugin_type(self) -> str:
        return self.manifest.plugin_type

    def __repr__(self) -> Any:
        state = "active" if self.active else "inactive"
        return f"<LoadedPlugin {self.name} [{state}]>"

class PluginLoader:
    """Discovers, loads, validates, and manages plugins.

    Usage:
        loader = PluginLoader(plugins_dir="plugins")
        loader.discover()
        loader.load_all(controller)
    """

    def __init__(self, plugins_dir: str = None) -> None:
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

        # Install the capability sandbox exactly once. Safe to call
        # repeatedly — internal flag guards against double-install.
        activate_sandbox()

    # Discovery
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
        """Parse, signature-verify, and validate a manifest.json file.

        All plugins MUST pass :func:`verify_plugin_manifest` first:
        that call enforces Ed25519 signature over the canonical
        manifest bytes, pinned-pubkey fingerprint match, and the
        entry-file SHA-384 pinning. Only dev-mode builds
        (``DUPEZ_PLUGIN_DEV_MODE=1``) can skip the signature check,
        and such plugins are marked :attr:`PluginSigState.DEV_UNSIGNED`
        and audited loudly. Anything else is rejected before parsing.
        """
        # ── Signature verification ( first ) ───────────────────
        try:
            signed = verify_plugin_manifest(path)
        except PluginSigError as e:
            log_error(f"Plugin at {plugin_dir!r} REJECTED: {e}")
            try:
                from app.logs.audit import audit_event
                audit_event("plugin_sig_rejected", {
                    "plugin_dir": os.path.basename(plugin_dir),
                    "reason": str(e),
                })
            except Exception:
                pass
            return None
        if signed.sig_state == PluginSigState.DEV_UNSIGNED:
            log_warning(
                f"Plugin '{signed.name}' loaded as DEV_UNSIGNED — "
                "signature skipped (DUPEZ_PLUGIN_DEV_MODE=1). This is not "
                "safe for production builds."
            )
            try:
                from app.logs.audit import audit_event
                audit_event("plugin_unsigned_loaded", {
                    "name": signed.name,
                    "version": signed.version,
                    "capabilities": sorted(signed.capabilities),
                })
            except Exception:
                pass

        # ── Now re-parse the raw manifest to build the legacy dict ──
        try:
            with open(path, "rb") as f:
                raw = f.read()
            validate_json_size(raw, context=f"plugin manifest {path}")
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            log_error(f"Failed to read manifest at {path}: {e}")
            return None

        # Validate required fields
        missing = REQUIRED_FIELDS - data.keys()
        if missing:
            log_error(f"Manifest at {path} missing fields: {missing}")
            return None

        # Validate through centralized validation module
        try:
            from app.core.validation import (
                validate_plugin_name, validate_version_string,
                validate_entry_point, VALID_PLUGIN_TYPES,
            )
            validate_plugin_name(data["name"])
            validate_version_string(data["version"])
            if data["type"] not in VALID_PLUGIN_TYPES:
                log_error(f"Manifest at {path} has invalid type '{data['type']}'")
                return None
            validate_entry_point(data["entry_point"], plugin_dir)
        except ValueError as e:
            log_error(f"Manifest validation failed at {path}: {e}")
            return None
        except ImportError:
            pass  # fallback to legacy validation below

        # Validate type (legacy fallback)
        if data["type"] not in VALID_TYPES:
            log_error(f"Manifest at {path} has invalid type '{data['type']}' — must be one of {VALID_TYPES}")
            return None

        # Validate entry_point — prevent path traversal attacks
        entry_point = data["entry_point"]
        if ".." in entry_point or os.path.isabs(entry_point):
            log_error(f"Manifest at {path} has suspicious entry_point: {entry_point}")
            return None
        entry_file = os.path.join(plugin_dir, entry_point)
        # Resolve and verify it's still inside the plugin dir
        real_entry = os.path.realpath(entry_file)
        real_plugin_dir = os.path.realpath(plugin_dir)
        if not real_entry.startswith(real_plugin_dir + os.sep):
            log_error(f"Plugin entry_point escapes plugin directory: {entry_point}")
            return None
        if not os.path.isfile(entry_file):
            log_error(f"Manifest at {path} references missing entry_point: {entry_point}")
            return None

        return PluginManifest(data, plugin_dir, signed=signed)

    # Loading
    def _enforce_second_factor(self, scope: str, reason: str) -> bool:
        """§9.2 gate. Returns True iff the load may proceed.

        Quietly passes on first-boot installs (no provider enrolled).
        Refuses (logs + returns False) on enrolled installs that fail
        verification or that have hit the rate limiter.
        """
        if os.environ.get("DUPEZ_SECOND_FACTOR_DISABLED") == "1":
            return True
        try:
            from app.core.second_factor import (
                SecondFactorRequired,
                get_gate,
            )
        except Exception as e:
            log_warning(f"second-factor gate unavailable, allowing: {e}")
            return True
        gate = get_gate()
        if not gate.is_enrolled():
            return True
        try:
            gate.require(scope, reason=reason)
            return True
        except SecondFactorRequired as e:
            log_error(f"plugin load refused by second-factor gate: {e}")
            return False

    def load_all(self, controller) -> List[LoadedPlugin]:
        """Load and activate all discovered plugins."""
        self._controller = controller
        loaded = []

        if self.manifests and not self._enforce_second_factor(
            "plugin_install", reason=f"load {len(self.manifests)} plugin(s)"
        ):
            log_error("Plugin load_all aborted: second-factor verification failed")
            return loaded

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

        if not self._enforce_second_factor(
            "plugin_install", reason=f"load plugin {name!r}"
        ):
            log_error(f"Plugin {name!r} load aborted: second-factor verification failed")
            return None

        plugin = self._load_plugin(manifest)
        if plugin:
            self.plugins[name] = plugin
        return plugin

    def _load_plugin(self, manifest: PluginManifest) -> Optional[LoadedPlugin]:
        """Import the plugin module, instantiate the class, and activate it.

        Security: validates entry path containment, audits load events,
        and restricts the plugin's module namespace.
        """
        entry_path = os.path.join(manifest.plugin_dir, manifest.entry_point)

        # Final path traversal guard (defense-in-depth)
        real_entry = os.path.realpath(entry_path)
        real_plugins = os.path.realpath(self.plugins_dir)
        if not real_entry.startswith(real_plugins + os.sep):
            log_error(f"Plugin entry path escapes plugins directory: {real_entry}")
            return None

        try:
            # Audit trail
            try:
                from app.logs.audit import audit_event
                audit_event("plugin_load_attempt", {
                    "name": manifest.name,
                    "version": manifest.version,
                    "type": manifest.plugin_type,
                    "entry_point": manifest.entry_point,
                })
            except Exception:
                pass

            # Dynamic import from file path
            module_name = f"dupez_plugin_{manifest.name.replace(' ', '_').replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(module_name, entry_path)
            if spec is None or spec.loader is None:
                log_error(f"Failed to create module spec for {entry_path}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module

            # Add plugin dir to sys.path temporarily for relative imports
            added_to_path = False
            if manifest.plugin_dir not in sys.path:
                sys.path.insert(0, manifest.plugin_dir)
                added_to_path = True

            try:
                spec.loader.exec_module(module)
            finally:
                # Remove from sys.path immediately — only needed during exec_module
                if added_to_path and manifest.plugin_dir in sys.path:
                    sys.path.remove(manifest.plugin_dir)

            # Find the plugin class — look for a class that inherits from PluginBase
            expected_base = TYPE_CLASS_MAP.get(manifest.plugin_type, PluginBase)
            plugin_class = None

            _base_classes = {PluginBase, DisruptionPlugin, ScannerPlugin, UIPanelPlugin, GenericPlugin}
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and issubclass(attr, expected_base)
                        and attr not in _base_classes):
                    plugin_class = attr
                    break

            if plugin_class is None:
                log_error(f"Plugin '{manifest.name}' has no class inheriting from {expected_base.__name__}")
                # Clean up sys.modules on failure
                sys.modules.pop(module_name, None)
                return None

            # Instantiate and activate INSIDE the capability sandbox.
            # The sandbox audit-hook mediates syscall-level events
            # (socket/subprocess/exec/open-for-write) and raises
            # SandboxViolation when the plugin attempts an op it didn't
            # declare a matching capability for.
            instance = plugin_class()
            with plugin_scope(manifest.name, manifest.capabilities):
                try:
                    success = instance.activate(self._controller)
                except SandboxViolation as sv:
                    log_error(
                        f"Plugin '{manifest.name}' blocked by sandbox: {sv}"
                    )
                    try:
                        from app.logs.audit import audit_event
                        audit_event("plugin_sandbox_violation", {
                            "name": manifest.name,
                            "reason": str(sv),
                        })
                    except Exception:
                        pass
                    sys.modules.pop(module_name, None)
                    return None

            loaded = LoadedPlugin(manifest, instance, module_name=module_name)
            loaded.active = success

            if success:
                log_info(
                    f"Plugin '{manifest.name}' activated "
                    f"[{manifest.sig_state.value}] "
                    f"caps={sorted(manifest.capabilities) or 'none'}"
                )
            else:
                loaded.error = "activate() returned False"
                log_warning(f"Plugin '{manifest.name}' activate() returned False")

            return loaded

        except Exception as e:
            log_error(f"Failed to load plugin '{manifest.name}': {e}\n{traceback.format_exc()}")
            return None

    # Unloading
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
            # Clean up module from sys.modules to allow re-import
            if plugin.module_name:
                sys.modules.pop(plugin.module_name, None)
            del self.plugins[name]
            log_info(f"Plugin '{name}' unloaded")
            return True
        except Exception as e:
            log_error(f"Error unloading plugin '{name}': {e}")
            return False

    def unload_all(self) -> None:
        """Deactivate and unload all plugins."""
        for name in list(self.plugins.keys()):
            self.unload_plugin(name)

    # ── Queries ────────────────────────────────────────────────────

    def get_active_plugins(self) -> List[LoadedPlugin]:
        """Return all currently active plugins."""
        return [p for p in self.plugins.values() if p.active]

    def get_plugins_by_type(self, plugin_type: str) -> List[LoadedPlugin]:
        """Return active plugins matching *plugin_type*."""
        return [
            p for p in self.plugins.values()
            if p.active and p.plugin_type == plugin_type
        ]

    def get_disruption_plugins(self) -> List[LoadedPlugin]:
        return self.get_plugins_by_type("disruption")

    def get_scanner_plugins(self) -> List[LoadedPlugin]:
        return self.get_plugins_by_type("scanner")

    def get_ui_panel_plugins(self) -> List[LoadedPlugin]:
        return self.get_plugins_by_type("ui_panel")

    def get_plugin(self, name: str) -> Optional[LoadedPlugin]:
        """Return a loaded plugin by name, or ``None``."""
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
                "sig_state": manifest.sig_state.value,
                "capabilities": sorted(manifest.capabilities),
            })
        return info

