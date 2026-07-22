#!/usr/bin/env python
# dupez_helper.py
"""
DupeZ elevated firewall helper entry point (ADR-0001).

This executable runs at High IL under the ``DUPEZ_ARCH=split`` architecture.
It owns WinDivert and the direct Clumsy child-process lifecycle, exposing only
small authenticated control messages over the named pipe. Packet bodies never
cross the IPC boundary.
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
    """Keep every helper-owned firewall call inside this process."""

    os.environ["DUPEZ_ARCH"] = "inproc"


# The frozen launcher imports this module only after recognizing helper role.
if "--role" in sys.argv:
    try:
        role_index = sys.argv.index("--role")
        if sys.argv[role_index + 1] == "helper":
            _force_helper_inproc_arch()
    except (ValueError, IndexError):
        pass

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


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


def _configure_logging() -> None:
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
        help=(
            "Parent GUI process PID. Helper exits if that exact process dies."
        ),
    )
    return parser.parse_args()


def _parent_watcher(
    parent_pid: int,
    shutdown_event,
    expected_create_time: float | None = None,
) -> None:
    """Request shutdown if the exact parent process disappears."""

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
            log.warning(
                "parent pid=%d gone, initiating shutdown",
                parent_pid,
            )
            shutdown_event.set()
            return
        time.sleep(1.0)


def main() -> int:
    _force_helper_inproc_arch()
    _configure_logging()
    log = logging.getLogger("dupez-helper")

    args = _parse_args()

    # Task Scheduler launches cannot carry a dynamic parent PID. In that path,
    # consume the sentinel written by the GUI-side helper launcher.
    if args.parent_pid is None:
        sentinel = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "DupeZ",
            "helper_parent_pid.txt",
        )
        try:
            if os.path.exists(sentinel):
                with open(sentinel, "r", encoding="utf-8") as file_handle:
                    args.parent_pid = int(file_handle.read().strip())
        except Exception:
            pass

    log.info(
        "dupez_helper starting: role=%s pipe=%s parent_pid=%s",
        args.role,
        args.pipe or "<default>",
        args.parent_pid,
    )

    # Import the direct-Clumsy-aware singleton. The helper owns this instance,
    # so direct Clumsy and native WinDivert use the same policy as Compat mode
    # without proxying back into another helper.
    try:
        from app.firewall.direct_clumsy_manager import disruption_manager
    except Exception as exc:
        log.exception("failed to import disruption_manager: %s", exc)
        return 2

    degraded_ok = os.environ.get("DUPEZ_HELPER_ALLOW_DEGRADED") == "1"
    degraded = False
    if not disruption_manager.initialize():
        if not degraded_ok:
            log.error("disruption_manager.initialize() returned False")
            return 3
        log.warning(
            "initialize() failed — continuing in DEGRADED mode "
            "(DUPEZ_HELPER_ALLOW_DEGRADED=1)"
        )
        degraded = True

    if not degraded:
        try:
            disruption_manager.start()
        except Exception as exc:
            if not degraded_ok:
                log.exception("disruption_manager.start() raised: %s", exc)
                return 4
            log.warning("start() raised in degraded mode: %s", exc)
            degraded = True

    log.info(
        "disruption engine running in helper process (degraded=%s)",
        degraded,
    )

    try:
        from app.firewall import blocker as blocker_module
    except Exception as exc:
        log.warning("blocker module import failed: %s", exc)
        blocker_module = None

    from app.firewall_helper.server import run_helper_server

    dispatcher = run_helper_server(
        disruption_manager,
        blocker_module=blocker_module,
    )

    if args.parent_pid is not None:
        import threading

        try:
            import psutil

            parent_create_time = psutil.Process(args.parent_pid).create_time()
        except Exception:
            parent_create_time = None
        watcher = threading.Thread(
            target=_parent_watcher,
            args=(
                args.parent_pid,
                dispatcher.shutdown_event,
                parent_create_time,
            ),
            name="parent-watcher",
            daemon=True,
        )
        watcher.start()

    def _signal_handler(signum, _frame):
        log.info("received signal %d, shutting down", signum)
        dispatcher.shutdown_event.set()

    for handled_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(handled_signal, _signal_handler)
        except Exception:
            pass

    try:
        while not dispatcher.shutdown_event.wait(timeout=0.5):
            pass
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt, shutting down")

    log.info("restoring helper-owned network state")
    try:
        disruption_manager.stop_all_devices()
    except Exception as exc:
        log.error("error stopping active devices: %s", exc)

    if blocker_module is not None:
        try:
            blocker_module.clear_all_dupez_blocks()
        except Exception as exc:
            log.error("error clearing firewall blocks: %s", exc)

    log.info("stopping disruption engine")
    try:
        disruption_manager.stop()
    except Exception as exc:
        log.error("error stopping disruption_manager: %s", exc)

    log.info("dupez_helper exit 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
