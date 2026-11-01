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

    1. Authenticate ``last_seen_version`` from the ledger.
    2. Set the effective floor to the greater of the installed binary's
       ``CURRENT_VERSION`` and the authenticated ledger value. A missing,
       malformed, or unauthenticated ledger therefore falls back to the
       installed version, never to an update-channel genesis value.
    3. If incoming manifest version >= the effective floor: accept and
       update the ledger. If it is lower: REJECT.

The actual auto-update path applies a second, stricter rule: the incoming
version must be strictly greater than the installed binary. Equal versions
may be recorded by this ledger module, but must never be launched as an
"update".

The rejection raises :class:`DowngradeRefusedError`, the updater logs
the event, emits an audit record, and refuses to launch the installer.

Version ordering follows SemVer 2.0.0: pre-releases sort below the matching
stable release, numeric pre-release identifiers use numeric ordering, and build
metadata does not affect precedence.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional, Tuple

from app.__version__ import __version__ as CURRENT_VERSION

__all__ = [
    "DowngradeRefusedError",
    "UpdateStateError",
    "get_last_seen_version",
    "set_last_seen_version",
    "is_downgrade",
    "compare_versions",
    "enforce_monotonic_version",
    "enforce_update_version",
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
    r"^(?P<maj>0|[1-9]\d*)\."
    r"(?P<min>0|[1-9]\d*)\."
    r"(?P<pat>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
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


# ── Semver compare ───────────────────────────────────────────────────

_PreRelease = Tuple[Tuple[bool, int | str], ...]
_ParsedVersion = Tuple[int, int, int, Optional[_PreRelease]]


def _parse(version: str) -> Optional[_ParsedVersion]:
    """Parse a strict SemVer 2.0.0 value, or return ``None``.

    The boolean in each pre-release identifier is ``True`` for numeric
    identifiers. Numeric identifiers with leading zeroes are invalid, as are
    empty pre-release/build identifiers.
    """
    if not isinstance(version, str):
        return None
    if version != version.strip():
        return None
    m = _SEMVER_RE.match(version)
    if not m:
        return None
    prerelease: Optional[_PreRelease] = None
    raw_prerelease = m.group("pre")
    if raw_prerelease is not None:
        parsed_identifiers: list[Tuple[bool, int | str]] = []
        for identifier in raw_prerelease.split("."):
            if identifier.isdigit():
                if len(identifier) > 1 and identifier.startswith("0"):
                    return None
                parsed_identifiers.append((True, int(identifier)))
            else:
                parsed_identifiers.append((False, identifier))
        prerelease = tuple(parsed_identifiers)
    return (
        int(m.group("maj")),
        int(m.group("min")),
        int(m.group("pat")),
        prerelease,
    )


def compare_versions(a: str, b: str) -> int:
    """Return -1/0/+1 for a < b / a == b / a > b.

    SemVer 2.0.0 precedence is applied in full. Pre-releases sort below the
    corresponding stable version, numeric identifiers compare numerically and
    before non-numeric identifiers, a shorter equal prefix sorts first, and
    build metadata is ignored.

    Unparseable inputs are treated as ``0.0.0`` so a malformed manifest
    cannot win the ordering.
    """
    pa = _parse(a)
    pb = _parse(b)
    if pa is None:
        pa = (0, 0, 0, None)
    if pb is None:
        pb = (0, 0, 0, None)

    core_a = pa[:3]
    core_b = pb[:3]
    if core_a < core_b:
        return -1
    if core_a > core_b:
        return 1

    pre_a = pa[3]
    pre_b = pb[3]
    if pre_a is None and pre_b is None:
        return 0
    if pre_a is None:
        return 1
    if pre_b is None:
        return -1

    for identifier_a, identifier_b in zip(pre_a, pre_b):
        if identifier_a == identifier_b:
            continue
        numeric_a, value_a = identifier_a
        numeric_b, value_b = identifier_b
        if numeric_a != numeric_b:
            return -1 if numeric_a else 1
        if value_a < value_b:
            return -1
        return 1
    if len(pre_a) < len(pre_b):
        return -1
    if len(pre_a) > len(pre_b):
        return 1
    return 0


def is_downgrade(incoming: str, last_seen: str) -> bool:
    """True iff *incoming* is strictly older than *last_seen*."""
    return compare_versions(incoming, last_seen) < 0


# ── Ledger I/O ───────────────────────────────────────────────────────

def _read_authenticated_ledger_version(
    *,
    path: Path | None = None,
    _lock_held: bool = False,
) -> Optional[str]:
    """Return the authenticated ledger value, or ``None`` if unavailable.

    Missing state and integrity/parse failures are deliberately
    indistinguishable here. Neither is authoritative enough to lower the
    installed-version floor.
    """
    from app.core.data_persistence import DataPersistenceManager

    path = path or ledger_path()
    hmac_path = path.with_suffix(path.suffix + _HMAC_SUFFIX)
    try:
        raw = DataPersistenceManager._read_authenticated_bytes(
            path,
            hmac_path=hmac_path,
            require_hmac=True,
            _lock_held=_lock_held,
        )
        if raw is None:
            return None
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict):
            return None
        if doc.get("schema") != _SCHEMA:
            return None
        ver = doc.get("last_seen_version", _DEFAULT_VERSION)
        if not isinstance(ver, str):
            return None
        if _parse(ver) is None:
            return None
        return ver
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _validated_installed_version(installed_version: Optional[str]) -> str:
    """Return a valid installed version or fail closed on build drift."""
    version = CURRENT_VERSION if installed_version is None else installed_version
    if _parse(version) is None:
        raise UpdateStateError(
            f"installed version is malformed; refusing update state use: {version!r}"
        )
    return version


