# app/firewall/clumsy_full_controls.py — complete direct-Clumsy control adapter
"""Install the remaining Kalirenegade 0.3.4 controls on the owned process.

This adapter does not widen target selection.  A user filter is accepted only
as a bounded additional predicate and is always ANDed with DupeZ's validated
exact-target filter.  All Win32 messages are sent to controls owned by the
single managed Clumsy child process.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional

from app.core.clumsy_controls import (
    BANDWIDTH_KB,
    BANDWIDTH_MB,
    CLUMSY_DIRECTION_KEYS,
    CLUMSY_METHOD_LABELS,
    CLUMSY_NUMERIC_LIMITS,
    TRIGGER_TIMER,
    normalize_additional_filter,
    normalize_bandwidth_unit,
    normalize_clumsy_label,
    normalize_direction,
    normalize_timer_seconds,
    normalize_trigger_mode,
    validate_clumsy_control_params,
)
from app.core.validation import validate_local_target_ip
from app.firewall import clumsy_network_disruptor as legacy
from app.firewall.direct_clumsy_manager import (
    DirectClumsyNetworkDisruptor,
    ManagedClumsyEngine,
)
from app.logs.logger import log_error, log_info, log_warning

__all__ = [
    "compose_scoped_filter",
    "install_clumsy_full_controls",
    "trigger_owned_rst_next_packet",
]

_BM_SETCHECK = 0x00F1
_BST_UNCHECKED = 0
_MAX_CONTROL_DISTANCE_PX = 42


def compose_scoped_filter(
    base_filter: str,
    target_ip: str,
    additional_predicate: Any,
) -> str:
    """Combine an extra predicate with an immutable private-target scope."""

    target = validate_local_target_ip(
        str(target_ip or ""),
        context="Clumsy additional filter",
    )
    base = str(base_filter or "").strip()
    if not base or base.lower() == "true" or target not in base:
        raise ValueError(
            "Clumsy additional filter refused because the mandatory exact-target "
            "scope was missing"
        )
    predicate = normalize_additional_filter(additional_predicate)
    if predicate.lower() == "true":
        return base
    return f"({base}) and ({predicate})"


def _direction_for(engine: ManagedClumsyEngine, method: str) -> str:
    key = CLUMSY_DIRECTION_KEYS[method]
    raw = engine.params.get(key)
    if method == "corrupt" and raw is None:
        raw = engine.params.get("corrupt_direction")
    return normalize_direction(raw or engine.params.get("direction", "both"))


def _flag(direction: str, active: bool) -> tuple[str, str]:
    if not active:
        return "false", "false"
    return (
        "true" if direction in {"both", "inbound"} else "false",
        "true" if direction in {"both", "outbound"} else "false",
    )


def _numeric(engine: ManagedClumsyEngine, name: str, default: int) -> int:
    value = int(engine.params.get(name, default))
    minimum, maximum = CLUMSY_NUMERIC_LIMITS[name]
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be from {minimum} to {maximum}")
    return value


def _write_config_with_named_scope(engine: ManagedClumsyEngine) -> None:
    name = normalize_clumsy_label(
        engine.params.get("_clumsy_filter_name"),
        default="DupeZ Target",
    )
    path = os.path.join(engine.clumsy_dir, "config.txt")
    content = f"{name}: {engine.filter_str}\n"
    with open(path, "w", encoding="utf-8", newline="\n") as file_handle:
        file_handle.write(content)
    log_info(f"config.txt written: {path}")
    log_info(f"  filter preset: {name}; scoped expression loaded")


def _empty_preset() -> str:
    return (
        "Lag_Inbound = false\nLag_Outbound = false\nLag_Delay = 0\n"
        "Drop_Inbound = false\nDrop_Outbound = false\nDrop_Chance = 0\n"
        "Disconnect_Inbound = false\nDisconnect_Outbound = false\n"
        "BandwidthLimiter_QueueSize = 0\nBandwidthLimiter_Size = kb\n"
        "BandwidthLimiter_Inbound = false\nBandwidthLimiter_Outbound = false\n"
        "BandwidthLimiter_Limit = 0\nThrottle_DropThrottled = false\n"
        "Throttle_Timeframe = 0\nThrottle_Inbound = false\n"
        "Throttle_Outbound = false\nThrottle_Chance = 0\n"
        "Duplicate_Count = 0\nDuplicate_Inbound = false\n"
        "Duplicate_Outbound = false\nDuplicate_Chance = 0\n"
        "OutOfOrder_Inbound = false\nOutOfOrder_Outbound = false\n"
        "OutOfOrder_Chance = 0\nTamper_RedoChecksum = false\n"
        "Tamper_Inbound = false\nTamper_Outbound = false\nTamper_Chance = 0\n"
        "SetTCPRST_Inbound = false\nSetTCPRST_Outbound = false\n"
        "SetTCPRST_Chance = 0\n"
    )


def _write_full_presets(engine: ManagedClumsyEngine) -> None:
    methods = set(engine.methods)
    p = engine.params
    preset_name = normalize_clumsy_label(
        p.get("_clumsy_function_preset_name"),
        default="DupeZ",
    )
    bandwidth_unit = normalize_bandwidth_unit(
        p.get("bandwidth_size", BANDWIDTH_KB)
    )

    directions = {
        method: _direction_for(engine, method)
        for method in CLUMSY_DIRECTION_KEYS
    }
    flags = {
        method: _flag(directions[method], method in methods)
        for method in CLUMSY_DIRECTION_KEYS
    }

    lag_delay = _numeric(engine, "lag_delay", 170) if "lag" in methods else 0
    drop_chance = (
        _numeric(engine, "drop_chance", 99) if "drop" in methods else 0
    )
    bandwidth_queue = (
        _numeric(engine, "bandwidth_queue", 0)
        if "bandwidth" in methods
        else 0
    )
    bandwidth_limit = (
        _numeric(engine, "bandwidth_limit", 0)
        if "bandwidth" in methods
        else 0
    )
    throttle_frame = (
        _numeric(engine, "throttle_frame", 0)
        if "throttle" in methods
        else 0
    )
    throttle_chance = (
        _numeric(engine, "throttle_chance", 0)
        if "throttle" in methods
        else 0
    )
    duplicate_extra = (
        _numeric(engine, "duplicate_count", 1)
        if "duplicate" in methods
        else 0
    )
    duplicate_total = duplicate_extra + 1 if "duplicate" in methods else 0
    duplicate_chance = (
        _numeric(engine, "duplicate_chance", 0)
        if "duplicate" in methods
        else 0
    )
    ood_chance = (
        _numeric(engine, "ood_chance", 0) if "ood" in methods else 0
    )
    tamper_chance = (
        _numeric(engine, "tamper_chance", 0)
        if "corrupt" in methods
        else 0
    )
    rst_chance = (
        _numeric(engine, "rst_chance", 0) if "rst" in methods else 0
    )

    content = (
        "[General]\nKeybind = [\n\n"
        f"[Preset1]\nPresetName = {preset_name}\n"
        f"Lag_Inbound = {flags['lag'][0]}\n"
        f"Lag_Outbound = {flags['lag'][1]}\nLag_Delay = {lag_delay}\n"
        f"Drop_Inbound = {flags['drop'][0]}\n"
        f"Drop_Outbound = {flags['drop'][1]}\nDrop_Chance = {drop_chance}\n"
        f"Disconnect_Inbound = {flags['disconnect'][0]}\n"
        f"Disconnect_Outbound = {flags['disconnect'][1]}\n"
        f"BandwidthLimiter_QueueSize = {bandwidth_queue}\n"
        f"BandwidthLimiter_Size = {bandwidth_unit}\n"
        f"BandwidthLimiter_Inbound = {flags['bandwidth'][0]}\n"
        f"BandwidthLimiter_Outbound = {flags['bandwidth'][1]}\n"
        f"BandwidthLimiter_Limit = {bandwidth_limit}\n"
        f"Throttle_DropThrottled = {str(bool(p.get('throttle_drop', False))).lower()}\n"
        f"Throttle_Timeframe = {throttle_frame}\n"
        f"Throttle_Inbound = {flags['throttle'][0]}\n"
        f"Throttle_Outbound = {flags['throttle'][1]}\n"
        f"Throttle_Chance = {throttle_chance}\n"
        f"Duplicate_Count = {duplicate_total}\n"
        f"Duplicate_Inbound = {flags['duplicate'][0]}\n"
        f"Duplicate_Outbound = {flags['duplicate'][1]}\n"
        f"Duplicate_Chance = {duplicate_chance}\n"
        f"OutOfOrder_Inbound = {flags['ood'][0]}\n"
        f"OutOfOrder_Outbound = {flags['ood'][1]}\n"
        f"OutOfOrder_Chance = {ood_chance}\n"
        f"Tamper_RedoChecksum = {str(bool(p.get('tamper_checksum', True))).lower()}\n"
        f"Tamper_Inbound = {flags['corrupt'][0]}\n"
        f"Tamper_Outbound = {flags['corrupt'][1]}\n"
        f"Tamper_Chance = {tamper_chance}\n"
        f"SetTCPRST_Inbound = {flags['rst'][0]}\n"
        f"SetTCPRST_Outbound = {flags['rst'][1]}\n"
        f"SetTCPRST_Chance = {rst_chance}\n"
    )
    empty = _empty_preset()
    for index in range(2, 6):
        content += (
            f"\n[Preset{index}]\nPresetName = Preset_{index}\n{empty}"
        )

    path = os.path.join(engine.clumsy_dir, "presets.ini")
    with open(path, "w", encoding="utf-8", newline="\n") as file_handle:
        file_handle.write(content)
    log_info(
        "presets.ini full-control Preset1 written: "
        f"name={preset_name!r}, methods={sorted(methods)}, "
        f"directions={directions}, bandwidth={bandwidth_unit}"
    )


def _rect(hwnd: Any) -> tuple[int, int, int, int]:
    class RECT(legacy.ctypes.Structure):
        _fields_ = [
            ("left", legacy.ctypes.c_long),
            ("top", legacy.ctypes.c_long),
            ("right", legacy.ctypes.c_long),
            ("bottom", legacy.ctypes.c_long),
        ]

    result = RECT()
    user32 = legacy.ctypes.windll.user32
    if not user32.GetWindowRect(hwnd, legacy.ctypes.byref(result)):
        return 0, 0, 0, 0
    return result.left, result.top, result.right, result.bottom


def _find_nearest_button(
    engine: ManagedClumsyEngine,
    module_hwnd: Any,
    text: str,
) -> Optional[Any]:
    module_rect = _rect(module_hwnd)
    module_y = (module_rect[1] + module_rect[3]) // 2
    candidates = []
    for hwnd in legacy._find_children_by_class(engine._hwnd, "BUTTON"):
        if legacy._get_window_text(hwnd).strip().lower() != text.lower():
            continue
        rect = _rect(hwnd)
        y = (rect[1] + rect[3]) // 2
        distance = abs(y - module_y)
        candidates.append((distance, hwnd))
    if not candidates:
        return None
    distance, hwnd = min(candidates, key=lambda item: item[0])
    return hwnd if distance <= _MAX_CONTROL_DISTANCE_PX else None


def _force_toggle_callback(hwnd: Any, desired: bool) -> bool:
    """Force one IUP ACTION callback with the requested final toggle state."""

    user32 = legacy.ctypes.windll.user32
    opposite = _BST_UNCHECKED if desired else legacy.BST_CHECKED
    expected = legacy.BST_CHECKED if desired else _BST_UNCHECKED
    user32.SendMessageW(hwnd, _BM_SETCHECK, opposite, 0)
    user32.SendMessageW(hwnd, legacy.BM_CLICK, 0, 0)
    time.sleep(0.02)
    return int(user32.SendMessageW(hwnd, legacy.BM_GETCHECK, 0, 0)) == expected


def _sync_module_directions(engine: ManagedClumsyEngine) -> bool:
    for method in engine.methods:
        label = CLUMSY_METHOD_LABELS.get(method)
        if not label:
            continue
        module_hwnd = engine._find_checkbox(label)
        if not module_hwnd:
            engine._last_error = f"Clumsy module row not found: {label}"
            return False
        direction = _direction_for(engine, method)
        expected = {
            "Inbound": direction in {"both", "inbound"},
            "Outbound": direction in {"both", "outbound"},
        }
        for text, state in expected.items():
            toggle = _find_nearest_button(engine, module_hwnd, text)
            if not toggle or not _force_toggle_callback(toggle, state):
                engine._last_error = (
                    f"Clumsy {label} {text} callback did not confirm "
                    f"state={state}"
                )
                return False
        log_info(f"Clumsy direction confirmed: {label}={direction}")
    return True


def _sync_extra_toggles(engine: ManagedClumsyEngine) -> bool:
    extras = (
        ("throttle", "Drop Throttled", bool(
            engine.params.get("throttle_drop", False)
        )),
        ("corrupt", "Redo Checksum", bool(
            engine.params.get("tamper_checksum", True)
        )),
    )
    for method, text, desired in extras:
        if method not in engine.methods:
            continue
        hwnd = engine._find_checkbox(text)
        if not hwnd or not _force_toggle_callback(hwnd, desired):
            engine._last_error = (
                f"Clumsy sub-control {text!r} did not confirm state={desired}"
            )
            return False
        log_info(f"Clumsy sub-control confirmed: {text}={desired}")
    return True


def _sync_bandwidth_unit(engine: ManagedClumsyEngine) -> bool:
    if "bandwidth" not in engine.methods:
        return True
    desired = normalize_bandwidth_unit(
        engine.params.get("bandwidth_size", BANDWIDTH_KB)
    )
    desired_text = "KB/s" if desired == BANDWIDTH_KB else "MB/s"
    buttons = legacy._find_children_by_class(engine._hwnd, "BUTTON")
    unit_button = next(
        (
            hwnd
            for hwnd in buttons
            if legacy._get_window_text(hwnd).strip().lower()
            in {"kb/s", "mb/s"}
        ),
        None,
    )
    if not unit_button:
        engine._last_error = "Clumsy bandwidth KB/s / MB/s control was not found"
        return False
    current = legacy._get_window_text(unit_button).strip()
    if current.lower() != desired_text.lower():
        legacy._click_button(unit_button)
        time.sleep(0.03)
        current = legacy._get_window_text(unit_button).strip()
    if current.lower() != desired_text.lower():
        engine._last_error = (
            f"Clumsy bandwidth unit expected {desired_text!r}, observed {current!r}"
        )
        return False
    log_info(f"Clumsy bandwidth unit confirmed: {desired_text}")
    return True


def _combo_with_items(engine: ManagedClumsyEngine, required: set[str]) -> Any:
    for combo in legacy._find_children_by_class(engine._hwnd, "COMBOBOX"):
        items = {item.strip().lower() for item in legacy._combobox_items(combo)}
        if required.issubset(items):
            return combo
    return None


def _select_combo_text(combo: Any, desired: str) -> bool:
    items = legacy._combobox_items(combo)
    for index, item in enumerate(items):
        if item.strip().lower() == desired.strip().lower():
            if not legacy._select_combobox_item(combo, index):
                return False
            return desired.strip().lower() in legacy._get_window_text(combo).lower()
    return False


def _sync_function_preset(engine: ManagedClumsyEngine) -> bool:
    desired = normalize_clumsy_label(
        engine.params.get("_clumsy_function_preset_name"),
        default="DupeZ",
    )
    combo = None
    for candidate in legacy._find_children_by_class(engine._hwnd, "COMBOBOX"):
        items = legacy._combobox_items(candidate)
        if len(items) == 5 and any(
            item.strip().lower() == desired.lower() for item in items
        ):
            combo = candidate
            break
    if not combo or not _select_combo_text(combo, desired):
        engine._last_error = (
            f"Clumsy function preset {desired!r} was not found or selected"
        )
        return False
    log_info(f"Clumsy function preset confirmed: {desired}")
    return True


def _sync_trigger_controls(engine: ManagedClumsyEngine) -> bool:
    mode = normalize_trigger_mode(engine.params.get("_clumsy_trigger_mode"))
    combo = _combo_with_items(engine, {"toggle", "timer"})
    if not combo or not _select_combo_text(combo, mode.title()):
        engine._last_error = f"Clumsy trigger mode did not confirm {mode!r}"
        return False
    if mode != TRIGGER_TIMER:
        log_info("Clumsy trigger mode confirmed: Toggle")
        return True

    seconds = normalize_timer_seconds(
        engine.params.get("_clumsy_timer_seconds", 3)
    )
    timer_combo = None
    for candidate in legacy._find_children_by_class(engine._hwnd, "COMBOBOX"):
        items = legacy._combobox_items(candidate)
        if len(items) == 60 and items[0].strip() == "1" and items[-1].strip() == "60":
            timer_combo = candidate
            break
    if not timer_combo or not _select_combo_text(timer_combo, str(seconds)):
        engine._last_error = (
            f"Clumsy Timer value did not confirm {seconds} seconds"
        )
        return False
    log_info(f"Clumsy trigger mode confirmed: Timer {seconds}s")
    return True


def _sync_all_non_numeric_controls(engine: ManagedClumsyEngine) -> bool:
    for callback in (
        _sync_function_preset,
        _sync_extra_toggles,
        _sync_module_directions,
        _sync_bandwidth_unit,
        _sync_trigger_controls,
    ):
        if not callback(engine):
            log_error(engine._last_error)
            return False
    return True


def _click_rst_next_packet(engine: ManagedClumsyEngine) -> bool:
    if "rst" not in engine.methods:
        engine._last_error = "RST next packet requires Set TCP RST to be enabled"
        return False
    button = legacy._find_child_by_text(engine._hwnd, "RST next packet")
    if not button:
        engine._last_error = "Clumsy RST next packet control was not found"
        return False
    if not legacy._click_button(button):
        engine._last_error = "Clumsy RST next packet click was not accepted"
        return False
    log_info("Clumsy RST next eligible TCP packet one-shot armed")
    return True


def trigger_owned_rst_next_packet(manager: Any, target_ip: str) -> bool:
    """Arm one RST on the exact live Clumsy process owned by *target_ip*."""

    try:
        target = validate_local_target_ip(
            str(target_ip or ""),
            context="Clumsy RST next packet",
        )
        lock = getattr(manager, "_device_lock", None)
        if lock is None:
            return False
        with lock:
            entry = getattr(manager, "disrupted_devices", {}).get(target)
            engine = entry.get("engine") if entry else None
        if not isinstance(engine, ManagedClumsyEngine) or not engine.alive:
            return False
        return _click_rst_next_packet(engine)
    except Exception as exc:
        log_error(f"Clumsy RST next packet action failed: {exc}")
        return False


def _schedule_generation_stop(
    manager: DirectClumsyNetworkDisruptor,
    target_ip: str,
    generation: int,
    seconds: int,
) -> None:
    def worker() -> None:
        time.sleep(float(seconds) + 0.15)
        with manager._device_lock:
            entry = manager.disrupted_devices.get(target_ip)
            current = entry.get("generation") if entry else None
        if current != generation:
            return
        log_info(
            f"Clumsy Timer elapsed ({seconds}s); releasing owned generation "
            f"{generation}"
        )
        manager.reconnect_device_clumsy(target_ip)

    threading.Thread(
        target=worker,
        name="DupeZClumsyTimer",
        daemon=True,
    ).start()


def install_clumsy_full_controls() -> None:
    """Install complete controls exactly once per Python/helper process."""

    if getattr(ManagedClumsyEngine, "_full_controls_installed", False):
        return

    original_assess = legacy.assess_clumsy_compatibility
    original_start_selected = DirectClumsyNetworkDisruptor._start_selected_engine
    original_disconnect = DirectClumsyNetworkDisruptor.disconnect_device_clumsy
    original_gui_start = ManagedClumsyEngine._start_gui_automation
    original_get_stats = ManagedClumsyEngine.get_stats

    def assess_with_full_controls(methods: Any, params: Any):
        decision = original_assess(methods, params)
        reasons = [
            reason
            for reason in decision.reasons
            if not reason.startswith("Clumsy compatibility requires direction=")
            and not reason.startswith(
                "Clumsy cannot preserve per-module direction"
            )
        ]
        if isinstance(params, dict):
            reasons.extend(validate_clumsy_control_params(methods or (), params))
        return legacy.ClumsyCompatibilityDecision(
            representable=not reasons,
            methods=decision.methods,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def start_selected_with_scope(
        manager: DirectClumsyNetworkDisruptor,
        *,
        filter_str: str,
        methods: list[str],
        params: dict[str, Any],
    ):
        effective = dict(params or {})
        try:
            scoped = compose_scoped_filter(
                filter_str,
                str(effective.get("_target_ip") or ""),
                effective.get("_clumsy_filter_predicate", "true"),
            )
        except ValueError as exc:
            manager._last_engine_error = str(exc)
            log_error(manager._last_engine_error)
            return None, "", str(
                effective.get("_engine_preference") or legacy.ENGINE_AUTO
            )

        if effective.get("_clumsy_rst_next_packet"):
            preference = legacy._normalize_engine_preference(
                effective.get("_engine_preference", legacy.ENGINE_AUTO)
            )
            if preference == legacy.ENGINE_NATIVE:
                manager._last_engine_error = (
                    "RST next packet is available only on the owned Clumsy "
                    "0.3.4 process"
                )
                log_error(manager._last_engine_error)
                return None, "", preference
            if preference == legacy.ENGINE_AUTO:
                effective["_engine_preference"] = legacy.ENGINE_CLUMSY

        return original_start_selected(
            manager,
            filter_str=scoped,
            methods=methods,
            params=effective,
        )

    def disconnect_with_timer(
        manager: DirectClumsyNetworkDisruptor,
        target_ip: str,
        methods: Optional[list[str]] = None,
        params: Optional[dict] = None,
        preset: Optional[str] = None,
        target_mac: Optional[str] = None,
        target_hostname: Optional[str] = None,
        target_device_type: Optional[str] = None,
    ) -> bool:
        effective = dict(params or {}) if params is not None else None
        started = original_disconnect(
            manager,
            target_ip,
            methods,
            effective,
            preset,
            target_mac,
            target_hostname,
            target_device_type,
        )
        if not started or not effective:
            return started
        try:
            mode = normalize_trigger_mode(
                effective.get("_clumsy_trigger_mode")
            )
            if mode != TRIGGER_TIMER:
                return started
            seconds = normalize_timer_seconds(
                effective.get("_clumsy_timer_seconds", 3)
            )
            with manager._device_lock:
                entry = manager.disrupted_devices.get(target_ip)
                generation = int(entry.get("generation")) if entry else 0
                if entry is not None:
                    entry["clumsy_trigger_mode"] = mode
                    entry["clumsy_timer_seconds"] = seconds
            if generation:
                _schedule_generation_stop(
                    manager,
                    target_ip,
                    generation,
                    seconds,
                )
        except Exception as exc:
            log_warning(f"Could not arm Clumsy generation timer: {exc}")
        return started

    def gui_start_with_rst(engine: ManagedClumsyEngine) -> bool:
        started = original_gui_start(engine)
        if not started:
            return False
        if not engine.params.get("_clumsy_rst_next_packet"):
            return True
        if _click_rst_next_packet(engine):
            engine._rst_next_packet_armed = True
            return True
        engine.stop()
        return False

    def get_stats_with_full_controls(engine: ManagedClumsyEngine) -> dict[str, Any]:
        stats = dict(original_get_stats(engine))
        stats.update(
            additional_filter=normalize_additional_filter(
                engine.params.get("_clumsy_filter_predicate", "true")
            ),
            filter_preset=normalize_clumsy_label(
                engine.params.get("_clumsy_filter_name"),
                default="DupeZ Target",
            ),
            function_preset=normalize_clumsy_label(
                engine.params.get("_clumsy_function_preset_name"),
                default="DupeZ",
            ),
            trigger_mode=normalize_trigger_mode(
                engine.params.get("_clumsy_trigger_mode")
            ),
            timer_seconds=normalize_timer_seconds(
                engine.params.get("_clumsy_timer_seconds", 3)
            ),
            bandwidth_unit=normalize_bandwidth_unit(
                engine.params.get("bandwidth_size", BANDWIDTH_KB)
            ),
            module_directions={
                method: _direction_for(engine, method)
                for method in engine.methods
                if method in CLUMSY_DIRECTION_KEYS
            },
            rst_next_packet_armed=bool(
                getattr(engine, "_rst_next_packet_armed", False)
            ),
            full_control_integration=True,
        )
        return stats

    legacy.assess_clumsy_compatibility = assess_with_full_controls
    ManagedClumsyEngine._write_config = _write_config_with_named_scope
    ManagedClumsyEngine._write_presets = _write_full_presets
    ManagedClumsyEngine._click_sub_checkboxes = _sync_all_non_numeric_controls
    ManagedClumsyEngine._start_gui_automation = gui_start_with_rst
    ManagedClumsyEngine.get_stats = get_stats_with_full_controls
    DirectClumsyNetworkDisruptor._start_selected_engine = start_selected_with_scope
    DirectClumsyNetworkDisruptor.disconnect_device_clumsy = disconnect_with_timer
    ManagedClumsyEngine._full_controls_installed = True
