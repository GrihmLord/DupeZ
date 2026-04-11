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

from app.logs.logger import log_error, log_info, log_warning


# Resolve the child script path once at import time.
_HOST_SCRIPT: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "host.py"
)


# ── Win32 HWND reparenting ──────────────────────────────────────────


def reparent_hwnd_into_container(
    child_hwnd: int,
    parent_hwnd: int,
    width: int,
    height: int,
) -> bool:
    """Embed a foreign top-level HWND inside a parent HWND (Windows).

    Qt's ``QWindow.fromWinId`` + ``createWindowContainer`` path is
    unreliable for foreign HWNDs from another process: it creates a
    Qt-side container widget but does not always call the Win32
    ``SetParent`` that actually moves the native window into our
    client area. The result is that the child's frameless QMainWindow
    stays a floating top-level and covers the screen.

    This helper does the reparent the Windows-native way:

    1. Strip top-level window styles (WS_POPUP / WS_CAPTION /
       WS_THICKFRAME / WS_SYSMENU) and add WS_CHILD.
    2. Call ``SetParent`` to move the HWND under the container.
    3. Call ``SetWindowPos`` with SWP_FRAMECHANGED so the new style
       takes effect.
    4. ``ShowWindow(SW_SHOW)`` so the now-child HWND is visible
       inside the container's client area.

    Returns True on success. Non-Windows platforms return False.
    """
    if sys.platform != "win32":
        return False

    try:
        import ctypes

        user32 = ctypes.windll.user32

        # Windows style bits
        GWL_STYLE = -16
        WS_CHILD = 0x40000000
        WS_POPUP = 0x80000000
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_SYSMENU = 0x00080000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000

        # SetWindowPos flags
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        SWP_NOACTIVATE = 0x0010

        # ShowWindow
        SW_SHOW = 5

        # Pick the 64/32-bit GetWindowLongPtr variant
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            get_long = user32.GetWindowLongPtrW
            set_long = user32.SetWindowLongPtrW
            get_long.restype = ctypes.c_ssize_t
            set_long.restype = ctypes.c_ssize_t
            get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        else:
            get_long = user32.GetWindowLongW
            set_long = user32.SetWindowLongW
            get_long.restype = ctypes.c_long
            set_long.restype = ctypes.c_long
            get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]

        child = ctypes.c_void_p(child_hwnd)
        parent = ctypes.c_void_p(parent_hwnd)

        # 1. Fix up window style
        style = get_long(child, GWL_STYLE)
        style &= ~(
            WS_POPUP
            | WS_CAPTION
            | WS_THICKFRAME
            | WS_SYSMENU
            | WS_MINIMIZEBOX
            | WS_MAXIMIZEBOX
        )
        style |= WS_CHILD
        set_long(child, GWL_STYLE, style)

        # 2. SetParent — move the native HWND into container's client area
        prev_parent = user32.SetParent(child, parent)
        if prev_parent == 0:
            err = ctypes.windll.kernel32.GetLastError()
            log_error(f"map-host: SetParent failed, GetLastError={err}")
            return False

        # 3. Apply style change + resize to container size
        user32.SetWindowPos(
            child,
            0,
            0,
            0,
            int(width),
            int(height),
            SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE,
        )

        # 4. Show the now-child HWND inside its new parent
        user32.ShowWindow(child, SW_SHOW)

        log_info(
            f"map-host: reparented hwnd=0x{child_hwnd:x} into "
            f"parent=0x{parent_hwnd:x} at {width}x{height}"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log_error(f"map-host: reparent_hwnd_into_container failed: {exc!r}")
        return False


def resize_child_hwnd(child_hwnd: int, width: int, height: int) -> None:
    """Resize an embedded child HWND to match its container (Windows)."""
    if sys.platform != "win32" or not child_hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # MoveWindow(hWnd, X, Y, nWidth, nHeight, bRepaint)
        user32.MoveWindow(
            ctypes.c_void_p(child_hwnd),
            0,
            0,
            int(width),
            int(height),
            True,
        )
    except Exception as exc:  # noqa: BLE001
        log_warning(f"map-host: resize_child_hwnd failed: {exc!r}")


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


# ── Prewarm singleton ───────────────────────────────────────────────
#
# DayZMapGUI is created eagerly by the dashboard when the main window
# builds, but that happens *after* the splash pipeline finishes — so
# the map host spawn and iZurvive load time are both on the critical
# path before the user sees the map. prewarm_map_host() spins the
# client up during the splash pipeline, on the main thread, so that
# Chromium, the child process, and the initial tile load all happen
# in parallel with the rest of DupeZ's boot. When DayZMapGUI is
# finally constructed it consumes the prewarmed client instead of
# starting a fresh one.

_PREWARMED_CLIENT: Optional[MapHostClient] = None


def prewarm_map_host(initial_url: str) -> bool:
    """Start the unelevated map host early and begin loading a map.

    Must be called on the main thread (``QTcpServer`` / ``QTcpSocket``
    are thread-affine to their owning thread, and Dashboard will want
    to adopt the client from the main thread later).

    Returns ``True`` if a prewarm was started (or was already
    running). Returns ``False`` on immediate spawn failure — callers
    should fall back to on-demand start inside DayZMapGUI.
    """
    global _PREWARMED_CLIENT
    if _PREWARMED_CLIENT is not None:
        return True

    client = MapHostClient(parent=None)

    def _on_hwnd(_hwnd: int) -> None:
        # Child is up — kick off the initial map load so tiles are
        # downloading while the user watches the splash finish.
        try:
            client.load(initial_url)
            log_info(f"map-host: prewarm load -> {initial_url}")
        except Exception as exc:  # noqa: BLE001
            log_warning(f"map-host: prewarm load failed: {exc}")

    def _on_failed(reason: str) -> None:
        global _PREWARMED_CLIENT
        log_warning(f"map-host: prewarm failed ({reason})")
        _PREWARMED_CLIENT = None

    client.hwndReceived.connect(_on_hwnd)
    client.connectionFailed.connect(_on_failed)

    if not client.start():
        log_warning("map-host: prewarm start() returned False")
        return False

    _PREWARMED_CLIENT = client
    log_info("map-host: prewarm dispatched")
    return True


def consume_prewarmed_client() -> Optional[MapHostClient]:
    """Hand off the prewarmed client to its final owner (DayZMapGUI).

    Returns ``None`` if no prewarm was active or it already failed.
    The caller becomes responsible for the client's lifecycle and
    must re-parent it (``setParent``) so Qt ownership is correct.
    """
    global _PREWARMED_CLIENT
    client = _PREWARMED_CLIENT
    _PREWARMED_CLIENT = None
    return client
