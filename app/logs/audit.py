"""
Tamper-Evident Audit Logger for DupeZ.

Security-critical events are logged to a separate, append-only audit
trail with HMAC-SHA384 hash-chained entries.  Each entry's ``hash``
field is ``HMAC(K, entry_json_sans_hash)`` where ``K`` is a 32-byte
per-install secret managed by :mod:`app.core.secret_store` (Windows
DPAPI on nt, 0o600 file under ``$XDG_DATA_HOME`` on POSIX).

The previous design chained entries with *unkeyed* SHA-384, which
meant a local-file-write attacker who could read the audit file could
simply recompute every ``hash`` field after editing an entry and the
chain would still verify.  The HMAC keys the chain to a secret that a
local-file attacker cannot extract without also compromising the
logged-in user's DPAPI master key (Windows) or a 0o600 file in the
user's home (POSIX), which raises the bar from "trivial" to "needs
live session context".

If any entry is modified, deleted, or re-signed with the wrong key,
the chain breaks and tampering is detectable via :meth:`verify_chain`.

Migration from legacy unkeyed SHA-384 chains is automatic: on first
open of an audit file whose terminal entry's ``hash`` still matches
the legacy unkeyed SHA-384 digest, the file is rotated aside with a
``.legacy.<ts>.jsonl`` suffix (forensic material is preserved) and a
fresh HMAC-chained file is started.  A migration audit event is the
first entry in the new file.

Events Logged:
  - Disruption start/stop (target, methods, params)
  - Settings changes
  - Secret store operations
  - Plugin load/unload
  - Authentication events
  - Network scan results

PII Scrubbing:
  - IP addresses are masked (last octet replaced)
  - MAC addresses are masked
  - API keys/tokens are never logged
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.logs.logger import log_error, log_info
from app.utils.helpers import mask_ip, mask_ips_in_text

__all__ = ["AuditLogger", "get_audit_logger", "audit_event"]


# ── Constants ────────────────────────────────────────────────────────

AUDIT_FILENAME: str = "audit.jsonl"
MAX_AUDIT_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB rotation threshold
GENESIS_HASH: str = "0" * 96  # SHA-384 hex length — chain start sentinel
AUDIT_SECRET_KIND: str = "audit.hmac"
AUDIT_KEY_SIZE: int = 32  # 256-bit key — comfortable overkill for HMAC-SHA384

# v5.7.6: Fail-closed tamper sentinel. When the chain is detected as
# broken/tampered/unrecoverable, the audit logger writes a sealed
# marker file alongside the audit log and refuses to write any further
# events until an operator runs ``dupez --reset-audit`` (which
# archives the suspect chain to ``audit-quarantine-<ts>.jsonl`` and
# removes the sentinel). Pre-v5.7.6 the logger silently rotated and
# kept writing, which lost the loud signal that something had touched
# the record-of-truth.
TAMPER_SENTINEL_FILENAME: str = "audit.TAMPERED"


# ── PII Scrubbing ────────────────────────────────────────────────────

def _scrub_pii(data: Any) -> Any:
    """Recursively scrub PII from audit data.

    - IP addresses → masked (192.168.1.xxx)
    - MAC addresses → masked (first 3 octets kept)
    - Known secret fields → [REDACTED]
    """
    if isinstance(data, str):
        # Mask any IPv4 address embedded in the string. Key-based
        # masking below only catches values under known IP key names;
        # this catches an IP under any other key or inside prose.
        return mask_ips_in_text(data)
    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            k_lower = k.lower()
            if any(s in k_lower for s in ("api_key", "password", "secret",
                                           "token", "credential", "bearer")):
                scrubbed[k] = "[REDACTED]"
            elif k_lower in ("ip", "target_ip", "src_ip", "dst_ip"):
                scrubbed[k] = mask_ip(str(v)) if v else ""
            elif k_lower in ("mac", "mac_address"):
                scrubbed[k] = _mask_mac(str(v)) if v else ""
            else:
                scrubbed[k] = _scrub_pii(v)
        return scrubbed
    if isinstance(data, list):
        return [_scrub_pii(item) for item in data]
    return data


def _mask_mac(mac: str) -> str:
    """Mask a MAC address — keep first 3 octets (vendor), mask rest."""
    parts = mac.split(":")
    if len(parts) == 6:
        return ":".join(parts[:3] + ["xx", "xx", "xx"])
    return mac


# ── Audit Logger ─────────────────────────────────────────────────────

class AuditLogger:
    """Append-only, HMAC-SHA384 hash-chained audit logger.

    Each log entry is a JSON line with:
      - seq: monotonic sequence number
      - ts: Unix timestamp
      - event: event type string
      - data: scrubbed event data dict
      - prev_hash: hash of the previous entry (HMAC-SHA384 hex)
      - hash: HMAC-SHA384(K, serialized_entry_sans_hash)

    The key ``K`` is resolved from :mod:`app.core.secret_store` under
    ``kind="audit.hmac"`` — first-run generates a CSPRNG 32-byte key,
    subsequent runs load the same key. On Windows the key is sealed
    with DPAPI (user scope); on POSIX it sits in a 0o600 file under
    ``$XDG_DATA_HOME/DupeZ/secrets/``.

    Degraded mode: if :mod:`secret_store` cannot be reached at
    construction time (catastrophic filesystem failure, DPAPI master
    key lost, etc.), the logger falls back to an **ephemeral**
    per-process key and sets :attr:`degraded` to ``True``. Entries are
    still written so we don't lose the audit trail, but a future
    :meth:`verify_chain` call across processes will report the
    discontinuity. A single ``audit_key_degraded`` event is logged.

    Usage::

        audit = AuditLogger()
        audit.log("disruption_start", {"target_ip": "198.51.100.5", ...})
    """

    def __init__(
        self,
        audit_dir: str = "",
        *,
        secret_kind: str = AUDIT_SECRET_KIND,
    ) -> None:
        if not audit_dir:
            from app.core.data_persistence import _resolve_data_directory
            audit_dir = _resolve_data_directory()

        self._audit_dir = Path(audit_dir)
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path = self._audit_dir / AUDIT_FILENAME
        self._tamper_sentinel = self._audit_dir / TAMPER_SENTINEL_FILENAME
        self._lock = threading.Lock()
        self._seq: int = 0
        self._prev_hash: str = GENESIS_HASH
        self._secret_kind: str = secret_kind
        self._key: bytes = b""
        self.degraded: bool = False
        # v5.7.6: when True, ``log()`` is a no-op (with a stderr warning
        # once per process) until ``reset_after_tamper()`` is called by
        # the operator via ``dupez --reset-audit``.
        self.sealed: bool = False
        self._sealed_warned: bool = False

        self._load_or_generate_key()
        # Resume chain from existing file (may migrate legacy content).
        self._resume_chain()
        # v5.7.6: if a prior process tripped the tamper sentinel and
        # the operator hasn't run --reset-audit yet, stay sealed.
        if self._tamper_sentinel.exists():
            self.sealed = True

    # ── Key plumbing ─────────────────────────────────────────────

    def _load_or_generate_key(self) -> None:
        """Load the HMAC key from the secret store or fall back.

        On any failure: generate an ephemeral per-process key with
        :func:`secrets.token_bytes` so audit writes don't stall, set
        :attr:`degraded` = ``True``, and log the error. This prevents a
        misconfigured secret store from silencing the audit trail.
        """
        try:
            from app.core.secret_store import get_or_create_secret
            key = get_or_create_secret(self._secret_kind, size=AUDIT_KEY_SIZE)
            if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
                raise RuntimeError(
                    f"secret_store returned invalid key (len={len(key) if key else 0})"
                )
            self._key = bytes(key)
        except Exception as e:  # pragma: no cover — exceptional path
            log_error(
                f"AuditLogger: failed to load HMAC key from secret_store "
                f"({e}); falling back to ephemeral in-process key"
            )
            import secrets as _secrets
            self._key = _secrets.token_bytes(AUDIT_KEY_SIZE)
            self.degraded = True

    def _digest(self, payload: bytes) -> str:
        """Return the hex HMAC-SHA384 digest of *payload* under the active key."""
        return hmac.new(self._key, payload, hashlib.sha384).hexdigest()

    @staticmethod
    def _legacy_digest(payload: bytes) -> str:
        """Unkeyed SHA-384 — used ONLY to detect legacy chains for migration."""
        return hashlib.sha384(payload).hexdigest()

    # ── Chain resume / migration ─────────────────────────────────

    def _resume_chain(self) -> None:
        """Read the last entry to resume the hash chain.

        If the terminal entry's hash matches the HMAC digest under the
        current key, we resume normally. If it matches the legacy
        unkeyed SHA-384 digest instead, the file is rotated aside
        (preserved for forensics) and we start a fresh HMAC chain with
        a migration marker entry. If it matches neither, the file is
        rotated aside as ``corrupted`` and a fresh chain is started;
        we prefer a loud re-start to silently appending onto a broken
        chain.
        """
        try:
            if not self._audit_path.exists():
                return

            last_line = ""
            with open(self._audit_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
            if not last_line:
                return

            try:
                entry = json.loads(last_line)
            except json.JSONDecodeError:
                # v5.7.6: corrupt terminal line is an integrity signal,
                # not a benign hiccup. Seal until operator clears it.
                self._rotate_aside("tampered", reason="terminal entry not JSON")
                self._seal(reason="terminal entry not valid JSON")
                return

            stored = entry.get("hash", "")
            if not isinstance(stored, str) or not stored:
                self._rotate_aside("tampered", reason="missing hash on terminal entry")
                self._seal(reason="terminal entry missing 'hash' field")
                return

            tmp = dict(entry)
            tmp.pop("hash", None)
            entry_json = json.dumps(tmp, separators=(",", ":"), sort_keys=True)
            payload = entry_json.encode("utf-8")

            if hmac.compare_digest(stored, self._digest(payload)):
                # Healthy HMAC chain — resume.
                self._seq = int(entry.get("seq", 0))
                self._prev_hash = stored
                return

            if hmac.compare_digest(stored, self._legacy_digest(payload)):
                # Legacy unkeyed SHA-384 chain — preserve and migrate.
                self._rotate_aside(
                    "legacy",
                    reason="pre-HMAC unkeyed SHA-384 chain detected",
                )
                self._log_internal(
                    "audit_chain_migrated",
                    {"from": "sha384-unkeyed", "to": "hmac-sha384"},
                )
                return

            # Neither — treat as tampered/unrecoverable.
            # v5.7.6: do NOT silently rotate-and-continue. Seal the
            # logger, drop a sentinel file, and refuse further writes
            # until the operator explicitly resets the chain via
            # ``dupez --reset-audit``. The suspect file is preserved
            # under ``audit.tampered.<ts>.jsonl`` for forensics.
            self._rotate_aside(
                "tampered",
                reason="terminal entry hash matches neither HMAC nor legacy SHA-384",
            )
            self._seal(
                reason=(
                    "terminal audit entry did not verify under current or "
                    "legacy algorithm — chain is considered untrusted until "
                    "operator runs `dupez --reset-audit`"
                ),
            )
        except Exception as e:
            log_error(f"AuditLogger: failed to resume chain: {e}")
            # Resume itself failing is also an integrity signal —
            # something is wrong with the audit substrate. Seal.
            try:
                self._seal(reason=f"chain resume crashed: {e}")
            except Exception:
                pass

    def _rotate_aside(self, tag: str, *, reason: str = "") -> None:
        """Move the current audit file aside with a tagged suffix, start fresh."""
        try:
            ts = int(time.time())
            rotated = self._audit_path.with_suffix(f".{tag}.{ts}.jsonl")
            os.rename(str(self._audit_path), str(rotated))
            log_info(
                f"AuditLogger: rotated {self._audit_path.name} → "
                f"{rotated.name} ({reason or tag})"
            )
        except Exception as e:
            log_error(f"AuditLogger: failed to rotate audit file: {e}")
        self._seq = 0
        self._prev_hash = GENESIS_HASH

    # ── v5.7.6: fail-closed tamper sentinel ──────────────────────

    def _seal(self, *, reason: str) -> None:
        """Mark the audit substrate as untrusted and refuse further writes.

        Writes a sentinel JSON file (``audit.TAMPERED``) recording the
        timestamp and reason. Subsequent :meth:`log` calls return
        without writing. The sentinel persists across process restarts
        (we re-check it in ``__init__``), so a fresh launch of DupeZ
        on a previously-sealed install also stays sealed.

        The operator clears the seal with ``dupez --reset-audit``,
        which calls :meth:`reset_after_tamper` after archiving the
        suspect chain.
        """
        self.sealed = True
        try:
            doc = {
                "schema": "dupez.audit-tamper.v1",
                "sealed_at": time.time(),
                "reason": reason,
            }
            payload = json.dumps(doc, sort_keys=True).encode("utf-8")
            with open(self._tamper_sentinel, "wb") as f:
                f.write(payload)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            log_error(
                f"AuditLogger: SEALED — {reason}. "
                f"Run `dupez --reset-audit` after investigating "
                f"{self._audit_dir} to resume audit logging."
            )
        except Exception as e:
            # Sentinel-write itself failing is an availability problem,
            # not a confidentiality/integrity one. Stay sealed in-process
            # regardless — that's what matters for refusing writes.
            log_error(f"AuditLogger: failed to write tamper sentinel: {e}")

    def is_sealed(self) -> bool:
        """True iff the logger is in fail-closed tamper mode."""
        return self.sealed

    def reset_after_tamper(self) -> Path:
        """Operator-driven recovery from the sealed state.

        Archives every ``audit*.tampered*.jsonl`` file and the current
        ``audit.jsonl`` (if any) into a single quarantine bundle named
        ``audit-quarantine-<ts>/`` under the audit dir, removes the
        sentinel, and resets the in-memory chain so the next
        :meth:`log` call starts a fresh HMAC chain.

        Returns the quarantine directory path so the caller (CLI flag)
        can print it for the operator.
        """
        ts = int(time.time())
        quarantine = self._audit_dir / f"audit-quarantine-{ts}"
        quarantine.mkdir(parents=True, exist_ok=True)
        # Move every audit-related file aside.
        for entry in self._audit_dir.iterdir():
            name = entry.name
            if name == quarantine.name:
                continue
            if name == TAMPER_SENTINEL_FILENAME:
                continue
            if not (name == AUDIT_FILENAME or name.startswith("audit")):
                continue
            try:
                os.rename(str(entry), str(quarantine / name))
            except OSError as e:
                log_error(f"AuditLogger.reset: failed to move {name}: {e}")
        # Clear the sentinel last.
        try:
            os.unlink(self._tamper_sentinel)
        except OSError:
            pass
        # Reset in-memory chain state.
        self.sealed = False
        self._sealed_warned = False
        self._seq = 0
        self._prev_hash = GENESIS_HASH
        # Mark the reason in the new chain so post-hoc readers see it.
        self._log_internal(
            "audit_chain_reset_by_operator",
            {"quarantine_dir": str(quarantine), "ts": ts},
        )
        return quarantine

    # ── Write path ───────────────────────────────────────────────

    def log(self, event: str, data: Optional[Dict] = None) -> None:
        """Append a tamper-evident audit entry.

        v5.7.6: when the logger is sealed (a previous tamper / chain
        failure tripped the sentinel), this is a no-op. We log a single
        stderr line per process so the operator sees there's a problem,
        but we DO NOT write further entries to the audit file — the
        integrity of subsequent writes can't be guaranteed until the
        chain is reset.

        Args:
            event: Event type (e.g. ``"disruption_start"``)
            data: Event data dict (PII will be scrubbed)
        """
        if self.sealed:
            if not self._sealed_warned:
                log_error(
                    f"AuditLogger: refusing to log {event!r} — logger is "
                    f"SEALED (run `dupez --reset-audit`). Subsequent "
                    f"events will be silently dropped until reset."
                )
                self._sealed_warned = True
            return
        scrubbed = _scrub_pii(data or {})
        self._write_entry(event, scrubbed)
        # v5.7.4: fan out to registered webhook sinks (Discord etc.)
        # AFTER the canonical JSONL write succeeds — the audit log is
        # the source of truth; the webhook is a best-effort notification.
        # Pre-v5.7.4 the audit_webhook module existed but emit_to_sinks
        # was never called from here, so configured webhooks fired
        # nothing. The sink layer does its own event whitelisting,
        # rate-limiting, and a second PII scrub, and dispatches on
        # daemon threads — this call returns immediately and never
        # raises into the audit hot path.
        try:
            from app.core.audit_webhook import emit_to_sinks
            emit_to_sinks(event, scrubbed)
        except Exception:
            # A webhook-layer failure must never break audit logging.
            pass

    def _log_internal(self, event: str, data: Dict[str, Any]) -> None:
        """Log a structural event (migration/reset) without PII scrubbing.

        Internal-only — used from :meth:`_resume_chain` to record the
        reason a chain was rotated. The payload is constructed by us
        and contains no caller data, so the scrub is unnecessary.
        """
        self._write_entry(event, data)

    def _write_entry(self, event: str, data: Any) -> None:
        with self._lock:
            self._seq += 1
            entry: Dict[str, Any] = {
                "seq": self._seq,
                "ts": time.time(),
                "event": event,
                "data": data,
                "prev_hash": self._prev_hash,
            }
            if self.degraded:
                # Flag every entry written under ephemeral key so a
                # reader can tell which writes are cross-process verifiable.
                entry["key_state"] = "ephemeral"

            entry_json = json.dumps(entry, separators=(",", ":"), sort_keys=True)
            entry_hash = self._digest(entry_json.encode("utf-8"))
            entry["hash"] = entry_hash
            self._prev_hash = entry_hash

            try:
                self._maybe_rotate()
                final_json = json.dumps(entry, separators=(",", ":"), sort_keys=True)
                with open(self._audit_path, "a", encoding="utf-8") as f:
                    f.write(final_json + "\n")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
            except Exception as e:
                log_error(f"AuditLogger: failed to write entry: {e}")

    def _maybe_rotate(self) -> None:
        """Rotate audit file if it exceeds size threshold."""
        try:
            if self._audit_path.exists():
                size = self._audit_path.stat().st_size
                if size > MAX_AUDIT_SIZE_BYTES:
                    rotated = self._audit_path.with_suffix(
                        f".{int(time.time())}.jsonl")
                    os.rename(str(self._audit_path), str(rotated))
                    log_info(f"AuditLogger: rotated to {rotated.name}")
        except Exception as e:
            log_error(f"AuditLogger: rotation failed: {e}")

    # ── Verify ───────────────────────────────────────────────────

    def verify_chain(self) -> Tuple[bool, int, str]:
        """Verify the integrity of the entire audit chain.

        Returns:
            ``(valid, entries_checked, error_message)``

        Verification is constant-time on each per-entry digest
        comparison via :func:`hmac.compare_digest`, so a timing
        side-channel can't leak partial matches to a co-resident
        attacker (defensive: we don't actually expect one, but it's
        free here).
        """
        if not self._audit_path.exists():
            return True, 0, ""

        prev_hash = GENESIS_HASH
        count = 0

        try:
            with open(self._audit_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    entry = json.loads(line)
                    stored_hash = entry.pop("hash", "")
                    if not isinstance(stored_hash, str) or not stored_hash:
                        return False, count, (
                            f"Missing hash at line {line_num}"
                        )

                    # Verify prev_hash chain
                    if entry.get("prev_hash") != prev_hash:
                        return False, count, (
                            f"Chain broken at line {line_num}: "
                            f"expected prev_hash={prev_hash[:16]}..., "
                            f"got {str(entry.get('prev_hash', ''))[:16]}..."
                        )

                    # Verify entry hash under the active key.
                    entry_json = json.dumps(entry, separators=(",", ":"),
                                            sort_keys=True)
                    computed = self._digest(entry_json.encode("utf-8"))
                    if not hmac.compare_digest(computed, stored_hash):
                        return False, count, (
                            f"HMAC mismatch at line {line_num}: "
                            f"entry may have been tampered with, or was "
                            f"written under a different key"
                        )

                    prev_hash = stored_hash
                    count += 1

            return True, count, ""

        except Exception as e:
            return False, count, f"Verification error: {e}"


# ── Global instance ──────────────────────────────────────────────────

_audit_logger: Optional[AuditLogger] = None
_audit_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    """Return the global audit logger (lazy singleton)."""
    global _audit_logger
    if _audit_logger is None:
        with _audit_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
    return _audit_logger


def audit_event(event: str, data: Optional[Dict] = None) -> None:
    """Convenience function to log an audit event."""
    get_audit_logger().log(event, data)
