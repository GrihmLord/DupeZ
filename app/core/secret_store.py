"""
Machine-rooted secret storage for DupeZ.

This module provides the one primitive we lacked everywhere else: a
durable, OS-integrated way to store a random byte string (typically a
32-byte key) such that an attacker with read access to the repository,
the installation directory, and the user's home directory — but
without *live* user-session context on the victim machine — still
cannot recover it.

Windows  →  CryptProtectData (DPAPI), user-scope by default.
            The ciphertext is bound to the logged-in user's master key.
            The key can be decrypted only from a logon session belonging
            to that user. Pass ``machine_scope=True`` for LocalMachine
            scope (decryptable by any local admin on the same machine).
            User scope is stronger and is the default.

POSIX    →  0600 ``~/.local/share/DupeZ/secrets/<name>.bin`` with the
            raw key bytes. Not as strong as DPAPI (a root-privileged
            reader owns the user anyway) but sufficient given that
            DupeZ on POSIX is a developer-only path.

Everywhere, keys are:

  * generated via ``secrets.token_bytes`` (CSPRNG)
  * bound to a caller-supplied string label (``kind``) so two callers
    asking for distinct secrets cannot collide
  * never logged or serialised to disk in plaintext

Public API
----------

    get_or_create_secret(kind: str, size: int = 32) -> bytes
    get_secret(kind: str) -> bytes | None
    put_secret(kind: str, value: bytes) -> None
    delete_secret(kind: str) -> bool
    wipe_secret_in_memory(secret: bytes) -> None

The ``kind`` is a short identifier like ``"audit.hmac"`` or
``"persistence.hmac"``. One file per kind.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import secrets as _secrets
import sys
import threading
from pathlib import Path
from typing import Optional

__all__ = [
    "SecretStoreError",
    "get_or_create_secret",
    "get_secret",
    "put_secret",
    "delete_secret",
    "wipe_secret_in_memory",
    "store_root",
]


class SecretStoreError(RuntimeError):
    """Raised on unrecoverable secret-storage errors (DPAPI fail, ACL fail, ...)."""


_STORE_LOCK = threading.Lock()
_KIND_RE = __import__("re").compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)*$")


# ── Paths ─────────────────────────────────────────────────────────────

def store_root() -> Path:
    """Return the directory where encrypted secrets are written.

    Windows: ``%LOCALAPPDATA%\\DupeZ\\secrets``
    POSIX:   ``$XDG_DATA_HOME/DupeZ/secrets`` or ``~/.local/share/DupeZ/secrets``

    Created with restrictive perms on first access.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        root = Path(base) / "DupeZ" / "secrets"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        root = Path(xdg) / "DupeZ" / "secrets"
    root.mkdir(parents=True, exist_ok=True)
    try:
        # 0o700 on POSIX — keeps other users out. No-op on Windows.
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _path_for(kind: str) -> Path:
    if not isinstance(kind, str) or not _KIND_RE.match(kind):
        raise ValueError(f"invalid secret kind {kind!r}")
    return store_root() / f"{kind}.bin"


# ── DPAPI (Windows) ───────────────────────────────────────────────────

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _make_blob(data: bytes) -> _DataBlob:
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DataBlob(cbData=len(data), pbData=ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))


def _blob_bytes(blob: _DataBlob) -> bytes:
    return bytes(ctypes.string_at(blob.pbData, blob.cbData))


# CryptProtectData flags. We always use CRYPTPROTECT_UI_FORBIDDEN to
# ensure we never trigger an interactive DPAPI prompt from the service
# elevation path. LOCAL_MACHINE is opt-in.
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _dpapi_protect(plaintext: bytes, machine_scope: bool = False) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    in_blob = _make_blob(plaintext)
    out_blob = _DataBlob()
    flags = _CRYPTPROTECT_UI_FORBIDDEN
    if machine_scope:
        flags |= _CRYPTPROTECT_LOCAL_MACHINE
    # CryptProtectData(pDataIn, description, pEntropy, pvReserved,
    #                  pPromptStruct, dwFlags, pDataOut)
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, flags, ctypes.byref(out_blob)
    ):
        err = kernel32.GetLastError()
        raise SecretStoreError(f"DPAPI protect failed: GetLastError={err}")
    try:
        return _blob_bytes(out_blob)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(ciphertext: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    in_blob = _make_blob(ciphertext)
    out_blob = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)
    ):
        err = kernel32.GetLastError()
        raise SecretStoreError(f"DPAPI unprotect failed: GetLastError={err}")
    try:
        return _blob_bytes(out_blob)
    finally:
        kernel32.LocalFree(out_blob.pbData)


