#!/usr/bin/env python
# dupez_helper.py
"""
DupeZ elevated firewall helper entry point (ADR-0001).

This is the executable that runs at High IL (elevated) under the
`DUPEZ_ARCH=split` architecture. It owns the WinDivert handle and the
entire `app.firewall` module chain, exposing a control-plane IPC over
a named pipe for the unelevated GUI process to drive.

Launch contract:
    dupez_helper.py --role helper [--pipe \\\\.\\pipe\\dupez_firewall_helper]

The helper imports and starts the real disruption manager, authenticates
the control pipe, watches the exact parent process identity, and performs
packet/firewall cleanup before exit. A Windows Job object remains the
preferred future hard binding.

Critical invariant:
    When this process is running, it IS the firewall. The GUI process
    has no WinDivert handle. All packet work happens in this process's
    thread pool, bit-for-bit identical to `inproc` mode. The split is
    control-plane only.
"""

from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
import time

def _force_helper_inproc_arch() -> None:
    """Keep every helper-owned firewall call inside this process.

    Merely deleting ``DUPEZ_ARCH`` is not sufficient in a frozen DupeZ-GPU
    build: that executable has ``_BUILD_DEFAULT_ARCH = "split"`` compiled
    into it, so feature_flag.get_arch() falls straight back to split mode.
    An explicit environment override wins over both the inherited GUI setting
    and the compiled default.
    """
    os.environ["DUPEZ_ARCH"] = "inproc"


# The frozen launcher imports this module only after recognizing
# ``--role helper``. Force the override immediately in that path, before any
# app module can be imported. A plain library import (for unit tests and
# tooling) is intentionally side-effect free.
if "--role" in sys.argv:
    try:
        _role_index = sys.argv.index("--role")
        if sys.argv[_role_index + 1] == "helper":
            _force_helper_inproc_arch()
    except (ValueError, IndexError):
        pass

# Ensure we can import app.* when launched as a script from the repo root.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _configure_logging() -> None:
    # In a one-file PyInstaller build _REPO_ROOT is the ephemeral _MEI
    # extraction directory. Persist helper diagnostics beside the GUI logs so
    # they survive helper exit and can explain elevation/IPC failures.
    log_path = _helper_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            RotatingFileHandler(
                log_path,
                maxBytes=2 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def _helper_log_path() -> str:
    """Return a durable helper log path outside PyInstaller's _MEI tree."""
    state_root = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_STATE_HOME")
        or os.path.expanduser("~")
    )
    return os.path.join(
        state_root,
        "DupeZ",
        "logs",
        "firewall_helper.log",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DupeZ elevated firewall helper (ADR-0001)",
    )
    parser.add_argument(
        "--role",
        choices=["helper"],
        required=True,
        help="Execution role. Only 'helper' is supported.",
    )
    parser.add_argument(
        "--pipe",
        default=None,
        help="Override the named-pipe path. Defaults to the standard path.",
    )
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=None,
        help="Parent GUI process PID. Helper exits if parent dies. "
             "(Day 4 will replace this with a Job object for hard binding.)",
    )
    return parser.parse_args()


