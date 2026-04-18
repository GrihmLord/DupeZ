#!/usr/bin/env python
"""
sign-plugin.py — build and sign a DupeZ plugin bundle.

Usage
-----

One-time, at key rotation::

    python scripts/sign-plugin.py --gen-key plugin-priv.pem plugin-pub.pem

Then add ``plugin-pub.pem`` contents to
``app.plugins.signing.TRUSTED_PUBKEYS_PEM`` in a new client release.

Sign a plugin directory::

    python scripts/sign-plugin.py \\
        --sign \\
        --priv plugin-priv.pem \\
        --plugin-dir plugins/my_cool_plugin

This rewrites ``manifest.json`` in canonical form (fills in
``entry_sha384`` from the entry file contents) and emits
``manifest.json.sig`` alongside it.

Verify locally before shipping::

    python scripts/sign-plugin.py \\
        --verify \\
        --plugin-dir plugins/my_cool_plugin \\
        --pub plugin-pub.pem

This runs the exact same verification path the client will run at
load time, so any mistake (wrong key, stale hash, missing capability,
etc.) is caught before the plugin leaves the signing host.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Import shared primitives from the client library so the signer and
# verifier are guaranteed byte-compatible.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.plugins.signing import (  # noqa: E402
    PluginSigError,
    pubkey_fingerprint,
    sign_manifest,
    verify_plugin_manifest,
)


def gen_key(priv_path: Path, pub_path: Path) -> None:
    """Generate a fresh Ed25519 keypair for plugin signing."""
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
        pass
    pub_path.write_bytes(pub_pem)

    fp = pubkey_fingerprint(pub_pem.decode("utf-8")).hex()
    print("Generated Ed25519 plugin-signing keypair:")
    print(f"  private: {priv_path}  (chmod 0600)")
    print(f"  public:  {pub_path}")
    print(f"  pubkey fingerprint: {fp}")
    print()
    print("Next steps:")
    print("  1. Paste contents of plugin-pub.pem into")
    print("     app/plugins/signing.TRUSTED_PUBKEYS_PEM in a new client release.")
    print("  2. Ship that client release BEFORE signing any plugin with this key.")
    print("  3. Store plugin-priv.pem on an air-gapped host or HSM.")


def sign_cmd(priv_path: Path, plugin_dir: Path) -> None:
    """Sign a plugin directory in place."""
    sig_path = sign_manifest(str(priv_path), str(plugin_dir))
    print(f"Signed plugin '{plugin_dir.name}':")
    print(f"  manifest: {plugin_dir / 'manifest.json'}  (rewritten with entry_sha384)")
    print(f"  sig:      {sig_path}")
    # Self-verify against the freshly computed pubkey so we never ship a
    # sig that the client would reject.
    from cryptography.hazmat.primitives import serialization
    priv = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    verified = verify_plugin_manifest(
        str(plugin_dir / "manifest.json"),
        trusted_pubkeys_pem=[pub_pem],
    )
    print(f"Self-verify OK: {verified.name} v{verified.version} "
          f"[{verified.sig_state.value}] caps={sorted(verified.capabilities)}")


def verify_cmd(plugin_dir: Path, pub_path: Path) -> None:
    """Run the full client verification path against a signed bundle."""
    pub_pem = pub_path.read_text(encoding="utf-8")
    try:
        m = verify_plugin_manifest(
            str(plugin_dir / "manifest.json"),
            trusted_pubkeys_pem=[pub_pem],
        )
    except PluginSigError as e:
        print(f"VERIFY FAILED: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"Verify OK: {m.name} v{m.version} [{m.sig_state.value}]")
    print(f"  entry_sha384: {m.entry_sha384}")
    print(f"  capabilities: {sorted(m.capabilities)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gen-key", nargs=2, metavar=("PRIV", "PUB"),
                    help="generate a fresh Ed25519 keypair")
    ap.add_argument("--sign", action="store_true",
                    help="sign a plugin directory in place")
    ap.add_argument("--verify", action="store_true",
                    help="re-verify a signed plugin bundle")
    ap.add_argument("--priv", type=Path, help="Ed25519 PEM private key")
    ap.add_argument("--pub", type=Path, help="pubkey PEM (for --verify)")
    ap.add_argument("--plugin-dir", type=Path,
                    help="directory containing manifest.json")
    args = ap.parse_args()

    if args.gen_key:
        gen_key(Path(args.gen_key[0]), Path(args.gen_key[1]))
        return 0
    if args.sign:
        if not (args.priv and args.plugin_dir):
            ap.error("--sign requires --priv and --plugin-dir")
        sign_cmd(args.priv, args.plugin_dir)
        return 0
    if args.verify:
        if not (args.pub and args.plugin_dir):
            ap.error("--verify requires --pub and --plugin-dir")
        verify_cmd(args.plugin_dir, args.pub)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
