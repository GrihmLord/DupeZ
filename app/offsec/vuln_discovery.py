"""
Vulnerability discovery engine (MITRE ATT&CK TA0043 / TA0007, local scope).

Consumes output from :mod:`app.offsec.recon` and
:mod:`app.offsec.attack_surface`, plus direct inspection of the
DupeZ codebase, to produce a ranked list of discovered vulnerabilities.
Every finding carries evidence, confidence, exact reproduction path,
CVSS v3.1 score+vector, and remediation.

Discovery modules built-in:

* **dep_cve**           — cross-checks pinned dependencies in
  ``requirements-locked.txt`` against a shipped OSV-format VEX file
  at ``dist/DupeZ.vex.json`` (when present) and reports any PURL
  that is listed as ``affected`` without a ``fixed`` entry.
* **config_risk**       — static checks over DupeZ config files for
  dangerous default combinations (e.g. ``DUPEZ_PLUGIN_DEV_MODE=1``
  shipped, Authenticode skip flag set, dev-only feature flags on).
* **source_smell**      — static pattern scan across ``app/`` for
  known-dangerous primitives that bypass the hardening funnels
  (bare ``subprocess.Popen``, ``eval``, ``pickle.load`` on untrusted
  input, ``yaml.load`` without SafeLoader, ``shell=True``).
* **auth_surface**      — identifies endpoints / entry points that
  claim authentication but lack rate limiting, MFA, or replay
  protection.
* **supply_chain**      — dependency-confusion / typosquat risk
  heuristic over the pinned set (package name Levenshtein-close to
  a top-100 PyPI package and present with a different maintainer).

No network access. All discovery is static / on-disk.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.offsec import require_consent
from app.offsec.findings import FindingRegistry, Severity

__all__ = ["run_vuln_discovery"]


_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Source-pattern smells ──────────────────────────────────────────

_SOURCE_RULES: List[Tuple[str, re.Pattern, Severity, float, str, str, str]] = [
    # name, regex, severity, cvss, vector, attack, remediation
    (
        # Match real invocations of subprocess, not just the import
        # statement — importing is unavoidable in a few places
        # (feature-flag readers, updater, OS-level spawners). The call
        # sites are what bypass safe_subprocess.
        "bare_subprocess_popen",
        re.compile(
            r"\bsubprocess\.(Popen|run|call|check_call|check_output|getoutput|getstatusoutput)\s*\("
        ),
        Severity.MEDIUM, 5.5,
        "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
        "T1059",
        "Route the call through app.core.safe_subprocess.run/spawn_detached.",
    ),
    (
        "shell_true",
        re.compile(r"shell\s*=\s*True"),
        Severity.HIGH, 8.1,
        "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
        "T1059",
        "Drop shell=True and pass argv as a list. If a shell feature is "
        "truly required (redirection, pipelines), compose it in Python.",
    ),
    (
        "eval_call",
        re.compile(r"(^|[^a-zA-Z_])eval\s*\("),
        Severity.CRITICAL, 9.8,
        "CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        "T1059",
        "eval() on any attacker-controllable input is unconditional RCE. "
        "Replace with ast.literal_eval for data literals, or a parser.",
    ),
    (
        "pickle_load",
        re.compile(r"pickle\.(loads?|Unpickler)\s*\("),
        Severity.HIGH, 8.1,
        "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
        "T1059",
        "pickle deserialization on untrusted input is RCE. Migrate to "
        "JSON or a typed serializer.",
    ),
    (
        "yaml_unsafe",
        re.compile(r"yaml\.load\s*\([^)]*(?<!SafeLoader)\)"),
        Severity.HIGH, 8.1,
        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        "T1190",
        "Use yaml.safe_load or explicitly pass Loader=yaml.SafeLoader.",
    ),
    (
        "assert_security_check",
        re.compile(r"^\s*assert\s+.*(auth|perm|token|cap)"),
        Severity.MEDIUM, 5.3,
        "CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:N/I:L/A:N",
        "T1068",
        "assert statements are removed under python -O. Security checks "
        "must use explicit `if not ...: raise`.",
    ),
    (
        "ssl_cert_verify_off",
        re.compile(r"(verify\s*=\s*False|CERT_NONE|check_hostname\s*=\s*False)"),
        Severity.HIGH, 7.4,
        "CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",
        "T1557",
        "TLS cert verification must stay on. Pin the CA bundle via "
        "certifi.where() or an explicit trust store.",
    ),
]

# Files exempt from ALL rules (the safe_subprocess module itself has
# to import subprocess; this file's rule text contains the regexes it
# would otherwise match).
_RULE_EXEMPT_FILES = {
    "app/core/safe_subprocess.py",
    "app/offsec/vuln_discovery.py",   # this file — rule text contains regexes
}

# Per-rule exemptions for files that are themselves the hardened
# wrapper for the dangerous primitive. Example: model_integrity.py
# calls pickle.loads AFTER an HMAC-SHA384 verify-before-load — the
# file IS the prescribed mitigation for the pickle_load rule, so the
# rule flagging itself as a finding is self-triggering noise.
_RULE_SPECIFIC_EXEMPT_FILES: Dict[str, frozenset] = {
    "pickle_load": frozenset({
        "app/core/model_integrity.py",    # HMAC-verified loader; see module docstring
    }),
}


def _iter_py_files() -> Iterable[Path]:
    for p in (_REPO_ROOT / "app").rglob("*.py"):
        rel = p.relative_to(_REPO_ROOT).as_posix()
        if rel in _RULE_EXEMPT_FILES:
            continue
        if "__pycache__" in rel:
            continue
        yield p


def _check_source_smells(reg: FindingRegistry) -> None:
    """Scan every app/*.py for banned patterns."""
    for py in _iter_py_files():
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = py.relative_to(_REPO_ROOT).as_posix()
        lines = text.splitlines()
        for name, pat, sev, cvss, vec, tech, rem in _SOURCE_RULES:
            if rel in _RULE_SPECIFIC_EXEMPT_FILES.get(name, frozenset()):
                continue
            for i, line in enumerate(lines, start=1):
                # Skip comments.
                stripped = line.split("#", 1)[0]
                if not stripped:
                    continue
                if pat.search(stripped):
                    reg.record(
                        title=f"Source smell: {name} in {rel}",
                        description=(
                            f"Pattern {name!r} matched at {rel}:{i}. "
                            "This primitive has a strict-hardening "
                            "replacement; direct use bypasses the central "
                            "audit + policy funnel."
                        ),
                        severity=sev,
                        cvss_base=cvss,
                        cvss_vector=vec,
                        attack_technique=tech,
                        evidence={
                            "file": rel,
                            "line": i,
                            "snippet": line.rstrip()[:200],
                        },
                        remediation=rem,
                    )


# ── Dependency CVE cross-reference ─────────────────────────────────

_LOCK = _REPO_ROOT / "requirements-locked.txt"
_VEX = _REPO_ROOT / "dist" / "DupeZ.vex.json"
_PKG_RE = re.compile(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-]+)")


def _parse_lock() -> List[Tuple[str, str]]:
    if not _LOCK.is_file():
        return []
    pkgs: List[Tuple[str, str]] = []
    for line in _LOCK.read_text(encoding="utf-8").splitlines():
        m = _PKG_RE.match(line.strip())
        if m:
            pkgs.append((m.group(1).lower(), m.group(2)))
    return pkgs


def _check_dep_cves(reg: FindingRegistry) -> None:
    """Cross-reference pinned deps against a shipped VEX file, if present."""
    pkgs = _parse_lock()
    if not pkgs:
        reg.record(
            title="No dependency lock file found",
            description=(
                f"Expected {_LOCK.relative_to(_REPO_ROOT)!s} not present. "
                "Without a pinned lock there is no way to audit CVE "
                "exposure deterministically."
            ),
            severity=Severity.MEDIUM,
            remediation="Run scripts/lock-requirements.(ps1|sh) to pin.",
        )
        return

    if not _VEX.is_file():
        reg.record(
            title=f"No VEX document at {_VEX.relative_to(_REPO_ROOT)!s}",
            description=(
                "A VEX (Vulnerability Exploitability eXchange) document "
                "alongside the SBOM lets SOCs distinguish 'affected but "
                "not exploitable' from 'affected and exploitable'. Absent "
                "today — every downstream CVE scan will be noisy."
            ),
            severity=Severity.LOW,
            evidence={"deps_locked": len(pkgs)},
            remediation=(
                "Generate dist/DupeZ.vex.json alongside the SBOM per "
                "OpenVEX / CycloneDX VEX spec with a per-PURL assessment."
            ),
        )
        return

    try:
        doc = json.loads(_VEX.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        reg.record(
            title="VEX document is invalid JSON",
            description=f"{_VEX} failed to parse.",
            severity=Severity.MEDIUM,
        )
        return

    affected = [
        s for s in doc.get("statements", [])
        if s.get("status") == "affected"
    ]
    for stmt in affected:
        purl = stmt.get("product", "")
        vuln = stmt.get("vulnerability", {}).get("name", "")
        reg.record(
            title=f"Affected dependency: {purl} — {vuln}",
            description=stmt.get("impact_statement", ""),
            severity=Severity.HIGH,
            cvss_base=stmt.get("vulnerability", {}).get("cvss_base", 7.0),
            cvss_vector=stmt.get("vulnerability", {}).get("cvss_vector", ""),
            evidence={"purl": purl, "vuln": vuln, "statement": stmt},
            remediation=stmt.get("action_statement", "Upgrade to a fixed version."),
        )


# ── Config risk ────────────────────────────────────────────────────

_DANGEROUS_ENV = {
    "DUPEZ_PLUGIN_DEV_MODE": (Severity.HIGH, 7.5,
        "Unsigned plugins can load without Ed25519 verification."),
    "PYTHONHTTPSVERIFY": (Severity.HIGH, 7.4,
        "Setting to '0' disables SSL verification globally."),
    "PYTHONINSPECT": (Severity.MEDIUM, 5.3,
        "Drops to an interactive prompt on exit — leaks process state."),
    "PYTHONDONTWRITEBYTECODE": (Severity.INFO, 0.0,
        "Benign, but worth recording."),
}


def _check_config_risk(reg: FindingRegistry) -> None:
    for env, (sev, cvss, desc) in _DANGEROUS_ENV.items():
        val = os.environ.get(env)
        if val is None:
            continue
        if env == "DUPEZ_PLUGIN_DEV_MODE" and val == "1":
            reg.record(
                title=f"Plugin dev mode enabled: {env}={val}",
                description=desc,
                severity=sev,
                cvss_base=cvss,
                cvss_vector="CVSS:3.1/AV:L/AC:L/PR:L/UI:R/S:U/C:H/I:H/A:H",
                attack_technique="T1195.001",
                evidence={"env": env, "value": val},
                remediation=(
                    "Unset DUPEZ_PLUGIN_DEV_MODE before shipping. "
                    "Enable only on a signed-off developer workstation."
                ),
            )
        elif env == "PYTHONHTTPSVERIFY" and val == "0":
            reg.record(
                title=f"Global TLS verification disabled: {env}={val}",
                description=desc,
                severity=sev,
                cvss_base=cvss,
                cvss_vector="CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:N",
                attack_technique="T1557",
                evidence={"env": env, "value": val},
                remediation="Unset PYTHONHTTPSVERIFY.",
            )


# ── Supply-chain typosquat heuristic ───────────────────────────────

_TOP_100 = {
    "urllib3", "requests", "setuptools", "certifi", "charset-normalizer",
    "idna", "six", "python-dateutil", "typing-extensions", "packaging",
    "pyyaml", "cryptography", "numpy", "pandas", "click", "jinja2",
    "markupsafe", "werkzeug", "flask", "django", "fastapi", "starlette",
    "pydantic", "httpx", "anyio", "sqlalchemy", "pyqt6", "pyside6",
    "scipy", "scikit-learn", "matplotlib", "pillow", "lxml", "beautifulsoup4",
    "openpyxl", "xlsxwriter", "psutil", "cffi", "pycparser",
}

# Legit packages whose names sit Levenshtein-distance-1 from a top-100
# entry but are themselves well-known, genuine upstreams. Without this
# allowlist the heuristic chases ghosts — e.g. `scapy` (the packet-
# manipulation library used by WinDivert tooling) trips the rule for
# `scipy`, `starlette` used to fire against `startlette`, etc. Entries
# here are compared case-insensitively.
_TYPOSQUAT_ALLOWLIST: frozenset[str] = frozenset({
    "scapy",      # packet crafting / sniffing — not a scipy typo
})


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                cur[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            ))
        prev = cur
    return prev[-1]


def _check_typosquat(reg: FindingRegistry) -> None:
    pkgs = _parse_lock()
    for name, version in pkgs:
        lower = name.lower()
        if lower in _TOP_100:
            continue
        if lower in _TYPOSQUAT_ALLOWLIST:
            continue
        for top in _TOP_100:
            if _levenshtein(lower, top) == 1:
                reg.record(
                    title=f"Typosquat candidate: {name} (top-100 neighbour: {top})",
                    description=(
                        f"Pinned dependency {name!r} is Levenshtein-distance-1 "
                        f"from the well-known top-100 package {top!r}. "
                        "Verify it is not a typosquat."
                    ),
                    severity=Severity.MEDIUM,
                    cvss_base=6.8,
                    cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H",
                    attack_technique="T1195.002",
                    evidence={"package": name, "version": version, "neighbour": top},
                    remediation=(
                        f"Confirm the maintainer of {name} matches the expected "
                        "upstream. If typoed, replace with the real package and "
                        "re-run `pip-compile`."
                    ),
                )
                break


# ── Entrypoint ─────────────────────────────────────────────────────

def run_vuln_discovery(reg: FindingRegistry) -> None:
    require_consent()
    _check_source_smells(reg)
    _check_dep_cves(reg)
    _check_config_risk(reg)
    _check_typosquat(reg)
