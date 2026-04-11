"""
WinDivert IPC Spike — Option B viability benchmark.

Measures the overhead of routing packet injection through an IPC boundary
(helper process over loopback TCP or Windows named pipe) vs. an in-process
function call. This is the ONLY blocking question for Option B:

    "If DupeZ main process runs unelevated and WinDivert runs in an elevated
     helper, does the IPC round-trip add enough latency to break duping?"

Hot path today (app/firewall/native_divert_engine.py::_send_packet):
    with self._send_lock:
        ctypes.memmove(send_buf, packet, pkt_len)
        WinDivertHelperCalcChecksums(...)
        WinDivertSend(handle, send_buf, pkt_len, ...)

Under Option B, the IPC-wrapped version adds: serialize packet+addr to a
framed binary message, write to pipe/socket, helper reads frame, helper
runs the same WinDivertSend, helper writes ack, client reads ack. We need
to know the delta.

Pass criteria (from Grihm's constraints — duping must NOT regress):
    p50  round-trip overhead  <  50  µs
    p99  round-trip overhead  < 200  µs
    p999 round-trip overhead  < 500  µs
    sustained throughput      ≥  2× current peak inject rate (~20k pkt/s)
    no burst latency cliff under sustained load

TOUCHES NO PRODUCTION CODE. Throwaway diagnostic.

Usage:
    python bench/windivert_ipc_spike.py --transport tcp     --packets 20000
    python bench/windivert_ipc_spike.py --transport pipe    --packets 20000   # Windows only
    python bench/windivert_ipc_spike.py --baseline          --packets 20000
    python bench/windivert_ipc_spike.py --all               --packets 20000   # run baseline + tcp (+pipe on win32)

Helper role (spawned automatically as child):
    python bench/windivert_ipc_spike.py --role helper --transport <t> --endpoint <addr>

The helper does NOT call the real WinDivert.dll — the goal is to isolate
IPC overhead. WinDivertSend cost is identical in both architectures, so it
cancels out of the delta. The helper performs an equivalent-cost no-op
(memcpy + checksum placeholder) to keep the measurement honest.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import time
import threading
from dataclasses import dataclass
from statistics import median
from typing import Callable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------
# Frame layout (little-endian, matches what a production Python<->helper
# protocol would use):
#
#     struct Header {
#         uint32_t frame_len;   // total bytes following this field
#         uint8_t  opcode;      // 1=inject, 2=ack, 3=quit
#         uint8_t  flags;
#         uint16_t addr_len;    // WINDIVERT_ADDRESS size (~80B)
#         uint32_t packet_len;  // packet bytes
#         /* addr_len bytes of addr */
#         /* packet_len bytes of packet */
#     };
#
# Ack frame: opcode=2, addr_len=0, packet_len=0, no payload.

HEADER_FMT = "<IBBHI"
HEADER_LEN = struct.calcsize(HEADER_FMT)

OP_INJECT = 1
OP_ACK = 2
OP_QUIT = 3

# Ack frame is cached — it's sent millions of times and never changes.
ACK_FRAME = struct.pack(HEADER_FMT, HEADER_LEN - 4, OP_ACK, 0, 0, 0)

# WINDIVERT_ADDRESS is 80 bytes on x64 for WinDivert 2.x. We use this fixed
# size for all bench packets so we're measuring the realistic envelope.
ADDR_SIZE = 80


def pack_inject(packet: bytes, addr: bytes) -> bytes:
    body_len = 1 + 1 + 2 + 4 + len(addr) + len(packet)
    return (
        struct.pack(HEADER_FMT, body_len, OP_INJECT, 0, len(addr), len(packet))
        + addr
        + packet
    )


def pack_quit() -> bytes:
    return struct.pack(HEADER_FMT, HEADER_LEN - 4, OP_QUIT, 0, 0, 0)


# ---------------------------------------------------------------------------
# Socket helpers
# ---------------------------------------------------------------------------

def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        r = sock.recv_into(view[got:], n - got)
        if r == 0:
            return None
        got += r
    return bytes(buf)


def _recv_frame(sock: socket.socket) -> Optional[Tuple[int, bytes]]:
    hdr = _recv_exact(sock, HEADER_LEN)
    if hdr is None:
        return None
    body_len, opcode, _flags, addr_len, packet_len = struct.unpack(HEADER_FMT, hdr)
    remaining = (addr_len + packet_len)
    if remaining:
        body = _recv_exact(sock, remaining)
        if body is None:
            return None
    else:
        body = b""
    return opcode, body


def _tune_socket(sock: socket.socket) -> None:
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    # Larger SO_SNDBUF/RCVBUF reduces syscall count under burst load.
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Helper role (server side — would run elevated in production)
# ---------------------------------------------------------------------------

def run_helper_tcp(host: str, port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    conn, _ = srv.accept()
    _tune_socket(conn)
    srv.close()

    # Pre-allocated "send buffer" mirrors native_divert_engine._send_buf.
    # In production this would be the buffer handed to WinDivertSend().
    send_buf = bytearray(65535)
    try:
        while True:
            frame = _recv_frame(conn)
            if frame is None:
                break
            opcode, body = frame
            if opcode == OP_QUIT:
                break
            if opcode != OP_INJECT:
                continue

            # Equivalent-cost no-op work to keep the benchmark honest.
            # This mirrors the memmove + checksum stage that happens on
            # the current hot path, MINUS the actual WinDivertSend syscall
            # (which is architecture-independent and cancels out of delta).
            packet_len = len(body) - ADDR_SIZE
            if packet_len > 0:
                send_buf[:packet_len] = body[ADDR_SIZE:ADDR_SIZE + packet_len]
                # Fake checksum: sum first 20 bytes (IP header span). Cheap
                # but non-trivial so the Python interpreter can't elide it.
                _ = sum(send_buf[:20])

            conn.sendall(ACK_FRAME)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def run_helper_pipe(pipe_name: str) -> None:
    """Windows named pipe helper. Only runs on win32."""
    if sys.platform != "win32":
        raise RuntimeError("Named pipe transport only supported on Windows")

    import win32pipe  # type: ignore
    import win32file  # type: ignore
    import pywintypes  # type: ignore

    pipe = win32pipe.CreateNamedPipe(
        pipe_name,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
        1,  # max instances
        1 << 20,  # out buffer
        1 << 20,  # in buffer
        0,
        None,
    )
    win32pipe.ConnectNamedPipe(pipe, None)

    send_buf = bytearray(65535)

    def read_exact(n: int) -> Optional[bytes]:
        out = bytearray()
        while len(out) < n:
            try:
                hr, data = win32file.ReadFile(pipe, n - len(out))
            except pywintypes.error:
                return None
            if not data:
                return None
            out.extend(data)
        return bytes(out)

    try:
        while True:
            hdr = read_exact(HEADER_LEN)
            if hdr is None:
                break
            body_len, opcode, _flags, addr_len, packet_len = struct.unpack(HEADER_FMT, hdr)
            remaining = addr_len + packet_len
            body = read_exact(remaining) if remaining else b""
            if body is None and remaining:
                break
            if opcode == OP_QUIT:
                break
            if opcode != OP_INJECT:
                continue

            if packet_len > 0:
                send_buf[:packet_len] = body[ADDR_SIZE:ADDR_SIZE + packet_len]
                _ = sum(send_buf[:20])

            win32file.WriteFile(pipe, ACK_FRAME)
    finally:
        try:
            win32file.CloseHandle(pipe)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Client-side benchmarks
# ---------------------------------------------------------------------------

@dataclass
class LatencyResult:
    label: str
    count: int
    size: int
    p50_us: float
    p90_us: float
    p99_us: float
    p999_us: float
    max_us: float
    mean_us: float
    throughput_pps: float
    wallclock_s: float

    def render(self) -> str:
        return (
            f"  {self.label:<28} "
            f"p50={self.p50_us:>7.1f}µs  "
            f"p99={self.p99_us:>7.1f}µs  "
            f"p999={self.p999_us:>7.1f}µs  "
            f"max={self.max_us:>7.1f}µs  "
            f"mean={self.mean_us:>7.1f}µs  "
            f"thr={self.throughput_pps:>9,.0f} pkt/s"
        )


def _summarize(label: str, samples_ns: List[int], size: int, wallclock_s: float) -> LatencyResult:
    samples_ns.sort()
    n = len(samples_ns)

    def pct(p: float) -> float:
        if n == 0:
            return 0.0
        idx = min(n - 1, int(p * n))
        return samples_ns[idx] / 1000.0

    mean_us = (sum(samples_ns) / n) / 1000.0 if n else 0.0
    return LatencyResult(
        label=label,
        count=n,
        size=size,
        p50_us=pct(0.50),
        p90_us=pct(0.90),
        p99_us=pct(0.99),
        p999_us=pct(0.999),
        max_us=(samples_ns[-1] / 1000.0) if n else 0.0,
        mean_us=mean_us,
        throughput_pps=(n / wallclock_s) if wallclock_s > 0 else 0.0,
        wallclock_s=wallclock_s,
    )


def bench_baseline(count: int, packet_size: int) -> LatencyResult:
    """In-process function call — matches current architecture cost."""
    packet = bytes(packet_size)
    addr = bytes(ADDR_SIZE)
    send_buf = bytearray(65535)

    def inject(pkt: bytes, a: bytes) -> None:
        # Mirrors helper no-op work exactly.
        plen = len(pkt)
        send_buf[:plen] = pkt
        _ = sum(send_buf[:20])

    samples: List[int] = []
    perf = time.perf_counter_ns
    t0 = perf()
    for _ in range(count):
        s = perf()
        inject(packet, addr)
        samples.append(perf() - s)
    wall = (perf() - t0) / 1e9
    return _summarize(f"baseline (in-proc, {packet_size}B)", samples, packet_size, wall)


def bench_tcp(count: int, packet_size: int, host: str = "127.0.0.1") -> LatencyResult:
    port = _pick_free_port()
    helper = _spawn_helper("tcp", f"{host}:{port}")
    try:
        sock = _connect_with_retry(lambda: _connect_tcp(host, port))
        _tune_socket(sock)
        try:
            samples = _run_pingpong(sock, count, packet_size, use_tcp=True)
        finally:
            try:
                sock.sendall(pack_quit())
            except OSError:
                pass
            sock.close()
    finally:
        helper.wait(timeout=5)

    wall = sum(samples) / 1e9
    return _summarize(f"tcp loopback ({packet_size}B)", samples, packet_size, wall)


def bench_pipe(count: int, packet_size: int) -> LatencyResult:
    if sys.platform != "win32":
        raise RuntimeError("Named pipe bench only supported on Windows")

    import win32file  # type: ignore
    import win32pipe  # type: ignore
    import pywintypes  # type: ignore

    pipe_name = r"\\.\pipe\dupez_ipc_spike_" + str(os.getpid())
    helper = _spawn_helper("pipe", pipe_name)
    try:
        # Wait for server to create pipe, then open handle.
        handle = None
        for _ in range(50):
            try:
                handle = win32file.CreateFile(
                    pipe_name,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                )
                break
            except pywintypes.error:
                time.sleep(0.02)
        if handle is None:
            raise RuntimeError("Could not connect to helper named pipe")

        samples = _run_pingpong_pipe(handle, count, packet_size)
        try:
            win32file.WriteFile(handle, pack_quit())
        except pywintypes.error:
            pass
        win32file.CloseHandle(handle)
    finally:
        helper.wait(timeout=5)

    wall = sum(samples) / 1e9
    return _summarize(f"win32 named pipe ({packet_size}B)", samples, packet_size, wall)


def bench_tcp_burst(count: int, packet_size: int, host: str = "127.0.0.1") -> LatencyResult:
    """Fire-and-forget throughput — client doesn't block on ack per packet.

    Measures sustained inject rate under a duping burst. A reader thread
    drains acks in parallel so we can observe whether the helper keeps up
    or starts queueing.
    """
    port = _pick_free_port()
    helper = _spawn_helper("tcp", f"{host}:{port}")
    try:
        sock = _connect_with_retry(lambda: _connect_tcp(host, port))
        _tune_socket(sock)

        stop = threading.Event()
        ack_count = [0]

        def drain() -> None:
            while not stop.is_set():
                frame = _recv_frame(sock)
                if frame is None:
                    return
                if frame[0] == OP_ACK:
                    ack_count[0] += 1
                    if ack_count[0] >= count:
                        return

        t = threading.Thread(target=drain, daemon=True)
        t.start()

        packet = bytes(packet_size)
        addr = bytes(ADDR_SIZE)
        frame = pack_inject(packet, addr)

        perf = time.perf_counter_ns
        t0 = perf()
        try:
            for _ in range(count):
                sock.sendall(frame)
        finally:
            pass
        # Wait for all acks to land.
        t.join(timeout=30)
        wall = (perf() - t0) / 1e9
        stop.set()

        try:
            sock.sendall(pack_quit())
        except OSError:
            pass
        sock.close()
    finally:
        helper.wait(timeout=5)

    # Throughput-only measurement: no per-packet latency recorded.
    return LatencyResult(
        label=f"tcp burst ({packet_size}B, async)",
        count=ack_count[0],
        size=packet_size,
        p50_us=0, p90_us=0, p99_us=0, p999_us=0, max_us=0, mean_us=0,
        throughput_pps=(ack_count[0] / wall) if wall > 0 else 0,
        wallclock_s=wall,
    )


# ---------------------------------------------------------------------------
# Ping-pong loops
# ---------------------------------------------------------------------------

def _run_pingpong(sock: socket.socket, count: int, packet_size: int, use_tcp: bool) -> List[int]:
    packet = bytes(packet_size)
    addr = bytes(ADDR_SIZE)
    frame = pack_inject(packet, addr)
    samples: List[int] = [0] * count
    perf = time.perf_counter_ns

    # Warm up — first few round-trips pay TCP slow start and page faults.
    for _ in range(100):
        sock.sendall(frame)
        _recv_frame(sock)

    for i in range(count):
        s = perf()
        sock.sendall(frame)
        _recv_frame(sock)
        samples[i] = perf() - s
    return samples


def _run_pingpong_pipe(handle, count: int, packet_size: int) -> List[int]:
    import win32file  # type: ignore

    packet = bytes(packet_size)
    addr = bytes(ADDR_SIZE)
    frame = pack_inject(packet, addr)

    def recv_frame() -> None:
        # Header
        want = HEADER_LEN
        got = bytearray()
        while len(got) < want:
            _, data = win32file.ReadFile(handle, want - len(got))
            if not data:
                return
            got.extend(data)
        body_len, _op, _f, addr_len, packet_len = struct.unpack(HEADER_FMT, bytes(got))
        rem = addr_len + packet_len
        while rem > 0:
            _, data = win32file.ReadFile(handle, rem)
            if not data:
                return
            rem -= len(data)

    # Warm up
    for _ in range(100):
        win32file.WriteFile(handle, frame)
        recv_frame()

    samples: List[int] = [0] * count
    perf = time.perf_counter_ns
    for i in range(count):
        s = perf()
        win32file.WriteFile(handle, frame)
        recv_frame()
        samples[i] = perf() - s
    return samples


# ---------------------------------------------------------------------------
# Plumbing: spawn helper, pick port, etc.
# ---------------------------------------------------------------------------

def _connect_tcp(host: str, port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    return s


def _connect_with_retry(fn: Callable[[], socket.socket], attempts: int = 50) -> socket.socket:
    last: Optional[Exception] = None
    for _ in range(attempts):
        try:
            return fn()
        except OSError as exc:
            last = exc
            time.sleep(0.02)
    raise RuntimeError(f"Could not connect after {attempts} attempts: {last}")


def _pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spawn_helper(transport: str, endpoint: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            os.path.abspath(__file__),
            "--role", "helper",
            "--transport", transport,
            "--endpoint", endpoint,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

PASS_CRITERIA = {
    "p50_us":  50.0,
    "p99_us":  200.0,
    "p999_us": 500.0,
    "min_pps": 40000.0,  # 2× current peak inject rate (~20k pps)
}


def verdict(baseline: LatencyResult, ipc: LatencyResult) -> Tuple[bool, List[str]]:
    """Compare IPC result to baseline + hard pass criteria."""
    reasons: List[str] = []
    ok = True

    delta_p50  = ipc.p50_us  - baseline.p50_us
    delta_p99  = ipc.p99_us  - baseline.p99_us
    delta_p999 = ipc.p999_us - baseline.p999_us

    if delta_p50 > PASS_CRITERIA["p50_us"]:
        ok = False
        reasons.append(f"FAIL: p50 overhead {delta_p50:.1f}µs > {PASS_CRITERIA['p50_us']}µs")
    else:
        reasons.append(f"pass: p50 overhead {delta_p50:.1f}µs")

    if delta_p99 > PASS_CRITERIA["p99_us"]:
        ok = False
        reasons.append(f"FAIL: p99 overhead {delta_p99:.1f}µs > {PASS_CRITERIA['p99_us']}µs")
    else:
        reasons.append(f"pass: p99 overhead {delta_p99:.1f}µs")

    if delta_p999 > PASS_CRITERIA["p999_us"]:
        ok = False
        reasons.append(f"FAIL: p999 overhead {delta_p999:.1f}µs > {PASS_CRITERIA['p999_us']}µs")
    else:
        reasons.append(f"pass: p999 overhead {delta_p999:.1f}µs")

    if ipc.throughput_pps < PASS_CRITERIA["min_pps"]:
        ok = False
        reasons.append(
            f"FAIL: throughput {ipc.throughput_pps:,.0f} pps < {PASS_CRITERIA['min_pps']:,.0f} pps"
        )
    else:
        reasons.append(f"pass: throughput {ipc.throughput_pps:,.0f} pps")

    return ok, reasons


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="WinDivert IPC overhead spike")
    ap.add_argument("--role", choices=["client", "helper"], default="client")
    ap.add_argument("--transport", choices=["tcp", "pipe"], default="tcp")
    ap.add_argument("--endpoint", default="127.0.0.1:0",
                    help="helper role: host:port for tcp, pipe name for pipe")
    ap.add_argument("--packets", type=int, default=20000,
                    help="ping-pong iterations per bench")
    ap.add_argument("--size", type=int, default=600,
                    help="simulated DayZ packet body size in bytes")
    ap.add_argument("--baseline", action="store_true",
                    help="run baseline in-proc bench only")
    ap.add_argument("--burst", action="store_true",
                    help="also run sustained burst throughput test")
    ap.add_argument("--all", action="store_true",
                    help="run baseline + tcp (+ pipe on Windows) + burst")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON summary at the end")
    args = ap.parse_args()

    if args.role == "helper":
        if args.transport == "tcp":
            host, port = args.endpoint.split(":")
            run_helper_tcp(host, int(port))
        else:
            run_helper_pipe(args.endpoint)
        return 0

    print("=" * 78)
    print("WinDivert IPC Overhead Spike — Option B viability benchmark")
    print("=" * 78)
    print(f"packets={args.packets}  packet_size={args.size}B  addr_size={ADDR_SIZE}B")
    print(f"pass criteria: p50<{PASS_CRITERIA['p50_us']}µs  "
          f"p99<{PASS_CRITERIA['p99_us']}µs  "
          f"p999<{PASS_CRITERIA['p999_us']}µs  "
          f"thr>{PASS_CRITERIA['min_pps']:,.0f} pps")
    print()

    results: List[LatencyResult] = []

    baseline = bench_baseline(args.packets, args.size)
    results.append(baseline)
    print(baseline.render())

    if args.baseline and not args.all:
        _report(results, baseline, None, as_json=args.json)
        return 0

    if args.transport == "tcp" or args.all:
        tcp = bench_tcp(args.packets, args.size)
        results.append(tcp)
        print(tcp.render())
    else:
        tcp = None

    pipe = None
    if args.all and sys.platform == "win32":
        try:
            pipe = bench_pipe(args.packets, args.size)
            results.append(pipe)
            print(pipe.render())
        except Exception as exc:
            print(f"  named pipe bench skipped: {exc}")
    elif args.transport == "pipe":
        pipe = bench_pipe(args.packets, args.size)
        results.append(pipe)
        print(pipe.render())

    if args.burst or args.all:
        burst = bench_tcp_burst(max(args.packets, 50000), args.size)
        results.append(burst)
        print(burst.render())

    # Use the transport the user explicitly ran (pipe > tcp if both ran).
    primary_ipc = pipe or tcp
    _report(results, baseline, primary_ipc, as_json=args.json)
    return 0


def _report(results: List[LatencyResult], baseline: LatencyResult,
            primary_ipc: Optional[LatencyResult], as_json: bool) -> None:
    print()
    print("-" * 78)
    if primary_ipc is None:
        print("baseline-only run — no IPC comparison")
    else:
        ok, reasons = verdict(baseline, primary_ipc)
        print(f"VERDICT: {'PASS — Option B is viable' if ok else 'FAIL — Option B would regress duping'}")
        for r in reasons:
            print(f"  {r}")
    print("-" * 78)

    if as_json:
        print(json.dumps({
            "results": [r.__dict__ for r in results],
            "verdict": (
                None if primary_ipc is None
                else {"pass": verdict(baseline, primary_ipc)[0]}
            ),
        }, indent=2))


if __name__ == "__main__":
    sys.exit(main())
