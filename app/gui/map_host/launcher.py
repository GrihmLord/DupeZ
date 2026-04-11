# app/gui/map_host/launcher.py — Parent-side child-host controller.
"""Launch an unelevated WebEngine child process and embed its HWND.

The parent DupeZ process runs elevated (for WinDivert), and Chromium's
GPU process refuses to initialize under an admin token. This module
spawns a separate ``python -m app.gui.map_host.host`` process via the
Explorer COM ``Shell.Application.ShellExecute`` API, which routes
through Explorer's medium-integrity token instead of our admin token,
so the child gets real GPU rasterization.

Parent ↔ child communication is a line-delimited JSON protocol over a
loopback TCP socket. The child sends ``{"type":"hello","hwnd":N}`` on
connect; the parent then wraps that HWND with ``QWindow.fromWinId`` +
``QWidget.createWindowContainer`` and drops the container into its
layout. Subsequent commands (``load`` / ``zoom`` / ``quit``) go over
the same socket.

Fallback: if Explorer COM is unavailable (non-Windows, missing
pywin32, COM error), we fall back to ``subprocess.Popen``, which
inherits the admin token and therefore gives us no GPU benefit, but
keeps the code path functional for Linux/macOS dev.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

from PyQt6.QtCore import QByteArray, QObject, pyqtSignal
from PyQt6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from app.logs.logger import log_error, log_info


# Resolve the child script path once at import time.
_HOST_SCRIPT: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "host.py"
)


# ── Explorer COM trick ──────────────────────────────────────────────


def _spawn_unelevated(python_exe: str, args: str) -> bool:
    """Spawn a child process at medium integrity via Explorer COM.

    The Explorer ``Shell.Application`` COM object executes its
    ``ShellExecute`` verb inside the Explorer process, which runs at
    medium integrity regardless of our token. The child process
    therefore inherits Explorer's token, not ours.

    Returns ``True`` if the spawn command was dispatched. Note: this
    function returns before the child has actually started — the
    parent must wait for the child's TCP ``hello`` message to confirm
    a successful launch.
    """
    if sys.platform != "win32":
        # Dev fallback: just popen it. No GPU benefit but the IPC path
        # still exercises end-to-end.
        return _spawn_popen(python_exe, args)

    try:
        import pythoncom  # noqa: F401 — needed for COM init on worker thread
        import win32com.client  # type: ignore

        # CoInitialize is required before Dispatch on Windows.
        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("Shell.Application")
            # ShellExecute(sFile, vArguments, vDirectory, vOperation, vShow)
            # vShow=1 → SW_SHOWNORMAL (we want it normal-sized so
            # reparenting doesn't need a resize event first).
            shell.ShellExecute(python_exe, args, os.getcwd(), "open", 1)
            log_info("map-host: spawned via Explorer COM (medium integrity)")
            return True
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        log_error(
            f"map-host: Explorer COM spawn failed ({exc!r}) — "
            "falling back to subprocess.Popen (inherits admin token, no GPU)"
        )
        return _spawn_popen(python_exe, args)


def _spawn_popen(python_exe: str, args: str) -> bool:
    """Plain subprocess spawn — inherits parent token."""
    import shlex
    import subprocess

    try:
        # shlex.split with posix=False on Windows keeps quoted paths intact.
        split_args = shlex.split(args, posix=(sys.platform != "win32"))
        subprocess.Popen([python_exe] + split_args, close_fds=True)
        log_info("map-host: spawned via subprocess.Popen (fallback)")
        return True
    except Exception as exc:  # noqa: BLE001
        log_error(f"map-host: subprocess fallback failed: {exc}")
        return False


# ── Parent-side controller ──────────────────────────────────────────


class MapHostClient(QObject):
    """Controls the lifecycle of an unelevated WebEngine child host.

    Usage:
        client = MapHostClient(self)
        client.hwndReceived.connect(self._embed_host_hwnd)
        client.connectionFailed.connect(self._fall_back_to_inproc)
        client.start()
        # ... later ...
        client.load(url)
        client.set_zoom(0.85)
        client.quit()   # also called in aboutToQuit

    Signals:
        hwndReceived(int)     — child sent its top-level HWND
        connectionFailed(str) — spawn or connect failed; caller should
                                fall back to the in-proc WebEngineView
        disconnected()        — child process exited or dropped socket
    """

    hwndReceived = pyqtSignal(int)
    connectionFailed = pyqtSignal(str)
    disconnected = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._server: QTcpServer = QTcpServer(self)
        self._sock: Optional[QTcpSocket] = None
        self._buf: bytes = b""
        self._hwnd: Optional[int] = None

    # ── Lifecycle ───────────────────────────────────────────────

    def start(self) -> bool:
        """Bind the listener and spawn the child.

        Returns ``False`` only on immediate failures (bind error,
        spawn dispatch error). A ``True`` return does NOT guarantee
        the child actually connected — wait for ``hwndReceived`` or
        ``connectionFailed``.
        """
        if not self._server.listen(
            QHostAddress.SpecialAddress.LocalHost, 0
        ):
            err = self._server.errorString()
            log_error(f"map-host: TCP listen failed: {err}")
            self.connectionFailed.emit(err)
            return False

        self._server.newConnection.connect(self._on_new_connection)
        port = self._server.serverPort()

        # Launch: `python -m app.gui.map_host.host --parent-port N`.
        # Using the module form avoids path-quoting edge cases on
        # Windows when the repo sits under "Program Files" or similar.
        args = f'-m app.gui.map_host.host --parent-port {port}'
        spawned = _spawn_unelevated(sys.executable, args)
        if not spawned:
            self._server.close()
            self.connectionFailed.emit("spawn failed")
            return False

        log_info(f"map-host: waiting for child on 127.0.0.1:{port}")
        return True

    def stop(self) -> None:
        """Ask the child to quit and tear down the listener."""
        try:
            self.quit()
        except Exception:
            pass
        try:
            if self._sock is not None:
                self._sock.disconnectFromHost()
        except Exception:
            pass
        try:
            self._server.close()
        except Exception:
            pass

    @property
    def hwnd(self) -> Optional[int]:
        return self._hwnd

    # ── Socket handling ─────────────────────────────────────────

    def _on_new_connection(self) -> None:
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        # Only accept one child.
        self._server.close()
        self._sock = sock
        sock.readyRead.connect(self._on_ready)
        sock.disconnected.connect(self._on_disconnected)
        log_info("map-host: child connected")

    def _on_ready(self) -> None:
        if self._sock is None:
            return
        try:
            self._buf += bytes(self._sock.readAll())
        except Exception:
            return
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                log_error(f"map-host: bad frame from child: {exc}")
                continue
            kind = msg.get("type")
            if kind == "hello":
                try:
                    hwnd = int(msg.get("hwnd", 0))
                except Exception:
                    hwnd = 0
                if hwnd:
                    self._hwnd = hwnd
                    log_info(f"map-host: child hwnd=0x{hwnd:x}")
                    self.hwndReceived.emit(hwnd)
                else:
                    self.connectionFailed.emit("child sent empty hwnd")

    def _on_disconnected(self) -> None:
        log_info("map-host: child disconnected")
        self.disconnected.emit()

    # ── Commands ────────────────────────────────────────────────

    def _send(self, obj: dict) -> None:
        if self._sock is None:
            return
        try:
            line = (json.dumps(obj) + "\n").encode("utf-8")
            self._sock.write(QByteArray(line))
            self._sock.flush()
        except Exception as exc:  # noqa: BLE001
            log_error(f"map-host: send failed: {exc}")

    def load(self, url: str) -> None:
        self._send({"type": "load", "url": url})

    def set_zoom(self, factor: float) -> None:
        self._send({"type": "zoom", "factor": factor})

    def quit(self) -> None:
        self._send({"type": "quit"})
