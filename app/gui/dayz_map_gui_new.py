#!/usr/bin/env python3
"""
DayZ Map GUI — Ad-free iZurvive with map selector
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView
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

# Aggressive ad selectors — covers Google Ads, iZurvive custom ads, generic patterns
AD_SELECTORS = [
    '.ad-container', '.adsbygoogle', '#google_image_div',
    '[id^="div-gpt-ad"]', '.ad-slot', '.desktop-ad',
    '.ad-banner', '.ad-leaderboard', '.ad-sidebar',
    'ins.adsbygoogle', '[data-ad-slot]', '[data-ad-client]',
    '.ad-wrapper', '#ad-container', '.advertisement',
    'iframe[src*="googleads"]', 'iframe[src*="doubleclick"]',
    '.sticky-ad', '.banner-ad', '.top-ad',
]


class DayZMapGUI(QWidget):
    """Ad-free iZurvive wrapper with map selector dropdown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_map = "Chernarus+ (Satellite)"
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

        # WebView
        self.map_view = QWebEngineView()
        layout.addWidget(self.map_view)

        self.map_view.loadFinished.connect(self._inject_adblocker)

    def load_map(self, map_name: str):
        self.current_map = map_name
        url = MAP_OPTIONS.get(map_name, MAP_OPTIONS["Chernarus+ (Satellite)"])
        try:
            self.map_view.load(QUrl(url))
            log_info(f"Loading map: {map_name} -> {url}")
        except Exception as e:
            log_error(f"Error loading map: {e}")

    def _inject_adblocker(self, success: bool):
        if not success:
            return

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
                }}

                // Initial removal
                removeAds();

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
        log_info("Map ad-blocker injected (with MutationObserver)")
