#!/usr/bin/env python
"""
sign-release.py — build and sign a DupeZ update manifest.

This is the offline signing tool that MUST run on an air-gapped or
otherwise hardened machine holding the Ed25519 release private key.
It produces the two sidecar artifacts the client updater verifies:

    DupeZ_Setup.exe.manifest.json
    DupeZ_Setup.exe.manifest.sig

Usage
-----

Generate a new keypair (one-time, at key rotation):

    python scripts/sign-release.py --gen-key priv.pem pub.pem

Then add the pub.pem contents to
``app/core/update_verify.TRUSTED_PUBKEYS_PEM`` in a new client
release. Only after clients carrying the new pubkey have rolled out
should signed releases using its private key ship. See the module
docstring in ``app/core/update_verify.py`` for the rotation sequence.

Sign an installer for release:

    python scripts/sign-release.py \\
        --sign \\
        --priv priv.pem \\
        --installer dist/DupeZ_Setup.exe \\
        --version 5.8.0

This writes:

    dist/DupeZ_Setup.exe.manifest.json
    dist/DupeZ_Setup.exe.manifest.sig

Both sidecar files MUST be uploaded alongside the installer as
release assets so that clients fetching ``DupeZ_Setup.exe`` can also
fetch ``DupeZ_Setup.exe.manifest.json`` and ``DupeZ_Setup.exe.manifest.sig``.

Verify locally before upload:

    python scripts/sign-release.py \\
        --verify \\
        --installer dist/DupeZ_Setup.exe \\
        --pub pub.pem

This re-runs the same verification path the client will run, so any
mistake (wrong installer, wrong key, stale manifest) is caught
before it ships.

Threat model
------------

The private key NEVER leaves the signing host. Never commit it.
Never upload it. If it leaks, the compromise window is:

    1. Rotate immediately — generate a new keypair, ship a client
       release that carries BOTH the old and new pubkey, then (after
       rollout) ship another client release that drops the old
       pubkey.
    2. Publish a CRL-style advisory pointing users at the new
       release so old clients upgrade before the old pubkey is
       dropped.

Until the rotation completes, an attacker with the leaked key can
sign updates that every old-client will accept — the pinning in the
client is ONE layer of defense, not a silver bullet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make repo root importable so we share constants with the client.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.update_verify import (  # noqa: E402
    MANIFEST_SCHEMA,
    SIGNATURE_SIZE,
    SIG_ENVELOPE_SIZE,
    pubkey_fingerprint,
    verify_manifest,
    verify_installer_sha256,
)


# ── Keypair generation ────────────────────────────────────────────

def gen_key(priv_path: Path, pub_path: Path) -> None:
    """Generate a fresh Ed25519 keypair and write PEMs to disk.

    The private key is written with 0600 permissions on POSIX. On
    Windows the caller is responsible for ACLing the directory
    (e.g. "everyone except signer: deny" on the containing folder).
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_path.write_bytes(priv_pem)
    try:
        os.chmod(priv_path, 0o600)
    except OSError:
        pass  # Windows — caller must lock via ACL
    pub_path.write_bytes(pub_pem)

    fp = pubkey_fingerprint(pub_pem.decode("utf-8")).hex()
    print("Generated Ed25519 keypair:")
    print(f"  private: {priv_path}  (chmod 0600)")
    print(f"  public:  {pub_path}")
    print(f"  pubkey fingerprint (bundle in TRUSTED_PUBKEYS_PEM): {fp}")
    print()
    print("Next steps:")
    print(f"  1. Paste the contents of {pub_path.name} into")
    print("     app/core/update_verify.TRUSTED_PUBKEYS_PEM in a new client release.")
    print(f"  2. Ship that client release BEFORE signing any update with {priv_path.name}.")
    print(f"  3. Store {priv_path.name} on an air-gapped host or HSM.")


# ── Manifest build + sign ─────────────────────────────────────────

