"""Tests for Smart Ops session ownership across the extracted panels."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.gui.panels.smart_mode_panel import SmartModePanel


def test_end_active_session_persists_once_and_refreshes_engine() -> None:
    tracker = SimpleNamespace(end_session=MagicMock())
    engine = SimpleNamespace(refresh_history=MagicMock())
    panel = SimpleNamespace(
        _active_session_id="session-1",
        _smart_tracker=tracker,
        _smart_engine=engine,
    )

    SmartModePanel.end_active_session(panel)
    SmartModePanel.end_active_session(panel)

    tracker.end_session.assert_called_once_with("session-1")
    engine.refresh_history.assert_called_once_with()
    assert panel._active_session_id is None
