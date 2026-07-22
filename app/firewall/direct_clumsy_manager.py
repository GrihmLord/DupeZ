# app/firewall/direct_clumsy_manager.py — owned direct Clumsy integration
"""First-class Clumsy process ownership for DupeZ.

The legacy compatibility engine proved that the bundled Clumsy controls can be
configured and verified, but it used a global ``taskkill /IM clumsy.exe`` sweep
before every start and a force-kill-only stop path. This module preserves its
packet semantics while giving DupeZ exact process ownership.

Invariants:

* DupeZ never kills an unrelated ``clumsy.exe`` process.
* Only one direct Clumsy session may be active in a helper process.
* Auto may fall back to native only for semantics-preserving methods.
* Explicit Clumsy selection fails closed with an actionable error.
* Stop requests Clumsy's Stop state and window close before killing only the
  exact owned PID as a bounded fallback.
* Explicit event capture layers survive target-profile tuning.
"""

from __future__ import annotations

import os
import threading
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

import psutil

from app.firewall import clumsy_network_disruptor as legacy
from app.logs.logger import log_error, log_info, log_warning

__all__ = [
    "ManagedClumsyEngine",
    "DirectClumsyNetworkDisruptor",
    "disruption_manager",
]

_PROCESS_TRANSITION_LOCK = threading.RLock()
_WM_CLOSE = 0x0010
_SW_RESTORE = 9