def _parent_watcher(
    parent_pid: int,
    shutdown_event,
    expected_create_time: float | None = None,
) -> None:
    """Poll for the parent process and request shutdown if it disappears.

    This is the Day 1 interim — Day 4 replaces this with a proper Windows
    Job object so termination is atomic and can't be bypassed.
    """
    import psutil
    log = logging.getLogger("parent-watcher")
    log.info("watching parent pid=%d", parent_pid)
    while not shutdown_event.is_set():
        try:
            process = psutil.Process(parent_pid)
            same_process = (
                expected_create_time is None
                or abs(process.create_time() - expected_create_time) < 0.001
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            same_process = False
        if not same_process:
            log.warning("parent pid=%d gone, initiating shutdown", parent_pid)
            shutdown_event.set()
            return
        time.sleep(1.0)


def main() -> int:
    # Also cover direct calls to main() and ``python dupez_helper.py``.
    _force_helper_inproc_arch()
    _configure_logging()
    log = logging.getLogger("dupez-helper")

    args = _parse_args()

    # If we were launched via Task Scheduler (B2b), the parent PID can't
    # be passed as a command-line argument — the task definition is
    # static. Fall back to the sentinel file written by launch_helper_via_task.
    if args.parent_pid is None:
        sentinel = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "DupeZ", "helper_parent_pid.txt",
        )
        try:
            if os.path.exists(sentinel):
                with open(sentinel, "r", encoding="utf-8") as f:
                    args.parent_pid = int(f.read().strip())
        except Exception:
            pass

    log.info("dupez_helper starting: role=%s pipe=%s parent_pid=%s",
             args.role, args.pipe or "<default>", args.parent_pid)

    # Import the real disruption_manager — same singleton as inproc mode.
    # This pulls in WinDivert via native_divert_engine's lazy import chain.
    try:
        from app.firewall.clumsy_network_disruptor import disruption_manager
    except Exception as e:
        log.exception("failed to import disruption_manager: %s", e)
        return 2

    # Initialize and start the engine in-process inside THIS helper.
    # `DUPEZ_HELPER_ALLOW_DEGRADED=1` lets the helper boot even when
    # initialize() fails — used ONLY for dev-box latency benchmarking
    # on a non-admin shell. Packet ops will return ERR_NOT_READY.
    degraded_ok = os.environ.get("DUPEZ_HELPER_ALLOW_DEGRADED") == "1"
    degraded = False
    if not disruption_manager.initialize():
        if not degraded_ok:
            log.error("disruption_manager.initialize() returned False")
            return 3
        log.warning("initialize() failed — continuing in DEGRADED mode "
                    "(DUPEZ_HELPER_ALLOW_DEGRADED=1)")
        degraded = True
    if not degraded:
        # start() returns None on the real DM (void contract).
        try:
            disruption_manager.start()
        except Exception as e:
            if not degraded_ok:
                log.exception("disruption_manager.start() raised: %s", e)
                return 4
            log.warning("start() raised in degraded mode: %s", e)
            degraded = True
    log.info("disruption engine running in helper process (degraded=%s)", degraded)

    # Import blocker module so the helper can service netsh ops.
    # blocker.py routes back to the real functions because is_split_mode()
    # is False inside the helper (the helper process does not set
    # DUPEZ_ARCH=split on itself).
    try:
        from app.firewall import blocker as blocker_module
    except Exception as e:
        log.warning("blocker module import failed: %s", e)
        blocker_module = None

    # Start the pipe server.
    from app.firewall_helper.server import run_helper_server
    dispatcher = run_helper_server(disruption_manager, blocker_module=blocker_module)

    # Optional parent-watcher thread.
    if args.parent_pid is not None:
        import threading
        try:
            import psutil
            parent_create_time = psutil.Process(args.parent_pid).create_time()
        except Exception:
            parent_create_time = None
        t = threading.Thread(
            target=_parent_watcher,
            args=(
                args.parent_pid,
                dispatcher.shutdown_event,
                parent_create_time,
            ),
            name="parent-watcher",
            daemon=True,
        )
        t.start()

    # Graceful signal handling.
    def _sig_handler(signum, _frame):
        log.info("received signal %d, shutting down", signum)
        dispatcher.shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _sig_handler)
        except Exception:
            pass  # SIGTERM may not be supported on Windows depending on env

    # Block until shutdown is requested.
    try:
        while not dispatcher.shutdown_event.wait(timeout=0.5):
            pass
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt, shutting down")

    log.info("restoring helper-owned network state")
    try:
        disruption_manager.stop_all_devices()
    except Exception as e:
        log.error("error stopping active devices: %s", e)
    if blocker_module is not None:
        try:
            blocker_module.clear_all_dupez_blocks()
        except Exception as e:
            log.error("error clearing firewall blocks: %s", e)

    log.info("stopping disruption engine")
    try:
        disruption_manager.stop()
    except Exception as e:
        log.error("error stopping disruption_manager: %s", e)

    log.info("dupez_helper exit 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
