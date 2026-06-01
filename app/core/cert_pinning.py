"""
Certificate / SPKI pinning for high-trust HTTPS endpoints (v5.7.6).

Why
---
The auto-updater calls ``api.github.com`` (release metadata) and
``objects.githubusercontent.com`` (installer + manifest blobs). Today
those calls trust whatever the Windows cert store says is a valid
chain. If the operator's cert store contains a maliciously injected
root (corporate MITM box gone rogue, malware that ships its own root,
state-actor sub-CA), an attacker can present a *valid-looking* cert
for github.com and the TLS layer raises no alarm. The Ed25519
manifest signature still saves us at that layer — the attacker can't
sign a malicious update — but a hostile MITM can still serve a
*stale* (signed-but-old) manifest and bypass the new downgrade-
replay protection by going around the version ledger entirely (e.g.
intercepting the very first call before the ledger exists).

SPKI pinning closes this. We compute SHA-256(SubjectPublicKeyInfo)
over each cert in the presented chain and require AT LEAST ONE pin
in the chain to match a value we hard-coded at build time.

What this module ships
----------------------
* :func:`spki_hash`           — SHA-256 of a DER-encoded cert's SPKI.
* :class:`PinViolation`       — exception raised on enforcement.
* :func:`enforce_pin`         — given a cert chain (list of DER blobs),
                                check it against the pin set for a host.
* :func:`pinned_https_open`   — drop-in replacement for ``urlopen``
                                that performs pin enforcement.
* :data:`PINS`                — host → frozenset of pinned SPKI hex
                                hashes. **EMPTY by default** in this
                                v5.7.6 ship. Operators / release
                                engineers populate it by running
                                ``dupez --capture-update-spkis`` and
                                copying the printed hashes here for
                                the next release. The empty-set policy
                                is *audit-only*: every chain seen is
                                logged so we have offline data for
                                hardening the pin set.

Why empty-by-default
--------------------
Shipping a wrong pin set bricks the updater for every user, with no
in-app recovery. Pinning the wrong CA is the #1 way to ruin your own
update channel. We ship the *infrastructure* with v5.7.6 (so the wire
is in place and unit-tested), and populate the pin set in v5.7.7
after a one-week telemetry window confirms what GitHub's chain
actually looks like across operator regions.

Environment overrides
---------------------
``DUPEZ_DISABLE_CERT_PIN=1`` disables enforcement entirely. Intended
ONLY for the operator-recovery case where a chain rotation has broken
the pin set and the user needs to update to a fixed v5.7.x. Setting
the var emits a loud audit event.
"""

from __future__ import annotations

import hashlib
import os
import ssl
import urllib.error
import urllib.request
from typing import Dict, FrozenSet, Iterable, List, Optional

__all__ = [
    "PinViolation",
    "PINS",
    "spki_hash",
    "chain_spki_hashes",
    "enforce_pin",
    "pinned_https_open",
    "capture_chain_for_host",
]


class PinViolation(RuntimeError):
    """Raised when a TLS chain fails SPKI pinning enforcement."""


# Host → pinned SPKI hashes. Populate when chain telemetry is in.
# Hash format: lowercase hex SHA-256 of the cert's SubjectPublicKeyInfo
# DER bytes (i.e. the input to RFC 7469 ``pin-sha256``, before base64).
PINS: Dict[str, FrozenSet[str]] = {
    # "api.github.com":                frozenset({...}),
    # "objects.githubusercontent.com": frozenset({...}),
}


# ── SPKI extraction ──────────────────────────────────────────────────

