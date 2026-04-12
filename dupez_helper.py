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

Day 1 status: this is a scaffold. It imports and starts the real
disruption_manager singleton (same module the inproc path uses), then
runs the pipe server and waits for shutdown. Day 2 will harden the
crash-safe lifecycle and Day 4 will add Job object self-registration so
the helper dies if the parent GUI dies.

Critical invariant:
    When this process is running, it IS the firewall. The GUI process
    has no WinDivert handle. All packet work happens in this process's
    thread pool, bit-for-bit identical to `inproc` mode. The split is
    control-plane only.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

# CRITICAL: unset DUPEZ_ARCH inside the helper process BEFORE any app
# imports. The helper always runs the real in-process engine; if we
# inherited DUPEZ_ARCH=split from the parent GUI, blocker.py's feature-
# flag route would try to proxy back to ourselves, creating an infinite
# loop. Scrub the variable early.
os.environ.pop("DUPEZ_ARCH", None)

# Ensure we can import app.* when launched as a script from the repo root.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _configure_logging() -> None:
    log_dir = os.path.join(_REPO_ROOT, "app", "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(
                os.path.join(log_dir, "firewall_helper.log"),
                encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
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


def _parent_watcher(parent_pid: int, shutdown_event) -> None:
    """Poll for the parent process and request shutdown if it disappears.

    This is the Day 1 interim — Day 4 replaces this with a proper Windows
    Job object so termination is atomic and can't be bypassed.
    """
    import psutil
    log = logging.getLogger("parent-watcher")
    log.info("watching parent pid=%d", parent_pid)
    while not shutdown_event.is_set():
        if not psutil.pid_exists(parent_pid):
            log.warning("parent pid=%d gone, initiating shutdown", parent_pid)
            shutdown_event.set()
            return
        time.sleep(1.0)


def main() -> int:
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
        t = threading.Thread(
            target=_parent_watcher,
            args=(args.parent_pid, dispatcher.shutdown_event),
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

    log.info("stopping disruption engine")
    try:
        disruption_manager.stop()
    except Exception as e:
        log.error("error stopping disruption_manager: %s", e)

    log.info("dupez_helper exit 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
