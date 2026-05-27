"""Custom preset persistence for DupeZ (v5.6.9).

The built-in presets (Red Disconnect / Lag / God Mode / Custom) live in
``app/gui/clumsy_control.PRESETS`` as a hard-coded dict. v5.6.9 adds a
parallel store of USER-AUTHORED presets that can be created, edited,
deleted, exported, and shared.

Schema:

    {
      "version": 1,
      "presets": [
        {
          "name": "Surgical 7s",
          "description": "100% drop on game ports, 7s timed cut",
          "methods": ["drop", "disconnect"],
          "params": {
            "drop_chance": 100,
            "disconnect_duration_ms": 7000,
            "direction": "both",
            "_ports": [2302, 2303, 2304, 2305],     # v5.6.9 #3
            "_process_scope": "auto"                # v5.6.9 #4
          },
          "created_at": "2026-05-12T10:00:00Z",
          "updated_at": "2026-05-12T10:00:00Z"
        }
      ]
    }

Storage: ``app/data/custom_presets.json`` via the existing persistence
manager (HMAC-signed alongside other data files). No new dependencies;
no DPAPI encryption needed because presets aren't secret.

API surface:

    list_custom_presets() -> List[CustomPreset]
    get_custom_preset(name) -> CustomPreset | None
    save_custom_preset(preset) -> bool        # add or update
    delete_custom_preset(name) -> bool
    export_preset(preset, path) -> bool       # JSON sidecar for sharing
    import_preset(path) -> CustomPreset

The GUI's preset dropdown reads from BOTH the built-in PRESETS dict
AND this store. Built-ins are immutable; custom presets are
user-editable. Built-in names take precedence on collision (the editor
refuses to save a custom preset with a reserved name).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.logs.logger import log_info, log_warning, log_error

__all__ = [
    "CustomPreset",
    "PresetValidationError",
    "RESERVED_PRESET_NAMES",
    "list_custom_presets",
    "get_custom_preset",
    "save_custom_preset",
    "delete_custom_preset",
    "export_preset",
    "import_preset",
    "validate_preset",
]


# Names reserved by built-in presets — custom presets cannot collide with these
# to avoid confusion in the GUI dropdown. Update if PRESETS dict gains entries.
RESERVED_PRESET_NAMES = frozenset({
    "Red Disconnect", "Lag", "God Mode", "Custom",
    # Defensive: lowercase variants in case the GUI changes capitalization
    "red disconnect", "lag", "god mode", "custom",
})

# Module-level methods whitelist — must match what the engine actually supports.
# Update when new disruption modules land in the engine.
VALID_METHODS = frozenset({
    "drop", "lag", "throttle", "duplicate", "corrupt", "rst",
    "bandwidth", "disconnect", "ooo", "godmode",
    "pulse", "tick_sync", "stealth_drop", "stealth_lag",
})

VALID_DIRECTIONS = frozenset({"inbound", "outbound", "both"})
# Name char set: alphanumerics, space, underscore, hyphen, parentheses.
# Parentheses are required so the auto-rename suffix produced by
# import_preset on collision (e.g. "Conflict (2)") passes validation.
# Without this, every duplicate-named import crashes.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-()]{0,63}$")
_DATA_TYPE = "custom_presets"


class PresetValidationError(ValueError):
    """Raised when a preset's schema or content is invalid."""


@dataclass
class CustomPreset:
    """One user-authored preset."""
    name: str
    description: str = ""
    methods: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CustomPreset":
        return cls(
            name=str(d.get("name", "")),
            description=str(d.get("description", "")),
            methods=list(d.get("methods", []) or []),
            params=dict(d.get("params", {}) or {}),
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
        )


# ── Validation ─────────────────────────────────────────────────────────

