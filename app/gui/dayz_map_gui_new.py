#!/usr/bin/env python3
# app/gui/dayz_map_gui_new.py — Ad-free iZurvive wrapper
"""DayZ Map GUI — Ad-free iZurvive with map selector.

Embeds the iZurvive interactive map inside a ``QWebEngineView`` with
two layers of ad-blocking:

1. **Network-level** — ``AdBlockInterceptor`` blocks requests to known
   ad/tracking domains before they leave the browser engine.
2. **DOM-level** — CSS injection + JS ``MutationObserver`` removes any
   ad elements that slip through (or are dynamically injected).

If ``QWebEngineWidgets`` is unavailable (headless builds, missing Qt
WebEngine package), the widget degrades to a placeholder label.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.logs.logger import log_error, log_info

# Graceful degradation when WebEngine is not installed.
#
# NOTE: we catch Exception (not just ImportError) because on Windows a
# missing/mismatched Qt DLL surfaces as OSError ("DLL load failed while
# importing QtWebEngineCore") rather than ImportError. We also log the
# real exception type + message so failures are diagnosable instead of
# silently degrading to a placeholder.
_WEBENGINE_IMPORT_ERROR: Optional[str] = None
try:
    from PyQt6.QtWebEngineCore import (
        QWebEngineProfile,
        QWebEngineUrlRequestInterceptor,
    )
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    _WEBENGINE_AVAILABLE: bool = True
except Exception as _webengine_exc:  # noqa: BLE001 — we really do want everything
    _WEBENGINE_AVAILABLE = False
    _WEBENGINE_IMPORT_ERROR = f"{type(_webengine_exc).__name__}: {_webengine_exc}"
    log_error(
        "QtWebEngine not available — DayZ map will show a placeholder "
        f"(reason: {_WEBENGINE_IMPORT_ERROR})"
    )

__all__ = ["DayZMapGUI"]

# ── Map catalogue ───────────────────────────────────────────────────

MAP_OPTIONS: Dict[str, str] = {
    "Chernarus+ (Satellite)": "https://izurvive.com/chernarusplussatmap",
    "Chernarus+ (Topographic)": "https://izurvive.com/chernarusplus",
    "Livonia": "https://izurvive.com/livonia",
    "Namalsk": "https://izurvive.com/namalsk",
    "Sakhal": "https://izurvive.com/sakhal",
    "Deer Isle": "https://izurvive.com/deerisle",
    "Esseker": "https://izurvive.com/esseker",
    "Takistan": "https://izurvive.com/takistan",
}

# ── Ad-blocking data ────────────────────────────────────────────────

#: Domains to block at the network request level.
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

#: URL path fragments that indicate ad content.
AD_PATH_FRAGMENTS: List[str] = [
    "/pagead/",
    "/adview",
    "/ads/",
    "/adsense/",
    "/adx/",
    "/gpt/",
    "/gampad/",
    "/pcs/view",
    "show_ads",
]

#: CSS selectors that target known ad containers (for DOM cleanup).
AD_SELECTORS: List[str] = [
    ".ad-container", ".adsbygoogle", "#google_image_div",
    '[id^="div-gpt-ad"]', ".ad-slot", ".desktop-ad",
    ".ad-banner", ".ad-leaderboard", ".ad-sidebar",
    "ins.adsbygoogle", "[data-ad-slot]", "[data-ad-client]",
    ".ad-wrapper", "#ad-container", ".advertisement",
    'iframe[src*="googleads"]', 'iframe[src*="doubleclick"]',
    'iframe[src*="googlesyndication"]', 'iframe[src*="amazon-adsystem"]',
    ".sticky-ad", ".banner-ad", ".top-ad",
    '[id*="google_ads"]',
]

#: Injected CSS that hides ad containers before JS runs.
_AD_HIDE_CSS: str = """
    .ad-container, .adsbygoogle, [id^="div-gpt-ad"], .ad-slot,
    .desktop-ad, .ad-banner, .ad-leaderboard, .ad-sidebar,
    ins.adsbygoogle, .ad-wrapper, #ad-container, .advertisement,
    .sticky-ad, .banner-ad, .top-ad {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        overflow: hidden !important;
    }
