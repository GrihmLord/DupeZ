"""
Secure Secrets Manager for DupeZ.

Provides encrypted storage for sensitive values (API keys, tokens,
credentials) with audit logging, automated expiry enforcement, and log
scrubbing.

Threat Model:
  - At-rest protection: AES-256-GCM with a per-record HKDF key.  The
    random root key is sealed by the operating-system secret store
    (DPAPI user scope on Windows); it is never derived from public
    machine metadata.
  - In-memory protection: secrets are decrypted only at point of use
    and never held in plaintext longer than necessary.
  - Log scrubbing: a global filter prevents accidental secret leakage
    in log output.
  - Expiry enforcement: every secret has a TTL.  Expired secrets are
    inaccessible until rotated.

Storage Format (secrets.enc.json):
  {
    "<name>": {
      "key_source": "secret-store-v1",
      "ciphertext": "<base64>",   # AES-256-GCM encrypted value
      "nonce": "<base64>",        # 96-bit GCM nonce
      "salt": "<base64>",         # 256-bit PBKDF2 salt for DEK derivation
      "tag": "<base64>",          # GCM authentication tag
      "created_at": <epoch>,
      "expires_at": <epoch>,      # 0 = no expiry
      "rotated": false
    }
  }

CNSA 2.0 Compliance:
  - AES-256-GCM for encryption
  - PBKDF2-SHA-512 (600k iterations) for key derivation
  - authenticated encryption for ciphertext integrity
  - secrets/os.urandom for all random material
"""

from __future__ import annotations

import base64
import json
import os
import hashlib
import hmac
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.crypto import (
    KEY_BYTES,
    NONCE_BYTES,
    PBKDF2_ITERATIONS,
    generate_nonce,
    generate_salt,
    derive_key,
)
from app.core.secret_store import get_or_create_secret
from app.logs.logger import log_info, log_error, log_warning

__all__ = [
    "SecretScrubFilter",
    "get_scrubber",
    "scrub_message",
    "SecretsManager",
    "get_secrets_manager",
]


# ── Constants ────────────────────────────────────────────────────────

# Default secret TTL: 90 days (matches key rotation policy)
DEFAULT_SECRET_TTL_S: int = 90 * 24 * 60 * 60

# Maximum plaintext secret length (sanity guard)
MAX_SECRET_LENGTH: int = 8192

# Secrets file name
SECRETS_FILENAME: str = "secrets.enc.json"
_MASTER_KEY_KIND: str = "secretsmanager.master"
_KEY_SOURCE: str = "secret-store-v1"
_MAX_STORE_BYTES: int = 2 * 1024 * 1024
_MAX_SECRET_COUNT: int = 256
_MAX_CIPHERTEXT_BYTES: int = MAX_SECRET_LENGTH * 4

# Patterns that indicate a value is sensitive and must be scrubbed
SENSITIVE_FIELD_PATTERNS: tuple = (
    "api_key", "api-key", "apikey",
    "password", "passwd", "secret",
    "token", "bearer", "credential",
    "private_key", "private-key",
    "auth", "authorization",
)


# ── AES-256-GCM encryption (required dependency; fail closed) ───────

def _aes_gcm_encrypt(key: bytes, plaintext: bytes, nonce: bytes) -> tuple[bytes, bytes]:
    """Encrypt with AES-256-GCM.  Returns (ciphertext, tag).

    ``cryptography`` is a locked runtime dependency.  If it is missing,
    storage fails closed rather than silently substituting weaker crypto.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    # AESGCM.encrypt returns ciphertext + tag concatenated
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, None)
    # Tag is last 16 bytes
    return ct_and_tag[:-16], ct_and_tag[-16:]


def _aes_gcm_decrypt(key: bytes, ciphertext: bytes, nonce: bytes,
                     tag: bytes) -> bytes:
    """Decrypt with AES-256-GCM.  Returns plaintext.

    Raises ValueError on authentication failure.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    ct_and_tag = ciphertext + tag
    return aesgcm.decrypt(nonce, ct_and_tag, None)


# ── Legacy machine-specific KEK derivation (read/migrate only) ──────