def get_last_seen_version(installed_version: Optional[str] = None) -> str:
    """Return the effective authenticated downgrade floor.

    The floor is always ``max(installed_version, authenticated_ledger)``.
    On first run, missing ledger, malformed JSON, or HMAC mismatch, the
    installed binary's version remains authoritative. This prevents local
    deletion or corruption of the ledger from making a current install
    accept an older, but otherwise validly signed, release manifest.

    ``installed_version`` is injectable for focused tests. Production callers
    should omit it so :mod:`app.__version__` remains the source of truth.
    """
    installed = _validated_installed_version(installed_version)
    authenticated = _read_authenticated_ledger_version()
    if authenticated is None:
        return installed
    if compare_versions(authenticated, installed) > 0:
        return authenticated
    return installed


def set_last_seen_version(
    version: str,
    installed_version: Optional[str] = None,
) -> None:
    """Persist *version* as the new floor. Never lowers an existing floor.

    The read/compare/commit sequence holds the mandatory per-target process
    lock. An immutable authenticated generation is durable before its atomic
    commit pointer advances, so neither a racing writer nor an abrupt exit can
    lower a previously committed high-water mark.
    """
    parsed = _parse(version)
    if parsed is None:
        raise UpdateStateError(f"refusing to persist malformed version {version!r}")
    installed = _validated_installed_version(installed_version)
    from app.core.data_persistence import (
        DataPersistenceManager,
        _authenticated_state_lock,
    )

    with _LOCK:
        path = ledger_path()
        hmac_path = path.with_suffix(path.suffix + _HMAC_SUFFIX)
        try:
            with _authenticated_state_lock(path):
                authenticated = _read_authenticated_ledger_version(
                    path=path,
                    _lock_held=True,
                )
                existing = installed
                if (
                    authenticated is not None
                    and compare_versions(authenticated, existing) > 0
                ):
                    existing = authenticated
                if compare_versions(version, existing) < 0:
                    return
                doc = {
                    "schema": _SCHEMA,
                    "last_seen_version": version,
                }
                payload = json.dumps(
                    doc,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                DataPersistenceManager._replace_authenticated_pair(
                    path,
                    payload,
                    hmac_path=hmac_path,
                    _lock_held=True,
                )
        except Exception as exc:
            raise UpdateStateError(
                f"failed to persist update ledger: {exc}"
            ) from exc


# ── Policy gate ──────────────────────────────────────────────────────

def enforce_monotonic_version(
    incoming_version: str,
    installed_version: Optional[str] = None,
) -> None:
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
    if _parse(incoming_version) is None:
        raise DowngradeRefusedError(
            f"refusing malformed manifest version {incoming_version!r}"
        )
    last_seen = get_last_seen_version(installed_version)
    if is_downgrade(incoming_version, last_seen):
        raise DowngradeRefusedError(
            f"refusing manifest version {incoming_version!r}: "
            f"strictly older than last accepted {last_seen!r}. "
            f"This indicates a downgrade-replay attack or a "
            f"misconfigured release alias — fail-closed."
        )
    set_last_seen_version(incoming_version, installed_version)


def enforce_update_version(
    incoming_version: str,
    installed_version: Optional[str] = None,
) -> None:
    """Enforce the stricter version policy used by the installer path.

    A signed manifest must be strictly newer than the running binary and at
    least as new as the authenticated monotonic ledger. This prevents both
    downgrade replay and re-installation of the current version.
    """
    installed = _validated_installed_version(installed_version)
    if _parse(incoming_version) is None:
        raise DowngradeRefusedError(
            f"refusing malformed manifest version {incoming_version!r}"
        )
    if compare_versions(incoming_version, installed) <= 0:
        raise DowngradeRefusedError(
            f"refusing manifest version {incoming_version!r}: an update must be "
            f"strictly newer than installed version {installed!r}."
        )
    enforce_monotonic_version(incoming_version, installed)
