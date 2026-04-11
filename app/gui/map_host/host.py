#!/usr/bin/env python3
# app/gui/map_host/host.py — Unelevated iZurvive WebEngine child.
"""DupeZ map host — standalone Chromium process for embedding.

Launched via Explorer COM ``ShellExecute`` from the elevated DupeZ
main process. Because ``ShellExecute`` routes through Explorer, this
child inherits Explorer's medium-integrity token instead of the
parent's admin token, so Chromium's GPU process actually starts and
iZurvive runs with real hardware acceleration.

Protocol (line-delimited JSON over loopback TCP):
    child → parent : {"type":"hello","hwnd":<int>}
    parent → child : {"type":"load","url":"..."}
    parent → child : {"type":"zoom","factor":<float>}
    parent → child : {"type":"quit"}

``hwnd`` is the native window handle (``int(QMainWindow.winId())``).
The parent wraps it with ``QWindow.fromWinId`` +
``QWidget.createWindowContainer`` to reparent the native window into
the DupeZ main layout.

This file is intentionally self-contained so it can be launched
as ``python -m app.gui.map_host.host`` or as a standalone script. It
only imports PyQt6 (no DupeZ internals) so a reduced import graph
keeps child startup fast.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

from PyQt6.QtCore import QByteArray, QUrl, Qt
from PyQt6.QtNetwork import QTcpSocket
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow


# ── Host window ─────────────────────────────────────────────────────


class MapHostWindow(QMainWindow):
    """Frameless top-level window hosting a single ``QWebEngineView``.

    The parent DupeZ process reparents this window's native HWND into
    its own layout via ``SetParent`` / ``QWindow.fromWinId``, so the
    window must be *shown* before the parent receives the ``hello``
    message (otherwise ``winId()`` returns a handle whose underlying
    native window hasn't been created yet).
    """

    def __init__(self, parent_port: int) -> None:
        # Frameless + no system menu: the window is going to be
        # reparented into a QWidget container, where the native frame
        # would otherwise show up as ugly chrome.
        super().__init__(flags=Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("DupeZ Map Host")
        # Initial size is irrelevant — parent resizes the container.
        self.resize(1280, 720)

        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)

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

        # Show first so winId() materializes a real native HWND.
        self.show()

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
        self._send({"type": "hello", "hwnd": hwnd})
        sys.stderr.write(f"map-host: hello sent hwnd=0x{hwnd:x}\n")

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
            self._dispatch(msg)

    def _on_disconnected(self) -> None:
        sys.stderr.write("map-host: parent disconnected — quitting\n")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ── Command dispatch ────────────────────────────────────────

    def _dispatch(self, msg: Dict[str, Any]) -> None:
        kind: Optional[str] = msg.get("type")
        if kind == "load":
            url = str(msg.get("url", "")).strip()
            if url:
                self.view.load(QUrl(url))
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


# ── Entry point ─────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(prog="dupez-map-host")
    ap.add_argument(
        "--parent-port",
        type=int,
        required=True,
        help="Loopback TCP port the parent DupeZ process is listening on",
    )
    args = ap.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    _ = MapHostWindow(args.parent_port)  # keep alive via app ownership
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
