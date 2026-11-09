from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from PyQt6.QtCore import QUrl

from app.gui.map_host.request_policy import (
    AdBlockInterceptor,
    ReviewedMapPage,
    is_reviewed_map_url,
)


class _RequestInfo:
    def __init__(self, url: str) -> None:
        self._url = QUrl(url)
        self.blocked = False

    def requestUrl(self) -> QUrl:  # noqa: N802
        return self._url

    def block(self, blocked: bool) -> None:
        self.blocked = bool(blocked)


def test_reviewed_map_navigation_rejects_non_https_and_foreign_hosts() -> None:
    assert is_reviewed_map_url("https://izurvive.com/chernarusplussatmap")
    assert is_reviewed_map_url("https://www.izurvive.com/livonia")
    assert not is_reviewed_map_url("http://izurvive.com/livonia")
    assert not is_reviewed_map_url("https://izurvive.com.evil.example/livonia")
    assert not is_reviewed_map_url("https://user@izurvive.com/livonia")
    assert not is_reviewed_map_url("javascript:alert(1)")


def test_shared_interceptor_blocks_tracker_but_allows_map_origin() -> None:
    interceptor = AdBlockInterceptor()
    tracker = _RequestInfo("https://pagead2.googlesyndication.com/pagead/x")
    map_tile = _RequestInfo("https://tiles.izurvive.com/chernarus/1/2/3.png")

    interceptor.interceptRequest(tracker)
    interceptor.interceptRequest(map_tile)

    assert tracker.blocked is True
    assert map_tile.blocked is False
    assert interceptor.blocked_count == 1


@pytest.mark.parametrize("url", [
    "http://izurvive.com/map", "file:///C:/private.txt", "javascript:alert(1)",
    "data:text/html,hello", "ftp://izurvive.com/map", "https://izurvive.com:444/map",
    "https://user@izurvive.com/map",
    # Synthetic credentials exercise userinfo rejection; no request is sent.
    "https://user:pass@izurvive.com/map",  # pragma: allowlist secret
    "https://izurvive.com.evil.example/map", "https://unreviewed.izurvive.com/map",
    "https://izurvive.com./map", "https://izurvive%2ecom/map", "https://127.0.0.1/",
    " https://izurvive.com/map", "https://izurvive.com/\nmap", "https://izurvive.com\\@evil.example/",
    "https://izurvive.com:bad/map", "https://[::1]/", "about:blank", "blob:https://izurvive.com/id",
])
def test_navigation_rejects_unsafe_or_unreviewed_url(url):
    assert not is_reviewed_map_url(url)
    # QUrl canonicalizes escaped host characters and whitespace before Qt's
    # callback. The resulting trusted destination is not a foreign-origin bypass.
    if url not in {"https://izurvive%2ecom/map", " https://izurvive.com/map", "https://izurvive.com/\nmap"}:
        assert not ReviewedMapPage.acceptNavigationRequest(None, QUrl(url), None, True)


@pytest.mark.parametrize("url", [
    "https://izurvive.com/map", "https://www.izurvive.com/map#x=1", "https://izurvive.com:443/map",
])
def test_reviewed_navigation_works_for_top_level_and_frames(url):
    assert is_reviewed_map_url(url)
    for main_frame in (True, False):
        assert ReviewedMapPage.acceptNavigationRequest(None, QUrl(url), None, main_frame)


def test_popups_and_file_chooser_never_delegate_to_browser_or_os():
    assert ReviewedMapPage.createWindow(None, None) is None
    assert ReviewedMapPage.chooseFiles(None, None, ["private.txt"], ["*"]) == []


@pytest.mark.parametrize("url", [
    "https://unknown.example/script.js", "http://tiles.izurvive.com/tile.png",
    "https://future.izurvive.com/script.js", "https://izurvive.com:8443/", "file:///C:/private.txt",
    "data:text/html,hello", "https://izurvive.com/ads/payload.js",
])
def test_resource_allowlist_denies_unreviewed_requests(url):
    interceptor = AdBlockInterceptor()
    request = _RequestInfo(url)
    interceptor.interceptRequest(request)
    assert request.blocked
    assert interceptor.blocked_count == 1


@pytest.mark.parametrize("kind", ["ResourceTypeMainFrame", "ResourceTypeSubFrame", "ResourceTypeNavigationPreloadMainFrame"])
def test_tile_origin_cannot_become_a_navigation_frame(kind):
    request = _RequestInfo("https://tiles.izurvive.com/payload.html")
    request.resourceType = lambda: SimpleNamespace(name=kind)
    AdBlockInterceptor().interceptRequest(request)
    assert request.blocked


def test_foreign_first_party_and_downloads_are_blocked():
    for download in (True, False):
        request = _RequestInfo("https://izurvive.com/map")
        request.isDownload = lambda: download
        request.firstPartyUrl = lambda: QUrl("https://izurvive.com/map" if download else "https://foreign.example/")
        AdBlockInterceptor().interceptRequest(request)
        assert request.blocked


def test_request_metadata_failure_fails_closed():
    request = _RequestInfo("https://izurvive.com/map")
    def broken():
        raise RuntimeError("fixture")
    request.firstPartyUrl = broken
    AdBlockInterceptor().interceptRequest(request)
    assert request.blocked


