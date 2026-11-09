# app/plugins/loader.py — Plugin Discovery, Validation, and Lifecycle
"""Plugin discovery, manifest validation, and lifecycle management.

Discovers plugins in the ``plugins/`` directory, validates each against
a manifest schema, and provides load/unload lifecycle hooks.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional, Type

from app.__version__ import __version__ as CURRENT_VERSION
from app.core.update_state import compare_versions
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
    _prepare_verified_code_authorization,
    activate_sandbox,
    plugin_scope,
)
from app.plugins.signing import (
    MANIFEST_VERSION as SIGNED_MANIFEST_VERSION,
    PluginSigError,
    PluginSigState,
    SignedPluginManifest,
    verify_plugin_manifest,
)

_SECOND_FACTOR_SECRET_KINDS = (
    "secondfactor.totp.seed",
    "secondfactor.fido2.creds",
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
MANIFEST_VERSION = SIGNED_MANIFEST_VERSION

# Required manifest fields
REQUIRED_FIELDS = {"name", "version", "description", "type", "entry_point"}
VALID_TYPES = {"disruption", "scanner", "ui_panel", "generic"}
INPROCESS_PRIVILEGED_CAPABILITIES = frozenset({
    "disruption.raw_packet",
    "process.spawn",
    "fs.write_user_data",
})

# Deterministic convenience import surface. These application-owned choices
# are preloaded by trusted loader code before a plugin scope is entered, so an
# ordinary trusted plugin does not succeed or fail according to which stdlib
# modules the host happened to import first. This is not an import allowlist:
# the pinned signing key is the security boundary and capability hooks remain
# best-effort diagnostics for fully trusted publisher code.
SAFE_PLUGIN_STDLIB_IMPORTS = frozenset({
    "__future__",
    "base64",
    "binascii",
    "collections",
    "collections.abc",
    "csv",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "fractions",
    "functools",
    "hashlib",
    "hmac",
    "http",
    "http.client",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "operator",
    "os",
    "pathlib",
    "random",
    "re",
    "secrets",
    "socket",
    "ssl",
    "statistics",
    "string",
    "struct",
    "subprocess",
    "textwrap",
    "time",
    "threading",
    "traceback",
    "typing",
    "urllib",
    "urllib.error",
    "urllib.parse",
    "urllib.request",
    "uuid",
})
SAFE_PLUGIN_HOST_IMPORTS = frozenset({
    "app.logs.logger",
    "app.plugins.base",
})
SAFE_UI_PLUGIN_IMPORTS = frozenset({
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
})


def _preload_safe_plugin_imports() -> None:
    """Load the fixed stdlib surface outside any plugin capability scope."""
    for module_name in sorted(SAFE_PLUGIN_STDLIB_IMPORTS - {"__future__"}):
        importlib.import_module(module_name)


def _preload_plugin_type_imports(plugin_type: str) -> None:
    """Preload the exact host/Qt API surface before entering plugin scope."""
    for module_name in sorted(SAFE_PLUGIN_HOST_IMPORTS):
        importlib.import_module(module_name)
    if plugin_type == "ui_panel":
        for module_name in sorted(SAFE_UI_PLUGIN_IMPORTS):
            importlib.import_module(module_name)


def inprocess_capabilities_allowed(
    capabilities,
    *,
    dev_mode: Optional[bool] = None,
) -> bool:
    """Reject high-impact capabilities until plugins are process-isolated."""
    if dev_mode is None:
        dev_mode = os.environ.get("DUPEZ_PLUGIN_DEV_MODE", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
    return bool(dev_mode) or not (
        frozenset(capabilities) & INPROCESS_PRIVILEGED_CAPABILITIES
    )

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
        self.min_dupez_version: str = (
            signed.min_dupez_version
            if signed
            else data.get("min_dupez_version", "4.0.0")
        )
        self.dependencies: List[str] = data.get("dependencies", [])
        self.plugin_dir: str = plugin_dir
        self.capabilities: frozenset = (
            signed.capabilities if signed else frozenset()
        )
        self.sig_state: PluginSigState = (
            signed.sig_state if signed else PluginSigState.REJECTED
        )
        self.entry_sha384: str = signed.entry_sha384 if signed else ""
        self._signed_manifest: Optional[SignedPluginManifest] = signed

    def __repr__(self) -> Any:
        return (
            f"<PluginManifest {self.name} v{self.version} "
            f"({self.plugin_type}) {self.sig_state.value}>"
        )

class LoadedPlugin:
    """Container for a loaded plugin instance + its manifest."""

    def __init__(
        self,
        manifest: PluginManifest,
        instance: PluginBase,
        module_name: str = "",
        module_names: Optional[set[str]] = None,
        code_authorization=None,
    ) -> None:
        self.manifest = manifest
        self.instance = instance
        self.module_name = module_name  # For cleanup on unload
        self.module_names = frozenset(module_names or ({module_name} if module_name else set()))
        self._code_authorization = code_authorization
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

        # Import the application-owned safe stdlib surface before any plugin
        # scope exists.  Otherwise CPython's first import of (for example)
        # ``fractions`` emits an ``exec`` event inside the plugin scope and a
        # signed plugin's result depends on unrelated host import order.
        _preload_safe_plugin_imports()

        # Install best-effort capability diagnostics exactly once. Safe to
        # call repeatedly; this does not turn trusted in-process Python into
        # an OS security boundary.
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
        manifest bytes, pinned-pubkey fingerprint match, and exact
        SHA-384/size coverage of every bundle file. Only dev-mode builds
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
        if not inprocess_capabilities_allowed(signed.capabilities):
            denied = sorted(
                signed.capabilities & INPROCESS_PRIVILEGED_CAPABILITIES
            )
            log_error(
                f"Plugin '{signed.name}' REJECTED: in-process privileged "
                f"capabilities require process isolation: {denied}"
            )
            return None

        # ── Now re-parse the raw manifest to build the legacy dict ──
        try:
            with open(path, "rb") as f:
                raw = f.read()
            validate_json_size(raw, context=f"plugin manifest {path}")
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            log_error(f"Failed to read manifest at {path}: {e}")
            return None
        if hashlib.sha384(raw).hexdigest() != signed.manifest_sha384:
            log_error(
                f"Plugin at {plugin_dir!r} REJECTED: manifest changed "
                "during discovery"
            )
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

        A healthy secret store and an affirmative gate decision are required.
        Only a positively established, explicitly unenrolled first-run state
        may pass without verification.
        """
        def refuse(failure: str) -> bool:
            log_error(
                "plugin load refused because second-factor authorization "
                f"failed ({failure})"
            )
            try:
                from app.logs.audit import audit_event

                audit_event(
                    "second_factor_boundary_refused",
                    {"boundary": "plugin_load", "failure": failure},
                )
            except Exception:
                # Audit availability must not change the fail-closed decision.
                pass
            return False

        try:
            from app.core.second_factor import get_gate
            from app.core.secret_store import check_store_health, get_secret
        except Exception:
            return refuse("dependency_unavailable")

        try:
            store_health = check_store_health()
        except Exception:
            return refuse("store_probe_failed")
        if getattr(store_health, "healthy", None) is not True:
            return refuse("store_unavailable")

        try:
            gate = get_gate()
        except Exception:
            return refuse("gate_unavailable")

        try:
            enrolled = gate.is_enrolled()
        except Exception:
            return refuse("enrollment_query_failed")
        if enrolled is False:
            try:
                stored_enrollment = any(
                    get_secret(kind) is not None
                    for kind in _SECOND_FACTOR_SECRET_KINDS
                )
            except Exception:
                return refuse("store_read_failed")
            if stored_enrollment:
                return refuse("enrollment_state_inconsistent")
            return True
        if enrolled is not True:
            return refuse("invalid_enrollment_state")

        try:
            verified = gate.require(scope, reason=reason)
        except Exception:
            return refuse("verification_failed")
        if verified is not True:
            return refuse("invalid_verification_result")
        return True

    def load_all(self, controller) -> List[LoadedPlugin]:
        """Load and activate all discovered plugins."""
        self._controller = controller
        loaded = []

        if self.manifests and not self._enforce_second_factor(
            "plugin_install", reason="authorize plugin code loading"
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
            "plugin_install", reason="authorize plugin code loading"
        ):
            log_error(f"Plugin {name!r} load aborted: second-factor verification failed")
            return None

        plugin = self._load_plugin(manifest)
        if plugin:
            self.plugins[name] = plugin
        return plugin

    def _load_plugin(self, manifest: PluginManifest) -> Optional[LoadedPlugin]:
        """Import the plugin module, instantiate the class, and activate it.

        Security: re-verifies the complete signed bundle immediately before
        import, validates entry path containment, audits load events, and
        restricts the plugin's module namespace.
        """
        manifest_path = os.path.join(manifest.plugin_dir, "manifest.json")
        try:
            fresh_signature = verify_plugin_manifest(manifest_path)
        except PluginSigError as e:
            log_error(
                f"Plugin '{manifest.name}' REJECTED before import: bundle "
                f"integrity check failed: {e}"
            )
            try:
                from app.logs.audit import audit_event
                audit_event("plugin_integrity_rejected", {
                    "name": manifest.name,
                    "reason": str(e),
                })
            except Exception:
                pass
            return None
        if fresh_signature != manifest._signed_manifest:
            log_error(
                f"Plugin '{manifest.name}' REJECTED before import: signed "
                "manifest changed after discovery; run discovery again"
            )
            return None
        if compare_versions(CURRENT_VERSION, manifest.min_dupez_version) < 0:
            log_error(
                f"Plugin '{manifest.name}' REJECTED before import: requires "
                f"DupeZ {manifest.min_dupez_version} or newer; host is "
                f"{CURRENT_VERSION}"
            )
            return None
        if manifest.dependencies:
            log_error(
                f"Plugin '{manifest.name}' REJECTED before import: external "
                "manifest dependencies are unsupported until installed "
                "distribution versions and files can be authenticated"
            )
            return None
        # This preload is deterministic convenience, not sandboxing. A pinned
        # signer remains fully trusted and can use Python reflection/import
        # machinery beyond this set; capability hooks only diagnose policy.
        try:
            _preload_plugin_type_imports(manifest.plugin_type)
        except ImportError as e:
            log_error(
                f"Plugin '{manifest.name}' REJECTED before import: required "
                f"host plugin API is unavailable: {e}"
            )
            return None

        entry_path = os.path.join(manifest.plugin_dir, fresh_signature.entry_point)

        # Final path traversal guard (defense-in-depth)
        real_entry = os.path.realpath(entry_path)
        real_plugins = os.path.realpath(self.plugins_dir)
        if not real_entry.startswith(real_plugins + os.sep):
            log_error(f"Plugin entry path escapes plugins directory: {real_entry}")
            return None

        # Python caches imports process-wide by bare module name. Remove only
        # modules previously loaded from this exact plugin directory so a
        # re-signed helper cannot resolve to stale code. If another plugin or
        # the host already owns the same name, fail closed instead of evicting
        # unrelated trusted code.
        local_module_names: set[str] = set()
        for file_record in fresh_signature.files:
            if not file_record.path.endswith(".py"):
                continue
            parts = file_record.path[:-3].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts and file_record.path != fresh_signature.entry_point:
                local_module_names.add(".".join(parts))

        real_plugin_dir = os.path.realpath(manifest.plugin_dir)
        for local_name in sorted(local_module_names):
            cached = sys.modules.get(local_name)
            if cached is None:
                continue
            cached_file = getattr(cached, "__file__", None)
            cached_real = os.path.realpath(cached_file) if cached_file else ""
            if cached_real.startswith(real_plugin_dir + os.sep):
                sys.modules.pop(local_name, None)
                continue
            log_error(
                f"Plugin '{manifest.name}' REJECTED before import: local module "
                f"name {local_name!r} collides with an existing host/plugin module"
            )
            return None

        # Bind import-time compile/exec approval to the exact Python bytes in
        # the freshly reverified v2 manifest. The audit hook receives this
        # immutable authorization while plugin code runs; a changed file,
        # spoofed filename, or dynamically compiled buffer is denied.
        verified_sources: dict[str, tuple[bytes, str]] = {}
        try:
            for file_record in fresh_signature.files:
                if not file_record.path.endswith(".py"):
                    continue
                source_path = os.path.realpath(os.path.join(
                    real_plugin_dir,
                    *file_record.path.split("/"),
                ))
                if os.path.commonpath((real_plugin_dir, source_path)) != real_plugin_dir:
                    raise ValueError(
                        f"signed Python path escapes plugin directory: {file_record.path}"
                    )
                with open(source_path, "rb") as source_file:
                    source = source_file.read()
                if (
                    len(source) != file_record.size
                    or hashlib.sha384(source).hexdigest() != file_record.sha384
                ):
                    raise ValueError(
                        f"signed Python source changed after verification: {file_record.path}"
                    )
                verified_sources[source_path] = (source, file_record.sha384)
            code_authorization = _prepare_verified_code_authorization(
                verified_sources
            )
        except (OSError, TypeError, ValueError, SyntaxError) as e:
            log_error(
                f"Plugin '{manifest.name}' REJECTED before import: cannot "
                f"authorize verified Python sources: {e}"
            )
            return None

        plugin_owned_modules: set[str] = set()
        instance: Optional[PluginBase] = None
        activation_started = False

        def _collect_plugin_owned_modules() -> None:
            for imported_name, imported_module in tuple(sys.modules.items()):
                imported_file = getattr(imported_module, "__file__", None)
                if imported_file and os.path.realpath(imported_file).startswith(
                    real_plugin_dir + os.sep
                ):
                    plugin_owned_modules.add(imported_name)

        def _purge_plugin_owned_modules() -> None:
            _collect_plugin_owned_modules()
            for owned_name in plugin_owned_modules:
                sys.modules.pop(owned_name, None)

        def _rollback_failed_activation() -> None:
            if instance is None or not activation_started:
                return
            try:
                with plugin_scope(
                    manifest.name,
                    manifest.capabilities,
                    verified_code=code_authorization,
                ):
                    instance.deactivate()
            except Exception as cleanup_error:
                log_warning(
                    f"Plugin '{manifest.name}' activation rollback failed: "
                    f"{cleanup_error}"
                )

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
            spec = importlib.util.spec_from_file_location(module_name, real_entry)
            if spec is None or spec.loader is None:
                log_error(f"Failed to create module spec for {entry_path}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            plugin_owned_modules.add(module_name)

            # Add plugin dir to sys.path temporarily for relative imports
            added_to_path = False
            if real_plugin_dir not in sys.path:
                sys.path.insert(0, real_plugin_dir)
                added_to_path = True

            previous_dont_write_bytecode = sys.dont_write_bytecode
            try:
                # Unsigned bytecode is neither generated nor eligible for
                # import: the v2 inventory rejects existing .pyc files.
                sys.dont_write_bytecode = True
                with plugin_scope(
                    manifest.name,
                    manifest.capabilities,
                    verified_code=code_authorization,
                ):
                    spec.loader.exec_module(module)
            finally:
                sys.dont_write_bytecode = previous_dont_write_bytecode
                # Remove from sys.path immediately — only needed during exec_module
                if added_to_path and real_plugin_dir in sys.path:
                    sys.path.remove(real_plugin_dir)

            _collect_plugin_owned_modules()

            # Class discovery can invoke module-defined __dir__/__getattr__;
            # keep it, construction, and activation in the same declared-
            # capability and manifest-bound scope used for module import.
            with plugin_scope(
                manifest.name,
                manifest.capabilities,
                verified_code=code_authorization,
            ):
                expected_base = TYPE_CLASS_MAP.get(
                    manifest.plugin_type,
                    PluginBase,
                )
                plugin_class = None
                base_classes = {
                    PluginBase,
                    DisruptionPlugin,
                    ScannerPlugin,
                    UIPanelPlugin,
                    GenericPlugin,
                }
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, expected_base)
                        and attr not in base_classes
                    ):
                        plugin_class = attr
                        break

                if plugin_class is None:
                    raise TypeError(
                        f"plugin has no class inheriting from "
                        f"{expected_base.__name__}"
                    )
                instance = plugin_class()
                activation_started = True
                success = instance.activate(self._controller)
                if not isinstance(success, bool):
                    raise TypeError("plugin activate() must return bool")

            if not success:
                _rollback_failed_activation()
                _purge_plugin_owned_modules()
                log_warning(
                    f"Plugin '{manifest.name}' activate() returned False; "
                    "activation was rolled back"
                )
                return None

            loaded = LoadedPlugin(
                manifest,
                instance,
                module_name=module_name,
                module_names=plugin_owned_modules,
                code_authorization=code_authorization,
            )
            loaded.active = True

            log_info(
                f"Plugin '{manifest.name}' activated "
                f"[{manifest.sig_state.value}] "
                f"caps={sorted(manifest.capabilities) or 'none'}"
            )

            return loaded

        except SandboxViolation as e:
            _rollback_failed_activation()
            _purge_plugin_owned_modules()
            log_error(f"Plugin '{manifest.name}' blocked by sandbox: {e}")
            try:
                from app.logs.audit import audit_event
                audit_event("plugin_sandbox_violation", {
                    "name": manifest.name,
                    "reason": str(e),
                })
            except Exception:
                pass
            return None
        except Exception as e:
            # Import can fail after one or more signed helper modules have
            # entered ``sys.modules`` but before the post-import inventory
            # runs. Discover those partial imports here as well so a later
            # plugin load cannot reuse stale code from a failed attempt.
            _rollback_failed_activation()
            _purge_plugin_owned_modules()
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
                with plugin_scope(
                    plugin.manifest.name,
                    plugin.manifest.capabilities,
                    verified_code=plugin._code_authorization,
                ):
                    deactivated = plugin.instance.deactivate()
                if not isinstance(deactivated, bool):
                    raise TypeError("plugin deactivate() must return bool")
                if not deactivated:
                    log_error(
                        f"Plugin '{name}' did not confirm deactivation; "
                        "retaining the live instance for retry"
                    )
                    return False
                plugin.active = False
            # Clean up module from sys.modules to allow re-import
            for module_name in plugin.module_names:
                sys.modules.pop(module_name, None)
            del self.plugins[name]
            log_info(f"Plugin '{name}' unloaded")
            return True
        except Exception as e:
            log_error(f"Error unloading plugin '{name}': {e}")
            return False

    def unload_all(self) -> bool:
        """Deactivate every plugin and report whether all releases succeeded."""
        unloaded = True
        for name in list(self.plugins.keys()):
            if not self.unload_plugin(name):
                unloaded = False
        return unloaded

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
