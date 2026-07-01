"""Local privacy inventory and scrub tools for DupeZ.

The files under ``app/data`` are intentionally ignored by git because
they can contain IP addresses, MAC addresses, device fingerprints,
account notes, audit chains, and runtime telemetry. This module gives
the UI/CLI a safe way to show what exists and quarantine or delete the
high-risk runtime artifacts without touching source files.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

__all__ = [
    "PrivacyItem",
    "RetentionPlan",
    "RetentionRule",
    "ScrubResult",
    "build_retention_plan",
    "enforce_retention_policy",
    "scan_privacy_items",
    "scrub_privacy_items",
]


@dataclass(frozen=True)
class PrivacyItem:
    """One local file that may contain private runtime data."""

    path: Path
    rel_path: str
    category: str
    size_bytes: int
    reason: str
    item_type: str = "file"


@dataclass(frozen=True)
class RetentionRule:
    """Age-based retention rule for a privacy category."""

    category: str
    max_age_days: int


@dataclass(frozen=True)
class RetentionPlan:
    """Dry-run view of files that exceed the configured retention window."""

    rules: Dict[str, int]
    items: List[PrivacyItem]
    eligible: List[PrivacyItem]
    total_bytes: int
    eligible_bytes: int


@dataclass(frozen=True)
class ScrubResult:
    """Result of a dry-run or applied scrub."""

    dry_run: bool
    quarantine_dir: Path | None
    items: List[PrivacyItem]
    removed: List[str]
    errors: List[str]

    @property
    def ok(self) -> bool:
        return not self.errors


_RUNTIME_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("audit*.jsonl", "audit", "tamper-evident audit chain may contain local event metadata"),
    ("audit.TAMPERED", "audit", "audit tamper sentinel reveals local integrity state"),
    ("*.tampered.*.jsonl", "audit", "archived tamper evidence may contain event metadata"),
    ("*.corrupted.*.jsonl", "audit", "archived corrupted audit material may contain event metadata"),
    ("*.legacy.*.jsonl", "audit", "legacy audit chain may contain event metadata"),
    ("episodes/*.jsonl", "episodes", "episode telemetry may contain IPs, methods, and timing"),
    ("episodes/*.jsonl.bak", "episodes", "episode backup telemetry may contain IPs and timing"),
    ("device_cache*.json", "device-cache", "device cache may contain IPs, MACs, vendors, and hostnames"),
    ("device_cache*.hmac", "device-cache", "device cache integrity sidecar"),
    ("device_nicknames*.json", "device-cache", "device nicknames may identify local devices"),
    ("scheduler.json", "scheduler", "scheduler may contain target and preset metadata"),
    (".diagnostics_write_probe.tmp", "diagnostics", "diagnostic write probe artifact"),
)

_ACCOUNT_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("dayz_accounts*.json", "account-data", "account tracker data may contain usernames and notes"),
    ("dayz_accounts*.hmac", "account-data", "account tracker integrity sidecar"),
    ("profiles/*.json", "profiles", "profile files may contain user-specific workflow data"),
)

_CAPTURE_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("*.etl", "packet-capture", "Pktmon ETL may contain network identifiers and packet bytes"),
    ("*.pcapng", "packet-capture", "PCAPNG contains network identifiers and packet bytes"),
    ("*.pcap", "packet-capture", "PCAP contains network identifiers and packet bytes"),
)
_LOG_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("*.log", "logs", "runtime logs may contain local event and error metadata"),
    ("*.log.*", "logs", "rotated runtime logs may contain local event metadata"),
)
_CRASH_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("FATAL_CRASH*.txt", "crash-report", "crash reports contain stack and environment metadata"),
)
_REPORT_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("*.json", "scenario-report", "scenario reports may contain local timing and masked target metadata"),
)
_SUPPORT_BUNDLE_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("support-bundle-*.json", "support-bundle", "support bundles contain redacted diagnostics and privacy metadata"),
)
_BACKUP_ARCHIVE_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("dupez-backup-*.zip", "backup-archive", "backup archives may contain account, settings, audit, and episode data"),
    ("dupez-backup-*.zip.dpapi", "backup-archive", "encrypted backup archives may still be sensitive local data"),
)
_QUARANTINE_DIR_PATTERNS: Sequence[tuple[str, str, str]] = (
    ("privacy-quarantine-*", "privacy-quarantine", "old privacy quarantine folders contain previously scrubbed private data"),
)

DEFAULT_RETENTION_DAYS: Dict[str, int] = {
    "backup-archive": 30,
    "packet-capture": 7,
    "privacy-quarantine": 30,
    "support-bundle": 14,
    "crash-report": 30,
    "logs": 30,
    "scenario-report": 30,
    "audit": 90,
    "device-cache": 90,
    "diagnostics": 7,
    "episodes": 90,
    "scheduler": 90,
}


def _default_data_dir() -> Path:
    from app.core.data_persistence import _resolve_data_directory
    return Path(_resolve_data_directory())


def _default_capture_dir() -> Path:
    from app.core.app_paths import captures_dir

    return captures_dir()


def _default_log_dir() -> Path:
    from app.core.app_paths import logs_dir

    return logs_dir()


def _default_crash_dir() -> Path:
    from app.core.app_paths import crashes_dir

    return crashes_dir()


def _default_report_dir() -> Path:
    from app.core.app_paths import reports_dir

    return reports_dir()


def _default_backup_dir() -> Path:
    from app.core.app_paths import backups_dir

    return backups_dir()


def _tree_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total


def _iter_matches(
    data_dir: Path,
    patterns: Iterable[tuple[str, str, str]],
    *,
    rel_prefix: str = "",
) -> Iterable[PrivacyItem]:
    seen: set[Path] = set()
    for pattern, category, reason in patterns:
        for path in data_dir.glob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                rel = path.relative_to(data_dir).as_posix()
            except ValueError:
                continue
            if rel_prefix:
                rel = f"{rel_prefix.rstrip('/')}/{rel}"
            yield PrivacyItem(
                path=path,
                rel_path=rel,
                category=category,
                size_bytes=path.stat().st_size,
                reason=reason,
            )


def _iter_dir_matches(
    data_dir: Path,
    patterns: Iterable[tuple[str, str, str]],
    *,
    rel_prefix: str = "",
) -> Iterable[PrivacyItem]:
    seen: set[Path] = set()
    for pattern, category, reason in patterns:
        for path in data_dir.glob(pattern):
            if not path.is_dir():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                rel = path.relative_to(data_dir).as_posix()
            except ValueError:
                continue
            if rel_prefix:
                rel = f"{rel_prefix.rstrip('/')}/{rel}"
            yield PrivacyItem(
                path=path,
                rel_path=rel,
                category=category,
                size_bytes=_tree_size(path),
                reason=reason,
                item_type="directory",
            )


def scan_privacy_items(
    *,
    data_dir: Path | str | None = None,
    capture_dir: Path | str | None = None,
    log_dir: Path | str | None = None,
    crash_dir: Path | str | None = None,
    report_dir: Path | str | None = None,
    backup_dir: Path | str | None = None,
    include_account_data: bool = False,
) -> List[PrivacyItem]:
    """Return local files that are safe candidates for privacy cleanup."""
    explicit_data_dir = data_dir is not None
    root = Path(data_dir) if explicit_data_dir else _default_data_dir()
    patterns = list(_RUNTIME_PATTERNS)
    if include_account_data:
        patterns.extend(_ACCOUNT_PATTERNS)
    items = list(_iter_matches(root, patterns)) if root.exists() else []
    capture_root = (
        Path(capture_dir)
        if capture_dir is not None
        else None
        if explicit_data_dir
        else _default_capture_dir()
    )
    if capture_root is not None and capture_root.exists():
        items.extend(
            _iter_matches(
                capture_root,
                _CAPTURE_PATTERNS,
                rel_prefix="captures",
            )
        )
    log_root = (
        Path(log_dir)
        if log_dir is not None
        else None
        if explicit_data_dir
        else _default_log_dir()
    )
    if log_root is not None and log_root.exists():
        items.extend(
            _iter_matches(log_root, _LOG_PATTERNS, rel_prefix="logs")
        )
    crash_root = (
        Path(crash_dir)
        if crash_dir is not None
        else None
        if explicit_data_dir
        else _default_crash_dir()
    )
    if crash_root is not None and crash_root.exists():
        items.extend(
            _iter_matches(
                crash_root,
                _CRASH_PATTERNS,
                rel_prefix="crashes",
            )
        )
    report_root = (
        Path(report_dir)
        if report_dir is not None
        else None
        if explicit_data_dir
        else _default_report_dir()
    )
    if report_root is not None and report_root.exists():
        items.extend(
            _iter_matches(
                report_root,
                _REPORT_PATTERNS,
                rel_prefix="reports",
            )
        )
    if root.exists():
        items.extend(_iter_matches(root, _SUPPORT_BUNDLE_PATTERNS))
        items.extend(_iter_dir_matches(root, _QUARANTINE_DIR_PATTERNS))
        items.extend(_iter_matches(root, _BACKUP_ARCHIVE_PATTERNS))
    backup_root = (
        Path(backup_dir)
        if backup_dir is not None
        else None
        if explicit_data_dir
        else _default_backup_dir()
    )
    if backup_root is not None and backup_root.exists():
        items.extend(
            _iter_matches(
                backup_root,
                _BACKUP_ARCHIVE_PATTERNS,
                rel_prefix="backups",
            )
        )
    return sorted(items, key=lambda item: (item.category, item.rel_path))


def _safe_destination(base: Path, rel_path: str) -> Path:
    dest = base / rel_path
    resolved = dest.resolve()
    base_resolved = base.resolve()
    if os.path.commonpath([str(base_resolved), str(resolved)]) != str(base_resolved):
        raise ValueError(f"refusing path outside quarantine: {rel_path}")
    return dest


def scrub_privacy_items(
    *,
    data_dir: Path | str | None = None,
    capture_dir: Path | str | None = None,
    log_dir: Path | str | None = None,
    crash_dir: Path | str | None = None,
    report_dir: Path | str | None = None,
    backup_dir: Path | str | None = None,
    include_account_data: bool = False,
    dry_run: bool = True,
    quarantine: bool = True,
    items: Sequence[PrivacyItem] | None = None,
) -> ScrubResult:
    """Quarantine or delete privacy-sensitive local runtime artifacts.

    Defaults to dry-run and quarantine mode. Account tracker/profile data
    is excluded unless ``include_account_data`` is explicitly enabled.
    """
    explicit_data_dir = data_dir is not None
    root = Path(data_dir) if explicit_data_dir else _default_data_dir()
    effective_capture_dir = (
        capture_dir
        if capture_dir is not None
        else None
        if explicit_data_dir
        else _default_capture_dir()
    )
    effective_log_dir = (
        log_dir
        if log_dir is not None
        else None
        if explicit_data_dir
        else _default_log_dir()
    )
    effective_crash_dir = (
        crash_dir
        if crash_dir is not None
        else None
        if explicit_data_dir
        else _default_crash_dir()
    )
    effective_report_dir = (
        report_dir
        if report_dir is not None
        else None
        if explicit_data_dir
        else _default_report_dir()
    )
    effective_backup_dir = (
        backup_dir
        if backup_dir is not None
        else None
        if explicit_data_dir
        else _default_backup_dir()
    )
    selected_items = list(items) if items is not None else scan_privacy_items(
        data_dir=root,
        capture_dir=effective_capture_dir,
        log_dir=effective_log_dir,
        crash_dir=effective_crash_dir,
        report_dir=effective_report_dir,
        backup_dir=effective_backup_dir,
        include_account_data=include_account_data,
    )
    quarantine_dir: Path | None = None
    removed: List[str] = []
    errors: List[str] = []

    if dry_run:
        return ScrubResult(True, None, selected_items, removed, errors)

    if quarantine:
        quarantine_dir = root / f"privacy-quarantine-{int(time.time())}"
        quarantine_dir.mkdir(parents=True, exist_ok=True)

    for item in selected_items:
        try:
            if quarantine_dir is not None:
                dest = _safe_destination(quarantine_dir, item.rel_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(item.path), str(dest))
            elif item.path.is_dir():
                shutil.rmtree(item.path)
            else:
                item.path.unlink()
            removed.append(item.rel_path)
        except OSError as exc:
            errors.append(f"{item.rel_path}: {exc}")

    return ScrubResult(False, quarantine_dir, selected_items, removed, errors)


def _older_than_days(path: Path, days: int, now: float) -> bool:
    try:
        age_seconds = now - path.stat().st_mtime
    except OSError:
        return False
    return age_seconds >= max(days, 0) * 24 * 60 * 60


def build_retention_plan(
    *,
    data_dir: Path | str | None = None,
    capture_dir: Path | str | None = None,
    log_dir: Path | str | None = None,
    crash_dir: Path | str | None = None,
    report_dir: Path | str | None = None,
    backup_dir: Path | str | None = None,
    include_account_data: bool = False,
    rules: Dict[str, int] | None = None,
    now: float | None = None,
) -> RetentionPlan:
    """Return files that exceed conservative local-data retention windows."""
    effective_rules = dict(DEFAULT_RETENTION_DAYS)
    if rules:
        for category, days in rules.items():
            effective_rules[str(category)] = max(int(days), 0)

    items = scan_privacy_items(
        data_dir=data_dir,
        capture_dir=capture_dir,
        log_dir=log_dir,
        crash_dir=crash_dir,
        report_dir=report_dir,
        backup_dir=backup_dir,
        include_account_data=include_account_data,
    )
    timestamp = time.time() if now is None else now
    eligible = [
        item for item in items
        if item.category in effective_rules
        and _older_than_days(item.path, effective_rules[item.category], timestamp)
    ]
    return RetentionPlan(
        rules=effective_rules,
        items=items,
        eligible=eligible,
        total_bytes=sum(item.size_bytes for item in items),
        eligible_bytes=sum(item.size_bytes for item in eligible),
    )


def enforce_retention_policy(
    *,
    data_dir: Path | str | None = None,
    capture_dir: Path | str | None = None,
    log_dir: Path | str | None = None,
    crash_dir: Path | str | None = None,
    report_dir: Path | str | None = None,
    backup_dir: Path | str | None = None,
    include_account_data: bool = False,
    rules: Dict[str, int] | None = None,
    dry_run: bool = True,
    quarantine: bool = True,
    now: float | None = None,
) -> ScrubResult:
    """Quarantine/delete only files that exceed retention policy."""
    plan = build_retention_plan(
        data_dir=data_dir,
        capture_dir=capture_dir,
        log_dir=log_dir,
        crash_dir=crash_dir,
        report_dir=report_dir,
        backup_dir=backup_dir,
        include_account_data=include_account_data,
        rules=rules,
        now=now,
    )
    return scrub_privacy_items(
        data_dir=data_dir,
        capture_dir=capture_dir,
        log_dir=log_dir,
        crash_dir=crash_dir,
        report_dir=report_dir,
        backup_dir=backup_dir,
        include_account_data=include_account_data,
        dry_run=dry_run,
        quarantine=quarantine,
        items=plan.eligible,
    )
