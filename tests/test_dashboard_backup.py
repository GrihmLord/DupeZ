"""Backup dialog outcome tests never open widgets or restore operator data."""

from types import SimpleNamespace

import pytest

from app.core import backup as backup_module
from app.core.backup import RestoreResult
from app.gui import dashboard as dashboard_module
from app.gui.dashboard import DupeZDashboard


@pytest.fixture
def backup_dialogs(monkeypatch):
    events = []
    monkeypatch.setattr(
        dashboard_module.QFileDialog, "getOpenFileName",
        lambda *_args: ("synthetic.zip", ""),
    )
    for level in ("critical", "information", "warning"):
        monkeypatch.setattr(
            dashboard_module.QMessageBox, level,
            lambda _parent, title, message, level=level: events.append((level, title, message)),
        )

    def confirm(*_args):
        events.append(("question", "", ""))
        return dashboard_module.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(dashboard_module.QMessageBox, "question", confirm)
    return events


@pytest.mark.parametrize("preview", [
    RestoreResult(skipped=["missing.json"], failed={"missing.json": "entry is missing from the archive"}),
    RestoreResult(hash_mismatches=["corrupt.json"]),
    RestoreResult(error="invalid ZIP"),
])
def test_incomplete_preview_never_prompts_or_restores(monkeypatch, backup_dialogs, preview):
    calls = []

    def restore(path, *, dry_run):
        calls.append((path, dry_run))
        assert dry_run
        return preview

    monkeypatch.setattr(backup_module, "restore_backup", restore)

    DupeZDashboard._on_restore_backup(SimpleNamespace())

    assert calls == [("synthetic.zip", True)]
    assert len(backup_dialogs) == 1
    assert backup_dialogs[0][0] == "critical"
    assert "No files were restored" in backup_dialogs[0][2]


@pytest.mark.parametrize("result, expected_level", [
    (
        RestoreResult(restored=["good.json"], skipped=["good.hmac"]),
        "information",
    ),
    (
        RestoreResult(restored=["good.json"], failed={"bad.json": "injected write failure"}),
        "warning",
    ),
])
def test_restore_completion_distinguishes_expected_skips_and_failures(
    monkeypatch, backup_dialogs, result, expected_level,
):
    calls = []

    def restore(path, *, dry_run):
        calls.append((path, dry_run))
        if dry_run:
            return RestoreResult(restored=["good.json"], skipped=["good.hmac"])
        return result

    monkeypatch.setattr(backup_module, "restore_backup", restore)

    DupeZDashboard._on_restore_backup(SimpleNamespace())

    assert calls == [("synthetic.zip", True), ("synthetic.zip", False)]
    assert [event[0] for event in backup_dialogs] == ["question", expected_level]
    if expected_level == "warning":
        assert "injected write failure" in backup_dialogs[-1][2]
        assert "failed 1" in backup_dialogs[-1][2]
