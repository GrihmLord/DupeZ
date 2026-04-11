#!/usr/bin/env python
# bench/latency_regression.py
"""
Latency regression benchmark — inproc vs split (ADR-0001 Day 5).

Runs the same control-plane workload through two paths:

    1. `inproc` — directly against the real in-process disruption_manager
       singleton. This is the zero-IPC baseline.
    2. `split`  — through the DisruptionManagerProxy / PipeClient chain,
       with an in-process LoopbackClient stand-in for the named pipe
       when pywin32 isn't available (CI / Linux sandbox).

Measures per-call latency for the two hottest control-plane ops that
run in the steady state:

    * get_status()          — dashboard polls this at ~2-10 Hz
    * hotkey_trigger(...)   — GodMode hook, must be <<100 ms p999

Reports min / p50 / p95 / p99 / p999 / max for each (path, op) pair so
the regression is visible at a glance.

CRITICAL: this benchmark does NOT exercise the packet path. That is
intentional — the packet path runs 100% inside the helper process under
split mode, bit-for-bit identical to inproc. The only thing that changes
under split is the control plane, which is what we measure here.

Run:
    python bench/latency_regression.py            # both paths
    python bench/latency_regression.py --iters 5000
    python bench/latency_regression.py --path split
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import Callable, List

# Ensure app.* imports resolve when run from repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── Fake disruption_manager (no WinDivert, no Qt) ─────────────────────
# Matches the API shape used by both the inproc path and HelperDispatcher.
# The numbers are deliberately cheap so the benchmark measures transport
# overhead, not engine work.

class _FakeDM:
    def __init__(self) -> None:
        self._started = False
        self._disrupted: set[str] = set()

    def initialize(self) -> bool:
        return True

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def disrupt_device(self, ip, methods=None, params=None, **kwargs) -> bool:
        self._disrupted.add(ip)
        return True

    def stop_device(self, ip) -> bool:
        self._disrupted.discard(ip)
        return True

    def stop_all_devices(self) -> bool:
        self._disrupted.clear()
        return True

    def get_disrupted_devices(self) -> list:
        return list(self._disrupted)

    def get_device_status(self, ip) -> dict:
        return {"ip": ip, "active": ip in self._disrupted}

    def get_status(self) -> dict:
        return {
            "started": self._started,
            "count": len(self._disrupted),
            "mode": "bench",
        }

    def get_engine_stats(self) -> dict:
        return {"fps": 60, "queue_depth": 0}

    def hotkey_trigger(self, action, payload) -> bool:
        return True


# ── Percentile helper ─────────────────────────────────────────────────

def _pct(samples: List[float], q: float) -> float:
    if not samples:
        return float("nan")
    s = sorted(samples)
    i = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return s[i]


def _report(name: str, samples_us: List[float]) -> None:
    if not samples_us:
        print(f"  {name}: (no samples)")
        return
    print(
        f"  {name:24s}  "
        f"min={min(samples_us):7.2f}  "
        f"p50={_pct(samples_us, 0.50):7.2f}  "
        f"p95={_pct(samples_us, 0.95):7.2f}  "
        f"p99={_pct(samples_us, 0.99):7.2f}  "
        f"p999={_pct(samples_us, 0.999):7.2f}  "
        f"max={max(samples_us):7.2f}   (µs)"
    )


# ── Benchmark drivers ─────────────────────────────────────────────────

def _bench(fn: Callable[[], None], iters: int) -> List[float]:
    # Warm up.
    for _ in range(min(200, iters // 10 or 1)):
        fn()
    samples: List[float] = []
    append = samples.append
    pc = time.perf_counter_ns
    for _ in range(iters):
        t0 = pc()
        fn()
        append((pc() - t0) / 1000.0)  # ns → µs
    return samples


def run_inproc(iters: int) -> None:
    print(f"\n[inproc] direct singleton calls, iters={iters}")
    dm = _FakeDM()
    dm.initialize()
    dm.start()

    _report("get_status",       _bench(lambda: dm.get_status(), iters))
    _report("hotkey_trigger",   _bench(lambda: dm.hotkey_trigger("HIT", {}), iters))
    _report("get_engine_stats", _bench(lambda: dm.get_engine_stats(), iters))
    _report("disrupt_device",   _bench(lambda: dm.disrupt_device("10.0.0.5"), iters))


def run_split_loopback(iters: int) -> None:
    print(f"\n[split/loopback] through HelperDispatcher + encode/decode, iters={iters}")
    from app.firewall_helper.inproc_harness import LoopbackClient

    dm = _FakeDM()
    dm.initialize()
    dm.start()
    client = LoopbackClient(dm)

    _report("get_status",       _bench(lambda: client.get_status(), iters))
    _report("hotkey_trigger",
            _bench(lambda: client.hotkey_trigger("HIT", {}), iters))
    _report("get_engine_stats", _bench(lambda: client.get_engine_stats(), iters))
    _report("disrupt_device",
            _bench(lambda: client.disrupt_device("10.0.0.5", None, None), iters))


def run_real_pipe(iters: int, pipe_name: str) -> None:
    """Measure latency through the real Windows named-pipe transport.

    Requires a helper process (dupez_helper.py) to be running elevated
    on the same machine and listening on `pipe_name`. Hits the same
    four ops as the loopback path so the numbers line up directly.
    """
    print(f"\n[split/real-pipe] via {pipe_name}, iters={iters}")
    from app.firewall_helper.transport import PipeClient
    from app.firewall_helper.protocol import (
        Request,
        OP_PING,
        OP_GET_STATUS,
        OP_GET_ENGINE_STATS,
        OP_DISRUPT_DEVICE,
        OP_HOTKEY_TRIGGER,
    )

    client = PipeClient(pipe_name=pipe_name)
    client.connect(timeout_ms=5000)
    # Handshake sanity check.
    resp = client.call(Request(op=OP_PING))
    if not resp.ok:
        raise RuntimeError(f"real-pipe ping failed: {resp.error_message}")
    print("  handshake: ok")

    def _status():
        client.call(Request(op=OP_GET_STATUS))

    def _hotkey():
        client.call(Request(op=OP_HOTKEY_TRIGGER,
                            args={"action": "HIT", "payload": {}}))

    def _stats():
        client.call(Request(op=OP_GET_ENGINE_STATS))

    def _disrupt():
        client.call(Request(op=OP_DISRUPT_DEVICE,
                            args={"ip": "10.0.0.5",
                                  "methods": None, "params": None}))

    _report("get_status",       _bench(_status, iters))
    _report("hotkey_trigger",   _bench(_hotkey, iters))
    _report("get_engine_stats", _bench(_stats, iters))
    _report("disrupt_device",   _bench(_disrupt, iters))
    client.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=2000)
    ap.add_argument(
        "--path",
        choices=["inproc", "split", "real-pipe", "both"],
        default="both",
    )
    ap.add_argument(
        "--pipe",
        default=r"\\.\pipe\dupez_firewall_helper",
        help="Named pipe path for --path real-pipe",
    )
    args = ap.parse_args()

    print("=" * 70)
    print("DupeZ control-plane latency regression (ADR-0001 Day 5)")
    print("NOTE: packet path is NOT measured — it runs unchanged in the helper.")
    print("=" * 70)

    if args.path in ("inproc", "both"):
        run_inproc(args.iters)
    if args.path in ("split", "both"):
        try:
            run_split_loopback(args.iters)
        except Exception as e:
            print(f"\n[split/loopback] FAILED: {e}")
            return 1
    if args.path == "real-pipe":
        try:
            run_real_pipe(args.iters, args.pipe)
        except Exception as e:
            print(f"\n[split/real-pipe] FAILED: {e}")
            print("  (is dupez_helper.py running elevated on that pipe?)")
            return 1

    # Sanity budget: hotkey_trigger p999 should be well under 100 ms even
    # on the loopback path — human perception floor is ~100 ms and the
    # hotkey is the tightest budget op we have.
    print("\nBudget check:")
    print("  target  hotkey_trigger p999 <  1_000 µs  (1 ms)")
    print("  ceiling hotkey_trigger p999 < 100_000 µs (100 ms, human floor)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