def spki_hash(cert_der: bytes) -> str:
    """Return lowercase hex SHA-256 of a DER cert's SubjectPublicKeyInfo.

    Uses the ``cryptography`` library (already a runtime dep for the
    Ed25519 update verifier) so we don't have to hand-parse ASN.1.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography import x509
    cert = x509.load_der_x509_certificate(cert_der)
    spki_der = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki_der).hexdigest()


def chain_spki_hashes(chain_ders: Iterable[bytes]) -> List[str]:
    """Convenience: SPKI hash of every cert in *chain_ders*."""
    return [spki_hash(d) for d in chain_ders]


# ── Enforcement ──────────────────────────────────────────────────────

def enforce_pin(host: str, chain_ders: Iterable[bytes]) -> None:
    """Raise :class:`PinViolation` if *chain* has no pin match for *host*.

    Empty pin set ⇒ AUDIT-ONLY: a ``cert_chain_observed`` event is
    emitted with the chain's SPKI hashes so the release engineer can
    promote them to PINS for the next release. No exception raised.

    Disable env override: ``DUPEZ_DISABLE_CERT_PIN=1`` ⇒ audit + skip.
    """
    chain = list(chain_ders)
    observed = chain_spki_hashes(chain) if chain else []

    if os.environ.get("DUPEZ_DISABLE_CERT_PIN") == "1":
        _audit_observed(host, observed, decision="bypassed_by_env")
        return

    pins = PINS.get(host, frozenset())
    if not pins:
        # Audit-only telemetry mode — empty pin set for this host.
        _audit_observed(host, observed, decision="audit_only")
        return

    if any(h in pins for h in observed):
        _audit_observed(host, observed, decision="pinned_ok")
        return

    _audit_observed(host, observed, decision="pin_violation")
    raise PinViolation(
        f"SPKI pin enforcement failed for {host!r}: presented chain "
        f"hashes {observed} match no pin in {sorted(pins)}. Refusing "
        f"the connection. If this is a legitimate CA rotation, set "
        f"DUPEZ_DISABLE_CERT_PIN=1 to recover and report it so the "
        f"pin set can be updated in the next release."
    )


def _audit_observed(host: str, observed: List[str], *, decision: str) -> None:
    """Emit a ``cert_chain_observed`` event for offline pin-set tuning."""
    try:
        from app.logs.audit import audit_event
        audit_event("cert_chain_observed", {
            "host": host,
            "spki_hashes": observed,
            "decision": decision,
        })
    except Exception:
        pass


# ── HTTPS connector with post-handshake pin enforcement ──────────────

def pinned_https_open(
    url: str,
    *,
    timeout: float = 30.0,
    headers: Optional[Dict[str, str]] = None,
) -> bytes:
    """Open *url* via HTTPS with SPKI pin enforcement, return body bytes.

    Uses :class:`urllib.request.HTTPSHandler` with a custom
    :class:`ssl.SSLContext` that records the peer chain in DER form on
    handshake. Pin enforcement runs immediately after handshake; on
    violation the connection is closed and :class:`PinViolation` is
    raised. The response body is returned only if every gate passes.
    """
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https":
        raise PinViolation(
            f"pinned_https_open refuses non-HTTPS URL: {url!r}"
        )

    # Build a context that will let us inspect the chain. We use the
    # default cert verification path on top — pinning is additive, not
    # replacing standard chain validation.
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    except (AttributeError, ValueError):
        pass
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True

    # We need the chain. urllib doesn't expose it; reach into the
    # underlying http.client.HTTPSConnection.
    import http.client
    conn = http.client.HTTPSConnection(
        host=parsed.hostname,
        port=parsed.port or 443,
        timeout=timeout,
        context=ctx,
    )
    try:
        conn.connect()
        sock = conn.sock
        chain_ders: List[bytes] = []
        try:
            # leaf cert
            leaf = sock.getpeercert(binary_form=True)
            if leaf:
                chain_ders.append(leaf)
            # In some stdlib versions get_verified_chain() exists; if
            # so, use it for the full chain. Otherwise we only have
            # the leaf, which is still useful for leaf-key pinning.
            getter = getattr(sock, "get_verified_chain", None)
            if callable(getter):
                full = getter()
                chain_ders = list(full) if full else chain_ders
        except (AttributeError, OSError):
            pass

        try:
            enforce_pin(host, chain_ders)
        except PinViolation:
            try:
                conn.close()
            except Exception:
                pass
            raise

        path = parsed.path or "/"
        if parsed.query:
            path = path + "?" + parsed.query
        req_headers = dict(headers or {})
        req_headers.setdefault("User-Agent", "DupeZ-PinnedHTTP/1.0")
        conn.request("GET", path, headers=req_headers)
        resp = conn.getresponse()
        if resp.status >= 400:
            body = resp.read(4096)
            raise urllib.error.HTTPError(
                url, resp.status, resp.reason, dict(resp.getheaders()),
                fp=None,
            )
        return resp.read()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def capture_chain_for_host(host: str, port: int = 443, timeout: float = 15.0) -> List[str]:
    """One-shot helper for the ``--capture-update-spkis`` CLI flag.

    Connects to ``host:port``, completes the TLS handshake under the
    system CA trust store, prints (and returns) the SPKI hashes of
    every cert in the chain. The release engineer copies the right
    hashes into :data:`PINS` for the next release.
    """
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    except (AttributeError, ValueError):
        pass
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True

    import socket
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as sock:
            chain_ders: List[bytes] = []
            leaf = sock.getpeercert(binary_form=True)
            if leaf:
                chain_ders.append(leaf)
            getter = getattr(sock, "get_verified_chain", None)
            if callable(getter):
                full = getter()
                if full:
                    chain_ders = list(full)
            return chain_spki_hashes(chain_ders)