def validate_preset(p: CustomPreset, *, allow_reserved: bool = False) -> None:
    """Raise PresetValidationError if *p* is malformed.

    Args:
        allow_reserved: when True, skip the "name not in reserved set"
            check. Used by import_preset for round-tripping (the import
            path renames on conflict instead of refusing outright).
    """
    if not isinstance(p.name, str) or not p.name.strip():
        raise PresetValidationError("preset name cannot be empty")
    if not _NAME_RE.match(p.name):
        raise PresetValidationError(
            f"preset name invalid: {p.name!r} (allowed: A-Z, a-z, 0-9, "
            f"space, underscore, dash, parentheses; 1-64 chars; must "
            f"start with alphanumeric)"
        )
    if not allow_reserved and p.name in RESERVED_PRESET_NAMES:
        raise PresetValidationError(
            f"preset name {p.name!r} is reserved by a built-in preset"
        )
    if len(p.description) > 256:
        raise PresetValidationError(
            f"preset description too long: {len(p.description)} > 256"
        )
    if not isinstance(p.methods, list):
        raise PresetValidationError("preset methods must be a list")
    bad = [m for m in p.methods if m not in VALID_METHODS]
    if bad:
        raise PresetValidationError(
            f"preset methods contain unknown values: {bad}. "
            f"Valid: {sorted(VALID_METHODS)}"
        )
    if not isinstance(p.params, dict):
        raise PresetValidationError("preset params must be a dict")

    # v5.7.3 SECURITY: underscore-key allowlist.
    #
    # Keys starting with "_" are engine-internal control flags read by
    # the disruption orchestrator — e.g. _network_local (forces NETWORK
    # vs FORWARD layer), _force_self_disrupt, _force_arp_spoof,
    # _wifi_auto_fallback, _target_ip. A preset is user-authored DATA,
    # and presets are SHARED (export/import JSON sidecars; a future
    # marketplace). If an imported preset could carry arbitrary "_*"
    # keys, a malicious shared preset could silently flip engine
    # behavior on the importer's machine — e.g. disable the isolation
    # watchdog, force a layer, or inject a bogus _target_ip.
    #
    # Only these two underscore keys are legitimately preset-settable
    # (they're documented preset features). Any other "_*" key is
    # rejected at validation time, so it can never reach save or the
    # engine. Non-underscore params (drop_chance, lag_delay, etc.) are
    # unaffected — they're plain tuning values.
    allowed_underscore = {"_ports", "_process_scope"}
    rogue = sorted(
        k for k in p.params
        if isinstance(k, str) and k.startswith("_")
        and k not in allowed_underscore
    )
    if rogue:
        raise PresetValidationError(
            f"preset params contains disallowed engine-internal keys: "
            f"{rogue}. Only {sorted(allowed_underscore)} may be set by "
            f"a preset; other '_'-prefixed keys are engine control "
            f"flags and cannot be injected via a shared preset."
        )

    # v5.7.3 SECURITY: bound the params dict size. A preset is small
    # config; an oversized params blob (thousands of keys, megabyte
    # values) is either corruption or an attempt to DoS the importer.
    try:
        params_json_len = len(json.dumps(p.params))
    except (TypeError, ValueError) as exc:
        raise PresetValidationError(
            f"preset params not JSON-serializable: {exc}"
        ) from exc
    if params_json_len > 16_384:
        raise PresetValidationError(
            f"preset params too large: {params_json_len} bytes "
            f"(cap 16384) — presets are small config, not data blobs"
        )

    direction = p.params.get("direction", "both")
    if direction not in VALID_DIRECTIONS:
        raise PresetValidationError(
            f"preset params.direction invalid: {direction!r}. "
            f"Valid: {sorted(VALID_DIRECTIONS)}"
        )
    # _ports: optional list of int 1..65535 OR list of {proto, port}
    ports = p.params.get("_ports")
    if ports is not None:
        if not isinstance(ports, list):
            raise PresetValidationError("params._ports must be a list")
        for entry in ports:
            if isinstance(entry, int):
                if not 1 <= entry <= 65535:
                    raise PresetValidationError(
                        f"params._ports entry out of range: {entry}"
                    )
            elif isinstance(entry, dict):
                proto = str(entry.get("proto", "")).lower()
                port = entry.get("port")
                if proto not in ("tcp", "udp"):
                    raise PresetValidationError(
                        f"params._ports entry proto invalid: {proto!r} "
                        f"(must be tcp or udp)"
                    )
                if not isinstance(port, int) or not 1 <= port <= 65535:
                    raise PresetValidationError(
                        f"params._ports entry port out of range: {port}"
                    )
            else:
                raise PresetValidationError(
                    f"params._ports entry must be int or "
                    f"{{proto, port}} dict, got {type(entry).__name__}"
                )
    # _process_scope: optional string, "auto" | "dayz" | "" | None
    scope = p.params.get("_process_scope")
    if scope not in (None, "", "auto", "dayz"):
        raise PresetValidationError(
            f"params._process_scope invalid: {scope!r} "
            f"(allowed: None, '', 'auto', 'dayz')"
        )


