#!/usr/bin/env python3
"""DayZ Map GUI — Ad-free iZurvive with map selector"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineUrlRequestInterceptor,
    QWebEngineProfile,
    QWebEnginePage,
)
from PyQt6.QtCore import QUrl
from app.logs.logger import log_info, log_error

MAP_OPTIONS = {
    "Chernarus+ (Satellite)": "https://izurvive.com/chernarusplussatmap",
    "Chernarus+ (Topographic)": "https://izurvive.com/chernarusplus",
    "Livonia": "https://izurvive.com/livonia",
    "Namalsk": "https://izurvive.com/namalsk",
    "Sakhal": "https://izurvive.com/sakhal",
    "Deer Isle": "https://izurvive.com/deerisle",
    "Esseker": "https://izurvive.com/esseker",
    "Takistan": "https://izurvive.com/takistan",
}

# ── Network-level ad blocker ──────────────────────────────────────────
# Blocks requests to known ad/tracking domains before they even load.
# This is the equivalent of uBlock Origin for QWebEngine.
AD_DOMAINS = [
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
]

# URL path fragments that indicate ad content
AD_PATH_FRAGMENTS = [
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


class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
    """Network-level ad blocker — blocks requests before they load."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._blocked = 0

    def interceptRequest(self, info):
        url = info.requestUrl().toString().lower()
        host = info.requestUrl().host().lower()

        # Block known ad domains
        for domain in AD_DOMAINS:
            if domain in host:
                info.block(True)
                self._blocked += 1
                return

        # Block ad-related URL paths
        for frag in AD_PATH_FRAGMENTS:
            if frag in url:
                info.block(True)
                self._blocked += 1
                return

    @property
    def blocked_count(self) -> int:
        return self._blocked


# ── DOM-level ad cleanup (backup for anything network blocker misses) ─
AD_SELECTORS = [
    '.ad-container', '.adsbygoogle', '#google_image_div',
    '[id^="div-gpt-ad"]', '.ad-slot', '.desktop-ad',
    '.ad-banner', '.ad-leaderboard', '.ad-sidebar',
    'ins.adsbygoogle', '[data-ad-slot]', '[data-ad-client]',
    '.ad-wrapper', '#ad-container', '.advertisement',
    'iframe[src*="googleads"]', 'iframe[src*="doubleclick"]',
    'iframe[src*="googlesyndication"]', 'iframe[src*="amazon-adsystem"]',
    '.sticky-ad', '.banner-ad', '.top-ad',
    '[id*="google_ads"]',
]

# CSS to hide ad containers immediately (before JS runs)
AD_HIDE_CSS = """
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


class DayZMapGUI(QWidget):
    """Ad-free iZurvive wrapper with map selector dropdown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_map = "Chernarus+ (Satellite)"
        self._interceptor = None
        self.init_ui()
        self.load_map(self.current_map)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Map selector bar
        selector_bar = QWidget()
        selector_bar.setFixedHeight(40)
        selector_bar.setStyleSheet("background-color: #0f1923; border-bottom: 1px solid #1a2a3a;")
        bar_layout = QHBoxLayout(selector_bar)
        bar_layout.setContentsMargins(12, 4, 12, 4)

        label = QLabel("MAP:")
        label.setStyleSheet("color: #00d9ff; font-weight: bold; font-size: 12px;")
        bar_layout.addWidget(label)

        self.map_combo = QComboBox()
        self.map_combo.addItems(MAP_OPTIONS.keys())
        self.map_combo.setCurrentText(self.current_map)
        self.map_combo.setStyleSheet("""
            QComboBox {
                background: #16213e;
                color: #e0e0e0;
                border: 1px solid #1a2a3a;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
                min-width: 200px;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: #0f1923;
                color: #e0e0e0;
                selection-background-color: rgba(0, 217, 255, 0.3);
                border: 1px solid #1a2a3a;
            }
        """)
        self.map_combo.currentTextChanged.connect(self.load_map)
        bar_layout.addWidget(self.map_combo)
        bar_layout.addStretch()

        layout.addWidget(selector_bar)

        # WebView with network-level ad blocking
        self.map_view = QWebEngineView()
        self._setup_ad_blocker()
        layout.addWidget(self.map_view)

        self.map_view.loadFinished.connect(self._inject_adblocker)

    def _setup_ad_blocker(self):
        """Install network-level request interceptor to block ad domains."""
        try:
            self._interceptor = AdBlockInterceptor(self)
            profile = QWebEngineProfile.defaultProfile()
            profile.setUrlRequestInterceptor(self._interceptor)
            log_info("Map: Network-level ad blocker installed")
        except Exception as e:
            log_error(f"Map: Failed to install network ad blocker: {e}")

    def load_map(self, map_name: str):
        self.current_map = map_name
        url = MAP_OPTIONS.get(map_name, MAP_OPTIONS["Chernarus+ (Satellite)"])
        try:
            self.map_view.load(QUrl(url))
            log_info(f"Loading map: {map_name} -> {url}")
        except Exception as e:
            log_error(f"Error loading map: {e}")

    def _inject_adblocker(self, success: bool):
        """Inject CSS + JS ad blocker as backup after page loads."""
        if not success:
            return

        # Phase 1: Inject CSS to hide ad containers immediately
        css_js = f"""
        (function() {{
            var style = document.createElement('style');
            style.textContent = `{AD_HIDE_CSS}`;
            document.head.appendChild(style);
        }})();
        """
        self.map_view.page().runJavaScript(css_js)

        # Phase 2: Remove ad elements and watch for new ones
        selectors_js = ", ".join(f"'{s}'" for s in AD_SELECTORS)
        js_code = f"""
        (function() {{
            try {{
                const selectors = [{selectors_js}];
                let removed = 0;

                function removeAds() {{
                    selectors.forEach(selector => {{
                        document.querySelectorAll(selector).forEach(el => {{
                            el.remove();
                            removed++;
                        }});
                    }});

                    // Remove iframes from known ad networks only
                    document.querySelectorAll('iframe').forEach(iframe => {{
                        var src = (iframe.src || '').toLowerCase();
                        if (src.includes('doubleclick') ||
                            src.includes('googlesyndication') || src.includes('amazon-adsystem') ||
                            src.includes('googleads')) {{
                            iframe.remove();
                            removed++;
                        }}
                    }});
                }}

                // Run immediately
                removeAds();

                // Run again after short delays (catches late-loading ads)
                setTimeout(removeAds, 500);
                setTimeout(removeAds, 1500);
                setTimeout(removeAds, 3000);
                setTimeout(removeAds, 5000);

                // Watch for dynamically injected ads
                const observer = new MutationObserver(() => removeAds());
                observer.observe(document.body, {{ childList: true, subtree: true }});

                console.log('DupeZ: Ad-blocker active, removed ' + removed + ' elements');
            }} catch (err) {{
                console.error('DupeZ ad-blocker error:', err);
            }}
        }})();
        """
        self.map_view.page().runJavaScript(js_code)

        blocked = self._interceptor.blocked_count if self._interceptor else 0
        log_info(f"Map ad-blocker injected (network blocked: {blocked}, DOM cleanup active)")
