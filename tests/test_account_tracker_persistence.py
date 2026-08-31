"""Failure-path coverage for DayZ account-tracker persistence."""

from __future__ import annotations

import os
from copy import deepcopy
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.gui import dayz_account_tracker as tracker_module  # noqa: E402
from app.gui.dayz_account_tracker import DayZAccountTracker  # noqa: E402


class _Label:
    def __init__(self, text: str = "Ready") -> None:
        self.text = text

    def setText(self, text: str) -> None:  # noqa: N802 - Qt-compatible seam
        self.text = text


class _AccountManager:
    def __init__(self, accounts: list[dict], outcome: object) -> None:
        self.items = deepcopy(accounts)
        self.outcome = outcome
        self.attempted: list[dict] | None = None

    @property
    def accounts(self) -> list[dict]:
        return self.items

    def save_changes(self, accounts: list[dict]) -> bool:
        self.attempted = deepcopy(accounts)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return bool(self.outcome)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_tracker(qapp: QApplication, accounts: list[dict]) -> DayZAccountTracker:
    del qapp
    tracker = DayZAccountTracker.__new__(DayZAccountTracker)
    tracker.accounts = deepcopy(accounts)
    tracker.current_account = tracker.accounts[0] if tracker.accounts else None
    tracker.status_label = _Label()
    tracker.last_modified_label = _Label("")
    tracker._refresh_account_table = Mock()
    tracker._update_statistics = Mock()
    return tracker


@pytest.mark.parametrize("outcome", [False, OSError("disk full")])
def test_failed_save_preserves_manager_and_view_state(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    outcome: object,
) -> None:
    original = [{"id": "1", "account": "Main", "status": "Ready"}]
    manager = _AccountManager(original, outcome)
    tracker = _make_tracker(qapp, original)
    critical = Mock()
    monkeypatch.setattr(tracker_module, "account_manager", manager)
    monkeypatch.setattr(tracker_module.QMessageBox, "critical", critical)

    candidate = deepcopy(original)
    candidate[0]["status"] = "Offline"

    assert not tracker._save_accounts(candidate, operation="update account status")
    assert manager.accounts == original
    assert tracker.accounts == original
    assert tracker.status_label.text == "Save failed: update account status"
    critical.assert_called_once()


def test_successful_save_commits_defensive_copies(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = [{"id": "1", "account": "Main", "status": "Ready"}]
    manager = _AccountManager(original, True)
    tracker = _make_tracker(qapp, original)
    monkeypatch.setattr(tracker_module, "account_manager", manager)

    candidate = deepcopy(original)
    candidate[0]["status"] = "Offline"

    assert tracker._save_accounts(candidate, operation="update account status")
    assert manager.accounts[0]["status"] == "Offline"
    assert tracker.accounts[0]["status"] == "Offline"

    candidate[0]["status"] = "Dead"
    assert manager.accounts[0]["status"] == "Offline"


def test_add_failure_never_reports_success_or_refreshes(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = [{"id": "1", "account": "Main", "status": "Ready"}]
    manager = _AccountManager(original, False)
    tracker = _make_tracker(qapp, original)
    critical = Mock()
    monkeypatch.setattr(tracker_module, "account_manager", manager)
    monkeypatch.setattr(tracker_module.QMessageBox, "critical", critical)
    tracker._show_account_dialog = Mock(
        return_value={"account": "Mule", "status": "Storage"}
    )

    tracker._add_account()

    assert manager.accounts == original
    assert tracker.accounts == original
    assert tracker.status_label.text == "Save failed: add account"
    tracker._refresh_account_table.assert_not_called()
    critical.assert_called_once()


def test_edit_failure_leaves_selected_record_unchanged(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = [
        {
            "id": "1",
            "account": "Main",
            "status": "Ready",
            "notes": "keep me",
        }
    ]
    manager = _AccountManager(original, False)
    tracker = _make_tracker(qapp, original)
    monkeypatch.setattr(tracker_module, "account_manager", manager)
    monkeypatch.setattr(tracker_module.QMessageBox, "critical", Mock())
    tracker._show_account_dialog = Mock(
        return_value={"account": "Renamed", "notes": "replacement"}
    )

    tracker._edit_account()

    assert manager.accounts == original
    assert tracker.accounts == original
    assert tracker.current_account == original[0]
    assert tracker.status_label.text == "Save failed: update account"
    tracker._refresh_account_table.assert_not_called()


def test_template_failure_keeps_existing_accounts_and_suppresses_success(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = [{"id": "1", "account": "Main", "status": "Ready"}]
    manager = _AccountManager(original, False)
    tracker = _make_tracker(qapp, original)
    information = Mock()
    monkeypatch.setattr(tracker_module, "account_manager", manager)
    monkeypatch.setattr(tracker_module.QMessageBox, "critical", Mock())
    monkeypatch.setattr(tracker_module.QMessageBox, "information", information)

    assert not tracker._apply_template(silent=False)
    assert manager.accounts == original
    assert tracker.accounts == original
    information.assert_not_called()


def test_import_failure_does_not_clear_or_replace_the_table(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = [{"id": "1", "account": "Main", "status": "Ready"}]
    manager = _AccountManager(original, False)
    tracker = _make_tracker(qapp, original)
    tracker.account_table = Mock()
    monkeypatch.setattr(tracker_module, "account_manager", manager)
    monkeypatch.setattr(tracker_module.QMessageBox, "critical", Mock())
    candidate = original + [
        {"id": "2", "account": "Imported", "status": "Storage"}
    ]

    assert not tracker._refresh_after_import(candidate)
    assert manager.accounts == original
    assert tracker.accounts == original
    tracker.account_table.clearContents.assert_not_called()
    tracker._update_statistics.assert_not_called()
