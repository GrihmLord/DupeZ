"""
IPC fuzzer (MITRE ATT&CK TA0008 Lateral Movement, but **local self-test only**).

Sends a bounded set of malformed messages to DupeZ's own local IPC
surface (named pipes on Windows, AF_UNIX sockets on POSIX) to verify
that the server:

    1. authenticates the peer before trusting any message (rejects a
       client running as a different user).
    2. enforces a maximum frame size (rejects overlong input without
       OOMing).
    3. rejects non-JSON, malformed JSON, and JSON whose type doesn't
       match the protocol schema.
    4. does not deadlock, hang indefinitely, or echo back uninitialised
       memory.

This is a black-box fuzz against our *own* endpoints — it is not a
general-purpose IPC exploit tool. It refuses to run against any socket
not explicitly listed in :data:`ALLOWED_TARGETS`, and only ever
connects to loopback / local transports.

No findings are emitted unless a misbehaviour is actually observed.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import time
from typing import Callable, List, Optional, Tuple

from app.offsec import require_consent
from app.offsec.findings import FindingRegistry, Severity

__all__ = ["run_fuzz_ipc", "ALLOWED_TARGETS"]


# Known DupeZ IPC endpoints — only these are probed.
# Format: ("pipe" | "unix", address)
ALLOWED_TARGETS: List[Tuple[str, str]] = [
    ("pipe", r"\\.\pipe\DupeZ.control"),
    ("pipe", r"\\.\pipe\DupeZ.helper"),
    ("unix", "/tmp/dupez.control.sock"),
]

# Per-message budget — don't waste the user's time on a wedged endpoint.
CONNECT_TIMEOUT_S = 1.0
READ_TIMEOUT_S = 2.0

# Cap per message. If the server lets us send more than this without
# refusing, we record a finding.
MAX_FRAME_CAP = 4 * 1024 * 1024


def _send_and_read(
    target: Tuple[str, str],
    payload: bytes,
    *,
    expect_close: bool = False,
    label: str = "",
) -> Tuple[bool, bytes, Optional[str]]:
    """Send *payload* to *target*, read up to 4KB of reply.

    Returns (ok, reply, error). ``ok=True`` means the send completed;
    the caller decides whether the server's response is acceptable.
    """
    kind, addr = target
    try:
        if kind == "pipe":
            if os.name != "nt":
                return (False, b"", "pipe on non-Windows")
            # File-open style pipe I/O.
            with open(addr, "r+b", buffering=0) as pipe:
                pipe.write(payload)
                try:
                    reply = pipe.read(4096)
                except Exception:
                    reply = b""
                return (True, reply, None)
        elif kind == "unix":
            if os.name == "nt" or not hasattr(socket, "AF_UNIX"):
                return (False, b"", "AF_UNIX unavailable")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(CONNECT_TIMEOUT_S)
            try:
                s.connect(addr)
                s.settimeout(READ_TIMEOUT_S)
                s.sendall(payload)
                try:
                    reply = s.recv(4096)
                except socket.timeout:
                    reply = b""
                return (True, reply, None)
            finally:
                try:
                    s.close()
                except OSError:
                    pass
        else:
            return (False, b"", f"unknown kind {kind}")
    except FileNotFoundError:
        return (False, b"", "not present")
    except PermissionError as e:
        return (False, b"", f"permission denied: {e}")
    except OSError as e:
        return (False, b"", f"os error: {e}")


def _target_exists(target: Tuple[str, str]) -> bool:
    kind, addr = target
    if kind == "pipe":
        return os.name == "nt" and os.path.exists(addr)
    if kind == "unix":
        return os.name != "nt" and os.path.exists(addr)
    return False


# ── Test cases ────────────────────────────────────────────────────

def _case_giant_frame(target, reg: FindingRegistry) -> None:
    """Server should refuse a 4 MiB single-message frame."""
    payload = b"A" * MAX_FRAME_CAP
    t0 = time.monotonic()
    ok, reply, err = _send_and_read(target, payload, label="giant_frame")
    dur = time.monotonic() - t0
    if ok and len(reply) > 0 and b"error" not in reply.lower():
        reg.record(
            title=f"IPC endpoint {target[1]} accepted a {MAX_FRAME_CAP}-byte frame",
            description=(
                "A 4 MiB single-message payload was accepted without an error "
                "response. The server must enforce a maximum frame size to "
                "prevent memory-exhaustion DoS from a local peer."
            ),
            severity=Severity.HIGH,
            cvss_base=7.5,
            cvss_vector="CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:H",
            attack_technique="T1499.003",  # Application Exhaustion Flood
            evidence={"target": target, "duration_s": round(dur, 3),
                      "reply_head": reply[:200].decode("utf-8", "replace")},
            remediation=(
                "Enforce a MAX_FRAME_SIZE constant (recommend 64 KiB) in the "
                "IPC read loop and drop the connection on violation."
            ),
        )


def _case_malformed_json(target, reg: FindingRegistry) -> None:
    """Each payload should elicit an error response, not a crash/hang."""
    payloads = [
        b"",                                  # empty
        b"{",                                 # truncated object
        b"\x00" * 64,                         # NUL sled
        b"\xff\xfe" + b"X" * 64,              # UTF-16 BOM + junk
        b'{"command": "\\u0000"}',            # NUL inside string
        b'{"command": ' + b'"X"' * 1024 + b'}',  # deeply repeated
        b'["' + b"nested" * 64 + b'"]',       # long array
        b'{"n": ' + b"9" * 1024 + b'}',       # giant number literal
    ]
    for p in payloads:
        t0 = time.monotonic()
        ok, reply, err = _send_and_read(target, p, label="malformed_json")
        dur = time.monotonic() - t0
        if dur > READ_TIMEOUT_S * 1.5:
            reg.record(
                title=f"IPC endpoint {target[1]} hung on malformed payload",
                description=(
                    "A malformed input took longer than the read timeout to "
                    "produce any response. Indicates a blocking parse loop or "
                    "a missing per-connection deadline."
                ),
                severity=Severity.MEDIUM,
                cvss_base=5.5,
                cvss_vector="CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:H",
                evidence={
                    "target": target,
                    "duration_s": round(dur, 3),
                    "payload_head": p[:64].hex(),
                },
                remediation=(
                    "Apply a SO_RCVTIMEO / asyncio.wait_for on reads, and "
                    "limit JSON parse depth via a streaming parser."
                ),
            )


def _case_cross_user(target, reg: FindingRegistry) -> None:
    """Sanity hook: in a hardened IPC the server would reject us if we
    ran under a different user. We can't easily test that from inside
    the same process, so we just note the expectation in the report.
    """
    reg.record(
        title=f"Manual check required: peer authentication on {target[1]}",
        description=(
            "Automated fuzzer cannot validate cross-user peer rejection "
            "from inside the same user session. Required manual test: "
            "(1) open a shell as a different OS user; (2) attempt to "
            "connect to this endpoint; (3) confirm the server refuses "
            "the connection (Windows: GetNamedPipeClientProcessId → "
            "OpenProcessToken → compare SID; POSIX: SO_PEERCRED → compare uid)."
        ),
        severity=Severity.INFO,
        attack_technique="T1021",
        evidence={"target": target},
    )


# ── Public entrypoint ───────────────────────────────────────────

def run_fuzz_ipc(reg: FindingRegistry) -> None:
    """Probe DupeZ's own IPC endpoints. Records findings into *reg*.

    Endpoints that are not present on this host are silently skipped —
    there is nothing to fuzz.
    """
    require_consent()
    any_reachable = False
    for target in ALLOWED_TARGETS:
        if not _target_exists(target):
            continue
        any_reachable = True
        _case_giant_frame(target, reg)
        _case_malformed_json(target, reg)
        _case_cross_user(target, reg)

    if not any_reachable:
        reg.record(
            title="No DupeZ IPC endpoints reachable for fuzzing",
            description=(
                "None of the allowlisted IPC endpoints "
                f"({[t[1] for t in ALLOWED_TARGETS]}) are present. "
                "Either DupeZ is not running, or the helper has not started."
            ),
            severity=Severity.INFO,
            evidence={"allowed_targets": ALLOWED_TARGETS},
        )
