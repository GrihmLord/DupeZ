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
            "size": 12345678,
            "authenticode_signer_sha256": "<SHA-256 of signer certificate DER>"
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

import ctypes
import hashlib
import hmac
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

__all__ = [
    "MANIFEST_SCHEMA",
    "SIG_ENVELOPE_SIZE",
    "SigVerifyError",
    "UpdateManifest",
    "pubkey_fingerprint",
    "authenticode_signer_sha256",
    "verify_manifest",
    "verify_manifest_and_enforce_monotonic",
    "verify_installer_authenticode",
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
# Then add the PEM contents of pub.pem to TRUSTED_PUBKEYS_PEM below.
# Do NOT commit the private key.  Keep it on an air-gapped machine or
# in a hardware security module.
#
# Until a real key is provisioned, this list is intentionally empty —
# which causes the updater to refuse every update (fail-closed).  This
# is the correct behaviour: never auto-install from an un-pinned source.
TRUSTED_PUBKEYS_PEM: List[str] = [
    # v5.6.6: Initial release signing key. Generated 2026-05-11, held
    # offline on the maintainer signing host. Fingerprint (8-byte
    # SHA-256 prefix, hex): 4e9c3c6731efbaa8. The signature envelope
    # of every released manifest will start with these 8 bytes.
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEA5hWX33y0ja2IOHeoJBwNB+dwucVJ0WHQ7YdWtGrg9Sw=\n"
    "-----END PUBLIC KEY-----\n",
    # v5.7.9 recovery rotation: the original private key was unavailable on
    # every registered signing host and in the protected secret inventory.
    # v5.7.9 is therefore the manual-upgrade trust bridge for this key.
    # Fingerprint (8-byte SHA-256 prefix, hex): 5555f0e8c31a40ed.
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEAIZXL+OQR2yIJeOdnHa+DIJEZ6kKykWwVN1/jCUNKO6A=\n"  # pragma: allowlist secret
    "-----END PUBLIC KEY-----\n",
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
    authenticode_signer_sha256: Optional[str] = None


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


def _windows_powershell_path() -> Path:
    """Resolve the inbox Windows PowerShell without trusting environment paths."""
    if os.name != "nt":
        raise SigVerifyError("Authenticode verification requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    get_system_directory.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = int(get_system_directory(buffer, len(buffer)))
    if length == 0 or length >= len(buffer):
        raise SigVerifyError(
            "cannot resolve the trusted Windows system directory"
        )
    powershell = (
        Path(buffer.value)
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        raise SigVerifyError("inbox Windows PowerShell is unavailable")
    return powershell


def authenticode_signer_sha256(installer_path: str) -> str:
    """Return the valid Authenticode signer certificate's DER SHA-256.

    ``Get-AuthenticodeSignature`` performs the Windows trust-policy check. The
    returned certificate identity is then hashed from its exact DER bytes and
    can be bound inside the separately Ed25519-signed update manifest.
    """
    path = Path(installer_path).resolve()
    if not path.is_file():
        raise SigVerifyError(f"installer missing: {path}")
    powershell = _windows_powershell_path()
    env = os.environ.copy()
    env["DUPEZ_AUTHENTICODE_TARGET"] = str(path)
    script = r"""
$ErrorActionPreference = 'Stop'
$securityModule = Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1'
Import-Module -Name $securityModule -ErrorAction Stop
$signature = Get-AuthenticodeSignature -LiteralPath $env:DUPEZ_AUTHENTICODE_TARGET
if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) {
    throw "Authenticode status is $($signature.Status)"
}
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $digest = $sha256.ComputeHash($signature.SignerCertificate.RawData)
}
finally {
    $sha256.Dispose()
}
[pscustomobject]@{
    status = $signature.Status.ToString()
    signer_sha256 = ([System.BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
} | ConvertTo-Json -Compress
"""
    try:
        completed = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
            env=env,
        )
    except Exception as exc:
        raise SigVerifyError(
            f"Authenticode signer query failed: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Windows trust policy rejected it"
        raise SigVerifyError(f"installer Authenticode is not valid: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SigVerifyError(
            "Authenticode signer query returned invalid JSON"
        ) from exc
    fingerprint = str(payload.get("signer_sha256") or "").lower()
    if payload.get("status") != "Valid" or not re.fullmatch(
        r"[0-9a-f]{64}", fingerprint
    ):
        raise SigVerifyError(
            "Authenticode signer query returned no valid certificate identity"
        )
    return fingerprint


def verify_installer_authenticode(
    installer_path: str,
    manifest: UpdateManifest,
    *,
    allow_unsigned: bool = False,
) -> None:
    """Verify Windows trust and the Ed25519-bound signer certificate.

    ``allow_unsigned`` exists only for explicit development/test artifact
    tooling. The in-app updater never enables it.
    """
    expected = manifest.authenticode_signer_sha256
    if allow_unsigned and expected is None:
        return
    if expected is None:
        raise SigVerifyError(
            "signed update manifest does not bind an Authenticode signer"
        )
    actual = authenticode_signer_sha256(installer_path)
    if not hmac.compare_digest(actual, expected.lower()):
        raise SigVerifyError(
            "installer Authenticode signer certificate does not match the "
            "Ed25519-signed manifest"
        )


# ── Manifest + signature verification ─────────────────────────────

def verify_manifest(
    manifest_bytes: bytes,
    sig_envelope: bytes,
    trusted_pubkeys_pem: Optional[Iterable[str]] = None,
    *,
    allow_unsigned: bool = False,
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
        allow_unsigned: explicit development/test escape hatch. Production
            updater callers must leave this false so the Ed25519-authenticated
            manifest is required to bind the exact Authenticode signer
            certificate expected on the downloaded installer.

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
    authenticode_signer_sha256 = installer.get(
        "authenticode_signer_sha256"
    )
    if (
        not isinstance(filename, str)
        or not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
    ):
        raise SigVerifyError(f"manifest.installer.filename invalid: {filename!r}")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise SigVerifyError(f"manifest.installer.sha256 invalid: {sha256!r}")
    try:
        bytes.fromhex(sha256)
    except ValueError as e:
        raise SigVerifyError(f"manifest.installer.sha256 not hex: {e}") from e
    if not isinstance(size, int) or size <= 0 or size > 1024 * 1024 * 1024:  # 1 GB cap
        raise SigVerifyError(f"manifest.installer.size invalid: {size!r}")
    if authenticode_signer_sha256 is None and allow_unsigned:
        pass
    elif (
        not isinstance(authenticode_signer_sha256, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", authenticode_signer_sha256)
    ):
        raise SigVerifyError(
            "manifest.installer.authenticode_signer_sha256 must bind the "
            "SHA-256 fingerprint of the expected signer certificate"
        )

    return UpdateManifest(
        version=version,
        released_at=released_at if isinstance(released_at, str) else "",
        installer_filename=filename,
        installer_sha256=sha256.lower(),
        installer_size=size,
        authenticode_signer_sha256=(
            authenticode_signer_sha256.lower()
            if isinstance(authenticode_signer_sha256, str)
            else None
        ),
    )


def verify_manifest_and_enforce_monotonic(
    manifest_bytes: bytes,
    sig_envelope: bytes,
    trusted_pubkeys_pem: Optional[Iterable[str]] = None,
    *,
    installed_version: Optional[str] = None,
    expected_release_version: Optional[str] = None,
    expected_installer_filename: Optional[str] = None,
) -> UpdateManifest:
    """Verify signature, bind release metadata, then gate the version.

    Combines :func:`verify_manifest` with
    :func:`app.core.update_state.enforce_update_version` so the
    updater has a single call site for "is this manifest acceptable to
    act on." On any failure — bad sig, downgrade, ledger I/O error —
    the caller MUST NOT launch the installer.

    When supplied by the caller, ``expected_release_version`` and
    ``expected_installer_filename`` bind the authenticated manifest to the
    release selected by the API and the exact installer URL before the
    monotonic ledger is advanced. Version comparison for that binding is
    exact after stripping the conventional leading ``v``.

    Raises:
        SigVerifyError on signature/schema failure (re-raised from
            :func:`verify_manifest`).
        app.core.update_state.DowngradeRefusedError when the manifest's
            version is not strictly newer than the installed binary or is
            older than the authenticated version floor.
            Note: callers can choose to catch this specifically to log
            a louder "POSSIBLE ATTACK" event without conflating it with
            ordinary signature failures.
    """
    manifest = verify_manifest(manifest_bytes, sig_envelope, trusted_pubkeys_pem)

    if expected_release_version is not None:
        expected = expected_release_version.lstrip("vV").strip()
        actual = manifest.version.lstrip("vV").strip()
        if not expected or actual != expected:
            raise SigVerifyError(
                f"manifest version {manifest.version!r} does not match "
                f"selected release {expected_release_version!r}"
            )

    if expected_installer_filename is not None:
        if manifest.installer_filename.casefold() != expected_installer_filename.casefold():
            raise SigVerifyError(
                f"manifest installer {manifest.installer_filename!r} does not match "
                f"download target {expected_installer_filename!r}"
            )

    # Lazy import so the signature-verify codepath stays import-light
    # for unit tests that exercise verify_manifest in isolation.
    from app.core.update_state import enforce_update_version
    enforce_update_version(manifest.version, installed_version)
    return manifest


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
