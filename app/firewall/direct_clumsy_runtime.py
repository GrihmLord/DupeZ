# app/firewall/direct_clumsy_runtime.py — staged GUI verification
"""Install the hardware-validated direct Clumsy GUI automation path.

The bundled IUP fork can create more than one top-level window during startup,
and its final native child controls are not guaranteed to materialize while the
dialog remains fully hidden. Returning the first exact-PID HWND therefore proves
ownership only; it does not prove that the selected candidate is the real Clumsy
control surface.

This module preserves exact process ownership while adding:

* a bounded candidate-aware control-tree readiness barrier;
* pre-show cloaking before a no-activation technical show;
* continuous exact-PID candidate re-enumeration and safe HWND rebinding;
* bounded sanitized candidate diagnostics;
* process-liveness checks throughout startup; and
* unchanged strict verification of layer, module toggles, sub-controls,
  numeric callbacks, and Start->Stop transition.
"""

from __future__ import annotations

import time
from typing import Any

from app.firewall import clumsy_hidden_window as hidden
from app.firewall import clumsy_network_disruptor as legacy
from app.firewall.direct_clumsy_manager import ManagedClumsyEngine
from app.logs.logger import log_error, log_info

__all__ = ["install_direct_clumsy_runtime"]

_CONTROL_TREE_TIMEOUT_SECONDS = 6.0
_WINDOW_TIMEOUT_SECONDS = 5.0
_POLL_SECONDS = 0.05
_MAX_CANDIDATE_DIAGNOSTICS = 30


def _process_exit_code(engine: ManagedClumsyEngine) -> Any:
    process = engine._proc
    return None if process is None else process.poll()


def _window_exists(hwnd: int, user32: Any = None) -> bool:
    user32 = user32 or legacy.ctypes.windll.user32
    try:
        return int(hwnd) > 0 and bool(user32.IsWindow(hwnd))
    except AttributeError:
        return int(hwnd) > 0


def _network_combo_ready(hwnd: int) -> bool:
    for combo in legacy._find_children_by_class(hwnd, "COMBOBOX"):
        lowered = [item.lower() for item in legacy._combobox_items(combo)]
        if any("(local)" in item for item in lowered) and any(
            "(remote)" in item for item in lowered
        ):
            return True
    return False


def _required_edit_count(engine: ManagedClumsyEngine) -> int:
    required_indices = [0]
    for index, parameter in legacy.EDIT_INDEX_MAP.items():
        method = legacy._EDIT_PARAM_METHOD.get(parameter)
        if method in engine.methods:
            required_indices.append(int(index))
    return max(required_indices) + 1


def _control_tree_state(
    engine: ManagedClumsyEngine,
    hwnd: int | None = None,
) -> dict[str, Any]:
    candidate = int(hwnd if hwnd is not None else (engine._hwnd or 0))
    start_button = legacy._find_child_by_text(candidate, "Start")
    if not start_button:
        start_button = legacy._find_child_by_text(candidate, "start")

    missing_modules = []
    for method in engine.methods:
        text = legacy.MODULE_CHECKBOX_TEXT.get(method)
        if text and not legacy._find_child_by_text(candidate, text):
            missing_modules.append(text)

    edits = legacy._get_edit_controls_sorted(candidate)
    required_edits = _required_edit_count(engine)
    return {
        "start_button": bool(start_button),
        "network_combo": _network_combo_ready(candidate),
        "missing_modules": tuple(missing_modules),
        "edit_count": len(edits),
        "required_edit_count": required_edits,
    }


def _control_tree_ready(state: dict[str, Any]) -> bool:
    return bool(
        state["start_button"]
        and state["network_combo"]
        and not state["missing_modules"]
        and state["edit_count"] >= state["required_edit_count"]
    )


def _readiness_score(engine: ManagedClumsyEngine, state: dict[str, Any]) -> int:
    requested_modules = max(1, len(engine.methods))
    matched_modules = max(
        0,
        requested_modules - len(tuple(state.get("missing_modules") or ())),
    )
    return (
        (4 if state.get("start_button") else 0)
        + (4 if state.get("network_combo") else 0)
        + matched_modules * 2
        + min(
            int(state.get("edit_count") or 0),
            int(state.get("required_edit_count") or 0),
        )
    )


def _safe_window_text(hwnd: int) -> str:
    raw = str(legacy._get_window_text(hwnd) or "")
    sanitized = "".join(
        character if character.isprintable() else "?"
        for character in raw
    )
    return sanitized[:120]


