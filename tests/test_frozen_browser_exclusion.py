"""No renderers or network: verify the frozen browser exclusion boundary."""

import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import release_preflight

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("browser_payload_policy", ROOT / "packaging/native_runtime_policy.py")
policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy)

FORBIDDEN = [
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebChannel", "PyQt6.QtQml", "PyQt6.QtQuickWidgets",
    r"PyQt6\QtWebEngineWidgets.pyd", "QtQml.pyd", "QtQuick.pyd", "QtWebChannel.pyd",
    "PyQt6/Qt6/bin/Qt6WebEngineCore.dll", "Qt6WebChannel.dll", "Qt6QmlModels.dll",
    "Qt6QuickControls2.dll", "PyQt6/Qt6/bin/QtWebEngineProcess.exe",
    "PyQt6/Qt6/resources/qtwebengine_resources.pak", "PyQt6/Qt6/resources/icudtl.dat",
    "v8_context_snapshot.bin", "PyQt6/Qt6/translations/qtwebengine_locales/en-US.pak",
    "PyQt6/Qt6/qml/QtQuick/Controls/qmldir", "PyQt6/Qt6/plugins/qmltooling/plugin.dll",
    "ordinary.qml", "plugins.qmltypes", "app.gui.map_host.host", "app.gui.map_host.request_policy",
]


@pytest.mark.parametrize("name", FORBIDDEN)
@pytest.mark.parametrize("inner", [False, True])
def test_final_archive_rejects_browser_native_modules_resources_and_qml(tmp_path, name, inner):
    artifact = tmp_path / "DupeZ-Compat.exe"
    artifact.write_bytes(b"inert-not-executable")

    class Archive:
        toc = {"PYZ.pyz": (), **({} if inner else {name: ()})}

        def __init__(self, _filename):
            pass

        def open_embedded_archive(self, _name):
            return type("Embedded", (), {"toc": {name: ()} if inner else {}})()

    errors = release_preflight._check_frozen_dependency_policy(
        [artifact], archive_reader_cls=Archive, release_data_names=set(), release_binary_expectations={},
    )
    assert any("excluded embedded browser/QML payload" in error for error in errors)


def test_build_collection_rejects_browser_data_and_preserves_widgets_and_schannel():
    safe = ["PyQt6.QtWidgets", "PyQt6.QtNetwork", "Qt6Core.dll", "Qt6Gui.dll",
            "Qt6Widgets.dll", "Qt6Network.dll", "Qt6Svg.dll",
            "PyQt6/Qt6/plugins/tls/qschannelbackend.dll", "app.gui.map_host.security_policy",
            "app.gui.dayz_map_gui_new", "app/resources/dupez.ico"]
    assert policy.excluded_browser_payloads(safe) == []
    policy.validate_no_embedded_browser_payload(safe)
    with pytest.raises(RuntimeError, match="Excluded embedded browser/QML payload"):
        policy.validate_no_embedded_browser_payload([*safe, "ordinary.qml"])


def test_both_builds_share_explicit_exclusions_and_no_required_webengine_import():
    tree = ast.parse((ROOT / "packaging/build_common.py").read_text(encoding="utf-8"))
    methods = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"_hidden_imports", "_excludes"}]
    ns = {"FROZEN_BROWSER_EXCLUDES": policy.FROZEN_BROWSER_EXCLUDES,
          "collect_submodules": lambda package, filter: [name for name in ["app.gui.map_host.host", "app.gui.lazy_dayz_map"] if filter(name)]}
    exec(compile(ast.Module(body=methods, type_ignores=[]), "build-functions", "exec"), ns)
    assert set(policy.FROZEN_BROWSER_EXCLUDES) <= set(ns["_excludes"]())
    assert set(policy.FROZEN_BROWSER_EXCLUDES).isdisjoint(ns["_hidden_imports"]())
    assert "app.gui.lazy_dayz_map" in ns["_hidden_imports"]()
    assert release_preflight._check_native_collection_policy() == []
    launcher = ast.parse((ROOT / "dupez.py").read_text(encoding="utf-8"))
    verifier = next(node for node in launcher.body if isinstance(node, ast.FunctionDef) and node.name == "_verify_runtime_imports")
    assert "QtNetwork" in ast.unparse(verifier)
    assert "QtWebEngine" not in ast.unparse(verifier)


def test_manual_map_catalogue_survives_missing_browser_modules_in_frozen_context(tmp_path):
    script = r'''
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
blocked = []
class MissingBrowser(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("PyQt6.QtWebEngine", "PyQt6.QtWebChannel", "PyQt6.QtQml", "PyQt6.QtQuick")):
            blocked.append(fullname)
            raise ImportError("Browser runtime deliberately absent")
sys.meta_path.insert(0, MissingBrowser())
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QDesktopServices
from app.gui.dayz_map_gui_new import DayZMapGUI
sys.frozen = True
def external(url):
    raise AssertionError("manual fallback must not invoke browser handlers")
QDesktopServices.openUrl = external
app = QApplication([])
widget = DayZMapGUI()
widget.load_map("Livonia")
widget._open_in_browser()
assert "https://izurvive.com/livonia" in widget._security_placeholder.text()
assert "omits the embedded browser runtime" in widget._security_placeholder.text()
assert widget.browser_btn.text() == "Manual browser URL"
assert widget.map_view is None and widget.webengine_ready is False
assert widget.webengine_status == "unavailable"
assert blocked
assert not any(name.startswith("PyQt6.QtWebEngine") for name in sys.modules)
print("manual catalogue works without embedded browser bytes")
'''
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script, str(ROOT)], cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "DUPEZ_USER_ROOT": str(tmp_path / "user"),
             "DUPEZ_FORCE_USER_DATA": "1"},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "manual catalogue works without embedded browser bytes" in completed.stdout
