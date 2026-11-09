"""
Data persistence system for DupeZ application.

Provides atomic JSON file storage with backup rotation, corruption
recovery, HMAC integrity verification, and a generic collection
manager that eliminates per-type boilerplate.

Security Features:
  - Crash-consistent authenticated generations with an atomic commit pointer
  - HMAC-SHA384 integrity tags: every saved file gets a companion
    .hmac compatibility projection; committed generations are authoritative.
  - Backup rotation with corruption recovery
  - Optional encryption at rest (via SecretsManager)

NOTE: Global manager instances are created at module import time,
which triggers directory creation and file I/O.  This is intentional —
persistence must be available before any other subsystem initialises.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.logs.logger import log_error, log_info

__all__ = [
    "PersistenceConfig",
    "DataPersistenceManager",
    "persistence_manager",
    "AutoSaveMixin",
    "CollectionManager",
    "SettingsManager",
    "DeviceManager",
    "AccountManager",
    "MarkerManager",
    "NicknameManager",
    "DeviceCacheManager",
    "settings_manager",
    "device_manager",
    "account_manager",
    "marker_manager",
    "nickname_manager",
    "device_cache_manager",
    "save_all_data",
    "get_persistence_info",
    "persistence_key_degraded",
]


# ── HMAC Integrity ───────────────────────────────────────────────────
#
# The HMAC key is a 32-byte per-install secret managed by
# :mod:`app.core.secret_store` under ``kind="persistence.hmac"``:
#
#   * Windows → sealed with DPAPI (user scope). Extracting the key
#     requires a logon session for the installing user *plus* access
#     to the ciphertext on disk; an attacker with read access to the
#     ``app/data/*.hmac`` files alone cannot forge integrity tags.
#   * POSIX   → 0o600 file under ``$XDG_DATA_HOME/DupeZ/secrets/``.
#
# A previous version of this module derived the "key" deterministically
# from ``platform.node() | $USERNAME | platform.machine() | <literal>``
# — values the local attacker already owns. That scheme provided only
# the illusion of integrity.  We retain the old derivation here **only**
# as a one-shot verification rung so that existing on-disk
# ``.hmac`` files still load; the next save re-signs them under the
# new secret-store-rooted key.

PERSISTENCE_SECRET_KIND: str = "persistence.hmac"
PERSISTENCE_KEY_SIZE: int = 32

_KEY_LOCK = threading.Lock()
_KEY_CACHE: Optional[bytes] = None
_KEY_DEGRADED: bool = False


# Authenticated files use an immutable generation plus one authenticated,
# atomically-replaced commit pointer.  ``<name>.json`` and its HMAC remain as
# a compatibility projection, but are never authoritative once a pointer
# exists.  A process can therefore die between either projection replacement
# without losing the last committed payload.
_GENERATION_SCHEMA = "dupez.authenticated-generation.v1"
_POINTER_SCHEMA = "dupez.authenticated-pointer.v1"
_GENERATION_TOKEN_BYTES = 16
_MAX_GENERATIONS = 2
_TARGET_LOCKS_GUARD = threading.Lock()
_TARGET_LOCKS: dict[str, threading.RLock] = {}


def _persistence_fault_point(_phase: str, _target: Path) -> None:
    """No-op fault point replaced only by focused crash tests."""


def _target_key(path: Path) -> str:
    """Return a stable process-local key for a logical state target."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _local_target_lock(path: Path) -> threading.RLock:
    key = _target_key(path)
    with _TARGET_LOCKS_GUARD:
        return _TARGET_LOCKS.setdefault(key, threading.RLock())


