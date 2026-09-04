"""One-click backup + restore for DupeZ (v5.6.9 feature #7).

Bundles every persisted file DupeZ owns into a single ZIP, optionally
encrypted with the operator's DPAPI-derived key (the same key the
audit log and secret store already use). Restore reverses the bundle
back into ``app/data/`` and adjacent paths.

What goes IN the bundle:

    app/data/*.json                — tracker, devices, settings, etc.
    app/data/*.hmac                — compatibility sidecars (never trusted;
                                     regenerated locally on restore)
    app/data/*.backup.*.json       — persistence layer's own backups
    app/data/episodes/*.jsonl      — episode recorder telemetry
    app/data/profiles/*.json       — per-user profile files
    app/data/audit.jsonl           — audit trail
    app/data/dupe_log.jsonl        — (future) dupe attempt log
    app/data/secrets.enc.json      — DPAPI-encrypted secret store
    app/data/custom_presets.json   — v5.6.9 custom presets

    app/config/*.json              — application-level config
                                     (settings.json, profiles.json,
                                      hotkeys.json, etc.)

What STAYS OUT (excluded for safety / portability):

    audit webhook URLs              — bearer credentials live only in
                                     the OS-backed secret store
    *.exe, *.dll, *.sys            — binaries — restore on the wrong
                                     machine would risk loader issues
    __pycache__                    — generated, useless
    .venv, venv, env               — interpreter trees
    logs/                          — runtime-rotated, large, low value
    dist/, build/                  — build artifacts
    .git/                          — repo metadata

Schema of the bundle (a single ZIP with a manifest):

    bundle.zip
    ├── manifest.json              — version, created_at, file count,
    │                               app version, sha256 of each entry
    └── files/
        ├── app/data/dayz_accounts.json
        ├── app/data/dayz_accounts.hmac
        ├── app/data/episodes/episode_20260512_010203.jsonl
        └── ...

The optional ``--encrypt`` mode wraps the entire ZIP in a DPAPI blob,
so the bundle is only restorable on the same Windows user account
unless the operator carries the DPAPI master key. Off by default;
useful for backups that travel via Discord/email.

API:

    create_backup(out_path: Path, *, encrypt: bool = False) -> Path
    restore_backup(in_path: Path, *, dry_run: bool = False) -> RestoreResult
    list_bundle(in_path: Path) -> BundleManifest
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, List, Tuple

from app.logs.logger import log_info, log_warning, log_error

__all__ = [
    "BundleManifest",
    "RestoreResult",
    "BackupError",
    "create_backup",
    "restore_backup",
    "list_bundle",
]

BUNDLE_SCHEMA = "dupez.backup-bundle.v1"

# Inclusion globs, relative to repo root. Order matters only for log
# readability — restore is keyed by manifest, not by glob order.
_INCLUDE_GLOBS: Tuple[str, ...] = (
    "app/data/*.json",
    "app/data/*.hmac",
    "app/data/*.backup.*.json",
    "app/data/episodes/*.jsonl",
    "app/data/profiles/*.json",
    "app/data/audit.jsonl",
    "app/data/dupe_log.jsonl",
    "app/data/secrets.enc.json",
    "app/data/custom_presets.json",
    "app/config/*.json",
)

# v5.7.3 SECURITY: restore-side path allowlist.
#
# The create side only ever collects files matching _INCLUDE_GLOBS
# (app/data + app/config). But restore_backup walks the manifest of
# whatever bundle it is handed — and a *hand-crafted malicious* bundle
# could contain an entry like ``app/core/clumsy_network_disruptor.py``
# or ``dupez.py`` with attacker code. The repo-root path-traversal
# guard alone does NOT stop that: the entry stays inside the repo, it
# just overwrites a SOURCE file, which executes on the next launch.
#
# Defense: restore_backup refuses to write any entry whose repo-
# relative path does not start with one of these prefixes. Generated
# data and user config are restorable; executable code and packaging
# are not. A legit DupeZ bundle only contains paths under these
# prefixes anyway, so this never rejects a genuine backup.
# v5.7.3 SECURITY: decompression-bomb caps. restore_backup / list_bundle
# read whole ZIP entries into memory; without a ceiling a 50 KB bundle
# can decompress to fill RAM + disk. These bound a single entry and the
# whole bundle's expanded size. 2 GB total is generous (the episode
# store + all config rarely exceeds tens of MB) but finite.
_MAX_ENTRY_BYTES: int = 512 * 1024 * 1024        # 512 MB per file
_MAX_TOTAL_RESTORE_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB whole bundle
# ZIP metadata and the outer container need their own limits.  Entry caps do
# not protect callers that parse a gigantic central directory or read an
# encrypted wrapper into memory before the archive has even been inspected.
_MAX_MANIFEST_BYTES: int = 8 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS: int = 8_192
_MAX_BUNDLE_BYTES: int = _MAX_TOTAL_RESTORE_BYTES + (64 * 1024 * 1024)
_MAX_IN_MEMORY_BUNDLE_BYTES: int = 512 * 1024 * 1024

# Anything matching these is dropped even if it shows up via the
# include globs (e.g., if a .json file slipped under build/).
_EXCLUDE_SUBSTRINGS: Tuple[str, ...] = (
    "__pycache__",
    "/.venv/",
    "/venv/",
    "/env/",
    "/dist/",
    "/build/",
    "/.git/",
    "/logs/",
)

_SETTINGS_SIDECARS: Dict[str, str] = {
    "app/data/settings.json": "app/data/settings.hmac",
    "app/config/settings.json": "app/config/settings.json.hmac",
}

_NON_JOURNALED_DATA_JSON: frozenset[str] = frozenset({
    # The encrypted secret-store envelope has its own DPAPI-backed format and
    # is not managed by DataPersistenceManager's JSON commit journal.
    "app/data/secrets.enc.json",
})


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class BundleEntry:
    """One file's slot in the bundle manifest."""
    path: str           # repo-relative POSIX path
    size: int
    sha256: str