def _hash_file(path: Path) -> tuple[str, int]:
    """Return (sha256_hex, size_bytes) streaming the file."""
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def sign_release(
    priv_path: Path,
    installer_path: Path,
    version: str,
    out_manifest: Path,
    out_sig: Path,
) -> None:
    """Build, serialize, and sign an update manifest for *installer_path*."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not installer_path.is_file():
        raise FileNotFoundError(f"installer not found: {installer_path}")
    if not priv_path.is_file():
        raise FileNotFoundError(f"private key not found: {priv_path}")

    priv_pem = priv_path.read_bytes()
    priv = serialization.load_pem_private_key(priv_pem, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise TypeError(f"private key is not Ed25519 (got {type(priv).__name__})")

    # Derive the pubkey PEM that will be embedded in the fingerprint.
    # We do this here rather than trust a sidecar pub.pem so that the
    # fingerprint in the signature envelope is provably matched to the
    # actual signing key — not a pub.pem someone might have swapped.
    pub_pem_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_pem = pub_pem_bytes.decode("utf-8")

    sha256_hex, size_bytes = _hash_file(installer_path)

    manifest_obj = {
        "schema": MANIFEST_SCHEMA,
        "version": version,
        "released_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "installer": {
            "filename": installer_path.name,
            "sha256": sha256_hex,
            "size": size_bytes,
        },
    }
    # Canonical JSON: sorted keys, no trailing newline, UTF-8.
    # The client verifies the signature over these EXACT bytes, so we
    # write them once and never re-serialize.
    manifest_bytes = json.dumps(
        manifest_obj,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    ).encode("utf-8")

    signature = priv.sign(manifest_bytes)
    if len(signature) != SIGNATURE_SIZE:
        raise RuntimeError(
            f"Ed25519 produced unexpected signature size: {len(signature)}"
        )

    fingerprint = pubkey_fingerprint(pub_pem)
    envelope = fingerprint + signature
    if len(envelope) != SIG_ENVELOPE_SIZE:
        raise RuntimeError(
            f"envelope size mismatch: {len(envelope)} (expected {SIG_ENVELOPE_SIZE})"
        )

    out_manifest.write_bytes(manifest_bytes)
    out_sig.write_bytes(envelope)

    # Round-trip self-check — if the client library can't verify our
    # own output, something is wrong with the signer.
    parsed = verify_manifest(manifest_bytes, envelope, trusted_pubkeys_pem=[pub_pem])
    verify_installer_sha256(str(installer_path), parsed)

    print(f"Signed manifest written: {out_manifest}")
    print(f"Signature written:       {out_sig}")
    print(f"  version:     {parsed.version}")
    print(f"  installer:   {parsed.installer_filename}")
    print(f"  sha256:      {parsed.installer_sha256}")
    print(f"  size:        {parsed.installer_size}")
    print(f"  fingerprint: {fingerprint.hex()}")
    print()
    print("Self-verify: OK. Ready to upload to the release alongside the installer.")


# ── Verify (dry-run of the client path) ──────────────────────────

def verify_release(installer_path: Path, pub_path: Path) -> None:
    """Run the full client verification path against on-disk artifacts."""
    manifest_path = installer_path.with_name(installer_path.name + ".manifest.json")
    sig_path = installer_path.with_name(installer_path.name + ".manifest.sig")
    for p in (installer_path, manifest_path, sig_path, pub_path):
        if not p.is_file():
            raise FileNotFoundError(f"missing: {p}")

    pub_pem = pub_path.read_text(encoding="utf-8")
    manifest_bytes = manifest_path.read_bytes()
    sig_bytes = sig_path.read_bytes()

    parsed = verify_manifest(manifest_bytes, sig_bytes, trusted_pubkeys_pem=[pub_pem])
    verify_installer_sha256(str(installer_path), parsed)

    print("Release verified OK:")
    print(f"  installer:  {installer_path}")
    print(f"  version:    {parsed.version}")
    print(f"  released:   {parsed.released_at}")
    print(f"  sha256:     {parsed.installer_sha256}")
    print(f"  size:       {parsed.installer_size}")


# ── CLI ──────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])

    # --gen-key keeps positional style consistent with the original
    # docstring reference but we also expose a subcommand.
    ap.add_argument("--gen-key", nargs=2, metavar=("PRIV", "PUB"),
                    help="generate a new Ed25519 keypair")

    ap.add_argument("--sign", action="store_true",
                    help="sign an installer (requires --priv, --installer, --version)")
    ap.add_argument("--priv", type=Path, help="Ed25519 PEM private key")
    ap.add_argument("--installer", type=Path, help="path to DupeZ_Setup.exe")
    ap.add_argument("--version", help="semver string, e.g. 5.8.0")
    ap.add_argument("--out-manifest", type=Path, default=None,
                    help="override output manifest path")
    ap.add_argument("--out-sig", type=Path, default=None,
                    help="override output signature path")

    ap.add_argument("--verify", action="store_true",
                    help="re-verify an already-signed installer using a pubkey PEM")
    ap.add_argument("--pub", type=Path, help="pubkey PEM (for --verify)")

    args = ap.parse_args()

    if args.gen_key:
        priv = Path(args.gen_key[0])
        pub = Path(args.gen_key[1])
        gen_key(priv, pub)
        return 0

    if args.sign:
        if not (args.priv and args.installer and args.version):
            ap.error("--sign requires --priv, --installer, --version")
        out_manifest = args.out_manifest or args.installer.with_name(
            args.installer.name + ".manifest.json"
        )
        out_sig = args.out_sig or args.installer.with_name(
            args.installer.name + ".manifest.sig"
        )
        sign_release(args.priv, args.installer, args.version, out_manifest, out_sig)
        return 0

    if args.verify:
        if not (args.installer and args.pub):
            ap.error("--verify requires --installer and --pub")
        verify_release(args.installer, args.pub)
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
