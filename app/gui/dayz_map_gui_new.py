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

import os
import sys
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.map_host.launcher import (
    MapHostClient,
    consume_prewarmed_client,
    reparent_hwnd_into_container,
    resize_child_hwnd,
)
from app.gui.map_host.security_policy import assess_webengine_security
from app.logs.logger import log_error, log_info

#: Embed mode — "inproc" keeps the QWebEngineView in the main process and
#: uses the renderer selected before PyQt imports.
#:
#: The "child-experimental" mode is a source/development diagnostic. It
#: creates an unelevated WebEngine host with the interactive shell token,
#: authenticates the spawned PID, TCP peer, and HWND owner, then reparents
#: that HWND for real GPU rasterization. Frozen builds fail closed to this
#: module-launch path until a dedicated asInvoker host artifact exists.
#: Keep it gated behind a different env value than plain "child" so existing
#: ``$env:DUPEZ_MAP_EMBED = "child"`` shell settings silently fall
#: through to the working inproc path.
_EMBED_MODE: str = os.environ.get("DUPEZ_MAP_EMBED", "inproc").lower()
if _EMBED_MODE not in ("inproc", "child-experimental"):
    _EMBED_MODE = "inproc"

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
    )
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from app.gui.map_host.request_policy import install_reviewed_page, is_reviewed_map_url

    _WEBENGINE_AVAILABLE: bool = True
except Exception as _webengine_exc:  # noqa: BLE001 — we really do want everything
    _WEBENGINE_AVAILABLE = False
    _WEBENGINE_IMPORT_ERROR = f"{type(_webengine_exc).__name__}: {_webengine_exc}"
    log_error(
        "QtWebEngine not available — DayZ map will show a placeholder "
        f"(reason: {_WEBENGINE_IMPORT_ERROR})"
    )

# A deterministic troubleshooting/CI escape hatch. Importing QtWebEngine is
# safe on supported builds, while constructing QWebEngineView may terminate
# the process natively on headless or broken GPU stacks before Python can
# report an exception.
if os.environ.get("DUPEZ_DISABLE_WEBENGINE", "").strip().lower() in {
    "1", "true", "yes", "on",
}:
    _WEBENGINE_AVAILABLE = False
    _WEBENGINE_IMPORT_ERROR = "disabled by DUPEZ_DISABLE_WEBENGINE"
    log_info("QtWebEngine disabled; DayZ map will show a safe placeholder")

# ── Perf mode constants ─────────────────────────────────────────────
# Reviewed non-elevated sessions can select CPU raster when hardware probing
# cannot establish a supported GPU path. Elevated sessions never embed remote
# content, regardless of the renderer tier.
#
# Primary targets for software-raster perf:
#   1. Composited layers: Leaflet uses will-change/translate3d to force
#      GPU layer promotion. On software raster those layers become
#      full-bitmap blits the CPU has to composite on every frame.
#   2. Tile fade + zoom animations: multi-frame compositing work.
#   3. Hi-DPI pixel doubling: iZurvive runs at devicePixelRatio ≥ 1.5
#      on many Windows setups, quadrupling fragment work.
#
#: Zoom factor applied to the web view. 0.70 cuts pixel work by ~51%
#: (linear × linear). Aggressive but necessary on software raster — a
#: 1440p viewport rendering at 0.70 is ~1M pixels instead of 2M, which
#: is the difference between tolerable and unusable on a CPU pipeline.
#: Text becomes noticeably softer; the map tiles are pre-rasterized so
#: they scale cleanly. Users who need sharper text can click the
#: "Open in Browser" button for a full-native fallback.
_MAP_ZOOM_FACTOR: float = 0.70

#: CSS injected into every iZurvive page before the DOM settles. This
#: neutralises the GPU-assumed animations Leaflet uses by default, plus
#: kills tile fade transitions that force per-frame alpha compositing.
_PERF_CSS: str = """
    /* Kill tile fade-in — the biggest software-raster cost on pan */
    .leaflet-tile { transition: none !important; opacity: 1 !important; }
    .leaflet-fade-anim .leaflet-tile { transition: none !important; }
    .leaflet-fade-anim .leaflet-tile-loaded { opacity: 1 !important; }

    /* Pixelated rendering skips bilinear filtering during CSS transforms.
       On software raster this is a real win because the filter runs per
       pixel per frame; tiles are already pre-rasterized so we don't need
       filtering anyway. */
    .leaflet-tile {
        image-rendering: pixelated !important;
        image-rendering: -webkit-optimize-contrast !important;
    }

    /* During active drag, temporarily isolate the marker + overlay panes
       as their own composited layers so they blit instead of rerender.
       The 'dupez-dragging' class is added/removed by our JS. */
    .leaflet-container.dupez-dragging .leaflet-marker-pane,
    .leaflet-container.dupez-dragging .leaflet-overlay-pane,
    .leaflet-container.dupez-dragging .leaflet-shadow-pane,
    .leaflet-container.dupez-dragging .leaflet-tooltip-pane,
    .leaflet-container.dupez-dragging .leaflet-popup-pane {
        visibility: hidden !important;
    }

    /* Remove will-change hints — on software raster these force full
       bitmap reads instead of helping. */
    .leaflet-pane, .leaflet-tile-pane, .leaflet-overlay-pane,
    .leaflet-marker-pane, .leaflet-popup-pane, .leaflet-tile,
    .leaflet-map-pane, .leaflet-zoom-animated {
        will-change: auto !important;
        backface-visibility: visible !important;
        perspective: none !important;
    }

    /* Paint containment — tells the renderer the map container is an
       isolated paint context. Prevents invalidations in the map from
       triggering repaints of the iZurvive chrome (sidebar, toolbar)
       and vice versa. Huge win on software raster. */
    .leaflet-container {
        contain: layout paint style !important;
        content-visibility: auto !important;
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

    /* Hide cursor coordinate trackers if iZurvive repaints one per
       mousemove — these tiny updates cause full-container invalidations
       on some versions of the page. */
    .mouse-position, .leaflet-control-mouseposition {
        display: none !important;
    }
"""