# ── Public API ────────────────────────────────────────────────────────

def get_secret(kind: str) -> Optional[bytes]:
    """Read a previously stored secret, or None if not present.

    Raises SecretStoreError if the file exists but cannot be decrypted
    (tamper, wrong user profile, DPAPI master key lost).
    """
    path = _path_for(kind)
    if not path.is_file():
        return None
    with _STORE_LOCK:
        raw = path.read_bytes()
    if os.name == "nt":
        return _dpapi_unprotect(raw)
    # POSIX: file IS the key. Verify perms for defense in depth.
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            # world/group readable — refuse. Better a loud failure than
            # a silent leak.
            raise SecretStoreError(
                f"refusing to read secret {kind!r}: perms {oct(mode)} are "
                "too permissive (expected 0o600)"
            )
    except OSError as e:
        raise SecretStoreError(f"secret stat failed: {e}") from e
    return raw


def put_secret(kind: str, value: bytes, *, machine_scope: bool = False) -> None:
    """Persist a secret.

    Callers should prefer ``get_or_create_secret`` for the typical
    lazy-init pattern. Direct ``put_secret`` is for rotation flows.
    """
    if not isinstance(value, (bytes, bytearray)) or not value:
        raise ValueError("secret value must be non-empty bytes")
    path = _path_for(kind)
    with _STORE_LOCK:
        if os.name == "nt":
            payload = _dpapi_protect(bytes(value), machine_scope=machine_scope)
        else:
            payload = bytes(value)

        # Atomic replace: write tmp, fsync, replace.
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)


def delete_secret(kind: str) -> bool:
    """Remove a stored secret. Returns True if a file was deleted."""
    path = _path_for(kind)
    if not path.exists():
        return False
    with _STORE_LOCK:
        try:
            path.unlink()
            return True
        except OSError:
            return False


def get_or_create_secret(
    kind: str,
    size: int = 32,
    *,
    machine_scope: bool = False,
) -> bytes:
    """Return the stored secret for *kind*, creating it on first access.

    The created secret is a CSPRNG-generated *size*-byte sequence. 32
    bytes is the default (HMAC-SHA256 key strength, Ed25519 seed size,
    128-bit symmetric cipher key with 128-bit margin).
    """
    if not isinstance(size, int) or size < 16 or size > 1024:
        raise ValueError(f"size must be in [16, 1024], got {size!r}")
    existing = get_secret(kind)
    if existing is not None:
        return existing
    new = _secrets.token_bytes(size)
    put_secret(kind, new, machine_scope=machine_scope)
    return new


def wipe_secret_in_memory(secret: bytes) -> None:
    """Best-effort overwrite of a mutable ``bytearray`` holding a secret.

    If passed a plain ``bytes`` object, does nothing (bytes are immutable
    in Python — copies may still exist).  Callers that care should hold
    their secret in a ``bytearray`` and pass it here after use.
    """
    if isinstance(secret, bytearray):
        for i in range(len(secret)):
            secret[i] = 0


# ── Self-test hook (sanity) ───────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover — manual smoke test
    import argparse
    ap = argparse.ArgumentParser(description="secret_store manual check")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        root = store_root()
        print(f"store root: {root}")
        k1 = get_or_create_secret("self.test")
        k2 = get_or_create_secret("self.test")
        assert k1 == k2 and len(k1) == 32
        print(f"  persisted key OK ({len(k1)} bytes)")
        delete_secret("self.test")
        print("  delete OK")
        sys.exit(0)
