"""Application configuration persistence (v5.7.6: HMAC-protected).

Reads and writes ``settings.json`` located alongside this package.

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
1. If both file and sidecar exist AND tag verifies → load.
2. If file exists but sidecar is missing → ONE-SHOT MIGRATION: we read
   the file, accept it, and re-write with a fresh HMAC. This is how
   an upgrade from v5.7.5 → v5.7.6 picks up integrity on the existing
   settings without bricking the operator's installed config.
3. If both exist but the tag does NOT verify → REFUSE. The function
   returns the safe default ({}) so the rest of the app boots, logs
   the rejection, and surfaces an audit event. The on-disk file is
   preserved as ``settings.json.tampered.<ts>`` for forensics.

Writes are always atomic (tmp → fsync → os.replace) and binary-mode so
Windows CRLF translation cannot corrupt the bytes the HMAC was
computed over.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

__all__ = ["load_config", "save_config", "CONFIG_PATH", "HMAC_PATH"]

CONFIG_PATH: str = os.path.join(os.path.dirname(__file__), "settings.json")
HMAC_PATH: str = CONFIG_PATH + ".hmac"


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

    * tag present + verifies → return parsed config
    * tag missing            → ONE-SHOT migration: read, sign, return
    * tag present + mismatch → quarantine the file, audit, return ``{}``
    * file missing           → return ``{}`` (fresh install)
    """
    try:
        if not os.path.isfile(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH, "rb") as f:
            raw = f.read()
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(doc, dict):
            return {}

        if os.path.isfile(HMAC_PATH):
            try:
                with open(HMAC_PATH, "r", encoding="ascii") as hf:
                    expected = hf.read().strip()
            except OSError:
                expected = ""
            if _verify_tag(raw, expected):
                return doc
            # Tag present but does not match — refuse + quarantine.
            _audit_tamper("HMAC mismatch on settings.json")
            _quarantine_tampered_file()
            try:
                os.unlink(HMAC_PATH)
            except OSError:
                pass
            return {}

        # No sidecar: one-shot v5.7.5 → v5.7.6 migration. The existing
        # file is accepted as authoritative on first read, then signed
        # so subsequent reads are protected.
        try:
            save_config(doc)
        except OSError:
            pass
        return doc
    except OSError:
        return {}


def save_config(config: Dict[str, Any]) -> None:
    """Atomically persist *config* to ``settings.json`` with HMAC sidecar.

    Both files land via tmp + fsync + os.replace. Binary-mode writes so
    Windows CRLF translation can never desync the bytes from the tag.
    """
    if not isinstance(config, dict):
        raise TypeError(f"config must be dict, got {type(config).__name__}")

    payload = json.dumps(config, indent=4, sort_keys=True).encode("utf-8")
    tag = _compute_tag(payload).encode("ascii")

    tmp_json = CONFIG_PATH + ".tmp"
    tmp_hmac = HMAC_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(tmp_json, "wb") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        with open(tmp_hmac, "wb") as f:
            f.write(tag)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_json, CONFIG_PATH)
        os.replace(tmp_hmac, HMAC_PATH)
    except Exception:
        for p in (tmp_json, tmp_hmac):
            try:
                os.unlink(p)
            except OSError:
                pass
        raise
