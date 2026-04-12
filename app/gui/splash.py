# app/gui/splash.py — DupeZ Splash Screen
"""
Animated splash screen that displays during app initialization.
Matches the DupeZ dark navy/cyan theme. Runs the full init pipeline
(logging, WinDivert, controller, plugins) on a background thread
and reports progress via status messages + progress bar.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
import threading
from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import (
    QColor, QFont, QFontDatabase, QLinearGradient, QPainter,
    QPainterPath, QPen, QRadialGradient, QBrush, QIcon,
)
from PyQt6.QtWidgets import QSplashScreen, QApplication, QWidget

from app.core.updater import CURRENT_VERSION

# ── Theme constants (match refined dark theme) ───────────────────
_BG_DARK      = QColor(4, 7, 16)        # #040710
_BG_MAIN      = QColor(5, 8, 16)        # #050810
_BG_SURFACE   = QColor(12, 18, 32)      # #0c1220
_CYAN         = QColor(0, 240, 255)     # #00f0ff
_CYAN_DIM     = QColor(0, 240, 255, 50)
_CYAN_GLOW    = QColor(0, 240, 255, 25)
_AMBER        = QColor(251, 191, 36)    # #fbbf24
_TEXT_PRIMARY  = QColor(226, 232, 240)   # #e2e8f0
_TEXT_MUTED    = QColor(100, 116, 139)   # #64748b
_RED           = QColor(255, 107, 107)   # #ff6b6b
_GREEN         = QColor(0, 255, 136)     # #00ff88

__all__ = ["DupeZSplash"]


class DupeZSplash(QSplashScreen):
    """Full-screen-ish splash with animated glow, progress bar, and
    status messages.  Driven by ``run_init_pipeline()``."""

    # Signals for thread-safe GUI updates
    _status_signal = pyqtSignal(str)
    _progress_signal = pyqtSignal(float)   # 0.0 → 1.0
    _error_signal = pyqtSignal(str)
    _done_signal = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.SplashScreen)

        # Size: fixed centered rectangle (taller for breathing room)
        screen = QApplication.primaryScreen().availableGeometry()
        self._w = min(680, int(screen.width() * 0.42))
        self._h = min(440, int(screen.height() * 0.48))
        x = (screen.width() - self._w) // 2
        y = (screen.height() - self._h) // 2
        self.setGeometry(x, y, self._w, self._h)
        self.setFixedSize(self._w, self._h)

        # State
        self._status_text: str = "Initializing..."
        self._progress: float = 0.0
        self._error_text: str = ""
        self._glow_phase: float = 0.0
        self._scan_offset: float = 0.0
        self._particles: List[_Particle] = []

        # Init results (set by pipeline)
        self.controller = None
        self.init_error: Optional[str] = None

        # Signals → slots
        self._status_signal.connect(self._set_status)
        self._progress_signal.connect(self._set_progress)
        self._error_signal.connect(self._set_error)
        self._done_signal.connect(self._on_done)

        # Animation timer: 30 FPS
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(33)

        # Seed particles
        import random
        for _ in range(18):
            self._particles.append(_Particle(self._w, self._h, random))

    # ── Public API ────────────────────────────────────────────────

    def run_init_pipeline(self, on_complete: Callable[[], None]) -> None:
        """Start the background init thread.  ``on_complete`` is called
        on the main thread when done (success or failure)."""
        self._on_complete = on_complete
        t = threading.Thread(target=self._pipeline, daemon=True, name="SplashInit")
        t.start()

    # ── Pipeline (runs on background thread) ─────────────────────

    def _pipeline(self) -> None:
        """Sequential init steps.  Each step: emit status → do work → emit progress."""
        steps: List[Tuple[str, float, Callable[[], None]]] = [
            ("Starting logging system...",       0.08, self._init_logging),
            ("Checking admin privileges...",      0.15, self._init_admin_check),
            ("Setting app identity...",           0.20, self._init_app_identity),
            ("Loading game profiles...",          0.30, self._init_game_profiles),
            ("Initializing WinDivert engine...",  0.45, self._init_windivert),
            ("Loading disruption modules...",     0.55, self._init_modules),
            ("Starting controller...",            0.65, self._init_controller),
            ("Loading plugins...",                0.75, self._init_plugins),
            ("Initializing theme engine...",      0.82, self._init_theme),
            ("Loading network scanner...",        0.90, self._init_scanner),
            ("Finalizing...",                     0.97, self._init_finalize),
        ]
        try:
            for msg, target_progress, fn in steps:
                self._status_signal.emit(msg)
                try:
                    fn()
                except Exception as exc:
                    # Log but don't abort — most steps are non-fatal
                    err = f"{msg.rstrip('.')} FAILED: {exc}"
                    self._try_log_error(err)
                # Cinematic progress ramp — slow, smooth ease toward target
                current = getattr(self, '_last_progress', 0.0)
                increments = 12
                step = (target_progress - current) / increments
                for i in range(increments):
                    current += step
                    self._progress_signal.emit(min(current, target_progress))
                    time.sleep(0.045)
                self._progress_signal.emit(target_progress)
                self._last_progress = target_progress
                time.sleep(0.25)  # hold between init steps

            # Hold at 100% so the user sees the finished state
            self._progress_signal.emit(1.0)
            self._status_signal.emit("Ready.")
            time.sleep(2.0)
            self._done_signal.emit()

        except Exception as exc:
            self._error_signal.emit(str(exc))
            self._done_signal.emit()

    # ── Init steps ────────────────────────────────────────────────

    def _init_logging(self) -> None:
        from app.logs.logger import log_startup, log_info
        log_startup()
        log_info(f"DupeZ v{CURRENT_VERSION} splash init starting")

    def _init_admin_check(self) -> None:
        from app.utils.helpers import is_admin
        self._is_admin = is_admin()
        status = "ADMIN" if self._is_admin else "standard user"
        self._try_log_info(f"Privileges: {status}")
        if not self._is_admin:
            self._status_signal.emit("Checking admin privileges... (not admin)")

    def _init_app_identity(self) -> None:
        import ctypes
        if os.name == "nt":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    f"com.dupez.app.{CURRENT_VERSION}")
            except Exception:
                pass

    def _init_game_profiles(self) -> None:
        try:
            from app.config.game_profiles import load_profile
            load_profile("dayz")
        except Exception:
            pass  # Optional — profile may not exist yet

    def _init_windivert(self) -> None:
        """Verify WinDivert DLL + SYS are present.

        In split mode, the GUI runs at Medium IL and MUST NOT try to
        initialize the in-process disruption_manager — doing so will fail
        because WinDivert requires admin, and failing here pollutes the
        splash log with scary red "WinDivert engine: unavailable" lines
        even though the helper (spawned later on first firewall op) will
        actually own the engine. Just report "deferred" and move on.
        """
        try:
            from app.firewall_helper.feature_flag import is_split_mode
            if is_split_mode():
                self._try_log_info(
                    "WinDivert engine: deferred (split mode — helper owns engine)"
                )
                return
        except Exception:
            pass

        from app.firewall.clumsy_network_disruptor import disruption_manager
        if not disruption_manager._initialized:
            disruption_manager.initialize()
        status = "ready" if disruption_manager._initialized else "unavailable"
        self._try_log_info(f"WinDivert engine: {status}")

    def _init_modules(self) -> None:
        """Pre-import disruption modules so first use is instant."""
        try:
            from app.firewall.modules import MODULE_MAP  # noqa: F401
            self._try_log_info(f"Modules loaded: {list(MODULE_MAP.keys())}")
        except Exception:
            pass

    def _init_controller(self) -> None:
        from app.core.controller import AppController
        self.controller = AppController()
        self._try_log_info("AppController initialized")

    def _init_plugins(self) -> None:
        # Plugins are loaded by AppController.__init__ already
        if self.controller and hasattr(self.controller, 'plugin_loader'):
            count = len(self.controller.plugin_loader.loaded_plugins
                        if hasattr(self.controller.plugin_loader, 'loaded_plugins')
                        else [])
            self._try_log_info(f"Plugins loaded: {count}")

    def _init_theme(self) -> None:
        try:
            from app.themes.theme_manager import get_theme_manager
            get_theme_manager()
        except Exception:
            pass

    def _init_scanner(self) -> None:
        try:
            from app.network.enhanced_scanner import EnhancedNetworkScanner  # noqa: F401
            self._try_log_info("Network scanner loaded")
        except Exception:
            pass

    def _init_finalize(self) -> None:
        """Last step — verify critical components."""
        if self.controller is None:
            self.init_error = "Controller failed to initialize"
            self._error_signal.emit(self.init_error)

    # ── Logging helpers (safe even if logger not yet ready) ───────

    @staticmethod
    def _try_log_info(msg: str) -> None:
        try:
            from app.logs.logger import log_info
            log_info(f"[Splash] {msg}")
        except Exception:
            pass

    @staticmethod
    def _try_log_error(msg: str) -> None:
        try:
            from app.logs.logger import log_error
            log_error(f"[Splash] {msg}")
        except Exception:
            pass

    # ── Slots (main thread) ──────────────────────────────────────

    def _set_status(self, text: str) -> None:
        self._status_text = text
        self.update()

    def _set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def _set_error(self, text: str) -> None:
        self._error_text = text
        self.init_error = text
        self.update()

    def _on_done(self) -> None:
        self._anim_timer.stop()
        if hasattr(self, '_on_complete') and self._on_complete:
            self._on_complete()

    # ── Animation tick ───────────────────────────────────────────

    def _tick(self) -> None:
        self._glow_phase += 0.025          # slower, dreamier pulse
        self._scan_offset += 0.8           # slower scan sweep
        if self._scan_offset > self._w:
            self._scan_offset = -80
        for p in self._particles:
            p.update()
        self.update()

    # ── Paint ────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        W, H = self._w, self._h

        # ── Background gradient ──
        bg = QLinearGradient(0, 0, W * 0.3, H)
        bg.setColorAt(0.0, _BG_DARK)
        bg.setColorAt(0.4, _BG_MAIN)
        bg.setColorAt(1.0, _BG_DARK)
        p.fillRect(0, 0, W, H, bg)

        # ── Rounded border with subtle glow ──
        border_path = QPainterPath()
        border_path.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 14, 14)
        p.setPen(QPen(QColor(0, 240, 255, 20), 1))
        p.drawPath(border_path)

        # ── Animated scan line ──
        scan_grad = QLinearGradient(self._scan_offset - 80, 0, self._scan_offset + 80, 0)
        scan_grad.setColorAt(0.0, QColor(0, 240, 255, 0))
        scan_grad.setColorAt(0.5, QColor(0, 240, 255, 18))
        scan_grad.setColorAt(1.0, QColor(0, 240, 255, 0))
        p.fillRect(0, 0, W, H, scan_grad)

        # ── Particles ──
        for pt in self._particles:
            alpha = int(pt.alpha * 255)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 240, 255, alpha))
            p.drawEllipse(QPointF(pt.x, pt.y), pt.size, pt.size)

        # ── Center glow ──
        import math
        glow_alpha = int(12 + 8 * math.sin(self._glow_phase))
        glow = QRadialGradient(W / 2, H * 0.36, W * 0.45)
        glow.setColorAt(0.0, QColor(0, 240, 255, glow_alpha))
        glow.setColorAt(0.6, QColor(0, 240, 255, int(glow_alpha * 0.3)))
        glow.setColorAt(1.0, QColor(0, 240, 255, 0))
        p.fillRect(0, 0, W, H, glow)

        # ── Layout anchors (vertical positions) ──
        title_y  = H * 0.13           # top of title block
        title_h  = 72                 # generous height for 44pt font
        ver_y    = title_y + title_h + 12   # clear gap below title
        tag_y    = ver_y + 26         # below version

        # ── "DUPEZ" title ──
        title_font = QFont("Segoe UI", 44, QFont.Weight.Black)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 14)
        p.setFont(title_font)

        # Glow behind text (softer, wider)
        p.setPen(QColor(0, 240, 255, 25))
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, -3), (0, 3)]:
            p.drawText(QRectF(dx, title_y + dy, W, title_h),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       "DUPEZ")
        # Main text
        p.setPen(_CYAN)
        p.drawText(QRectF(0, title_y, W, title_h),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   "DUPEZ")

        # ── Version tag ──
        ver_font = QFont("Cascadia Code", 9)
        p.setFont(ver_font)
        p.setPen(QColor(100, 116, 139, 160))
        p.drawText(QRectF(0, ver_y, W, 20),
                   Qt.AlignmentFlag.AlignHCenter, f"v{CURRENT_VERSION}")

        # ── Tagline ──
        tag_font = QFont("Segoe UI", 10)
        tag_font.setWeight(QFont.Weight.Medium)
        p.setFont(tag_font)
        p.setPen(QColor(100, 116, 139, 140))
        p.drawText(QRectF(0, tag_y, W, 20),
                   Qt.AlignmentFlag.AlignHCenter,
                   "Network Disruption Toolkit")

        # ── Progress bar ──
        bar_y = H * 0.70
        bar_h = 3
        bar_margin = 70
        bar_w = W - bar_margin * 2

        # Track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(12, 18, 32))
        p.drawRoundedRect(QRectF(bar_margin, bar_y, bar_w, bar_h), 1.5, 1.5)

        # Fill
        fill_w = bar_w * self._progress
        if fill_w > 0:
            bar_grad = QLinearGradient(bar_margin, 0, bar_margin + fill_w, 0)
            bar_grad.setColorAt(0.0, QColor(0, 240, 255, 140))
            bar_grad.setColorAt(1.0, _CYAN)
            p.setBrush(bar_grad)
            p.drawRoundedRect(QRectF(bar_margin, bar_y, fill_w, bar_h), 1.5, 1.5)

            # Glow at tip
            tip_glow = QRadialGradient(bar_margin + fill_w, bar_y + bar_h / 2, 14)
            tip_glow.setColorAt(0.0, QColor(0, 240, 255, 60))
            tip_glow.setColorAt(1.0, QColor(0, 240, 255, 0))
            p.setBrush(tip_glow)
            p.drawEllipse(QPointF(bar_margin + fill_w, bar_y + bar_h / 2), 14, 14)

        # ── Status text ──
        status_font = QFont("Cascadia Code", 9)
        p.setFont(status_font)
        color = _RED if self._error_text else _TEXT_MUTED
        p.setPen(color)
        text = self._error_text if self._error_text else self._status_text
        p.drawText(QRectF(bar_margin, bar_y + 14, bar_w, 20),
                   Qt.AlignmentFlag.AlignLeft, text)

        # ── Progress percentage ──
        pct_text = f"{int(self._progress * 100)}%"
        p.setPen(_CYAN_DIM)
        p.drawText(QRectF(bar_margin, bar_y + 14, bar_w, 20),
                   Qt.AlignmentFlag.AlignRight, pct_text)

        # ── Bottom credits ──
        cred_font = QFont("Segoe UI", 8)
        cred_font.setWeight(QFont.Weight.Medium)
        p.setFont(cred_font)
        p.setPen(QColor(100, 116, 139, 80))
        p.drawText(QRectF(0, H - 34, W, 20),
                   Qt.AlignmentFlag.AlignHCenter,
                   "PS5  \u00b7  Xbox  \u00b7  PC")

        p.end()


class _Particle:
    """Tiny floating dot for ambient animation."""

    def __init__(self, w: int, h: int, rng) -> None:
        self.x = rng.uniform(0, w)
        self.y = rng.uniform(0, h)
        self.vx = rng.uniform(-0.3, 0.3)
        self.vy = rng.uniform(-0.2, -0.05)
        self.size = rng.uniform(0.8, 2.0)
        self.alpha = rng.uniform(0.05, 0.25)
        self._w = w
        self._h = h
        self._rng = rng

    def update(self) -> None:
        self.x += self.vx
        self.y += self.vy
        self.alpha -= 0.001
        if self.alpha <= 0 or self.y < -5:
            # Respawn at bottom
            self.x = self._rng.uniform(0, self._w)
            self.y = self._rng.uniform(self._h * 0.7, self._h)
            self.alpha = self._rng.uniform(0.05, 0.25)
            self.vy = self._rng.uniform(-0.2, -0.05)