@dataclass
class BundleManifest:
    """Bundle metadata stored as manifest.json inside the ZIP."""
    schema: str = BUNDLE_SCHEMA
    created_at: str = ""
    app_version: str = ""
    encrypted: bool = False
    entries: List[BundleEntry] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "schema": self.schema,
            "created_at": self.created_at,
            "app_version": self.app_version,
            "encrypted": self.encrypted,
            "entries": [
                {"path": e.path, "size": e.size, "sha256": e.sha256}
                for e in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "BundleManifest":
        if not isinstance(d, dict):
            raise BackupError("bundle manifest must be a JSON object")
        raw_entries = d.get("entries", [])
        if not isinstance(raw_entries, list):
            raise BackupError("bundle manifest entries must be a list")
        entries: List[BundleEntry] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise BackupError("bundle manifest entry must be an object")
            path = raw_entry.get("path")
            size = raw_entry.get("size")
            sha256 = raw_entry.get("sha256")
            if not isinstance(path, str) or not path:
                raise BackupError("bundle manifest entry path must be text")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise BackupError(
                    f"bundle manifest entry has invalid size: {path!r}"
                )
            if (
                not isinstance(sha256, str)
                or len(sha256) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in sha256)
            ):
                raise BackupError(
                    f"bundle manifest entry has invalid SHA-256: {path!r}"
                )
            entries.append(BundleEntry(path=path, size=size, sha256=sha256.lower()))
        return cls(
            schema=str(d.get("schema", "")),
            created_at=str(d.get("created_at", "")),
            app_version=str(d.get("app_version", "")),
            encrypted=bool(d.get("encrypted", False)),
            entries=entries,
        )


@dataclass
class RestoreResult:
    """Outcome of a restore operation."""
    restored: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    hash_mismatches: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.hash_mismatches


class BackupError(Exception):
    """Raised when backup/restore can't proceed safely."""


# ── Internal helpers ──────────────────────────────────────────────────

def _repo_root() -> Path:
    """Find the repo root by walking up from this file."""
    return Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _app_version() -> str:
    try:
        from app import __version__ as _v
        return _v.__version__
    except Exception:
        return "unknown"


