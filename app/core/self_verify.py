"""
Self-integrity check for the DupeZ executable (v5.7.6, item #6).

Threat model
------------
A local attacker (or a malicious uninstaller/installer combo, or a
quick-and-dirty "modded" DupeZ build floated on a forum) can swap the
``dupez.exe`` on disk with a tampered version that signs its own
update manifests under the official pubkey it copied — wait, no, the
adversary can't do that without the private key. What they CAN do:
replace ``dupez.exe`` with a binary that bypasses the firewall consent
flow, ships keystrokes off-box, or quietly enables the network
scanner against arbitrary subnets. The Ed25519 signing chain protects
*delivery* of updates; it does nothing for *post-install tamper* of
the binary already on disk.

Mitigation
----------
Each release ships a sidecar ``dupez.exe.sig`` (built by
``scripts/sign-release.py``) — a 72-byte envelope identical to the
update manifest sig envelope: 8-byte pubkey fingerprint + 64-byte
Ed25519 signature over the SHA-256 of the executable bytes.

``verify_self()`` reads the running exe (or this script under
``python``), hashes it, and verifies the signature against the same
``TRUSTED_PUBKEYS_PEM`` list used by the update verifier. It is
intended to be called:

* From ``dupez --verify-self`` (operator escape hatch / CI check)
* Optionally at startup as a non-blocking, log-only check; a failure
  in the auto-startup path does NOT refuse to boot (avoids bricking
  the operator on first install before the sidecar is provisioned)
  but it audits loudly.

Dev / source-tree caveat
------------------------
When running from a source checkout (``python dupez.py``), there is no
exe to verify and no ``dupez.exe.sig`` next to ``sys.executable``.
``verify_self`` returns ``(True, "skipped: not a frozen build")`` in
that case so the dev workflow doesn't trip the check.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

__all__ = ["verify_self", "exe_signature_path"]


def _running_exe_path() -> Optional[Path]:
    """Return the path to the running PyInstaller exe, or ``None`` if dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def exe_signature_path(exe: Path) -> Path:
    """Return the expected sidecar path for *exe*: ``<exe>.sig``."""
    return exe.with_suffix(exe.suffix + ".sig")


def _sha256_of_file(path: Path) -> bytes:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.digest()


def verify_self() -> Tuple[bool, str]:
    """Verify the running binary against its bundled signature sidecar.

    Returns ``(ok, message)``:

    * ``(True, "verified: ...")``        — signature matched a pinned pubkey
    * ``(True, "skipped: ...")``         — dev mode / no sidecar; do not fail
    * ``(False, "tampered: ...")``       — fingerprint or signature mismatch
    * ``(False, "missing-sidecar: ...")`` — frozen build w/o sig; suspicious

    The caller picks the policy. ``--verify-self`` exits non-zero on
    any False; the startup auto-check logs but doesn't exit.
    """
    exe = _running_exe_path()
    if exe is None:
        return True, "skipped: not a frozen build (running from source)"
    if not exe.is_file():
        return False, f"running exe not found at {exe}"

    sig_path = exe_signature_path(exe)
    if not sig_path.is_file():
        return False, (
            f"missing-sidecar: expected {sig_path.name} alongside the "
            f"executable. The binary cannot be self-verified. If this is "
            f"a freshly built install that pre-dates v5.7.6 signing, "
            f"re-download the latest signed installer."
        )

    try:
        sig_envelope = sig_path.read_bytes()
    except OSError as e:
        return False, f"sidecar unreadable: {e}"

    try:
        from app.core.update_verify import (
            FINGERPRINT_SIZE,
            SIG_ENVELOPE_SIZE,
            SIGNATURE_SIZE,
            SigVerifyError,
            TRUSTED_PUBKEYS_PEM,
            _load_ed25519_pubkey,
            pubkey_fingerprint,
        )
    except ImportError as e:
        return False, f"update_verify import failed: {e}"

    if len(sig_envelope) != SIG_ENVELOPE_SIZE:
        return False, (
            f"tampered: sidecar size {len(sig_envelope)} != "
            f"{SIG_ENVELOPE_SIZE}"
        )
    fingerprint = sig_envelope[:FINGERPRINT_SIZE]
    signature = sig_envelope[FINGERPRINT_SIZE:]
    assert len(signature) == SIGNATURE_SIZE

    matched_pem = None
    for pem in TRUSTED_PUBKEYS_PEM:
        if pubkey_fingerprint(pem) == fingerprint:
            matched_pem = pem
            break
    if matched_pem is None:
        return False, (
            "tampered: sidecar fingerprint does not match any pinned "
            "release key (the binary's signature claims to be signed by "
            "a key this client does not trust)"
        )

    try:
        exe_hash = _sha256_of_file(exe)
        pubkey = _load_ed25519_pubkey(matched_pem)
        from cryptography.exceptions import InvalidSignature
        try:
            pubkey.verify(signature, exe_hash)
        except InvalidSignature:
            return False, (
                "tampered: Ed25519 signature does not match the SHA-256 "
                "of the running executable. The on-disk binary has been "
                "modified since release."
            )
    except SigVerifyError as e:
        return False, f"tampered: {e}"
    except Exception as e:
        return False, f"verification crashed: {e}"

    return True, (
        f"verified: {exe.name} matches its signed sidecar "
        f"(fingerprint={fingerprint.hex()})"
    )
