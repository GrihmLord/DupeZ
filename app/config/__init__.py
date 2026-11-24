"""Application configuration persistence (v5.7.6: HMAC-protected).

Reads and writes ``settings.json`` from the canonical runtime config folder.

v5.7.6 security hardening
-------------------------
Pre-v5.7.6, ``settings.json`` had no at-rest integrity check. A local
attacker (or a buggy backup-restore tool) could edit the file directly
and DupeZ would happily load whatever was there. The signed-update
chain and DPAPI'd secret store protected updates and secrets, but not
the operator's tuned settings — so an attacker could, for example,
disable the kill-switch entirely by setting ``"kill_switch": false``.

v5.7.6 closes this with the same HMAC-sidecar pattern PatchMonitor and
:mod:`app.core.data_persistence` already use:

* ``settings.json``          — the JSON payload, binary-mode write
* ``settings.json.hmac``     — 96-hex HMAC-SHA384 over the JSON bytes

The HMAC key is the per-install ``persistence.hmac`` secret managed by
:mod:`app.core.secret_store` (DPAPI-sealed on Windows; 0o600 file on
POSIX). A file-write attacker cannot produce a matching tag without
also compromising the user's DPAPI master key.

Policy on load
~~~~~~~~~~~~~~
An authenticated immutable generation and atomic commit pointer are
authoritative. ``settings.json`` and its HMAC are a compatibility projection
that is repaired from the committed generation after an interrupted write.
Pre-journal signed pairs migrate on first load. Unsigned settings retain the
one-shot DPAPI-backed migration marker: after initialization, an unsigned
legacy file is rejected rather than accepted as a fresh migration.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

__all__ = ["load_config", "save_config", "CONFIG_PATH", "HMAC_PATH"]

from app.core.app_paths import config_dir, ensure_runtime_migration

ensure_runtime_migration()
CONFIG_PATH: str = str(config_dir() / "settings.json")
HMAC_PATH: str = CONFIG_PATH + ".hmac"
_INTEGRITY_MARKER_KIND = "persistence.config.initialized"
_INTEGRITY_MARKER_VALUE = b"dupez.config.integrity.v1"


def _integrity_initialized() -> bool:
    """Return whether unsigned-config migration has already been consumed."""
    from app.core.secret_store import get_secret

    marker = get_secret(_INTEGRITY_MARKER_KIND)
    return marker == _INTEGRITY_MARKER_VALUE


def _mark_integrity_initialized() -> None:
    """Durably close the unsigned-config migration path before acceptance."""
    from app.core.secret_store import put_secret

    put_secret(_INTEGRITY_MARKER_KIND, _INTEGRITY_MARKER_VALUE)


def _compute_tag(payload: bytes) -> str:
    """Return persistence-keyed HMAC-SHA384 hex digest of *payload*."""
    import hashlib
    import hmac as _hmac
    # Lazy: avoid pulling data_persistence into early import paths
    # that may run before the app data dir is resolved.
    from app.core.data_persistence import _get_hmac_key
    return _hmac.new(_get_hmac_key(), payload, hashlib.sha384).hexdigest()


def _verify_tag(payload: bytes, expected_hex: str) -> bool:
    """Constant-time verification of an HMAC tag against *payload*."""
    import hmac as _hmac
    if not isinstance(expected_hex, str) or len(expected_hex) != 96:
        return False
    return _hmac.compare_digest(_compute_tag(payload), expected_hex)


def _verify_legacy_tag(payload: bytes, expected_hex: str) -> bool:
    """Verify a historical tag only while the real secret store works."""
    if not isinstance(expected_hex, str) or len(expected_hex) != 96:
        return False
    from app.core.data_persistence import _verify_hmac_legacy

    return _verify_hmac_legacy(payload, expected_hex)


def _quarantine_tampered_file() -> None:
    """Move ``settings.json`` aside with a tampered-<ts> suffix.

    Forensic preservation — the operator (or our support team) can
    look at exactly what was on disk after the integrity failure.
    Errors are swallowed: we never want quarantine I/O to crash boot.
    """
    try:
        ts = int(time.time())
        target = CONFIG_PATH + f".tampered.{ts}"
        if os.path.exists(CONFIG_PATH):
            os.replace(CONFIG_PATH, target)
    except OSError:
        pass


def _audit_tamper(reason: str) -> None:
    """Best-effort audit event for settings tampering."""
    try:
        from app.logs.audit import audit_event
        audit_event("settings_tampered", {"reason": reason})
    except Exception:
        pass


def load_config() -> Dict[str, Any]:
    """Load and return the JSON configuration, or ``{}`` on any failure.

    Integrity policy:

    * authenticated commit present → load it and repair the compatibility pair
    * legacy tag present + verifies → migrate to an authenticated commit
    * tag missing + uninitialized → mark, sign transactionally, return
    * tag missing + initialized   → quarantine and return ``{}``
    * authenticated state invalid → quarantine, audit, return ``{}``
    * file missing           → return ``{}`` (fresh install)
    """
    try:
        from app.core.data_persistence import DataPersistenceManager

        config_path = Path(CONFIG_PATH)
        hmac_path = Path(HMAC_PATH)
        commit_exists = DataPersistenceManager._pointer_path(config_path).is_file()
        if commit_exists or hmac_path.is_file():
            raw = DataPersistenceManager._read_authenticated_bytes(
                config_path,
                hmac_path=hmac_path,
                require_hmac=True,
            )
            if raw is None:
                _audit_tamper("authenticated settings state is invalid")
                _quarantine_tampered_file()
                try:
                    os.unlink(HMAC_PATH)
                except OSError:
                    pass
                return {}
            try:
                doc = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            if not isinstance(doc, dict):
                return {}
            try:
                if not _integrity_initialized():
                    _mark_integrity_initialized()
            except Exception:
                _audit_tamper("settings integrity marker unavailable")
                return {}
            return doc

        if not config_path.is_file():
            return {}
        try:
            raw = config_path.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(doc, dict):
            return {}

        # No sidecar: permit exactly one DPAPI-marked migration. A deleted
        # legacy sidecar after initialization is an integrity failure, not
        # another chance to accept unsigned settings.
        try:
            if _integrity_initialized():
                _audit_tamper("HMAC sidecar missing after initialization")
                _quarantine_tampered_file()
                return {}
            save_config(doc)
        except Exception:
            _audit_tamper("unsigned settings migration failed")
            return {}
        return doc
    except Exception:
        return {}


def save_config(config: Dict[str, Any]) -> None:
    """Transactionally persist *config* and its HMAC sidecar."""
    if not isinstance(config, dict):
        raise TypeError(f"config must be dict, got {type(config).__name__}")

    from app.core.data_persistence import DataPersistenceManager

    payload = json.dumps(config, indent=4, sort_keys=True).encode("utf-8")
    # Close the migration path before touching live config. If the pair write
    # fails, future loads reject the old unsigned file instead of accepting it.
    _mark_integrity_initialized()
    DataPersistenceManager._replace_authenticated_pair(
        Path(CONFIG_PATH),
        payload,
        hmac_path=Path(HMAC_PATH),
    )
