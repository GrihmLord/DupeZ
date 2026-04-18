"""
Adversarial simulation engine — multi-step MITRE ATT&CK playbooks.

Chains the single-purpose modules in this package into full
scenario walkthroughs. Every playbook is **atomic, scope-validated,
and logged end-to-end**: a start state, a target outcome, a
step-by-step execution log, and a boolean result that records
whether the objective was reached.

Playbooks:

* ``initial_access_webapp``    — simulates the web-surface initial-
  access chain by triggering recon + vuln_discovery with a focus on
  HTTP/API smells.
* ``supply_chain_compromise``  — runs the typosquat / VEX / lock-
  absence checks.
* ``lateral_movement_creduse`` — maps reachable credential stores
  and same-user processes.
* ``privilege_escalation``     — enumerates writable PATH, autostart
  surfaces, and dangerous env vars that could elevate an attacker.
* ``exfil_via_permitted_egress`` — identifies egress channels a
  compromised process could abuse without tripping existing
  detections.
* ``persistence_via_legit``    — maps the autostart / scheduled-task
  surfaces a compromised process could use.

Every playbook composes existing module functions — no new
external-target capability is introduced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List

from app.offsec import require_consent
from app.offsec.findings import FindingRegistry, Severity
from app.offsec import recon, attack_surface, vuln_discovery, post_exploit

__all__ = [
    "PlaybookResult",
    "run_playbook",
    "list_playbooks",
]


@dataclass(frozen=True)
class PlaybookResult:
    name: str
    achieved: bool
    start_state: str
    target_outcome: str
    steps: List[str]
    finding_count_delta: int


def _playbook_initial_access_webapp(reg: FindingRegistry) -> PlaybookResult:
    before = len(reg.all())
    steps: List[str] = []
    steps.append("recon: host profile + loaded modules")
    recon._check_host_profile(reg)           # public via module, unde
    recon._check_loaded_modules(reg)
    steps.append("vuln_discovery: source smells (ssl/yaml/eval)")
    vuln_discovery._check_source_smells(reg)
    after = len(reg.all())
    critical = sum(1 for f in reg.all()[before:] if f.severity == Severity.CRITICAL)
    return PlaybookResult(
        name="initial_access_webapp",
        achieved=critical > 0,
        start_state="unauthenticated external caller",
        target_outcome="identify an HTTP/API path to RCE in DupeZ",
        steps=steps,
        finding_count_delta=after - before,
    )


def _playbook_supply_chain(reg: FindingRegistry) -> PlaybookResult:
    before = len(reg.all())
    steps = ["parse requirements-locked.txt",
             "cross-reference VEX document",
             "typosquat Levenshtein scan"]
    vuln_discovery._check_dep_cves(reg)
    vuln_discovery._check_typosquat(reg)
    after = len(reg.all())
    high_plus = sum(1 for f in reg.all()[before:]
                    if f.severity in (Severity.CRITICAL, Severity.HIGH))
    return PlaybookResult(
        name="supply_chain_compromise",
        achieved=high_plus > 0,
        start_state="attacker controls a PyPI namespace",
        target_outcome="DupeZ pins a vulnerable / typosquatted package",
        steps=steps,
        finding_count_delta=after - before,
    )


def _playbook_lateral_movement(reg: FindingRegistry) -> PlaybookResult:
    before = len(reg.all())
    steps = ["enumerate same-user processes",
             "map reachable credential stores"]
    post_exploit._lateral_movement(reg)
    post_exploit._data_reach(reg)
    after = len(reg.all())
    new = reg.all()[before:]
    achieved = any(f.severity in (Severity.HIGH, Severity.CRITICAL) for f in new)
    return PlaybookResult(
        name="lateral_movement_creduse",
        achieved=achieved,
        start_state="compromised DupeZ process, same-user context",
        target_outcome="read other-process credentials",
        steps=steps,
        finding_count_delta=after - before,
    )


def _playbook_privilege_escalation(reg: FindingRegistry) -> PlaybookResult:
    before = len(reg.all())
    steps = ["writable PATH entries",
             "authenticode state",
             "dangerous env vars",
             "DLL search order"]
    recon._check_writable_path_dirs(reg)
    recon._check_authenticode(reg)
    vuln_discovery._check_config_risk(reg)
    recon._check_dll_search_order(reg)
    after = len(reg.all())
    new = reg.all()[before:]
    achieved = any(f.severity in (Severity.HIGH, Severity.CRITICAL) for f in new)
    return PlaybookResult(
        name="privilege_escalation",
        achieved=achieved,
        start_state="standard-user code execution",
        target_outcome="SYSTEM / root via DupeZ spawn or DLL hijack",
        steps=steps,
        finding_count_delta=after - before,
    )


def _playbook_exfil_egress(reg: FindingRegistry) -> PlaybookResult:
    before = len(reg.all())
    steps = ["enumerate listeners",
             "note permitted egress channels in env"]
    attack_surface._check_listeners(reg)
    recon._check_suspicious_env(reg)
    after = len(reg.all())
    new = reg.all()[before:]
    achieved = any(f.severity in (Severity.HIGH, Severity.MEDIUM, Severity.CRITICAL) for f in new)
    return PlaybookResult(
        name="exfil_via_permitted_egress",
        achieved=achieved,
        start_state="compromised DupeZ process with user-network access",
        target_outcome="exfiltrate data without tripping egress filters",
        steps=steps,
        finding_count_delta=after - before,
    )


def _playbook_persistence(reg: FindingRegistry) -> PlaybookResult:
    before = len(reg.all())
    steps = ["map autostart surfaces"]
    post_exploit._persistence_surfaces(reg)
    after = len(reg.all())
    new = reg.all()[before:]
    achieved = any(f.severity in (Severity.HIGH, Severity.MEDIUM, Severity.CRITICAL) for f in new)
    return PlaybookResult(
        name="persistence_via_legit",
        achieved=achieved,
        start_state="user-level code execution",
        target_outcome="survive reboot without admin",
        steps=steps,
        finding_count_delta=after - before,
    )


_PLAYBOOKS: Dict[str, Callable[[FindingRegistry], PlaybookResult]] = {
    "initial_access_webapp":       _playbook_initial_access_webapp,
    "supply_chain_compromise":     _playbook_supply_chain,
    "lateral_movement_creduse":    _playbook_lateral_movement,
    "privilege_escalation":        _playbook_privilege_escalation,
    "exfil_via_permitted_egress":  _playbook_exfil_egress,
    "persistence_via_legit":       _playbook_persistence,
}


def list_playbooks() -> List[str]:
    return list(_PLAYBOOKS)


def run_playbook(name: str, reg: FindingRegistry) -> PlaybookResult:
    require_consent()
    fn = _PLAYBOOKS.get(name)
    if fn is None:
        raise KeyError(f"unknown playbook: {name!r}; known: {list(_PLAYBOOKS)}")
    result = fn(reg)
    reg.record(
        title=f"Playbook '{name}' — {'OBJECTIVE_ACHIEVED' if result.achieved else 'OBJECTIVE_NOT_ACHIEVED'}",
        description=(
            f"Start: {result.start_state}. "
            f"Target: {result.target_outcome}. "
            f"Steps: {', '.join(result.steps)}. "
            f"Findings delta: {result.finding_count_delta}."
        ),
        severity=Severity.INFO if not result.achieved else Severity.MEDIUM,
        attack_technique="",
        evidence={
            "playbook": name,
            "achieved": result.achieved,
            "steps": result.steps,
            "findings_added": result.finding_count_delta,
        },
    )
    return result