__all__ = [
    "DayZMapGUI",
    "set_prewarmed_map_gui",
    "consume_prewarmed_map_gui",
]


# ── In-proc prewarm singleton ───────────────────────────────────────
#
# Dashboard constructs DayZMapGUI when the main window is built, which
# happens AFTER the splash init pipeline finishes. That means the
# QWebEngineView spin-up and the initial iZurvive tile download are
# both on the critical path between "splash closes" and "map is
# interactive", and the user sees a blank map tab for several seconds
# the first time they click it.
#
# The fix is to construct DayZMapGUI once, early, on the main thread
# during splash boot. The widget's __init__ calls load_map() which
# kicks the network load off immediately. While the splash pipeline
# runs (WinDivert init, controller init, plugin discovery, etc.) the
# widget is loading iZurvive in parallel. When Dashboard later calls
# consume_prewarmed_map_gui() it gets a fully-loaded widget instead
# of constructing a cold one.
#
# The widget is parented to None initially (top-level, hidden) and
# is reparented into the QStackedWidget by Qt automatically when
# Dashboard.addWidget() takes it.

_PREWARMED_MAP_GUI: Optional["DayZMapGUI"] = None


def set_prewarmed_map_gui(gui: "DayZMapGUI") -> None:
    """Register a pre-constructed DayZMapGUI for Dashboard to adopt."""
    global _PREWARMED_MAP_GUI
    _PREWARMED_MAP_GUI = gui


def consume_prewarmed_map_gui() -> Optional["DayZMapGUI"]:
    """Hand off the prewarmed DayZMapGUI. Returns None if none exists."""
    global _PREWARMED_MAP_GUI
    gui = _PREWARMED_MAP_GUI
    _PREWARMED_MAP_GUI = None
    return gui

# ── Map catalogue ───────────────────────────────────────────────────

# ── DayZ maps (iZurvive) ────────────────────────────────────────────
_DAYZ_MAPS: Dict[str, str] = {
    "Chernarus+ (Satellite)": "https://izurvive.com/chernarusplussatmap",
    "Chernarus+ (Topographic)": "https://izurvive.com/chernarusplus",
    "Livonia": "https://izurvive.com/livonia",
    "Namalsk": "https://izurvive.com/namalsk",
    "Sakhal": "https://izurvive.com/sakhal",
    "Deer Isle": "https://izurvive.com/deerisle",
    "Esseker": "https://izurvive.com/esseker",
    "Takistan": "https://izurvive.com/takistan",
}

MAP_OPTIONS: Dict[str, str] = dict(_DAYZ_MAPS)

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

_BROWSER_BTN_QSS: str = """
    QPushButton {
        background: #16213e; color: #00d9ff; border: 1px solid #00d9ff;
        border-radius: 4px; padding: 4px 12px; font-size: 11px;
        font-weight: bold;
    }
    QPushButton:hover {
        background: rgba(0, 217, 255, 0.15);
    }
    QPushButton:pressed {
        background: rgba(0, 217, 255, 0.3);
    }
"""

_PLACEHOLDER_QSS: str = (
    "color: #64748b; font-size: 14px; background: #0a0e1a; padding: 40px;"
)


# ── HWND container ──────────────────────────────────────────────────