@contextlib.contextmanager
def _authenticated_state_lock(path: Path) -> Iterator[None]:
    """Serialize writers to *path* across both threads and processes.

    The advisory byte lock is mandatory for every supported platform.  A
    lock-backend failure aborts the transaction instead of silently reducing
    the guarantee to process-local serialization.  The lock file is retained
    permanently so no unlink/recreate race can split cooperating writers.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.auth.lock")
    with _local_target_lock(path):
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+b", closefd=True) as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _get_hmac_key() -> bytes:
    """Return the HMAC key, loading it from :mod:`secret_store` once.

    Secret-store failure is an integrity stop condition. The predictable
    legacy machine derivation remains available only as a verification rung
    *after* this function has successfully obtained the real secret; it is
    never used to sign new state or as an availability fallback.
    """
    global _KEY_CACHE, _KEY_DEGRADED
    if _KEY_CACHE is not None:
        return _KEY_CACHE
    with _KEY_LOCK:
        if _KEY_CACHE is not None:
            return _KEY_CACHE
        try:
            from app.core.secret_store import get_or_create_secret
            key = get_or_create_secret(
                PERSISTENCE_SECRET_KIND, size=PERSISTENCE_KEY_SIZE,
            )
            if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
                raise RuntimeError(
                    f"secret_store returned invalid key "
                    f"(len={len(key) if key else 0})"
                )
            _KEY_CACHE = bytes(key)
            _KEY_DEGRADED = False
        except Exception as e:
            log_error(
                "persistence: secret store unavailable "
                f"({type(e).__name__}); authenticated data operations are "
                "disabled until secret-store access is restored"
            )
            _KEY_DEGRADED = True
            raise RuntimeError("persistence HMAC key is unavailable") from e
        return _KEY_CACHE


def _get_legacy_hmac_key() -> bytes:
    """Legacy machine-derived key — kept ONLY for verification fallback.

    Any file whose stored HMAC matches under this key will be silently
    re-signed under the new secret-store-rooted key on its next save.
    """
    import platform
    parts = [
        platform.node(),
        os.environ.get("USERNAME", os.environ.get("USER", "default")),
        platform.machine(),
        "DupeZ-DataIntegrity-v1",  # domain separation
    ]
    seed = "|".join(parts).encode("utf-8")
    return hashlib.sha384(seed).digest()


def _compute_hmac(data: bytes) -> str:
    """Compute HMAC-SHA384 hex digest for data integrity."""
    return hmac.new(_get_hmac_key(), data, hashlib.sha384).hexdigest()


def _verify_hmac(data: bytes, expected_hex: str) -> bool:
    """Constant-time HMAC verification.

    Tries the current secret-store-rooted key first; on mismatch, the
    caller (:meth:`DataPersistenceManager._try_load_json`) also gets a
    chance to normalise CRLF and to try the legacy key. We expose a
    single-key check here and keep the fallback orchestration visible
    at the call site so the ladder is auditable.
    """
    computed = hmac.new(_get_hmac_key(), data, hashlib.sha384).hexdigest()
    return hmac.compare_digest(computed, expected_hex)


def _verify_hmac_legacy(data: bytes, expected_hex: str) -> bool:
    """Verify a legacy tag only when the durable key store is available."""
    # This call is an explicit guard: the predictable derivation cannot become
    # an availability fallback if the secret store is down.
    _get_hmac_key()
    computed = hmac.new(
        _get_legacy_hmac_key(), data, hashlib.sha384
    ).hexdigest()
    return hmac.compare_digest(computed, expected_hex)


# ── Data directory resolution ─────────────────────────────────────────

def _resolve_data_directory() -> str:
    """Return source-tree data in development and per-user data when installed."""
    from app.core.app_paths import data_dir, ensure_runtime_migration

    ensure_runtime_migration()
    return str(data_dir())


# ── Configuration ─────────────────────────────────────────────────────

@dataclass
class PersistenceConfig:
    """Configuration for the persistence manager.

    If *data_directory* is left empty (the default) it is resolved
    automatically via :func:`_resolve_data_directory` in ``__post_init__``.
    """

    auto_save: bool = True
    save_interval: int = 30  # seconds between implicit saves
    backup_enabled: bool = True
    max_backups: int = 5
    data_directory: str = ""

    def __post_init__(self) -> None:
        if not self.data_directory:
            self.data_directory = _resolve_data_directory()


# ── Core persistence manager ─────────────────────────────────────────

class DataPersistenceManager:
    """Centralised, thread-safe data persistence manager.

    All public methods that touch ``_dirty_data`` or ``_data_cache``
    acquire ``_lock`` first.
    """

    def __init__(self, config: Optional[PersistenceConfig] = None) -> None:
        self.config = config or PersistenceConfig()
        self.data_directory = Path(self.config.data_directory)
        self.data_directory.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._dirty_data: set[str] = set()
        self._last_save_time: float = time.time()
        self._data_cache: Dict[str, Any] = {}

        log_info("Data persistence manager initialized")

    # ── Save / load ───────────────────────────────────────────────

    def save_data(self, data_type: str, data: Any, force: bool = False) -> bool:
        """Persist *data* behind an authenticated atomic commit pointer.

        The traditional JSON/HMAC files remain a compatibility projection.
        Readers recover that projection from the committed immutable
        generation if the process stops between its two replacements.
        """
        if data_type == "settings":
            # Webhook URLs are bearer credentials.  This serialization guard
            # makes it impossible for a bypassing caller to write one back to
            # settings.json; supported provisioning is routed through
            # audit_webhook_config and the OS-backed secret store.
            from app.core.audit_webhook_config import sanitize_settings_document

            data = sanitize_settings_document(data)
        with self._lock:
            try:
                if not force and not self._should_save_locked(data_type):
                    return True

                file_path = self.data_directory / f"{data_type}.json"

                if self.config.backup_enabled and file_path.exists():
                    self._create_backup(file_path)

                # Binary JSON avoids Windows newline translation: the exact
                # staged bytes are what the HMAC authenticates.
                raw_json = json.dumps(data, indent=2, ensure_ascii=False)
                raw_bytes = raw_json.encode("utf-8")
                self._replace_authenticated_pair(file_path, raw_bytes)

                self._data_cache[data_type] = data
                self._dirty_data.discard(data_type)
                self._last_save_time = time.time()
                return True

            except Exception as e:
                log_error(f"Failed to save {data_type}: {e}")
                return False

    @staticmethod
    def _write_staged(path: Path, payload: bytes) -> None:
        """Write and fsync one staging file without replacing its target."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

    @classmethod
    def _write_random_stage(
        cls,
        parent: Path,
        prefix: str,
        payload: bytes,
    ) -> Path:
        """Create, write, and fsync an exclusive random same-dir stage."""
        parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=prefix,
            dir=str(parent),
            delete=False,
        )
        path = Path(handle.name)
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        """Persist directory entry changes where the platform exposes fsync.

        Windows rejects directory ``fsync``.  The Windows replacement path
        below instead uses ``MoveFileExW(MOVEFILE_WRITE_THROUGH)``, the native
        durability equivalent for same-volume renames.
        """
        if os.name == "nt":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @classmethod
    def _durable_replace(
        cls,
        source: Path,
        destination: Path,
        *,
        replace: bool = True,
    ) -> None:
        """Durably install *source* at *destination* in the same directory."""
        source = Path(source)
        destination = Path(destination)
        if source.parent.resolve() != destination.parent.resolve():
            raise OSError("authenticated state replacement must stay in one directory")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            move_file = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
            move_file.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
            move_file.restype = wintypes.BOOL
            flags = 0x00000008  # MOVEFILE_WRITE_THROUGH
            if replace:
                flags |= 0x00000001  # MOVEFILE_REPLACE_EXISTING
            if not move_file(
                os.path.abspath(source),
                os.path.abspath(destination),
                flags,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return
        if replace:
            os.replace(source, destination)
        else:
            # link() supplies no-overwrite semantics for immutable generations.
            os.link(source, destination)
            source.unlink()
        cls._fsync_directory(destination.parent)

    @staticmethod
    def _pointer_path(file_path: Path) -> Path:
        return file_path.with_name(f".{file_path.name}.auth-commit")

    @staticmethod
    def _generation_path(file_path: Path, token: str) -> Path:
        return file_path.with_name(f".{file_path.name}.auth-gen-{token}")

    @staticmethod
    def _valid_generation_token(token: object) -> bool:
        return (
            isinstance(token, str)
            and len(token) == _GENERATION_TOKEN_BYTES * 2
            and all(char in "0123456789abcdef" for char in token)
        )

    @staticmethod
    def _target_identity(file_path: Path) -> str:
        normalized = os.path.normcase(os.path.abspath(os.fspath(file_path)))
        return hashlib.sha384(os.fsencode(normalized)).hexdigest()

    @staticmethod
    def _canonical_record(record: dict[str, Any]) -> bytes:
        return json.dumps(
            record,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def _encode_authenticated_record(cls, record: dict[str, Any]) -> bytes:
        record_bytes = cls._canonical_record(record)
        envelope = {
            "record": record,
            "hmac_sha384": _compute_hmac(record_bytes),
        }
        return cls._canonical_record(envelope)

    @classmethod
    def _decode_authenticated_record(
        cls,
        raw: bytes,
        *,
        schema: str,
    ) -> dict[str, Any]:
        envelope = json.loads(raw.decode("utf-8"))
        if not isinstance(envelope, dict) or set(envelope) != {
            "record",
            "hmac_sha384",
        }:
            raise ValueError("invalid authenticated state envelope")
        record = envelope.get("record")
        tag = envelope.get("hmac_sha384")
        if not isinstance(record, dict) or not isinstance(tag, str):
            raise ValueError("invalid authenticated state envelope fields")
        if record.get("schema") != schema:
            raise ValueError("authenticated state schema mismatch")
        if not _verify_hmac(cls._canonical_record(record), tag):
            raise ValueError("authenticated state envelope HMAC mismatch")
        return record

    @classmethod
    def _load_pointer_locked(
        cls,
        file_path: Path,
    ) -> tuple[dict[str, Any], bytes]:
        pointer_path = cls._pointer_path(file_path)
        raw = pointer_path.read_bytes()
        pointer = cls._decode_authenticated_record(raw, schema=_POINTER_SCHEMA)
        expected_keys = {
            "schema",
            "target_id",
            "generation",
            "generation_sha384",
            "previous_generation",
        }
        if set(pointer) != expected_keys:
            raise ValueError("invalid authenticated pointer fields")
        if pointer.get("target_id") != cls._target_identity(file_path):
            raise ValueError("authenticated pointer target mismatch")
        generation = pointer.get("generation")
        previous = pointer.get("previous_generation")
        digest = pointer.get("generation_sha384")
        if not cls._valid_generation_token(generation):
            raise ValueError("invalid authenticated pointer generation")
        if previous is not None and not cls._valid_generation_token(previous):
            raise ValueError("invalid authenticated pointer predecessor")
        if (
            not isinstance(digest, str)
            or len(digest) != hashlib.sha384().digest_size * 2
        ):
            raise ValueError("invalid authenticated pointer digest")
        return pointer, raw

    @classmethod
    def _load_committed_payload_locked(
        cls,
        file_path: Path,
    ) -> tuple[bytes, dict[str, Any]]:
        pointer, _raw_pointer = cls._load_pointer_locked(file_path)
        token = pointer["generation"]
        generation_path = cls._generation_path(file_path, token)
        generation_raw = generation_path.read_bytes()
        actual_digest = hashlib.sha384(generation_raw).hexdigest()
        if not hmac.compare_digest(actual_digest, pointer["generation_sha384"]):
            raise ValueError("committed generation digest mismatch")
        generation = cls._decode_authenticated_record(
            generation_raw,
            schema=_GENERATION_SCHEMA,
        )
        expected_keys = {
            "schema",
            "target_id",
            "generation",
            "payload_b64",
            "payload_sha384",
        }
        if set(generation) != expected_keys:
            raise ValueError("invalid authenticated generation fields")
        if generation.get("target_id") != cls._target_identity(file_path):
            raise ValueError("authenticated generation target mismatch")
        if generation.get("generation") != token:
            raise ValueError("authenticated generation identity mismatch")
        encoded = generation.get("payload_b64")
        payload_digest = generation.get("payload_sha384")
        if not isinstance(encoded, str) or not isinstance(payload_digest, str):
            raise ValueError("invalid authenticated generation payload")
        payload = base64.b64decode(encoded.encode("ascii"), validate=True)
        actual_payload_digest = hashlib.sha384(payload).hexdigest()
        if not hmac.compare_digest(actual_payload_digest, payload_digest):
            raise ValueError("authenticated generation payload digest mismatch")
        return payload, pointer

    @classmethod
    def _compatibility_projection_matches(
        cls,
        file_path: Path,
        hmac_path: Path,
        payload: bytes,
    ) -> bool:
        try:
            if file_path.read_bytes() != payload:
                return False
            tag = hmac_path.read_text(encoding="ascii").strip()
            return _verify_hmac(payload, tag)
        except (OSError, UnicodeError):
            return False

    @classmethod
    def _materialize_compatibility_pair_locked(
        cls,
        file_path: Path,
        hmac_path: Path,
        payload: bytes,
    ) -> None:
        expected_hmac = _compute_hmac(payload).encode("ascii")
        prefix = f".{file_path.name}.auth-stage-"
        json_stage = cls._write_random_stage(file_path.parent, prefix, payload)
        hmac_stage: Path | None = None
        try:
            hmac_stage = cls._write_random_stage(
                file_path.parent,
                prefix,
                expected_hmac,
            )
            cls._durable_replace(hmac_stage, hmac_path)
            hmac_stage = None
            _persistence_fault_point("hmac-mirrored", file_path)
            cls._durable_replace(json_stage, file_path)
            json_stage = None
            _persistence_fault_point("json-mirrored", file_path)
            if not cls._compatibility_projection_matches(
                file_path,
                hmac_path,
                payload,
            ):
                raise OSError("compatibility projection verification failed")
        finally:
            if json_stage is not None:
                json_stage.unlink(missing_ok=True)
            if hmac_stage is not None:
                hmac_stage.unlink(missing_ok=True)

    @classmethod
    def _cleanup_transaction_files_locked(
        cls,
        file_path: Path,
        pointer: dict[str, Any],
    ) -> None:
        keep = {pointer["generation"]}
        previous = pointer.get("previous_generation")
        if previous is not None:
            keep.add(previous)
        cls._prune_transaction_files_locked(file_path, keep=keep)

    @classmethod
    def _prune_transaction_files_locked(
        cls,
        file_path: Path,
        *,
        keep: set[str],
    ) -> None:
        if len(keep) > _MAX_GENERATIONS:
            raise ValueError("too many authenticated generations retained")
        generation_prefix = f".{file_path.name}.auth-gen-"
        stage_prefix = f".{file_path.name}.auth-stage-"
        for candidate in file_path.parent.iterdir():
            name = candidate.name
            if name.startswith(generation_prefix):
                token = name[len(generation_prefix):]
                if token not in keep:
                    candidate.unlink(missing_ok=True)
            elif name.startswith(stage_prefix):
                candidate.unlink(missing_ok=True)
        cls._fsync_directory(file_path.parent)

    @classmethod
    def _commit_authenticated_payload_locked(
        cls,
        file_path: Path,
        payload: bytes,
        *,
        hmac_path: Path,
    ) -> None:
        pointer_path = cls._pointer_path(file_path)
        previous: str | None = None
        if pointer_path.exists():
            _old_payload, old_pointer = cls._load_committed_payload_locked(file_path)
            previous = old_pointer["generation"]
            cls._cleanup_transaction_files_locked(file_path, old_pointer)
        else:
            # Generations without a commit pointer are interrupted, never
            # authoritative transactions. Prune them before the next attempt.
            cls._prune_transaction_files_locked(file_path, keep=set())

        token = secrets.token_hex(_GENERATION_TOKEN_BYTES)
        payload_digest = hashlib.sha384(payload).hexdigest()
        generation_record = {
            "schema": _GENERATION_SCHEMA,
            "target_id": cls._target_identity(file_path),
            "generation": token,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "payload_sha384": payload_digest,
        }
        generation_raw = cls._encode_authenticated_record(generation_record)
        prefix = f".{file_path.name}.auth-stage-"
        generation_stage = cls._write_random_stage(
            file_path.parent,
            prefix,
            generation_raw,
        )
        generation_path = cls._generation_path(file_path, token)
        try:
            cls._durable_replace(
                generation_stage,
                generation_path,
                replace=False,
            )
            generation_stage = None
            _persistence_fault_point("generation-durable", file_path)

            pointer_record = {
                "schema": _POINTER_SCHEMA,
                "target_id": cls._target_identity(file_path),
                "generation": token,
                "generation_sha384": hashlib.sha384(generation_raw).hexdigest(),
                "previous_generation": previous,
            }
            pointer_raw = cls._encode_authenticated_record(pointer_record)
            pointer_stage = cls._write_random_stage(
                file_path.parent,
                prefix,
                pointer_raw,
            )
            try:
                _persistence_fault_point("pointer-staged", file_path)
                cls._durable_replace(pointer_stage, pointer_path)
                pointer_stage = None
                _persistence_fault_point("pointer-committed", file_path)
            finally:
                if pointer_stage is not None:
                    pointer_stage.unlink(missing_ok=True)
        finally:
            if generation_stage is not None:
                generation_stage.unlink(missing_ok=True)

        # The authenticated pointer is the commit boundary.  Projection
        # failure after this point cannot invalidate the committed state; all
        # readers resolve the pointer first and repair this compatibility view.
        try:
            cls._materialize_compatibility_pair_locked(
                file_path,
                hmac_path,
                payload,
            )
        except Exception as exc:
            log_error(
                f"Authenticated state committed for {file_path.name}, but its "
                f"compatibility projection is pending ({type(exc).__name__})"
            )
        cls._cleanup_transaction_files_locked(file_path, pointer_record)

    @classmethod
    def _replace_authenticated_pair(
        cls,
        file_path: Path,
        payload: bytes,
        *,
        hmac_path: Path | None = None,
        _lock_held: bool = False,
    ) -> None:
        """Durably commit *payload* and refresh the legacy JSON/HMAC view."""
        file_path = Path(file_path)
        hmac_path = hmac_path or file_path.with_suffix(".hmac")
        hmac_path = Path(hmac_path)
        if hmac_path.parent.resolve() != file_path.parent.resolve():
            raise OSError("JSON and HMAC state must share one directory")
        # Resolve the key before creating any transaction artifact.
        _compute_hmac(payload)
        if _lock_held:
            cls._commit_authenticated_payload_locked(
                file_path,
                payload,
                hmac_path=hmac_path,
            )
            return
        with _authenticated_state_lock(file_path):
            cls._commit_authenticated_payload_locked(
                file_path,
                payload,
                hmac_path=hmac_path,
            )

    @classmethod
    def _remove_authenticated_state(
        cls,
        file_path: Path,
        *,
        hmac_path: Path | None = None,
    ) -> None:
        """Remove one logical state target, including journal generations."""
        file_path = Path(file_path)
        hmac_path = Path(hmac_path or file_path.with_suffix(".hmac"))
        with _authenticated_state_lock(file_path):
            cls._pointer_path(file_path).unlink(missing_ok=True)
            file_path.unlink(missing_ok=True)
            hmac_path.unlink(missing_ok=True)
            cls._prune_transaction_files_locked(file_path, keep=set())

    def load_data(self, data_type: str, default: Any = None) -> Any:
        """Load ``<data_type>.json``, falling back to backups on corruption."""
        file_path = self.data_directory / f"{data_type}.json"

        # Try main file first
        data = self._try_load_json(file_path)
        if data is not None:
            with self._lock:
                self._data_cache[data_type] = data
            return data

        # Main file missing or corrupt — try backups (newest first)
        backups = sorted(
            file_path.parent.glob(f"{file_path.stem}.backup.*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for backup in backups:
            # Rotated backups created by supported versions are always paired
            # with an HMAC. An untagged archive is not a trustworthy recovery
            # source and is never promoted into live application state.
            data = self._try_load_json(backup, require_hmac=True)
            if data is not None:
                log_info(f"Recovered {data_type} from backup: {backup.name}")
                with self._lock:
                    self._data_cache[data_type] = data
                return data

        if file_path.exists():
            log_error(f"Failed to load {data_type}: main file and all backups corrupt")
        return default

    # ── Dirty tracking ────────────────────────────────────────────

    def mark_dirty(self, data_type: str) -> None:
        """Mark *data_type* as changed (needs saving)."""
        with self._lock:
            self._dirty_data.add(data_type)

    def auto_save_all(self) -> bool:
        """Save every dirty data type that has a cached value.

        Takes a snapshot of dirty items under the lock, then releases
        before calling ``save_data`` (which re-acquires the lock per
        item).  This avoids holding the lock for the entire I/O batch.
        """
        if not self.config.auto_save:
            return True

        with self._lock:
            to_save = {
                dt: self._data_cache[dt]
                for dt in list(self._dirty_data)
                if dt in self._data_cache
            }

        success = True
        for data_type, data in to_save.items():
            if not self.save_data(data_type, data):
                success = False
        return success

    # ── Internal helpers (caller must hold _lock) ─────────────────

    def _should_save_locked(self, data_type: str) -> bool:
        """Return True if *data_type* warrants a save right now.

        **Must be called while holding ``_lock``.**
        """
        if data_type in self._dirty_data:
            return True
        if time.time() - self._last_save_time > self.config.save_interval:
            return True
        return False

    @classmethod
    def _read_legacy_authenticated_bytes_locked(
        cls,
        path: Path,
        *,
        hmac_path: Path,
        require_hmac: bool,
    ) -> bytes | None:
        """Read the pre-journal JSON/HMAC representation, fail closed."""
        try:
            if not path.exists():
                return None
            raw = path.read_bytes()
            if require_hmac and not hmac_path.is_file():
                log_error(
                    f"HMAC sidecar missing for recovery file {path.name}"
                )
                return None
            if hmac_path.exists():
                try:
                    with open(hmac_path, "r", encoding="ascii") as handle:
                        stored_hmac = handle.read().strip()
                    normalised = raw.replace(b"\r\n", b"\n")
                    if _verify_hmac(raw, stored_hmac):
                        pass
                    elif normalised != raw and _verify_hmac(normalised, stored_hmac):
                        log_info(
                            f"HMAC accepted for {path.name} "
                            "(CRLF-normalised); migrating authenticated state"
                        )
                    elif _verify_hmac_legacy(raw, stored_hmac):
                        log_info(
                            f"HMAC accepted for {path.name} under legacy "
                            "machine-derived key; migrating authenticated state"
                        )
                    elif (
                        normalised != raw
                        and _verify_hmac_legacy(normalised, stored_hmac)
                    ):
                        log_info(
                            f"HMAC accepted for {path.name} under legacy "
                            "key (CRLF-normalised); migrating authenticated state"
                        )
                    else:
                        log_error(
                            f"HMAC verification FAILED for {path.name} — "
                            "possible tampering (no key matched)"
                        )
                        return None
                except Exception as e:
                    log_error(f"HMAC check error for {path.name}: {e}")
                    return None
            return raw
        except OSError:
            return None

    @classmethod
    def _read_authenticated_bytes_locked(
        cls,
        path: Path,
        *,
        hmac_path: Path,
        require_hmac: bool,
    ) -> bytes | None:
        pointer_path = cls._pointer_path(path)
        if pointer_path.exists():
            try:
                payload, pointer = cls._load_committed_payload_locked(path)
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                log_error(
                    f"Authenticated commit verification FAILED for {path.name} "
                    f"({type(exc).__name__})"
                )
                return None

            # The projection is explicitly non-authoritative.  Repair a stale
            # or half-written pair after a crash and still return the committed
            # generation if projection repair is temporarily unavailable.
            if not cls._compatibility_projection_matches(
                path,
                hmac_path,
                payload,
            ):
                try:
                    cls._materialize_compatibility_pair_locked(
                        path,
                        hmac_path,
                        payload,
                    )
                except Exception as exc:
                    log_error(
                        f"Could not repair compatibility projection for "
                        f"{path.name} ({type(exc).__name__})"
                    )
            try:
                cls._cleanup_transaction_files_locked(path, pointer)
            except OSError as exc:
                log_error(
                    f"Could not prune old authenticated generations for "
                    f"{path.name} ({type(exc).__name__})"
                )
            return payload

        legacy = cls._read_legacy_authenticated_bytes_locked(
            path,
            hmac_path=hmac_path,
            require_hmac=require_hmac,
        )
        if legacy is None:
            return None
        # A verified legacy pair is immediately placed behind a durable commit
        # pointer.  Failure leaves the original pair untouched and readable;
        # no partially-created generation is treated as committed.
        try:
            cls._commit_authenticated_payload_locked(
                path,
                legacy,
                hmac_path=hmac_path,
            )
        except Exception as exc:
            log_error(
                f"Could not migrate legacy authenticated state for {path.name} "
                f"({type(exc).__name__})"
            )
        return legacy

    @classmethod
    def _read_authenticated_bytes(
        cls,
        path: Path,
        *,
        hmac_path: Path | None = None,
        require_hmac: bool = True,
        _lock_held: bool = False,
    ) -> bytes | None:
        """Return the authoritative authenticated bytes for *path*."""
        path = Path(path)
        hmac_path = Path(hmac_path or path.with_suffix(".hmac"))
        if hmac_path.parent.resolve() != path.parent.resolve():
            raise OSError("JSON and HMAC state must share one directory")
        if _lock_held:
            return cls._read_authenticated_bytes_locked(
                path,
                hmac_path=hmac_path,
                require_hmac=require_hmac,
            )
        with _authenticated_state_lock(path):
            return cls._read_authenticated_bytes_locked(
                path,
                hmac_path=hmac_path,
                require_hmac=require_hmac,
            )

    @classmethod
    def _try_load_json(cls, path: Path, *, require_hmac: bool = True) -> Any:
        """Load journaled JSON, or safely migrate a verified legacy pair."""
        try:
            raw = cls._read_authenticated_bytes(
                path,
                require_hmac=require_hmac,
            )
            if raw is None:
                return None
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError):
            return None

    def _create_backup(self, file_path: Path) -> None:
        """Create an authenticated rotated copy, then prune old pairs."""
        try:
            payload = self._read_authenticated_bytes(
                file_path,
                require_hmac=True,
            )
            if payload is None:
                log_error(
                    f"Refusing to rotate unauthenticated {file_path.name}"
                )
                return
            timestamp = int(time.time())
            backup_path = file_path.with_suffix(f".backup.{timestamp}.json")

            backup_files = sorted(
                file_path.parent.glob(f"{file_path.stem}.backup.*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if file_path.stem == "settings":
                from app.core.audit_webhook_config import sanitize_settings_payload

                payload, _recognized = sanitize_settings_payload(
                    f"app/data/{file_path.name}",
                    payload,
                )
                if payload is None:
                    log_error(
                        "Refusing to rotate an invalid settings payload"
                    )
                    return

            self._replace_authenticated_pair(backup_path, payload)

            backup_files = sorted(
                file_path.parent.glob(f"{file_path.stem}.backup.*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in backup_files[self.config.max_backups:]:
                self._remove_authenticated_state(old)
        except Exception as e:
            log_error(f"Failed to create backup: {e}")

    # ── Diagnostics ───────────────────────────────────────────────

    def get_data_info(self) -> Dict[str, Any]:
        """Return a diagnostic snapshot of persistence state."""
        try:
            with self._lock:
                dirty = list(self._dirty_data)
                cached = list(self._data_cache.keys())

            total_files = 0
            total_size = 0
            for file_path in self.data_directory.glob("*.json"):
                if file_path.is_file():
                    total_files += 1
                    total_size += file_path.stat().st_size

            return {
                "data_directory": str(self.data_directory),
                "total_files": total_files,
                "total_size": total_size,
                "dirty_data": dirty,
                "cached_data": cached,
            }
        except Exception as e:
            log_error(f"Failed to get data info: {e}")
            return {}


# ── Global persistence manager ────────────────────────────────────────

persistence_manager = DataPersistenceManager()


# ── AutoSave mixin ────────────────────────────────────────────────────

class AutoSaveMixin:
    """Mixin that delegates save/load to the global persistence manager."""

    def __init__(self, data_type: str) -> None:
        self._data_type = data_type
        self._auto_save_enabled = True

    def save_changes(self, data: Any, force: bool = False) -> bool:
        """Persist *data* via the global manager."""
        if self._auto_save_enabled:
            persistence_manager.mark_dirty(self._data_type)
            return persistence_manager.save_data(self._data_type, data, force)
        return True

    def load_saved_data(self, default: Any = None) -> Any:
        """Load previously persisted data, or return *default*."""
        return persistence_manager.load_data(self._data_type, default)

    def enable_auto_save(self, enabled: bool = True) -> None:
        """Toggle auto-save for this data type."""
        self._auto_save_enabled = enabled
        log_info(f"Auto-save {'enabled' if enabled else 'disabled'} for {self._data_type}")


# ── Generic collection manager ────────────────────────────────────────

class CollectionManager(AutoSaveMixin):
    """Generic CRUD manager for list-based persistent collections.

    Eliminates the repeated add/update/remove pattern across
    DeviceManager, AccountManager, etc.
    """

    def __init__(self, data_type: str, key_field: str = "ip",
                 default: Optional[List[Dict]] = None) -> None:
        super().__init__(data_type)
        self._key_field = key_field
        self.items: List[Dict] = self.load_saved_data(
            default if default is not None else []
        )

    def add(self, item: Dict) -> None:
        """Append *item* and persist."""
        self.items.append(item)
        self.save_changes(self.items)

    def update(self, key_value: str, updates: Dict) -> None:
        """Update the first item whose key field matches *key_value*."""
        for item in self.items:
            if item.get(self._key_field) == key_value:
                item.update(updates)
                self.save_changes(self.items)
                return

    def remove(self, key_value: str) -> None:
        """Remove all items whose key field matches *key_value*."""
        self.items = [i for i in self.items if i.get(self._key_field) != key_value]
        self.save_changes(self.items)


# ── Specific managers (thin backwards-compat wrappers) ────────────────

class SettingsManager(AutoSaveMixin):
    """Manager for application settings (dict-based, not a collection)."""

    def __init__(self) -> None:
        super().__init__("settings")
        self.settings: Dict[str, Any] = self.load_saved_data({})

    def update_setting(self, key: str, value: Any) -> None:
        if key == "audit_webhook" and isinstance(value, dict):
            from app.core.audit_webhook_config import (
                configure_audit_webhook_enabled,
                provision_audit_webhook,
            )

            url = next(
                (
                    value.get(field)
                    for field in ("url", "webhook_url", "endpoint_url")
                    if value.get(field)
                ),
                None,
            )
            if url is not None:
                provision_audit_webhook(
                    url,
                    kind=value.get("kind", "discord"),
                    rate_limit_per_min=value.get("rate_limit_per_min", 30),
                    enabled=value.get("enabled", True),
                    manager=self,
                )
                return
            if set(value).issubset({"enabled"}):
                configure_audit_webhook_enabled(
                    value.get("enabled", False),
                    manager=self,
                )
                return
        self.settings[key] = value
        self.save_changes(self.settings)

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)


class DeviceManager(CollectionManager):
    """Manager for device data."""

    def __init__(self) -> None:
        super().__init__("devices", key_field="ip")

    @property
    def devices(self) -> List[Dict]:
        return self.items

    def add_device(self, d: Dict) -> None:
        self.add(d)

    def update_device(self, ip: str, u: Dict) -> None:
        self.update(ip, u)

    def remove_device(self, ip: str) -> None:
        self.remove(ip)


class AccountManager(CollectionManager):
    """Manager for DayZ account data."""

    def __init__(self) -> None:
        super().__init__("dayz_accounts", key_field="account")

    @property
    def accounts(self) -> List[Dict]:
        return self.items

    def add_account(self, a: Dict) -> None:
        self.add(a)

    def update_account(self, name: str, u: Dict) -> None:
        self.update(name, u)

    def remove_account(self, name: str) -> None:
        self.remove(name)


class MarkerManager(AutoSaveMixin):
    """Manager for map markers and loot locations."""

    def __init__(self) -> None:
        super().__init__("dayz_markers")
        self.markers: Dict[str, Any] = self.load_saved_data({
            "markers": [], "loot_locations": [], "gps_coordinates": {},
        })

    def add_marker(self, marker: Dict) -> None:
        self.markers["markers"].append(marker)
        self.save_changes(self.markers)

    def add_loot_location(self, loot: Dict) -> None:
        self.markers["loot_locations"].append(loot)
        self.save_changes(self.markers)

    def update_gps_coordinates(self, coordinates: Dict) -> None:
        self.markers["gps_coordinates"].update(coordinates)
        self.save_changes(self.markers)


class NicknameManager(AutoSaveMixin):
    """Device nicknames — MAC-preferred key → friendly name."""

    def __init__(self) -> None:
        super().__init__("device_nicknames")
        self.nicknames: Dict[str, str] = self.load_saved_data({})

    def set_nickname(self, key: str, nickname: str) -> None:
        if nickname:
            self.nicknames[key] = nickname
        else:
            self.nicknames.pop(key, None)
        self.save_changes(self.nicknames, force=True)

    def get_nickname(self, mac: str = "", ip: str = "") -> str:
        if mac and mac in self.nicknames:
            return self.nicknames[mac]
        if ip and ip in self.nicknames:
            return self.nicknames[ip]
        return ""

    def remove_nickname(self, key: str) -> None:
        if key in self.nicknames:
            del self.nicknames[key]
            self.save_changes(self.nicknames, force=True)

    def get_all(self) -> Dict[str, str]:
        return dict(self.nicknames)


class DeviceCacheManager(AutoSaveMixin):
    """Persists discovered devices across restarts."""

    def __init__(self) -> None:
        super().__init__("device_cache")
        self._cache: List[Dict] = self.load_saved_data([])

    def update_cache(self, devices: List[Dict]) -> None:
        self._cache = devices
        self.save_changes(self._cache, force=True)

    def get_cached_devices(self) -> List[Dict]:
        return list(self._cache)

    def clear(self) -> None:
        self._cache = []
        self.save_changes(self._cache, force=True)


# ── Global manager instances ──────────────────────────────────────────

settings_manager = SettingsManager()
device_manager = DeviceManager()
account_manager = AccountManager()
marker_manager = MarkerManager()
nickname_manager = NicknameManager()
device_cache_manager = DeviceCacheManager()


# ── Module-level convenience functions ────────────────────────────────

def save_all_data() -> bool:
    """Flush all dirty data to disk."""
    return persistence_manager.auto_save_all()


def get_persistence_info() -> Dict[str, Any]:
    """Return diagnostic info about persistence state."""
    return persistence_manager.get_data_info()


def persistence_key_degraded() -> bool:
    """Return True when the durable integrity key is unavailable."""
    try:
        _get_hmac_key()
    except Exception:
        return True
    return _KEY_DEGRADED
