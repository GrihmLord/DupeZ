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

    1. ``manifest.json`` is a version-2 manifest that schema-validates
       and names an ``entry_point`` contained under the plugin directory.
    2. ``manifest.json.sig`` decodes to a 72-byte envelope whose 8-byte
       fingerprint matches a pinned pubkey in
       :data:`TRUSTED_PUBKEYS_PEM`.
    3. The Ed25519 signature verifies over the **exact** bytes of
       ``manifest.json`` on disk (no re-serialisation).
    4. The signed ``files`` inventory exactly matches every regular file
       in the plugin directory (other than the manifest and its signature),
       including each canonical relative path, byte size, and SHA-384.

The signer therefore commits to the metadata, entry path, Python helpers,
native modules, and resources as one immutable bundle.  Legacy manifests
that pin only ``entry_sha384`` are deliberately not promoted to VERIFIED:
they must be re-signed with the current tool.

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
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional

from app.core.update_state import _parse as _parse_semver

__all__ = [
    "MANIFEST_VERSION",
    "KNOWN_CAPABILITIES",
    "PLUGIN_SIG_ENVELOPE_SIZE",
    "PluginSigError",
    "PluginSigState",
    "SignedPluginFile",
    "SignedPluginManifest",
    "TRUSTED_PUBKEYS_PEM",
    "pubkey_fingerprint",
    "sign_manifest",
    "verify_plugin_manifest",
]


# ── Constants ─────────────────────────────────────────────────────

MANIFEST_VERSION = "2.0"
FINGERPRINT_SIZE = 8
SIGNATURE_SIZE = 64
PLUGIN_SIG_ENVELOPE_SIZE = FINGERPRINT_SIZE + SIGNATURE_SIZE
MAX_MANIFEST_BYTES = 65_536
MAX_ENTRY_BYTES = 10 * 1024 * 1024
MAX_PLUGIN_FILE_BYTES = 64 * 1024 * 1024
MAX_PLUGIN_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PLUGIN_FILES = 1_024
MAX_PLUGIN_PATH_CHARS = 512
_RESERVED_BUNDLE_PATHS = frozenset({"manifest.json", "manifest.json.sig"})

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
class SignedPluginFile:
    """One path authenticated by a version-2 plugin manifest."""

    path: str
    sha384: str
    size: int


@dataclass(frozen=True)
class SignedPluginManifest:
    """Parsed+verified plugin manifest with capability information."""

    name: str
    version: str
    description: str
    plugin_type: str
    entry_point: str
    entry_sha384: str
    files: tuple[SignedPluginFile, ...]
    manifest_sha384: str
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


def _hash_file(path: Path, *, max_bytes: int) -> tuple[str, int]:
    """Return the SHA-384 and byte size of *path* with a hard read cap."""
    h = hashlib.sha384()
    total = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise PluginSigError(
                    f"plugin file {path.name!r} exceeds {max_bytes} bytes"
                )
    return h.hexdigest(), total


def _sha384_file(path: Path, *, max_bytes: int = MAX_ENTRY_BYTES) -> str:
    """Return the SHA-384 hex of *path*, streaming to avoid RAM spikes."""
    digest, _ = _hash_file(path, max_bytes=max_bytes)
    return digest


