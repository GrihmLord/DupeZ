"""Privacy-preserving runtime storage and migration status."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from app.core import app_paths

SCHEMA = "dupez.storage-status.v1"

_MIGRATION_MARKERS: tuple[tuple[str, str], ...] = (
    ("data", ".migration-data-v1.json"),
    ("config", ".migration-config-v1.json"),
    ("logs", ".migration-logs-v1.json"),
    ("crashes", ".migration-crashes-v1.json"),
)


def _path_state(path: Path) -> Dict[str, Any]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": path.is_dir() if exists else False,
        "parent_exists": path.parent.exists(),
        "writable_hint": path.exists() and path.is_dir(),
    }


def _marker_state(root: Path, marker_name: str) -> Dict[str, Any]:
    marker = root / marker_name
    payload: Dict[str, Any] = {
        "marker": str(marker),
        "exists": marker.exists(),
        "ok": False,
        "copied": 0,
        "conflicts": 0,
        "errors": 0,
    }
    if not payload["exists"]:
        return payload
    try:
        doc = app_paths.read_migration_marker(marker)
    except (OSError, ValueError, RecursionError) as exc:
        payload["error"] = (
            "migration marker could not be read or validated "
            f"({type(exc).__name__})"
        )
        return payload
    payload.update({
        "schema": doc["schema"],
        "ok": not doc["errors"],
        "copied": len(doc["copied"]),
        "conflicts": len(doc["conflicts"]),
        "errors": len(doc["errors"]),
        "legacy_files_deleted": False,
    })
    return payload


def _count_legacy_candidates(root: Path, patterns: tuple[str, ...]) -> int:
    if not root.exists():
        return 0
    seen: set[Path] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                seen.add(path.resolve())
    return len(seen)


def build_storage_status() -> Dict[str, Any]:
    """Return a read-only summary of DupeZ-managed runtime storage."""
    roots = {
        "user_root": app_paths.user_root(),
        "data": app_paths.data_dir(),
        "config": app_paths.config_dir(),
        "captures": app_paths.captures_dir(),
        "reports": app_paths.reports_dir(),
        "backups": app_paths.backups_dir(),
        "models": app_paths.models_dir(),
        "logs": app_paths.logs_dir(),
        "crashes": app_paths.crashes_dir(),
    }
    root_status = {name: _path_state(path) for name, path in roots.items()}

    marker_roots = {
        "data": app_paths.data_dir(),
        "config": app_paths.config_dir(),
        "logs": app_paths.logs_dir(),
        "crashes": app_paths.crashes_dir(),
    }
    migration = {
        name: _marker_state(marker_roots[name], marker)
        for name, marker in _MIGRATION_MARKERS
    }
    legacy_root = app_paths.legacy_runtime_root()
    legacy_candidates = {
        "data": _count_legacy_candidates(
            legacy_root / "app" / "data",
            app_paths._DATA_PATTERNS,
        ),
        "config": _count_legacy_candidates(
            legacy_root / "app" / "config",
            app_paths._CONFIG_PATTERNS,
        ),
        "logs": _count_legacy_candidates(legacy_root / "logs", ("*.log", "*.log.*")),
        "crashes": _count_legacy_candidates(legacy_root, ("FATAL_CRASH*.txt",)),
    }

    recommendations: list[str] = []
    if any(state["exists"] and not state["ok"] for state in migration.values()):
        recommendations.append(
            "A migration marker is invalid or reports errors; preserve legacy "
            "files and inspect diagnostics before retrying migration."
        )
    if app_paths.is_installed_runtime():
        incomplete = [
            name for name, state in migration.items()
            if legacy_candidates.get(name, 0) and not state["exists"]
        ]
        if incomplete:
            recommendations.append(
                "Legacy mutable files exist without completed migration markers; "
                "launch normally or inspect diagnostics before deleting legacy files."
            )
    else:
        recommendations.append(
            "Source checkout mode keeps mutable development data in the repository tree."
        )
    if not root_status["backups"]["exists"]:
        recommendations.append(
            "No managed backup directory exists yet; GUI backup creation will create it."
        )

    return {
        "schema": SCHEMA,
        "runtime": {
            "installed": app_paths.is_installed_runtime(),
            "frozen": bool(getattr(app_paths.sys, "frozen", False)),
            "legacy_runtime_root": str(legacy_root),
        },
        "roots": root_status,
        "migration": {
            "schema": app_paths.MIGRATION_SCHEMA,
            "markers": migration,
            "legacy_candidates": legacy_candidates,
        },
        "recommendations": recommendations[:5],
    }