def test_secure_page_installs_all_boundaries_before_assignment(monkeypatch):
    from app.gui.map_host import request_policy as policy

    events = []

    class Signal:
        def connect(self, callback):
            self.callback = callback

    class Profile:
        PersistentCookiesPolicy = SimpleNamespace(NoPersistentCookies="no-cookies")

        def __init__(self):
            self.downloadRequested = Signal()
            events.append("ephemeral-profile")

        def setUrlRequestInterceptor(self, interceptor):  # noqa: N802
            self.interceptor = interceptor
            events.append("interceptor")

        def setPersistentCookiesPolicy(self, value):  # noqa: N802
            assert value == "no-cookies"

        def deleteLater(self):  # noqa: N802
            events.append("profile-delete-later")

    class Settings:
        def __init__(self):
            self.attributes = {}

        def setAttribute(self, name, value):  # noqa: N802
            self.attributes[name] = value

        def setUnknownUrlSchemePolicy(self, value):  # noqa: N802
            self.schemes = value

    class Page:
        def __init__(self, profile, parent):
            self.profile = profile
            self.parent = parent
            self.settings_object = Settings()
            for name in ("destroyed", "certificateError", "permissionRequested", "fileSystemAccessRequested", "fullScreenRequested"):
                setattr(self, name, Signal())

        def settings(self):
            return self.settings_object

    class View:
        def setPage(self, page):  # noqa: N802
            self.page = page
            events.append("assign-secured-page")

    monkeypatch.setattr(policy, "QWebEngineProfile", Profile)
    monkeypatch.setattr(policy, "ReviewedMapPage", Page)
    monkeypatch.setattr(policy, "AdBlockInterceptor", lambda page: object())
    view = View()
    page = policy.install_reviewed_page(view)
    assert events == ["ephemeral-profile", "interceptor", "assign-secured-page"]
    assert page is view.page
    assert page.parent is view
    assert page.profile is page._dupez_profile
    assert page.profile.interceptor is page._dupez_interceptor
    assert len(page.settings_object.attributes) == 11
    assert set(page.settings_object.attributes.values()) == {False}
    assert page.settings_object.schemes == policy.QWebEngineSettings.UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes
    denied = []
    page.profile.downloadRequested.callback(SimpleNamespace(cancel=lambda: denied.append("download")))
    page.certificateError.callback(SimpleNamespace(rejectCertificate=lambda: denied.append("certificate")))
    page.permissionRequested.callback(SimpleNamespace(deny=lambda: denied.append("permission")))
    page.fileSystemAccessRequested.callback(SimpleNamespace(reject=lambda: denied.append("file")))
    page.fullScreenRequested.callback(SimpleNamespace(reject=lambda: denied.append("fullscreen")))
    assert denied == ["download", "certificate", "permission", "file", "fullscreen"]
    page.destroyed.callback()
    assert events[-1] == "profile-delete-later"


@pytest.mark.parametrize("allowed,url,loads", [
    (True, "https://izurvive.com/map", 1),
    (False, "https://izurvive.com/map", 0),
    (True, "https://foreign.example/map", 0),
])
def test_child_ipc_load_requires_current_admission(monkeypatch, allowed, url, loads):
    from app.gui.map_host import host

    seen, responses = [], []
    monkeypatch.setattr(host, "assess_webengine_security", lambda: SimpleNamespace(allowed=allowed))
    window = SimpleNamespace(view=SimpleNamespace(load=seen.append), _send=responses.append)
    window._admit_remote_content = lambda: host.MapHostWindow._admit_remote_content(window)
    host.MapHostWindow._dispatch(window, {"type": "load", "url": url})
    assert len(seen) == loads
    assert bool(responses) is (loads == 0)


def test_child_denial_retires_view_and_latches_late_success(monkeypatch):
    from app.gui.map_host import host

    cleanup, responses, loads = [], [], []
    view = SimpleNamespace(
        load=loads.append,
        stop=lambda: cleanup.append("stop"),
        hide=lambda: cleanup.append("hide"),
        deleteLater=lambda: cleanup.append("delete"),
    )
    window = SimpleNamespace(view=view, _send=responses.append)
    window._admit_remote_content = lambda: host.MapHostWindow._admit_remote_content(window)
    monkeypatch.setattr(host, "assess_webengine_security", lambda: SimpleNamespace(allowed=False))
    host.MapHostWindow._dispatch(window, {"type": "load", "url": "https://izurvive.com/map"})
    assert cleanup == ["stop", "hide", "delete"]
    monkeypatch.setattr(host, "assess_webengine_security", lambda: SimpleNamespace(allowed=True))
    host.MapHostWindow._on_load_finished(window, True)
    host.MapHostWindow._on_load_started(window)
    host.MapHostWindow._dispatch(window, {"type": "load", "url": "https://izurvive.com/map"})
    assert not loads
    assert cleanup == ["stop", "hide", "delete"]
    assert all(response == {"type": "load-finished", "ok": False} for response in responses)


def test_child_sets_shared_context_attribute_before_qapplication() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "gui"
        / "map_host"
        / "host.py"
    ).read_text(encoding="utf-8")

    attribute = source.index("AA_ShareOpenGLContexts")
    application = source.index("app = QApplication(qt_argv)")
    assert attribute < application