def _window_class(hwnd: int, user32: Any) -> str:
    try:
        buffer = legacy.ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return str(buffer.value or "")[:80]
    except Exception:
        return ""


def _child_class_counts(hwnd: int, user32: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    callback_factory = legacy.WNDENUMPROC or (lambda callback: callback)

    def child_callback(child_hwnd, _lparam):
        try:
            buffer = legacy.ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(child_hwnd, buffer, 128)
            class_name = str(buffer.value or "<unknown>")[:80]
        except Exception:
            class_name = "<unknown>"
        counts[class_name] = counts.get(class_name, 0) + 1
        return len(counts) < 40

    try:
        user32.EnumChildWindows(
            hwnd,
            callback_factory(child_callback),
            0,
        )
    except Exception:
        return {}
    return dict(sorted(counts.items())[:20])


def _candidate_diagnostic(
    engine: ManagedClumsyEngine,
    hwnd: int,
    state: dict[str, Any],
    *,
    user32: Any = None,
) -> dict[str, Any]:
    user32 = user32 or legacy.ctypes.windll.user32
    try:
        visible = bool(user32.IsWindowVisible(hwnd))
    except Exception:
        visible = False
    try:
        enabled = bool(user32.IsWindowEnabled(hwnd))
    except Exception:
        enabled = False

    return {
        "top_level": True,
        "candidate": True,
        "hwnd": int(hwnd),
        "class": _window_class(hwnd, user32),
        "text": _safe_window_text(hwnd),
        "control_id": 0,
        "visible": visible,
        "enabled": enabled,
        "child_class_counts": _child_class_counts(hwnd, user32),
        "readiness": dict(state),
        "readiness_score": _readiness_score(engine, state),
    }


def _format_candidate_diagnostics(records: list[dict[str, Any]]) -> str:
    if not records:
        return "candidates=[]"
    parts = []
    for record in records[:8]:
        parts.append(
            "{"
            f"hwnd={record.get('hwnd')}, "
            f"class={record.get('class')!r}, "
            f"title={record.get('text')!r}, "
            f"visible={record.get('visible')}, "
            f"enabled={record.get('enabled')}, "
            f"children={record.get('child_class_counts')}, "
            f"readiness={record.get('readiness')}"
            "}"
        )
    return "candidates=[" + ", ".join(parts) + "]"


def _wait_for_control_tree(engine: ManagedClumsyEngine) -> bool:
    process = engine._proc
    if process is None:
        engine._last_error = "Clumsy process is missing during control discovery"
        return False

    pid = int(process.pid)
    deadline = time.monotonic() + _CONTROL_TREE_TIMEOUT_SECONDS
    prepared: set[int] = set()
    if engine._hwnd:
        prepared.add(int(engine._hwnd))

    last_records: list[dict[str, Any]] = []
    best_state: dict[str, Any] = {}

    while time.monotonic() < deadline:
        exit_code = _process_exit_code(engine)
        if exit_code is not None:
            engine._failure_diagnostics = last_records[
                :_MAX_CANDIDATE_DIAGNOSTICS
            ]
            engine._last_error = (
                "Clumsy exited while waiting for its Functions controls "
                f"(rc={exit_code}); "
                + _format_candidate_diagnostics(last_records)
            )
            return False

        candidates = hidden.enumerate_owned_clumsy_windows(pid)
        current_records: list[dict[str, Any]] = []

        for hwnd in candidates:
            candidate = int(hwnd)
            if not _window_exists(candidate):
                continue

            if candidate not in prepared:
                if not hidden.pre_show_cloak_owned_window(candidate):
                    continue
                prepared.add(candidate)

            state = _control_tree_state(engine, candidate)
            record = _candidate_diagnostic(engine, candidate, state)
            current_records.append(record)

            if _control_tree_ready(state):
                engine._hwnd = candidate
                log_info(
                    "ClumsyEngine GUI: complete control tree ready "
                    f"(hwnd={candidate}, edits={state['edit_count']}, "
                    f"methods={engine.methods})"
                )
                return True

        if current_records:
            current_records.sort(
                key=lambda item: (
                    int(item.get("readiness_score") or 0),
                    int(item.get("hwnd") or 0),
                ),
                reverse=True,
            )
            best = current_records[0]
            best_state = dict(best.get("readiness") or {})
            engine._hwnd = int(best["hwnd"])
            last_records = current_records[:_MAX_CANDIDATE_DIAGNOSTICS]

        time.sleep(_POLL_SECONDS)

    engine._failure_diagnostics = last_records[:_MAX_CANDIDATE_DIAGNOSTICS]
    engine._last_error = (
        "Clumsy Functions control tree did not become ready within "
        f"{_CONTROL_TREE_TIMEOUT_SECONDS:g}s: {best_state}; "
        + _format_candidate_diagnostics(last_records)
    )
    log_error(engine._last_error)
    return False


def _retain_adapter_error(
    engine: ManagedClumsyEngine,
    fallback: str,
) -> str:
    detail = str(getattr(engine, "_last_error", "") or "").strip()
    if detail:
        return detail
    return fallback


def _fail_stage(
    engine: ManagedClumsyEngine,
    fallback: str,
) -> bool:
    engine._last_error = _retain_adapter_error(engine, fallback)
    log_error(
        f"Clumsy startup failed during {engine._last_stage}: "
        f"{engine._last_error}"
    )
    engine._cleanup()
    return False


def _staged_start_gui_automation(engine: ManagedClumsyEngine) -> bool:
    """Verify the entire fork GUI before reporting an active disruption."""

    engine._startup_verified = False
    engine._last_error = ""
    try:
        engine._last_stage = "window_discovery"
        if engine._proc is None:
            engine._last_error = "Clumsy process is missing before window discovery"
            return False
        engine._hwnd = legacy._find_window_by_pid(
            engine._proc.pid,
            timeout=_WINDOW_TIMEOUT_SECONDS,
        )
        if not engine._hwnd:
            exit_code = _process_exit_code(engine)
            engine._last_error = (
                "Clumsy window was not discovered"
                if exit_code is None
                else f"Clumsy exited before window discovery (rc={exit_code})"
            )
            engine._cleanup()
            return False
        title = legacy._get_window_text(engine._hwnd)
        log_info(
            "ClumsyEngine GUI: found owned bootstrap window "
            f"hwnd={engine._hwnd} title={title!r}"
        )

        engine._last_stage = "control_tree_readiness"
        if not _wait_for_control_tree(engine):
            return _fail_stage(
                engine,
                "Clumsy Functions control tree did not become ready",
            )

        engine._last_error = ""
        engine._last_stage = "network_layer"
        if not engine._select_network_layer():
            requested = (
                "Local / NETWORK"
                if engine.params.get("_network_local")
                else "Remote / NETWORK_FORWARD"
            )
            return _fail_stage(
                engine,
                "Clumsy could not confirm the requested capture layer: "
                f"{requested}",
            )

        engine._last_error = ""
        engine._last_stage = "module_toggles"
        if not engine._enable_modules():
            return _fail_stage(
                engine,
                "Clumsy did not confirm every requested top-level module toggle",
            )

        engine._last_error = ""
        engine._last_stage = "sub_checkboxes"
        if not engine._click_sub_checkboxes():
            return _fail_stage(
                engine,
                "Clumsy did not confirm every requested module sub-checkbox",
            )

        engine._last_error = ""
        engine._last_stage = "numeric_inputs"
        if not engine._set_input_values():
            return _fail_stage(
                engine,
                "Clumsy did not confirm every requested numeric input callback",
            )

        engine._last_error = ""
        engine._last_stage = "start_filtering"
        started = engine._click_start_button()
        if not started:
            started = engine._try_keybind_fallback()
        if not started:
            return _fail_stage(
                engine,
                "Clumsy Start control did not transition to Stop",
            )

        time.sleep(0.1)
        exit_code = _process_exit_code(engine)
        if exit_code is not None:
            engine._last_error = (
                "Clumsy exited immediately after verified Start "
                f"(rc={exit_code})"
            )
            engine._proc = None
            engine._startup_verified = False
            return False

        engine._startup_verified = True
        engine._last_stage = "running"
        legacy._hide_window(engine._hwnd)
        log_info(
            "ClumsyEngine RUNNING: "
            f"PID={engine._proc.pid}, methods={engine.methods}, "
            f"filter={engine.filter_str}"
        )
        return True
    except Exception as exc:
        engine._last_error = (
            f"Clumsy GUI automation failed during {engine._last_stage}: {exc}"
        )
        log_error(engine._last_error)
        engine._cleanup()
        return False


def install_direct_clumsy_runtime() -> None:
    """Install the staged runtime exactly once for this Python process."""

    if getattr(ManagedClumsyEngine, "_staged_runtime_installed", False):
        return
    ManagedClumsyEngine._start_gui_automation = _staged_start_gui_automation
    ManagedClumsyEngine._staged_runtime_installed = True
