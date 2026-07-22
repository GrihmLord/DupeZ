# app/gui/lazy_dayz_map.py — Deferred QtWebEngine map construction
"""A lightweight map placeholder that creates Chromium only when shown.

QtWebEngine has a comparatively large process and memory footprint. The normal
startup path can prewarm the map for fast tab switching, but constrained
systems should not pay that cost before the user asks for the map. This wrapper
preserves the QWidget contract expected by the dashboard while deferring the
real :class:`DayZMapGUI` import and construction until first visibility.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.logs.logger import log_error, log_info

__all__ = ["LazyDayZMapGUI"]

MapFactory = Callable[[], QWidget]


class LazyDayZMapGUI(QWidget):
    """Load the real map widget on first show without blocking app startup."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        map_factory: Optional[MapFactory] = None,
    ) -> None:
        super().__init__(parent)
        self._map_factory = map_factory
        self._map_widget: Optional[QWidget] = None
        self._loading = False
        self._attempted = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(12)

        self._status = QLabel(
            "The interactive DayZ map is deferred to reduce startup memory.\n"
            "It will initialize when this tab becomes visible."
        )
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            "color: #94a3b8; font-size: 14px; background: #0a0e1a; "
            "padding: 28px; border-radius: 8px;"
        )
        self._layout.addStretch(1)
        self._layout.addWidget(self._status)

        self._retry = QPushButton("Retry map initialization")
        self._retry.setVisible(False)
        self._retry.clicked.connect(self.retry)
        self._layout.addWidget(self._retry)
        self._layout.addStretch(1)

    @property
    def is_loaded(self) -> bool:
        return self._map_widget is not None

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().showEvent(event)
        if not self.is_loaded and not self._loading and not self._attempted:
            # Let QStackedWidget complete the tab switch and paint the
            # placeholder before constructing QtWebEngine on the GUI thread.
            QTimer.singleShot(0, self.load_now)

    def _resolve_factory(self) -> MapFactory:
        if self._map_factory is not None:
            return self._map_factory
        from app.gui.dayz_map_gui_new import DayZMapGUI

        return DayZMapGUI

    def load_now(self) -> bool:
        """Construct and mount the real map once. Return whether it loaded."""
        if self.is_loaded:
            return True
        if self._loading:
            return False

        self._loading = True
        self._attempted = True
        self._retry.setVisible(False)
        self._status.setText("Initializing the interactive DayZ map…")

        try:
            widget = self._resolve_factory()()
            if not isinstance(widget, QWidget):
                raise TypeError("map factory did not return a QWidget")

            self._layout.removeWidget(self._status)
            self._status.deleteLater()
            self._layout.removeWidget(self._retry)
            self._retry.deleteLater()
            while self._layout.count():
                item = self._layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().setParent(None)
            self._layout.setContentsMargins(0, 0, 0, 0)
            self._layout.setSpacing(0)
            self._layout.addWidget(widget)
            self._map_widget = widget
            widget.show()
            log_info("Map: lazy DayZMapGUI initialized on first tab open")
            return True
        except Exception as exc:
            self._status.setText(
                "The embedded map could not initialize.\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "You can retry without restarting DupeZ."
            )
            self._retry.setVisible(True)
            log_error(f"Lazy map initialization failed: {exc}")
            return False
        finally:
            self._loading = False

    def retry(self) -> None:
        """Allow an explicit retry after a recoverable initialization error."""
        if self.is_loaded or self._loading:
            return
        self._attempted = False
        self.load_now()
