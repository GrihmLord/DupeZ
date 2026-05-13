"""One-click backup + restore for DupeZ (v5.6.9 feature #7).

Bundles every persisted file DupeZ owns into a single ZIP, optionally
encrypted with the operator's DPAPI-derived key (the same key the
audit log and secret store already use). Restore reverses the bundle
back into ``app/data/`` and adjacent paths.

What goes IN the bundle:

    app/data/*.json                — tracker, devices, settings, etc.
    app/data/*.hmac                — sidecar HMACs (verified on restore)
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
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
        return cls(
            schema=str(d.get("schema", "")),
            created_at=str(d.get("created_at", "")),
            app_version=str(d.get("app_version", "")),
            encrypted=bool(d.get("encrypted", False)),
            entries=[
                BundleEntry(
                    path=str(e.get("path", "")),
                    size=int(e.get("size", 0)),
                    sha256=str(e.get("sha256", "")),
                )
                for e in d.get("entries", [])
            ],
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


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


# ── Public API ────────────────────────────────────────────────────────

def create_backup(out_path, *, encrypt: bool = False) -> Path:
    """Bundle every persisted file into *out_path*.

    Returns the actual written path. When *encrypt* is True, the
    ``.zip`` becomes ``.zip.dpapi`` and is wrapped with DPAPI under
    CurrentUser scope.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    files = _collect_files()
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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src in files:
            try:
                data = src.read_bytes()
            except OSError as exc:
                log_warning(f"create_backup: skipping {src}: {exc}")
                continue
            rel = src.resolve().relative_to(_repo_root()).as_posix()
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
    raw = Path(in_path).read_bytes()
    if str(in_path).endswith(".dpapi"):
        raw = _dpapi_decrypt(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        with zf.open("manifest.json") as f:
            doc = json.loads(f.read())
    manifest = BundleManifest.from_dict(doc)
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
        raw = Path(in_path).read_bytes()
        if str(in_path).endswith(".dpapi"):
            raw = _dpapi_decrypt(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with zf.open("manifest.json") as f:
                manifest = BundleManifest.from_dict(json.loads(f.read()))
            if manifest.schema != BUNDLE_SCHEMA:
                raise BackupError(
                    f"unsupported bundle schema: {manifest.schema!r}"
                )

            root = _repo_root()
            for entry in manifest.entries:
                src_in_zip = f"files/{entry.path}"
                try:
                    with zf.open(src_in_zip) as f:
                        data = f.read()
                except KeyError:
                    result.skipped.append(entry.path)
                    continue

                if _hash_bytes(data) != entry.sha256:
                    log_error(
                        f"restore_backup: hash mismatch on {entry.path} "
                        f"— bundle entry corrupted; refusing to write"
                    )
                    result.hash_mismatches.append(entry.path)
                    continue

                if dry_run:
                    result.restored.append(entry.path)
                    continue

                dest = (root / entry.path).resolve()
                try:
                    # Refuse to escape the repo tree.
                    dest.relative_to(root.resolve())
                except ValueError:
                    log_error(
                        f"restore_backup: path traversal blocked: {entry.path}"
                    )
                    result.skipped.append(entry.path)
                    continue

                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
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
