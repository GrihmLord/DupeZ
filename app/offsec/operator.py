"""
Unified offensive operator interface (tier-2 gated).

This module is the single entrypoint an authorised operator uses to
drive the offensive self-test layer. It is intentionally *more*
restricted than the defensive surface:

* Tier 1 — :func:`app.offsec.require_consent` must pass (the global
  ``DUPEZ_OFFSEC_CONSENT`` env var gate).
* Tier 2 — :func:`authorize_operator` must pass. This requires an
  HMAC-SHA256 token over ``(operator_id || reason || consent_value)``
  using a key loaded from either ``DUPEZ_OFFSEC_OPERATOR_KEY`` (hex)
  or, if absent, from ``~/.config/dupez/offsec_operator.key`` (32
  random bytes written with mode 0600). The token is supplied via
  ``DUPEZ_OFFSEC_OPERATOR_TOKEN``.
* Tier 3 — the :class:`EngagementScope` constructor refuses any
  ``target`` other than ``"self"``.

Capabilities
------------

* :func:`list_capabilities` — machine-readable inventory of every
  offensive module, probe, playbook, and detection-rule the layer
  can run.
* :func:`run_engagement` — run a named set of tactics and/or named
  playbooks in one call, produce a single consolidated engagement
  record written to ``dist/engagement-*.json``.
* :func:`mint_operator_token` — CLI helper so a human operator can
  generate the HMAC token for a given (operator, reason).

CLI
---

    python -m app.offsec.operator list
    python -m app.offsec.operator mint --operator grihm --reason "Q2 review"
    python -m app.offsec.operator engage \
        --operator grihm --reason "Q2 review" \
        --tactics recon,attack_surface,detection_coverage \
        --playbooks initial_access_webapp,privilege_escalation

Every invocation is permanently audited via
:mod:`app.logs.audit` when that module is importable; when it isn't,
the invocation is written to the engagement JSON only.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from app.offsec import (
    OFFSEC_CONSENT_ENV,
    OFFSEC_CONSENT_VALUE,
    OffsecConsentError,
    consent_granted,
    require_consent,
)
from app.offsec.findings import FindingRegistry, Severity

__all__ = [
    "OPERATOR_KEY_ENV",
    "OPERATOR_TOKEN_ENV",
    "OperatorAuthError",
    "EngagementScope",
    "authorize_operator",
    "mint_operator_token",
    "list_capabilities",
    "run_engagement",
    "main",
]

# ── Tier-2 authorisation ───────────────────────────────────────────

OPERATOR_KEY_ENV = "DUPEZ_OFFSEC_OPERATOR_KEY"            # hex-encoded
OPERATOR_TOKEN_ENV = "DUPEZ_OFFSEC_OPERATOR_TOKEN"        # hex-encoded HMAC
_OPERATOR_KEY_FILE = Path.home() / ".config" / "dupez" / "offsec_operator.key"


class OperatorAuthError(RuntimeError):
    """Raised when tier-2 operator authorisation fails."""


def _load_operator_key() -> bytes:
    """Load the tier-2 shared secret used to mint and verify tokens.

    Preference order:
      1. ``DUPEZ_OFFSEC_OPERATOR_KEY`` env var (hex).
      2. ``~/.config/dupez/offsec_operator.key`` — 32 random bytes,
         mode 0600. Auto-created on first use when the env var is
         absent, because a local self-test that never leaves the host
         should not require a human to seed a key file by hand.
    """
    env_hex = os.environ.get(OPERATOR_KEY_ENV, "").strip()
    if env_hex:
        try:
            raw = bytes.fromhex(env_hex)
        except ValueError as e:
            raise OperatorAuthError(
                f"{OPERATOR_KEY_ENV} is set but is not valid hex: {e}"
            )
        if len(raw) < 16:
            raise OperatorAuthError(
                f"{OPERATOR_KEY_ENV} must be at least 16 bytes (got {len(raw)})"
            )
        return raw

    _OPERATOR_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _OPERATOR_KEY_FILE.exists():
        key = secrets.token_bytes(32)
        _OPERATOR_KEY_FILE.write_bytes(key)
        try:
            os.chmod(_OPERATOR_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return key
    return _OPERATOR_KEY_FILE.read_bytes()


def mint_operator_token(operator: str, reason: str) -> str:
    """Return the hex HMAC-SHA256 token for ``(operator, reason)``.

    Requires tier-1 consent already granted — otherwise we refuse to
    even print a token, on the principle that the token is useless
    without consent but its existence could imply authorisation.
    """
    require_consent()
    if not operator:
        raise OperatorAuthError("operator identity required")
    key = _load_operator_key()
    msg = f"{operator}|{reason}|{OFFSEC_CONSENT_VALUE}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def authorize_operator(operator: str, reason: str, *,
                       token: Optional[str] = None) -> None:
    """Raise :class:`OperatorAuthError` unless tier-2 auth passes.

    ``token`` defaults to the value of ``DUPEZ_OFFSEC_OPERATOR_TOKEN``.
    """
    require_consent()
    if not operator:
        raise OperatorAuthError("operator identity required")
    presented = token if token is not None else os.environ.get(OPERATOR_TOKEN_ENV, "")
    if not presented:
        raise OperatorAuthError(
            f"{OPERATOR_TOKEN_ENV} is not set — tier-2 auth required. "
            "Mint a token with `python -m app.offsec.operator mint "
            f"--operator {operator!r} --reason {reason!r}`."
        )
    expected = mint_operator_token(operator, reason)
    if not hmac.compare_digest(presented.strip().lower(), expected.lower()):
        raise OperatorAuthError(
            "tier-2 auth failed: operator token does not match the "
            "expected HMAC for the given (operator, reason). Re-mint "
            "the token with the exact same operator+reason strings."
        )


# ── Engagement scope ───────────────────────────────────────────────

_VALID_TACTICS = [
    "recon", "attack_surface", "fuzz_ipc",
    "vuln_discovery", "exploit", "post_exploit",
    "detection_coverage",
]

_VALID_PLAYBOOKS = [
    "initial_access_webapp", "supply_chain_compromise",
    "lateral_movement_creduse", "privilege_escalation",
    "exfil_via_permitted_egress", "persistence_via_legit",
]


@dataclass(frozen=True)
class EngagementScope:
    """Authorised engagement parameters.

    Attributes:
        operator:  operator identity (logged on every finding).
        reason:    free-form justification (logged on every finding).
        target:    MUST be ``"self"``.
        tactics:   subset of ``_VALID_TACTICS``.
        playbooks: subset of ``_VALID_PLAYBOOKS``.
        safe_mode: when True (default), probes stop at confirmation.
    """
    operator: str
    reason: str
    target: str = "self"
    tactics: Tuple[str, ...] = tuple(_VALID_TACTICS)
    playbooks: Tuple[str, ...] = ()
    safe_mode: bool = True

    def validate(self) -> None:
        if self.target != "self":
            raise OperatorAuthError(
                f"engagement target={self.target!r} refused; "
                "offsec layer is scoped to the local DupeZ process."
            )
        if not self.operator:
            raise OperatorAuthError("operator identity required")
        bad_t = [t for t in self.tactics if t not in _VALID_TACTICS]
        if bad_t:
            raise OperatorAuthError(f"unknown tactic(s): {bad_t}")
        bad_p = [p for p in self.playbooks if p not in _VALID_PLAYBOOKS]
        if bad_p:
            raise OperatorAuthError(f"unknown playbook(s): {bad_p}")


# ── Capability inventory ───────────────────────────────────────────

def list_capabilities() -> dict:
    """Machine-readable inventory of every offensive capability.

    Safe to call without tier-2 auth (but still requires tier-1
    consent): it only inspects module metadata, no findings emitted.
    """
    require_consent()
    inv: dict = {
        "tactics":   [],
        "playbooks": [],
        "probes":    [],
        "rules":     [],
    }
    # Tactic inventory.
    tactic_docs = {
        "recon":              "Local reconnaissance — host profile, loaded modules, writable PATH, dangerous env vars, DLL search order.",
        "attack_surface":     "Enumerate our own listeners + named pipes + permissions on sensitive files.",
        "fuzz_ipc":           "Malformed-frame fuzz of DupeZ's OWN IPC endpoints (consent-gated).",
        "vuln_discovery":     "Source-code smells, dependency CVE/VEX cross-ref, typosquat detection, config risk.",
        "exploit":            "PoC probes against hardened primitives (signature, argv, traversal, HMAC, audit chain).",
        "post_exploit":       "Blast-radius mapping (data reach, lateral movement, persistence, detection evasion).",
        "detection_coverage": "Per-rule PASS/FAIL coverage metric over DupeZ's defensive detections.",
    }
    for t, doc in tactic_docs.items():
        inv["tactics"].append({"name": t, "description": doc})

    # Playbook inventory.
    try:
        from app.offsec import scenarios
        for name in scenarios.list_playbooks():
            inv["playbooks"].append({"name": name})
    except Exception as e:
        inv["playbooks_error"] = repr(e)

    # Probe inventory.
    try:
        from app.offsec import exploit
        for name, _ in exploit._PROBES:
            inv["probes"].append({"name": name})
    except Exception as e:
        inv["probes_error"] = repr(e)

    # Detection rule inventory.
    try:
        from app.offsec import detection_coverage as dc
        for fn in dc._RULES:
            inv["rules"].append({"name": fn.__name__.lstrip("_")})
    except Exception as e:
        inv["rules_error"] = repr(e)

    return inv


# ── Engagement execution ───────────────────────────────────────────

def _audit(event: str, evidence: dict) -> None:
    """Best-effort audit-log emit; silent if audit module missing."""
    try:
        from app.logs import audit
        emit = getattr(audit, "audit_event", None)
        if callable(emit):
            emit(event, evidence)
    except Exception:
        pass


def run_engagement(scope: EngagementScope,
                   registry: Optional[FindingRegistry] = None,
                   *,
                   out_path: Optional[Path] = None,
                   product_version: str = "0.0.0-dev",
                   ) -> dict:
    """Run the operator-authorised engagement and return a record dict.

    Writes the record to ``out_path`` (defaults to
    ``dist/engagement-<epoch>.json``). Callers that want the raw
    :class:`FindingRegistry` back can pass one in — it will be
    re-used and returned alongside the dict.
    """
    require_consent()
    authorize_operator(scope.operator, scope.reason)
    scope.validate()

    registry = registry or FindingRegistry()
    t_start = time.time()
    _audit("offsec_engagement_start", {
        "operator": scope.operator, "reason": scope.reason,
        "tactics": list(scope.tactics), "playbooks": list(scope.playbooks),
        "safe_mode": scope.safe_mode,
    })

    # Record the engagement invocation itself.
    registry.record(
        title="Operator engagement started",
        description=(
            f"Operator {scope.operator!r} started an engagement: "
            f"reason={scope.reason!r}, safe_mode={scope.safe_mode}, "
            f"tactics={list(scope.tactics)}, playbooks={list(scope.playbooks)}."
        ),
        severity=Severity.INFO,
        evidence={
            "operator": scope.operator,
            "reason": scope.reason,
            "tactics": list(scope.tactics),
            "playbooks": list(scope.playbooks),
            "safe_mode": scope.safe_mode,
            "target": scope.target,
        },
    )

    # Run tactics.
    tactic_status: Dict[str, str] = {}
    if scope.tactics:
        try:
            from app.offsec.runner import run_all
            tactic_status = run_all(list(scope.tactics), registry)
        except Exception as e:
            tactic_status["_fatal"] = f"{e!r}"
            registry.record(
                title="Engagement tactic runner raised",
                description="Unhandled exception during tactic dispatch.",
                severity=Severity.LOW,
                evidence={"error": repr(e),
                          "traceback": traceback.format_exc()},
            )

    # Run playbooks.
    playbook_status: Dict[str, dict] = {}
    if scope.playbooks:
        try:
            from app.offsec import scenarios
            for pb in scope.playbooks:
                try:
                    r = scenarios.run_playbook(pb, registry)
                    playbook_status[pb] = {
                        "achieved": r.achieved,
                        "steps": r.steps,
                        "findings_added": r.finding_count_delta,
                    }
                except Exception as e:
                    playbook_status[pb] = {"error": repr(e)}
        except Exception as e:
            playbook_status["_fatal"] = {"error": repr(e)}

    # Serialise.
    duration = time.time() - t_start
    record = {
        "engagement": {
            "operator": scope.operator,
            "reason": scope.reason,
            "target": scope.target,
            "safe_mode": scope.safe_mode,
            "started_at": t_start,
            "duration_s": round(duration, 3),
        },
        "tactics": tactic_status,
        "playbooks": playbook_status,
        "findings_summary": registry.summary(),
    }

    if out_path is None:
        dist = Path("dist")
        dist.mkdir(parents=True, exist_ok=True)
        out_path = dist / f"engagement-{int(t_start)}.json"
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        registry.write_json(
            out_path.with_suffix(".findings.json"),
            product_version=product_version,
        )
    except Exception as e:
        record["findings_write_error"] = repr(e)

    try:
        out_path.write_text(json.dumps(record, indent=2, sort_keys=True),
                            encoding="utf-8")
    except Exception as e:
        record["engagement_write_error"] = repr(e)

    _audit("offsec_engagement_end", {
        "operator": scope.operator,
        "duration_s": record["engagement"]["duration_s"],
        "total_findings": record["findings_summary"].get("total", 0),
    })
    return record


# ── CLI ────────────────────────────────────────────────────────────

def _cmd_list(args: argparse.Namespace) -> int:
    inv = list_capabilities()
    print(json.dumps(inv, indent=2, sort_keys=True))
    return 0


def _cmd_mint(args: argparse.Namespace) -> int:
    tok = mint_operator_token(args.operator, args.reason)
    print(tok)
    return 0


def _cmd_engage(args: argparse.Namespace) -> int:
    tactics = tuple(t.strip() for t in args.tactics.split(",") if t.strip()) \
        if args.tactics else tuple(_VALID_TACTICS)
    playbooks = tuple(p.strip() for p in args.playbooks.split(",") if p.strip()) \
        if args.playbooks else ()
    scope = EngagementScope(
        operator=args.operator,
        reason=args.reason,
        tactics=tactics,
        playbooks=playbooks,
        safe_mode=not args.unsafe,
    )
    try:
        record = run_engagement(
            scope,
            out_path=args.out,
            product_version=args.product_version,
        )
    except (OffsecConsentError, OperatorAuthError) as e:
        print(f"auth failure: {e}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


def main(argv: List[str] | None = None) -> int:
    # Apply startup hardening before anything else so the offsec self-
    # test process itself is running under SetDefaultDllDirectories. A
    # probe that reports DLL_NOT_HARDENED against an unhardened offsec
    # process would be circular.
    try:
        from app.core.self_integrity import apply_startup_hardening as _apply
        _apply()
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        prog="python -m app.offsec.operator",
        description="Unified offensive operator interface (tier-2 gated).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List every available capability as JSON.")

    ap_mint = sub.add_parser("mint", help="Mint a tier-2 operator token.")
    ap_mint.add_argument("--operator", required=True)
    ap_mint.add_argument("--reason", required=True)

    ap_eng = sub.add_parser("engage", help="Run an authorised engagement.")
    ap_eng.add_argument("--operator", required=True)
    ap_eng.add_argument("--reason", required=True)
    ap_eng.add_argument("--tactics", default="",
                        help="Comma-separated tactics (default: all).")
    ap_eng.add_argument("--playbooks", default="",
                        help="Comma-separated playbooks (default: none).")
    ap_eng.add_argument("--unsafe", action="store_true",
                        help="Disable safe_mode — not recommended.")
    ap_eng.add_argument("--out", type=Path, default=None,
                        help="Output JSON path (default: dist/engagement-<ts>.json).")
    ap_eng.add_argument("--product-version", default="0.0.0-dev")

    args = ap.parse_args(argv)

    try:
        if args.cmd == "list":
            return _cmd_list(args)
        if args.cmd == "mint":
            return _cmd_mint(args)
        if args.cmd == "engage":
            return _cmd_engage(args)
    except OffsecConsentError as e:
        print(f"consent not granted: {e}", file=sys.stderr)
        return 2
    except OperatorAuthError as e:
        print(f"operator auth failure: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"unhandled error: {e}", file=sys.stderr)
        traceback.print_exc()
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
