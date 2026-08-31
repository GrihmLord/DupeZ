"""Shared network policy for in-process and child map WebEngine views."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

__all__ = [
    "AdBlockInterceptor",
    "AD_DOMAINS",
    "AD_PATH_FRAGMENTS",
    "is_izurvive_host",
    "is_reviewed_map_url",
]

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
    """Return whether *host* is iZurvive or one of its subdomains."""

    normalized = str(host).lower().rstrip(".")
    return normalized == "izurvive.com" or normalized.endswith(".izurvive.com")


def is_reviewed_map_url(url: str) -> bool:
    """Accept only HTTPS navigation to the reviewed iZurvive origin."""

    try:
        parsed = urlsplit(str(url))
        return (
            parsed.scheme.casefold() == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
            and is_izurvive_host(parsed.hostname or "")
        )
    except (TypeError, ValueError):
        return False


class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
    """Block known advertising and tracking requests before transmission."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._blocked = 0

    def interceptRequest(self, info: Any) -> None:  # noqa: N802
        url_obj = info.requestUrl()
        host = url_obj.host().lower()
        if is_izurvive_host(host):
            return

        labels = host.split(".")
        for index in range(len(labels) - 1):
            if ".".join(labels[index:]) in AD_DOMAINS:
                info.block(True)
                self._blocked += 1
                return

        url = url_obj.toString().lower()
        for fragment in AD_PATH_FRAGMENTS:
            if fragment in url:
                info.block(True)
                self._blocked += 1
                return

    @property
    def blocked_count(self) -> int:
        return self._blocked