def _running_clumsy_pids() -> tuple[int, ...]:
    """Return live Clumsy process IDs without exposing command lines."""

    pids: list[int] = []
    for process in psutil.process_iter(("pid", "name")):
        try:
            name = str(process.info.get("name") or "").lower()
            if name in {"clumsy.exe", "clumsy"}:
                pids.append(int(process.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, TypeError):
            continue
    return tuple(sorted(set(pids)))


class ManagedClumsyEngine(legacy.ClumsyEngine):
    """Clumsy compatibility engine with exact child-process ownership."""

    def __init__(
        self,
        clumsy_exe: str,
        clumsy_dir: str,
        filter_str: str,
        methods: list,
        params: dict,
    ) -> None:
        super().__init__(clumsy_exe, clumsy_dir, filter_str, methods, params)
        self._last_error = ""
        self._stop_mode = "not_stopped"
        self._contention_pids: tuple[int, ...] = ()

    def _fail(self, message: str) -> bool:
        self._last_error = str(message)
        log_error(message)
        return False

    def start(self) -> bool:
        """Start the exact bundled process without global process sweeps."""

        self._startup_verified = False
        self._runtime_verified = False
        self._last_error = ""
        self._stop_mode = "not_stopped"

        with _PROCESS_TRANSITION_LOCK:
            try:
                compatibility = legacy.assess_clumsy_compatibility(
                    self.methods,
                    self.params,
                )
                if not compatibility.representable:
                    return self._fail(
                        "Direct Clumsy refused a non-equivalent request: "
                        f"{compatibility.reason}"
                    )
                self.methods = list(compatibility.methods)

                # Never terminate a process we did not create. A standalone
                # Clumsy window remains available for diagnostics.
                self._contention_pids = _running_clumsy_pids()
                if self._contention_pids:
                    return self._fail(
                        "Direct Clumsy is already running outside this event "
                        f"(PID count={len(self._contention_pids)}). Stop that "
                        "session or select Native/Auto; no process was killed."
                    )

                self._write_config()
                self._write_presets()
                for filename, minimum_size in (
                    ("presets.ini", 100),
                    ("config.txt", 10),
                ):
                    path = os.path.join(self.clumsy_dir, filename)
                    if not os.path.isfile(path):
                        return self._fail(
                            f"Direct Clumsy configuration missing: {path}"
                        )
                    if os.path.getsize(path) < minimum_size:
                        return self._fail(
                            f"Direct Clumsy configuration is incomplete: {path}"
                        )

                executable = os.path.abspath(self.clumsy_exe)
                if legacy._safe_sp is None:
                    return self._fail(
                        "Direct Clumsy cannot start because safe_subprocess "
                        "is unavailable"
                    )

                use_silent = self._detect_silent_support(executable)
                argv = [executable, "--silent"] if use_silent else [executable]
                self._proc = legacy._safe_sp.spawn_managed(
                    argv,
                    cwd=self.clumsy_dir,
                    trusted_executable=False,
                    intent="clumsy.direct_owned_launch",
                )
                log_info(
                    "Direct Clumsy launched as owned child: "
                    f"PID={self._proc.pid}"
                )

                if use_silent:
                    time.sleep(0.15)
                    return_code = self._proc.poll()
                    if return_code is not None:
                        self._proc = None
                        return self._fail(
                            "Direct Clumsy silent launch exited immediately "
                            f"(rc={return_code})"
                        )
                    self._startup_verified = True
                    return True

                if not self._start_gui_automation():
                    self._last_error = (
                        self._last_error
                        or "Clumsy controls or Start state could not be verified; "
                        "review the DupeZ log and use diagnostic window mode."
                    )
                    return False
                return True
            except Exception as exc:
                self._last_error = f"Direct Clumsy start failed: {exc}"
                log_error(self._last_error)
                self._cleanup()
                return False

    def _request_graceful_stop(self) -> bool:
        """Stop filtering and close the owned Clumsy window."""

        if not self._hwnd:
            return False
        try:
            stop_button = legacy._find_child_by_text(self._hwnd, "Stop")
            if stop_button:
                legacy._click_button(stop_button)
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    if legacy._get_window_text(stop_button).lower() == "start":
                        break
                    time.sleep(0.05)

            user32 = legacy.ctypes.windll.user32
            user32.SendMessageW(self._hwnd, _WM_CLOSE, 0, 0)
            return True
        except Exception as exc:
            log_warning(f"Direct Clumsy graceful-stop request failed: {exc}")
            return False

    def _wait_for_exit(self, timeout_seconds: float) -> bool:
        process = self._proc
        if process is None:
            return True
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return True
            time.sleep(0.05)
        return process.poll() is not None

    def stop(self) -> None:
        """Gracefully stop, then kill only this exact child as fallback."""

        with _PROCESS_TRANSITION_LOCK:
            process = self._proc
            if process is None:
                self._reset_runtime_state()
                return

            graceful_requested = self._request_graceful_stop()
            if graceful_requested and self._wait_for_exit(1.5):
                self._stop_mode = "graceful"
            else:
                try:
                    process.kill()
                    self._stop_mode = "owned_pid_kill_fallback"
                except Exception as exc:
                    self._stop_mode = "kill_failed"
                    self._last_error = f"Owned Clumsy process stop failed: {exc}"
                    log_error(self._last_error)

            self._reset_runtime_state()
            log_info(f"Direct Clumsy stopped (mode={self._stop_mode})")

    def _reset_runtime_state(self) -> None:
        self._proc = None
        self._hwnd = None
        self._startup_verified = False
        self._runtime_verified = False

    def show_diagnostic_window(self) -> bool:
        """Restore the owned window for operator-side diagnostics."""

        if not self._hwnd or not self.alive:
            return False
        try:
            user32 = legacy.ctypes.windll.user32
            ex_style = user32.GetWindowLongW(self._hwnd, legacy.GWL_EXSTYLE)
            user32.SetWindowLongW(
                self._hwnd,
                legacy.GWL_EXSTYLE,
                ex_style & ~legacy.WS_EX_LAYERED,
            )
            user32.ShowWindow(self._hwnd, _SW_RESTORE)
            user32.SetForegroundWindow(self._hwnd)
            return True
        except Exception as exc:
            self._last_error = f"Could not show Clumsy diagnostic window: {exc}"
            log_error(self._last_error)
            return False

    def get_stats(self) -> Dict[str, Any]:
        stats = dict(super().get_stats())
        stats.update(
            pid=getattr(self._proc, "pid", None),
            window_handle=int(self._hwnd) if self._hwnd else None,
            capture_layer=(
                "local" if self.params.get("_network_local") else "remote"
            ),
            filter_expression=self.filter_str,
            last_error=self._last_error,
            stop_mode=self._stop_mode,
            contention_detected=bool(self._contention_pids),
            contention_process_count=len(self._contention_pids),
            owned_process=True,
        )
        return stats


class DirectClumsyNetworkDisruptor(legacy.ClumsyNetworkDisruptor):
    """Manager that makes direct Clumsy a first-class, single-session engine."""

    def __init__(self) -> None:
        super().__init__()
        self._engine_transition_lock = threading.RLock()
        self._last_engine_error = ""
        self._last_requested_engine = legacy.ENGINE_AUTO
        self._last_actual_engine = ""

    def _active_clumsy_targets(self) -> tuple[str, ...]:
        with self._device_lock:
            return tuple(
                target
                for target, info in self.disrupted_devices.items()
                if info.get("engine_name") == legacy.ENGINE_CLUMSY
                and getattr(info.get("engine"), "alive", False)
            )

    def disconnect_device_clumsy(
        self,
        target_ip: str,
        methods: Optional[List[str]] = None,
        params: Optional[Dict] = None,
        preset: Optional[str] = None,
        target_mac: Optional[str] = None,
        target_hostname: Optional[str] = None,
        target_device_type: Optional[str] = None,
    ) -> bool:
        """Preserve an explicit event layer while retaining profile tuning."""

        effective_params = deepcopy(dict(params or {})) if params is not None else None
        explicit_layer = bool(
            effective_params
            and effective_params.get("_network_layer_explicit")
        )
        if explicit_layer and preset is None:
            try:
                from app.firewall.target_profile import resolve_target_profile

                detection = resolve_target_profile(
                    target_ip=target_ip,
                    mac=target_mac,
                    hostname=target_hostname,
                    device_type=target_device_type,
                )
                preset = detection.profile
                effective_params.setdefault("_target_profile", detection.profile)
                effective_params.setdefault(
                    "_network_class",
                    getattr(detection, "connection_mode", "unknown"),
                )
                effective_params.setdefault("_platform", detection.platform)
                log_info(
                    "Explicit event layer preserved with target profile "
                    f"{detection.profile!r}"
                )
            except Exception as exc:
                self._last_engine_error = (
                    "Explicit capture layer could not resolve target tuning: "
                    f"{exc}"
                )
                log_error(self._last_engine_error)
                return False

        return super().disconnect_device_clumsy(
            target_ip,
            methods,
            effective_params,
            preset=preset,
            target_mac=target_mac,
            target_hostname=target_hostname,
            target_device_type=target_device_type,
        )

    def _start_selected_engine(
        self,
        *,
        filter_str: str,
        methods: List[str],
        params: Dict[str, Any],
    ) -> tuple[Optional[Any], str, str]:
        preference = legacy._normalize_engine_preference(
            params.get("_engine_preference", legacy.ENGINE_AUTO)
        )
        compatibility = legacy.assess_clumsy_compatibility(methods, params)
        self._last_requested_engine = preference
        self._last_actual_engine = ""
        self._last_engine_error = ""

        def try_native() -> Optional[Any]:
            if not legacy.NATIVE_ENGINE_AVAILABLE:
                self._last_engine_error = "Native WinDivert engine is unavailable"
                log_error(self._last_engine_error)
                return None
            native_engine = None
            try:
                native_engine = legacy.NativeWinDivertEngine(
                    dll_path=self.windivert_dll,
                    filter_str=filter_str,
                    methods=methods,
                    params=params,
                )
                if native_engine.start():
                    self._last_actual_engine = legacy.ENGINE_NATIVE
                    return native_engine
                self._last_engine_error = "Native WinDivert start returned False"
            except Exception as exc:
                self._last_engine_error = f"Native WinDivert start failed: {exc}"
            if native_engine is not None:
                try:
                    native_engine.stop()
                except Exception:
                    pass
            log_error(self._last_engine_error)
            return None

        def try_clumsy() -> Optional[Any]:
            if not compatibility.representable:
                self._last_engine_error = (
                    "Direct Clumsy cannot preserve this event's semantics: "
                    f"{compatibility.reason}"
                )
                log_error(self._last_engine_error)
                return None

            if self._active_clumsy_targets():
                self._last_engine_error = (
                    "Direct Clumsy already owns one active event. Stop it "
                    "before starting another explicit Clumsy event."
                )
                log_error(self._last_engine_error)
                return None

            if not self.clumsy_exe or not os.path.isfile(self.clumsy_exe):
                self._last_engine_error = (
                    f"Bundled clumsy.exe is missing: {self.clumsy_exe}"
                )
                log_error(self._last_engine_error)
                return None

            engine = ManagedClumsyEngine(
                clumsy_exe=self.clumsy_exe,
                clumsy_dir=self._get_clumsy_dir(),
                filter_str=filter_str,
                methods=list(compatibility.methods),
                params=params,
            )
            if engine.start():
                self._last_actual_engine = legacy.ENGINE_CLUMSY
                return engine
            self._last_engine_error = (
                engine.get_stats().get("last_error")
                or "Direct Clumsy failed to start"
            )
            try:
                engine.stop()
            except Exception:
                pass
            return None

        with self._engine_transition_lock:
            if preference == legacy.ENGINE_CLUMSY:
                engine = try_clumsy()
                return (
                    engine,
                    legacy.ENGINE_CLUMSY if engine else "",
                    preference,
                )

            if preference == legacy.ENGINE_NATIVE:
                engine = try_native()
                return (
                    engine,
                    legacy.ENGINE_NATIVE if engine else "",
                    preference,
                )

            if compatibility.representable:
                engine = try_clumsy()
                if engine is not None:
                    return engine, legacy.ENGINE_CLUMSY, preference

                requested_methods = set(compatibility.methods)
                if not requested_methods.issubset(
                    legacy._NATIVE_CLUMSY_FALLBACK_METHODS
                ):
                    self._last_engine_error = (
                        self._last_engine_error
                        or "Native fallback would change packet semantics"
                    )
                    return None, "", preference
                log_warning(
                    "Direct Clumsy was unavailable; Auto is trying the "
                    "bounded native equivalent"
                )
            else:
                log_info(
                    "Event requires native-only behavior: "
                    f"{compatibility.reason}"
                )

            engine = try_native()
            if engine is not None:
                return engine, legacy.ENGINE_NATIVE, preference
            return None, "", preference

    def get_device_status_clumsy(self, target_ip: str) -> Dict:
        status = dict(super().get_device_status_clumsy(target_ip))
        if not status.get("disrupted"):
            return status
        with self._device_lock:
            info = self.disrupted_devices.get(target_ip, {})
            engine = info.get("engine")
            status["generation"] = info.get("generation")
        if engine is not None and hasattr(engine, "get_stats"):
            engine_stats = dict(engine.get_stats())
            for key in (
                "startup_verified",
                "verification_state",
                "capture_layer",
                "last_error",
                "stop_mode",
                "owned_process",
            ):
                if key in engine_stats:
                    status[key] = engine_stats[key]
        return status

    def get_clumsy_status(self) -> Dict:
        status = dict(super().get_clumsy_status())
        status.update(
            direct_clumsy_integration=True,
            single_clumsy_session=True,
            active_clumsy_targets=list(self._active_clumsy_targets()),
            last_requested_engine=self._last_requested_engine,
            last_actual_engine=self._last_actual_engine,
            last_engine_error=self._last_engine_error,
        )
        return status

    def show_clumsy_diagnostic_window(self, target_ip: str) -> bool:
        with self._device_lock:
            info = self.disrupted_devices.get(target_ip)
            engine = info.get("engine") if info else None
        if isinstance(engine, ManagedClumsyEngine):
            return engine.show_diagnostic_window()
        return False


# One manager per process. In split mode this singleton lives only in the
# elevated helper; in Compat/inproc it lives in the GUI process.
disruption_manager = DirectClumsyNetworkDisruptor()
