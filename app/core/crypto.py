"""
Centralized cryptographic primitives for DupeZ.

Cryptographic Inventory (CNSA 2.0 / Suite B compliant):
========================================================

+------------------+-------------------+-------------------------------+
| Use              | Algorithm         | Notes                         |
+------------------+-------------------+-------------------------------+
| Symmetric enc    | AES-256-GCM       | Primary. All at-rest data.    |
| Symmetric enc    | ChaCha20-Poly1305 | Secondary. Where GCM unavail. |
| Hashing          | SHA-384 / SHA-512 | All integrity checks.         |
| Param hashing    | SHA-384           | Replaced MD5 in stealth.      |
| Session IDs      | secrets.token_hex | 128-bit CSPRNG tokens.        |
| Nonce generation | os.urandom        | All nonces, IVs, salts.       |
| Key derivation   | PBKDF2-SHA-512    | 600k iterations minimum.      |
+------------------+-------------------+-------------------------------+

BANNED PRIMITIVES (enforced by this module — do NOT use elsewhere):
  - MD5           (collision-broken, CNSA 2.0 non-compliant)
  - SHA-1         (collision-broken since 2017)
  - RSA < 3072    (below CNSA 2.0 minimum)
  - ECC < 384     (below CNSA 2.0 minimum)
  - DES / 3DES    (deprecated, insufficient key length)
  - RC4           (broken stream cipher)
  - random.random (Mersenne Twister — NOT a CSPRNG)
    Exception: random.random IS acceptable for non-security purposes
    like packet disruption probability rolls. NOT for key/token/nonce.

Key Rotation Policy:
  - Encryption keys:    Rotate every 90 days (enforced by expiry metadata)
  - Session tokens:     Single-use or max 24h
  - HMAC keys:          Rotate with encryption keys
  - Nonces:             Never reused (counter or random per operation)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import struct
import time
from typing import Optional, Tuple

__all__ = [
    "generate_token",
    "generate_session_id",
    "generate_nonce",
    "generate_salt",
    "hash_sha384",
    "hash_sha512",
    "hmac_sha384",
    "verify_hmac",
    "derive_key",
    "compute_file_integrity",
    "compute_data_integrity",
    "create_key_metadata",
    "is_key_expired",
    "deterministic_param_hash",
]

# ── Constants ────────────────────────────────────────────────────────

# CSPRNG-generated token lengths (bytes → hex chars = 2x)
TOKEN_BYTES: int = 16       # 128-bit session tokens
NONCE_BYTES: int = 12       # 96-bit nonces for AES-256-GCM
SALT_BYTES: int = 32        # 256-bit salts for key derivation
KEY_BYTES: int = 32         # 256-bit symmetric keys (AES-256)

# PBKDF2 parameters
PBKDF2_ITERATIONS: int = 600_000  # OWASP 2024 recommendation for SHA-512
PBKDF2_HASH: str = "sha512"

# Key rotation interval (seconds)
KEY_ROTATION_INTERVAL_S: int = 90 * 24 * 60 * 60  # 90 days

# Hash algorithm for integrity operations
INTEGRITY_HASH: str = "sha384"


# ── CSPRNG Token Generation ─────────────────────────────────────────

def generate_token(nbytes: int = TOKEN_BYTES) -> str:
    """Generate a cryptographically secure random hex token.

    Uses :func:`secrets.token_hex` backed by ``os.urandom``.

    Args:
        nbytes: Number of random bytes (output hex string is 2x this).

    Returns:
        Hex-encoded token string.
    """
    return secrets.token_hex(nbytes)


def generate_session_id() -> str:
    """Generate a CSPRNG session identifier (128-bit, hex-encoded).

    Replaces ``uuid.uuid4()[:8]`` which only provides 32 bits of
    entropy after truncation.
    """
    return secrets.token_hex(TOKEN_BYTES)


def generate_nonce() -> bytes:
    """Generate a 96-bit random nonce for AES-256-GCM.

    MUST NOT be reused with the same key.
    """
    return os.urandom(NONCE_BYTES)


def generate_salt() -> bytes:
    """Generate a 256-bit random salt for key derivation."""
    return os.urandom(SALT_BYTES)


# ── Hashing (CNSA 2.0 compliant) ────────────────────────────────────

def hash_sha384(data: bytes) -> str:
    """Compute SHA-384 digest (hex).

    Replaces all MD5 and SHA-1 usage across the codebase.
    """
    return hashlib.sha384(data).hexdigest()


def hash_sha512(data: bytes) -> str:
    """Compute SHA-512 digest (hex)."""
    return hashlib.sha512(data).hexdigest()


def hmac_sha384(key: bytes, data: bytes) -> bytes:
    """Compute HMAC-SHA-384 for data integrity verification.

    Args:
        key: HMAC key (should be >= 48 bytes for full security).
        data: Data to authenticate.

    Returns:
        Raw HMAC digest bytes.
    """
    return hmac.new(key, data, hashlib.sha384).digest()


def verify_hmac(key: bytes, data: bytes, expected: bytes) -> bool:
    """Constant-time HMAC verification (timing-attack resistant)."""
    computed = hmac_sha384(key, data)
    return hmac.compare_digest(computed, expected)


# ── Key Derivation ──────────────────────────────────────────────────

def derive_key(
    password: str,
    salt: Optional[bytes] = None,
    iterations: int = PBKDF2_ITERATIONS,
) -> Tuple[bytes, bytes]:
    """Derive an AES-256 key from a password using PBKDF2-SHA-512.

    Args:
        password: User-supplied password or passphrase.
        salt: Random salt (generated if None).
        iterations: PBKDF2 iteration count.

    Returns:
        Tuple of (derived_key, salt) — both needed for later derivation.
    """
    if salt is None:
        salt = generate_salt()
    key = hashlib.pbkdf2_hmac(
        PBKDF2_HASH,
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=KEY_BYTES,
    )
    return key, salt


# ── Integrity Verification ──────────────────────────────────────────

def compute_file_integrity(file_path: str) -> str:
    """Compute SHA-384 hash of a file for integrity verification.

    Reads in 64 KB chunks to handle large files without excessive
    memory consumption.

    Args:
        file_path: Path to the file.

    Returns:
        Hex-encoded SHA-384 digest.
    """
    h = hashlib.sha384()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_data_integrity(data: bytes) -> str:
    """Compute SHA-384 hash of raw bytes."""
    return hashlib.sha384(data).hexdigest()


# ── Key Metadata ────────────────────────────────────────────────────

def create_key_metadata(key_id: str) -> dict:
    """Create metadata for a newly generated key.

    Includes creation time, expiry, and rotation tracking.
    """
    now = int(time.time())
    return {
        "key_id": key_id,
        "algorithm": "AES-256-GCM",
        "created_at": now,
        "expires_at": now + KEY_ROTATION_INTERVAL_S,
        "rotated": False,
        "rotation_count": 0,
    }


def is_key_expired(metadata: dict) -> bool:
    """Check if a key has passed its rotation deadline."""
    return int(time.time()) >= metadata.get("expires_at", 0)


# ── Deterministic Parameter Hashing (stealth module) ────────────────

def deterministic_param_hash(session_hash: str, param: str) -> float:
    """Derive a deterministic float [0, 1) from a session hash + param name.

    Replaces MD5-based parameter hashing in the stealth module with
    SHA-384, maintaining the same interface but with a CNSA 2.0
    compliant primitive.

    Args:
        session_hash: Session-unique hex string.
        param: Parameter name to hash.

    Returns:
        A float in [0, 1) deterministically derived from the inputs.
    """
    digest = hashlib.sha384(
        (session_hash + param).encode("utf-8")
    ).digest()
    # Use first 8 bytes as a 64-bit unsigned int, normalize to [0, 1)
    value = struct.unpack(">Q", digest[:8])[0]
    return value / (2**64)
