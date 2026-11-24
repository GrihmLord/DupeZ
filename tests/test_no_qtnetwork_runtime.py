"""The manual-map profile must work with its network binding genuinely absent."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_manual_map_and_child_rejection_do_not_import_qt_network(tmp_path):
    script = r'''
import importlib.abc
import sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
network_attempts = []
class MissingOptionalQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PyQt6.QtNetwork":
            network_attempts.append(fullname)
            raise ImportError("QtNetwork deliberately absent")
        if fullname.startswith(("PyQt6.QtWebEngine", "PyQt6.QtWebChannel", "PyQt6.QtQml", "PyQt6.QtQuick")):
            raise ImportError("Browser runtime deliberately absent")
sys.meta_path.insert(0, MissingOptionalQt())
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QDesktopServices
from app.gui.dayz_map_gui_new import DayZMapGUI
from app.gui.map_host.launcher import MapHostClient
sys.modules["app.firewall_helper._build_default"] = SimpleNamespace(
    _BUILD_DEFAULT_ARCH="split", _BUILD_QT_PROFILE="frozen-raster-no-qtnetwork",
)
sys.frozen = True
def external(url):
    raise AssertionError("manual fallback must not invoke browser handlers")
QDesktopServices.openUrl = external
app = QApplication(["manual-map-test"])
widget = DayZMapGUI()
widget.show()
app.processEvents()
widget.load_map("Livonia")
widget._open_in_browser()
assert "https://izurvive.com/livonia" in widget._security_placeholder.text()
assert widget.browser_btn.text() == "Manual browser URL"
assert widget.map_view is None and widget.webengine_ready is False
assert widget.webengine_status == "unavailable" and widget.manual_url_ready is True
try:
    MapHostClient()
except RuntimeError as error:
    assert "excluded from the QtNetwork-free profile" in str(error)
else:
    raise AssertionError("excluded child client was constructed")
assert network_attempts == [], network_attempts
assert "PyQt6.QtNetwork" not in sys.modules
widget.close()
print("manual map works without QtNetwork; child client refused before import")
'''
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script, str(ROOT)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
             "DUPEZ_USER_ROOT": str(tmp_path / "user"), "DUPEZ_FORCE_USER_DATA": "1",
             "DUPEZ_QT_BUILD_PROFILE": "legacy"},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "manual map works without QtNetwork" in completed.stdout
