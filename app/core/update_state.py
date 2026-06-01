"""
Monotonic update-state ledger for DupeZ's auto-updater (v5.7.6).

Threat model
------------
``app/core/update_verify.py`` already ensures an incoming manifest was
signed by a pinned Ed25519 key. That binds the manifest to "an
authentic past release," but it says nothing about whether the
incoming manifest is the *latest* release.

If an attacker who can intercept the GitHub-Releases response (a
compromised CDN, a one-time signing-key compromise on a withdrawn
release, a malicious mirror) re-publishes a known-vulnerable older
manifest under the latest-download alias, the signature check passes
and every client "updates" backwards into the vulnerable version. That
is the classic *downgrade replay* attack and the Ed25519 fingerprint
pin does not stop it on its own.

Mitigation
----------
This module keeps a small, machine-bound ledger of the highest
manifest version this client has ever verified. The ledger lives at::

    <app/data>/update_state.json
    <app/data>/update_state.json.hmac    # 96-hex-char HMAC-SHA384

The ledger is signed under the existing per-install
``persistence.hmac`` secret (managed by :mod:`app.core.secret_store`,
DPAPI-sealed on Windows, 0o600 on POSIX), reusing the integrity
infrastructure from :mod:`app.core.data_persistence`. A local-file
attacker who can edit ``update_state.json`` cannot forge the matching
``.hmac`` without also compromising the user's DPAPI master key.

Policy
------
On every successful ``verify_manifest`` call:

    1. Load ``last_seen_version`` from the ledger (default ``"0.0.0"``
       on first run or HMAC mismatch — fail-safe, not fail-open).
    2. If incoming manifest version >= last_seen_version: accept,
       update ledger.
    3. If incoming manifest version <  last_seen_version: REJECT.

The rejection raises :class:`DowngradeRefusedError`, the updater logs
the event, emits an audit record, and refuses to launch the installer.

The compare is strict semver — pre-release/build metadata is ignored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional, Tuple

__all__ = [
    "DowngradeRefusedError",
    "UpdateStateError",
    "get_last_seen_version",
    "set_last_seen_version",
    "is_downgrade",
    "compare_versions",
    "enforce_monotonic_version",
    "ledger_path",
]


class UpdateStateError(RuntimeError):
    """Raised on unrecoverable ledger I/O failure."""


class DowngradeRefusedError(ValueError):
    """Raised when an incoming manifest version < last_seen_version.

    The caller MUST NOT launch the installer on this error.
    """


# ── Constants ────────────────────────────────────────────────────────

_LEDGER_FILENAME: str = "update_state.json"
_HMAC_SUFFIX: str = ".hmac"
_SCHEMA: str = "dupez.update-state.v1"
_DEFAULT_VERSION: str = "0.0.0"

_SEMVER_RE = re.compile(
    r"^(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)"
    r"(?:[-+][0-9A-Za-z.\-]+)?$"
)

_LOCK = threading.Lock()


# ── Path resolution ──────────────────────────────────────────────────

def ledger_path() -> Path:
    """Return the absolute path to ``update_state.json``.

    Resolved relative to the same data directory the audit log and the
    persistence layer use, so the file lives next to the rest of the
    integrity-protected state under ``<app/data>``.
    """
    from app.core.data_persistence import _resolve_data_directory
    base = Path(_resolve_data_directory())
    base.mkdir(parents=True, exist_ok=True)
    return base / _LEDGER_FILENAME


# ── HMAC plumbing — borrowed from data_persistence ───────────────────

def _digest(payload: bytes) -> str:
    """Return the persistence-keyed HMAC-SHA384 hex digest of *payload*."""
    # Lazy import — keeps update_state importable from very early in
    # boot (before data_persistence has been touched).
    from app.core.data_persistence import _get_hmac_key
    return hmac.new(_get_hmac_key(), payload, hashlib.sha384).hexdigest()


def _verify(payload: bytes, expected_hex: str) -> bool:
    """Constant-time HMAC verification under the persistence key."""
    if not isinstance(expected_hex, str) or len(expected_hex) != 96:
        return False
    computed = _digest(payload)
    return hmac.compare_digest(computed, expected_hex)


# ── Semver compare ───────────────────────────────────────────────────

def _parse(version: str) -> Optional[Tuple[int, int, int]]:
    """Return (major, minor, patch) tuple or None on malformed input."""
    if not isinstance(version, str):
        return None
    m = _SEMVER_RE.match(version.strip())
    if not m:
        return None
    return int(m.group("maj")), int(m.group("min")), int(m.group("pat"))


def compare_versions(a: str, b: str) -> int:
    """Return -1/0/+1 for a < b / a == b / a > b.

    Strict semver MAJOR.MINOR.PATCH. Pre-release / build metadata are
    parsed off but ignored for the ordering — the policy here is "two
    different 5.7.6 builds compare equal," which is the right call for
    a downgrade check (you can roll a fresh signing of the same
    version, you can't roll backwards).

    Unparseable inputs are treated as ``0.0.0`` so a malformed manifest
    cannot win the ordering.
    """
    pa = _parse(a) or (0, 0, 0)
    pb = _parse(b) or (0, 0, 0)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def is_downgrade(incoming: str, last_seen: str) -> bool:
    """True iff *incoming* is strictly older than *last_seen*."""
    return compare_versions(incoming, last_seen) < 0


# ── Ledger I/O ───────────────────────────────────────────────────────

def get_last_seen_version() -> str:
    """Return the highest manifest version this install has accepted.

    Returns ``"0.0.0"`` on first run, missing ledger, malformed JSON,
    or HMAC mismatch. The defaulting is *intentionally permissive*
    here: a missing/broken ledger blocks NO updates — it only fails to
    raise the floor — so we can't deadlock a fresh install. The
    integrity guarantee is "we never silently lower the floor."
    """
    path = ledger_path()
    hmac_path = path.with_suffix(path.suffix + _HMAC_SUFFIX)
    try:
        if not path.exists() or not hmac_path.exists():
            return _DEFAULT_VERSION
        with open(path, "rb") as f:
            raw = f.read()
        with open(hmac_path, "r", encoding="ascii") as f:
            tag = f.read().strip()
        if not _verify(raw, tag):
            return _DEFAULT_VERSION
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict):
            return _DEFAULT_VERSION
        if doc.get("schema") != _SCHEMA:
            return _DEFAULT_VERSION
        ver = doc.get("last_seen_version", _DEFAULT_VERSION)
        if not isinstance(ver, str):
            return _DEFAULT_VERSION
        if _parse(ver) is None:
            return _DEFAULT_VERSION
        return ver
    except (OSError, ValueError, UnicodeDecodeError):
        return _DEFAULT_VERSION


def set_last_seen_version(version: str) -> None:
    """Persist *version* as the new floor. Never lowers an existing floor.

    Writes are atomic (tmp + os.replace) and binary mode so Windows
    CRLF translation cannot corrupt the bytes that the HMAC was
    computed over.
    """
    parsed = _parse(version)
    if parsed is None:
        raise UpdateStateError(f"refusing to persist malformed version {version!r}")
    with _LOCK:
        existing = get_last_seen_version()
        if compare_versions(version, existing) < 0:
            # Never lower the floor. Caller is supposed to gate this
            # via ``enforce_monotonic_version`` but defense-in-depth.
            return
        path = ledger_path()
        hmac_path = path.with_suffix(path.suffix + _HMAC_SUFFIX)
        doc = {
            "schema": _SCHEMA,
            "last_seen_version": version,
        }
        payload = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")
        tag = _digest(payload)
        tmp_json = str(path) + ".tmp"
        tmp_hmac = str(hmac_path) + ".tmp"
        try:
            with open(tmp_json, "wb") as f:
                f.write(payload)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            with open(tmp_hmac, "wb") as f:
                f.write(tag.encode("ascii"))
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_json, str(path))
            os.replace(tmp_hmac, str(hmac_path))
        except OSError as e:
            for p in (tmp_json, tmp_hmac):
                try:
                    os.unlink(p)
                except OSError:
                    pass
            raise UpdateStateError(f"failed to persist update ledger: {e}") from e


# ── Policy gate ──────────────────────────────────────────────────────

def enforce_monotonic_version(incoming_version: str) -> None:
    """Raise :class:`DowngradeRefusedError` if *incoming* < last seen.

    On accept, the ledger is bumped to *incoming_version*. The bump
    happens BEFORE the installer launches — that's intentional. If the
    installer subsequently fails, we still don't want to re-accept the
    same or older manifest blindly; the next successful run will
    advance again.

    Callers MUST treat the exception as fatal: do not launch the
    installer, do not retry under the same manifest. The audit emit is
    done by the updater wrapper, not here, so this module stays
    side-effect-light and easy to unit-test.
    """
    last_seen = get_last_seen_version()
    if is_downgrade(incoming_version, last_seen):
        raise DowngradeRefusedError(
            f"refusing manifest version {incoming_version!r}: "
            f"strictly older than last accepted {last_seen!r}. "
            f"This indicates a downgrade-replay attack or a "
            f"misconfigured release alias — fail-closed."
        )
    set_last_seen_version(incoming_version)