"""

# ── QSS constants ──────────────────────────────────────────────────

_SELECTOR_BAR_QSS: str = (
    "background-color: #0f1923; border-bottom: 1px solid #1a2a3a;"
)

_LABEL_QSS: str = "color: #00d9ff; font-weight: bold; font-size: 12px;"

_COMBO_QSS: str = """
    QComboBox {
        background: #16213e; color: #e0e0e0; border: 1px solid #1a2a3a;
        border-radius: 4px; padding: 4px 10px; font-size: 12px; min-width: 200px;
    }
    QComboBox::drop-down { border: none; width: 20px; }
    QComboBox QAbstractItemView {
        background: #0f1923; color: #e0e0e0;
        selection-background-color: rgba(0, 217, 255, 0.3);
        border: 1px solid #1a2a3a;
    }
"""

_PLACEHOLDER_QSS: str = (
    "color: #64748b; font-size: 14px; background: #0a0e1a; padding: 40px;"
)


# ── AdBlockInterceptor ──────────────────────────────────────────────

if _WEBENGINE_AVAILABLE:

    class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
        """Network-level ad blocker — blocks requests before they load."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._blocked: int = 0

        def interceptRequest(self, info: Any) -> None:  # noqa: N802
            """Check each outgoing request against the block lists.

            PERF: iZurvive fires hundreds of tile requests per pan/zoom.
            Host matching uses suffix check against a pre-built set
            (O(depth) per request, not O(n_domains)). Path fragment
            matching stays linear — the list is tiny (<10 entries) and
            most tile URLs don't even trigger the second loop because
            the host is the iZurvive CDN.
            """
            url_obj = info.requestUrl()
            host: str = url_obj.host().lower()

            # Fast path: skip both loops for obvious map tile requests
            # (iZurvive serves from izurvive.com / its CDN subdomains).
            if host.endswith("izurvive.com"):
                return

            # Suffix match: walk up the host label by label, hit a set.
            # "pagead2.googlesyndication.com" → check "googlesyndication.com",
            # then "syndication.com", then "com" — O(labels), not O(n_domains).
            labels = host.split(".")
            for i in range(len(labels) - 1):
                candidate = ".".join(labels[i:])
                if candidate in AD_DOMAINS:
                    info.block(True)
                    self._blocked += 1
                    return

            # Path fragment check only if host didn't match
            url: str = url_obj.toString().lower()
            for frag in AD_PATH_FRAGMENTS:
                if frag in url:
                    info.block(True)
                    self._blocked += 1
                    return

        @property
        def blocked_count(self) -> int:
            """Total number of requests blocked this session."""
            return self._blocked


# ── DayZMapGUI ──────────────────────────────────────────────────────

