# app/firewall_helper/transport.py
"""
Windows named-pipe transport for the DupeZ split-elevation IPC.

Benchmark results (bench/windivert_ipc_spike.py, commit a55601f):
    p50  = 18.5 µs
    p99  = 40.0 µs
    p999 = 71.3 µs
    throughput = 51,190 ops/sec sustained

These are well inside the control-plane budget. Control messages happen at
~10 Hz (stats polling) or on user action (disrupt/stop/hotkey); IPC overhead
is invisible against the 100 ms human-perception floor.

This module provides:
    * PipeServer  — helper side. Accepts one client connection at a time,
                    dispatches frames via a user-supplied handler.
    * PipeClient  — main side. Connects to the pipe, sends framed requests,
                    reads framed responses. Thread-safe via an internal lock.

Both classes expect `protocol.Request` / `protocol.Response` dataclasses.

On non-Windows platforms these raise at import time. That's fine — DupeZ
is Windows-only.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Callable, Optional

from app.firewall_helper.auth import (
    AuthenticationError,
    HandshakeError,
    HANDSHAKE_TIMEOUT_SEC,
    handshake_client,
    handshake_server,
)
from app.firewall_helper.protocol import (
    FRAME_TERMINATOR,
    MAX_FRAME_BYTES,
    Request,
    Response,
)

log = logging.getLogger(__name__)

# Default pipe name. Session-specific variants can be constructed at
# runtime if we ever want to support multiple DupeZ instances on one box.
DEFAULT_PIPE_NAME = r"\\.\pipe\dupez_firewall_helper"

# Connection timeouts (milliseconds). Liberal on connect to absorb the
# UAC prompt + helper boot; tight on individual frame I/O.
CONNECT_TIMEOUT_MS = 15_000
FRAME_TIMEOUT_MS = 5_000


# ── Import Windows IPC primitives lazily so unit tests on Linux can stub ─

def _import_win32():
    """Import pywin32 pipe primitives. Raises on non-Windows."""
    if sys.platform != "win32":
        raise RuntimeError(
            "firewall_helper.transport requires Windows. "
            "Set DUPEZ_ARCH=inproc on non-Windows dev environments."
        )
    import win32con  # noqa: F401
    import win32file
    import win32pipe
    import pywintypes
    return win32pipe, win32file, pywintypes


def _build_cross_il_pipe_sa():
    """Build a SECURITY_ATTRIBUTES allowing Medium-IL clients to open the pipe.

    The helper runs at High IL (admin). By default, a pipe it creates gets
    a SECURITY_DESCRIPTOR that blocks Medium-IL clients — both because the
    default DACL only grants access to the creator's SID/admins/system, and
    because the implicit integrity label (High + default "NoWriteUp") denies
    write access from below. The Medium-IL GUI then fails its CreateFile
    with ERROR_ACCESS_DENIED (5).

    SDDL breakdown:
        D:(A;;GA;;;WD)          — DACL: Everyone (World, WD) GenericAll
        (A;;GA;;;AU)            — DACL: Authenticated Users GenericAll
        S:(ML;;NW;;;LW)         — SACL: Low mandatory label, No-Write-Up policy
                                   (Low means "allow any IL ≥ Low to access";
                                   NW is the pipe-appropriate policy bit)

    This keeps PIPE_REJECT_REMOTE_CLIENTS in effect at the pipe level, so
    network access remains denied even with the permissive DACL.
    """
    try:
        import win32security
        sddl = "D:(A;;GA;;;WD)(A;;GA;;;AU)S:(ML;;NW;;;LW)"
        sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            sddl, win32security.SDDL_REVISION_1
        )
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        sa.bInheritHandle = False
        return sa
    except Exception as e:
        log.error(
            "failed to build cross-IL pipe SECURITY_ATTRIBUTES (%s); "
            "falling back to default SD — Medium-IL clients will likely "
            "get ERROR_ACCESS_DENIED", e,
        )
        return None


# ── Frame helpers ───────────────────────────────────────────────────────

def _read_frame(pipe_handle, win32file, pywintypes) -> Optional[bytes]:
    """Read one LF-terminated frame from *pipe_handle*.

    Returns the frame bytes (without the terminator), or None if the peer
    closed the pipe. Raises on protocol violations (oversized frames).
    """
    buf = bytearray()
    try:
        while len(buf) < MAX_FRAME_BYTES:
            # ReadFile with a modest chunk; loop until we see LF.
            hr, chunk = win32file.ReadFile(pipe_handle, 4096)
            if not chunk:
                return None
            buf.extend(chunk)
            term_idx = buf.find(FRAME_TERMINATOR)
            if term_idx >= 0:
                frame = bytes(buf[:term_idx])
                leftover = bytes(buf[term_idx + 1:])
                if leftover:
                    # Protocol is one-frame-per-request on control plane;
                    # leftover implies peer pipelined frames. Reject.
                    raise ValueError(
                        f"unexpected {len(leftover)} bytes after frame terminator"
                    )
                return frame
    except pywintypes.error as e:
        # Broken pipe = clean disconnect.
        log.debug("pipe read error (treating as disconnect): %s", e)
        return None

    raise ValueError(f"frame exceeded {MAX_FRAME_BYTES} bytes without terminator")


def _write_frame(pipe_handle, win32file, data: bytes) -> None:
    """Write one pre-terminated frame to *pipe_handle*."""
    win32file.WriteFile(pipe_handle, data)


# ── Server side (lives in helper process) ───────────────────────────────

class PipeServer:
    """Named-pipe server for the firewall helper.

    Accepts one client at a time (the main DupeZ GUI process). On
    disconnect, loops back to accept the next connection — so the user
    can restart the GUI without restarting the helper.

    Security: the pipe is created with a SECURITY_DESCRIPTOR that allows
    the interactive user to connect but denies network access. Because
    the helper runs elevated and the main runs at Medium IL, this is the
    one cross-integrity path we explicitly permit.
    """

    def __init__(
        self,
        handler: Callable[[Request], Response],
        shared_secret: bytes,
        pipe_name: str = DEFAULT_PIPE_NAME,
    ) -> None:
        if not isinstance(shared_secret, (bytes, bytearray)) or len(shared_secret) != 32:
            raise ValueError(
                "PipeServer.shared_secret must be 32 bytes (see "
                "app.firewall_helper.auth.generate_token)"
            )
        self.handler = handler
        self.shared_secret = bytes(shared_secret)
        self.pipe_name = pipe_name
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("PipeServer already started")
        self._thread = threading.Thread(
            target=self._serve_forever,
            name="firewall-helper-pipe-server",
            daemon=True,
        )
        self._thread.start()

    def stop(self, wait_timeout_sec: float = 5.0) -> None:
        """Signal the server to stop and wake any blocked accept call.

        The blocking `ConnectNamedPipe` inside `_serve_forever` is woken
        by issuing a no-op self-connect via `CreateFile` against our own
        pipe — this is the Microsoft-documented pattern for graceful
        named-pipe shutdown without needing overlapped I/O.
        """
        self._stop.set()
        # Wake the accept loop by briefly connecting to ourselves.
        try:
            win32pipe, win32file, pywintypes = _import_win32()
            try:
                h = win32file.CreateFile(
                    self.pipe_name,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                )
                win32file.CloseHandle(h)
            except pywintypes.error:
                pass  # Pipe may already be torn down — fine.
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=wait_timeout_sec)

    def _serve_forever(self) -> None:
        win32pipe, win32file, pywintypes = _import_win32()
        log.info("PipeServer starting on %s", self.pipe_name)

        # Build once: cross-IL SECURITY_ATTRIBUTES. Falls back to None on
        # failure (same behavior as before the fix).
        pipe_sa = _build_cross_il_pipe_sa()

        while not self._stop.is_set():
            pipe_handle = None
            try:
                pipe_handle = win32pipe.CreateNamedPipe(
                    self.pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    (
                        win32pipe.PIPE_TYPE_BYTE
                        | win32pipe.PIPE_READMODE_BYTE
                        | win32pipe.PIPE_WAIT
                        | win32pipe.PIPE_REJECT_REMOTE_CLIENTS
                    ),
                    1,        # max instances: one client at a time
                    65536,    # out buffer
                    65536,    # in buffer
                    0,        # default timeout
                    pipe_sa,  # cross-IL SD (Medium-IL GUI can open)
                )
                win32pipe.ConnectNamedPipe(pipe_handle, None)
                log.info("PipeServer client connected")
                # ── Mutual auth BEFORE any dispatch (H2 / ADR-0001 §6) ──
                # Any process on the same session can open the pipe
                # (SDDL grants WD+AU), so every connection MUST prove
                # knowledge of the shared secret before we accept a
                # single request frame.
                try:
                    self._do_handshake(pipe_handle, win32file, pywintypes)
                except AuthenticationError as e:
                    log.warning("PipeServer: rejecting unauthenticated client: %s", e)
                    continue
                except HandshakeError as e:
                    log.warning("PipeServer: malformed handshake, dropping: %s", e)
                    continue
                self._serve_client(pipe_handle, win32file, pywintypes)
            except Exception as e:
                # ERROR_PIPE_BUSY (231) means another helper instance already
                # owns this pipe — don't spam the log; back off for a second
                # so the duplicate helper (if any) can notice and exit.
                msg = str(e)
                if "231" in msg or "All pipe instances are busy" in msg:
                    log.error(
                        "PipeServer: another helper already owns %s — "
                        "this instance will back off and retry",
                        self.pipe_name,
                    )
                    time.sleep(1.0)
                else:
                    log.error("PipeServer error: %s", e)
                    time.sleep(0.1)
            finally:
                if pipe_handle is not None:
                    try:
                        win32pipe.DisconnectNamedPipe(pipe_handle)
                    except Exception:
                        pass
                    try:
                        win32file.CloseHandle(pipe_handle)
                    except Exception:
                        pass

        log.info("PipeServer stopped")

    def _do_handshake(self, pipe_handle, win32file, pywintypes) -> None:
        """Run the mutual auth handshake on an accepted pipe.

        Budget is HANDSHAKE_TIMEOUT_SEC — we enforce this by running
        the handshake in a side thread and joining on a deadline. On
        timeout we raise HandshakeError, which the accept loop treats
        as a disconnect.

        The handshake itself uses the same frame primitives as the
        dispatch loop (_read_frame / _write_frame), so WinDivert's
        pipe buffer semantics apply identically.
        """
        def _reader() -> Optional[bytes]:
            return _read_frame(pipe_handle, win32file, pywintypes)

        def _writer(data: bytes) -> None:
            _write_frame(pipe_handle, win32file, data)

        exc: list = []

        def _run() -> None:
            try:
                handshake_server(self.shared_secret, _reader, _writer)
            except Exception as e:  # noqa: BLE001 — re-raised on main thread below
                exc.append(e)

        t = threading.Thread(target=_run, name="pipe-handshake-server", daemon=True)
        t.start()
        t.join(timeout=HANDSHAKE_TIMEOUT_SEC)
        if t.is_alive():
            # Pipe read is still blocked — slam the pipe so the reader
            # unblocks with an error, then treat as a timeout.
            try:
                win32file.CloseHandle(pipe_handle)
            except Exception:
                pass
            raise HandshakeError(
                f"handshake did not complete within {HANDSHAKE_TIMEOUT_SEC}s"
            )
        if exc:
            raise exc[0]
        log.info("PipeServer: handshake complete, client authenticated")

    def _serve_client(self, pipe_handle, win32file, pywintypes) -> None:
        while not self._stop.is_set():
            frame = _read_frame(pipe_handle, win32file, pywintypes)
            if frame is None:
                log.debug("PipeServer client disconnected")
                return
            try:
                request = Request.decode(frame)
            except Exception as e:
                log.warning("PipeServer bad request: %s", e)
                response = Response.failure(
                    request_id=0,
                    error_code=2,  # ERR_BAD_REQUEST
                    error_message=str(e),
                )
                _write_frame(pipe_handle, win32file, response.encode())
                continue

            try:
                response = self.handler(request)
            except Exception as e:
                log.exception("PipeServer handler error on op=%s", request.op)
                response = Response.failure(
                    request_id=request.request_id,
                    error_code=3,  # ERR_INTERNAL
                    error_message=f"{type(e).__name__}: {e}",
                )

            _write_frame(pipe_handle, win32file, response.encode())


# ── Client side (lives in main GUI process) ─────────────────────────────

class PipeClient:
    """Named-pipe client used by the main GUI to talk to the helper.

    Thread-safe: a single internal lock serializes frame send/receive so
    multiple GUI threads can share one client instance.
    """

    def __init__(
        self,
        shared_secret: bytes,
        pipe_name: str = DEFAULT_PIPE_NAME,
    ) -> None:
        if not isinstance(shared_secret, (bytes, bytearray)) or len(shared_secret) != 32:
            raise ValueError(
                "PipeClient.shared_secret must be 32 bytes (see "
                "app.firewall_helper.auth.generate_token)"
            )
        self.shared_secret = bytes(shared_secret)
        self.pipe_name = pipe_name
        self._handle = None
        self._lock = threading.Lock()
        self._win32pipe = None
        self._win32file = None
        self._pywintypes = None

    def connect(self, timeout_ms: int = CONNECT_TIMEOUT_MS) -> None:
        """Open the pipe and complete mutual auth.

        The helper's CreateNamedPipe and our CreateFile race at startup;
        if the helper isn't ready yet we get ERROR_FILE_NOT_FOUND and
        retry after a short sleep. Once the pipe is open, we MUST complete
        the mutual-auth handshake before any Request frame is sent —
        see ADR-0001 §6 / auth.handshake_client.
        """
        self._win32pipe, self._win32file, self._pywintypes = _import_win32()

        deadline = time.monotonic() + (timeout_ms / 1000.0)
        last_err: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                self._handle = self._win32file.CreateFile(
                    self.pipe_name,
                    self._win32file.GENERIC_READ | self._win32file.GENERIC_WRITE,
                    0,
                    None,
                    self._win32file.OPEN_EXISTING,
                    0,
                    None,
                )
                # Match server mode.
                self._win32pipe.SetNamedPipeHandleState(
                    self._handle,
                    self._win32pipe.PIPE_READMODE_BYTE,
                    None,
                    None,
                )
                log.info("PipeClient connected to %s, running handshake...", self.pipe_name)
                # Run handshake BEFORE declaring the client usable.
                self._run_client_handshake()
                log.info("PipeClient handshake complete — authenticated to helper")
                return
            except (AuthenticationError, HandshakeError):
                # Hard fail on auth: we're talking to the wrong helper
                # or the secret is stale. Close the handle and raise —
                # the caller should NOT retry without a fresh token.
                try:
                    if self._handle is not None:
                        self._win32file.CloseHandle(self._handle)
                        self._handle = None
                except Exception:
                    pass
                raise
            except self._pywintypes.error as e:
                last_err = e
                time.sleep(0.05)

        raise TimeoutError(
            f"PipeClient.connect timed out after {timeout_ms} ms: {last_err}"
        )

    def _run_client_handshake(self) -> None:
        """Run the mutual-auth handshake over the currently open pipe."""
        if self._handle is None:
            raise RuntimeError("PipeClient._run_client_handshake before CreateFile")

        def _reader() -> Optional[bytes]:
            return _read_frame(self._handle, self._win32file, self._pywintypes)

        def _writer(data: bytes) -> None:
            _write_frame(self._handle, self._win32file, data)

        # Enforce the same timeout budget as the server.
        exc: list = []

        def _run() -> None:
            try:
                handshake_client(self.shared_secret, _reader, _writer)
            except Exception as e:  # noqa: BLE001 — re-raised on main thread
                exc.append(e)

        t = threading.Thread(target=_run, name="pipe-handshake-client", daemon=True)
        t.start()
        t.join(timeout=HANDSHAKE_TIMEOUT_SEC)
        if t.is_alive():
            # Kill the pipe to unblock the background reader, then raise.
            try:
                self._win32file.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
            raise HandshakeError(
                f"client handshake timed out after {HANDSHAKE_TIMEOUT_SEC}s"
            )
        if exc:
            raise exc[0]

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                try:
                    self._win32file.CloseHandle(self._handle)
                except Exception:
                    pass
                self._handle = None

    def call(self, request: Request) -> Response:
        """Send *request* and block until the matching response arrives."""
        if self._handle is None:
            raise RuntimeError("PipeClient.call before connect()")

        with self._lock:
            _write_frame(self._handle, self._win32file, request.encode())
            frame = _read_frame(self._handle, self._win32file, self._pywintypes)
            if frame is None:
                raise ConnectionError("PipeClient peer disconnected")
            response = Response.decode(frame)
            if response.request_id != request.request_id:
                raise RuntimeError(
                    f"PipeClient response id mismatch: "
                    f"expected {request.request_id}, got {response.request_id}"
                )
            return response
