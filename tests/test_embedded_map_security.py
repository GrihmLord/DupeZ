"""Containment contracts using fake browser views; no renderer or network starts."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QWidget

from app.gui import dayz_map_gui_new as map_module
from app.gui import lazy_dayz_map as lazy_module


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["dupez-map-containment-tests"])


@pytest.fixture
def browser_harness(monkeypatch, qapp):
    events = []
    policy = SimpleNamespace(allowed=True, reason="")

    class Signal:
        def connect(self, callback):
            pass

    class View(QWidget):
        def __init__(self):
            super().__init__()
            events.append("construct")
            self.loadStarted = Signal()
            self.loadFinished = Signal()
            self._page = SimpleNamespace(renderProcessTerminated=Signal())

        def page(self):
            return self._page

        def load(self, url):
            events.append(("load", url.toString()))

        def stop(self):
            events.append("stop")

        def deleteLater(self):  # noqa: N802
            events.append("dispose")
            super().deleteLater()

    def install(view):
        events.append("install-reviewed-page")
        return view.page()

    monkeypatch.setattr(map_module, "QWebEngineView", View, raising=False)
    monkeypatch.setattr(map_module, "install_reviewed_page", install, raising=False)
    monkeypatch.setattr(map_module, "_WEBENGINE_AVAILABLE", True)
    monkeypatch.setattr(map_module, "_EMBED_MODE", "inproc")
    monkeypatch.setattr(map_module, "assess_webengine_security", lambda: policy)
    monkeypatch.setattr(lazy_module, "assess_webengine_security", lambda: policy)
    monkeypatch.setattr(map_module.DayZMapGUI, "_install_ad_blocker", lambda self: events.append("interceptor"))
    monkeypatch.setattr(map_module.DayZMapGUI, "_apply_perf_settings", lambda self: events.append("settings"))
    monkeypatch.setattr(map_module.QDesktopServices, "openUrl", lambda url: events.append(("external", url.toString())))
    return SimpleNamespace(events=events, policy=policy)


@pytest.mark.parametrize("mode", ["inproc", "child-experimental"])
@pytest.mark.parametrize("reason", ["Elevated process denied", "Sandbox disabled", "Native runtime security gate unmet"])
def test_denied_context_never_constructs_navigates_or_launches_browser(browser_harness, monkeypatch, mode, reason):
    harness = browser_harness
    harness.policy.allowed = False
    harness.policy.reason = reason
    monkeypatch.setattr(map_module, "_EMBED_MODE", mode)
    monkeypatch.setattr(map_module, "MapHostClient", lambda *args: pytest.fail("child construction forbidden"))

    widget = map_module.DayZMapGUI()
    widget._build_inproc_webengine(widget.layout())
    widget._build_child_embed(widget.layout())
    widget._on_host_failed("synthetic child failure")
    widget._on_host_hwnd_received(123)
    widget.load_map("Livonia")
    widget._open_in_browser()
    widget._on_inproc_load_finished(True)
    widget._on_host_load_finished(True)

    assert harness.events == []
    assert widget.webengine_status == "unavailable"
    assert widget.webengine_ready is False
    assert reason in widget._security_placeholder.text()
    assert "https://izurvive.com/livonia" in widget._security_placeholder.text()
    assert "non-administrator browser" in widget._security_placeholder.text()
    assert widget._security_placeholder.openExternalLinks() is False
    widget.deleteLater()


def test_reviewed_unelevated_runtime_installs_boundary_before_navigation(browser_harness):
    widget = map_module.DayZMapGUI()

    assert browser_harness.events == [
        "construct", "install-reviewed-page", "interceptor", "settings",
        ("load", "https://izurvive.com/chernarusplussatmap"),
    ]
    assert widget._secured_page is widget.map_view.page()
    assert widget.webengine_status == "loading"
    widget._on_inproc_load_finished(True)
    assert widget.webengine_ready is True
    widget.load_map("Livonia")
    assert browser_harness.events[-1] == ("load", "https://izurvive.com/livonia")
    widget.deleteLater()


def test_recheck_denies_cached_navigation_and_latches_until_restart(browser_harness):
    widget = map_module.DayZMapGUI()
    widget._on_inproc_load_finished(True)
    browser_harness.policy.allowed = False
    browser_harness.policy.reason = "Sandbox disabled"

    # This previously loaded URL must not skip the gate via deduplication.
    widget.load_map(widget.current_map)
    assert widget.webengine_status == "unavailable"
    assert widget.webengine_ready is False
    assert "stop" in browser_harness.events
    assert widget.map_view is None
    assert widget._secured_page is None
    assert browser_harness.events.count("dispose") == 1
    browser_harness.policy.allowed = True
    widget.load_map("Livonia")
    widget._open_in_browser()
    widget._on_inproc_load_finished(True)

    assert [item for item in browser_harness.events if isinstance(item, tuple)] == [
        ("load", "https://izurvive.com/chernarusplussatmap"),
    ]
    assert widget.webengine_status == "unavailable"
    assert browser_harness.events.count("dispose") == 1
    widget.deleteLater()


def test_denied_view_disposal_failure_retains_owner_for_retry(browser_harness, monkeypatch):
    widget = map_module.DayZMapGUI()
    view = widget.map_view
    original_dispose = view.deleteLater
    attempts = []

    def fail_disposal():
        attempts.append("failed")
        raise RuntimeError("synthetic scheduling error")

    monkeypatch.setattr(view, "deleteLater", fail_disposal)
    browser_harness.policy.allowed = False
    browser_harness.policy.reason = "Sandbox disabled"
    widget.load_map("Livonia")

    assert attempts == ["failed"]
    assert widget.map_view is view
    assert widget.layout().indexOf(view) == -1
    assert widget.webengine_ready is False
    assert "Cleanup is not confirmed" in widget._security_placeholder.text()
    assert "teardown could not be scheduled" in widget._security_placeholder.text()
    assert "dispose" not in browser_harness.events

    monkeypatch.setattr(view, "deleteLater", original_dispose)
    widget._open_in_browser()  # denied button retries cleanup, never launches
    widget._on_inproc_load_finished(True)
    widget._on_host_failed("late child failure")

    assert widget.map_view is None
    assert widget.webengine_status == "unavailable"
    assert browser_harness.events.count("dispose") == 1
    assert browser_harness.events.count("construct") == 1
    assert "Cleanup is not confirmed" not in widget._security_placeholder.text()
    assert not any(isinstance(item, tuple) and item[0] == "external" for item in browser_harness.events)
    widget.deleteLater()


def test_view_disposal_proceeds_when_stop_fails_and_child_cleanup_is_independent(browser_harness, monkeypatch):
    widget = map_module.DayZMapGUI()
    view = widget.map_view
    child_calls = []

    def fail_stop():
        raise RuntimeError("synthetic stop error")

    monkeypatch.setattr(view, "stop", fail_stop)
    widget._host_client = SimpleNamespace(stop=lambda: child_calls.append("stop"))
    browser_harness.policy.allowed = False
    browser_harness.policy.reason = "Native runtime security gate unmet"

    widget.load_map("Livonia")

    assert widget.map_view is None
    assert widget.layout().indexOf(view) == -1
    assert browser_harness.events.count("dispose") == 1
    assert child_calls == ["stop"]
    assert widget._host_client is None
    assert widget.webengine_status == "unavailable"
    widget.deleteLater()


def test_denial_stops_existing_child_before_any_ipc_navigation(browser_harness):
    widget = map_module.DayZMapGUI()
    child_calls = []
    widget._host_client = SimpleNamespace(
        hwnd=123, stop=lambda: child_calls.append("stop"),
        load=lambda url: child_calls.append(("load", url)),
    )
    widget._host_container = QWidget(widget)
    browser_harness.policy.allowed = False
    browser_harness.policy.reason = "Native runtime security gate unmet"

    widget.load_map("Livonia")
    widget._on_host_hwnd_received(123)

    assert child_calls == ["stop"]
    assert widget._host_client is None
    assert widget.webengine_status == "unavailable"
    widget.deleteLater()


def test_security_assessment_error_fails_closed(browser_harness, monkeypatch):
    def broken_policy():
        raise RuntimeError("synthetic policy error")

    monkeypatch.setattr(map_module, "assess_webengine_security", broken_policy)
    widget = map_module.DayZMapGUI()
    assert browser_harness.events == []
    assert widget.webengine_status == "unavailable"
    assert "could not be verified" in widget._security_placeholder.text()
    widget.deleteLater()


def test_lazy_denial_precedes_factory_resolution_and_retries(browser_harness, monkeypatch):
    browser_harness.policy.allowed = False
    browser_harness.policy.reason = "Elevated process denied"
    lazy = lazy_module.LazyDayZMapGUI()
    monkeypatch.setattr(lazy, "_resolve_factory", lambda: pytest.fail("factory resolution forbidden"))

    assert lazy.load_now() is False
    lazy.retry()

    assert lazy.is_loaded is False
    assert lazy.webengine_status == "unavailable"
    assert lazy.webengine_ready is False
    assert "https://izurvive.com/chernarusplussatmap" in lazy._status.text()
    assert "non-administrator browser" in lazy._status.text()
    assert lazy._status.openExternalLinks() is False
    assert browser_harness.events == []
    lazy.deleteLater()


def test_lazy_security_assessment_error_does_not_resolve_factory(browser_harness, monkeypatch):
    def broken_policy():
        raise RuntimeError("synthetic policy error")

    monkeypatch.setattr(lazy_module, "assess_webengine_security", broken_policy)
    lazy = lazy_module.LazyDayZMapGUI(map_factory=lambda: pytest.fail("factory construction forbidden"))
    assert lazy.load_now() is False
    assert lazy.webengine_status == "unavailable"
    assert "could not be verified" in lazy._status.text()
    lazy.deleteLater()


@pytest.mark.parametrize("url,expected_scripts", [
    ("https://izurvive.com/livonia", 4),
    ("https://example.com/map", 0),
    ("https://izurvive.com.example.com/", 0),
    ("http://izurvive.com/livonia", 0),
    ("file:///C:/Users/Owner/private.html", 0),
    ("about:blank", 0),
])
def test_map_scripts_run_only_on_reviewed_https_origin(browser_harness, monkeypatch, url, expected_scripts):
    monkeypatch.setenv("DUPEZ_MAP_RENDERER_TIER", "tier3_cpu")
    widget = map_module.DayZMapGUI()
    scripts = []
    page = widget.map_view.page()
    page.url = lambda: QUrl(url)
    page.runJavaScript = scripts.append

    widget._inject_dom_adblocker(True)
    widget._inject_perf_tweaks(True)

    assert len(scripts) == expected_scripts
    widget.deleteLater()


def test_map_reuses_reviewed_profile_interceptor_without_persistent_storage(monkeypatch, qapp):
    monkeypatch.setattr(map_module, "_WEBENGINE_AVAILABLE", False)
    monkeypatch.setattr(map_module, "assess_webengine_security", lambda: SimpleNamespace(allowed=True, reason=""))
    widget = map_module.DayZMapGUI()
    calls = []
    interceptor = object()
    profile = SimpleNamespace(
        setHttpCacheType=lambda kind: calls.append(("cache", kind)),
        setHttpCacheMaximumSize=lambda size: calls.append(("limit", size)),
    )
    page = SimpleNamespace(_dupez_interceptor=interceptor, profile=lambda: profile)
    widget.map_view = SimpleNamespace(page=lambda: page)

    widget._install_ad_blocker()

    assert widget._interceptor is interceptor
    assert calls == [
        ("cache", map_module.QWebEngineProfile.HttpCacheType.MemoryHttpCache),
        ("limit", 64 * 1024 * 1024),
    ]
    del page._dupez_interceptor
    with pytest.raises(RuntimeError, match="network policy initialization failed"):
        widget._install_ad_blocker()
    widget.deleteLater()
