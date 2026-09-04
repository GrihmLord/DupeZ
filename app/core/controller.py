# app/core/controller.py — DupeZ Controller
"""
Central orchestrator for DupeZ: device scanning, disruption delegation,
auto-scan loop, plugin lifecycle, and settings management.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import psutil

from app.core.cut_chain import (
    ChainConfig,
    ChainEvent,
    CutChainRunner,
    build_automatic_connection_test,
    validate_chain_config,
)
from app.core.kill_switch import (
    KillSwitch,
    KillSwitchConfig,
    KillSwitchConfigurationError,
    build_kill_switch_config,
    sanitize_process_basenames,
)
from app.core.operation_journal import OperationJournal
from app.core.safety_policy import SafetyPolicy
from app.core.scheduler import DisruptionScheduler
from app.core.state import AppSettings, AppState, Device
from app.firewall import blocker
from app.logs.logger import log_error, log_info, log_network_scan
from app.network import device_scan
from app.plugins.loader import PluginLoader
from app.utils.helpers import mask_ip

__all__ = ["AppController"]


@dataclass(frozen=True)
class _OperationDeadline:
    generation: int
    timer: threading.Timer
    expires_monotonic: float
    expires_unix: float


def _restore_ip_forwarding(enabled: bool) -> bool:
    from app.network.arp_spoof import _set_ip_forwarding
    return bool(_set_ip_forwarding(bool(enabled)))


class _DryRunManager:
    def initialize(self) -> bool:
        return True

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def stop_device(self, _ip: str) -> bool:
        return True

    def stop_all_devices(self) -> bool:
        return True

    def get_disrupted_devices(self) -> List[str]:
        return []

    def mark_cut_outcome(self, _persisted: bool, ip=None) -> int:
        return 0

    def get_device_status(self, _ip: str) -> Dict:
        return {}

    def get_status(self) -> Dict:
        return {"initialized": False, "running": False, "dry_run": True}

    def get_engine_stats(self) -> Dict:
        return {}


class _DryRunCache:
    @staticmethod
    def get_cached_devices() -> list:
        return []

    @staticmethod
    def update_cache(_devices: list) -> None:
        return None


class _InactiveService:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def discover(self) -> list:
        return []

    def load_all(self, _controller) -> list:
        return []

    def unload_all(self) -> None:
        return None

    def get_active_plugins(self) -> list:
        return []

    def get_plugin_info(self) -> list:
        return []

    def get_ui_panel_plugins(self) -> list:
        return []


class AppController:
    """Top-level controller that ties together scanning, disruption,
    scheduling, plugins, and persistent state."""

    _DEADLINE_RELEASE_RETRY_SECONDS = 1.0

    def __init__(
        self,
        *,
        disruption_manager: Any = None,
        device_cache: Any = None,
        save_all: Optional[Callable[[], bool]] = None,
        state: Optional[AppState] = None,
        plugin_loader: Any = None,
        scheduler_factory: Callable[..., Any] = DisruptionScheduler,
        safety_policy: Optional[SafetyPolicy] = None,
        recovery_journal: Optional[OperationJournal] = None,
        clear_firewall_blocks: Callable[[], bool] = blocker.clear_all_dupez_blocks,
        get_blocked_ips: Callable[[], List[str]] = blocker.get_blocked_ips,
        restore_ip_forwarding: Callable[[bool], bool] = _restore_ip_forwarding,
        auto_start: bool = True,
    ) -> None:
        self.state = state if state is not None else AppState()
        self._safety_policy_injected = safety_policy is not None
        self.safety_policy = (
            safety_policy
            if safety_policy is not None
            else SafetyPolicy.from_settings(self.state.settings)
        )

        if self.safety_policy.dry_run:
            disruption_manager = disruption_manager or _DryRunManager()
            device_cache = device_cache or _DryRunCache()
            save_all = save_all or (lambda: True)
            plugin_loader = plugin_loader or _InactiveService()

        if disruption_manager is None:
            from app.firewall_helper.feature_flag import get_disruption_manager
            disruption_manager = get_disruption_manager()
        if device_cache is None or save_all is None:
            from app.core import data_persistence
            if device_cache is None:
                device_cache = data_persistence.device_cache_manager
            if save_all is None:
                save_all = data_persistence.save_all_data

        self._disruption_manager = disruption_manager
        self._device_cache = device_cache
        self._save_all = save_all
        self._lifecycle_lock = threading.Lock()
        self._started = False
        self._engine_initialized = False
        self._network_operations_blocked_reason: Optional[str] = None
        self._kill_switch_config_error: Optional[str] = None
        self._deadline_lock = threading.Lock()
        self._deadline_generation = 0
        self._deadline_timers: Dict[str, _OperationDeadline] = {}
        self._automatic_state_lock = threading.RLock()
        self._automatic_transition_lock = threading.RLock()
        self._automatic_generation = 0
        self._automatic_runner: Optional[CutChainRunner] = None
        self._recovery_journal = recovery_journal or OperationJournal()
        self._clear_firewall_blocks = clear_firewall_blocks
        self._get_blocked_ips = get_blocked_ips
        self._restore_ip_forwarding = restore_ip_forwarding
        self.scan_thread: Optional[threading.Thread] = None
        self.stop_scanning = False
        self.auto_scan_enabled = True
        self._scan_lock = threading.Lock()
        self._scan_stop_event = threading.Event()

        self.scheduler = (
            _InactiveService()
            if self.safety_policy.dry_run
            else scheduler_factory(
                disrupt_fn=self.disrupt_device,
                stop_fn=self.stop_disruption,
            )
        )
        self.plugin_loader = (
            plugin_loader if plugin_loader is not None else PluginLoader()
        )
        try:
            kill_switch_config = self._build_kill_switch_config(
                self.state.settings
            )
        except KillSwitchConfigurationError:
            # Keep the operator's panic stop available, but fail closed for
            # new mutations until the malformed persisted settings are fixed.
            self._kill_switch_config_error = (
                "automatic kill-switch settings are invalid"
            )
            kill_switch_config = KillSwitchConfig(enabled=False)
        self._kill_switch = self._new_kill_switch(kill_switch_config)
        if auto_start:
            self.start()

    def start(self) -> None:
        """Start controller-owned services exactly once."""
        with self._lifecycle_lock:
            if self._started:
                return
            try:
                self._load_device_cache()
                self._init_engine()
                self._kill_switch.start()
                if self.safety_policy.dry_run:
                    self._started = True
                    log_info(
                        "Safety dry-run controller started without scheduler, "
                        "plugins, auto-scan, or packet engine"
                    )
                    return
                try:
                    self._recover_stale_network_state()
                except RuntimeError as exc:
                    # A recovery failure must fail closed for every new
                    # network mutation, but it must not permanently brick
                    # unrelated UI/diagnostic features. Keep the controller
                    # alive in a clearly reportable recovery-blocked state.
                    self._network_operations_blocked_reason = str(exc)
                    self._started = True
                    log_error(
                        "Controller started in recovery-blocked safe mode: "
                        f"{exc}"
                    )
                    return
                self.scheduler.start()
                self._init_plugins()
                if self.state.settings.auto_scan:
                    self.start_auto_scan()
                self._started = True
            except Exception:
                self._rollback_failed_start()
                raise

    def _rollback_failed_start(self) -> None:
        """Best-effort cleanup after a partial startup failure."""
        steps = [
            ("automatic kill switch", self._stop_kill_switch),
            ("automatic workflow", self.stop_automatic_workflow),
            ("auto-scan", self.stop_auto_scan),
            ("scheduler", self.scheduler.stop),
        ]
        # Calling stop() on a split proxy that never initialized attempts to
        # launch the elevated helper again, turning one startup failure into a
        # second UAC prompt/15-second wait.
        if self._engine_initialized:
            steps.append(("disruption engine", self._stop_engine))
        for name, stop_fn in steps:
            try:
                stop_fn()
            except Exception as exc:
                log_error(f"Startup rollback failed ({name}): {exc}")

    def _stop_engine(self) -> None:
        """Stop an initialized engine and update lifecycle ownership."""
        if not self._engine_initialized:
            return
        stopped = self._disruption_manager.stop()
        if stopped is False:
            raise RuntimeError("disruption engine did not confirm stop")
        # ``None`` is the established successful return for in-process engine
        # implementations.  Only an exception or an explicit False means the
        # controller must retain ownership for a later cleanup attempt.
        self._engine_initialized = False

    # ── Automatic kill switch ────────────────────────────────────

    def _build_kill_switch_config(self, settings: object) -> KillSwitchConfig:
        return build_kill_switch_config(
            settings,
            get_drop_counters=self._get_kill_switch_drop_counters,
        )

    def _new_kill_switch(self, config: KillSwitchConfig) -> KillSwitch:
        return KillSwitch(config, self._handle_kill_switch_fire)

    def _handle_kill_switch_fire(self, _reason: str) -> bool:
        # KillSwitch owns reason logging. Keep the callback focused on the
        # existing restoration path so no target or per-device data is copied.
        return self.stop_all_disruptions()

    def fire_manual_kill_switch(
        self,
        reason: str = "operator panic stop",
    ) -> bool:
        """Fire the manual panic stop regardless of automatic configuration."""
        return self._kill_switch.fire_manual(reason)

    def _stop_kill_switch(self) -> None:
        if not self._kill_switch.stop():
            raise RuntimeError("automatic kill-switch worker did not stop")

    def _install_kill_switch(
        self,
        config: KillSwitchConfig,
    ) -> tuple[KillSwitch, bool]:
        """Install a validated config without ever overlapping workers."""
        previous = self._kill_switch
        should_run = self._started or previous.is_running
        if not previous.stop():
            raise RuntimeError(
                "automatic kill-switch worker could not be stopped"
            )

        replacement = self._new_kill_switch(config)
        try:
            if should_run:
                replacement.start()
        except Exception:
            if should_run:
                previous.start()
            raise
        self._kill_switch = replacement
        return previous, should_run

    def _restore_kill_switch(
        self,
        previous: KillSwitch,
        should_run: bool,
    ) -> None:
        current = self._kill_switch
        if current is not previous and not current.stop():
            raise RuntimeError(
                "replacement automatic kill-switch worker could not be stopped"
            )
        self._kill_switch = previous
        if should_run and not previous.is_running:
            previous.start()

    # ── Disruption engine ───────────────────────────────────────

    def _init_engine(self) -> None:
        """Initialise the disruption engine (NativeWinDivert or clumsy.exe fallback)."""
        if self.safety_policy.dry_run:
            log_info("Safety dry-run enabled; packet engine initialization skipped")
            return
        try:
            if self._disruption_manager.initialize():
                self._engine_initialized = True
                self._disruption_manager.start()
                log_info("Disruption engine initialized")
            else:
                raise RuntimeError(
                    "Disruption engine init failed — check administrator "
                    "privileges and WinDivert files"
                )
        except Exception as e:
            log_error(f"Disruption engine init error: {e}")
            raise

    # ── Disruption delegation ─────────────────────────────────────

    def start_automatic_workflow(
        self,
        ip: str,
        *,
        common_params: Optional[Dict[str, Any]] = None,
        disrupt_kwargs: Optional[Dict[str, Any]] = None,
        on_event: Optional[Callable[[ChainEvent], None]] = None,
    ) -> int:
        """Start one controller-owned automatic connection test.

        Starting a new run synchronously cancels and releases the previous
        run.  The positive return value is a monotonically increasing
        generation suitable for guarding asynchronous GUI updates; ``0``
        means the target was refused before a worker was started.
        """
        if not self.network_operations_available:
            log_error(
                "Automatic workflow refused while safety controls are unavailable: "
                f"{self._current_network_block_reason()}"
            )
            return 0
        try:
            target_ip = self.safety_policy.validate_target(ip)
        except ValueError as exc:
            log_error(f"Automatic workflow refused: {exc}")
            return 0

        config = build_automatic_connection_test(
            target_ip,
            common_params=common_params,
            disrupt_kwargs=disrupt_kwargs,
        )

        return self._start_owned_cut_chain(config, on_event=on_event)

    def start_cut_chain(
        self,
        config: ChainConfig,
        *,
        on_event: Optional[Callable[[ChainEvent], None]] = None,
    ) -> int:
        """Start one validated user-configured chain under controller safety.

        The supplied object is copied before ownership. The target is checked
        against the current (possibly narrower) configured CIDRs and the
        global chain deadline is capped by ``max_operation_seconds``.
        ``0`` means the request was refused before a worker started.
        """
        if not self.network_operations_available:
            log_error(
                "Cut chain refused while safety controls are unavailable: "
                f"{self._current_network_block_reason()}"
            )
            return 0
        try:
            owned = deepcopy(config)
            owned.target_ip = self.safety_policy.validate_target(
                owned.target_ip
            )
            owned.global_timeout_s = self.safety_policy.bounded_timeout(
                owned.global_timeout_s
            )
            validate_chain_config(owned)
        except (AttributeError, TypeError, ValueError) as exc:
            log_error(f"Cut chain refused: {exc}")
            return 0
        return self._start_owned_cut_chain(owned, on_event=on_event)

    def _start_owned_cut_chain(
        self,
        config: ChainConfig,
        *,
        on_event: Optional[Callable[[ChainEvent], None]],
    ) -> int:
        """Replace the controller-owned chain; caller has validated config."""

        with self._automatic_transition_lock:
            with self._automatic_state_lock:
                previous = self._automatic_runner
            if previous is not None:
                if not self._stop_automatic_workflow_serialized():
                    log_error(
                        "Cut chain refused: previous stage release was not "
                        "confirmed"
                    )
                    return 0
            else:
                # Invalidate callbacks from any already-finished generation.
                self._stop_automatic_workflow_serialized()
            with self._automatic_state_lock:
                self._automatic_generation += 1
                generation = self._automatic_generation

                def _forward_event(event: ChainEvent) -> None:
                    with self._automatic_state_lock:
                        if (
                            generation != self._automatic_generation
                            or self._automatic_runner is not runner
                        ):
                            return
                        if (
                            event.kind in {"complete", "halt", "error"}
                            and runner.release_confirmed
                        ):
                            self._automatic_runner = None
                    if on_event is not None:
                        try:
                            on_event(event)
                        except Exception as exc:
                            log_error(
                                "Automatic workflow callback failed: "
                                f"{exc}"
                            )

                runner = CutChainRunner(
                    config,
                    self,
                    on_event=_forward_event,
                )
                self._automatic_runner = runner
            runner.start()
            return generation

    # Name the product action as well as the generic lifecycle API.  Keeping
    # this tiny alias makes headless callers self-documenting.
    start_automatic_connection_test = start_automatic_workflow

    def stop_automatic_workflow(self) -> bool:
        """Cancel and release the current automatic run, if any."""
        with self._automatic_transition_lock:
            return self._stop_automatic_workflow_serialized()

    def _stop_automatic_workflow_serialized(self) -> bool:
        """Stop helper; caller must hold ``_automatic_transition_lock``."""
        with self._automatic_state_lock:
            runner = self._automatic_runner
        if runner is None:
            with self._automatic_state_lock:
                self._automatic_generation += 1
            # Idempotent cleanup: owning no runner is already a confirmed
            # released state, not a stop failure.
            return True

        if runner.stop() is not True:
            log_error(
                "Automatic workflow stop could not confirm stage release"
            )
            return False
        with self._automatic_state_lock:
            if self._automatic_runner is runner:
                self._automatic_runner = None
            self._automatic_generation += 1
        return True

    def is_automatic_workflow_running(self) -> bool:
        """Return whether a runner thread or unconfirmed stage is owned."""
        with self._automatic_state_lock:
            runner = self._automatic_runner
            return bool(
                runner is not None
                and (runner.running or not runner.release_confirmed)
            )

    def disrupt_device(
        self,
        ip: str,
        methods: Optional[List[str]] = None,
        params: Optional[Dict] = None,
        operation_timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> bool:
        """Start disruption on *ip* with optional methods/params.

        Additional ``**kwargs`` (e.g. ``target_mac``, ``target_hostname``,
        ``target_device_type``) are forwarded to the underlying engine to
        enable auto-detection of the appropriate disruption profile.
        """
        if not self.network_operations_available:
            log_error(
                "Disruption refused while safety controls are unavailable: "
                f"{self._current_network_block_reason()}"
            )
            return False
        chain_runner = kwargs.pop("_cut_chain_runner", None)
        if chain_runner is None:
            # A direct/manual disruption replaces the automatic sequence.
            with self._automatic_state_lock:
                owned_runner = self._automatic_runner
            if (
                owned_runner is not None
                and not self.stop_automatic_workflow()
            ):
                log_error(
                    "Manual disruption refused: previous stage release was "
                    "not confirmed"
                )
                return False
        else:
            # Reject a late stage from a detached/cancelled runner.  The
            # sentinel is controller-internal and never reaches the helper.
            with self._automatic_state_lock:
                if self._automatic_runner is not chain_runner:
                    return False
        try:
            target_ip = self.safety_policy.validate_target(ip)
            timeout = self.safety_policy.bounded_timeout(operation_timeout)
        except ValueError as exc:
            log_error(f"Disruption refused: {exc}")
            return False
        if self.safety_policy.dry_run:
            log_info(
                f"Safety dry-run: would disrupt {mask_ip(target_ip)} "
                f"for at most {timeout:.1f}s"
            )
            self._audit_safety_event("disruption_dry_run", target_ip, timeout)
            return True
        try:
            self._recovery_journal.mark_pending("packet_disruption")
        except Exception as exc:
            log_error(f"Disruption refused: recovery journal unavailable: {exc}")
            return False
        started = self._disruption_manager.disrupt_device(
            target_ip, methods, params, **kwargs
        )
        if started:
            self._arm_operation_deadline(target_ip, timeout)
        else:
            self._maybe_clear_recovery_journal()
        return bool(started)

    def stop_disruption(self, ip: str, **kwargs: Any) -> bool:
        """Stop disruption on *ip*."""
        chain_runner = kwargs.pop("_cut_chain_runner", None)
        if chain_runner is None:
            if self.stop_automatic_workflow() is not True:
                log_error(
                    "Disruption stop refused: automatic workflow release "
                    "was not confirmed"
                )
                return False
        else:
            # A runner that was cancelled/replaced must never release a
            # newer same-target stage after a slow backend call completes.
            with self._automatic_state_lock:
                if self._automatic_runner is not chain_runner:
                    return False
        if self.safety_policy.dry_run:
            self._cancel_operation_deadline(ip)
            return True
        stopped = bool(self._disruption_manager.stop_device(ip))
        if stopped:
            # Retain the safety deadline until the backend has positively
            # acknowledged release.  A False result or exception leaves the
            # owner and its automatic retry path intact.
            self._cancel_operation_deadline(ip)
            self._maybe_clear_recovery_journal()
        else:
            log_error(
                "Disruption stop was not confirmed; safety deadline retained "
                f"for {mask_ip(ip)}"
            )
        return stopped

    def stop_all_disruptions(self) -> bool:
        """Stop all active disruptions."""
        with self._automatic_transition_lock:
            self._stop_automatic_workflow_serialized()
            restored = (
                True
                if self.safety_policy.dry_run
                else self._restore_network_state()
            )
            if restored:
                self._cancel_all_operation_deadlines()
                with self._automatic_state_lock:
                    runner = self._automatic_runner
                if (
                    runner is not None
                    and runner.confirm_external_release()
                ):
                    with self._automatic_state_lock:
                        if self._automatic_runner is runner:
                            self._automatic_runner = None
                            self._automatic_generation += 1
            return restored

    def _restore_network_state_for_shutdown(self) -> None:
        """Require confirmed restoration before releasing shutdown deadlines."""
        if not self.stop_all_disruptions():
            raise RuntimeError("network restoration was not confirmed")

    def _recover_stale_network_state(self) -> None:
        if not self._recovery_journal.is_pending():
            return
        log_info("Stale operation journal found; restoring network state")
        if not self._restore_network_state():
            raise RuntimeError(
                "stale network state could not be fully restored; "
                "operation journal retained"
            )
        # Audit sentinel only; this value is never used to bind a socket.
        self._audit_safety_event(  # nosec B104
            "stale_network_state_restored", "0.0.0.0", 0
        )

    @property
    def network_operations_available(self) -> bool:
        """Whether the controller may begin new network mutations."""
        return self._current_network_block_reason() is None

    def _current_network_block_reason(self) -> Optional[str]:
        return (
            self._network_operations_blocked_reason
            or self._kill_switch_config_error
        )

    def get_startup_health(self) -> Dict[str, Any]:
        """Return a privacy-safe startup status for UI diagnostics."""
        reason = self._current_network_block_reason()
        return {
            "ready": self._started,
            "network_operations_available": reason is None,
            "recovery_blocked": self._network_operations_blocked_reason is not None,
            "kill_switch_blocked": self._kill_switch_config_error is not None,
            "message": reason or "",
        }

    def _restore_network_state(self) -> bool:
        packet_ok = False
        firewall_ok = False
        forwarding_ok = True
        try:
            packet_ok = bool(self._disruption_manager.stop_all_devices())
        except Exception as exc:
            log_error(f"Packet-engine restoration failed: {exc}")
        if not packet_ok:
            log_error("Packet-engine restoration reported incomplete cleanup")
        try:
            firewall_ok = bool(self._clear_firewall_blocks())
        except Exception as exc:
            log_error(f"Firewall restoration failed: {exc}")
        if not firewall_ok:
            log_error("Firewall restoration reported incomplete cleanup")
        original_forwarding = self._recovery_journal.forwarding_original_state()
        if original_forwarding is not None:
            try:
                forwarding_ok = bool(
                    self._restore_ip_forwarding(original_forwarding)
                )
            except Exception as exc:
                forwarding_ok = False
                log_error(f"IP-forwarding restoration failed: {exc}")
            if not forwarding_ok:
                log_error("IP-forwarding restoration reported incomplete cleanup")
        if packet_ok and firewall_ok and forwarding_ok:
            self._recovery_journal.clear()
            return not self._recovery_journal.is_pending()
        failure_reasons = []
        if not packet_ok:
            failure_reasons.append("restore_packet_incomplete")
        if not firewall_ok:
            failure_reasons.append("restore_firewall_incomplete")
        if not forwarding_ok:
            failure_reasons.append("restore_forwarding_incomplete")
        try:
            for reason in failure_reasons:
                self._recovery_journal.mark_pending(reason)
        except Exception as exc:
            log_error(f"Could not preserve recovery journal: {exc}")
        return False

    def _maybe_clear_recovery_journal(self) -> None:
        try:
            packet_active = bool(
                self._disruption_manager.get_disrupted_devices()
            )
            firewall_active = bool(self._get_blocked_ips())
        except Exception:
            return
        if not packet_active and not firewall_active:
            self._recovery_journal.clear()

    def _arm_operation_deadline(self, ip: str, timeout: float) -> None:
        with self._deadline_lock:
            previous = self._deadline_timers.pop(ip, None)
            if previous is not None:
                previous.timer.cancel()
            self._deadline_generation += 1
            generation = self._deadline_generation
            now_monotonic = time.monotonic()
            now_unix = time.time()
            timer = threading.Timer(
                timeout,
                self._expire_operation,
                args=(ip, generation),
            )
            timer.daemon = True
            self._deadline_timers[ip] = _OperationDeadline(
                generation=generation,
                timer=timer,
                expires_monotonic=now_monotonic + timeout,
                expires_unix=now_unix + timeout,
            )
            timer.start()
        self._audit_safety_event("operation_deadline_armed", ip, timeout)

    def _expire_operation(self, ip: str, generation: int) -> None:
        with self._deadline_lock:
            current = self._deadline_timers.get(ip)
            if current is None or current.generation != generation:
                return
        try:
            stopped = bool(self._disruption_manager.stop_device(ip))
        except Exception as exc:
            log_error(f"Safety deadline stop failed for {mask_ip(ip)}: {exc}")
            self._retry_expired_operation(ip, generation)
            return
        if not stopped:
            log_error(
                "Safety deadline stop was not confirmed for "
                f"{mask_ip(ip)}; retry remains armed"
            )
            self._retry_expired_operation(ip, generation)
            return

        with self._deadline_lock:
            current = self._deadline_timers.get(ip)
            if current is None or current.generation != generation:
                return
            current.timer.cancel()
            self._deadline_timers.pop(ip, None)
        log_info(f"Safety deadline expired; stopped {mask_ip(ip)}")
        self._maybe_clear_recovery_journal()
        self._audit_safety_event("operation_deadline_expired", ip, 0)

    def _retry_expired_operation(self, ip: str, generation: int) -> None:
        """Keep an expired deadline owned and retry an unconfirmed release."""
        with self._deadline_lock:
            current = self._deadline_timers.get(ip)
            if current is None or current.generation != generation:
                return
            current.timer.cancel()
            retry = threading.Timer(
                self._DEADLINE_RELEASE_RETRY_SECONDS,
                self._expire_operation,
                args=(ip, generation),
            )
            retry.daemon = True
            self._deadline_timers[ip] = _OperationDeadline(
                generation=generation,
                timer=retry,
                expires_monotonic=current.expires_monotonic,
                expires_unix=current.expires_unix,
            )
            retry.start()

    def _cancel_operation_deadline(self, ip: str) -> None:
        with self._deadline_lock:
            current = self._deadline_timers.pop(ip, None)
        if current is not None:
            current.timer.cancel()

    def _cancel_all_operation_deadlines(self) -> None:
        with self._deadline_lock:
            timers = [item.timer for item in self._deadline_timers.values()]
            self._deadline_timers.clear()
        for timer in timers:
            timer.cancel()

    @staticmethod
    def _audit_safety_event(event: str, ip: str, timeout: float) -> None:
        try:
            from app.logs.audit import audit_event
            audit_event(event, {
                "target": mask_ip(ip),
                "timeout_seconds": round(float(timeout), 3),
            })
        except Exception:
            pass

    def get_disrupted_devices(self) -> List[str]:
        """Return list of currently disrupted IPs."""
        return self._disruption_manager.get_disrupted_devices()

    def mark_cut_outcome(self, persisted: bool, ip: Optional[str] = None) -> int:
        """Label the currently-open cut for the survival trainer.

        ``persisted=False`` → dupe succeeded (hive did not flush).
        ``persisted=True``  → dupe failed (hive flushed normally).
        Returns the number of engines that received the label.
        """
        return self._disruption_manager.mark_cut_outcome(persisted, ip=ip)

    def get_disruption_status(self, ip: str) -> Dict:
        """Return disruption status for *ip*."""
        return self._disruption_manager.get_device_status(ip)

    def get_operation_deadline_status(self, ip: str) -> Dict[str, Any]:
        """Return deadline state for one target without exposing parameters."""
        with self._deadline_lock:
            deadline = self._deadline_timers.get(ip)
        if deadline is None:
            return {
                "automatic_stop_armed": False,
                "deadline_at": None,
                "remaining_seconds": None,
            }
        return {
            "automatic_stop_armed": True,
            "deadline_at": deadline.expires_unix,
            "remaining_seconds": max(
                0,
                int(deadline.expires_monotonic - time.monotonic()),
            ),
        }

    def get_active_operations(self) -> List[Dict[str, Any]]:
        """Return active scope and deadline state without raw parameters."""
        from app.core.scenario_report import fingerprint_params

        now_unix = time.time()
        operations: List[Dict[str, Any]] = []
        for ip in self._disruption_manager.get_disrupted_devices():
            status = self._disruption_manager.get_device_status(ip) or {}
            deadline = self.get_operation_deadline_status(ip)
            started_at = float(status.get("start_time") or 0)
            operations.append({
                "target": mask_ip(ip),
                "methods": sorted({
                    str(method)
                    for method in status.get("methods", [])
                    if method
                }),
                "params_fingerprint": fingerprint_params(
                    status.get("params") or {}
                ),
                "started_at": started_at or None,
                "elapsed_seconds": (
                    max(0, int(now_unix - started_at))
                    if started_at
                    else None
                ),
                "deadline_at": deadline["deadline_at"],
                "remaining_seconds": deadline["remaining_seconds"],
                "automatic_stop_armed": deadline["automatic_stop_armed"],
                "process_running": bool(status.get("process_running", False)),
            })
        return sorted(operations, key=lambda item: item["target"])

    def get_clumsy_status(self) -> Dict:
        """Return overall engine status."""
        return self._disruption_manager.get_status()

    def get_engine_stats(self) -> Dict:
        """Return packet processing stats from all engines."""
        return self._disruption_manager.get_engine_stats()

    def _get_kill_switch_drop_counters(self) -> Dict[str, int]:
        """Extract only the aggregate drop count needed by the trigger."""
        stats = self.get_engine_stats()
        if not isinstance(stats, Mapping):
            raise ValueError("packet engine statistics are unavailable")
        dropped = stats.get("packets_dropped", 0)
        if isinstance(dropped, bool) or not isinstance(dropped, int) or dropped < 0:
            raise ValueError("aggregate packet drop count is invalid")
        # Deliberately exclude ``per_device`` and every other engine field.
        return {"packets_dropped": dropped}

    # ── Device cache ──────────────────────────────────────────────

    _CACHE_FIELDS = ("ip", "mac", "hostname", "vendor", "local", "traffic", "last_seen")
    _CACHE_DEFAULTS: Dict[str, Any] = {
        "ip": "", "mac": "", "hostname": "", "vendor": "",
        "local": False, "traffic": 0, "last_seen": "",
    }

    def _load_device_cache(self) -> None:
        """Populate the device list from last session's cache."""
        try:
            cached = self._device_cache.get_cached_devices()
            if cached:
                self.state.update_devices(cached)
                log_info(f"Loaded {len(cached)} cached devices from previous session")
        except Exception as e:
            log_error(f"Device cache load error: {e}")

    def _save_device_cache(self, devices: list) -> None:
        """Persist discovered devices for next launch."""
        try:
            serializable = [
                d if isinstance(d, dict)
                else {k: getattr(d, k, self._CACHE_DEFAULTS[k]) for k in self._CACHE_FIELDS}
                for d in devices
                if isinstance(d, dict) or hasattr(d, "__dict__")
            ]
            self._device_cache.update_cache(serializable)
        except Exception as e:
            log_error(f"Device cache save error: {e}")

    # ── Device scanning ───────────────────────────────────────────

    def scan_devices(self, quick: bool = True) -> List[Dict]:
        """Scan for devices on the local network.

        Called from a background thread in the GUI, so we call
        ``scan_network()`` synchronously here.
        """
        start_time = time.time()
        try:
            self.state.set_scan_status(True)
            log_info(f"Starting device scan ({'quick' if quick else 'full'})...")

            network_info = device_scan.get_network_info()
            self.state.update_network_info(network_info)

            # Lazy import — EnhancedNetworkScanner is heavy and depends on Qt
            from app.network.enhanced_scanner import EnhancedNetworkScanner
            scanner = EnhancedNetworkScanner()
            devices = scanner.scan_network(quick_scan=quick)

            real_devices = [d for d in devices if self._is_real_device(d)]
            for d in real_devices:
                log_info(f"Found device: {mask_ip(d['ip'])} — {d.get('hostname', 'Unknown')}")

            self.state.update_devices(real_devices)
            self._save_device_cache(real_devices)

            duration = time.time() - start_time
            log_network_scan(len(real_devices), duration)
            return real_devices

        except Exception as e:
            log_error(f"Device scan failed: {e}")
            return []
        finally:
            self.state.set_scan_status(False)

    @staticmethod
    def _is_real_device(d: dict) -> bool:
        """Filter out loopback, multicast, broadcast, and link-local addresses."""
        ip = d.get("ip")
        if not ip or ip == "127.0.0.1":
            return False
        octets = ip.split(".")
        if len(octets) != 4:
            return False
        first, last = int(octets[0]), int(octets[3])
        return not (first >= 224 or last == 255 or (first == 169 and int(octets[1]) == 254))

    def quick_scan_devices(self) -> List[Dict]:
        """Convenience: run a quick scan."""
        return self.scan_devices(quick=True)

    # ── Device management ─────────────────────────────────────────

    def select_device(self, ip: str) -> None:
        """Select a device by IP for subsequent operations."""
        self.state.select_device(ip)

    def get_selected_device(self) -> Optional[Device]:
        """Return the currently selected device."""
        return self.state.get_selected_device()

    def toggle_lag(self, ip: Optional[str] = None) -> bool:
        """Toggle firewall blocking for a device.

        Despite the legacy name ('lag'), this uses netsh firewall
        rules for hard block/unblock, not packet manipulation.
        """
        if not ip:
            return False
        if not self.network_operations_available:
            log_error(
                "Firewall block refused while safety controls are unavailable: "
                f"{self._current_network_block_reason()}"
            )
            return False
        try:
            device = self.state.get_device_by_ip(ip)
            if not device:
                try:
                    self._recovery_journal.mark_pending("firewall_block")
                except Exception as exc:
                    log_error(
                        f"Firewall block refused: recovery journal unavailable: {exc}"
                    )
                    return False
                success = blocker.block_device(ip)
                if not success:
                    self._maybe_clear_recovery_journal()
                return success
            fn = blocker.unblock_device if device.blocked else blocker.block_device
            if not device.blocked:
                try:
                    self._recovery_journal.mark_pending("firewall_block")
                except Exception as exc:
                    log_error(
                        f"Firewall block refused: recovery journal unavailable: {exc}"
                    )
                    return False
            if fn(ip):
                device.blocked = not device.blocked
                if not device.blocked:
                    self._maybe_clear_recovery_journal()
            elif not device.blocked:
                self._maybe_clear_recovery_journal()
            return device.blocked
        except Exception as e:
            log_error(f"Toggle lag failed: {e}")
            return False

    def get_devices(self) -> List[Device]:
        """Return the current device list."""
        return self.state.devices

    def get_blocked_devices(self) -> List[Device]:
        """Return only devices with blocked=True."""
        return [d for d in self.state.devices if d.blocked]

    def get_device_by_ip(self, ip: str) -> Optional[Device]:
        """Look up a device by IP."""
        return self.state.get_device_by_ip(ip)

    def clear_devices(self) -> None:
        """Remove all devices from state."""
        with self.state._lock:
            self.state.devices = []
        self.state.notify_observers("devices_updated", [])

    # ── Auto-scan ─────────────────────────────────────────────────

    def start_auto_scan(self) -> None:
        """Start the background auto-scan loop."""
        with self._scan_lock:
            self.auto_scan_enabled = True
            self.stop_scanning = False
            self._scan_stop_event.clear()
            if not self.scan_thread or not self.scan_thread.is_alive():
                self.scan_thread = threading.Thread(
                    target=self._auto_scan_loop,
                    daemon=True,
                    name="DupeZAutoScan",
                )
                self.scan_thread.start()

    def stop_auto_scan(self, join_timeout: float = 2.0) -> None:
        """Signal the auto-scan loop to stop and wait briefly for exit."""
        self.auto_scan_enabled = False
        self.stop_scanning = True
        self._scan_stop_event.set()
        thread = self.scan_thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=max(0.0, join_timeout))

    def _auto_scan_loop(self) -> None:
        """Background loop that rescans at the configured interval."""
        while not self._scan_stop_event.is_set():
            try:
                if not self.state.scan_in_progress:
                    self.quick_scan_devices()
                interval = max(10, self.state.settings.scan_interval)
                self._scan_stop_event.wait(interval)
            except Exception as e:
                log_error(f"Auto-scan error: {e}")
                self._scan_stop_event.wait(60)

    # ── Network info ──────────────────────────────────────────────

    def get_network_info(self) -> Dict[str, Any]:
        """Return active interfaces and I/O counters."""
        try:
            interfaces = psutil.net_if_addrs()
            active = [
                {"name": name, "ip": addr.address, "netmask": addr.netmask}
                for name, addrs in interfaces.items()
                for addr in addrs
                if addr.family == socket.AF_INET
            ]
            net_io = psutil.net_io_counters()
            return {
                "interfaces": active,
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
            }
        except Exception as e:
            log_error(f"Get network info failed: {e}")
            return {}

    # ── Settings ──────────────────────────────────────────────────

    def update_settings(self, new_settings: AppSettings) -> None:
        """Validate, activate, and persist a complete settings snapshot."""
        candidate_settings = deepcopy(new_settings)
        candidate_settings.kill_switch_process_names = sanitize_process_basenames(
            getattr(candidate_settings, "kill_switch_process_names", [])
        )
        new_kill_switch_config = self._build_kill_switch_config(
            candidate_settings
        )
        new_policy = None
        if not self._safety_policy_injected:
            new_policy = SafetyPolicy.from_settings(candidate_settings)
        with self._lifecycle_lock:
            old_settings = self.state.settings
            old_policy = self.safety_policy
            old_config_error = self._kill_switch_config_error
            if new_policy is not None and new_policy != self.safety_policy:
                if not self.stop_all_disruptions():
                    raise RuntimeError(
                        "settings update refused because active network state "
                        "could not be restored"
                    )

            previous, should_run = self._install_kill_switch(
                new_kill_switch_config
            )
            try:
                self.state.settings = candidate_settings
                if new_policy is not None:
                    self.safety_policy = new_policy
                self._kill_switch_config_error = None
                if self.state.save_settings() is False:
                    raise RuntimeError("settings persistence was not confirmed")
            except Exception:
                self.state.settings = old_settings
                self.safety_policy = old_policy
                self._kill_switch_config_error = old_config_error
                self._restore_kill_switch(previous, should_run)
                raise

    def update_setting(self, key: str, value: Any) -> None:
        """Validate and persist a single setting as a full snapshot."""
        if hasattr(self.state.settings, key):
            new_settings = deepcopy(self.state.settings)
            setattr(new_settings, key, value)
            self.update_settings(new_settings)

    def get_settings(self) -> AppSettings:
        """Return current settings."""
        return self.state.settings

    def is_scanning(self) -> bool:
        """Return whether a scan is in progress."""
        return self.state.scan_in_progress

    def is_blocking(self) -> bool:
        """Return whether any devices are currently blocked."""
        return len(self.get_blocked_devices()) > 0

    # ── Plugin system ─────────────────────────────────────────────

    def _init_plugins(self) -> None:
        """Discover and load all plugins."""
        try:
            self.plugin_loader.discover()
            self.plugin_loader.load_all(self)
            active = self.plugin_loader.get_active_plugins()
            log_info(f"Plugin system initialized: {len(active)} active plugin(s)")
        except Exception as e:
            log_error(f"Plugin system init error: {e}")

    def get_plugin_info(self) -> List[Dict]:
        """Return metadata for all discovered plugins."""
        return self.plugin_loader.get_plugin_info()

    def reload_plugins(self) -> bool:
        """Unload and re-discover plugins without overlapping live instances."""
        try:
            if self.plugin_loader.unload_all() is False:
                log_error(
                    "Plugin reload refused because one or more live plugins "
                    "did not confirm deactivation"
                )
                return False
            self.plugin_loader.discover()
            return self.plugin_loader.load_all(self) is not False
        except Exception as exc:
            log_error(f"Plugin reload failed: {exc}")
            return False

    # ── Shutdown ──────────────────────────────────────────────────

    def shutdown(self) -> bool:
        """Graceful shutdown; return whether every cleanup step succeeded."""
        with self._lifecycle_lock:
            if not self._started:
                self._stop_kill_switch()
                return self.stop_automatic_workflow()
            log_info("Controller shutting down...")
            errors = []
            if self.safety_policy.dry_run:
                steps = [
                    ("automatic kill switch", self._stop_kill_switch),
                    ("automatic workflow", self.stop_automatic_workflow),
                    ("operation deadlines", self._cancel_all_operation_deadlines),
                    ("persistence", self._save_all),
                ]
            else:
                steps = [
                    ("automatic kill switch", self._stop_kill_switch),
                    ("plugins", self.plugin_loader.unload_all),
                    ("auto-scan", self.stop_auto_scan),
                    ("scheduler", self.scheduler.stop),
                    (
                        "network restoration",
                        self._restore_network_state_for_shutdown,
                    ),
                    ("disruption engine", self._stop_engine),
                    ("persistence", self._save_all),
            ]
            for name, stop_fn in steps:
                try:
                    result = stop_fn()
                    if result is False:
                        raise RuntimeError("cleanup was not confirmed")
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                    log_error(f"Shutdown step failed ({name}): {exc}")
            # Retain lifecycle ownership after any failed release so another
            # shutdown/Panic Stop attempt re-runs every cleanup boundary.
            self._started = bool(errors)
            if errors:
                log_error(
                    "Controller shutdown completed with errors: "
                    + "; ".join(errors)
                )
            else:
                log_info("Controller shutdown complete")
            return not errors
