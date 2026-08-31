# app/main.py — DupeZ Entry Point
"""
Launches the DupeZ GUI application with automatic UAC elevation,
splash screen initialization, crash dump handler, and graceful
shutdown coordination.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import traceback
from urllib.parse import urlsplit

from app.core.qt_startup import normalized_qt_argv
from dupez_single_instance import guard_gui_startup

__all__ = ["dump_crash", "main"]


# ── Crash-dump PII scrubber (H5) ─────────────────────────────────────
# Tracebacks contain absolute filesystem paths — under Python these
# routinely include the developer's home directory (``C:\Users\<name>``
# or ``/home/<name>``). When users attach FATAL_CRASH.txt to a bug
# report or post it in Discord, those paths leak the Windows username
# and any directory names off of it. Scrub before writing.

# Patterns redact the user component while keeping the traceback
# structurally useful (file name, line number, code snippet all remain).
_PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # C:\Users\<name>\...   →   C:\Users\<REDACTED>\...
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    # /Users/<name>/...     →   /Users/<REDACTED>/...
    (re.compile(r"(/Users/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
    # /home/<name>/...      →   /home/<REDACTED>/...
    (re.compile(r"(/home/)[^/\"'<>|\r\n]+"), r"\1<REDACTED>"),
)

_BEARER_SECRET_RE = re.compile(
    r"(?i)\b(?P<scheme>bearer|basic)\s+"
    r"(?P<secret>[A-Za-z0-9._~+/=-]{8,})"
)
_LABELED_SECRET_RE = re.compile(
    r"(?ix)"
    r"(?P<label>\b(?:api[_-]?key|password|passwd|secret|token|credential|"
    r"private[_-]?key|auth)\b\s*[:=]\s*)"
    r"(?:"
    r"(?P<quote>[\"'])(?P<quoted>[^\r\n]*?)(?P=quote)"
    r"|(?P<plain>[^\s,;}\]\r\n]+)"
    r")"
)
_STANDALONE_SECRET_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}\b"
    ),
)
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _redact_labeled_secret(match: re.Match[str]) -> str:
    quote = match.group("quote") or ""
    return f"{match.group('label')}{quote}[REDACTED]{quote}"


def _redact_crash_url(match: re.Match[str]) -> str:
    token = match.group(0)
    # Traceback prose commonly follows a URL with sentence punctuation. Keep
    # that punctuation outside the parsed URL so the report remains readable.
    core = token.rstrip("),.;]")
    suffix = token[len(core):]
    try:
        parsed = urlsplit(core)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme}://{host}{port}/[REDACTED]{suffix}"
    except (TypeError, ValueError):
        return f"[REDACTED URL]{suffix}"


def _scrub_traceback(text: str) -> str:
    """Redact private values from traceback output.

    Keeps file basenames, line numbers and code context so the dump is
    still useful for post-mortem analysis. Redaction is layered so a failure
    to import one optional runtime component never restores raw output.
    """
    try:
        from app.core.secrets_manager import scrub_message

        text = scrub_message(text)
    except Exception:
        pass
    for pat, repl in _PII_PATTERNS:
        text = pat.sub(repl, text)
    try:
        from app.core.secret_store import _redact_local_paths

        text = _redact_local_paths(text)
    except Exception:
        pass
    # Remove URL credentials/path/query material before field-shaped secret
    # matching can introduce redaction markers inside the URL token.
    text = _URL_IN_TEXT_RE.sub(_redact_crash_url, text)
    text = _BEARER_SECRET_RE.sub(
        lambda match: f"{match.group('scheme')} [REDACTED]",
        text,
    )
    text = _LABELED_SECRET_RE.sub(_redact_labeled_secret, text)
    for pattern in _STANDALONE_SECRET_RES:
        text = pattern.sub("[REDACTED]", text)
    try:
        from app.utils.helpers import mask_ips_in_text, mask_macs_in_text

        text = mask_ips_in_text(text)
        text = mask_macs_in_text(text)
    except Exception:
        pass
    return text


def _get_pythonw() -> str:
    """Return path to pythonw.exe (no-console) next to current interpreter."""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    d = os.path.dirname(os.path.abspath(sys.executable))
    pythonw = os.path.join(d, "pythonw.exe")
    return pythonw if os.path.isfile(pythonw) else os.path.abspath(sys.executable)


def _self_elevation_command() -> tuple[str, str, str]:
    """Return a pinned executable, CRT-safe parameters, and trusted CWD.

    ``ShellExecuteW`` accepts a single parameter string rather than an argv
    array.  Hand-written quoting is not equivalent to Windows' CRT parsing
    rules (notably for embedded quotes and backslashes before a quote), so use
    the same serializer as :mod:`subprocess`.  Source launches always select
    this module explicitly; user arguments can never replace the entry point.
    """
    executable = os.path.abspath(_get_pythonw())
    if not os.path.isfile(executable):
        raise OSError("self-elevation executable is unavailable")

    passthrough = list(sys.argv[1:])
    if any(not isinstance(arg, str) or "\x00" in arg for arg in passthrough):
        raise ValueError("self-elevation arguments contain an invalid value")
    launch_argv = (
        passthrough
        if getattr(sys, "frozen", False)
        else ["-m", "app.main", *passthrough]
    )
    parameters = subprocess.list2cmdline(launch_argv)
    working_dir = (
        os.path.dirname(executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return executable, parameters, working_dir


def dump_crash(exctype, value, tb) -> None:
    """Write unhandled exception to FATAL_CRASH.txt for post-mortem.

    The same scrubbed traceback is written to disk and stderr. Sending the raw
    exception back through ``sys.__excepthook__`` would undo the disk privacy
    boundary in captured console logs and CI artifacts.
    """
    try:
        try:
            from app.core.app_paths import crashes_dir

            crash_dir = str(crashes_dir())
            os.makedirs(crash_dir, exist_ok=True)
        except Exception:
            crash_dir = os.getcwd()
        crash_file = os.path.join(crash_dir, "FATAL_CRASH.txt")
        raw = "".join(traceback.format_exception(exctype, value, tb))
        scrubbed = _scrub_traceback(raw)
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write(scrubbed)
    except Exception:
        scrubbed = "Unhandled exception (crash report unavailable)\n"
    try:
        sys.stderr.write(scrubbed)
        if scrubbed and not scrubbed.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()
    except Exception:
        pass


sys.excepthook = dump_crash

# Windows UAC drops CWD to System32 — force it back to exe directory
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

# ── Startup hardening (H6) ───────────────────────────────────────────
# Call SetDefaultDllDirectories BEFORE any import that triggers a
# LoadLibrary: PyQt6 pulls Chromium, Chromium loads ~60 .dlls, and a
# single attacker-controlled CWD resolution there is a sideload win.
# Keep this block above every third-party import.
_FROZEN_WINDOWS_RELEASE = (
    sys.platform == "win32" and bool(getattr(sys, "frozen", False))
)
try:
    from app.core.self_integrity import (
        enforce_startup_hardening as _apply_hardening,
    )
    _apply_hardening()
except Exception:
    if _FROZEN_WINDOWS_RELEASE:
        raise RuntimeError(
            "Required Windows DLL search hardening could not be applied; "
            "refusing startup."
        ) from None
    # Source and non-Windows development remain best-effort.

# ── QtWebEngine sandbox gating (H6) ──────────────────────────────────
# Chromium refuses to render under Administrator (High-IL) without
# disabling its inner sandbox — mandatory for the Compat variant and
# the legacy in-proc path. Under split mode the GUI is Medium-IL and
# the Chromium sandbox MUST stay enabled; disabling it pointlessly
# reduces the defense-in-depth around iZurvive's embedded map context.
def _should_disable_qt_sandbox() -> bool:
    # Split mode never elevates the GUI → keep Chromium sandbox on. Resolve
    # the compiled build default as well as the environment override: the GPU
    # executable normally has no DUPEZ_ARCH variable because "split" is baked
    # into _build_default.py.
    try:
        from app.firewall_helper.feature_flag import is_split_mode
        if is_split_mode():
            return False
    except Exception:
        arch = os.environ.get("DUPEZ_ARCH", "").strip().lower()
        if arch == "split":
            return False
        # If architecture resolution itself is broken, preserve the sandbox.
        # Compat builds resolve positively to inproc through feature_flag.
        return arch == "inproc"
    # In-proc / Compat path runs High-IL → Chromium requires sandbox off.
    return True


_disable_qt_sandbox = _should_disable_qt_sandbox()
try:
    from app.gui.map_host.renderer_tier import apply_chromium_sandbox_policy

    apply_chromium_sandbox_policy(disable=_disable_qt_sandbox)
except Exception:
    if _disable_qt_sandbox:
        os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    else:
        # Fail closed if the policy module is unavailable: clear both known
        # QtWebEngine sandbox bypass channels, even at the cost of GPU flags.
        os.environ.pop("QTWEBENGINE_DISABLE_SANDBOX", None)
        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)

from PyQt6.QtGui import QIcon
from PyQt6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QThreadPool,
    QTimer,
    Qt,
)
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.core.resource_profile import detect_startup_resource_profile
from app.core.updater import CURRENT_VERSION
from app.logs.logger import log_error, log_info, log_shutdown, log_startup, log_warning
from app.utils.helpers import is_admin

IS_ADMIN: bool = is_admin()


def _authorize_inproc_startup(*, split_mode: bool) -> bool:
    """Authorize whole-GUI High-IL mode before engine initialization."""

    if split_mode:
        return True
    try:
        from app.firewall_helper.elevation import enforce_second_factor

        enforce_second_factor(boundary="inproc_startup")
        return True
    except Exception:
        log_warning("Privileged startup refused because authorization failed")
        QMessageBox.critical(
            None,
            "Authorization Required",
            "DupeZ could not authorize privileged firewall startup. "
            "No network engine was initialized.",
        )
        return False


def main() -> None:
    # --- Phase 1: UAC Elevation ---
    # ADR-0001 split mode: the GUI process MUST stay at Medium IL so the
    # embedded Chromium map can initialize its GPU sandbox. WinDivert ops
    # are proxied through dupez_helper.py which runs separately at High
    # IL (see app/firewall_helper/elevation.py). Under split mode we do
    # NOT self-elevate here — doing so kills the GPU path and, worse,
    # creates a UAC cascade when the already-elevated GUI then tries to
    # spawn its own helper via runas. Inproc mode (the legacy code path
    # and the DupeZ-Compat.exe variant) still self-elevates as before.
    try:
        from app.firewall_helper.feature_flag import is_split_mode
        _split = is_split_mode()
    except Exception:
        if _FROZEN_WINDOWS_RELEASE:
            log_error("Frozen architecture policy is unavailable; refusing startup")
            return
        _split = (os.environ.get("DUPEZ_ARCH", "").strip().lower() == "split")

    try:
        if not IS_ADMIN and not _split:
            log_warning("Not running as admin — auto-elevating via UAC...")
            exe, arguments, working_dir = _self_elevation_command()
            shell_execute = ctypes.windll.shell32.ShellExecuteW
            try:
                shell_execute.restype = ctypes.c_void_p
            except (AttributeError, TypeError):
                pass
            result = shell_execute(
                None, "runas", exe, arguments, working_dir, 1,
            )
            if not result or int(result) <= 32:
                log_error(f"UAC elevation failed with code: {result}")
                ctypes.windll.user32.MessageBoxW(
                    0, "Failed to elevate. Run as Administrator.",
                    "Admin Required", 0x10,
                )
            sys.exit(0)
        if _split and not IS_ADMIN:
            log_info("split mode: running GUI at Medium IL; helper "
                     "will elevate during controller startup")
    except SystemExit:
        raise
    except Exception as e:
        log_error(f"Error during auto-elevation: {e}")
        ctypes.windll.user32.MessageBoxW(
            0, "Failed to elevate. Run as Administrator.",
            "Admin Warning", 0x10,
        )
        sys.exit(1)

    # The root launcher acquires this before importing app.main. Keep the
    # direct ``python -m app.main`` path protected too; the guard is
    # process-idempotent, so this is a no-op during normal launches.
    if not guard_gui_startup():
        return

    # --- Phase 1b: Log GPU/renderer tier ---
    _tier = os.environ.get("DUPEZ_MAP_RENDERER_TIER", "tier3_cpu")
    try:
        from app.firewall_helper.feature_flag import get_arch
        _arch = get_arch()
    except Exception:
        _arch = os.environ.get("DUPEZ_ARCH", "unknown")
    log_info(f"Renderer tier: {_tier} | Architecture: {_arch} | Admin: {IS_ADMIN}")
    if _tier == "tier3_cpu" and not IS_ADMIN:
        log_warning(
            "Running CPU-raster map. If you have a GPU, ensure you are "
            "using DupeZ-GPU.exe (split mode) for hardware-accelerated map."
        )

    # --- Phase 2: QApplication + Splash Screen ---
    try:
        # QtWebEngine REQUIRES this attribute to be set on the
        # QCoreApplication BEFORE the QApplication instance is
        # constructed. Without it, Chromium prints a warning at
        # startup and some contexts (embedded iZurvive map) can
        # render with corrupted textures on multi-GPU machines.
        # This MUST come before QApplication construction below.
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

        app = QApplication(normalized_qt_argv())

        # Bound Qt's global worker pool before any subsystem can enqueue work.
        # This reduces stack, scheduler, and memory pressure on constrained PCs.
        resource_profile = detect_startup_resource_profile()
        qt_pool = QThreadPool.globalInstance()
        qt_pool.setMaxThreadCount(resource_profile.qt_max_threads)
        qt_pool.setExpiryTimeout(
            resource_profile.qt_expiry_timeout_ms
        )
        log_info(
            f"Startup resource profile: {resource_profile.summary()}"
        )

        # Set app icon
        for icon_path in [
            "app/resources/dupez.ico",
            "app/resources/dupez.png",
            "app/assets/icon.ico",
        ]:
            if os.path.exists(icon_path):
                app.setWindowIcon(QIcon(icon_path))
                break

        # Require a versioned acknowledgement before initializing any active
        # network components. The state contains no device or account data.
        from app.core.operator_acknowledgement import (
            is_acknowledged,
            record_acknowledgement,
        )
        if not is_acknowledged():
            from app.gui.operator_ack_dialog import (
                OperatorAcknowledgementDialog,
            )
            acknowledgement = OperatorAcknowledgementDialog()
            if acknowledgement.exec() != acknowledgement.DialogCode.Accepted:
                log_info("Startup cancelled at authorized-use acknowledgement")
                return
            record_acknowledgement()
            log_info("Authorized-use policy acknowledged")

        # Compat/in-process mode runs the entire GUI at High IL. Enforce the
        # same factor as the split helper inside this privileged process before
        # the splash pipeline can import or initialize the firewall engine.
        if not _authorize_inproc_startup(split_mode=_split):
            return

        # --- Show splash screen and run init pipeline ---
        from app.gui.splash import DupeZSplash

        splash = DupeZSplash()
        splash.show()
        app.processEvents()

        # Keep controller initialization ahead of Chromium construction. A
        # native WebEngine/GPU failure must never hide recovery or helper
        # startup failures.
        startup_loop = QEventLoop()
        startup_watchdog = QTimer(splash)
        startup_watchdog.setSingleShot(True)
        startup_state = {"ready": False, "timed_out": False}

        def _on_splash_complete() -> None:
            startup_state["ready"] = True
            startup_watchdog.stop()
            if startup_loop.isRunning():
                startup_loop.quit()

        def _on_startup_timeout() -> None:
            if startup_state["ready"]:
                return
            startup_state["timed_out"] = True
            if startup_loop.isRunning():
                startup_loop.quit()

        startup_watchdog.timeout.connect(_on_startup_timeout)
        splash.run_init_pipeline(on_complete=_on_splash_complete)
        startup_watchdog.start(resource_profile.startup_timeout_ms)

        if not startup_state["ready"]:
            startup_loop.exec()

        controller = splash.controller
        init_error = splash.init_error

        if startup_state["timed_out"]:
            # Stop progression between initialization phases and briefly allow
            # the daemon worker to observe cancellation. A currently blocked
            # native call cannot be force-killed safely from the GUI thread.
            try:
                splash.cancel_init_pipeline()
                splash.wait_for_init_pipeline(1.0)
            except Exception as cancel_exc:
                log_warning(
                    "Splash cancellation failed after timeout "
                    f"(non-fatal): {cancel_exc}"
                )

            # Refresh after the bounded cancellation wait because controller
            # construction may have completed while the timeout was handled.
            controller = splash.controller

            if controller is not None:
                try:
                    controller.shutdown()
                except Exception as shutdown_exc:
                    log_warning(
                        "Controller cleanup failed after startup timeout "
                        f"(non-fatal): {shutdown_exc}"
                    )

            splash.close()
            splash.deleteLater()

            log_error(
                "Startup initialization timed out after "
                f"{resource_profile.startup_timeout_ms} ms"
            )
            QMessageBox.critical(
                None,
                "Initialization Timed Out",
                "DupeZ initialization exceeded its safe startup deadline. "
                "Network and controller cleanup was requested. Restart DupeZ "
                "and review the diagnostic logs. On a constrained PC, set "
                "DUPEZ_LOW_RESOURCE=1 before launching.",
            )
            sys.exit(1)

        splash.close()
        splash.deleteLater()

        if controller is None:
            detail = init_error or "Controller failed to initialize"
            log_dir = os.path.join(
                os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                "DupeZ",
                "logs",
            )
            QMessageBox.critical(
                None,
                "Initialization Failed",
                f"DupeZ could not start:\n{detail}\n\n"
                f"Diagnostic logs: {log_dir}",
            )
            sys.exit(1)

        startup_health = (
            controller.get_startup_health()
            if controller is not None
            and hasattr(controller, "get_startup_health")
            else {}
        )
        if startup_health.get("recovery_blocked"):
            QMessageBox.warning(
                None,
                "Network Recovery Required",
                "DupeZ opened in safe mode because a previous network "
                "operation could not be fully restored.\n\n"
                "Disruption and firewall controls are disabled for this "
                "session. Close other DupeZ processes, then restart the "
                "app. If this persists, review the durable DupeZ logs.\n\n"
                f"Details: {startup_health.get('message', 'unknown error')}",
            )

        def _install_lazy_map(reason: str) -> None:
            """Register a lightweight retryable map placeholder."""
            try:
                from app.gui.dayz_map_gui_new import set_prewarmed_map_gui
                from app.gui.lazy_dayz_map import LazyDayZMapGUI

                lazy_map = LazyDayZMapGUI()
                lazy_map.hide()
                set_prewarmed_map_gui(lazy_map)
                log_info(f"Map: deferred until first tab open ({reason})")
            except Exception as lazy_exc:
                # Dashboard retains its normal cold-construction fallback.
                log_warning(
                    f"Map lazy registration failed (non-fatal): {lazy_exc}"
                )

        # Construct Chromium only after controller recovery is known-good.
        # Capable systems retain prewarming; constrained systems defer the
        # QWebEngineView and Chromium renderer until the Map tab is opened.
        if resource_profile.prewarm_map:
            try:
                from app.gui.dayz_map_gui_new import (
                    DayZMapGUI,
                    set_prewarmed_map_gui,
                )

                _prewarmed_map = DayZMapGUI()
                _prewarmed_map.hide()
                set_prewarmed_map_gui(_prewarmed_map)
                app.processEvents()
                log_info(
                    "Map: prewarmed DayZMapGUI after controller startup"
                )
            except Exception as prewarm_exc:
                log_warning(
                    f"Map prewarm failed (non-fatal): {prewarm_exc}"
                )
                _install_lazy_map("prewarm failure")
        else:
            _install_lazy_map("startup resource profile")

        # --- Phase 3: Main Window ---
        from app.gui.dashboard import DupeZDashboard
        from app.gui.hotkey import HotkeyListener

        window = DupeZDashboard(controller=controller)

        hotkey = HotkeyListener(callback=controller.toggle_lag)
        hotkey.start()

        window.show()
        log_info("DupeZ started successfully")

        # --- Phase 4: Background Services ---
        try:
            from app.core.patch_monitor import start_background_monitoring
            start_background_monitoring()
            log_info("Patch monitor started")
        except Exception as e:
            log_warning(f"Patch monitor failed to start (non-fatal): {e}")

        # --- Phase 4b: v5.7.4 startup maintenance + service wiring ---
        # The v5.7.0/v5.7.1 feature backends (episode rotation, audit
        # webhook sinks, OBS overlay) were shipped without an invocation
        # point. This block wires them in. Each step is independently
        # guarded — a failure in one does not block the others or the app.
        try:
            # Episode-store rotation: enforce the 90-day / 5000-file
            # retention policy once per launch so the JSONL store does
            # not grow unbounded.
            from app.ai.episode_recorder import rotate_episodes
            removed = rotate_episodes()
            if removed:
                log_info(f"Episode rotation: pruned {removed} stale file(s)")
        except Exception as e:
            log_warning(f"Episode rotation failed (non-fatal): {e}")

        try:
            # Audit webhook sinks: register any sink the operator
            # configured so audit_event fan-out has a destination.  The URL
            # is a bearer credential and is resolved only from the OS-backed
            # secret store; legacy plaintext settings are migrated before a
            # sink can be registered.
            from app.core.data_persistence import settings_manager
            from app.core.audit_webhook_config import resolve_audit_webhook

            _wh = resolve_audit_webhook(manager=settings_manager)
            if _wh is not None:
                from app.core.audit_webhook import (
                    DiscordWebhookSink, GenericWebhookSink, register_sink,
                )
                kind = _wh.kind
                sink_cls = (DiscordWebhookSink if kind == "discord"
                            else GenericWebhookSink)
                register_sink(sink_cls(
                    _wh.url,
                    rate_limit_per_min=_wh.rate_limit_per_min,
                ))
                log_info(f"Audit webhook sink registered ({kind})")
        except Exception as e:
            log_warning(f"Audit webhook setup failed (non-fatal): {e}")

        try:
            # OBS overlay HTTP server: auto-start when enabled in
            # settings. The Tools menu also exposes a manual toggle.
            from app.core.data_persistence import settings_manager
            if settings_manager.get_setting("obs_overlay_enabled", False):
                overlay_owner = window.overlay_server_owner
                if overlay_owner.start():
                    log_info(
                        f"OBS overlay server started at "
                        f"{overlay_owner.base_url}/overlay.html"
                    )
                else:
                    retained = (
                        " Cleanup ownership was retained for shutdown."
                        if overlay_owner.owned
                        else ""
                    )
                    log_warning(
                        "OBS overlay autostart failed — overlay is not "
                        f"running this session (check port 4778).{retained}"
                    )
        except Exception as e:
            log_warning(f"OBS overlay autostart failed (non-fatal): {e}")

        shutdown_state = {"done": False}

        def _shutdown_cleanup() -> None:
            if shutdown_state["done"]:
                return
            shutdown_state["done"] = True

            try:
                hotkey.stop()
            except Exception as exc:
                log_warning(
                    f"Hotkey shutdown failed (non-fatal): {exc}"
                )

            try:
                from app.core.patch_monitor import stop_background_monitoring

                stop_background_monitoring()
                log_info("Patch monitor stopped")
            except Exception:
                pass

            try:
                overlay_owner = getattr(
                    window,
                    "overlay_server_owner",
                    None,
                )
                if overlay_owner is not None and overlay_owner.owned:
                    if overlay_owner.stop():
                        log_info("OBS overlay server stopped")
                    else:
                        log_error(
                            "OBS overlay shutdown was not confirmed; "
                            "ownership retained until process exit"
                        )
            except Exception as exc:
                log_error(f"OBS overlay shutdown failed: {exc}")

            try:
                if controller.shutdown() is False:
                    log_error("Controller shutdown was not confirmed")
            except Exception as exc:
                log_error(f"Controller shutdown failed: {exc}")

            try:
                qt_pool.clear()
                if not qt_pool.waitForDone(3_000):
                    log_warning(
                        "Qt worker pool did not fully drain before exit"
                    )
            except Exception as exc:
                log_warning(
                    "Qt worker-pool shutdown failed "
                    f"(non-fatal): {exc}"
                )

            log_shutdown()

        app.aboutToQuit.connect(_shutdown_cleanup)
        sys.exit(app.exec())

    except SystemExit:
        raise
    except Exception as e:
        log_error(f"Unhandled exception in main: {e}")
        try:
            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None,
                    "Critical Error",
                    f"An error occurred:\n{e}",
                )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
