"""Subprocess GUI smoke test with the explicit WebEngine safe fallback."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_dashboard_constructs_and_shuts_down_offscreen(tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update({
        "QT_QPA_PLATFORM": "offscreen",
        "DUPEZ_DISABLE_WEBENGINE": "1",
        "DUPEZ_ARCH": "inproc",
        "DUPEZ_FORCE_USER_DATA": "1",
        "DUPEZ_USER_ROOT": str(tmp_path / "runtime"),
    })
    script = """
from PyQt6.QtWidgets import QApplication
from app.core.controller import AppController
from app.core.safety_policy import SafetyPolicy
from app.gui.dashboard import DupeZDashboard
from app.gui.panels import voice_panel

voice_panel._probe_voice_available = lambda: (_ for _ in ()).throw(
    AssertionError("dashboard construction must not probe optional voice dependencies")
)

app = QApplication([])
controller = AppController(safety_policy=SafetyPolicy(dry_run=True))
window = DupeZDashboard(controller=controller)
assert window.map_view.map_view is None
app.processEvents()
window._force_quit = True
window.close()
app.processEvents()
print("DASHBOARD_SMOKE_OK")
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, (
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )
    assert "DASHBOARD_SMOKE_OK" in result.stdout
