"""Minimal QtWebEngine smoke test — bypasses DupeZ entirely.

Opens a bare QWebEngineView pointed at iZurvive. Prints every load
event and any render-process crash so we can tell exactly where the
map is failing: import, network, Cloudflare, or GPU/sandbox.

Run:
    python test_webengine.py
"""
from __future__ import annotations

import os
import sys

# Force software rendering + no sandbox BEFORE Qt imports. Fixes ~80%
# of blank-webengine cases on Windows under admin tokens.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --disable-gpu-compositing")
os.environ.setdefault("QT_OPENGL", "software")

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QMainWindow

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage
    print("[OK] QtWebEngine imported")
except Exception as exc:
    print(f"[FAIL] QtWebEngine import: {type(exc).__name__}: {exc}")
    sys.exit(1)


class LoggingPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, msg, line, source):
        print(f"[js] {source}:{line} {msg}")

    def certificateError(self, error):
        print(f"[cert] {error.description()}")
        return True  # ignore cert errors for the test


def main() -> int:
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("DupeZ WebEngine smoke test")
    win.resize(1280, 800)

    view = QWebEngineView()
    view.setPage(LoggingPage(view))

    def on_load_started():
        print("[load] started")

    def on_load_progress(p):
        print(f"[load] progress {p}%")

    def on_load_finished(ok):
        print(f"[load] finished ok={ok}")
        if not ok:
            print("[load] -> page did not load. Likely Cloudflare/DNS/sandbox.")

    def on_render_process_terminated(status, code):
        print(f"[renderer] terminated status={status} exit={code}")

    view.loadStarted.connect(on_load_started)
    view.loadProgress.connect(on_load_progress)
    view.loadFinished.connect(on_load_finished)
    view.page().renderProcessTerminated.connect(on_render_process_terminated)

    url = "https://www.izurvive.com/"
    print(f"[test] navigating to {url}")
    view.load(QUrl(url))

    win.setCentralWidget(view)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