def _is_excluded(rel_path: str) -> bool:
    """Match against _EXCLUDE_SUBSTRINGS using POSIX-style separators."""
    norm = rel_path.replace("\\", "/")
    return any(sub in f"/{norm}/" or sub in norm for sub in _EXCLUDE_SUBSTRINGS)


def _collect_files() -> List[Path]:
    """Walk include globs from repo root; dedupe; filter excludes."""
    root = _repo_root()
    seen: set = set()
    out: List[Path] = []
    for pattern in _INCLUDE_GLOBS:
        for p in root.glob(pattern):
            if not p.is_file():
                continue
            try:
                rel = p.resolve().relative_to(root)
            except ValueError:
                # File lives outside repo (symlink); skip on principle.
                continue
            rel_posix = rel.as_posix()
            if _is_excluded(rel_posix):
                continue
            if rel_posix in seen:
                continue
            seen.add(rel_posix)
            out.append(p)
    return sorted(out)


def _collect_backup_entries() -> List[Tuple[Path, str]]:
    """Return source paths paired with stable bundle-relative names."""
    from app.core.app_paths import config_dir, data_dir, is_installed_runtime

    if not is_installed_runtime():
        return [
            (path, path.resolve().relative_to(_repo_root()).as_posix())
            for path in _collect_files()
        ]

    entries: List[Tuple[Path, str]] = []
    seen: set[str] = set()
    for base, prefix, patterns in (
        (
            data_dir(),
            "app/data",
            (
                "*.json",
                "*.hmac",
                "*.backup.*.json",
                "episodes/*.jsonl",
                "profiles/*.json",
                "models/*",
                "audit.jsonl",
                "dupe_log.jsonl",
            ),
        ),
        (config_dir(), "app/config", ("*.json", "*.hmac")),
    ):
        if not base.exists():
            continue
        for pattern in patterns:
            for path in base.glob(pattern):
                if not path.is_file():
                    continue
                rel = f"{prefix}/{path.relative_to(base).as_posix()}"
                if rel in seen or _is_excluded(rel):
                    continue
                seen.add(rel)
                entries.append((path, rel))
    return sorted(entries, key=lambda item: item[1])


def _restore_destination(entry_path: str) -> Path:
    """Map stable bundle paths to the current runtime storage roots."""
    from app.core.app_paths import config_dir, data_dir, is_installed_runtime

    norm = _canonical_restore_path(entry_path)
    relative = PurePosixPath(norm).parts[2:]
    if not is_installed_runtime():
        base = (
            _repo_root() / "app" / "data"
            if norm.startswith("app/data/")
            else _repo_root() / "app" / "config"
        )
        return base.joinpath(*relative).resolve()
    if norm.startswith("app/data/"):
        return data_dir().joinpath(*relative).resolve()
    if norm.startswith("app/config/"):
        return config_dir().joinpath(*relative).resolve()
    raise BackupError(f"non-restorable path: {entry_path!r}")


def _canonical_restore_path(entry_path: str) -> str:
    """Return a canonical allowlisted POSIX bundle path or raise.

    Archive paths are logical paths, not host paths. Backslashes, absolute
    forms, dot segments, repeated separators, and parent traversal are all
    rejected before a ZIP member is opened or a destination is resolved.
    """
    if not isinstance(entry_path, str) or not entry_path:
        raise BackupError("bundle entry path must be non-empty text")
    if "\\" in entry_path or "\x00" in entry_path:
        raise BackupError("bundle entry path is not canonical POSIX form")
    if entry_path.startswith("/") or entry_path.endswith("/"):
        raise BackupError("absolute or directory bundle paths are not allowed")
    raw_parts = entry_path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise BackupError("bundle entry path contains a non-canonical segment")
    if any(":" in part or part.endswith((".", " ")) for part in raw_parts):
        raise BackupError(
            "bundle entry path contains a Windows-ambiguous segment"
        )
    path = PurePosixPath(entry_path)
    if path.is_absolute() or path.as_posix() != entry_path:
        raise BackupError("bundle entry path is not canonical POSIX form")
    parts = path.parts
    if (
        len(parts) < 3
        or parts[0] != "app"
        or parts[1] not in {"data", "config"}
    ):
        raise BackupError(
            "bundle entries must be files below app/data or app/config"
        )
    return path.as_posix()