# ── Persistence ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_raw() -> Dict[str, Any]:
    """Load the raw on-disk dict. Returns the v1 empty shell on miss."""
    try:
        from app.core.data_persistence import persistence_manager
        data = persistence_manager.load_data(_DATA_TYPE, default=None)
        if data is None:
            return {"version": 1, "presets": []}
        if not isinstance(data, dict):
            log_warning(
                f"{_DATA_TYPE}.json was not a dict — treating as empty"
            )
            return {"version": 1, "presets": []}
        if "presets" not in data or not isinstance(data["presets"], list):
            data.setdefault("presets", [])
        data.setdefault("version", 1)
        return data
    except Exception as e:
        log_error(f"Failed to load custom presets: {e}")
        return {"version": 1, "presets": []}


def _save_raw(data: Dict[str, Any]) -> bool:
    try:
        from app.core.data_persistence import persistence_manager
        return persistence_manager.save_data(_DATA_TYPE, data, force=True)
    except Exception as e:
        log_error(f"Failed to save custom presets: {e}")
        return False


# ── Public API ─────────────────────────────────────────────────────────

def list_custom_presets() -> List[CustomPreset]:
    """Return all custom presets in creation order."""
    raw = _load_raw()
    out: List[CustomPreset] = []
    for entry in raw.get("presets", []):
        try:
            p = CustomPreset.from_dict(entry)
            out.append(p)
        except Exception as e:
            log_warning(f"Skipping malformed preset entry: {e}")
    return out


def get_custom_preset(name: str) -> Optional[CustomPreset]:
    """Return the preset with the given name, or None if absent."""
    for p in list_custom_presets():
        if p.name == name:
            return p
    return None


def save_custom_preset(preset: CustomPreset) -> bool:
    """Add or update *preset* by name. Returns True on persist success."""
    validate_preset(preset)
    raw = _load_raw()
    now = _now_iso()
    found = False
    for i, entry in enumerate(raw["presets"]):
        if entry.get("name") == preset.name:
            preset.created_at = entry.get("created_at", now)
            preset.updated_at = now
            raw["presets"][i] = preset.to_dict()
            found = True
            break
    if not found:
        preset.created_at = preset.created_at or now
        preset.updated_at = now
        raw["presets"].append(preset.to_dict())
    ok = _save_raw(raw)
    if ok:
        log_info(
            f"Custom preset {'updated' if found else 'created'}: {preset.name}"
        )
    return ok


def delete_custom_preset(name: str) -> bool:
    """Delete the preset by name. Returns True if removed."""
    raw = _load_raw()
    before = len(raw["presets"])
    raw["presets"] = [
        e for e in raw["presets"] if e.get("name") != name
    ]
    if len(raw["presets"]) == before:
        return False
    ok = _save_raw(raw)
    if ok:
        log_info(f"Custom preset deleted: {name}")
    return ok


def export_preset(preset: CustomPreset, path: str) -> bool:
    """Write *preset* to *path* as a standalone JSON sidecar.

    Suitable for sharing (e.g., attach to a Discord post). The exported
    file has the same schema as one entry in `presets[]` above, wrapped
    in `{version: 1, presets: [...]}` so it round-trips through
    :func:`import_preset` cleanly.
    """
    try:
        bundle = {"version": 1, "presets": [preset.to_dict()]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, sort_keys=True)
        log_info(f"Preset exported: {preset.name} → {path}")
        return True
    except Exception as e:
        log_error(f"Failed to export preset: {e}")
        return False


def import_preset(path: str) -> CustomPreset:
    """Load a preset from *path*. Returns the parsed CustomPreset.

    On name collision with an existing custom preset, appends a numeric
    suffix (`Name`, `Name (2)`, `Name (3)`, ...) until unique. Raises
    PresetValidationError if the file isn't a valid bundle or the
    preset schema doesn't validate.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            bundle = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise PresetValidationError(f"cannot read preset bundle: {e}") from e

    if not isinstance(bundle, dict):
        raise PresetValidationError("bundle root must be a JSON object")
    presets = bundle.get("presets")
    if not isinstance(presets, list) or not presets:
        raise PresetValidationError("bundle.presets must be a non-empty list")

    preset = CustomPreset.from_dict(presets[0])
    validate_preset(preset, allow_reserved=True)

    existing = {p.name for p in list_custom_presets()}
    if preset.name in existing or preset.name in RESERVED_PRESET_NAMES:
        base = preset.name
        n = 2
        while f"{base} ({n})" in existing:
            n += 1
        preset.name = f"{base} ({n})"
        validate_preset(preset)  # re-validate the new name

    save_custom_preset(preset)
    return preset
