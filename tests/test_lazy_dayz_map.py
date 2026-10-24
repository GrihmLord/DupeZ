from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from app.gui.lazy_dayz_map import LazyDayZMapGUI
from app.gui import lazy_dayz_map as lazy_module


@pytest.fixture(autouse=True)
def reviewed_runtime(monkeypatch):
    monkeypatch.setattr(lazy_module, "assess_webengine_security", lambda: SimpleNamespace(allowed=True, reason=""))


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication(["dupez-lazy-map-tests"])
    return app


def test_map_factory_is_deferred_until_requested(qapp: QApplication) -> None:
    calls: list[int] = []

    def factory() -> QWidget:
        calls.append(1)
        return QLabel("map-ready")

    lazy = LazyDayZMapGUI(map_factory=factory)

    assert calls == []
    assert lazy.is_loaded is False
    assert lazy.webengine_status == "deferred"

    assert lazy.load_now() is True
    assert calls == [1]
    assert lazy.is_loaded is True
    assert lazy.webengine_ready is False

    # Repeated tab activations must not create another Chromium instance.
    assert lazy.load_now() is True
    assert calls == [1]

    lazy.deleteLater()
    qapp.processEvents()


def test_ready_state_delegates_to_loaded_map(qapp: QApplication) -> None:
    class ReadyMap(QWidget):
        webengine_ready = True

    lazy = LazyDayZMapGUI(map_factory=ReadyMap)

    assert lazy.webengine_ready is False
    assert lazy.load_now() is True
    assert lazy.webengine_ready is True
    assert lazy.webengine_status == "ready"

    lazy.deleteLater()
    qapp.processEvents()


def test_failed_initialization_can_retry_without_restart(qapp: QApplication) -> None:
    attempts: list[str] = []

    def failing_factory() -> QWidget:
        attempts.append("failed")
        raise RuntimeError("simulated QtWebEngine failure")

    lazy = LazyDayZMapGUI(map_factory=failing_factory)

    assert lazy.load_now() is False
    assert attempts == ["failed"]
    assert lazy.is_loaded is False
    assert lazy.webengine_status == "failed"
    assert lazy._retry.isVisible() is False  # parent is not shown in headless CI
    assert "simulated QtWebEngine failure" in lazy._status.text()

    def working_factory() -> QWidget:
        attempts.append("loaded")
        return QWidget()

    lazy._map_factory = working_factory
    lazy.retry()

    assert attempts == ["failed", "loaded"]
    assert lazy.is_loaded is True

    lazy.deleteLater()
    qapp.processEvents()
