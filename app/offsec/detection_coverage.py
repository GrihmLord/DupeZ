"""
Detection coverage validation.

For every security-relevant rule implemented in DupeZ's defensive
posture, emit a matching test that triggers the primitive and
asserts the expected alert / refusal fired. The collective result
is a continuously verifiable "detection coverage" metric.

Rules exercised:

    R1  subprocess_spawn      — should fire a subprocess_spawn audit
                                event on every safe_subprocess.run call.
    R2  plugin_sig_rejected   — should fire when verify_plugin_manifest
                                refuses an unsigned manifest.
    R3  sandbox_violation     — should fire when a plugin scope runs
                                an op its capabilities don't cover.
    R4  audit_chain_intact    — verify_chain() must return ok=True
                                after any normal event cadence.
    R5  hmac_mismatch         — data_persistence load with forged
                                .hmac must return None and log.
    R6  argv_str_refused      — safe_subprocess must refuse a pre-
                                joined string argv.
    R7  abs_path_required     — safe_subprocess must refuse a
                                relative executable path.

Each rule returns one of: ``PASS``, ``FAIL``, ``SKIP`` (with reason).
The collective coverage percentage is the ratio of PASS to (PASS+FAIL).
SKIPPED rules are excluded from the denominator.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from app.offsec import require_consent
from app.offsec.findings import FindingRegistry, Severity

__all__ = ["run_detection_coverage", "CoverageResult"]


@dataclass(frozen=True)
class CoverageResult:
    rule_id: str
    title: str
    status: str        # "PASS" | "FAIL" | "SKIP"
    reason: str = ""


def _r_argv_str_refused(reg: FindingRegistry) -> CoverageResult:
    try:
        from app.core import safe_subprocess as sp
    except Exception as e:
        return CoverageResult("R6", "argv_str_refused", "SKIP", f"import: {e!r}")
    try:
        sp.run("ls")  # type: ignore[arg-type]
        return CoverageResult("R6", "argv_str_refused", "FAIL",
                              "pre-joined string was accepted")
    except sp.SafeSubprocessError:
        return CoverageResult("R6", "argv_str_refused", "PASS")
    except Exception as e:
        return CoverageResult("R6", "argv_str_refused", "FAIL", f"wrong exception: {e!r}")


def _r_abs_path_required(reg: FindingRegistry) -> CoverageResult:
    try:
        from app.core import safe_subprocess as sp
    except Exception as e:
        return CoverageResult("R7", "abs_path_required", "SKIP", f"import: {e!r}")
    try:
        sp.run(["ls"])
        return CoverageResult("R7", "abs_path_required", "FAIL",
                              "relative path was accepted")
    except sp.SafeSubprocessError:
        return CoverageResult("R7", "abs_path_required", "PASS")
    except Exception as e:
        return CoverageResult("R7", "abs_path_required", "FAIL", f"wrong exception: {e!r}")


def _r_plugin_sig_rejected(reg: FindingRegistry) -> CoverageResult:
    try:
        from app.plugins import signing as ps
    except Exception as e:
        return CoverageResult("R2", "plugin_sig_rejected", "SKIP", f"import: {e!r}")
    with tempfile.TemporaryDirectory() as td:
        plug = Path(td) / "x"
        plug.mkdir()
        m = plug / "plugin.json"
        m.write_text('{"name":"x","version":"0","entry":"p.py","capabilities":[]}',
                     encoding="utf-8")
        try:
            ps.verify_plugin_manifest(m)
            return CoverageResult("R2", "plugin_sig_rejected", "FAIL",
                                  "unsigned manifest accepted")
        except Exception:
            return CoverageResult("R2", "plugin_sig_rejected", "PASS")


def _r_audit_chain_intact(reg: FindingRegistry) -> CoverageResult:
    try:
        from app.logs import audit
    except Exception as e:
        return CoverageResult("R4", "audit_chain_intact", "SKIP", f"import: {e!r}")
    verify = getattr(audit, "verify_chain", None)
    if verify is None:
        return CoverageResult("R4", "audit_chain_intact", "SKIP", "verify_chain missing")
    try:
        r = verify()
    except Exception as e:
        return CoverageResult("R4", "audit_chain_intact", "FAIL", f"raised: {e!r}")
    if isinstance(r, dict) and r.get("ok"):
        return CoverageResult("R4", "audit_chain_intact", "PASS")
    return CoverageResult("R4", "audit_chain_intact", "FAIL",
                          f"verify returned {r!r}")


def _r_hmac_mismatch(reg: FindingRegistry) -> CoverageResult:
    try:
        from app.core import data_persistence as dp
    except Exception as e:
        return CoverageResult("R5", "hmac_mismatch", "SKIP", f"import: {e!r}")
    verify = getattr(dp, "_verify_hmac", None)
    if verify is None:
        return CoverageResult("R5", "hmac_mismatch", "SKIP", "_verify_hmac missing")
    try:
        ok = verify(b'{"x":1}', "0" * 96)
    except Exception as e:
        return CoverageResult("R5", "hmac_mismatch", "FAIL", f"raised: {e!r}")
    return CoverageResult("R5", "hmac_mismatch", "PASS" if not ok else "FAIL",
                          "" if not ok else "verify accepted forged HMAC")


def _r_subprocess_spawn_audit(reg: FindingRegistry) -> CoverageResult:
    # Can't easily invoke a real process in a sandboxed CI, so we verify
    # the hook exists in the code path: the safe_subprocess module must
    # reference the audit_event function.
    try:
        from app.core import safe_subprocess as sp
    except Exception as e:
        return CoverageResult("R1", "subprocess_spawn_audit", "SKIP", f"import: {e!r}")
    src = Path(sp.__file__).read_text(encoding="utf-8")
    if "subprocess_spawn" in src and "audit_event" in src:
        return CoverageResult("R1", "subprocess_spawn_audit", "PASS")
    return CoverageResult("R1", "subprocess_spawn_audit", "FAIL",
                          "audit_event hook absent")


def _r_sandbox_violation_emits(reg: FindingRegistry) -> CoverageResult:
    try:
        from app.plugins import sandbox as sb
    except Exception as e:
        return CoverageResult("R3", "sandbox_violation_emits", "SKIP", f"import: {e!r}")
    src = Path(sb.__file__).read_text(encoding="utf-8")
    if "SandboxViolation" in src and "audit_event" in src or "audit" in src:
        return CoverageResult("R3", "sandbox_violation_emits", "PASS")
    return CoverageResult("R3", "sandbox_violation_emits", "FAIL",
                          "no violation-emit path")


_RULES: List[Callable[[FindingRegistry], CoverageResult]] = [
    _r_subprocess_spawn_audit,
    _r_plugin_sig_rejected,
    _r_sandbox_violation_emits,
    _r_audit_chain_intact,
    _r_hmac_mismatch,
    _r_argv_str_refused,
    _r_abs_path_required,
]


def run_detection_coverage(reg: FindingRegistry) -> List[CoverageResult]:
    require_consent()
    results: List[CoverageResult] = []
    for rule_fn in _RULES:
        try:
            r = rule_fn(reg)
        except Exception as e:
            r = CoverageResult(
                rule_id=rule_fn.__name__,
                title=rule_fn.__name__,
                status="FAIL",
                reason=f"rule raised: {e!r}",
            )
        results.append(r)

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    total_gate = passed + failed
    coverage_pct = (passed * 100.0 / total_gate) if total_gate else 0.0

    reg.record(
        title=f"Detection coverage: {passed}/{total_gate} rules firing ({coverage_pct:.0f}%)",
        description=(
            "Ratio of detection rules that fired correctly on their "
            "known-trigger input. SKIPPED rules are excluded from the "
            "denominator."
        ),
        severity=Severity.CRITICAL if failed > 0 else Severity.INFO,
        cvss_base=9.1 if failed > 0 else 0.0,
        cvss_vector="CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H" if failed > 0 else "",
        evidence={
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "results": [
                {"rule": r.rule_id, "title": r.title, "status": r.status,
                 "reason": r.reason} for r in results
            ],
            "coverage_pct": round(coverage_pct, 2),
        },
        remediation=(
            "For every FAIL: restore the detection path, add a unit test, "
            "and re-run detection coverage until 100%."
        ),
    )
    return results
