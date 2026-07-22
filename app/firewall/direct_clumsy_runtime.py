# app/firewall/direct_clumsy_runtime.py — staged GUI verification
"""Install the hardware-validated direct Clumsy GUI automation path.

The Kalirenegade fork shows its top-level IUP dialog before every module toggle
and numeric control has been materialized as a Win32 child. Returning from
``_find_window_by_pid`` therefore proves only that the shell exists; starting
module automation immediately can race the later ``uiSetupModule`` calls.

This module patches only :class:`ManagedClumsyEngine`, preserving the legacy
compatibility helpers and the exact bundled binary while adding:

* a bounded full-control-tree readiness barrier;
* explicit stage/error reporting;
* process-liveness checks throughout startup;
* unchanged strict verification of layer, module toggles, sub-controls,
  numeric callbacks, and Start->Stop transition.

Detailed errors produced by the control adapters are retained. A stage-level
fallback is used only when the failing adapter did not provide its own control
name, expected value, observed value, or Win32 callback result.
"""

from __future__ import annotations

import time
from typing import Any

from app.firewall import clumsy_network_disruptor as legacy
from app.firewall.direct_clumsy_manager import ManagedClumsyEngine
from app.logs.logger import log_error, log_info

__all__ = ["install_direct_clumsy_runtime"]

_CONTROL_TREE_TIMEOUT_SECONDS = 6.0
_WINDOW_TIMEOUT_SECONDS = 5.0
_POLL_SECONDS = 0.05


def _process_exit_code(engine: ManagedClumsyEngine) -> Any:
    process = engine._proc
    return None if process is None else process.poll()


def _network_combo_ready(engine: ManagedClumsyEngine) -> bool:
    for combo in legacy._find_children_by_class(engine._hwnd, "COMBOBOX"):
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


def _control_tree_state(engine: ManagedClumsyEngine) -> dict[str, Any]:
    start_button = legacy._find_child_by_text(engine._hwnd, "Start")
    if not start_button:
        start_button = legacy._find_child_by_text(engine._hwnd, "start")

    missing_modules = []
    for method in engine.methods:
        text = legacy.MODULE_CHECKBOX_TEXT.get(method)
        if text and not engine._find_checkbox(text):
            missing_modules.append(text)

    edits = legacy._get_edit_controls_sorted(engine._hwnd)
    required_edits = _required_edit_count(engine)
    return {
        "start_button": bool(start_button),
        "network_combo": _network_combo_ready(engine),
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


def _wait_for_control_tree(engine: ManagedClumsyEngine) -> bool:
    deadline = time.monotonic() + _CONTROL_TREE_TIMEOUT_SECONDS
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        exit_code = _process_exit_code(engine)
        if exit_code is not None:
            engine._last_error = (
                "Clumsy exited while waiting for its Functions controls "
                f"(rc={exit_code})"
            )
            return False

        last_state = _control_tree_state(engine)
        if _control_tree_ready(last_state):
            log_info(
                "ClumsyEngine GUI: complete control tree ready "
                f"(edits={last_state['edit_count']}, "
                f"methods={engine.methods})"
            )
            return True
        time.sleep(_POLL_SECONDS)

    engine._last_error = (
        "Clumsy Functions control tree did not become ready within "
        f"{_CONTROL_TREE_TIMEOUT_SECONDS:g}s: {last_state}"
    )
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
            "ClumsyEngine GUI: found owned window "
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
