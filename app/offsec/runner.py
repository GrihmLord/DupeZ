"""
Offensive self-test runner (CLI entrypoint).

Orchestrates the three tactic modules (``recon``, ``attack_surface``,
``fuzz_ipc``) into a single run, producing one JSON findings document
and a console summary.

Usage::

    # Consent is enforced: without this env var, everything refuses.
    export DUPEZ_OFFSEC_CONSENT=i-own-this-machine-and-accept-local-scope

    python -m app.offsec.runner                        # all tactics
    python -m app.offsec.runner --only recon           # one tactic
    python -m app.offsec.runner --skip fuzz_ipc        # exclude one
    python -m app.offsec.runner --out findings.json    # custom path
    python -m app.offsec.runner --product-version 5.8.0

Exit codes:
    0   — ran to completion (regardless of findings severity).
    2   — consent not granted / invalid invocation.
    3   — a tactic raised an unhandled exception.

Findings severity does NOT affect exit code. This tool is a reporter,
not a gate. CI callers that want a gate should read the JSON summary
and fail on any CRITICAL / HIGH count themselves.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, List

from app.offsec import (
    OFFSEC_CONSENT_ENV,
    OFFSEC_CONSENT_VALUE,
    OffsecConsentError,
    consent_granted,
    require_consent,
)
from app.offsec.findings import FindingRegistry, Severity

__all__ = ["main", "run_all"]


_TACTIC_MODULES: Dict[str, str] = {
    "recon":              "app.offsec.recon.run_recon",
    "attack_surface":     "app.offsec.attack_surface.run_attack_surface",
    "fuzz_ipc":           "app.offsec.fuzz_ipc.run_fuzz_ipc",
    "vuln_discovery":     "app.offsec.vuln_discovery.run_vuln_discovery",
    "exploit":            "app.offsec.exploit.run_exploitation",
    "post_exploit":       "app.offsec.post_exploit.run_post_exploit_analysis",
    "detection_coverage": "app.offsec.detection_coverage.run_detection_coverage",
}


def _resolve(dotted: str) -> Callable[[FindingRegistry], None]:
    """Resolve 'pkg.module.func' to the callable."""
    mod_name, _, fn_name = dotted.rpartition(".")
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name)
    if not callable(fn):
        raise RuntimeError(f"{dotted} is not callable")
    return fn


def run_all(
    tactics: List[str],
    registry: FindingRegistry,
) -> Dict[str, str]:
    """Run the named tactics in order. Returns a per-tactic status dict."""
    statuses: Dict[str, str] = {}
    for name in tactics:
        target = _TACTIC_MODULES.get(name)
        if not target:
            statuses[name] = f"unknown tactic: {name}"
            continue
        try:
            fn = _resolve(target)
            t0 = time.monotonic()
            fn(registry)
            dur = time.monotonic() - t0
            statuses[name] = f"ok ({dur:.2f}s)"
        except OffsecConsentError:
            raise
        except Exception as e:
            statuses[name] = f"error: {e}"
            registry.record(
                title=f"Tactic {name} raised an exception",
                description=(
                    f"While running the {name} tactic, an unhandled "
                    f"exception was raised. This is a bug in the self-test "
                    "itself, not necessarily in the code under test."
                ),
                severity=Severity.LOW,
                evidence={
                    "tactic": name,
                    "error": repr(e),
                    "traceback": traceback.format_exc(),
                },
            )
    return statuses


def _print_summary(registry: FindingRegistry, statuses: Dict[str, str]) -> None:
    summary = registry.summary()
    print()
    print("=" * 72)
    print("DupeZ offsec self-test — summary")
    print("=" * 72)
    for name, status in statuses.items():
        print(f"  [{name}] {status}")
    print()
    print(f"  Findings: {summary['total']}")
    for sev, count in summary["by_severity"].items():
        marker = "  "
        if sev in {"CRITICAL", "HIGH"} and count > 0:
            marker = "!!"
        print(f"  {marker} {sev:8s}  {count}")
    print("=" * 72)


def main(argv: List[str] | None = None) -> int:
    # Apply startup hardening first so the offsec self-test process is
    # itself running under SetDefaultDllDirectories.
    try:
        from app.core.self_integrity import apply_startup_hardening as _apply
        _apply()
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        prog="python -m app.offsec.runner",
        description=__doc__.split("\n\n")[0],
    )
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="TACTIC",
        choices=list(_TACTIC_MODULES),
        help="Run only the named tactic (repeatable).",
    )
    ap.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="TACTIC",
        choices=list(_TACTIC_MODULES),
        help="Skip the named tactic (repeatable).",
    )
    ap.add_argument(
        "--out", type=Path,
        default=Path("dist/offsec-findings.json"),
        help="Output path for the findings JSON document.",
    )
    ap.add_argument(
        "--product-version", default="0.0.0-dev",
        help="Product version string embedded in the report.",
    )
    args = ap.parse_args(argv)

    if not consent_granted():
        print(
            "offsec runner refused to start: "
            f"{OFFSEC_CONSENT_ENV}={OFFSEC_CONSENT_VALUE!r} is not set.\n"
            "This layer is a LOCAL self-test. Only set that variable if:\n"
            "  (1) you own this machine, and\n"
            "  (2) you accept that it will inspect local resources and\n"
            "      send malformed messages to DupeZ's OWN IPC endpoints.",
            file=sys.stderr,
        )
        return 2

    # §9.2: second-factor gate for offsec engagement bootstrap. We do
    # this AFTER consent but BEFORE any tactic actually runs. If no
    # second-factor provider is enrolled the gate short-circuits
    # silently (first-boot UX); on enrolled installs, verification is
    # mandatory. Set DUPEZ_SECOND_FACTOR_DISABLED=1 only in trusted CI.
    if os.environ.get("DUPEZ_SECOND_FACTOR_DISABLED") != "1":
        try:
            from app.core.second_factor import (
                SecondFactorRequired,
                get_gate,
            )
            _gate = get_gate()
            if _gate.is_enrolled():
                try:
                    _gate.require(
                        "offsec.engagement",
                        reason=f"bootstrap offsec run: {tactics}",
                    )
                except SecondFactorRequired as e:
                    print(
                        f"offsec runner refused by second-factor gate: {e}",
                        file=sys.stderr,
                    )
                    return 2
        except ImportError:
            pass
        except Exception as e:
            print(
                f"second-factor gate error (not blocking first-boot install): {e}",
                file=sys.stderr,
            )

    # Decide which tactics to run.
    tactics = args.only or list(_TACTIC_MODULES)
    tactics = [t for t in tactics if t not in args.skip]
    if not tactics:
        print("No tactics selected.", file=sys.stderr)
        return 2

    registry = FindingRegistry()
    # A meta-finding that records the invocation itself — helps audit.
    registry.record(
        title="offsec self-test invoked",
        description=(
            "The DupeZ offsec self-test runner was invoked with consent. "
            f"Tactics: {tactics}."
        ),
        severity=Severity.INFO,
        evidence={
            "tactics": tactics,
            "product_version": args.product_version,
            "argv": sys.argv,
        },
    )

    try:
        statuses = run_all(tactics, registry)
    except OffsecConsentError as e:
        print(f"consent lost mid-run: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"unhandled exception during run: {e}", file=sys.stderr)
        traceback.print_exc()
        return 3

    try:
        registry.write_json(args.out, product_version=args.product_version)
    except OSError as e:
        print(f"failed to write {args.out}: {e}", file=sys.stderr)
        return 3

    _print_summary(registry, statuses)
    print(f"\n  Findings JSON: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
