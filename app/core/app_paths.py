"""Canonical installed/runtime paths and verified legacy-data migration."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

MIGRATION_SCHEMA = "dupez.data-migration.v1"


def source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def legacy_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return source_root()


def is_installed_runtime() -> bool:
    return bool(
        getattr(sys, "frozen", False)
        or os.environ.get("DUPEZ_FORCE_USER_DATA") == "1"
    )


def user_root() -> Path:
    override = os.environ.get("DUPEZ_USER_ROOT")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or os.path.expanduser(r"~\AppData\Local")
        )
    else:
        base = Path(
            os.environ.get("XDG_DATA_HOME")
            or os.path.expanduser("~/.local/share")
        )
    return base / "DupeZ"


def data_dir() -> Path:
    if is_installed_runtime():
        return user_root() / "data"
    return source_root() / "app" / "data"


def config_dir() -> Path:
    if is_installed_runtime():
        return user_root() / "config"
    return source_root() / "app" / "config"


def captures_dir() -> Path:
    return user_root() / "captures"


def reports_dir() -> Path:
    return user_root() / "reports"


def backups_dir() -> Path:
    return user_root() / "backups"


def models_dir() -> Path:
    return data_dir() / "models"


def logs_dir() -> Path:
    if is_installed_runtime():
        return user_root() / "logs"
    return source_root() / "logs"


def crashes_dir() -> Path:
    if is_installed_runtime():
        return user_root() / "crashes"
    return source_root()


@dataclass(frozen=True)
class MigrationResult:
    source: str
    destination: str
    copied: tuple[str, ...]
    conflicts: tuple[str, ...]
    errors: tuple[str, ...]
    marker: str

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "schema": MIGRATION_SCHEMA,
            **asdict(self),
            "ok": self.ok,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".migrating")
    shutil.copy2(source, tmp)
    if _sha256(source) != _sha256(tmp):
        tmp.unlink(missing_ok=True)
        raise OSError(f"verification failed for {source.name}")
    os.replace(tmp, destination)


def migrate_legacy_files(
    source: Path,
    destination: Path,
    *,
    patterns: Iterable[str],
    marker_name: str,
) -> MigrationResult:
    """Copy missing legacy files, verify bytes, and never delete originals."""
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / marker_name
    if marker.exists():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            return MigrationResult(
                source=str(source),
                destination=str(destination),
                copied=tuple(payload.get("copied", [])),
                conflicts=tuple(payload.get("conflicts", [])),
                errors=tuple(payload.get("errors", [])),
                marker=str(marker),
            )
        except (OSError, json.JSONDecodeError):
            pass

    copied: list[str] = []
    conflicts: list[str] = []
    errors: list[str] = []
    if source.exists() and source.resolve() != destination.resolve():
        seen: set[Path] = set()
        for pattern in patterns:
            for candidate in source.glob(pattern):
                if not candidate.is_file() or candidate in seen:
                    continue
                seen.add(candidate)
                rel = candidate.relative_to(source)
                target = destination / rel
                try:
                    if target.exists():
                        if _sha256(candidate) != _sha256(target):
                            conflicts.append(rel.as_posix())
                        continue
                    _copy_verified(candidate, target)
                    copied.append(rel.as_posix())
                except OSError as exc:
                    errors.append(f"{rel.as_posix()}: {exc}")

    payload = {
        "schema": MIGRATION_SCHEMA,
        "completed_at": int(time.time()),
        "source": str(source),
        "destination": str(destination),
        "copied": sorted(copied),
        "conflicts": sorted(conflicts),
        "errors": sorted(errors),
        "legacy_files_deleted": False,
    }
    if not errors:
        tmp_marker = marker.with_suffix(marker.suffix + ".tmp")
        with tmp_marker.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_marker, marker)
    return MigrationResult(
        source=str(source),
        destination=str(destination),
        copied=tuple(sorted(copied)),
        conflicts=tuple(sorted(conflicts)),
        errors=tuple(sorted(errors)),
        marker=str(marker) if not errors else "",
    )


_DATA_PATTERNS = (
    "*.json",
    "*.hmac",
    "*.jsonl",
    "*.TAMPERED",
    "*.backup.*.json",
    "episodes/*.jsonl",
    "episodes/*.jsonl.bak",
    "profiles/*.json",
    "models/*.pkl",
    "models/*.onnx",
    "models/*.sha256",
)
_CONFIG_PATTERNS = (
    "settings.json",
    "settings.json.hmac",
    "audit_webhook_hosts.json",
    "audit_webhook_hosts.json.hmac",
)


def ensure_runtime_migration() -> tuple[MigrationResult, ...] | None:
    """Migrate installed builds once; source checkouts remain untouched."""
    if not is_installed_runtime():
        return None
    root = legacy_runtime_root()
    data_result = migrate_legacy_files(
        root / "app" / "data",
        data_dir(),
        patterns=_DATA_PATTERNS,
        marker_name=".migration-data-v1.json",
    )
    config_result = migrate_legacy_files(
        root / "app" / "config",
        config_dir(),
        patterns=_CONFIG_PATTERNS,
        marker_name=".migration-config-v1.json",
    )
    log_result = migrate_legacy_files(
        root / "logs",
        logs_dir(),
        patterns=("*.log", "*.log.*"),
        marker_name=".migration-logs-v1.json",
    )
    crash_result = migrate_legacy_files(
        root,
        crashes_dir(),
        patterns=("FATAL_CRASH*.txt",),
        marker_name=".migration-crashes-v1.json",
    )
    return data_result, config_result, log_result, crash_result