def _restore_destination_identity(entry_path: str) -> str:
    """Return the portable Windows identity of one restore destination.

    Backup bundles can be created or inspected on a case-sensitive host but
    later restored on Windows. Resolve against the actual runtime root before
    case-folding so case variants and existing filesystem aliases (including
    expanded short names) can never select the same Windows destination.
    """
    canonical = _canonical_restore_path(entry_path)
    destination = _restore_destination(canonical)
    return os.path.normcase(str(destination)).casefold()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _journal_sidecar_payload(rel_path: str, payload: bytes) -> bytes:
    """Return a fresh compatibility tag for an archived journal payload."""
    try:
        if _is_journaled_data_json(rel_path):
            from app.core.data_persistence import _compute_hmac

            return _compute_hmac(payload).encode("ascii")
        if rel_path.casefold() == "app/config/settings.json":
            from app.config import _compute_tag

            return _compute_tag(payload).encode("ascii")
    except Exception as exc:
        raise BackupError(
            "could not integrity-sign authenticated state for backup"
        ) from exc
    raise BackupError(f"unsupported journal payload: {rel_path!r}")


def _is_journaled_data_json(rel_path: str) -> bool:
    """Return whether *rel_path* uses the authenticated data journal."""
    path = PurePosixPath(rel_path)
    folded_parts = tuple(part.casefold() for part in path.parts)
    return (
        len(path.parts) == 3
        and folded_parts[:2] == ("app", "data")
        and path.suffix.casefold() == ".json"
        and rel_path.casefold() not in {
            item.casefold() for item in _NON_JOURNALED_DATA_JSON
        }
    )


def _journal_sidecar_rel_path(rel_path: str) -> str | None:
    """Return the canonical compatibility-sidecar name for journal JSON."""
    folded = rel_path.casefold()
    if folded == "app/config/settings.json":
        return f"{rel_path}.hmac"
    if not _is_journaled_data_json(rel_path):
        return None
    if folded == "app/data/update_state.json":
        return f"{rel_path}.hmac"
    return PurePosixPath(rel_path).with_suffix(".hmac").as_posix()


def _restored_hmac_path(rel_path: str, destination: Path) -> Path | None:
    """Return the local compatibility-sidecar path for journaled JSON."""
    folded = rel_path.casefold()
    if folded == "app/config/settings.json":
        return Path(str(destination) + ".hmac")
    if not _is_journaled_data_json(rel_path):
        return None
    if folded == "app/data/update_state.json":
        return Path(str(destination) + ".hmac")
    return destination.with_suffix(".hmac")


def _is_transported_journal_hmac(rel_path: str) -> bool:
    """Reject machine-bound journal tags transported inside a backup."""
    folded = rel_path.casefold()
    if folded in {item.casefold() for item in _SETTINGS_SIDECARS.values()}:
        return True
    path = PurePosixPath(rel_path)
    folded_parts = tuple(part.casefold() for part in path.parts)
    if (
        len(path.parts) != 3
        or folded_parts[:2] != ("app", "data")
        or path.suffix.casefold() != ".hmac"
    ):
        return False
    name = path.name
    if name.casefold().endswith(".json.hmac"):
        payload_name = name[:-len(".hmac")]
    else:
        payload_name = f"{path.stem}.json"
    return _is_journaled_data_json(
        PurePosixPath("app", "data", payload_name).as_posix()
    )


