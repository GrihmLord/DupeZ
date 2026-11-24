"""Account marker UI reports persisted outcomes without creating a window."""

from types import SimpleNamespace

import pytest

from app.core import account_quick_switch as aqs
from app.gui.dashboard import DupeZDashboard


@pytest.mark.parametrize(
    ("handler", "direction"),
    [(DupeZDashboard._cycle_account_next, 1), (DupeZDashboard._cycle_account_prev, -1)],
)
@pytest.mark.parametrize("outcome", ["saved", "failed", "empty"])
def test_cycle_status_reports_persistence_outcome(monkeypatch, handler, direction, outcome):
    messages = []
    requested = []
    window = SimpleNamespace(
        status_bar=SimpleNamespace(showMessage=lambda message, _ms: messages.append(message)),
    )

    def cycle(value):
        requested.append(value)
        return "fixture-account" if outcome == "saved" else None

    monkeypatch.setattr(aqs, "cycle_active_account", cycle)
    monkeypatch.setattr(
        aqs, "active_account_names",
        lambda: [] if outcome == "empty" else ["fixture-account"],
    )
    handler(window)

    assert requested == [direction]
    assert messages == [{
        "saved": "Active account: fixture-account",
        "failed": "Could not save active account; selection unchanged",
        "empty": "No accounts in tracker — add one first",
    }[outcome]]


@pytest.mark.parametrize("saved", [True, False])
def test_clear_status_reports_persistence_outcome(monkeypatch, saved):
    messages = []
    window = SimpleNamespace(
        status_bar=SimpleNamespace(showMessage=lambda message, _ms: messages.append(message)),
    )
    monkeypatch.setattr(aqs, "clear_active_account", lambda: saved)

    DupeZDashboard._clear_active_account(window)

    assert messages == [
        "Active account cleared" if saved
        else "Could not clear active account; selection unchanged"
    ]