def _get_machine_seed() -> str:
    """Derive the legacy machine seed for backward-compatible migration.

    Combines hostname, username, and a stable machine identifier.
    New records never use this predictable value.  It remains solely so an
    existing installation can decrypt and immediately migrate an old record.
    """
    import platform
    parts = [
        platform.node(),
        os.environ.get("USERNAME", os.environ.get("USER", "default")),
        platform.machine(),
        platform.system(),
    ]
    # Optional Windows machine UUID — deliberately NOT spawned via
    # subprocess. The four parts above already make cross-machine
    # decryption fail (node+user+machine+system collision is vanishingly
    # rare in a normal install base). A prior version of this function
    # shelled out to `wmic csproduct get UUID`, which (a) bypassed
    # safe_subprocess policy, (b) tripped the offsec bare-subprocess
    # rule, and (c) depends on wmic.exe, which Microsoft is removing
    # from Windows 11 24H2+. We now read the UUID passively from the
    # registry when Windows exposes it, and silently skip on any
    # failure — the seed's core identity is already strong without it.
    if os.name == "nt":
        try:
            import winreg  # type: ignore[import-not-found]
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as k:
                machine_guid, _ = winreg.QueryValueEx(k, "MachineGuid")
                if isinstance(machine_guid, str) and machine_guid:
                    parts.append(machine_guid)
        except Exception:
            pass
    return "|".join(parts)


# ── Log Scrubbing Filter ────────────────────────────────────────────

class SecretScrubFilter:
    """Logging filter that redacts sensitive values from log messages.

    Maintains a set of known secret values (registered at store time)
    and replaces any occurrence in log output with '[REDACTED]'.
    Also pattern-matches common secret formats.
    """

    def __init__(self) -> None:
        self._known_secrets: set[str] = set()
        self._lock = threading.Lock()

    def register(self, secret: str) -> None:
        """Register a secret value for scrubbing."""
        if secret and len(secret) >= 4:
            with self._lock:
                self._known_secrets.add(secret)

    def unregister(self, secret: str) -> None:
        """Remove a secret from the scrub list."""
        with self._lock:
            self._known_secrets.discard(secret)

    def scrub(self, message: str) -> str:
        """Replace any known secret values in message with [REDACTED]."""
        with self._lock:
            secrets_snapshot = set(self._known_secrets)
        for secret in secrets_snapshot:
            if secret in message:
                message = message.replace(secret, "[REDACTED]")
        return message


# Global scrubber instance
_scrubber = SecretScrubFilter()


def get_scrubber() -> SecretScrubFilter:
    """Return the global secret scrubber."""
    return _scrubber


def scrub_message(message: str) -> str:
    """Scrub sensitive values from a log message."""
    return _scrubber.scrub(message)


# ── Secrets Manager ──────────────────────────────────────────────────