def _backup_source_payload(source: Path, rel_path: str) -> bytes:
    """Read the committed journal payload, never a stale projection."""
    hmac_path = _restored_hmac_path(rel_path, source)
    if hmac_path is None:
        return source.read_bytes()

    from app.core.data_persistence import (
        DataPersistenceManager,
        _authenticated_state_lock,
    )

    with _authenticated_state_lock(source):
        if not DataPersistenceManager._pointer_path(source).is_file():
            # Preserve legacy bundle behavior until a commit journal exists.
            return source.read_bytes()
        payload = DataPersistenceManager._read_authenticated_bytes(
            source,
            hmac_path=hmac_path,
            require_hmac=True,
            _lock_held=True,
        )
    if payload is None:
        raise BackupError(
            f"authenticated journal is invalid for {rel_path!r}"
        )
    return payload


def _replace_restored_authenticated_pair(
    rel_path: str,
    destination: Path,
    payload: bytes,
    *,
    hmac_path: Path,
) -> None:
    """Commit restored JSON through the live authenticated-state journal."""
    try:
        from app.core.data_persistence import DataPersistenceManager

        DataPersistenceManager._replace_authenticated_pair(
            destination,
            payload,
            hmac_path=hmac_path,
        )
    except Exception as exc:
        raise BackupError(
            f"could not transactionally restore {rel_path!r}"
        ) from exc


def _dpapi_encrypt(payload: bytes) -> bytes:
    """Wrap *payload* with DPAPI CurrentUser scope.

    Raises BackupError on non-Windows or DPAPI failure. Operators
    requesting encrypt=True on Linux/macOS get a clear failure rather
    than silently shipping plaintext.
    """
    if not sys.platform.startswith("win"):
        raise BackupError(
            "encrypt=True requires Windows DPAPI; not available on this OS"
        )
    try:
        import ctypes
        from ctypes import wintypes
    except Exception as exc:
        raise BackupError(f"ctypes unavailable: {exc}") from exc

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]

    in_blob = DATA_BLOB(
        len(payload),
        ctypes.cast(
            ctypes.c_char_p(payload), ctypes.POINTER(ctypes.c_byte)
        ),
    )
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), "DupeZ-backup", None, None, None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(out_blob),
    ):
        raise BackupError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _dpapi_decrypt(blob: bytes) -> bytes:
    if not sys.platform.startswith("win"):
        raise BackupError(
            "decrypt requires Windows DPAPI; not available on this OS"
        )
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte))]

    in_blob = DATA_BLOB(
        len(blob),
        ctypes.cast(
            ctypes.c_char_p(blob), ctypes.POINTER(ctypes.c_byte)
        ),
    )
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(out_blob),
    ):
        raise BackupError(
            "CryptUnprotectData failed (wrong user account, or "
            "bundle was encrypted under a different DPAPI master key)"
        )
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _bounded_file_bytes(path: Path, limit: int, *, label: str) -> bytes:
    """Read at most *limit* bytes, including protection against file races."""
    try:
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except OSError as exc:
        raise BackupError(f"could not read {label}") from exc
    if len(payload) > limit:
        raise BackupError(f"{label} exceeds the {limit}-byte size cap")
    return payload


