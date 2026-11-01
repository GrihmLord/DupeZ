#!/usr/bin/env python3
# app/gui/map_host/host.py — Unelevated iZurvive WebEngine child.
"""DupeZ map host — standalone Chromium process for embedding.

Launched from the elevated DupeZ main process with the interactive
shell's verified non-elevated token, so Chromium's GPU process actually
starts and iZurvive runs with real hardware acceleration.

Protocol (line-delimited JSON over loopback TCP):
    child → parent : {"type":"hello","session_nonce":"...",
                      "pid":<int>,"hwnd":<int>}
    parent → child : {"type":"load","url":"..."}
    parent → child : {"type":"zoom","factor":<float>}
    parent → child : {"type":"quit"}
    child → parent : {"type":"load-started"}
    child → parent : {"type":"load-finished","ok":<bool>}
    child → parent : {"type":"renderer-terminated",...}

``session_nonce`` is the parent's per-launch 32-byte random challenge.
The parent checks it in constant time, then requires ``pid`` to equal
the PID returned by process creation and confirms on Windows that
``hwnd`` has that same owner before exposing the handle for reparenting.

This file is intentionally narrow so it can be launched as
``python -m app.gui.map_host.host``. Besides PyQt6 it imports only the shared
map request policy, keeping child startup and its trust surface small.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from PyQt6.QtCore import QByteArray, QCoreApplication, QUrl, Qt
from PyQt6.QtNetwork import QTcpSocket
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow

from app.gui.map_host.request_policy import (
    install_reviewed_page,
    is_reviewed_map_url,
)
from app.gui.map_host.security_policy import assess_webengine_security


# ── Host window ─────────────────────────────────────────────────────


class MapHostWindow(QMainWindow):
    """Frameless top-level window hosting a single ``QWebEngineView``.

    The parent DupeZ process reparents this window's native HWND into
    its own layout via ``SetParent`` / ``QWindow.fromWinId``, so the
    window must be *shown* before the parent receives the ``hello``
    message (otherwise ``winId()`` returns a handle whose underlying
    native window hasn't been created yet).
    """

    def __init__(self, parent_port: int, session_nonce: str) -> None:
        # Frameless + no system menu: the window is about to be
        # reparented into a QWidget container via Win32 SetParent, so
        # we don't want any native chrome to flash on screen first.
        super().__init__(flags=Qt.WindowType.FramelessWindowHint)
        assessment = assess_webengine_security()
        if not assessment.allowed:
            raise RuntimeError(assessment.reason)
        self._security_blocked = False
        self.setWindowTitle("DupeZ Map Host")
        # Initial size doesn't matter — the parent will MoveWindow us
        # to match its container as soon as reparenting completes.
        self.resize(1, 1)

        self.view = QWebEngineView(self)
        self._secured_page = install_reviewed_page(self.view)
        self.setCentralWidget(self.view)

        # The profile does not own its interceptor. Keep a child-owned strong
        # reference for the entire browser lifetime and fail before connecting
        # to the parent if the privacy boundary cannot be installed.
        self._interceptor = self._secured_page._dupez_interceptor

        # Minimal perf settings — child runs with real GPU so we do
        # NOT need the aggressive software-raster tuning the in-proc
        # path applies. Just turn off the noisy defaults.
        try:
            s = self.view.settings()
            A = QWebEngineSettings.WebAttribute
            s.setAttribute(A.PluginsEnabled, False)
            s.setAttribute(A.HyperlinkAuditingEnabled, False)
            s.setAttribute(A.AutoLoadIconsForPage, False)
            s.setAttribute(A.LocalStorageEnabled, True)
            s.setAttribute(A.JavascriptEnabled, True)
            s.setAttribute(A.ErrorPageEnabled, False)
        except Exception:
            pass

        # CRITICAL: do NOT call self.show(). We need the native HWND
        # to exist (so winId() is valid and SetParent has something
        # to reparent), but we must NOT present it as a top-level
        # window — otherwise it flashes as a frameless floating
        # window before the parent reparents it, and on a prior
        # launch it got stuck covering the entire screen.
        #
        # WA_NativeWindow + create() forces Qt to allocate the
        # underlying native window without calling ShowWindow. The
        # parent process will ShowWindow() it after SetParent moves
        # it into the container's client area.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        # Position far off-screen as a belt-and-suspenders in case
        # some Windows configuration still presents the native window
        # before SetParent completes.
        self.move(-32000, -32000)
        self.create()

        self._buf: bytes = b""
        self.sock: QTcpSocket = QTcpSocket(self)
        self.sock.readyRead.connect(self._on_ready)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.connectToHost("127.0.0.1", parent_port)
        if not self.sock.waitForConnected(5000):
            sys.stderr.write(
                f"map-host: connect to parent failed: {self.sock.errorString()}\n"
            )
            sys.exit(2)

        hwnd = int(self.winId())
        pid = os.getpid()
        self._send({
            "type": "hello",
            "session_nonce": session_nonce,
            "pid": pid,
            "hwnd": hwnd,
        })
        sys.stderr.write(
            f"map-host: hello sent pid={pid} hwnd=0x{hwnd:x}\n"
        )
        self.view.loadStarted.connect(self._on_load_started)
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.page().renderProcessTerminated.connect(
            self._on_render_process_terminated
        )

    # ── Socket plumbing ─────────────────────────────────────────

    def _send(self, obj: Dict[str, Any]) -> None:
        try:
            line = (json.dumps(obj) + "\n").encode("utf-8")
            self.sock.write(QByteArray(line))
            self.sock.flush()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"map-host: send failed: {exc}\n")

    def _on_ready(self) -> None:
        try:
            self._buf += bytes(self.sock.readAll())
        except Exception:
            return
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"map-host: bad frame: {exc}\n")
                continue
            if not isinstance(msg, dict):
                sys.stderr.write("map-host: rejected non-object frame\n")
                continue
            self._dispatch(msg)

    def _on_disconnected(self) -> None:
        sys.stderr.write("map-host: parent disconnected — quitting\n")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ── Command dispatch ────────────────────────────────────────

    def _admit_remote_content(self) -> bool:
        if getattr(self, "_security_blocked", False):
            return False
        try:
            if assess_webengine_security().allowed:
                return True
        except Exception:
            pass
        self._security_blocked = True
        # Stop alone does not terminate an already-loaded page's JavaScript.
        # Retire the view and never reuse this host after a security denial.
        for operation in ("stop", "hide", "deleteLater"):
            try:
                getattr(self.view, operation)()
            except Exception:
                sys.stderr.write("map-host: blocked view cleanup incomplete\n")
        return False

    def _dispatch(self, msg: Dict[str, Any]) -> None:
        kind: Optional[str] = msg.get("type")
        if kind == "load":
            url = str(msg.get("url", "")).strip()
            if is_reviewed_map_url(url) and self._admit_remote_content():
                self.view.load(QUrl(url))
            else:
                sys.stderr.write("map-host: rejected unreviewed map URL\n")
                self._send({"type": "load-finished", "ok": False})
        elif kind == "zoom":
            try:
                self.view.setZoomFactor(float(msg.get("factor", 1.0)))
            except Exception:
                pass
        elif kind == "quit":
            app = QApplication.instance()
            if app is not None:
                app.quit()
        else:
            sys.stderr.write(f"map-host: unknown cmd {kind!r}\n")

    def _on_load_started(self) -> None:
        if self._admit_remote_content():
            self._send({"type": "load-started"})
        else:
            self._send({"type": "load-finished", "ok": False})

    def _on_load_finished(self, ok: bool) -> None:
        self._send({"type": "load-finished", "ok": bool(ok) and self._admit_remote_content()})

    def _on_render_process_terminated(
        self,
        termination_status: Any,
        exit_code: int,
    ) -> None:
        status = getattr(termination_status, "name", "unknown")
        self._send({
            "type": "renderer-terminated",
            "status": str(status)[:64],
            "exit_code": int(exit_code),
        })


# ── Entry point ─────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(prog="dupez-map-host")
    ap.add_argument(
        "--parent-port",
        type=int,
        required=True,
        help="Loopback TCP port the parent DupeZ process is listening on",
    )
    ap.add_argument(
        "--session-nonce",
        required=True,
        help=argparse.SUPPRESS,
    )
    args = ap.parse_args()

    qt_argv = list(sys.argv)
    if not qt_argv:
        qt_argv = [os.path.abspath(sys.executable or "dupez-map-host")]
    elif not qt_argv[0].strip():
        qt_argv[0] = os.path.abspath(sys.executable or "dupez-map-host")
    QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts,
        True,
    )
    app = QApplication(qt_argv)
    app.setQuitOnLastWindowClosed(True)
    _ = MapHostWindow(
        args.parent_port,
        args.session_nonce,
    )  # keep alive via app ownership
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
