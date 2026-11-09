"""No renderers or network: verify the frozen browser exclusion boundary."""

import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

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
    "PyQt6/uic/widget-plugins/qtquickwidgets.py", "PyQt6/uic/widget-plugins/qtwebenginewidgets.py",
]
RASTER_FORBIDDEN = [
    "PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets", "PyQt6.QtOpenGL.child",
    r"PyQt6\QtOpenGL.pyd", "PyQt6/QtOpenGLWidgets.cp313-win_amd64.pyd",
    "QtOpenGL.pyi", "PyQt6/QtOpenGLWidgets.pyi",
    "PyQt6/bindings/QtOpenGL/QtOpenGL.toml",
    "PyQt6/bindings/QtOpenGLWidgets/arbitrary-definition.sip",
    "PyQt6/uic/widget-plugins/qtopenglwidgets.py",
    "PyQt6/Qt6/bin/Qt6OpenGL.dll", "Qt6OpenGLWidgets.dll",
    "PyQt6/Qt6/bin/opengl32sw.dll", r"unexpected\D3DCOMPILER_47.DLL",
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


@pytest.mark.parametrize("name", RASTER_FORBIDDEN)
@pytest.mark.parametrize("inner", [False, True])
def test_raster_archive_rejects_gl_payloads_in_outer_and_pyz_only_when_selected(tmp_path, name, inner):
    artifact = tmp_path / "DupeZ-GPU.exe"
    artifact.write_bytes(b"inert-not-executable")

    class Archive:
        toc = {"PYZ.pyz": (), **({} if inner else {name: ()})}

        def __init__(self, _filename):
            pass

        def open_embedded_archive(self, _name):
            return SimpleNamespace(toc={name: ()} if inner else {})

    options = dict(archive_reader_cls=Archive, release_data_names=set(), release_binary_expectations={})
    errors = release_preflight._check_frozen_dependency_policy([artifact], qt_profile="frozen-raster", **options)
    assert any("excluded frozen-raster payload" in error for error in errors)
    assert release_preflight._check_frozen_dependency_policy([artifact], **options) == []
    assert release_preflight._check_frozen_dependency_policy([artifact], qt_profile="legacy", **options) == []


def test_raster_guard_preserves_widgets_schannel_and_unrelated_uic_data():
    names = ["PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6/QtNetwork.pyi",
             "Qt6Widgets.dll", "Qt6Svg.dll", "Qt6PrintSupport.dll",
             "PyQt6/Qt6/plugins/tls/qschannelbackend.dll",
             "PyQt6/bindings/QtWidgets/qwidget.sip",
             "PyQt6/uic/widget-plugins/qaxcontainer.py",
             "PyQt6/uic/widget-plugins/qtprintsupport.py"]
    assert policy.excluded_frozen_raster_payloads(names) == []
    policy.validate_frozen_raster_payload(iter(names), qt_profile="frozen-raster")
    for name in RASTER_FORBIDDEN:
        with pytest.raises(RuntimeError, match="Excluded frozen-raster payload"):
            policy.validate_frozen_raster_payload([*names, name], qt_profile="frozen-raster")
        policy.validate_frozen_raster_payload([*names, name], qt_profile="legacy")


@pytest.mark.parametrize("configured", [None, "legacy", "frozen-raster", "", "Legacy", "frozen-raster ", "unexpected"])
def test_build_profile_is_explicit_and_unknown_values_fail_closed(monkeypatch, configured):
    if configured is None:
        monkeypatch.delenv("DUPEZ_QT_BUILD_PROFILE", raising=False)
        assert policy.configured_qt_build_profile() == "legacy"
    elif configured in {"legacy", "frozen-raster"}:
        monkeypatch.setenv("DUPEZ_QT_BUILD_PROFILE", configured)
        assert policy.configured_qt_build_profile() == configured
    else:
        monkeypatch.setenv("DUPEZ_QT_BUILD_PROFILE", configured)
        with pytest.raises(ValueError, match="Unknown Qt build profile"):
            policy.configured_qt_build_profile()


def _build_function_namespace(analysis, events):
    tree = ast.parse((ROOT / "packaging/build_common.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_variant")
    namespace = {
        "configured_qt_build_profile": policy.configured_qt_build_profile,
        "validate_frozen_raster_payload": policy.validate_frozen_raster_payload,
        "FROZEN_RASTER_EXCLUDES": policy.FROZEN_RASTER_EXCLUDES,
        "_configure_build_analysis_state": lambda: events.append("configure"),
        "configure_windows_analysis_environment": lambda: "system",
        "_write_build_default": lambda _variant: events.append("write-default"),
        "_binaries": lambda: [], "_datas": lambda: [], "_hidden_imports": lambda: [],
        "_excludes": lambda: list(policy.FROZEN_BROWSER_EXCLUDES),
        "os": os, "ROOT": str(ROOT), "HERE": str(ROOT / "packaging"),
        "BLOCK_CIPHER": None, "Analysis": analysis,
        "_filter_root_binary_duplicates": lambda _entries: pytest.fail("TOC cleanup preceded raster rejection"),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "build-variant", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("variant", ["gpu", "compat"])
@pytest.mark.parametrize("section,name", [
    ("binaries", "opengl32sw.dll"),
    ("datas", "PyQt6/bindings/QtOpenGLWidgets/arbitrary.sip"),
    ("pure", "PyQt6.QtOpenGL"),
])
def test_raster_build_rejects_all_collected_sections_before_cleanup(monkeypatch, variant, section, name):
    monkeypatch.setenv("DUPEZ_QT_BUILD_PROFILE", "frozen-raster")
    events, captured = [], {}
    toc = SimpleNamespace(binaries=[], datas=[], pure=[])
    getattr(toc, section).append((name, "inert-source", "DATA"))

    def analyze(*_args, **kwargs):
        captured.update(kwargs)
        return toc

    namespace = _build_function_namespace(analyze, events)
    with pytest.raises(RuntimeError, match="Excluded frozen-raster payload"):
        namespace["build_variant"](variant, "DupeZ", "inert.manifest", variant == "compat")
    assert set(policy.FROZEN_RASTER_EXCLUDES) <= set(captured["excludes"])
    assert set(policy.FROZEN_BROWSER_EXCLUDES) <= set(captured["excludes"])
    assert getattr(toc, section) == [(name, "inert-source", "DATA")]


def test_unknown_profile_stops_build_before_state_or_default_mutation(monkeypatch):
    monkeypatch.setenv("DUPEZ_QT_BUILD_PROFILE", "unknown")
    events = []
    namespace = _build_function_namespace(lambda *_a, **_k: pytest.fail("Analysis ran"), events)
    with pytest.raises(ValueError, match="Unknown Qt build profile"):
        namespace["build_variant"]("gpu", "DupeZ", "inert.manifest", False)
    assert events == []


def test_final_archive_unknown_profile_fails_before_archive_access():
    errors = release_preflight._check_frozen_dependency_policy(
        [ROOT / "does-not-exist.exe"], qt_profile="unexpected",
        archive_reader_cls=lambda _path: pytest.fail("Archive was opened"),
        release_data_names=set(), release_binary_expectations={},
    )
    assert errors == ["Unknown Qt build profile; expected legacy or frozen-raster"]


@pytest.mark.parametrize("profile", [None, "legacy", "frozen-raster"])
def test_cli_passes_explicit_profile_without_reading_build_environment(monkeypatch, profile):
    captured = {}
    monkeypatch.setenv("DUPEZ_QT_BUILD_PROFILE", "frozen-raster")
    argv = ["release_preflight.py", "--frozen-artifact", "inert.exe"]
    if profile is not None:
        argv.extend(["--qt-profile", profile])
    monkeypatch.setattr(sys, "argv", argv)

    def inspect(artifacts, **kwargs):
        captured.update(kwargs)
        assert artifacts == [Path("inert.exe")]
        return []

    monkeypatch.setattr(release_preflight, "_check_frozen_dependency_policy", inspect)
    assert release_preflight.main() == 0
    assert captured["qt_profile"] == (profile or "legacy")


@pytest.mark.parametrize("argv", [
    ["--qt-profile", "frozen-raster"],
    ["--dist", "--qt-profile", "frozen-raster"],
    ["--frozen-artifact", "inert.exe", "--qt-profile", "unknown"],
])
def test_raster_cli_cannot_silently_change_default_release_gates(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["release_preflight.py", *argv])
    monkeypatch.setattr(release_preflight, "check_source", lambda *_a: pytest.fail("source gate reached"))
    with pytest.raises(SystemExit) as caught:
        release_preflight.main()
    assert caught.value.code == 2


def test_uic_data_exclusion_is_exact_and_other_browser_payload_still_fails():
    rows = [
        ("PyQt6/uic/widget-plugins/qtquickwidgets.py", "wheel/qtquickwidgets.py", "DATA"),
        ("PyQt6/uic/widget-plugins/qtwebenginewidgets.py", "wheel/qtwebenginewidgets.py", "DATA"),
        ("PyQt6/uic/widget-plugins/qtprintsupport.py", "wheel/qtprintsupport.py", "DATA"),
        ("PyQt6/Qt6/bin/Qt6WebEngineCore.dll", "unexpected/browser.dll", "BINARY"),
    ]
    result = policy.without_disabled_browser_uic_plugins(rows)
    assert result == rows[2:]
    with pytest.raises(RuntimeError, match="Excluded embedded browser/QML payload"):
        policy.validate_no_embedded_browser_payload(entry[0] for entry in result)


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
widget.show()
app.processEvents()
widget.load_map("Livonia")
widget._open_in_browser()
assert "https://izurvive.com/livonia" in widget._security_placeholder.text()
assert "omits the embedded browser runtime" in widget._security_placeholder.text()
assert widget.browser_btn.text() == "Manual browser URL"
assert widget.map_view is None and widget.webengine_ready is False
assert widget.webengine_status == "unavailable"
assert widget.manual_url_ready is True
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
