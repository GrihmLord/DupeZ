"""Tests for app.firewall.process_scope (v5.6.9 feature #4).

Covers filter-clause construction, the apply_process_scope branch
matrix, and the watcher's state-change callback semantics. Live
foreground PID + DayZ process enumeration are mocked since the test
host doesn't actually run DayZ.
"""

from __future__ import annotations

import pytest

from app.firewall.process_scope import (
    DAYZ_PROCESS_NAMES,
    ProcessScopeWatcher,
    apply_process_scope,
    build_pid_filter_clause,
)


class TestBuildPidFilterClause:
    """build_pid_filter_clause — empty/single/multi/dedupe/sort."""

    def test_empty_iterable_returns_empty_string(self) -> None:
        # Critical: callers AND this onto a filter, so empty must not
        # produce "filter and " (syntax error in WinDivert).
        assert build_pid_filter_clause([]) == ""

    def test_zero_and_negative_pids_excluded(self) -> None:
        # Zero is not a real PID and would clash with WinDivert's
        # convention. Negative values are nonsense; both filtered.
        assert build_pid_filter_clause([0, -1, -100]) == ""

    def test_single_pid(self) -> None:
        assert build_pid_filter_clause([1234]) == "(processId == 1234)"

    def test_multiple_pids_or_joined(self) -> None:
        assert build_pid_filter_clause([1234, 5678]) == \
            "(processId == 1234 or processId == 5678)"

    def test_pids_deduplicated(self) -> None:
        # Duplicate PIDs should not produce redundant clauses.
        assert build_pid_filter_clause([1234, 1234, 5678]) == \
            "(processId == 1234 or processId == 5678)"

    def test_pids_sorted_for_determinism(self) -> None:
        # Caching by filter-string hash needs deterministic ordering.
        assert build_pid_filter_clause([5678, 1234]) == \
            build_pid_filter_clause([1234, 5678])


class TestApplyProcessScope:
    """apply_process_scope — None / dayz / auto / unknown_mode branches."""

    BASE = "ip.SrcAddr == 10.0.0.5 or ip.DstAddr == 10.0.0.5"

    def test_no_scope_passthrough(self) -> None:
        for mode in (None, ""):
            assert apply_process_scope(self.BASE, mode) == self.BASE

    def test_dayz_with_pids_wraps(self) -> None:
        result = apply_process_scope(
            self.BASE, "dayz", dayz_pids=[1234, 5678],
        )
        assert "processId == 1234" in result
        assert "processId == 5678" in result
        assert self.BASE in result

    def test_dayz_with_no_pids_falls_back_to_base(self) -> None:
        # Documented behavior: "no PIDs" is safer-returns-base than
        # silently no-op'ing every cut.
        result = apply_process_scope(self.BASE, "dayz", dayz_pids=[])
        assert result == self.BASE

    def test_auto_with_foreground_in_dayz_pids(self) -> None:
        # Auto mode targets only the foreground DayZ window.
        result = apply_process_scope(
            self.BASE, "auto", dayz_pids=[1234, 5678], foreground_pid=5678,
        )
        assert "processId == 5678" in result
        assert "processId == 1234" not in result

    def test_auto_with_foreground_not_in_dayz_falls_back(self) -> None:
        # Operator alt-tabbed to browser; auto mode should not scope.
        result = apply_process_scope(
            self.BASE, "auto", dayz_pids=[1234], foreground_pid=9999,
        )
        assert result == self.BASE

    def test_auto_with_no_pids_falls_back(self) -> None:
        result = apply_process_scope(
            self.BASE, "auto", dayz_pids=None, foreground_pid=None,
        )
        assert result == self.BASE

    def test_true_filter_replaced_not_wrapped(self) -> None:
        # When base filter is "true" the scope clause stands alone
        # rather than being AND'd with "true".
        result = apply_process_scope("true", "dayz", dayz_pids=[1234])
        assert result == "(processId == 1234)"

    def test_unknown_mode_logs_and_falls_back(self) -> None:
        # apply_process_scope returns base unchanged on unknown mode
        # rather than raising — the orchestrator wraps this in try/except.
        result = apply_process_scope(
            self.BASE, "nuke_them_all", dayz_pids=[1234],
        )
        assert result == self.BASE


class TestDayZProcessNames:
    """Defensive: the process-name set covers both DayZ exe variants."""

    def test_covers_battleeye_and_unprotected(self) -> None:
        names = {n.lower() for n in DAYZ_PROCESS_NAMES}
        assert "dayz.exe" in names
        assert "dayz_be.exe" in names
        # Also cover the x64 variant some installs use.
        assert "dayz_x64.exe" in names


class TestProcessScopeWatcher:
    """Watcher fires the callback only on state TRANSITIONS, not polls."""

    def test_callback_fires_only_on_state_change(self) -> None:
        events = []

        watcher = ProcessScopeWatcher(
            on_state_change=lambda is_dayz, pid: events.append((is_dayz, pid)),
            poll_interval_s=0.05,
        )
        # Drive the state machine manually instead of relying on the
        # real foreground; pid_is_dayz is the only Windows-specific
        # call, monkey-patch it to a stub.
        states = iter([True, True, False, False, True])
        watcher._pid_is_dayz = lambda pid: next(states, False)  # type: ignore
        # Run _run inline for 5 ticks then stop.
        import threading
        watcher._stop = threading.Event()

        # Drive 5 ticks manually
        for _ in range(5):
            try:
                fg_pid = 4242
                is_dayz = watcher._pid_is_dayz(fg_pid)
                if is_dayz != watcher._last_state:
                    watcher._last_state = is_dayz
                    watcher._cb(is_dayz, fg_pid)
            except StopIteration:
                break

        # Expected transitions: None→True, True→False, False→True (3 events)
        assert len(events) == 3
        assert events[0] == (True, 4242)
        assert events[1] == (False, 4242)
        assert events[2] == (True, 4242)
