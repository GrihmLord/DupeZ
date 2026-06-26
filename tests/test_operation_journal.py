"""Tests for the crash-recovery operation marker."""

from app.core.operation_journal import OperationJournal


def test_mark_and_clear_round_trip(tmp_path) -> None:
    journal = OperationJournal(tmp_path / "active.json")

    assert journal.is_pending() is False
    journal.mark_pending("packet_disruption")
    assert journal.is_pending() is True
    journal.clear()
    assert journal.is_pending() is False


def test_journal_contains_no_target_identifiers(tmp_path) -> None:
    path = tmp_path / "active.json"
    journal = OperationJournal(path)

    journal.mark_pending("firewall_block")
    text = path.read_text(encoding="utf-8")

    assert "firewall_block" in text
    assert "target" not in text
    assert "192.168." not in text


def test_corrupt_journal_fails_safe_as_pending(tmp_path) -> None:
    path = tmp_path / "active.json"
    path.write_text("{broken", encoding="utf-8")

    assert OperationJournal(path).is_pending() is True


def test_forwarding_state_round_trip(tmp_path) -> None:
    journal = OperationJournal(tmp_path / "active.json")

    journal.mark_forwarding_change(True)

    assert journal.is_pending() is True
    assert journal.forwarding_original_state() is True
    journal.clear_forwarding_change()
    assert journal.is_pending() is False


def test_forwarding_cleanup_preserves_other_pending_reasons(tmp_path) -> None:
    journal = OperationJournal(tmp_path / "active.json")
    journal.mark_pending("packet_disruption")
    journal.mark_forwarding_change(False)

    journal.clear_forwarding_change()

    assert journal.is_pending() is True
    assert journal.forwarding_original_state() is None
