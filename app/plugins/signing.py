"""
Plugin manifest signing and verification for DupeZ.

Threat model
------------
Plugins execute with the full privileges of the DupeZ process (High-IL
when launched via the elevation-compat variant). An unsigned plugin
loader is equivalent to an RCE primitive for anyone who can drop a
folder into ``plugins/``:

  * shared-machine attacker,
  * malware-in-downloads (user double-clicks a ZIP),
  * a supply-chain compromise of a third-party plugin,
  * a malicious plugin bundle masquerading as a legitimate one.

Without signature verification, the existing loader
(``app/plugins/loader.py``) just ``spec.loader.exec_module(...)``s
whatever Python lives at ``plugins/<name>/<entry>``. This module
closes that gap.

Guarantees
----------
A plugin is accepted ONLY IF:

    1. ``manifest.json`` parses, schema-validates, and names an
       ``entry_point`` contained under the plugin directory.
    2. ``manifest.json.sig`` decodes to a 72-byte envelope whose
       8-byte fingerprint matches a pinned pubkey in
       :data:`TRUSTED_PUBKEYS_PEM`.
    3. The Ed25519 signature verifies over the **exact** bytes of
       ``manifest.json`` on disk (no re-serialisation).
    4. The manifest carries an ``entry_sha384`` field whose value
       matches the SHA-384 of the resolved entry file.

The signer thus commits to BOTH the metadata (capabilities, entry
path, version) AND the code, and the client rejects anything that
deviates from either.

Dev-mode override
-----------------
If the environment variable ``DUPEZ_PLUGIN_DEV_MODE`` is set to a
truthy value, the loader accepts unsigned plugins but:

    * emits a ``plugin_unsigned_loaded`` audit event,
    * marks the :class:`PluginSigState` as ``DEV_UNSIGNED``,
    * the status is surfaced to the UI so the user can see it.

Production builds MUST NOT set that env var. ``scripts/sign-plugin.py``
is the offline signer.

Key rotation follows the same pattern as update signing (see
``app/core/update_verify.py``) — add the new pubkey, ship a client
release, then drop the old pubkey in a later release.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

__all__ = [
    "MANIFEST_VERSION",
    "KNOWN_CAPABILITIES",
    "PLUGIN_SIG_ENVELOPE_SIZE",
    "PluginSigError",
    "PluginSigState",
    "SignedPluginManifest",
    "TRUSTED_PUBKEYS_PEM",
    "pubkey_fingerprint",
    "sign_manifest",
    "verify_plugin_manifest",
]


# ── Constants ─────────────────────────────────────────────────────

MANIFEST_VERSION = "1.0"
FINGERPRINT_SIZE = 8
SIGNATURE_SIZE = 64
PLUGIN_SIG_ENVELOPE_SIZE = FINGERPRINT_SIZE + SIGNATURE_SIZE
MAX_MANIFEST_BYTES = 65_536
MAX_ENTRY_BYTES = 10 * 1024 * 1024  # 10 MB per plugin entry — paranoia cap

# Capability vocabulary the loader understands. A plugin MUST declare
# every capability it requires; the loader's sandbox enforces the
# declaration at runtime via a sys.addaudithook() mediator.
KNOWN_CAPABILITIES = frozenset({
    "disruption.raw_packet",   # WinDivert / raw socket send
    "network.scan",            # ARP/ICMP/port discovery
    "network.http",            # outbound HTTP(S)
    "fs.read_user_data",       # read ~/AppData, settings, etc.
    "fs.write_user_data",      # write ~/AppData, settings, etc.
    "process.spawn",           # subprocess.Popen / os.system
    "ui.panel",                # contribute a Qt panel
    "hotkey.global",           # register a Win32 global hotkey
})


# ── Pinned pubkeys (bundled at build time) ───────────────────────
#
# Populate via ``python scripts/sign-plugin.py --gen-key priv.pem pub.pem``
# and paste pub.pem into this list. The private key stays offline.
# When empty AND dev mode is off, the loader refuses every plugin —
# which is the correct default on first boot before a plugin
# ecosystem exists.
TRUSTED_PUBKEYS_PEM: List[str] = [
    # "-----BEGIN PUBLIC KEY-----\n"
    # "MCowBQYDK2VwAyEA<...base64...>\n"
    # "-----END PUBLIC KEY-----\n",
]


# ── Errors + state ───────────────────────────────────────────────

class PluginSigError(ValueError):
    """Raised when a plugin fails signature or integrity verification.

    Callers MUST NOT load the plugin on any :class:`PluginSigError` —
    the plugin bundle is considered hostile.
    """


class PluginSigState(enum.Enum):
    """Verification result the loader attaches to every plugin it sees."""

    VERIFIED = "verified"           # signature good, entry hash good
    DEV_UNSIGNED = "dev_unsigned"   # unsigned but DUPEZ_PLUGIN_DEV_MODE
    REJECTED = "rejected"           # failed verification; DO NOT LOAD


@dataclass(frozen=True)
class SignedPluginManifest:
    """Parsed+verified plugin manifest with capability information."""

    name: str
    version: str
    description: str
    plugin_type: str
    entry_point: str
    entry_sha384: str
    capabilities: frozenset
    author: str
    url: str
    min_dupez_version: str
    dependencies: tuple
    sig_state: PluginSigState


# ── Helpers ──────────────────────────────────────────────────────

def pubkey_fingerprint(pubkey_pem: str) -> bytes:
    """Return the 8-byte fingerprint of a PEM-encoded pubkey."""
    if not isinstance(pubkey_pem, str):
        raise TypeError("pubkey_pem must be a PEM string")
    return hashlib.sha256(pubkey_pem.encode("utf-8")).digest()[:FINGERPRINT_SIZE]


def _sha384_file(path: Path) -> str:
    """Return the SHA-384 hex of *path*, streaming to avoid RAM spikes."""
    h = hashlib.sha384()
    total = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
            if total > MAX_ENTRY_BYTES:
                raise PluginSigError(
                    f"plugin entry {path.name} exceeds {MAX_ENTRY_BYTES} bytes"
                )
    return h.hexdigest()


def _load_ed25519_pubkey(pem: str):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    key = load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise PluginSigError(
            f"pinned key is not Ed25519 (got {type(key).__name__})"
        )
    return key


def _dev_mode_enabled() -> bool:
    """Return True if the dev-mode override env var is set."""
    val = os.environ.get("DUPEZ_PLUGIN_DEV_MODE", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


# ── Capability validation ────────────────────────────────────────

def _validate_capabilities(raw: object) -> frozenset:
    """Parse and validate the manifest.capabilities list."""
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise PluginSigError("manifest.capabilities must be a list of strings")
    out = set()
    for c in raw:
        if not isinstance(c, str):
            raise PluginSigError(
                f"manifest.capabilities entry must be string, got {type(c).__name__}"
            )
        if c not in KNOWN_CAPABILITIES:
            raise PluginSigError(
                f"manifest declares unknown capability {c!r}. "
                f"Known capabilities: {sorted(KNOWN_CAPABILITIES)}"
            )
        out.add(c)
    return frozenset(out)


# ── Verification entrypoint ──────────────────────────────────────

def verify_plugin_manifest(
    manifest_path: str,
    trusted_pubkeys_pem: Optional[Iterable[str]] = None,
) -> SignedPluginManifest:
    """Verify a plugin's manifest + signature + entry-point hash.

    Args:
        manifest_path: absolute path to ``<plugin_dir>/manifest.json``.
        trusted_pubkeys_pem: override for testing; defaults to the
            module-level :data:`TRUSTED_PUBKEYS_PEM`.

    Returns:
        A :class:`SignedPluginManifest` with sig_state set to
        :attr:`PluginSigState.VERIFIED` or
        :attr:`PluginSigState.DEV_UNSIGNED`.

    Raises:
        PluginSigError on any verification failure.
    """
    if trusted_pubkeys_pem is None:
        trusted_pubkeys_pem = TRUSTED_PUBKEYS_PEM
    pinned = list(trusted_pubkeys_pem)

    mpath = Path(manifest_path)
    plugin_dir = mpath.parent
    sig_path = mpath.with_suffix(mpath.suffix + ".sig")

    # 1. Read the raw manifest bytes (exact on-disk content — we sign over these).
    if not mpath.is_file():
        raise PluginSigError(f"manifest not found: {mpath}")
    manifest_bytes = mpath.read_bytes()
    if not manifest_bytes or len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise PluginSigError(f"manifest size out of bounds: {len(manifest_bytes)}")

    # 2. Parse + schema-validate the manifest BEFORE signature check so a
    #    malformed manifest produces a clean error, not a "bad sig".
    try:
        data = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PluginSigError(f"manifest not valid UTF-8 JSON: {e}") from e
    if not isinstance(data, dict):
        raise PluginSigError("manifest root must be a JSON object")

    required = {"name", "version", "description", "type",
                "entry_point", "entry_sha384"}
    missing = required - data.keys()
    if missing:
        raise PluginSigError(f"manifest missing fields: {sorted(missing)}")

    name = data["name"]
    version = data["version"]
    description = data["description"]
    plugin_type = data["type"]
    entry_point = data["entry_point"]
    entry_sha384 = data["entry_sha384"]
    author = data.get("author", "Unknown")
    url = data.get("url", "")
    min_dupez_version = data.get("min_dupez_version", "4.0.0")
    deps_raw = data.get("dependencies", [])
    caps = _validate_capabilities(data.get("capabilities", []))

    for field, val in (("name", name), ("version", version),
                       ("description", description), ("type", plugin_type),
                       ("entry_point", entry_point), ("entry_sha384", entry_sha384)):
        if not isinstance(val, str) or not val:
            raise PluginSigError(f"manifest.{field} must be non-empty string")

    if not isinstance(deps_raw, list) or not all(isinstance(d, str) for d in deps_raw):
        raise PluginSigError("manifest.dependencies must be a list of strings")
    deps = tuple(deps_raw)

    if len(entry_sha384) != 96:
        raise PluginSigError(f"manifest.entry_sha384 must be 96 hex chars, got {len(entry_sha384)}")
    try:
        bytes.fromhex(entry_sha384)
    except ValueError as e:
        raise PluginSigError(f"manifest.entry_sha384 not hex: {e}") from e

    # Path traversal guard on entry_point — same containment as loader.
    if ".." in entry_point or os.path.isabs(entry_point):
        raise PluginSigError(f"manifest.entry_point suspicious: {entry_point!r}")
    entry_file = plugin_dir / entry_point
    real_entry = Path(os.path.realpath(entry_file))
    real_dir = Path(os.path.realpath(plugin_dir))
    try:
        real_entry.relative_to(real_dir)
    except ValueError as e:
        raise PluginSigError(
            f"manifest.entry_point escapes plugin dir: {entry_point!r}"
        ) from e
    if not real_entry.is_file():
        raise PluginSigError(f"entry_point does not exist: {entry_point}")

    # 3. Entry-file integrity — HARD even in dev mode. This catches a
    #    hand-edited `.py` inside a signed plugin bundle.
    actual_entry_hash = _sha384_file(real_entry)
    if actual_entry_hash != entry_sha384.lower():
        raise PluginSigError(
            f"entry_point hash mismatch for {name}: "
            f"manifest={entry_sha384[:12]}... disk={actual_entry_hash[:12]}..."
        )

    # 4. Signature check.
    if not sig_path.is_file():
        if _dev_mode_enabled():
            return SignedPluginManifest(
                name=name, version=version, description=description,
                plugin_type=plugin_type, entry_point=entry_point,
                entry_sha384=actual_entry_hash,
                capabilities=caps, author=author, url=url,
                min_dupez_version=min_dupez_version, dependencies=deps,
                sig_state=PluginSigState.DEV_UNSIGNED,
            )
        raise PluginSigError(
            f"plugin {name!r} is unsigned and DUPEZ_PLUGIN_DEV_MODE is off — "
            f"refusing to load"
        )

    sig_envelope = sig_path.read_bytes()
    if len(sig_envelope) != PLUGIN_SIG_ENVELOPE_SIZE:
        raise PluginSigError(
            f"plugin sig envelope wrong size: {len(sig_envelope)} "
            f"(expected {PLUGIN_SIG_ENVELOPE_SIZE})"
        )

    if not pinned:
        if _dev_mode_enabled():
            # Dev mode: accept as unsigned even though a sig file exists,
            # because we have no pinned key to verify against.
            return SignedPluginManifest(
                name=name, version=version, description=description,
                plugin_type=plugin_type, entry_point=entry_point,
                entry_sha384=actual_entry_hash,
                capabilities=caps, author=author, url=url,
                min_dupez_version=min_dupez_version, dependencies=deps,
                sig_state=PluginSigState.DEV_UNSIGNED,
            )
        raise PluginSigError(
            "no pinned plugin pubkeys configured — refusing signed-plugin load. "
            "Populate TRUSTED_PUBKEYS_PEM in app.plugins.signing or set "
            "DUPEZ_PLUGIN_DEV_MODE=1 for local development."
        )

    fingerprint = bytes(sig_envelope[:FINGERPRINT_SIZE])
    signature = bytes(sig_envelope[FINGERPRINT_SIZE:])

    matched_pem: Optional[str] = None
    for pem in pinned:
        if pubkey_fingerprint(pem) == fingerprint:
            matched_pem = pem
            break
    if matched_pem is None:
        raise PluginSigError(
            f"plugin {name!r} signature fingerprint unknown — signed by an "
            f"untrusted key or client needs newer TRUSTED_PUBKEYS_PEM"
        )

    try:
        from cryptography.exceptions import InvalidSignature
    except ImportError as e:  # pragma: no cover
        raise PluginSigError(f"cryptography library unavailable: {e}") from e

    pubkey = _load_ed25519_pubkey(matched_pem)
    try:
        pubkey.verify(signature, manifest_bytes)
    except InvalidSignature as e:
        raise PluginSigError(
            f"plugin {name!r}: Ed25519 signature invalid: {e}"
        ) from e

    return SignedPluginManifest(
        name=name, version=version, description=description,
        plugin_type=plugin_type, entry_point=entry_point,
        entry_sha384=actual_entry_hash,
        capabilities=caps, author=author, url=url,
        min_dupez_version=min_dupez_version, dependencies=deps,
        sig_state=PluginSigState.VERIFIED,
    )


# ── Signer-side (used by scripts/sign-plugin.py) ─────────────────

def sign_manifest(
    priv_pem_path: str,
    plugin_dir: str,
    out_sig_path: Optional[str] = None,
) -> str:
    """Sign a plugin's manifest.json in-place and emit manifest.json.sig.

    Preconditions:
        * ``<plugin_dir>/manifest.json`` exists with all required fields
          EXCEPT ``entry_sha384`` — which this function fills in by
          hashing the real on-disk entry file.

    Returns:
        Path to the written ``.sig`` file.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    pdir = Path(plugin_dir)
    mpath = pdir / "manifest.json"
    if not mpath.is_file():
        raise FileNotFoundError(f"manifest missing: {mpath}")

    data = json.loads(mpath.read_text(encoding="utf-8"))

    entry_point = data.get("entry_point")
    if not isinstance(entry_point, str) or not entry_point:
        raise ValueError("manifest.entry_point missing")
    entry_file = pdir / entry_point
    if not entry_file.is_file():
        raise FileNotFoundError(f"entry_point missing: {entry_file}")
    data["entry_sha384"] = _sha384_file(entry_file)

    # Canonical JSON — the verifier re-reads these exact bytes.
    manifest_bytes = json.dumps(
        data, separators=(",", ":"), sort_keys=True, ensure_ascii=True,
    ).encode("utf-8")
    mpath.write_bytes(manifest_bytes)

    priv_pem = Path(priv_pem_path).read_bytes()
    priv = serialization.load_pem_private_key(priv_pem, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise TypeError(f"private key not Ed25519 (got {type(priv).__name__})")

    signature = priv.sign(manifest_bytes)
    if len(signature) != SIGNATURE_SIZE:
        raise RuntimeError(f"signature wrong size: {len(signature)}")

    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    envelope = pubkey_fingerprint(pub_pem) + signature
    if len(envelope) != PLUGIN_SIG_ENVELOPE_SIZE:
        raise RuntimeError(f"envelope wrong size: {len(envelope)}")

    out = Path(out_sig_path) if out_sig_path else mpath.with_suffix(mpath.suffix + ".sig")
    out.write_bytes(envelope)
    return str(out)