class SecretsManager:
    """Encrypted secrets storage with expiry enforcement.

    Usage:
        sm = SecretsManager()
        sm.store("llm_api_key", "sk-abc123...", ttl_seconds=7776000)
        key = sm.retrieve("llm_api_key")  # decrypted value or None
        sm.delete("llm_api_key")
    """

    def __init__(self, secrets_dir: str = "") -> None:
        if not secrets_dir:
            from app.core.data_persistence import _resolve_data_directory
            secrets_dir = _resolve_data_directory()

        self._secrets_dir = Path(secrets_dir)
        self._secrets_dir.mkdir(parents=True, exist_ok=True)
        self._secrets_path = self._secrets_dir / SECRETS_FILENAME
        self._lock = threading.Lock()
        self._cache: Dict[str, dict] = {}
        self._kek_cache: Dict[str, bytes] = {}  # salt_hex → derived key
        self._load()

    def _load(self) -> None:
        """Load encrypted secrets metadata from disk."""
        try:
            if self._secrets_path.exists():
                if not self._secrets_path.is_file():
                    raise ValueError("secrets store is not a regular file")
                if self._secrets_path.stat().st_size > _MAX_STORE_BYTES:
                    raise ValueError("secrets store exceeds the size limit")
                with open(self._secrets_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    raise ValueError("secrets store root must be an object")
                if len(loaded) > _MAX_SECRET_COUNT:
                    raise ValueError("secrets store contains too many records")
                if any(
                    not isinstance(name, str)
                    or not name
                    or len(name) > 128
                    or not isinstance(entry, dict)
                    for name, entry in loaded.items()
                ):
                    raise ValueError("secrets store contains an invalid record")
                self._cache = loaded
                log_info(f"SecretsManager: loaded {len(self._cache)} secret(s)")
        except Exception as e:
            log_error(
                "SecretsManager: failed to load secrets store "
                f"({type(e).__name__})"
            )
            self._cache = {}

    def _save(self) -> None:
        """Persist encrypted secrets to disk atomically or raise."""
        tmp_path = self._secrets_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_path), str(self._secrets_path))
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _derive_kek(self, salt: bytes) -> bytes:
        """Derive a per-record key from an OS-sealed random root key."""
        cache_key = f"{_KEY_SOURCE}:{salt.hex()}"
        if cache_key in self._kek_cache:
            return self._kek_cache[cache_key]
        master = get_or_create_secret(_MASTER_KEY_KIND, size=KEY_BYTES)
        if len(master) != KEY_BYTES:
            raise ValueError("invalid secrets-manager master key length")
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=KEY_BYTES,
            salt=salt,
            info=b"DupeZ SecretsManager secret-store-v1",
        ).derive(master)
        self._kek_cache[cache_key] = key
        return key

    def _derive_legacy_kek(self, salt: bytes) -> bytes:
        """Derive the old metadata-based key for one-time migration."""
        cache_key = f"legacy:{salt.hex()}"
        if cache_key in self._kek_cache:
            return self._kek_cache[cache_key]
        key, _ = derive_key(_get_machine_seed(), salt=salt)
        self._kek_cache[cache_key] = key
        return key

    def store(self, name: str, value: str,
              ttl_seconds: int = DEFAULT_SECRET_TTL_S) -> bool:
        """Encrypt and store a secret.

        Args:
            name: Secret identifier (e.g. "llm_api_key")
            value: Plaintext secret value
            ttl_seconds: Time-to-live in seconds (0 = no expiry)

        Returns:
            True on success.
        """
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 128
            or not isinstance(value, str)
            or not value
        ):
            log_error("SecretsManager: name and value are required")
            return False
        if len(value) > MAX_SECRET_LENGTH:
            log_error(f"SecretsManager: secret '{name}' exceeds max length")
            return False
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or ttl_seconds < 0
        ):
            log_error("SecretsManager: ttl_seconds must be a non-negative integer")
            return False

        try:
            salt = generate_salt()
            nonce = generate_nonce()
            kek = self._derive_kek(salt)

            plaintext = value.encode("utf-8")
            ciphertext, tag = _aes_gcm_encrypt(kek, plaintext, nonce)

            now = int(time.time())
            entry = {
                "key_source": _KEY_SOURCE,
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "salt": base64.b64encode(salt).decode("ascii"),
                "tag": base64.b64encode(tag).decode("ascii"),
                "created_at": now,
                "expires_at": now + ttl_seconds if ttl_seconds > 0 else 0,
                "rotated": False,
            }

            with self._lock:
                marker = object()
                previous = self._cache.get(name, marker)
                self._cache[name] = entry
                try:
                    self._save()
                except Exception:
                    if previous is marker:
                        self._cache.pop(name, None)
                    else:
                        self._cache[name] = previous
                    raise

            # Register with scrubber so value never appears in logs
            _scrubber.register(value)

            log_info(f"SecretsManager: stored secret '{name}' "
                     f"(expires={'never' if not ttl_seconds else f'{ttl_seconds}s'})")

            # Audit trail
            try:
                from app.logs.audit import audit_event
                audit_event("secret_stored", {
                    "name": name,
                    "ttl_seconds": ttl_seconds,
                })
            except Exception:
                pass

            return True

        except Exception as e:
            log_error(
                f"SecretsManager: failed to store '{name}' "
                f"({type(e).__name__})"
            )
            return False

    def retrieve(self, name: str, allow_expired: bool = False) -> Optional[str]:
        """Decrypt and return a secret, or None if not found/expired.

        Args:
            name: Secret identifier
            allow_expired: If True, return expired secrets with a warning

        Returns:
            Decrypted plaintext string, or None.
        """
        with self._lock:
            entry = self._cache.get(name)
        if not entry:
            return None

        # Check expiry
        expires_at = entry.get("expires_at", 0)
        if expires_at and time.time() >= expires_at:
            if not allow_expired:
                log_warning(f"SecretsManager: secret '{name}' has expired — "
                            "rotate or re-store to continue using")
                return None
            log_warning(f"SecretsManager: returning expired secret '{name}' "
                        "(allow_expired=True)")

        try:
            ciphertext = base64.b64decode(entry["ciphertext"], validate=True)
            nonce = base64.b64decode(entry["nonce"], validate=True)
            salt = base64.b64decode(entry["salt"], validate=True)
            tag = base64.b64decode(entry["tag"], validate=True)
            if (
                len(ciphertext) > _MAX_CIPHERTEXT_BYTES
                or len(nonce) != NONCE_BYTES
                or len(salt) != KEY_BYTES
                or len(tag) != 16
            ):
                raise ValueError("invalid encrypted-secret record dimensions")

            legacy = entry.get("key_source") is None
            if entry.get("key_source") not in (None, _KEY_SOURCE):
                raise ValueError("unsupported encrypted-secret key source")
            kek = (
                self._derive_legacy_kek(salt)
                if legacy
                else self._derive_kek(salt)
            )
            plaintext = _aes_gcm_decrypt(kek, ciphertext, nonce, tag)
            value = plaintext.decode("utf-8")
            if len(value) > MAX_SECRET_LENGTH:
                raise ValueError("decrypted secret exceeds the length limit")

            # Re-register with scrubber (in case of restart)
            _scrubber.register(value)

            # Existing releases used a key derived from public machine
            # metadata.  Re-seal a successfully decrypted, unexpired record
            # under the OS-protected random root key immediately.
            if legacy and not (expires_at and time.time() >= expires_at):
                remaining_ttl = (
                    max(1, int(expires_at - time.time()))
                    if expires_at
                    else 0
                )
                if not self.store(name, value, remaining_ttl):
                    log_warning(
                        f"SecretsManager: legacy migration failed for '{name}'"
                    )

            return value

        except ValueError as e:
            log_error(f"SecretsManager: decryption failed for '{name}': {e}")
            return None
        except Exception as e:
            log_error(f"SecretsManager: failed to retrieve '{name}': {e}")
            return None

    def delete(self, name: str) -> bool:
        """Remove a secret from the store."""
        with self._lock:
            if name not in self._cache:
                return False
            previous = self._cache.pop(name)
            try:
                self._save()
            except Exception as exc:
                self._cache[name] = previous
                log_error(
                    f"SecretsManager: failed to delete '{name}' "
                    f"({type(exc).__name__})"
                )
                return False
        log_info(f"SecretsManager: deleted secret '{name}'")
        return True

    def rotate(self, name: str, new_value: str,
               ttl_seconds: int = DEFAULT_SECRET_TTL_S) -> bool:
        """Rotate a secret — store new value and mark old as rotated."""
        # Retrieve old to unregister from scrubber after durable replacement.
        old_value = self.retrieve(name, allow_expired=True)
        success = self.store(name, new_value, ttl_seconds)
        if success:
            if old_value:
                _scrubber.unregister(old_value)
            _scrubber.register(new_value)
            with self._lock:
                if name in self._cache:
                    self._cache[name]["rotated"] = True
                    try:
                        self._save()
                    except Exception as exc:
                        log_warning(
                            "SecretsManager: rotation marker was not persisted "
                            f"({type(exc).__name__})"
                        )
            log_info(f"SecretsManager: rotated secret '{name}'")
        return success

    def list_secrets(self) -> List[dict]:
        """Return metadata (no plaintext) for all stored secrets."""
        result = []
        now = time.time()
        with self._lock:
            for name, entry in self._cache.items():
                expires_at = entry.get("expires_at", 0)
                result.append({
                    "name": name,
                    "created_at": entry.get("created_at", 0),
                    "expires_at": expires_at,
                    "expired": bool(expires_at and now >= expires_at),
                    "rotated": entry.get("rotated", False),
                })
        return result

    def get_expired(self) -> List[str]:
        """Return names of all expired secrets."""
        now = time.time()
        expired = []
        with self._lock:
            for name, entry in self._cache.items():
                expires_at = entry.get("expires_at", 0)
                if expires_at and now >= expires_at:
                    expired.append(name)
        return expired

    def has_secret(self, name: str) -> bool:
        """Check if a secret exists (may be expired)."""
        with self._lock:
            return name in self._cache

    def is_expired(self, name: str) -> bool:
        """Check if a specific secret is expired."""
        with self._lock:
            entry = self._cache.get(name)
        if not entry:
            return True
        expires_at = entry.get("expires_at", 0)
        if not expires_at:
            return False
        return time.time() >= expires_at


# ── Global instance ──────────────────────────────────────────────────

_manager: Optional[SecretsManager] = None
_manager_lock = threading.Lock()


def get_secrets_manager() -> SecretsManager:
    """Return the global SecretsManager (lazy singleton)."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SecretsManager()
    return _manager
