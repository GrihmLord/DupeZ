"""Tests for app.core.privacy local data inventory and scrub tools."""

from __future__ import annotations

from pathlib import Path
import os
import time

from app.core.privacy import (
    build_retention_plan,
    enforce_retention_policy,
    scan_privacy_items,
    scrub_privacy_items,
)


def _write(path: Path, text: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestPrivacyScan:
    def test_runtime_items_are_detected(self, tmp_path: Path) -> None:
        _write(tmp_path / "audit.jsonl", '{"event":"x"}\n')
        _write(tmp_path / "episodes" / "episode_1.jsonl", "{}\n")
        _write(tmp_path / "device_cache.json", "{}")
        _write(tmp_path / "secrets.enc.json", "{}")

        items = scan_privacy_items(data_dir=tmp_path)
        rels = {item.rel_path for item in items}

        assert "audit.jsonl" in rels
        assert "episodes/episode_1.jsonl" in rels
        assert "device_cache.json" in rels
        assert "secrets.enc.json" not in rels

    def test_account_data_is_opt_in(self, tmp_path: Path) -> None:
        _write(tmp_path / "dayz_accounts.json", '{"notes":"private"}')

        assert scan_privacy_items(data_dir=tmp_path) == []
        items = scan_privacy_items(data_dir=tmp_path, include_account_data=True)

        assert [item.rel_path for item in items] == ["dayz_accounts.json"]

    def test_pktmon_capture_artifacts_are_detected(
        self,
        tmp_path: Path,
    ) -> None:
        data_dir = tmp_path / "data"
        capture_dir = tmp_path / "captures"
        data_dir.mkdir()
        _write(capture_dir / "sample.etl", "capture")
        _write(capture_dir / "sample.pcapng", "capture")

        items = scan_privacy_items(
            data_dir=data_dir,
            capture_dir=capture_dir,
        )

        assert {item.rel_path for item in items} == {
            "captures/sample.etl",
            "captures/sample.pcapng",
        }
        assert {item.category for item in items} == {"packet-capture"}

    def test_logs_and_crash_reports_are_detected(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        log_dir = tmp_path / "logs"
        crash_dir = tmp_path / "crashes"
        data_dir.mkdir()
        _write(log_dir / "errors.log", "error")
        _write(crash_dir / "FATAL_CRASH.txt", "traceback")

        items = scan_privacy_items(
            data_dir=data_dir,
            log_dir=log_dir,
            crash_dir=crash_dir,
        )

        assert {item.rel_path for item in items} == {
            "logs/errors.log",
            "crashes/FATAL_CRASH.txt",
        }

    def test_reports_and_support_bundles_are_detected(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        report_dir = tmp_path / "reports"
        data_dir.mkdir()
        _write(data_dir / "support-bundle-20260625T120000Z.json", "{}")
        _write(report_dir / "scenario-abc.json", "{}")

        items = scan_privacy_items(data_dir=data_dir, report_dir=report_dir)

        assert {item.rel_path for item in items} == {
            "support-bundle-20260625T120000Z.json",
            "reports/scenario-abc.json",
        }
        assert {item.category for item in items} == {
            "support-bundle",
            "scenario-report",
        }

    def test_backup_archives_and_quarantine_dirs_are_detected(
        self,
        tmp_path: Path,
    ) -> None:
        data_dir = tmp_path / "data"
        backup_dir = tmp_path / "backups"
        _write(data_dir / "privacy-quarantine-123" / "audit.jsonl", "{}\n")
        _write(data_dir / "dupez-backup-inline.zip", "zip")
        _write(backup_dir / "dupez-backup-managed.zip.dpapi", "zip")

        items = scan_privacy_items(data_dir=data_dir, backup_dir=backup_dir)

        by_rel = {item.rel_path: item for item in items}
        assert by_rel["privacy-quarantine-123"].category == "privacy-quarantine"
        assert by_rel["privacy-quarantine-123"].item_type == "directory"
        assert by_rel["dupez-backup-inline.zip"].category == "backup-archive"
        assert by_rel["backups/dupez-backup-managed.zip.dpapi"].category == (
            "backup-archive"
        )


class TestPrivacyScrub:
    def test_dry_run_does_not_move_files(self, tmp_path: Path) -> None:
        audit = _write(tmp_path / "audit.jsonl", "{}\n")

        result = scrub_privacy_items(data_dir=tmp_path, dry_run=True)

        assert result.dry_run is True
        assert audit.exists()
        assert result.removed == []
        assert result.errors == []

    def test_scrub_quarantines_by_default(self, tmp_path: Path) -> None:
        audit = _write(tmp_path / "audit.jsonl", "{}\n")

        result = scrub_privacy_items(data_dir=tmp_path, dry_run=False)

        assert result.ok
        assert not audit.exists()
        assert result.quarantine_dir is not None
        assert (result.quarantine_dir / "audit.jsonl").exists()
        assert result.removed == ["audit.jsonl"]

    def test_delete_mode_removes_without_quarantine(self, tmp_path: Path) -> None:
        audit = _write(tmp_path / "audit.jsonl", "{}\n")

        result = scrub_privacy_items(
            data_dir=tmp_path,
            dry_run=False,
            quarantine=False,
        )

        assert result.ok
        assert not audit.exists()
        assert result.quarantine_dir is None

    def test_scrub_quarantines_external_capture_artifacts(
        self,
        tmp_path: Path,
    ) -> None:
        data_dir = tmp_path / "data"
        capture_dir = tmp_path / "captures"
        data_dir.mkdir()
        capture = _write(capture_dir / "sample.pcapng", "capture")

        result = scrub_privacy_items(
            data_dir=data_dir,
            capture_dir=capture_dir,
            dry_run=False,
        )

        assert result.ok
        assert not capture.exists()
        assert result.quarantine_dir is not None
        assert (
            result.quarantine_dir / "captures" / "sample.pcapng"
        ).exists()


class TestPrivacyRetention:
    def test_retention_plan_selects_only_expired_categories(
        self,
        tmp_path: Path,
    ) -> None:
        now = time.time()
        old_capture = _write(tmp_path / "captures" / "old.pcapng", "capture")
        fresh_capture = _write(tmp_path / "captures" / "fresh.pcapng", "capture")
        old_log = _write(tmp_path / "logs" / "dupez.log", "log")
        for path, days_old in (
            (old_capture, 10),
            (fresh_capture, 1),
            (old_log, 31),
        ):
            stamp = now - days_old * 24 * 60 * 60
            os.utime(path, (stamp, stamp))

        plan = build_retention_plan(
            data_dir=tmp_path / "data",
            capture_dir=tmp_path / "captures",
            log_dir=tmp_path / "logs",
            now=now,
        )

        assert {item.rel_path for item in plan.eligible} == {
            "captures/old.pcapng",
            "logs/dupez.log",
        }
        assert plan.eligible_bytes > 0

    def test_retention_enforcement_quarantines_only_eligible_items(
        self,
        tmp_path: Path,
    ) -> None:
        now = time.time()
        old_capture = _write(tmp_path / "captures" / "old.pcapng", "capture")
        fresh_capture = _write(tmp_path / "captures" / "fresh.pcapng", "capture")
        os.utime(old_capture, (now - 10 * 24 * 60 * 60,) * 2)
        os.utime(fresh_capture, (now - 1 * 24 * 60 * 60,) * 2)

        result = enforce_retention_policy(
            data_dir=tmp_path / "data",
            capture_dir=tmp_path / "captures",
            dry_run=False,
            now=now,
        )

        assert result.ok
        assert not old_capture.exists()
        assert fresh_capture.exists()
        assert result.quarantine_dir is not None
        assert (result.quarantine_dir / "captures" / "old.pcapng").exists()

    def test_retention_enforcement_can_delete_old_quarantine_directories(
        self,
        tmp_path: Path,
    ) -> None:
        now = time.time()
        old_quarantine = _write(
            tmp_path / "data" / "privacy-quarantine-old" / "audit.jsonl",
            "{}\n",
        ).parent
        os.utime(old_quarantine, (now - 40 * 24 * 60 * 60,) * 2)

        result = enforce_retention_policy(
            data_dir=tmp_path / "data",
            dry_run=False,
            quarantine=False,
            now=now,
        )

        assert result.ok
        assert not old_quarantine.exists()
        assert result.removed == ["privacy-quarantine-old"]

    def test_retention_plan_includes_managed_backup_archives(
        self,
        tmp_path: Path,
    ) -> None:
        now = time.time()
        backup = _write(tmp_path / "backups" / "dupez-backup-old.zip", "zip")
        os.utime(backup, (now - 31 * 24 * 60 * 60,) * 2)

        plan = build_retention_plan(
            data_dir=tmp_path / "data",
            backup_dir=tmp_path / "backups",
            now=now,
        )

        assert [item.rel_path for item in plan.eligible] == [
            "backups/dupez-backup-old.zip"
        ]
        assert plan.eligible[0].category == "backup-archive"
