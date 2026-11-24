"""Focused ownership and truthful-result tests for the OBS overlay UI."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app.core import data_persistence
from app.gui import dashboard as dashboard_module
from app.gui.dashboard import DupeZDashboard


ROOT = Path(__file__).resolve().parents[1]


class _StatusBar:
    def __init__(self) -> None:
        self.messages = []

    def showMessage(self, message, timeout) -> None:
        self.messages.append((message, timeout))


class _Owner:
    def __init__(
        self,
        *,
        owned: bool,
        start_result: bool = False,
        stop_result: bool = False,
    ) -> None:
        self.owned = owned
        self.running = owned
        self.start_result = start_result
        self.stop_result = stop_result
        self.start_calls = 0
        self.stop_calls = 0
        self.base_url = "http://127.0.0.1:4778"

    def start(self) -> bool:
        self.start_calls += 1
        if self.start_result:
            self.owned = True
            self.running = True
        return self.start_result

    def stop(self) -> bool:
        self.stop_calls += 1
        if self.stop_result:
            self.owned = False
            self.running = False
        return self.stop_result


def _parent(owner: _Owner):
    return SimpleNamespace(
        controller=object(),
        overlay_server_owner=owner,
        status_bar=_StatusBar(),
    )


def _patch_messages(monkeypatch):
    warning = Mock()
    information = Mock()
    monkeypatch.setattr(dashboard_module.QMessageBox, "warning", warning)
    monkeypatch.setattr(
        dashboard_module.QMessageBox,
        "information",
        information,
    )
    return warning, information


def test_startup_and_shutdown_do_not_create_a_shadow_obs_owner() -> None:
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert re.search(r"\b_overlay_server\b", source) is None
    assert "window.overlay_server_owner" in source
    assert '"overlay_server_owner"' in source


def test_dashboard_failed_stop_retains_owner_and_enabled_preference(
    monkeypatch,
) -> None:
    owner = _Owner(owned=True, stop_result=False)
    parent = _parent(owner)
    updates = []
    warning, information = _patch_messages(monkeypatch)
    monkeypatch.setattr(
        data_persistence.settings_manager,
        "update_setting",
        lambda *args: updates.append(args),
    )

    DupeZDashboard._toggle_obs_overlay(parent)

    assert parent.overlay_server_owner is owner
    assert owner.owned is True
    assert owner.stop_calls == 1
    assert updates == []
    assert parent.status_bar.messages == []
    warning.assert_called_once()
    information.assert_not_called()


def test_dashboard_failed_start_never_persists_or_reports_success(
    monkeypatch,
) -> None:
    owner = _Owner(owned=False, start_result=False)
    parent = _parent(owner)
    updates = []
    warning, information = _patch_messages(monkeypatch)
    monkeypatch.setattr(
        data_persistence.settings_manager,
        "update_setting",
        lambda *args: updates.append(args),
    )

    DupeZDashboard._toggle_obs_overlay(parent)

    assert owner.start_calls == 1
    assert owner.owned is False
    assert updates == []
    assert parent.status_bar.messages == []
    warning.assert_called_once()
    information.assert_not_called()


def test_dashboard_retains_cleanup_owner_when_enable_save_rollback_fails(
    monkeypatch,
) -> None:
    owner = _Owner(
        owned=False,
        start_result=True,
        stop_result=False,
    )
    parent = _parent(owner)
    warning, information = _patch_messages(monkeypatch)

    def fail_update(*_args):
        raise OSError("settings unavailable")

    monkeypatch.setattr(
        data_persistence.settings_manager,
        "update_setting",
        fail_update,
    )

    DupeZDashboard._toggle_obs_overlay(parent)

    assert owner.start_calls == 1
    assert owner.stop_calls == 1
    assert owner.owned is True
    assert parent.overlay_server_owner is owner
    assert parent.status_bar.messages == []
    warning.assert_called_once()
    assert "cleanup was not confirmed" in warning.call_args.args[2]
    information.assert_not_called()
