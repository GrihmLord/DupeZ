"""
Signed release manifest verification for the DupeZ auto-updater.

Threat model
------------
The updater (``app/core/updater.py``) downloads ``DupeZ_Setup.exe`` from
the GitHub releases URL and runs it with ``/SILENT``. Without signature
verification, a compromise of:

    * the GrihmLord GitHub account,
    * the GitHub release artifact storage,
    * a CDN or mirror in the response path, or
    * the user's DNS resolution,

translates one-for-one into silent installer-grade remote code execution
on every user who clicks "Install update". The installer runs at the
same integrity level as the caller (High-IL under the Compat variant),
so this is a full-system compromise.

Mitigation
----------
Each GitHub release SHALL ship three artifacts:

    * ``DupeZ_Setup.exe``                  — the installer binary
    * ``DupeZ_Setup.exe.manifest.json``    — signed metadata
    * ``DupeZ_Setup.exe.manifest.sig``     — Ed25519 signature envelope

The manifest is a small JSON document containing:

    {
        "schema": "dupez.update-manifest.v1",
        "version": "5.7.0",
        "released_at": "2026-04-17T12:34:56Z",
        "installer": {
            "filename": "DupeZ_Setup.exe",
            "sha256": "<64 hex>",
            "size": 12345678
        }
    }

The ``.sig`` file is a detached signature envelope over the EXACT bytes
of the manifest (no re-serialization):

    bytes[0..8]    key_fingerprint = SHA-256(pubkey_pem)[:8]
    bytes[8..72]   ed25519_signature = Ed25519(priv, manifest_bytes)

The verifier checks the fingerprint against TRUSTED_PUBKEYS, verifies
the signature with the matching pubkey, then verifies the installer's
SHA-256 matches ``installer.sha256``. ONLY THEN does the updater launch
the installer.

Key rotation
------------
TRUSTED_PUBKEYS is a list of PEM-encoded Ed25519 keys bundled in this
module at build time. To rotate:

    1. Generate a new keypair offline (scripts/sign-release.py --gen-key).
    2. Add the new pubkey to TRUSTED_PUBKEYS in a new client release.
    3. Release both old-signed and new-signed manifests during the
       transition window.
    4. After all clients upgrade, drop the old pubkey from the list.

The fingerprint approach lets a single verifier support N keys without
needing to try each one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, List, Optional

__all__ = [
    "MANIFEST_SCHEMA",
    "SIG_ENVELOPE_SIZE",
    "SigVerifyError",
    "UpdateManifest",
    "pubkey_fingerprint",
    "verify_manifest",
    "verify_installer_sha256",
]

MANIFEST_SCHEMA = "dupez.update-manifest.v1"
FINGERPRINT_SIZE = 8
SIGNATURE_SIZE = 64
SIG_ENVELOPE_SIZE = FINGERPRINT_SIZE + SIGNATURE_SIZE
MAX_MANIFEST_BYTES = 65_536  # manifest is small JSON — cap hard


# ── Trusted signing keys (pinned) ──────────────────────────────────
#
# Each entry is a PEM-encoded Ed25519 public key.  These pubkeys are
# the ONLY keys that can produce a valid update manifest signature
# for this client.  Compromise of the GitHub account does NOT allow
# an attacker to ship a malicious update — they would additionally
# need to compromise the offline-held private key matching one of
# these pubkeys.
#
# Generate a keypair:
#     python scripts/sign-release.py --gen-key priv.pem pub.pem
#
# Then replace the placeholder below with the PEM contents of pub.pem.
# Do NOT commit the private key.  Keep it on an air-gapped machine or
# in a hardware security module.
#
# Until a real key is provisioned, this list is intentionally empty —
# which causes the updater to refuse every update (fail-closed).  This
# is the correct behaviour: never auto-install from an un-pinned source.
TRUSTED_PUBKEYS_PEM: List[str] = [
    # "-----BEGIN PUBLIC KEY-----\n"
    # "MCowBQYDK2VwAyEA<...base64...>\n"
    # "-----END PUBLIC KEY-----\n",
]


# ── Exceptions ────────────────────────────────────────────────────

class SigVerifyError(ValueError):
    """Raised when an update manifest fails any verification step.

    The caller MUST NOT launch the installer on any SigVerifyError —
    the downloaded file is assumed hostile.
    """


# ── Data types ────────────────────────────────────────────────────

@dataclass(frozen=True)
class UpdateManifest:
    """Parsed, verified update manifest."""
    version: str
    released_at: str
    installer_filename: str
    installer_sha256: str
    installer_size: int


# ── Helpers ───────────────────────────────────────────────────────

def pubkey_fingerprint(pubkey_pem: str) -> bytes:
    """Return the 8-byte fingerprint of a PEM-encoded pubkey.

    Fingerprint = SHA-256(pem_bytes)[:8].  We use the PEM text verbatim
    (including header/footer/newlines) so anyone rotating keys uses the
    same byte-for-byte input.
    """
    if not isinstance(pubkey_pem, str):
        raise TypeError("pubkey_pem must be a PEM string")
    return hashlib.sha256(pubkey_pem.encode("utf-8")).digest()[:FINGERPRINT_SIZE]


def _load_ed25519_pubkey(pem: str):
    """Return a cryptography Ed25519 public key object from PEM."""
    # Lazy import — cryptography is already a runtime dep but this module
    # is imported on GUI startup, so keep the import local.
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    key = load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise SigVerifyError(
            f"pinned key is not Ed25519 (got {type(key).__name__})"
        )
    return key


# ── Manifest + signature verification ─────────────────────────────

def verify_manifest(
    manifest_bytes: bytes,
    sig_envelope: bytes,
    trusted_pubkeys_pem: Optional[Iterable[str]] = None,
) -> UpdateManifest:
    """Verify a signed manifest and return the parsed UpdateManifest.

    Args:
        manifest_bytes: raw bytes of DupeZ_Setup.exe.manifest.json as
            downloaded. MUST be the exact bytes fetched — do NOT
            re-serialize the JSON, as signature is over the raw bytes.
        sig_envelope: raw bytes of DupeZ_Setup.exe.manifest.sig.  72
            bytes exactly: 8-byte pubkey fingerprint + 64-byte signature.
        trusted_pubkeys_pem: optional override (testing).  Defaults to
            the module-level TRUSTED_PUBKEYS_PEM.

    Returns:
        Verified UpdateManifest.

    Raises:
        SigVerifyError on any verification failure (size, parse, unknown
        signer, bad signature, schema mismatch, ...).
    """
    if trusted_pubkeys_pem is None:
        trusted_pubkeys_pem = TRUSTED_PUBKEYS_PEM
    pinned = list(trusted_pubkeys_pem)
    if not pinned:
        raise SigVerifyError(
            "no pinned pubkeys configured — refusing to auto-update. "
            "Provision TRUSTED_PUBKEYS_PEM in app.core.update_verify "
            "before enabling signed updates."
        )

    # 1. Bound checks.
    if not isinstance(manifest_bytes, (bytes, bytearray)):
        raise SigVerifyError("manifest_bytes must be bytes")
    if len(manifest_bytes) == 0 or len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise SigVerifyError(f"manifest size out of bounds: {len(manifest_bytes)}")
    if not isinstance(sig_envelope, (bytes, bytearray)):
        raise SigVerifyError("sig_envelope must be bytes")
    if len(sig_envelope) != SIG_ENVELOPE_SIZE:
        raise SigVerifyError(
            f"sig envelope wrong size: {len(sig_envelope)} "
            f"(expected {SIG_ENVELOPE_SIZE})"
        )

    fingerprint = bytes(sig_envelope[:FINGERPRINT_SIZE])
    signature = bytes(sig_envelope[FINGERPRINT_SIZE:])

    # 2. Find the pinned pubkey matching the fingerprint.
    matched_pem: Optional[str] = None
    for pem in pinned:
        if pubkey_fingerprint(pem) == fingerprint:
            matched_pem = pem
            break
    if matched_pem is None:
        raise SigVerifyError(
            "signature fingerprint does not match any pinned pubkey — "
            "either the manifest was signed by an untrusted key, or the "
            "client needs a newer TRUSTED_PUBKEYS list"
        )

    # 3. Verify Ed25519 signature over the manifest bytes verbatim.
    try:
        from cryptography.exceptions import InvalidSignature
    except ImportError as e:  # pragma: no cover
        raise SigVerifyError(f"cryptography library unavailable: {e}") from e

    pubkey = _load_ed25519_pubkey(matched_pem)
    try:
        pubkey.verify(signature, bytes(manifest_bytes))
    except InvalidSignature as e:
        raise SigVerifyError(f"Ed25519 signature invalid: {e}") from e
    except Exception as e:  # defensive
        raise SigVerifyError(f"signature verification error: {e}") from e

    # 4. Parse JSON and enforce schema.
    try:
        doc = json.loads(bytes(manifest_bytes).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SigVerifyError(f"manifest is not valid UTF-8 JSON: {e}") from e
    if not isinstance(doc, dict):
        raise SigVerifyError("manifest root must be a JSON object")
    if doc.get("schema") != MANIFEST_SCHEMA:
        raise SigVerifyError(
            f"unsupported manifest schema: {doc.get('schema')!r} "
            f"(expected {MANIFEST_SCHEMA!r})"
        )

    version = doc.get("version")
    released_at = doc.get("released_at", "")
    installer = doc.get("installer")
    if not isinstance(version, str) or not version:
        raise SigVerifyError("manifest.version missing")
    if not isinstance(installer, dict):
        raise SigVerifyError("manifest.installer missing")
    filename = installer.get("filename")
    sha256 = installer.get("sha256")
    size = installer.get("size")
    if not isinstance(filename, str) or "/" in filename or "\\" in filename:
        raise SigVerifyError(f"manifest.installer.filename invalid: {filename!r}")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise SigVerifyError(f"manifest.installer.sha256 invalid: {sha256!r}")
    try:
        bytes.fromhex(sha256)
    except ValueError as e:
        raise SigVerifyError(f"manifest.installer.sha256 not hex: {e}") from e
    if not isinstance(size, int) or size <= 0 or size > 1024 * 1024 * 1024:  # 1 GB cap
        raise SigVerifyError(f"manifest.installer.size invalid: {size!r}")

    return UpdateManifest(
        version=version,
        released_at=released_at if isinstance(released_at, str) else "",
        installer_filename=filename,
        installer_sha256=sha256.lower(),
        installer_size=size,
    )


def verify_installer_sha256(
    installer_path: str,
    manifest: UpdateManifest,
) -> None:
    """Hash the downloaded installer and compare to the signed manifest.

    Streams the file so we don't load multi-hundred-MB installers into
    memory.

    Raises SigVerifyError on size or hash mismatch.
    """
    import os as _os
    try:
        actual_size = _os.path.getsize(installer_path)
    except OSError as e:
        raise SigVerifyError(f"installer missing: {e}") from e
    if actual_size != manifest.installer_size:
        raise SigVerifyError(
            f"installer size mismatch: {actual_size} != {manifest.installer_size}"
        )

    h = hashlib.sha256()
    try:
        with open(installer_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
    except OSError as e:
        raise SigVerifyError(f"installer unreadable: {e}") from e
    actual_hash = h.hexdigest().lower()
    if actual_hash != manifest.installer_sha256.lower():
        raise SigVerifyError(
            f"installer hash mismatch: {actual_hash} != {manifest.installer_sha256}"
        )
