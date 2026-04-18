"""
Tamper-evident load/save for pickled ML artefacts.

Plain ``pickle.load`` on a disk file is an RCE primitive — if an
attacker can write the ``.pkl``, they can execute arbitrary code in
the process. DupeZ mitigates this by requiring every model artefact
to be paired with a sibling ``.hmac`` file containing the HMAC-SHA384
hex digest of the artefact bytes under a key derived from the
DPAPI-protected secret store.

Load flow:
    1. Read ``<path>`` bytes.
    2. Read ``<path>.hmac`` hex.
    3. :func:`hmac.compare_digest` — constant-time verification.
    4. ONLY on success, ``pickle.loads`` from the buffer.

Save flow:
    1. Serialize the artefact to bytes.
    2. Compute HMAC-SHA384 over the bytes.
    3. Atomic write ``<path>.tmp`` → ``<path>``, then write
       ``<path>.hmac`` (hex).

The key kind is ``model.artefact.hmac`` — separate from the
persistence HMAC kind so that rotating the persistence key doesn't
invalidate every trained model.

API:
    * :func:`load_artefact(path) -> Any`       — verify + unpickle.
    * :func:`save_artefact(artefact, path)`    — pickle + sign.
    * :exc:`ModelIntegrityError`               — raised on any failure
      that would allow unverified deserialisation.

Backward-compat:
    A legacy ``.pkl`` without a sibling ``.hmac`` is treated as a
    refusal (ModelIntegrityError). Training scripts can emit the
    ``.hmac`` via :func:`save_artefact`. In-place migration of an
    existing trusted artefact — :func:`sign_existing_artefact` — is
    provided so operators can opt a known-good file in without
    retraining.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import pickle
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "ModelIntegrityError",
    "MODEL_SECRET_KIND",
    "load_artefact",
    "save_artefact",
    "sign_existing_artefact",
    "is_signed",
]


class ModelIntegrityError(RuntimeError):
    """Raised when a model artefact fails integrity verification."""


MODEL_SECRET_KIND: str = "model.artefact.hmac"
_MODEL_KEY_SIZE: int = 32
_MODEL_HMAC_ALGO = hashlib.sha384

_KEY_LOCK = threading.Lock()
_KEY_CACHE: Optional[bytes] = None


def _get_key() -> bytes:
    """Load (and cache) the model-integrity HMAC key from the secret store."""
    global _KEY_CACHE
    if _KEY_CACHE is not None:
        return _KEY_CACHE
    with _KEY_LOCK:
        if _KEY_CACHE is not None:
            return _KEY_CACHE
        try:
            from app.core.secret_store import get_or_create_secret
            k = get_or_create_secret(MODEL_SECRET_KIND, size=_MODEL_KEY_SIZE)
        except Exception as e:
            raise ModelIntegrityError(
                f"secret_store unreachable, cannot verify model integrity: {e!r}"
            )
        if not isinstance(k, (bytes, bytearray)) or len(k) < 16:
            raise ModelIntegrityError(
                f"secret_store returned invalid key "
                f"(len={len(k) if k else 0})"
            )
        _KEY_CACHE = bytes(k)
        return _KEY_CACHE


def _compute(data: bytes) -> str:
    return hmac.new(_get_key(), data, _MODEL_HMAC_ALGO).hexdigest()


def _verify(data: bytes, expected_hex: str) -> bool:
    computed = _compute(data)
    return hmac.compare_digest(computed, expected_hex.strip())


def is_signed(path: Path) -> bool:
    """Return True when a sibling ``.hmac`` file exists for ``path``."""
    return Path(f"{path}.hmac").exists()


def load_artefact(path: Path) -> Any:
    """Verify and unpickle the artefact at ``path``.

    Raises :class:`ModelIntegrityError` if:
      * the file doesn't exist,
      * the sibling ``.hmac`` is missing,
      * the HMAC doesn't match,
      * anything in the path bypasses verification.

    On success, the caller receives the unpickled object. The
    :func:`pickle.loads` call is reached ONLY after
    :func:`hmac.compare_digest` returns True.
    """
    p = Path(path)
    if not p.exists():
        raise ModelIntegrityError(f"artefact not found: {p}")
    sig_path = Path(f"{p}.hmac")
    if not sig_path.exists():
        raise ModelIntegrityError(
            f"missing integrity tag for {p}; refusing to deserialise. "
            f"Re-train the model or call sign_existing_artefact() on a "
            f"known-good copy."
        )

    try:
        data = p.read_bytes()
    except OSError as e:
        raise ModelIntegrityError(f"cannot read artefact: {e}")

    try:
        expected = sig_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise ModelIntegrityError(f"cannot read integrity tag: {e}")

    if len(expected) != _MODEL_HMAC_ALGO().digest_size * 2:
        raise ModelIntegrityError(
            f"integrity tag length mismatch "
            f"(got {len(expected)}, expected {_MODEL_HMAC_ALGO().digest_size * 2})"
        )

    if not _verify(data, expected):
        raise ModelIntegrityError(
            f"integrity tag mismatch for {p}; refusing to deserialise. "
            f"The file has been modified or was produced with a different key."
        )

    # HMAC verified — only now do we enter pickle territory. pickle.loads
    # is still a general-purpose deserialiser, but the input is now known
    # to be the exact bytes we wrote under the current secret-store key.
    try:
        return pickle.loads(data)
    except Exception as e:
        raise ModelIntegrityError(f"pickle parse failed after HMAC OK: {e!r}")


def save_artefact(artefact: Any, path: Path, *, protocol: int = 4) -> None:
    """Pickle ``artefact`` to ``path`` and write the sibling ``.hmac``.

    Uses an atomic-rename pattern: we write ``<path>.tmp``, fsync, then
    rename over ``<path>``. The ``.hmac`` is then written in place —
    it's fine for it to be written non-atomically because a verifier
    that sees a missing tag fails closed.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    data = pickle.dumps(artefact, protocol=protocol)
    tag = _compute(data)

    fd, tmp_name = tempfile.mkstemp(
        prefix=p.name + ".", suffix=".tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
            fp.flush()
            try:
                os.fsync(fp.fileno())
            except OSError:
                pass
        os.replace(tmp_name, str(p))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    Path(f"{p}.hmac").write_text(tag, encoding="utf-8")


def sign_existing_artefact(path: Path) -> str:
    """Compute and write a sibling ``.hmac`` for an already-present file.

    This exists for **operator-blessed** migration of a known-good
    artefact — e.g. a freshly trained ``duration_regressor.pkl`` that
    was produced before this integrity module existed. The operator is
    trusting the bytes on disk at the moment they call this function;
    verification is subsequently mandatory for every load.

    Returns the hex tag that was written.
    """
    p = Path(path)
    if not p.exists():
        raise ModelIntegrityError(f"cannot sign missing artefact: {p}")
    data = p.read_bytes()
    tag = _compute(data)
    Path(f"{p}.hmac").write_text(tag, encoding="utf-8")
    return tag
