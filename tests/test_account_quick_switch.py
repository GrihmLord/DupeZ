"""Tests for app.core.account_quick_switch (v5.7.1 feature #9)."""

from __future__ import annotations

from typing import Iterator, List

import pytest

from app.core import account_quick_switch as aqs


@pytest.fixture
def isolated_storage(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Redirect persistence to a temp dir and reset the module cache."""
    from app.core import data_persistence
    monkeypatch.setattr(
        data_persistence.persistence_manager,
        "data_directory",
        tmp_path,
    )
    # Reset the module-level cache.
    aqs._cached_name = None
    aqs._cache_loaded = False
    yield
    aqs._cached_name = None
    aqs._cache_loaded = False


@pytest.fixture
def fake_tracker(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Override the account list with a known fixture.

    Note: Python class bodies don't close over enclosing function
    locals (unlike functions), so building the FakeMgr.accounts list
    inside a class block referencing ``names`` fails with NameError.
    Build the list first, then attach it explicitly.
    """
    names = ["Alice", "Bob", "Charlie"]
    accounts_list = [{"account": n} for n in names]

    class _FakeMgr:
        pass

    _FakeMgr.accounts = accounts_list
    monkeypatch.setattr(
        "app.core.data_persistence.account_manager", _FakeMgr
    )
    return names


# ── Get / set ────────────────────────────────────────────────────────


class TestGetSet:
    """get_active_account / set_active_account lifecycle."""

    def test_initial_state_none(
        self, isolated_storage, fake_tracker,
    ) -> None:
        assert aqs.get_active_account() is None

    def test_set_then_get(
        self, isolated_storage, fake_tracker,
    ) -> None:
        assert aqs.set_active_account("Alice") is True
        assert aqs.get_active_account() == "Alice"

    def test_set_unknown_account_refused(
        self, isolated_storage, fake_tracker,
    ) -> None:
        # Phantom names not in the tracker should be rejected.
        assert aqs.set_active_account("Phantom") is False
        assert aqs.get_active_account() is None

    def test_set_empty_refused(
        self, isolated_storage, fake_tracker,
    ) -> None:
        assert aqs.set_active_account("") is False
        assert aqs.set_active_account("   ") is False

    def test_set_replaces_existing(
        self, isolated_storage, fake_tracker,
    ) -> None:
        aqs.set_active_account("Alice")
        aqs.set_active_account("Bob")
        assert aqs.get_active_account() == "Bob"


# ── Cycle ────────────────────────────────────────────────────────────


class TestCycle:
    """cycle_active_account moves forward / backward through tracker."""

    def test_cycle_from_none_starts_at_first(
        self, isolated_storage, fake_tracker,
    ) -> None:
        assert aqs.cycle_active_account(1) == "Alice"

    def test_cycle_forward(
        self, isolated_storage, fake_tracker,
    ) -> None:
        aqs.set_active_account("Alice")
        assert aqs.cycle_active_account(1) == "Bob"
        assert aqs.cycle_active_account(1) == "Charlie"

    def test_cycle_wraps_around(
        self, isolated_storage, fake_tracker,
    ) -> None:
        aqs.set_active_account("Charlie")
        # Wrap to start of list.
        assert aqs.cycle_active_account(1) == "Alice"

    def test_cycle_backward(
        self, isolated_storage, fake_tracker,
    ) -> None:
        aqs.set_active_account("Bob")
        assert aqs.cycle_active_account(-1) == "Alice"
        # Backward from first wraps to last.
        assert aqs.cycle_active_account(-1) == "Charlie"

    def test_cycle_empty_tracker_returns_none(
        self, isolated_storage, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _EmptyMgr:
            pass
        _EmptyMgr.accounts = []
        monkeypatch.setattr(
            "app.core.data_persistence.account_manager", _EmptyMgr,
        )
        assert aqs.cycle_active_account(1) is None

    def test_cycle_when_current_no_longer_exists(
        self, isolated_storage, fake_tracker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Set Alice, then mutate the tracker to remove Alice.
        aqs.set_active_account("Alice")

        class _ReducedMgr:
            pass
        _ReducedMgr.accounts = [{"account": "Bob"}, {"account": "Charlie"}]
        monkeypatch.setattr(
            "app.core.data_persistence.account_manager", _ReducedMgr,
        )
        # Cycling should restart at first (Bob).
        assert aqs.cycle_active_account(1) == "Bob"


# ── Clear ────────────────────────────────────────────────────────────


class TestClear:
    """clear_active_account unsets the marker."""

    def test_clear_after_set(
        self, isolated_storage, fake_tracker,
    ) -> None:
        aqs.set_active_account("Alice")
        assert aqs.clear_active_account() is True
        assert aqs.get_active_account() is None

    def test_clear_when_none_is_safe(
        self, isolated_storage, fake_tracker,
    ) -> None:
        # Idempotent: clear from None doesn't raise.
        assert aqs.clear_active_account() is True
        assert aqs.get_active_account() is None


@pytest.mark.parametrize("operation", ["set", "cycle", "clear"])
@pytest.mark.parametrize("outcome", [False, OSError("disk full")])
def test_failed_persistence_never_changes_or_announces_active_selection(
    isolated_storage, fake_tracker, monkeypatch, operation, outcome,
) -> None:
    from app.core import data_persistence

    assert aqs.set_active_account("Alice")
    messages = []
    monkeypatch.setattr(aqs, "log_info", messages.append)

    def fail_save(*args, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    with monkeypatch.context() as failure:
        failure.setattr(data_persistence.persistence_manager, "save_data", fail_save)
        if operation == "set":
            assert aqs.set_active_account("Bob") is False
        elif operation == "cycle":
            assert aqs.cycle_active_account() is None
        else:
            assert aqs.clear_active_account() is False
        assert aqs.get_active_account() == "Alice"
        assert messages == []

    # The previously persisted value survives a cache reload as well.
    aqs._cache_loaded = False
    assert aqs.get_active_account() == "Alice"


def test_transient_load_failure_is_retried(isolated_storage, monkeypatch) -> None:
    from app.core import data_persistence
    from unittest.mock import Mock

    load = Mock(side_effect=[OSError("busy"), {"name": "Alice"}])
    monkeypatch.setattr(data_persistence.persistence_manager, "load_data", load)

    assert aqs.get_active_account() is None
    assert aqs.get_active_account() == "Alice"
    assert load.call_count == 2


def test_account_names_skip_malformed_and_duplicate_records(monkeypatch) -> None:
    from types import SimpleNamespace

    manager = SimpleNamespace(accounts=[
        {"account": " Alice "}, None, "not a record", {"account": None},
        {"account": 42}, {"account": ""}, {"account": "Alice"}, {"account": "Bob"},
    ])
    monkeypatch.setattr("app.core.data_persistence.account_manager", manager)

    assert aqs.active_account_names() == ["Alice", "Bob"]


@pytest.mark.parametrize("name", [None, 42, [], {}])
def test_set_rejects_non_string_names(isolated_storage, fake_tracker, name) -> None:
    assert aqs.set_active_account(name) is False
    assert aqs.get_active_account() is None