class _HwndContainer(QWidget):
    """A native QWidget that hosts a reparented foreign HWND.

    Owns its own native HWND (via ``WA_NativeWindow``) so Win32
    ``SetParent`` has a concrete parent handle to target. When Qt
    resizes this widget, its ``resizeEvent`` forwards the new size
    to the embedded child HWND via ``MoveWindow`` so the map tracks
    the dashboard layout.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # Force a real native HWND — SetParent needs something real
        # on both sides of the call.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        # Dark background so nothing flashes white before the child
        # HWND becomes visible inside us.
        self.setStyleSheet("background: #0a0e1a;")
        self._child_hwnd: int = 0

    def set_child_hwnd(self, hwnd: int) -> None:
        self._child_hwnd = int(hwnd)
        # Immediately size-match so the initial render fills us.
        resize_child_hwnd(self._child_hwnd, self.width(), self.height())

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(event)
        if self._child_hwnd:
            resize_child_hwnd(
                self._child_hwnd, event.size().width(), event.size().height()
            )


# ── DayZMapGUI ──────────────────────────────────────────────────────

class DayZMapGUI(QWidget):
    """Ad-free iZurvive wrapper with map-selector dropdown.

    Falls back to a placeholder label when ``QWebEngineWidgets`` is
    unavailable (e.g. headless CI, missing system package).
    """

    webengineReadyChanged = pyqtSignal(bool)
    webengineStatusChanged = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.current_map: str = "Chernarus+ (Satellite)"
        self._interceptor: Any = None
        self._secured_page: Any = None
        self.map_view: Any = None  # QWebEngineView (inproc) or None
        self._security_blocked_reason = ""
        self._security_placeholder: Optional[QLabel] = None
        self._security_cleanup_in_progress = False
        self._security_stopped_view: Any = None
        self._security_cleanup_errors: Dict[str, str] = {}
        self._webengine_ready = False
        self._webengine_status = (
            "initializing" if _WEBENGINE_AVAILABLE else "unavailable"
        )

        # Child-host mode state (only used when _EMBED_MODE == "child")
        self._host_client: Optional[MapHostClient] = None
        self._host_container: Optional[QWidget] = None
        self._host_placeholder: Optional[QLabel] = None
        self._host_layout: Optional[QVBoxLayout] = None

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
        # Belt-and-suspenders: currentTextChanged handles programmatic
        # changes; activated fires on every user click (even re-selecting
        # the same item) which guards against Qt versions that silently
        # drop currentTextChanged when the embedded view is mid-load.
        self.map_combo.currentTextChanged.connect(self.load_map)
        self.map_combo.activated.connect(self._on_map_combo_activated)
        bar_layout.addWidget(self.map_combo)
        bar_layout.addStretch()

        # Escape-valve — opens the current map in the system browser.
        # Under ADR-0001 split mode we pick the reviewed Chromium raster
        # path automatically (probed hardware or CPU); the browser
        # button stays as a final fallback for users on very old GPUs.
        _tier = os.environ.get("DUPEZ_MAP_RENDERER_TIER", "tier3_cpu")
        if _tier == "tier1_hw":
            _btn_tip = (
                "Open the current map in your system browser.\n"
                "The embedded view is GPU-accelerated (hardware raster)."
            )
        else:
            _btn_tip = (
                "Open the current map in your system browser for full\n"
                "hardware-accelerated performance. The embedded view is\n"
                "running in CPU-raster compatibility mode."
            )
        self.browser_btn = QPushButton("Open in Browser ↗")
        self.browser_btn.setToolTip(_btn_tip)
        self.browser_btn.setStyleSheet(_BROWSER_BTN_QSS)
        self.browser_btn.clicked.connect(self._open_in_browser)
        bar_layout.addWidget(self.browser_btn)

        layout.addWidget(selector_bar)
        self._host_layout = layout

        if not self._enforce_webengine_security():
            return

        # Embed mode selection:
        #   * child  — spawn an unelevated WebEngine host process and
        #              reparent its HWND into our layout. Real GPU
        #              rasterization, no admin-token deadlock.
        #   * inproc — in-process QWebEngineView in an admitted,
        #              non-elevated session only.
        if _EMBED_MODE == "child-experimental" and _WEBENGINE_AVAILABLE:
            log_info("Map: embed mode = child (unelevated WebEngine host)")
            self._build_child_embed(layout)
        elif _WEBENGINE_AVAILABLE:
            log_info("Map: embed mode = inproc")
            self._build_inproc_webengine(layout)
        else:
            self._set_webengine_status("unavailable")
            reason = _WEBENGINE_IMPORT_ERROR or "PyQt6-WebEngine not installed"
            placeholder = QLabel(
                "Map unavailable — QtWebEngine failed to load.\n\n"
                f"Reason: {reason}\n\n"
                "Install a reviewed DupeZ runtime before retrying the embedded map."
            )
            placeholder.setStyleSheet(_PLACEHOLDER_QSS)
            placeholder.setWordWrap(True)
            layout.addWidget(placeholder)

    def _manual_map_url(self) -> str:
        """Use only the fixed HTTPS catalogue for the manual browser fallback."""
        return _DAYZ_MAPS.get(self.current_map, _DAYZ_MAPS["Chernarus+ (Satellite)"])

    @property
    def manual_url_ready(self) -> bool:
        """The approved URL is mounted as plain text with no retained browser."""
        label = self._security_placeholder
        return bool(
            self._security_blocked_reason
            and label is not None
            and self._host_layout is not None
            and self._host_layout.indexOf(label) >= 0
            and label.isVisibleTo(self)
            and label.textFormat() == Qt.TextFormat.PlainText
            and self._manual_map_url() in label.text().splitlines()
            and self.map_view is None
            and self._secured_page is None
            and self._host_client is None
            and not self._security_cleanup_errors
        )

    def _show_security_fallback(self) -> None:
        """Expose a copyable URL without invoking an elevated browser handler."""
        if self._host_layout is None:
            return
        if self._security_placeholder is None:
            self._security_placeholder = QLabel(self)
            self._security_placeholder.setTextFormat(Qt.TextFormat.PlainText)
            self._security_placeholder.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            self._security_placeholder.setStyleSheet(_PLACEHOLDER_QSS)
            self._security_placeholder.setWordWrap(True)
            self._host_layout.addWidget(self._security_placeholder, stretch=1)
        cleanup_note = ""
        if self._security_cleanup_errors:
            cleanup_note = (
                "\n\nCleanup is not confirmed: "
                + "; ".join(self._security_cleanup_errors.values())
                + " Click Manual browser URL to retry cleanup, or close DupeZ."
            )
        self._security_placeholder.setText(
            "Embedded map disabled for security.\n\n"
            f"{self._security_blocked_reason}\n\n"
            "Open this approved HTTPS address manually in your normal, "
            "non-administrator browser:\n"
            f"{self._manual_map_url()}\n\n"
            "DupeZ provides this address for manual use and will not launch a browser. "
            "Renderer settings do not enable embedded browsing in packaged builds."
            + cleanup_note
        )
        self.browser_btn.setText("Manual browser URL")
        self.browser_btn.setToolTip(
            "The approved address is shown below. DupeZ will not launch a browser "
            "from this blocked security context."
        )

    def _enforce_webengine_security(self) -> bool:
        """Fail closed before construction/navigation, including child fallback."""
        if not self._security_blocked_reason:
            try:
                decision = assess_webengine_security()
                if decision.allowed:
                    return True
                self._security_blocked_reason = decision.reason
            except Exception as exc:
                self._security_blocked_reason = "The browser security policy could not be verified."
                log_error(f"Map: browser security verification failed ({type(exc).__name__})")
            if not self._security_blocked_reason:
                self._security_blocked_reason = "The browser security requirements were not met."
        self._set_webengine_status("unavailable")
        # Once denied, do not let delayed signals or a later environment edit
        # resume this widget. Cleanup is independent and retains a failed child
        # owner for close/retry; no new browser is created as a fallback.
        if not self._security_cleanup_in_progress:
            self._security_cleanup_in_progress = True
            try:
                if self.map_view is not None:
                    view = self.map_view
                    if view is not self._security_stopped_view:
                        try:
                            view.stop()
                            self._security_stopped_view = view
                        except Exception as exc:
                            log_error(f"Map: blocked view stop failed ({type(exc).__name__})")
                    try:
                        view.hide()
                    except Exception as exc:
                        log_error(f"Map: blocked view hide failed ({type(exc).__name__})")
                    if self._host_layout is not None:
                        try:
                            self._host_layout.removeWidget(view)
                        except Exception as exc:
                            log_error(f"Map: blocked view detach failed ({type(exc).__name__})")
                    # stop() only cancels navigation; it does not terminate
                    # already-loaded JavaScript. Dispose the page-owning view
                    # at Qt's next deferred-delete boundary. Keep ownership on
                    # scheduling failure so a later denied action can retry.
                    try:
                        view.deleteLater()
                    except Exception as exc:
                        self._security_cleanup_errors["view"] = (
                            f"Embedded browser teardown could not be scheduled ({type(exc).__name__})."
                        )
                        log_error(f"Map: blocked view disposal failed ({type(exc).__name__})")
                    else:
                        self.map_view = None
                        self._secured_page = None
                        self._interceptor = None
                        self._security_stopped_view = None
                        self._security_cleanup_errors.pop("view", None)
                if self._host_client is not None:
                    client = self._host_client
                    try:
                        client.stop()
                    except Exception as exc:
                        self._security_cleanup_errors["child"] = (
                            f"Map child teardown failed ({type(exc).__name__})."
                        )
                        log_error(f"Map: blocked child cleanup failed ({type(exc).__name__})")
                    else:
                        if self._host_client is client:
                            self._host_client = None
                        self._security_cleanup_errors.pop("child", None)
                if self._host_container is not None:
                    self._host_container.hide()
                if self._host_placeholder is not None:
                    self._host_placeholder.hide()
            finally:
                self._security_cleanup_in_progress = False
        self._show_security_fallback()
        return False

    @property
    def webengine_ready(self) -> bool:
        """Whether the current map navigation completed successfully."""

        return bool(self._webengine_ready)

    @property
    def webengine_status(self) -> str:
        """Operational browser state used by lazy/dashboard consumers."""

        return self._webengine_status

    def _set_webengine_status(self, status: str) -> None:
        if self._security_blocked_reason:
            status = "unavailable"
        if status not in {
            "unavailable",
            "initializing",
            "loading",
            "ready",
            "failed",
            "crashed",
        }:
            raise ValueError("invalid WebEngine status")
        previous_status = self._webengine_status
        previous_ready = self._webengine_ready
        self._webengine_status = status
        self._webengine_ready = status == "ready"
        if previous_status != status:
            self.webengineStatusChanged.emit(status)
        if previous_ready != self._webengine_ready:
            self.webengineReadyChanged.emit(self._webengine_ready)

    def _build_inproc_webengine(
        self,
        layout: QVBoxLayout,
        *,
        stretch: int = 0,
    ) -> None:
        """Construct and secure one in-process WebEngine view."""

        if not self._enforce_webengine_security():
            return
        self._set_webengine_status("initializing")
        view: Any = None
        try:
            view = QWebEngineView()
            self.map_view = view
            self._secured_page = install_reviewed_page(view)
            self._install_ad_blocker()
            self._apply_perf_settings()
            view.loadStarted.connect(self._on_inproc_load_started)
            view.loadFinished.connect(self._on_inproc_load_finished)
            view.loadFinished.connect(self._inject_dom_adblocker)
            if self._uses_software_renderer():
                view.loadFinished.connect(self._inject_perf_tweaks)
                view.loadFinished.connect(self._boost_renderer_priority)
            view.page().renderProcessTerminated.connect(
                self._on_render_process_terminated
            )
            layout.addWidget(view, stretch=stretch)
            log_info("Map: WebEngine boundary initialized; awaiting navigation")
        except Exception as exc:
            self._set_webengine_status("failed")
            self.map_view = None
            self._secured_page = None
            if view is not None:
                view.deleteLater()
            log_error(
                "Map: WebEngine initialization failed "
                f"({type(exc).__name__})"
            )
            raise RuntimeError("map WebEngine initialization failed") from None

    @staticmethod
    def _uses_software_renderer() -> bool:
        return os.environ.get(
            "DUPEZ_MAP_RENDERER_TIER", "tier3_cpu"
        ) == "tier3_cpu"

    def _on_inproc_load_started(self) -> None:
        if not self._enforce_webengine_security():
            return
        self._set_webengine_status("loading")

    def _on_inproc_load_finished(self, success: bool) -> None:
        if not self._enforce_webengine_security():
            return
        self._set_webengine_status("ready" if success else "failed")
        if success:
            log_info("Map: WebEngine navigation ready")
        else:
            log_error("Map: WebEngine navigation failed")

    def _on_render_process_terminated(
        self,
        termination_status: Any,
        exit_code: int,
    ) -> None:
        """Invalidate readiness when Chromium reports renderer termination."""

        self._set_webengine_status("crashed")
        status_name = getattr(termination_status, "name", "unknown")
        log_error(
            "Map: WebEngine renderer terminated "
            f"(status={status_name}, exit_code={int(exit_code)})"
        )

    # ── Ad blocker setup ────────────────────────────────────────────

    def _install_ad_blocker(self) -> None:
        """Retain the reviewed page's network interceptor and memory-only cache.

        ``install_reviewed_page`` owns the dedicated off-record profile and
        policy. Do not replace that interceptor or enable persistent storage.
        Cache sizing is optional; a missing network boundary is a hard failure.
        """
        try:
            page = self.map_view.page()
            self._interceptor = page._dupez_interceptor
            if self._interceptor is None:
                raise RuntimeError("reviewed map interceptor is missing")
            profile = page.profile()
            try:
                profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
                profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
            except Exception as cache_exc:
                log_error(
                    "Map: cache tuning failed (non-fatal) "
                    f"({type(cache_exc).__name__})"
                )
            log_info("Map: Network-level ad blocker installed")
        except Exception as exc:
            self._interceptor = None
            log_error(
                "Map: failed to install network policy "
                f"({type(exc).__name__})"
            )
            raise RuntimeError("map network policy initialization failed") from None

    def _reviewed_script_page(self) -> Any:
        """Never inject application scripts into an unreviewed navigation."""
        if not self._enforce_webengine_security() or self.map_view is None:
            return None
        try:
            page = self.map_view.page()
            if is_reviewed_map_url(page.url().toString()):
                return page
        except Exception as exc:
            log_error(f"Map: script origin verification failed ({type(exc).__name__})")
        return None

    # ── Software-raster perf tuning ─────────────────────────────────

    def _apply_perf_settings(self) -> None:
        """Apply common hardening and CPU-only raster tuning.

        When an admitted, non-elevated session uses CPU raster, the
        cheapest performance improvements on that pipeline are:
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
            settings = self.map_view.settings()
            A = QWebEngineSettings.WebAttribute
            common_settings = (
                (A.PluginsEnabled, False),
                (A.HyperlinkAuditingEnabled, False),
                (A.AutoLoadIconsForPage, False),
                (A.ShowScrollBars, True),
                (A.LocalStorageEnabled, True),   # iZurvive preferences
                (A.JavascriptEnabled, True),
                (A.ErrorPageEnabled, False),
            )
            for attr, value in common_settings:
                try:
                    settings.setAttribute(attr, value)
                except Exception:
                    pass  # some attrs vary by Qt version

            if self._uses_software_renderer():
                # ~51% pixel-area reduction at the cost of softer text.
                self.map_view.setZoomFactor(_MAP_ZOOM_FACTOR)
                for attr in (
                    A.ScrollAnimatorEnabled,
                    A.WebGLEnabled,
                    A.Accelerated2dCanvasEnabled,
                ):
                    try:
                        settings.setAttribute(attr, False)
                    except Exception:
                        pass
                log_info(
                    f"Map: CPU perf settings applied (zoom={_MAP_ZOOM_FACTOR}, "
                    "WebGL/2DCanvas off, scroll animator off)"
                )
            else:
                log_info("Map: hardware renderer settings retained")
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
        if not success or not self._uses_software_renderer():
            return
        page = self._reviewed_script_page()
        if page is None:
            return

        # Phase 1: CSS — synchronous, kills compositing work immediately
        css_js = (
            "(function(){"
            "var s=document.createElement('style');"
            f"s.textContent=`{_PERF_CSS}`;"
            "document.head.appendChild(s);"
            "})();"
        )
        page.runJavaScript(css_js)

        # Phase 2: JS — find the live Leaflet map, turn off animations,
        # force devicePixelRatio=1 on the page, and install a
        # requestAnimationFrame throttle that caps frame delivery at
        # ~33fps. On software raster each frame costs roughly twice as
        # much as on GPU, so halving the framerate roughly doubles the
        # headroom without noticeably affecting pan/zoom feel (Leaflet
        # drags still track the cursor because mousemove events are
        # processed regardless of rAF rate).
        tune_js = r"""
        (function() {
            try {
                // ── rAF throttle: cap animation callbacks at ~33fps ──
                // We don't monkey-patch requestAnimationFrame globally
                // because iZurvive's non-map JS (menus, overlays) uses
                // it too and we don't want to break those. Instead we
                // wrap it so callbacks are coalesced to a 30ms window.
                const origRaf = window.requestAnimationFrame;
                const origCaf = window.cancelAnimationFrame;
                const FRAME_MS = 30;  // ~33fps
                let lastFrame = 0;
                let pending = [];
                let scheduled = false;
                window.requestAnimationFrame = function(cb) {
                    const id = Symbol('raf');
                    pending.push({id: id, cb: cb});
                    if (!scheduled) {
                        scheduled = true;
                        const now = performance.now();
                        const wait = Math.max(0, FRAME_MS - (now - lastFrame));
                        setTimeout(function() {
                            lastFrame = performance.now();
                            const batch = pending;
                            pending = [];
                            scheduled = false;
                            origRaf.call(window, function(ts) {
                                for (const item of batch) {
                                    try { item.cb(ts); } catch(e) {}
                                }
                            });
                        }, wait);
                    }
                    return id;
                };
                window.cancelAnimationFrame = function(id) {
                    pending = pending.filter(function(p) { return p.id !== id; });
                };

                // ── devicePixelRatio override ──
                // Force page-level DPR to 1. Leaflet uses this to pick
                // tile sizes (retina 2× tiles vs 1× tiles); forcing 1
                // halves the pixel work per tile.
                try {
                    Object.defineProperty(window, 'devicePixelRatio', {
                        get: function() { return 1; },
                        configurable: true
                    });
                } catch(e) {}

                // ── Find + tune the live Leaflet map ──
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
                        map.options.wheelDebounceTime = 80;
                        map.options.wheelPxPerZoomLevel = 140;
                        map.options.preferCanvas = true;
                        map._fadeAnimated = false;
                        map._zoomAnimated = false;

                        // ── Tile layer tuning ──
                        // Big keepBuffer (12) gives the drag a large
                        // cushion of pre-loaded tiles. updateWhenIdle
                        // defers any tile refresh until the drag ends.
                        const tileLayers = [];
                        map.eachLayer && map.eachLayer(function(layer) {
                            if (layer.options && layer._update) {
                                layer.options.updateWhenIdle = true;
                                layer.options.updateWhenZooming = false;
                                layer.options.updateInterval = 500;
                                layer.options.keepBuffer = 12;
                                tileLayers.push(layer);
                            }
                        });

                        // ── HARD FREEZE: monkey-patch _update ──
                        // updateWhenIdle is a Leaflet option but some
                        // code paths still call _update mid-move. We
                        // wrap _update to hard no-op when dragging or
                        // zooming is in progress. This is THE biggest
                        // software-raster win — it completely stops
                        // tile decode/paint/composite during drags.
                        tileLayers.forEach(function(layer) {
                            if (layer.__dupezPatched) return;
                            const origUpdate = layer._update.bind(layer);
                            layer._update = function(center) {
                                const dragging = map.dragging && map.dragging._draggable && map.dragging._draggable._moving;
                                if (dragging || map._animatingZoom) return;
                                return origUpdate(center);
                            };
                            layer.__dupezPatched = true;
                        });

                        // ── Pane-hiding during drag ──
                        // Marker/overlay panes are composited every
                        // frame during a drag on software raster.
                        // Hide them entirely while dragging and
                        // restore on dragend. Done via a CSS class
                        // toggle so the CSS rules pick it up.
                        if (!map.__dupezDragHide) {
                            const container = map.getContainer();
                            const onStart = function() {
                                container.classList.add('dupez-dragging');
                            };
                            const onEnd = function() {
                                container.classList.remove('dupez-dragging');
                                // Trigger a deferred tile refresh now
                                // that the drag is over.
                                tileLayers.forEach(function(layer) {
                                    try { layer._update(); } catch(e) {}
                                });
                            };
                            map.on('movestart dragstart zoomstart', onStart);
                            map.on('moveend dragend zoomend', onEnd);
                            map.__dupezDragHide = true;
                        }

                        // ── Tile prefetch ──
                        // Warm the tile cache by preloading 2 rings
                        // of tiles around the current viewport, at
                        // the current zoom level only. Deferred with
                        // setTimeout so it doesn't compete with the
                        // initial render.
                        setTimeout(function() {
                            try {
                                if (tileLayers.length === 0) return;
                                const layer = tileLayers[0];
                                const bounds = map.getPixelBounds();
                                const tileSize = layer.getTileSize();
                                const zoom = map.getZoom();
                                const minX = Math.floor(bounds.min.x / tileSize.x) - 2;
                                const maxX = Math.floor(bounds.max.x / tileSize.x) + 2;
                                const minY = Math.floor(bounds.min.y / tileSize.y) - 2;
                                const maxY = Math.floor(bounds.max.y / tileSize.y) + 2;
                                let prefetched = 0;
                                for (let x = minX; x <= maxX; x++) {
                                    for (let y = minY; y <= maxY; y++) {
                                        try {
                                            const url = layer.getTileUrl({x: x, y: y, z: zoom});
                                            const img = new Image();
                                            img.src = url;
                                            prefetched++;
                                        } catch(e) {}
                                    }
                                }
                                console.log('DupeZ: prefetched ' + prefetched + ' tiles');
                            } catch(e) {
                                console.warn('DupeZ: prefetch failed', e);
                            }
                        }, 1500);

                        try { map.invalidateSize(false); } catch(e) {}

                        console.log('DupeZ: Leaflet perf tune applied (hard freeze on drag)');
                        return true;
                    } catch (e) {
                        console.error('DupeZ: tune failed', e);
                        return false;
                    }
                }

                let attempts = 0;
                const maxAttempts = 8;
                function attempt() {
                    const map = findMap();
                    if (tune(map)) return;
                    if (++attempts < maxAttempts) {
                        setTimeout(attempt, 400);
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

    def _boost_renderer_priority(self, success: bool) -> None:
        """Raise QtWebEngineProcess renderer to HIGH_PRIORITY_CLASS.

        QtWebEngine runs the Chromium renderer in a child process
        named ``QtWebEngineProcess.exe``. By default it runs at
        NORMAL priority, which means it competes for CPU with
        DupeZ's WinDivert packet workers, the network scanner, and
        the ML classifier. On a software-raster pipeline every
        stolen slice is a dropped frame.

        Finds all child ``QtWebEngineProcess`` descendants of the
        current process and bumps them to ``HIGH_PRIORITY_CLASS``.
        Failure is non-fatal (requires psutil + Windows ctypes).
        """
        if (
            not success
            or not self._enforce_webengine_security()
            or not self._uses_software_renderer()
            or os.name != "nt"
        ):
            return
        try:
            import psutil  # noqa: PLC0415 — optional dep
        except ImportError:
            log_info("Map: renderer priority boost skipped (psutil not installed)")
            return
        try:
            import ctypes  # noqa: PLC0415

            HIGH_PRIORITY_CLASS = 0x00000080
            PROCESS_SET_INFORMATION = 0x0200

            me = psutil.Process()
            boosted = 0
            for child in me.children(recursive=True):
                try:
                    if "QtWebEngineProcess" not in child.name():
                        continue
                    hp = ctypes.windll.kernel32.OpenProcess(
                        PROCESS_SET_INFORMATION, False, child.pid
                    )
                    if not hp:
                        continue
                    try:
                        ok = ctypes.windll.kernel32.SetPriorityClass(
                            hp, HIGH_PRIORITY_CLASS
                        )
                        if ok:
                            boosted += 1
                    finally:
                        ctypes.windll.kernel32.CloseHandle(hp)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if boosted:
                log_info(
                    f"Map: boosted {boosted} QtWebEngineProcess renderer(s) "
                    "to HIGH_PRIORITY_CLASS"
                )
        except Exception as exc:
            log_error(f"Map: renderer priority boost failed: {exc}")

    # ── Child-host embed mode ───────────────────────────────────────

    def _build_child_embed(self, layout: QVBoxLayout) -> None:
        """Spawn (or adopt) the unelevated WebEngine host and prep the slot.

        Placeholder + plain QWidget container go into the layout
        immediately. The container has ``WA_NativeWindow`` so it owns
        a real HWND that we can pass to Win32 ``SetParent`` as soon
        as the child reports its own HWND.

        If a prewarmed client already exists (from splash), it is
        adopted here and its signals are rewired — saving 2-5s of
        child spawn + Chromium init + initial tile load. Otherwise a
        fresh ``MapHostClient`` is started on demand.

        On any spawn / connect / reparent failure, ``_on_host_failed``
        tears down the child-mode state and falls back to the
        in-process ``QWebEngineView`` only if the security gate still admits it.
        """
        if not self._enforce_webengine_security():
            return
        self._set_webengine_status("initializing")

        # Placeholder shown while the child is booting. It will be
        # removed (and the native container revealed) on hwndReceived.
        self._host_placeholder = QLabel(
            "Starting map host…\n\n"
            "The map will appear here once Chromium is ready."
        )
        self._host_placeholder.setStyleSheet(_PLACEHOLDER_QSS)
        self._host_placeholder.setWordWrap(True)
        layout.addWidget(self._host_placeholder, stretch=1)

        # Container that will host the reparented HWND. Must own a
        # real native HWND (WA_NativeWindow) so we have something to
        # pass as the second arg of Win32 SetParent.
        container = _HwndContainer(self)
        container.setMinimumSize(320, 240)
        container.hide()  # revealed after reparent succeeds
        layout.addWidget(container, stretch=1)
        self._host_container = container

        # Try to adopt a prewarmed client before starting a new one.
        prewarmed = consume_prewarmed_client()
        if prewarmed is not None:
            log_info("Map: adopting prewarmed map host client")
            self._host_client = prewarmed
            prewarmed.setParent(self)
            self._wire_host_client(prewarmed)
            # If the child already reported its HWND before we got
            # here, fire the handler synchronously now.
            if prewarmed.hwnd is not None:
                self._on_host_hwnd_received(prewarmed.hwnd)
            return

        # Cold start path — spawn a fresh child.
        client = MapHostClient(self)
        self._host_client = client
        self._wire_host_client(client)

        if not client.start() and self._host_client is client:
            self._on_host_failed("spawn failed")

    def _wire_host_client(self, client: MapHostClient) -> None:
        client.hwndReceived.connect(self._on_host_hwnd_received)
        client.connectionFailed.connect(self._on_host_failed)
        client.disconnected.connect(self._on_host_disconnected)
        client.loadStarted.connect(self._on_host_load_started)
        client.loadFinished.connect(self._on_host_load_finished)
        client.renderProcessTerminated.connect(
            self._on_host_render_process_terminated
        )

    def _on_host_load_started(self) -> None:
        if not self._enforce_webengine_security():
            return
        self._set_webengine_status("loading")

    def _on_host_load_finished(self, success: bool) -> None:
        if not self._enforce_webengine_security():
            return
        self._set_webengine_status("ready" if success else "failed")
        if success:
            log_info("Map: child WebEngine navigation ready")
        else:
            log_error("Map: child WebEngine navigation failed")

    def _on_host_render_process_terminated(
        self,
        status: str,
        exit_code: int,
    ) -> None:
        self._set_webengine_status("crashed")
        log_error(
            "Map: child WebEngine renderer terminated "
            f"(status={status}, exit_code={exit_code})"
        )

    def _on_host_hwnd_received(self, hwnd: int) -> None:
        """Reparent the child's HWND into our native container.

        Uses Win32 ``SetParent`` (via the launcher helper) instead of
        Qt's ``QWindow.fromWinId`` + ``createWindowContainer`` path,
        which proved unreliable for foreign HWNDs across process
        boundaries — on our first test the child's frameless window
        escaped the reparent and ended up covering the screen.
        """
        if not self._enforce_webengine_security():
            return
        if self._host_layout is None or self._host_container is None:
            return
        try:
            container = self._host_container

            # Make sure the container has a real native HWND before
            # we reparent into it. processEvents flushes the pending
            # native window creation from the preceding layout add.
            container.show()
            # Flush pending events so the container's native HWND
            # is fully realized before SetParent touches it.
            QApplication.processEvents()

            if not self._enforce_webengine_security():
                return

            parent_hwnd = int(container.winId())
            if not parent_hwnd:
                raise RuntimeError("container has no native HWND")

            width = max(container.width(), 320)
            height = max(container.height(), 240)

            ok = reparent_hwnd_into_container(hwnd, parent_hwnd, width, height)
            if not ok:
                raise RuntimeError("reparent_hwnd_into_container returned False")

            # Remember the child HWND so container resize events can
            # MoveWindow it to track the layout.
            container.set_child_hwnd(hwnd)

            # Drop the placeholder now that the native child is in.
            if self._host_placeholder is not None:
                self._host_layout.removeWidget(self._host_placeholder)
                self._host_placeholder.deleteLater()
                self._host_placeholder = None

            # If prewarm already loaded the current map this is a
            # no-op at the browser level (same URL), but it's cheap
            # and guarantees we're showing what DayZMapGUI thinks.
            url = MAP_OPTIONS.get(
                self.current_map, MAP_OPTIONS["Chernarus+ (Satellite)"]
            )
            if self._host_client is not None:
                self._set_webengine_status("loading")
                self._host_client.load(url)
            log_info(
                f"Map: reparented child hwnd=0x{hwnd:x} into container, "
                f"loaded {self.current_map}"
            )
            log_info("Map: child WebEngine boundary initialized")
        except Exception as exc:
            log_error(
                f"Map: HWND reparent failed ({exc!r}) — falling back to inproc"
            )
            self._on_host_failed(f"reparent failed: {exc}")

    def _on_host_failed(self, reason: str) -> None:
        """Spawn/connect/reparent failed — fall back to inproc view.

        Keeps the map path alive even when the child architecture
        trips on COM, missing pywin32, HWND reparent glitches, etc.
        """
        if not self._enforce_webengine_security():
            return
        self._set_webengine_status("failed")
        log_error(f"Map: child host failed ({reason}) — falling back to inproc")
        # Tear down any host state.
        if self._host_client is not None:
            try:
                self._host_client.stop()
            except Exception:
                pass
            self._host_client = None
        if self._host_placeholder is not None and self._host_layout is not None:
            self._host_layout.removeWidget(self._host_placeholder)
            self._host_placeholder.deleteLater()
            self._host_placeholder = None
        if self._host_container is not None and self._host_layout is not None:
            self._host_layout.removeWidget(self._host_container)
            self._host_container.deleteLater()
            self._host_container = None

        # Build the in-proc view if we don't already have one.
        if self.map_view is None and _WEBENGINE_AVAILABLE and self._host_layout is not None:
            try:
                self._build_inproc_webengine(self._host_layout, stretch=1)
                self.load_map(self.current_map)
            except RuntimeError:
                placeholder = QLabel(
                    "Map unavailable — the secured browser could not initialize.\n\n"
                    "Restart DupeZ or open the map in your system browser."
                )
                placeholder.setStyleSheet(_PLACEHOLDER_QSS)
                placeholder.setWordWrap(True)
                self._host_layout.addWidget(placeholder, stretch=1)

    def _on_host_disconnected(self) -> None:
        """Child exited unexpectedly — fall back so the user keeps a map."""
        self._set_webengine_status("crashed")
        # Only treat this as a failure if we hadn't already replaced
        # the client (e.g. during shutdown self._host_client is None).
        if self._host_client is not None:
            self._on_host_failed("child disconnected")

    # ── Map loading ─────────────────────────────────────────────────

    def _on_map_combo_activated(self, index: int) -> None:
        """Handle explicit user selection from the combo dropdown.

        ``activated`` fires on every user click — even re-selecting the
        current item — so this catches cases where ``currentTextChanged``
        was silently swallowed (Qt race with in-flight page loads).
        """
        name = self.map_combo.itemText(index)
        if name:
            self.load_map(name)

    def load_map(self, map_name: str) -> None:
        """Navigate the active view (inproc or child) to the selected map."""
        url = MAP_OPTIONS.get(map_name)
        if url is None:
            log_error(
                f"Map: unknown map name {map_name!r}, "
                "falling back to Chernarus+ (Satellite)"
            )
            url = MAP_OPTIONS.get(
                "Chernarus+ (Satellite)",
                "https://izurvive.com/chernarusplussatmap",
            )

        if not self._enforce_webengine_security():
            self.current_map = map_name
            self._show_security_fallback()
            return

        # De-duplicate rapid calls (both currentTextChanged and
        # activated fire on the same user click).
        _last = getattr(self, "_last_loaded_url", None)
        if (
            url == _last
            and map_name == self.current_map
            and self.webengine_status in {"loading", "ready"}
        ):
            return
        self.current_map = map_name
        self._last_loaded_url = url  # type: ignore[attr-defined]
        log_info(f"Map: load_map — name={map_name!r}")

        # Child-host path: push the URL over IPC. If the child isn't
        # connected yet, _on_host_hwnd_received will push the current
        # URL once it's up, so we can safely no-op here.
        if self._host_client is not None and self._host_container is not None:
            try:
                if self._host_client.hwnd is not None:
                    self._set_webengine_status("loading")
                self._host_client.load(url)
                log_info(f"Map: navigating (child): {map_name}")
            except Exception as exc:
                self._set_webengine_status("failed")
                log_error(f"Map: child host load failed: {exc}")
            return

        if self.map_view is None:
            log_error("Map: load_map — map_view is None, cannot navigate")
            return
        try:
            # Cancel any in-flight navigation first — without this,
            # calling load() while the previous page is still fetching
            # tiles/ads can be silently dropped by some Qt versions.
            if _last is not None:
                self.map_view.stop()
            self._set_webengine_status("loading")
            self.map_view.load(QUrl(url))
            log_info(f"Map: navigating (inproc): {map_name}")
        except Exception as exc:
            self._set_webengine_status("failed")
            log_error(f"Map: inproc load failed: {exc}")

    # ── Cleanup ─────────────────────────────────────────────────────

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        """Tear down the unelevated child host on widget close."""
        try:
            if self._host_client is not None:
                self._host_client.stop()
                self._host_client = None
        except Exception as exc:
            log_error(f"Map: host client cleanup failed: {exc}")
        super().closeEvent(event)

    def _open_in_browser(self) -> None:
        """Open the current map in the system's default browser.

        Escape valve for users whose embedded renderer or graphics driver
        cannot provide acceptable Leaflet performance.
        """
        if not self._enforce_webengine_security():
            return
        url = self._manual_map_url()
        try:
            if QDesktopServices.openUrl(QUrl(url)):
                log_info(f"Opened map in system browser: {self.current_map}")
            else:
                log_error("System browser refused the reviewed map URL")
        except Exception as exc:
            log_error(f"Failed to open map in browser: {exc}")

    # ── DOM-level ad cleanup ────────────────────────────────────────

    def _inject_dom_adblocker(self, success: bool) -> None:
        """Inject CSS + JS ad-blocker as backup after page load completes."""
        if not success:
            return
        page = self._reviewed_script_page()
        if page is None:
            return

        # Phase 1: CSS — hide ad containers immediately
        css_js = (
            "(function() {"
            "  var style = document.createElement('style');"
            f"  style.textContent = `{_AD_HIDE_CSS}`;"
            "  document.head.appendChild(style);"
            "})();"
        )
        page.runJavaScript(css_js)

        # Phase 2: JS — remove ad elements via fixed-schedule sweeps.
        #
        # PERF: we previously ran a debounced MutationObserver here.
        # On software raster even a 250ms-debounced observer costs
        # measurable CPU because each mutation event still allocates
        # and runs through the JS dispatcher, and iZurvive's Leaflet
        # can fire thousands of mutations per pan. Switched to a
        # fixed schedule (initial + 1s + 3s + 8s) with no observer —
        # iZurvive's ad layout is static after load, so watching
        # forever just burns cycles. One combined-selector DOM walk
        # per pass.
        selectors_js = ", ".join(f"'{s}'" for s in AD_SELECTORS)
        remove_js = f"""
        (function() {{
            try {{
                const combinedSelector = [{selectors_js}].join(', ');
                let totalRemoved = 0;

                function removeAds() {{
                    let removed = 0;
                    document.querySelectorAll(combinedSelector).forEach(el => {{
                        el.remove();
                        removed++;
                    }});
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
                    totalRemoved += removed;
                    return removed;
                }}

                // Fixed schedule: initial sweep then catches for
                // late-loading ad scripts. No MutationObserver — the
                // live pan/zoom work is too expensive to observe.
                removeAds();
                setTimeout(removeAds, 1000);
                setTimeout(removeAds, 3000);
                setTimeout(function() {{
                    removeAds();
                    console.log('DupeZ: ad-blocker complete, total removed=' + totalRemoved);
                }}, 8000);
            }} catch (err) {{
                console.error('DupeZ ad-blocker error:', err);
            }}
        }})();
        """
        page.runJavaScript(remove_js)

        blocked = self._interceptor.blocked_count if self._interceptor else 0
        log_info(f"Map ad-blocker injected (network blocked: {blocked}, DOM cleanup active)")
