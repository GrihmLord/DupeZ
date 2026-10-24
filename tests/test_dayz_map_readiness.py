from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from app.gui import dayz_map_gui_new as map_module


@pytest.fixture(autouse=True)
def reviewed_runtime(monkeypatch):
    monkeypatch.setattr(map_module, "assess_webengine_security", lambda: SimpleNamespace(allowed=True, reason=""))


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(["dupez-map-state-tests"])


def _placeholder_map(monkeypatch, qapp: QApplication):
    monkeypatch.setattr(map_module, "_WEBENGINE_AVAILABLE", False)
    widget = map_module.DayZMapGUI()
    assert widget.webengine_status == "unavailable"
    return widget


def test_readiness_tracks_load_success_failure_and_renderer_crash(
    monkeypatch,
    qapp: QApplication,
) -> None:
    widget = _placeholder_map(monkeypatch, qapp)
    states: list[str] = []
    widget.webengineStatusChanged.connect(states.append)

    widget._on_inproc_load_started()
    assert widget.webengine_status == "loading"
    assert widget.webengine_ready is False

    widget._on_inproc_load_finished(True)
    assert widget.webengine_status == "ready"
    assert widget.webengine_ready is True

    widget._on_inproc_load_finished(False)
    assert widget.webengine_status == "failed"
    assert widget.webengine_ready is False

    class _Status:
        name = "CrashedTerminationStatus"

    widget._on_render_process_terminated(_Status(), -1)
    assert widget.webengine_status == "crashed"
    assert states == ["loading", "ready", "failed", "crashed"]
    widget.deleteLater()


def test_hardware_tier_keeps_webgl_canvas_and_native_zoom(
    monkeypatch,
    qapp: QApplication,
) -> None:
    widget = _placeholder_map(monkeypatch, qapp)

    class _Settings:
        def __init__(self) -> None:
            self.calls: list[tuple[object, bool]] = []

        def setAttribute(self, attribute, value: bool) -> None:  # noqa: N802
            self.calls.append((attribute, value))

    class _View:
        def __init__(self) -> None:
            self.settings_object = _Settings()
            self.zooms: list[float] = []

        def settings(self):
            return self.settings_object

        def setZoomFactor(self, factor: float) -> None:  # noqa: N802
            self.zooms.append(factor)

    view = _View()
    widget.map_view = view
    monkeypatch.setenv("DUPEZ_MAP_RENDERER_TIER", "tier1_hw")

    widget._apply_perf_settings()

    attributes = {attribute for attribute, _value in view.settings_object.calls}
    web = map_module.QWebEngineSettings.WebAttribute
    assert web.PluginsEnabled in attributes
    assert web.WebGLEnabled not in attributes
    assert web.Accelerated2dCanvasEnabled not in attributes
    assert view.zooms == []
    widget.deleteLater()