def _open_bundle_archive(in_path) -> zipfile.ZipFile:
    """Open a bounded bundle without materializing ordinary ZIPs in RAM."""
    path = Path(in_path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BackupError("backup bundle is unavailable") from exc
    if not path.is_file():
        raise BackupError("backup bundle is not a regular file")
    if size > _MAX_BUNDLE_BYTES:
        raise BackupError(
            f"backup bundle exceeds the {_MAX_BUNDLE_BYTES}-byte size cap"
        )

    try:
        if str(path).casefold().endswith(".dpapi"):
            if size > _MAX_IN_MEMORY_BUNDLE_BYTES:
                raise BackupError(
                    "encrypted backup exceeds the in-memory decryption cap"
                )
            encrypted = _bounded_file_bytes(
                path,
                _MAX_IN_MEMORY_BUNDLE_BYTES,
                label="encrypted backup bundle",
            )
            decrypted = _dpapi_decrypt(encrypted)
            if len(decrypted) > _MAX_BUNDLE_BYTES:
                raise BackupError("decrypted backup exceeds the size cap")
            return zipfile.ZipFile(io.BytesIO(decrypted))
        return zipfile.ZipFile(path)
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise BackupError("backup bundle is not a valid ZIP archive") from exc


def _validated_archive_members(
    zf: zipfile.ZipFile,
) -> List[zipfile.ZipInfo]:
    """Return a duplicate-free, count-bounded ZIP directory."""
    members = zf.infolist()
    if len(members) > _MAX_ARCHIVE_MEMBERS:
        raise BackupError(
            "backup bundle contains too many ZIP members "
            f"({len(members)} > {_MAX_ARCHIVE_MEMBERS})"
        )
    names = [member.filename for member in members]
    if len(names) != len(set(names)):
        raise BackupError("bundle contains duplicate ZIP member names")
    return members


def _read_bundle_manifest(zf: zipfile.ZipFile) -> BundleManifest:
    """Read and validate the bounded manifest member."""
    try:
        info = zf.getinfo("manifest.json")
    except KeyError as exc:
        raise BackupError("bundle is missing manifest.json") from exc
    if info.is_dir():
        raise BackupError("bundle manifest is not a file")
    if info.file_size > _MAX_MANIFEST_BYTES:
        raise BackupError("bundle manifest exceeds the size cap")
    try:
        with zf.open(info) as handle:
            raw = handle.read(_MAX_MANIFEST_BYTES + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise BackupError("bundle manifest could not be read") from exc
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise BackupError("bundle manifest exceeds the size cap")
    if len(raw) != info.file_size:
        raise BackupError("bundle manifest length does not match ZIP metadata")
    try:
        doc = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("bundle manifest is not valid JSON") from exc
    manifest = BundleManifest.from_dict(doc)
    if len(manifest.entries) >= _MAX_ARCHIVE_MEMBERS:
        raise BackupError("bundle manifest contains too many entries")
    return manifest


# ── Public API ────────────────────────────────────────────────────────

def create_backup(out_path, *, encrypt: bool = False) -> Path:
    """Bundle every persisted file into *out_path*.

    Returns the actual written path. When *encrypt* is True, the
    ``.zip`` becomes ``.zip.dpapi`` and is wrapped with DPAPI under
    CurrentUser scope.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    files = _collect_backup_entries()
    if not files:
        log_warning("create_backup: nothing to back up (no matching files)")

    manifest = BundleManifest(
        created_at=_now_iso(),
        app_version=_app_version(),
        encrypted=bool(encrypt),
    )

    # Build the ZIP in memory so we can DPAPI-wrap the whole blob if
    # requested. Most backups are well under 100 MB (the episode store
    # rotates and the persistence files are small); the memory cost
    # is acceptable for the simpler control flow.
    # Materialize and sanitize before opening the output ZIP.  A legacy
    # ``audit_webhook.url`` is a bearer credential and must never be copied
    # into a newly-created archive, including rotated settings backups.
    payloads: Dict[str, bytes] = {}
    from app.core.audit_webhook_config import sanitize_settings_payload

    for src, rel in files:
        try:
            data = _backup_source_payload(src, rel)
        except OSError as exc:
            log_warning(f"create_backup: skipping {src}: {exc}")
            continue
        data, recognized_settings = sanitize_settings_payload(rel, data)
        if recognized_settings and data is None:
            log_warning(
                f"create_backup: skipping invalid settings payload {rel}"
            )
            continue
        if data is not None:
            payloads[rel] = data

    # Machine-bound source tags may describe a stale compatibility projection
    # or pre-sanitization settings bytes. Drop every transported journal tag,
    # then emit one freshly computed compatibility sidecar under the exact
    # convention used by that logical target. Restore still regenerates these
    # tags under the destination machine's key.
    for rel in tuple(payloads):
        if _is_transported_journal_hmac(rel):
            payloads.pop(rel)
    for rel, data in tuple(payloads.items()):
        sidecar_rel = _journal_sidecar_rel_path(rel)
        if sidecar_rel is not None:
            payloads[sidecar_rel] = _journal_sidecar_payload(rel, data)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel, data in sorted(payloads.items()):
            entry_path = f"files/{rel}"
            zf.writestr(entry_path, data)
            manifest.entries.append(
                BundleEntry(
                    path=rel, size=len(data), sha256=_hash_bytes(data)
                )
            )
        zf.writestr(
            "manifest.json",
            json.dumps(manifest.to_dict(), indent=2, sort_keys=True),
        )

    raw = buf.getvalue()
    if encrypt:
        raw = _dpapi_encrypt(raw)
        # Mark the file with .dpapi extension to make the
        # restore-side detection unambiguous.
        if out.suffix != ".dpapi":
            out = out.with_suffix(out.suffix + ".dpapi")

    out.write_bytes(raw)
    log_info(
        f"Backup written: {out} "
        f"({len(manifest.entries)} files, {len(raw):,} bytes, "
        f"encrypted={encrypt})"
    )
    return out


def list_bundle(in_path) -> BundleManifest:
    """Parse and return the bundle manifest without restoring."""
    with _open_bundle_archive(in_path) as zf:
        _validated_archive_members(zf)
        manifest = _read_bundle_manifest(zf)
    if manifest.schema != BUNDLE_SCHEMA:
        raise BackupError(
            f"unsupported bundle schema: {manifest.schema!r} "
            f"(expected {BUNDLE_SCHEMA!r})"
        )
    return manifest


def restore_backup(in_path, *, dry_run: bool = False) -> RestoreResult:
    """Restore every entry from *in_path* back into the repo tree.

    Existing files are overwritten WITHOUT warning — the operator is
    expected to have confirmed the action in the UI before calling.
    Returns a :class:`RestoreResult` describing what landed.

    When *dry_run* is True, no files are written; the result still
    populates ``restored`` so the operator can preview impact.
    """
    result = RestoreResult()
    try:
        with _open_bundle_archive(in_path) as zf:
            _validated_archive_members(zf)
            manifest = _read_bundle_manifest(zf)
            if manifest.schema != BUNDLE_SCHEMA:
                raise BackupError(
                    f"unsupported bundle schema: {manifest.schema!r}"
                )

            destination_counts: Dict[str, int] = {}
            for candidate in manifest.entries:
                try:
                    identity = _restore_destination_identity(candidate.path)
                except BackupError:
                    continue
                destination_counts[identity] = (
                    destination_counts.get(identity, 0) + 1
                )

            total_bytes = 0
            for entry in manifest.entries:
                # ── SECURITY GATE 1: path allowlist ───────────────────
                # Reject anything outside app/data + app/config BEFORE
                # reading it. A malicious bundle entry like
                # app/core/<x>.py or dupez.py would execute on next
                # launch if restored — refuse outright.
                try:
                    norm = _canonical_restore_path(entry.path)
                except BackupError:
                    log_error(
                        f"restore_backup: BLOCKED non-allowlisted path "
                        f"{entry.path!r} — only app/data/ and app/config/ "
                        f"canonical file paths are restorable"
                    )
                    result.skipped.append(entry.path)
                    continue
                destination_identity = _restore_destination_identity(norm)
                if destination_counts[destination_identity] > 1:
                    log_error(
                        "restore_backup: BLOCKED ambiguous case-insensitive "
                        f"destination {entry.path!r}"
                    )
                    result.skipped.append(entry.path)
                    continue

                # ── SECURITY GATE 2: per-entry size cap ───────────────
                if entry.size > _MAX_ENTRY_BYTES:
                    log_error(
                        f"restore_backup: BLOCKED oversized entry "
                        f"{entry.path!r} ({entry.size} bytes > "
                        f"{_MAX_ENTRY_BYTES}) — possible decompression bomb"
                    )
                    result.skipped.append(entry.path)
                    continue
                src_in_zip = f"files/{norm}"
                try:
                    zip_info = zf.getinfo(src_in_zip)
                except KeyError:
                    result.skipped.append(entry.path)
                    continue
                if zip_info.is_dir() or zip_info.file_size != entry.size:
                    raise BackupError(
                        f"bundle entry size mismatch: {entry.path!r}"
                    )
                total_bytes += zip_info.file_size
                if total_bytes > _MAX_TOTAL_RESTORE_BYTES:
                    log_error(
                        f"restore_backup: ABORTED — bundle expands beyond "
                        f"{_MAX_TOTAL_RESTORE_BYTES} bytes total "
                        f"(decompression-bomb guard)"
                    )
                    raise BackupError(
                        "bundle exceeds total restore size cap"
                    )

                with zf.open(zip_info) as f:
                    # Read one byte past the declared and ZIP-directory size.
                    # Exact length is mandatory; neither metadata source can
                    # be used to bypass aggregate decompression accounting.
                    data = f.read(entry.size + 1)

                if len(data) != entry.size:
                    raise BackupError(
                        f"bundle entry length mismatch: {entry.path!r}"
                    )

                if _hash_bytes(data) != entry.sha256:
                    log_error(
                        f"restore_backup: hash mismatch on {entry.path} "
                        f"— bundle entry corrupted or tampered; refusing "
                        f"to write"
                    )
                    result.hash_mismatches.append(entry.path)
                    continue

                # Journal HMACs are tied to the source user's machine-local
                # key. Never install them from a bundle: the matching JSON is
                # committed below and receives a fresh local tag. If its JSON
                # is absent or rejected, preserving the live tag is safer than
                # installing an orphaned, unverifiable one.
                if _is_transported_journal_hmac(norm):
                    result.skipped.append(entry.path)
                    continue

                from app.core.audit_webhook_config import sanitize_settings_payload

                sanitized, recognized_settings = sanitize_settings_payload(
                    norm,
                    data,
                )
                if recognized_settings and sanitized is None:
                    log_error(
                        f"restore_backup: BLOCKED invalid settings payload "
                        f"{entry.path!r}"
                    )
                    result.skipped.append(entry.path)
                    continue
                if sanitized is not None:
                    data = sanitized

                if dry_run:
                    result.restored.append(entry.path)
                    continue

                dest = _restore_destination(norm)
                try:
                    from app.core.app_paths import (
                        config_dir,
                        data_dir,
                        is_installed_runtime,
                    )

                    allowed_roots = (
                        [data_dir().resolve(), config_dir().resolve()]
                        if is_installed_runtime()
                        else [
                            (_repo_root() / "app" / "data").resolve(),
                            (_repo_root() / "app" / "config").resolve(),
                        ]
                    )
                    if not any(
                        dest == root or root in dest.parents
                        for root in allowed_roots
                    ):
                        raise ValueError
                except ValueError:
                    log_error(
                        f"restore_backup: path traversal blocked: {entry.path}"
                    )
                    result.skipped.append(entry.path)
                    continue

                hmac_path = _restored_hmac_path(norm, dest)
                if hmac_path is not None:
                    _replace_restored_authenticated_pair(
                        norm,
                        dest,
                        data,
                        hmac_path=hmac_path,
                    )
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    import tempfile

                    stage_fd, stage_name = tempfile.mkstemp(
                        prefix=f".{dest.name}.",
                        suffix=".restoring",
                        dir=str(dest.parent),
                    )
                    tmp_dest = Path(stage_name)
                    try:
                        with os.fdopen(stage_fd, "wb") as handle:
                            handle.write(data)
                            handle.flush()
                            os.fsync(handle.fileno())
                        if _hash_bytes(tmp_dest.read_bytes()) != _hash_bytes(data):
                            raise BackupError(
                                f"post-write verification failed: {entry.path}"
                            )
                        os.replace(tmp_dest, dest)
                    finally:
                        tmp_dest.unlink(missing_ok=True)
                result.restored.append(entry.path)

        log_info(
            f"Backup restore complete: {len(result.restored)} restored, "
            f"{len(result.skipped)} skipped, "
            f"{len(result.hash_mismatches)} hash mismatches"
            f"{' (dry run)' if dry_run else ''}"
        )
    except BackupError as e:
        result.error = str(e)
        log_error(f"restore_backup: {e}")
    except Exception as e:
        result.error = f"unexpected: {e}"
        log_error(f"restore_backup unexpected: {e}")
    return result
