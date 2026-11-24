"""Real parser/export failure regressions for account data, with UI dialogs stubbed."""

from __future__ import annotations

import builtins
import csv
import os
from copy import deepcopy
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from app.gui import dayz_account_tracker as tracker_module  # noqa: E402
from app.gui.dayz_account_tracker import DayZAccountTracker  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tracker(qapp, monkeypatch):
    widget = DayZAccountTracker.__new__(DayZAccountTracker)
    widget.accounts = [{"account": "Existing", "notes": "keep me"}]
    widget.status_label = Mock()
    widget._refresh_after_import = Mock(return_value=True)
    monkeypatch.setattr(tracker_module.QMessageBox, "critical", Mock())
    monkeypatch.setattr(tracker_module.QMessageBox, "information", Mock())
    return widget


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_headerless_csv_imports_every_row_without_collapsing_empty_columns(
    tracker, tmp_path, delimiter,
):
    source = tmp_path / "accounts.csv"
    rows = [
        ["Alpha", "", "North", "high", "ready", "", "", "", "", "", "first"],
        ["Bravo", "", "South", "low", "offline", "", "", "", "", "", "second"],
        ["Charlie", "", "West", "medium", "storage", "", "", "", "", "", "third"],
    ]
    with source.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter=delimiter).writerows(rows)

    tracker._process_csv_file(str(source))

    candidate = tracker._refresh_after_import.call_args.args[0]
    assert [row["account"] for row in candidate] == ["Existing", "Alpha", "Bravo", "Charlie"]
    assert [(row["location"], row["notes"]) for row in candidate[1:]] == [
        ("North", "first"), ("South", "second"), ("West", "third"),
    ]
    assert [row["status"] for row in candidate[1:]] == ["Ready", "Offline", "Storage"]
    tracker_module.QMessageBox.critical.assert_not_called()


def test_named_csv_handles_bom_leading_blank_lines_and_multiline_fields(tracker, tmp_path):
    source = tmp_path / "accounts.csv"
    source.write_text(
        '\ufeff\n\nCharacter;E-Mail;Condition;Comment\nAlpha;alpha@example.invalid;ready;"line 1\nline 2"\n',
        encoding="utf-8",
    )

    tracker._process_csv_file(str(source))

    candidate = tracker._refresh_after_import.call_args.args[0]
    assert len(candidate) == 2
    assert candidate[1]["account"] == "Alpha"
    assert candidate[1]["email"] == "alpha@example.invalid"
    assert candidate[1]["notes"].splitlines() == ["line 1", "line 2"]
    assert candidate[1]["status"] == "Ready"


@pytest.mark.parametrize("contents", [
    b"Account,Notes\nAlpha,valid\nBravo,\xff\n",
    b'Account,Notes\nAlpha,valid\nBravo,"unterminated\n',
    b"Account,Account\nAlpha,Bravo\n",
    b"Account,Name\nAlpha,Bravo\n",
])
def test_invalid_csv_never_persists_a_partial_import(tracker, tmp_path, contents):
    source = tmp_path / "accounts.csv"
    source.write_bytes(contents)
    original = deepcopy(tracker.accounts)

    tracker._process_csv_file(str(source))

    tracker._refresh_after_import.assert_not_called()
    assert tracker.accounts == original
    tracker_module.QMessageBox.critical.assert_called_once()
    tracker_module.QMessageBox.information.assert_not_called()


@pytest.mark.parametrize("failure", ["write", "cancel", "flush", "replace"])
@pytest.mark.parametrize("existing", [True, False])
def test_failed_export_preserves_destination_and_removes_only_its_stage(
    tmp_path, monkeypatch, failure, existing,
):
    destination = tmp_path / "accounts.csv"
    unrelated_stage = tmp_path / ".accounts.csv.unrelated.tmp"
    unrelated_stage.write_text("someone else's stage", encoding="utf-8")
    if existing:
        destination.write_bytes(b"previous complete export")
    if failure == "flush":
        monkeypatch.setattr(tracker_module.os, "fsync", Mock(side_effect=OSError("disk full")))
    elif failure == "replace":
        monkeypatch.setattr(tracker_module.os, "replace", Mock(side_effect=OSError("locked")))
    expected = KeyboardInterrupt if failure == "cancel" else OSError

    with pytest.raises(expected):
        with tracker_module._account_export_file(str(destination)) as stream:
            stream.write("incomplete")
            if failure == "write":
                raise OSError("disk full")
            if failure == "cancel":
                raise KeyboardInterrupt

    if existing:
        assert destination.read_bytes() == b"previous complete export"
    else:
        assert not destination.exists()
    assert unrelated_stage.read_text(encoding="utf-8") == "someone else's stage"
    assert set(tmp_path.iterdir()) == ({destination, unrelated_stage} if existing else {unrelated_stage})


def test_csv_export_replaces_only_after_complete_safe_serialization(tmp_path):
    destination = tmp_path / "accounts.csv"
    destination.write_bytes(b"old")
    accounts = [{"account": "Alpha", "notes": '=HYPERLINK("https://example.invalid")'}]
    original = deepcopy(accounts)

    tracker_module._write_account_csv(str(destination), accounts)

    with destination.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == tracker_module.TABLE_HEADERS
    assert rows[1][0] == "Alpha"
    assert rows[1][-1] == "'" + accounts[0]["notes"]
    assert accounts == original
    assert list(tmp_path.iterdir()) == [destination]


def test_xlsx_export_is_readable_and_subset_does_not_mutate_view(tracker, tmp_path):
    import openpyxl

    destination = tmp_path / "accounts.xlsx"
    subset = [{"account": "Alpha", "notes": "=1+1"}]
    original = deepcopy(tracker.accounts)

    tracker._export_xlsx(str(destination), subset)

    workbook = openpyxl.load_workbook(destination)
    try:
        assert workbook.active.max_row == 2
        assert workbook.active["A2"].value == "Alpha"
        assert workbook.active["K2"].value == "'=1+1"
        assert workbook.active["K2"].data_type == "s"
    finally:
        workbook.close()
    assert tracker.accounts == original
    assert list(tmp_path.iterdir()) == [destination]


def test_partial_xlsx_serialization_preserves_previous_export(tracker, tmp_path, monkeypatch):
    import openpyxl

    destination = tmp_path / "accounts.xlsx"
    destination.write_bytes(b"previous workbook")

    def fail_save(_workbook, stream):
        stream.write(b"partial archive")
        raise OSError("disk full")

    monkeypatch.setattr(openpyxl.Workbook, "save", fail_save)

    with pytest.raises(OSError, match="disk full"):
        tracker._export_xlsx(str(destination))

    assert destination.read_bytes() == b"previous workbook"
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("subset", [True, False])
def test_missing_xlsx_dependency_never_reports_export_success(tracker, tmp_path, monkeypatch, subset):
    destination = tmp_path / "accounts.xlsx"
    original_import = builtins.__import__

    def import_without_openpyxl(name, *args, **kwargs):
        if name == "openpyxl":
            raise ImportError("unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_openpyxl)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", Mock(return_value=(str(destination), "")))

    if subset:
        tracker._export_subset(tracker.accounts)
    else:
        tracker._export_csv_accounts()

    assert not destination.exists()
    tracker_module.QMessageBox.information.assert_not_called()
    tracker_module.QMessageBox.critical.assert_called_once()
    tracker.status_label.setText.assert_not_called()
