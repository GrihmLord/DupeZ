# app/gui/widgets/collapsible_card.py — Collapsible / Reorderable Card Widget
"""A collapsible, optionally reorderable card section.

Click the header to expand/collapse.  The up/down buttons let users
reorder sections within the parent layout.

Extracted from ``clumsy_control.py`` so that any panel can reuse the
component without importing the heavyweight control view.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["CollapsibleCard"]

# ── Stylesheet constants ────────────────────────────────────────────

COLLAPSE_HEADER_QSS = (
    "QPushButton { background: rgba(10,15,26,0.55); color: #00f0ff; "
    "font-size: 11px; font-weight: 700; letter-spacing: 1px; "
    "border: 1px solid rgba(30,41,59,0.45); border-radius: 8px; "
    "text-align: left; padding: 8px 12px; } "
    "QPushButton:hover { border-color: rgba(0,240,255,0.25); "
    "background: rgba(10,15,26,0.7); }"
)

REORDER_BTN_QSS = (
    "QPushButton { background: transparent; color: #475569; "
    "border: none; font-size: 13px; padding: 0; min-width: 20px; } "
    "QPushButton:hover { color: #00f0ff; }"
)


class CollapsibleCard(QWidget):
    """A collapsible, optionally reorderable card section.

    Click the header to expand/collapse.  The up/down buttons let users
    reorder sections within the parent layout.

    Parameters
    ----------
    title : str
        Section header label (e.g. "MODULES").
    content : QWidget
        The widget to show/hide when toggling.
    parent_layout : QVBoxLayout | None
        If provided, up/down reorder buttons are shown and wired to swap
        position within this layout.
    collapsed : bool
        Start collapsed (default False — start expanded).
    header_qss : str | None
        Optional override for the header button stylesheet.
    reorder_qss : str | None
        Optional override for the reorder button stylesheet.
    """

    def __init__(
        self,
        title: str,
        content: QWidget,
        *,
        parent_layout: Optional[QVBoxLayout] = None,
        collapsed: bool = False,
        parent: Optional[QWidget] = None,
        header_qss: Optional[str] = None,
        reorder_qss: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._expanded = not collapsed
        self._parent_layout = parent_layout

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(2)

        # Header row
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)

        arrow = "\u25bc" if self._expanded else "\u25b6"
        self._header_btn = QPushButton(f" {arrow}  {title}")
        self._header_btn.setStyleSheet(header_qss or COLLAPSE_HEADER_QSS)
        self._header_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._header_btn.setFixedHeight(34)
        self._header_btn.clicked.connect(self._toggle)
        header_row.addWidget(self._header_btn, 1)

        # Reorder buttons (only if parent_layout given)
        _rqss = reorder_qss or REORDER_BTN_QSS
        if parent_layout is not None:
            self._btn_up = QPushButton("\u25b2")
            self._btn_up.setStyleSheet(_rqss)
            self._btn_up.setFixedSize(22, 34)
            self._btn_up.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_up.setToolTip("Move section up")
            self._btn_up.clicked.connect(self._move_up)
            header_row.addWidget(self._btn_up)

            self._btn_down = QPushButton("\u25bc")
            self._btn_down.setStyleSheet(_rqss)
            self._btn_down.setFixedSize(22, 34)
            self._btn_down.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_down.setToolTip("Move section down")
            self._btn_down.clicked.connect(self._move_down)
            header_row.addWidget(self._btn_down)

        root.addLayout(header_row)

        # Content area
        self._content = content
        self._content.setVisible(self._expanded)
        root.addWidget(self._content)

    # ── Public API ───────────────────────────────────────────────────

    def set_expanded(self, expanded: bool) -> None:
        """Programmatically expand or collapse the card."""
        if expanded != self._expanded:
            self._toggle()

    @property
    def expanded(self) -> bool:
        return self._expanded

    # ── Toggle collapse ──────────────────────────────────────────────

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        arrow = "\u25bc" if self._expanded else "\u25b6"
        self._header_btn.setText(f" {arrow}  {self._title}")
        self._content.setVisible(self._expanded)

    # ── Reorder within parent layout ─────────────────────────────────

    def _find_index(self) -> int:
        """Find this widget's index in the parent layout."""
        if self._parent_layout is None:
            return -1
        for i in range(self._parent_layout.count()):
            item = self._parent_layout.itemAt(i)
            if item and item.widget() is self:
                return i
        return -1

    def _move_up(self) -> None:
        idx = self._find_index()
        if idx <= 0 or self._parent_layout is None:
            return
        target = idx - 1
        while target >= 0:
            item = self._parent_layout.itemAt(target)
            if item and isinstance(item.widget(), CollapsibleCard):
                break
            target -= 1
        if target < 0:
            return
        self._swap_with(target)

    def _move_down(self) -> None:
        idx = self._find_index()
        if idx < 0 or self._parent_layout is None:
            return
        count = self._parent_layout.count()
        target = idx + 1
        while target < count:
            item = self._parent_layout.itemAt(target)
            if item and isinstance(item.widget(), CollapsibleCard):
                break
            target += 1
        if target >= count:
            return
        self._swap_with(target)

    def _swap_with(self, other_idx: int) -> None:
        """Swap this widget's position with the widget at *other_idx*."""
        my_idx = self._find_index()
        if my_idx < 0 or self._parent_layout is None:
            return
        hi, lo = max(my_idx, other_idx), min(my_idx, other_idx)
        hi_item = self._parent_layout.takeAt(hi)
        lo_item = self._parent_layout.takeAt(lo)
        self._parent_layout.insertWidget(lo, hi_item.widget())
        self._parent_layout.insertWidget(hi, lo_item.widget())