def _is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows reparse point."""
    try:
        info = path.lstat()
    except OSError as e:
        raise PluginSigError(f"cannot inspect plugin path {path}: {e}") from e
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _validate_bundle_path(raw_path: object) -> str:
    """Validate and return a canonical, portable plugin-relative path."""
    if not isinstance(raw_path, str) or not raw_path:
        raise PluginSigError("manifest.files path must be a non-empty string")
    if len(raw_path) > MAX_PLUGIN_PATH_CHARS:
        raise PluginSigError(
            f"manifest.files path exceeds {MAX_PLUGIN_PATH_CHARS} characters"
        )
    if "\\" in raw_path or unicodedata.normalize("NFC", raw_path) != raw_path:
        raise PluginSigError(
            f"manifest.files path is not canonical POSIX NFC: {raw_path!r}"
        )
    posix_path = PurePosixPath(raw_path)
    if (
        posix_path.is_absolute()
        or raw_path != posix_path.as_posix()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise PluginSigError(f"manifest.files path is unsafe: {raw_path!r}")
    if raw_path.casefold() in _RESERVED_BUNDLE_PATHS:
        raise PluginSigError(f"manifest.files cannot contain reserved path {raw_path!r}")
    return raw_path


def _inventory_plugin_files(plugin_dir: Path) -> tuple[SignedPluginFile, ...]:
    """Hash every immutable file in *plugin_dir* using canonical paths."""
    if _is_reparse_point(plugin_dir):
        raise PluginSigError(f"plugin directory cannot be a reparse point: {plugin_dir}")

    records: list[SignedPluginFile] = []
    seen_casefold: set[str] = set()
    total_bytes = 0
    try:
        walker = os.walk(plugin_dir, topdown=True, followlinks=False)
        for current, dirnames, filenames in walker:
            current_path = Path(current)
            for dirname in dirnames:
                directory = current_path / dirname
                if _is_reparse_point(directory):
                    raise PluginSigError(
                        f"plugin bundle cannot contain linked directory: {directory}"
                    )
            for filename in filenames:
                path = current_path / filename
                relative = path.relative_to(plugin_dir).as_posix()
                if relative.casefold() in _RESERVED_BUNDLE_PATHS:
                    if _is_reparse_point(path):
                        raise PluginSigError(
                            f"plugin control file cannot be a link: {relative}"
                        )
                    continue
                relative = _validate_bundle_path(relative)
                if _is_reparse_point(path) or not path.is_file():
                    raise PluginSigError(
                        f"plugin bundle path must be a regular file: {relative}"
                    )
                if "__pycache__" in PurePosixPath(relative).parts or path.suffix.lower() in {
                    ".pyc",
                    ".pyo",
                }:
                    raise PluginSigError(
                        f"plugin bundle contains generated bytecode; remove {relative!r} "
                        "before signing"
                    )
                folded = relative.casefold()
                if folded in seen_casefold:
                    raise PluginSigError(
                        f"plugin paths collide case-insensitively: {relative!r}"
                    )
                seen_casefold.add(folded)
                digest, size = _hash_file(path, max_bytes=MAX_PLUGIN_FILE_BYTES)
                total_bytes += size
                if total_bytes > MAX_PLUGIN_TOTAL_BYTES:
                    raise PluginSigError(
                        f"plugin bundle exceeds {MAX_PLUGIN_TOTAL_BYTES} bytes"
                    )
                records.append(SignedPluginFile(relative, digest, size))
                if len(records) > MAX_PLUGIN_FILES:
                    raise PluginSigError(
                        f"plugin bundle exceeds {MAX_PLUGIN_FILES} files"
                    )
    except OSError as e:
        raise PluginSigError(f"cannot enumerate plugin bundle {plugin_dir}: {e}") from e

    records.sort(key=lambda item: item.path)
    return tuple(records)


def _parse_file_inventory(raw: object) -> tuple[SignedPluginFile, ...]:
    """Schema-check the signed version-2 file inventory."""
    if not isinstance(raw, list) or not raw:
        raise PluginSigError("manifest.files must be a non-empty list")
    if len(raw) > MAX_PLUGIN_FILES:
        raise PluginSigError(f"manifest.files exceeds {MAX_PLUGIN_FILES} entries")

    records: list[SignedPluginFile] = []
    seen_casefold: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != {"path", "sha384", "size"}:
            raise PluginSigError(
                f"manifest.files[{index}] must contain only path, sha384, and size"
            )
        path = _validate_bundle_path(item["path"])
        folded = path.casefold()
        if folded in seen_casefold:
            raise PluginSigError(f"manifest.files contains duplicate path {path!r}")
        seen_casefold.add(folded)
        digest = item["sha384"]
        size = item["size"]
        if not isinstance(digest, str) or len(digest) != 96:
            raise PluginSigError(
                f"manifest.files[{index}].sha384 must be 96 lowercase hex characters"
            )
        try:
            bytes.fromhex(digest)
        except ValueError as e:
            raise PluginSigError(
                f"manifest.files[{index}].sha384 is not hexadecimal"
            ) from e
        if digest != digest.lower():
            raise PluginSigError(
                f"manifest.files[{index}].sha384 must use lowercase hexadecimal"
            )
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PluginSigError(f"manifest.files[{index}].size must be a non-negative integer")
        if size > MAX_PLUGIN_FILE_BYTES:
            raise PluginSigError(
                f"manifest.files[{index}].size exceeds {MAX_PLUGIN_FILE_BYTES} bytes"
            )
        records.append(SignedPluginFile(path, digest, size))

    if records != sorted(records, key=lambda item: item.path):
        raise PluginSigError("manifest.files must be sorted by canonical path")
    if sum(record.size for record in records) > MAX_PLUGIN_TOTAL_BYTES:
        raise PluginSigError(f"manifest.files exceeds {MAX_PLUGIN_TOTAL_BYTES} bytes")
    return tuple(records)


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
    """Verify a plugin's manifest, signature, and complete file inventory.

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

    # 1. Read the raw manifest bytes (exact on-disk content -- these are signed).
    if not mpath.is_file():
        raise PluginSigError(f"manifest not found: {mpath}")
    if _is_reparse_point(mpath):
        raise PluginSigError("plugin manifest cannot be a symlink or reparse point")
    manifest_bytes = mpath.read_bytes()
    if not manifest_bytes or len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise PluginSigError(f"manifest size out of bounds: {len(manifest_bytes)}")
    manifest_sha384 = hashlib.sha384(manifest_bytes).hexdigest()

    # 2. Parse and bound the signed schema before doing expensive bundle I/O.
    try:
        data = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PluginSigError(f"manifest not valid UTF-8 JSON: {e}") from e
    if not isinstance(data, dict):
        raise PluginSigError("manifest root must be a JSON object")

    if "manifest_version" not in data and "entry_sha384" in data:
        raise PluginSigError(
            "legacy entry-only plugin manifest cannot be trusted; re-sign the "
            "complete bundle with the current scripts/sign-plugin.py"
        )
    required = {
        "manifest_version",
        "name",
        "version",
        "description",
        "type",
        "entry_point",
        "files",
    }
    missing = required - data.keys()
    if missing:
        raise PluginSigError(f"manifest missing fields: {sorted(missing)}")
    if data["manifest_version"] != MANIFEST_VERSION:
        raise PluginSigError(
            "unsupported plugin manifest version "
            f"{data['manifest_version']!r}; expected {MANIFEST_VERSION!r}"
        )

    name = data["name"]
    version = data["version"]
    description = data["description"]
    plugin_type = data["type"]
    entry_point = data["entry_point"]
    author = data.get("author", "Unknown")
    url = data.get("url", "")
    min_dupez_version = data.get("min_dupez_version", "4.0.0")
    deps_raw = data.get("dependencies", [])
    caps = _validate_capabilities(data.get("capabilities", []))
    signed_files = _parse_file_inventory(data["files"])

    for field, val in (("name", name), ("version", version),
                       ("description", description), ("type", plugin_type),
                       ("entry_point", entry_point)):
        if not isinstance(val, str) or not val:
            raise PluginSigError(f"manifest.{field} must be non-empty string")

    if _parse_semver(min_dupez_version) is None:
        raise PluginSigError(
            "manifest.min_dupez_version must be a strict SemVer string"
        )

    if not isinstance(deps_raw, list) or not all(isinstance(d, str) for d in deps_raw):
        raise PluginSigError("manifest.dependencies must be a list of strings")
    deps = tuple(deps_raw)

    # Path traversal guard on entry_point — same containment as loader.
    try:
        canonical_entry = _validate_bundle_path(entry_point)
    except PluginSigError as e:
        raise PluginSigError(f"manifest.entry_point is invalid: {e}") from e
    if canonical_entry != entry_point or os.path.isabs(entry_point):
        raise PluginSigError(f"manifest.entry_point suspicious: {entry_point!r}")
    signed_by_path = {record.path: record for record in signed_files}
    if entry_point not in signed_by_path:
        raise PluginSigError(
            f"manifest.entry_point {entry_point!r} is absent from manifest.files"
        )
    entry_record = signed_by_path[entry_point]
    if entry_record.size > MAX_ENTRY_BYTES:
        raise PluginSigError(
            f"plugin entry {entry_point!r} exceeds {MAX_ENTRY_BYTES} bytes"
        )

    # 3. Authenticate the manifest. Dev mode can classify a bundle as
    #    DEV_UNSIGNED, but never promotes it to VERIFIED.
    sig_state: PluginSigState
    if not sig_path.is_file():
        if _dev_mode_enabled():
            sig_state = PluginSigState.DEV_UNSIGNED
        else:
            raise PluginSigError(
                f"plugin {name!r} is unsigned and DUPEZ_PLUGIN_DEV_MODE is off -- "
                "refusing to load"
            )
    else:
        if _is_reparse_point(sig_path):
            raise PluginSigError("plugin signature cannot be a symlink or reparse point")
        sig_envelope = sig_path.read_bytes()
        if len(sig_envelope) != PLUGIN_SIG_ENVELOPE_SIZE:
            raise PluginSigError(
                f"plugin sig envelope wrong size: {len(sig_envelope)} "
                f"(expected {PLUGIN_SIG_ENVELOPE_SIZE})"
            )
        if not pinned:
            if _dev_mode_enabled():
                sig_state = PluginSigState.DEV_UNSIGNED
            else:
                raise PluginSigError(
                    "no pinned plugin pubkeys configured -- refusing signed-plugin "
                    "load. Populate TRUSTED_PUBKEYS_PEM in app.plugins.signing or "
                    "set DUPEZ_PLUGIN_DEV_MODE=1 for local development."
                )
        else:
            fingerprint = bytes(sig_envelope[:FINGERPRINT_SIZE])
            signature = bytes(sig_envelope[FINGERPRINT_SIZE:])
            matched_pem: Optional[str] = None
            for pem in pinned:
                if pubkey_fingerprint(pem) == fingerprint:
                    matched_pem = pem
                    break
            if matched_pem is None:
                raise PluginSigError(
                    f"plugin {name!r} signature fingerprint unknown -- signed by "
                    "an untrusted key or the client needs newer pinned keys"
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
            sig_state = PluginSigState.VERIFIED

    # 4. Compare the authenticated inventory with a fresh traversal. This
    #    rejects modified, missing, and newly-added helpers/resources alike.
    actual_files = _inventory_plugin_files(plugin_dir)
    if actual_files != signed_files:
        expected = {record.path: record for record in signed_files}
        actual = {record.path: record for record in actual_files}
        missing_paths = sorted(expected.keys() - actual.keys())
        unexpected_paths = sorted(actual.keys() - expected.keys())
        changed_paths = sorted(
            path
            for path in expected.keys() & actual.keys()
            if expected[path] != actual[path]
        )
        details = []
        if missing_paths:
            details.append(f"missing={missing_paths}")
        if unexpected_paths:
            details.append(f"unexpected={unexpected_paths}")
        if changed_paths:
            details.append(f"changed={changed_paths}")
        raise PluginSigError(
            "plugin bundle inventory mismatch: " + "; ".join(details)
        )

    return SignedPluginManifest(
        name=name, version=version, description=description,
        plugin_type=plugin_type, entry_point=entry_point,
        entry_sha384=entry_record.sha384,
        files=signed_files,
        manifest_sha384=manifest_sha384,
        capabilities=caps, author=author, url=url,
        min_dupez_version=min_dupez_version, dependencies=deps,
        sig_state=sig_state,
    )


# ── Signer-side (used by scripts/sign-plugin.py) ─────────────────

def sign_manifest(
    priv_pem_path: str,
    plugin_dir: str,
    out_sig_path: Optional[str] = None,
) -> str:
    """Sign a plugin's manifest.json in-place and emit manifest.json.sig.

    Preconditions:
        * ``<plugin_dir>/manifest.json`` exists with the plugin metadata.
        * The directory contains only immutable files intended for the
          distributed plugin (no symlinks, reparse points, or bytecode cache).

    The function upgrades legacy metadata to manifest v2, removes the obsolete
    entry-only hash, inventories the complete directory, and emits canonical
    JSON before signing it.

    Returns:
        Path to the written ``.sig`` file.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    pdir = Path(plugin_dir)
    mpath = pdir / "manifest.json"
    if not mpath.is_file():
        raise FileNotFoundError(f"manifest missing: {mpath}")
    if _is_reparse_point(mpath):
        raise PluginSigError("plugin manifest cannot be a symlink or reparse point")

    private_path = Path(priv_pem_path)
    try:
        private_path.resolve().relative_to(pdir.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("plugin private signing key must not be inside the bundle")

    priv_pem = private_path.read_bytes()
    priv = serialization.load_pem_private_key(priv_pem, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise TypeError(f"private key not Ed25519 (got {type(priv).__name__})")

    manifest_input = mpath.read_bytes()
    if not manifest_input or len(manifest_input) > MAX_MANIFEST_BYTES:
        raise PluginSigError(f"manifest size out of bounds: {len(manifest_input)}")
    data = json.loads(manifest_input.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")

    entry_point = data.get("entry_point")
    if not isinstance(entry_point, str) or not entry_point:
        raise ValueError("manifest.entry_point missing")
    try:
        entry_point = _validate_bundle_path(entry_point)
    except PluginSigError as e:
        raise ValueError(f"manifest.entry_point invalid: {e}") from e

    inventory = _inventory_plugin_files(pdir)
    by_path = {record.path: record for record in inventory}
    if entry_point not in by_path:
        raise FileNotFoundError(f"entry_point missing from plugin bundle: {entry_point}")
    if by_path[entry_point].size > MAX_ENTRY_BYTES:
        raise PluginSigError(
            f"plugin entry {entry_point!r} exceeds {MAX_ENTRY_BYTES} bytes"
        )

    data["manifest_version"] = MANIFEST_VERSION
    data.pop("entry_sha384", None)
    data["files"] = [
        {"path": record.path, "sha384": record.sha384, "size": record.size}
        for record in inventory
    ]

    # Canonical JSON -- the verifier authenticates these exact bytes.
    manifest_bytes = json.dumps(
        data, separators=(",", ":"), sort_keys=True, ensure_ascii=True,
    ).encode("utf-8")
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise PluginSigError(
            f"canonical manifest exceeds {MAX_MANIFEST_BYTES} bytes"
        )
    mpath.write_bytes(manifest_bytes)

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

    # Catch a bundle that changed while it was being signed. The CLI also runs
    # full public-key verification, but callers of this library get this guard.
    if _inventory_plugin_files(pdir) != inventory:
        raise PluginSigError("plugin bundle changed while it was being signed")
    return str(out)
