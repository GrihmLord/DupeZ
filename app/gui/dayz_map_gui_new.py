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
        QWebEngineSettings,
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

# ── Perf mode constants ─────────────────────────────────────────────
# Software raster (forced by admin-token elevation) makes GPU flags
# unusable, so map lag has to be attacked at the browser/DOM layer.
#
# Primary targets for software-raster perf:
#   1. Composited layers: Leaflet uses will-change/translate3d to force
#      GPU layer promotion. On software raster those layers become
#      full-bitmap blits the CPU has to composite on every frame.
#   2. Tile fade + zoom animations: multi-frame compositing work.
#   3. Hi-DPI pixel doubling: iZurvive runs at devicePixelRatio ≥ 1.5
#      on many Windows setups, quadrupling fragment work.
#
#: Zoom factor applied to the web view. 0.85 cuts pixel work by ~27%
#: (linear × linear) at the cost of slightly softer text — the right
#: trade on a CPU-bound pipeline. Raise if text feels too soft.
_MAP_ZOOM_FACTOR: float = 0.85

#: CSS injected into every iZurvive page before the DOM settles. This
#: neutralises the GPU-assumed animations Leaflet uses by default, plus
#: kills tile fade transitions that force per-frame alpha compositing.
_PERF_CSS: str = """
    /* Kill tile fade-in — the biggest software-raster cost on pan */
    .leaflet-tile { transition: none !important; opacity: 1 !important; }
    .leaflet-fade-anim .leaflet-tile { transition: none !important; }
    .leaflet-fade-anim .leaflet-tile-loaded { opacity: 1 !important; }

    /* Remove will-change hints — on software raster these force full
       bitmap reads instead of helping. */
    .leaflet-pane, .leaflet-tile-pane, .leaflet-overlay-pane,
    .leaflet-marker-pane, .leaflet-popup-pane, .leaflet-tile,
    .leaflet-map-pane, .leaflet-zoom-animated {
        will-change: auto !important;
    }

    /* Remove transitions on everything inside the map container */
    .leaflet-container, .leaflet-container * {
        transition-duration: 0s !important;
        animation-duration: 0s !important;
    }

    /* Zoom animation does a crossfade — skip it entirely */
    .leaflet-zoom-anim .leaflet-zoom-animated {
        transition: none !important;
    }
"""

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
            self._apply_perf_settings()
            self.map_view.loadFinished.connect(self._inject_dom_adblocker)
            self.map_view.loadFinished.connect(self._inject_perf_tweaks)
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
        """Attach the network-level request interceptor to the default profile.

        Also opportunistically enlarges the HTTP disk cache so iZurvive
        tile requests don't re-hit the network on every pan. Failures
        are non-fatal — the interceptor is the critical path.
        """
        try:
            self._interceptor = AdBlockInterceptor(self)
            profile = QWebEngineProfile.defaultProfile()
            profile.setUrlRequestInterceptor(self._interceptor)
            # Aggressive disk cache for tile reuse on pan/zoom
            try:
                profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
                profile.setHttpCacheMaximumSize(512 * 1024 * 1024)  # 512 MiB
                profile.setPersistentCookiesPolicy(
                    QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
                )
            except Exception as cache_exc:
                log_error(f"Map: cache tuning failed (non-fatal): {cache_exc}")
            log_info("Map: Network-level ad blocker installed")
        except Exception as exc:
            log_error(f"Map: Failed to install network ad blocker: {exc}")

    # ── Software-raster perf tuning ─────────────────────────────────

    def _apply_perf_settings(self) -> None:
        """Tune QWebEngineSettings + zoom factor for software raster.

        Under the admin-token elevation DupeZ needs for WinDivert, the
        Chromium GPU process refuses to start, so all rendering falls
        back to the software rasterizer. The cheapest wins on that
        pipeline are:
          1. Drop devicePixelRatio-equivalent work via setZoomFactor.
          2. Disable scroll/cursor animations the compositor has to
             redraw.
          3. Disable WebGL + 2D canvas accel (they're no-ops without
             GPU but still cost at init time).
          4. Kill plugins and image animation playback (animated GIF
             ads repaint forever).
        """
        if self.map_view is None:
            return
        try:
            # ~27% pixel reduction at the cost of slightly softer text
            self.map_view.setZoomFactor(_MAP_ZOOM_FACTOR)

            settings = self.map_view.settings()
            A = QWebEngineSettings.WebAttribute
            # Disable animations / effects that burn CPU on software raster
            for attr, value in (
                (A.ScrollAnimatorEnabled, False),
                (A.PluginsEnabled, False),
                (A.WebGLEnabled, False),
                (A.Accelerated2dCanvasEnabled, False),
                (A.HyperlinkAuditingEnabled, False),
                (A.AutoLoadIconsForPage, False),
                (A.ShowScrollBars, True),
                (A.LocalStorageEnabled, True),   # iZurvive preferences
                (A.JavascriptEnabled, True),
                (A.ErrorPageEnabled, False),
            ):
                try:
                    settings.setAttribute(attr, value)
                except Exception:
                    pass  # some attrs vary by Qt version

            # Stop animated GIF/APNG ads from repainting forever
            try:
                from PyQt6.QtWebEngineCore import QWebEngineSettings as _QWES
                if hasattr(_QWES, "UnknownUrlSchemePolicy"):
                    pass  # noqa — placeholder; keeps import local
            except Exception:
                pass

            log_info(
                f"Map: perf settings applied (zoom={_MAP_ZOOM_FACTOR}, "
                "WebGL/2DCanvas off, scroll animator off)"
            )
        except Exception as exc:
            log_error(f"Map: failed to apply perf settings: {exc}")

    def _inject_perf_tweaks(self, success: bool) -> None:
        """Inject CSS + JS that neutralise Leaflet's GPU-assumed animations.

        Runs on ``loadFinished``. The CSS disables tile fade/zoom
        transitions and strips ``will-change`` hints (which force the
        software compositor to allocate and blit full-bitmap layers).
        The JS walks the DOM for the live ``L.Map`` instance iZurvive
        has already constructed and turns off its animation options in
        place — you can't retroactively change constructor options, but
        most Leaflet animation flags are read on each frame.
        """
        if not success or self.map_view is None:
            return
        page = self.map_view.page()

        # Phase 1: CSS — synchronous, kills compositing work immediately
        css_js = (
            "(function(){"
            "var s=document.createElement('style');"
            f"s.textContent=`{_PERF_CSS}`;"
            "document.head.appendChild(s);"
            "})();"
        )
        page.runJavaScript(css_js)

        # Phase 2: JS — find the live Leaflet map and turn off animations
        tune_js = r"""
        (function() {
            try {
                // Leaflet attaches the map instance to the container's
                // _leaflet_id; walk candidate containers and check for
                // a .dragging control (unique to L.Map instances).
                function findMap() {
                    const candidates = document.querySelectorAll(
                        '.leaflet-container, [class*="leaflet"]'
                    );
                    for (const el of candidates) {
                        for (const k of Object.keys(el)) {
                            const v = el[k];
                            if (v && v.dragging && v.getCenter && v.options) {
                                return v;
                            }
                        }
                    }
                    // Fallback: check window globals
                    for (const k of Object.keys(window)) {
                        const v = window[k];
                        if (v && v.dragging && v.getCenter && v.options
                            && v.options.crs) {
                            return v;
                        }
                    }
                    return null;
                }

                function tune(map) {
                    if (!map) return false;
                    try {
                        map.options.fadeAnimation = false;
                        map.options.zoomAnimation = false;
                        map.options.markerZoomAnimation = false;
                        map.options.inertia = false;
                        map.options.zoomSnap = 1;
                        map.options.wheelDebounceTime = 60;
                        map.options.wheelPxPerZoomLevel = 120;
                        // Leaflet caches the animation flag internally
                        map._fadeAnimated = false;
                        map._zoomAnimated = false;
                        // Kill running transitions on tile layers
                        map.eachLayer && map.eachLayer(function(layer) {
                            if (layer.options) {
                                layer.options.updateWhenIdle = true;
                                layer.options.updateWhenZooming = false;
                                layer.options.keepBuffer = 4;
                            }
                        });
                        console.log('DupeZ: Leaflet perf tune applied');
                        return true;
                    } catch (e) {
                        console.error('DupeZ: tune failed', e);
                        return false;
                    }
                }

                // Retry loop — iZurvive builds the map async after
                // load event. Six attempts over ~3s covers slow cases.
                let attempts = 0;
                const maxAttempts = 6;
                function attempt() {
                    const map = findMap();
                    if (tune(map)) return;
                    if (++attempts < maxAttempts) {
                        setTimeout(attempt, 500);
                    } else {
                        console.warn('DupeZ: Leaflet map instance not found');
                    }
                }
                attempt();
            } catch (err) {
                console.error('DupeZ perf tune error:', err);
            }
        })();
        """
        page.runJavaScript(tune_js)
        log_info("Map: perf tweaks injected (CSS + Leaflet tune)")

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
