"""Shared network policy for in-process and child map WebEngine views."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject
from PyQt6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)

__all__ = [
    "AdBlockInterceptor",
    "AD_DOMAINS",
    "AD_PATH_FRAGMENTS",
    "is_izurvive_host",
    "is_reviewed_map_url",
    "install_reviewed_page",
]

# Exact hosts, not a wildcard trust grant to every future subdomain. Additional
# resource origins require review and regression coverage before being added.
NAVIGATION_HOSTS = frozenset({"izurvive.com", "www.izurvive.com"})
RESOURCE_HOSTS = NAVIGATION_HOSTS | {"tiles.izurvive.com"}

AD_DOMAINS: frozenset[str] = frozenset({
    "googlesyndication.com",
    "doubleclick.net",
    "googleadservices.com",
    "google-analytics.com",
    "googletagmanager.com",
    "googletagservices.com",
    "adservice.google.com",
    "pagead2.googlesyndication.com",
    "tpc.googlesyndication.com",
    "securepubads.g.doubleclick.net",
    "ad.doubleclick.net",
    "ads.google.com",
    "fundingchoicesmessages.google.com",
    "amazon-adsystem.com",
    "adskeeper.co.uk",
    "adnxs.com",
    "adsrvr.org",
    "adform.net",
    "criteo.com",
    "criteo.net",
    "outbrain.com",
    "taboola.com",
    "moatads.com",
    "serving-sys.com",
    "analytics.twitter.com",
    "ads-twitter.com",
})

AD_PATH_FRAGMENTS: tuple[str, ...] = (
    "/pagead/",
    "/adview",
    "/ads/",
    "/adsense/",
    "/adx/",
    "/gpt/",
    "/gampad/",
    "/pcs/view",
    "show_ads",
)


def is_izurvive_host(host: str) -> bool:
    """Label-bound domain relationship, not a navigation/resource permission.

    Retain the legacy classifier for callers; admission uses the exact host
    sets below and deliberately rejects trailing dots and unreviewed subdomains.
    """

    normalized = str(host).lower().rstrip(".")
    return normalized == "izurvive.com" or normalized.endswith(".izurvive.com")


def _https_host(url: str) -> str | None:
    if not isinstance(url, str) or not url or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme.lower() != "https" or parsed.username is not None
                or parsed.password is not None or parsed.port not in {None, 443}
                or "%" in parsed.netloc or not parsed.hostname):
            return None
        return parsed.hostname.lower()
    except (TypeError, ValueError):
        return None


def is_reviewed_map_url(url: str) -> bool:
    """Accept only HTTPS navigation to the reviewed iZurvive origin."""

    return _https_host(url) in NAVIGATION_HOSTS


class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
    """Deny unreviewed origins/schemes as well as advertising requests."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._blocked = 0

    def interceptRequest(self, info: Any) -> None:  # noqa: N802
        allowed = False
        try:
            url = info.requestUrl().toString()
            allowed = _https_host(url) in RESOURCE_HOSTS
            # Apply the narrower navigation set to frames (including redirects).
            if hasattr(info, "resourceType"):
                kind = getattr(info.resourceType(), "name", "")
                if kind in {"ResourceTypeMainFrame", "ResourceTypeSubFrame",
                            "ResourceTypeNavigationPreloadMainFrame", "ResourceTypeNavigationPreloadSubFrame"}:
                    allowed = is_reviewed_map_url(url)
            if hasattr(info, "firstPartyUrl"):
                first_party = info.firstPartyUrl().toString()
                if first_party and not is_reviewed_map_url(first_party):
                    allowed = False
            if hasattr(info, "isDownload") and info.isDownload():
                allowed = False
            if any(fragment in url.lower() for fragment in AD_PATH_FRAGMENTS):
                allowed = False
        except Exception:
            allowed = False
        if not allowed:
            info.block(True)
            self._blocked += 1

    @property
    def blocked_count(self) -> int:
        return self._blocked


class ReviewedMapPage(QWebEnginePage):
    """No foreign navigation, popups, file pickers or implicit OS launches."""

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):  # noqa: N802
        return is_reviewed_map_url(url.toString())

    def createWindow(self, window_type):  # noqa: N802
        return None

    def chooseFiles(self, mode, old_files, accepted_mime_types):  # noqa: N802
        return []


def install_reviewed_page(view) -> ReviewedMapPage:
    """Install a dedicated ephemeral profile and all security hooks before load.

    The caller must pass runtime admission before constructing its view. Setup
    failure propagates, so callers must not navigate a partially secured view.
    """
    profile = QWebEngineProfile()  # unnamed/off-the-record; no shared profile
    page = ReviewedMapPage(profile, view)
    page._dupez_profile = profile
    # Qt requires the profile to outlive every page using it. It must not be
    # an earlier QObject sibling destroyed before the view's page.
    page.destroyed.connect(profile.deleteLater)
    page._dupez_interceptor = AdBlockInterceptor(page)
    profile.setUrlRequestInterceptor(page._dupez_interceptor)
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    profile.downloadRequested.connect(lambda request: request.cancel())
    page.certificateError.connect(lambda error: error.rejectCertificate())
    page.permissionRequested.connect(lambda permission: permission.deny())
    page.fileSystemAccessRequested.connect(lambda request: request.reject())
    page.fullScreenRequested.connect(lambda request: request.reject())
    settings = page.settings()
    attributes = QWebEngineSettings.WebAttribute
    for name in (
        "PluginsEnabled", "HyperlinkAuditingEnabled", "JavascriptCanOpenWindows",
        "JavascriptCanAccessClipboard", "JavascriptCanPaste", "LocalContentCanAccessFileUrls",
        "LocalContentCanAccessRemoteUrls", "AllowRunningInsecureContent",
        "AllowGeolocationOnInsecureOrigins", "ScreenCaptureEnabled", "DnsPrefetchEnabled",
    ):
        settings.setAttribute(getattr(attributes, name), False)
    settings.setUnknownUrlSchemePolicy(QWebEngineSettings.UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes)
    view.setPage(page)
    return page