class DayZMapGUI(QWidget):
    """Ad-free iZurvive wrapper with map-selector dropdown.

    Falls back to a placeholder label when ``QWebEngineWidgets`` is
    unavailable (e.g. headless CI, missing system package).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.current_map: str = "Chernarus+ (Satellite)"
        self._interceptor: Any = None
        self.map_view: Any = None  # QWebEngineView or None

        self._build_ui()
        self.load_map(self.current_map)

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Assemble selector bar + web view (or placeholder)."""
        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Map selector bar
        selector_bar = QWidget()
        selector_bar.setFixedHeight(40)
        selector_bar.setStyleSheet(_SELECTOR_BAR_QSS)
        bar_layout = QHBoxLayout(selector_bar)
        bar_layout.setContentsMargins(12, 4, 12, 4)

        label = QLabel("MAP:")
        label.setStyleSheet(_LABEL_QSS)
        bar_layout.addWidget(label)

        self.map_combo = QComboBox()
        self.map_combo.addItems(MAP_OPTIONS.keys())
        self.map_combo.setCurrentText(self.current_map)
        self.map_combo.setStyleSheet(_COMBO_QSS)
        self.map_combo.currentTextChanged.connect(self.load_map)
        bar_layout.addWidget(self.map_combo)
        bar_layout.addStretch()

        layout.addWidget(selector_bar)

        # WebEngine view (with fallback)
        if _WEBENGINE_AVAILABLE:
            self.map_view = QWebEngineView()
            self._install_ad_blocker()
            self.map_view.loadFinished.connect(self._inject_dom_adblocker)
            layout.addWidget(self.map_view)
        else:
            reason = _WEBENGINE_IMPORT_ERROR or "PyQt6-WebEngine not installed"
            placeholder = QLabel(
                "Map unavailable — QtWebEngine failed to load.\n\n"
                f"Reason: {reason}\n\n"
                "Fix: pip install --upgrade PyQt6 PyQt6-WebEngine"
            )
            placeholder.setStyleSheet(_PLACEHOLDER_QSS)
            placeholder.setWordWrap(True)
            layout.addWidget(placeholder)

    # ── Ad blocker setup ────────────────────────────────────────────

    def _install_ad_blocker(self) -> None:
        """Attach the network-level request interceptor to the default profile."""
        try:
            self._interceptor = AdBlockInterceptor(self)
            profile = QWebEngineProfile.defaultProfile()
            profile.setUrlRequestInterceptor(self._interceptor)
            log_info("Map: Network-level ad blocker installed")
        except Exception as exc:
            log_error(f"Map: Failed to install network ad blocker: {exc}")

    # ── Map loading ─────────────────────────────────────────────────

    def load_map(self, map_name: str) -> None:
        """Navigate the web view to the selected iZurvive map."""
        self.current_map = map_name
        url = MAP_OPTIONS.get(map_name, MAP_OPTIONS["Chernarus+ (Satellite)"])
        if self.map_view is None:
            return
        try:
            self.map_view.load(QUrl(url))
            log_info(f"Loading map: {map_name} -> {url}")
        except Exception as exc:
            log_error(f"Error loading map: {exc}")

    # ── DOM-level ad cleanup ────────────────────────────────────────

    def _inject_dom_adblocker(self, success: bool) -> None:
        """Inject CSS + JS ad-blocker as backup after page load completes."""
        if not success or self.map_view is None:
            return

        page = self.map_view.page()

        # Phase 1: CSS — hide ad containers immediately
        css_js = (
            "(function() {"
            "  var style = document.createElement('style');"
            f"  style.textContent = `{_AD_HIDE_CSS}`;"
            "  document.head.appendChild(style);"
            "})();"
        )
        page.runJavaScript(css_js)

        # Phase 2: JS — remove ad elements and watch for new ones.
        #
        # PERF: iZurvive is a Leaflet tile map that swaps dozens of
        # <img> tiles per pan/zoom frame. An unthrottled MutationObserver
        # on document.body with subtree:true would fire hundreds of
        # times per second and run 22 querySelectorAll sweeps per hit,
        # grinding the map to a halt. So we:
        #   1. Combine all selectors into a single comma-joined query
        #      (one DOM walk instead of 22).
        #   2. Debounce the observer callback to 250ms via requestIdle
        #      + trailing timer.
        #   3. Auto-disconnect the observer after 15s — ads are static
        #      after initial load; we don't need to watch forever.
        #   4. Drop the overlapping [500,1500,3000,5000] passes; the
        #      debounced observer covers late-loading ads.
        selectors_js = ", ".join(f"'{s}'" for s in AD_SELECTORS)
        remove_js = f"""
        (function() {{
            try {{
                const combinedSelector = [{selectors_js}].join(', ');
                let removed = 0;

                function removeAds() {{
                    // Single DOM walk across all selectors
                    document.querySelectorAll(combinedSelector).forEach(el => {{
                        el.remove();
                        removed++;
                    }});
                    // Iframe sweep — cheap, ad iframes are rare
                    document.querySelectorAll('iframe').forEach(iframe => {{
                        const src = (iframe.src || '').toLowerCase();
                        if (src.includes('doubleclick') ||
                            src.includes('googlesyndication') ||
                            src.includes('amazon-adsystem') ||
                            src.includes('googleads')) {{
                            iframe.remove();
                            removed++;
                        }}
                    }});
                }}

                // Initial sweep — before any mutations
                removeAds();

                // Debounced observer — coalesces bursts of tile swaps
                // into a single trailing sweep 250ms after the burst
                // ends. Uses a flag + setTimeout instead of a rolling
                // timer to avoid allocating a new closure per mutation.
                let pending = false;
                const debounced = () => {{
                    if (pending) return;
                    pending = true;
                    setTimeout(() => {{ pending = false; removeAds(); }}, 250);
                }};

                const observer = new MutationObserver(debounced);
                observer.observe(document.body, {{ childList: true, subtree: true }});

                // Auto-disconnect after 15s — ads are static by then,
                // and continuing to observe a live Leaflet map just
                // burns CPU.
                setTimeout(() => {{
                    observer.disconnect();
                    console.log('DupeZ: ad observer disconnected after 15s');
                }}, 15000);

                console.log('DupeZ: Ad-blocker active, initial removed=' + removed);
            }} catch (err) {{
                console.error('DupeZ ad-blocker error:', err);
            }}
        }})();
        """
        page.runJavaScript(remove_js)

        blocked = self._interceptor.blocked_count if self._interceptor else 0
        log_info(f"Map ad-blocker injected (network blocked: {blocked}, DOM cleanup active)")
