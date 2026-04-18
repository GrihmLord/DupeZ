"""
Local reconnaissance (MITRE ATT&CK TA0043, local scope only).

This module performs **read-only** inspection of the host environment
that the DupeZ process is running on. It does not connect to any
external service, does not enumerate other machines on the LAN, and
does not attempt privilege escalation.

Every check records a :class:`~app.offsec.findings.Finding` instead of
raising on issues — the point is to produce a structured report the
maintainer can review, not to fail the process.

Checks performed
----------------

* ``host_profile``       — OS, arch, Python interpreter, elevation state.
* ``authenticode_state`` — is the current process running from a signed
  binary? (Windows only; delegates to
  :func:`app.core.self_integrity.verify_self_authenticode`.)
* ``dll_search_order``   — has :func:`SetDefaultDllDirectories` been
  called? On an un-hardened process this is a CRITICAL DLL-hijack
  surface.
* ``writable_path_dirs`` — entries on ``PATH`` that the current user
  can write to. A writable PATH entry earlier than a system binary is
  a classic local privilege-escalation primitive (MITRE T1574.007).
* ``suspicious_env``     — environment variables whose names suggest
  credentials leaked into the process env (e.g. ``*_TOKEN``,
  ``*_SECRET``, ``*_PASSWORD``).
* ``loaded_modules``     — any loaded DLL / .so whose path is outside
  the expected trust anchors (system dir, our install dir, site-
  packages). Surfaces injected modules.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path
from typing import Iterable, List

from app.offsec import require_consent
from app.offsec.findings import FindingRegistry, Severity

__all__ = ["run_recon"]


# ── Helpers ────────────────────────────────────────────────────────

_SECRET_NAME_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|"
    r"ACCESS[_-]?KEY|AWS_|AZURE_|GCP_|GOOGLE_APPLICATION_CREDENTIALS|"
    r"GITHUB_TOKEN|NPM_TOKEN|PYPI_TOKEN|DOCKER_PASSWORD|SSH_PRIVATE)",
    re.IGNORECASE,
)

# Values that trip the name regex but are known-benign.
#
# DUPEZ_OFFSEC_OPERATOR_TOKEN is the tier-2 gate token for the offsec
# operator itself (see app/offsec/operator.py). It MUST be exported in
# the engagement shell — flagging it would be the tool flagging its own
# entry criterion. Noise, not signal.
_SECRET_NAME_ALLOWLIST = frozenset({
    "SECRETS_DIR",                   # XDG-style pointer, not a secret
    "PASSWORD_POLICY",
    "TOKEN_TYPE",
    "DUPEZ_OFFSEC_OPERATOR_TOKEN",   # tier-2 gate input; see operator.py
})


def _is_elevated() -> bool:
    """Best-effort check for admin / root."""
    if os.name == "nt":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _path_is_user_writable(p: Path) -> bool:
    """Return True if the current user can create/overwrite files in *p*.

    Uses an access() probe rather than DACL parsing so the check is
    portable; on Windows this implicitly checks the effective token's
    WRITE rights.
    """
    try:
        return p.is_dir() and os.access(str(p), os.W_OK)
    except OSError:
        return False


def _expected_module_roots() -> List[Path]:
    """Trust anchors for loaded-module paths."""
    roots: List[Path] = []
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot") or r"C:\Windows"
        roots.extend([
            Path(sysroot),
            Path(sysroot) / "System32",
            Path(sysroot) / "SysWOW64",
            Path(sysroot) / "WinSxS",
        ])
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            roots.append(Path(program_files))
        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        if program_files_x86:
            roots.append(Path(program_files_x86))
    else:
        roots.extend([
            Path("/lib"),
            Path("/lib64"),
            Path("/usr/lib"),
            Path("/usr/lib64"),
            Path("/usr/local/lib"),
        ])
    # Python interpreter dir, site-packages, our own install dir.
    roots.append(Path(sys.prefix))
    roots.append(Path(sys.base_prefix))
    try:
        import site
        for sp in site.getsitepackages():
            roots.append(Path(sp))
        user_site = site.getusersitepackages()
        if user_site:
            roots.append(Path(user_site))
    except Exception:
        pass
    exe = Path(sys.executable).resolve().parent
    roots.append(exe)
    roots.append(Path(__file__).resolve().parents[2])  # repo / install root
    # De-dupe, preserve order.
    seen = set()
    unique: List[Path] = []
    for r in roots:
        try:
            rp = r.resolve()
        except OSError:
            continue
        if rp not in seen:
            seen.add(rp)
            unique.append(rp)
    return unique


def _is_under_any(p: Path, roots: Iterable[Path]) -> bool:
    try:
        rp = p.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            rp.relative_to(root)
            return True
        except ValueError:
            continue
    return False


# ── Individual checks ──────────────────────────────────────────────

def _check_host_profile(reg: FindingRegistry) -> None:
    reg.record(
        title="Host profile",
        description=(
            f"DupeZ self-test running on "
            f"{platform.system()} {platform.release()} "
            f"({platform.machine()}), Python {sys.version.split()[0]}. "
            f"Elevated: {_is_elevated()}."
        ),
        severity=Severity.INFO,
        attack_technique="T1082",  # System Information Discovery
        evidence={
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "arch": platform.machine(),
            "python": sys.version,
            "python_executable": sys.executable,
            "elevated": _is_elevated(),
            "pid": os.getpid(),
        },
    )


def _check_authenticode(reg: FindingRegistry) -> None:
    if os.name != "nt":
        return
    try:
        from app.core.self_integrity import verify_self_authenticode, TrustState
    except Exception as e:
        reg.record(
            title="Authenticode check unavailable",
            description=(
                "Could not import self-integrity module to check the "
                "Authenticode signature of the running process."
            ),
            severity=Severity.LOW,
            evidence={"error": repr(e)},
        )
        return

    result = verify_self_authenticode()
    state = getattr(result, "state", None) or getattr(result, "name", str(result))
    state_name = getattr(state, "name", str(state))

    if state_name == "TRUSTED":
        reg.record(
            title="Authenticode signature: TRUSTED",
            description="The running binary is Authenticode-signed and WinVerifyTrust returns OK.",
            severity=Severity.INFO,
            evidence={"state": state_name},
        )
    elif state_name in {"UNSIGNED", "TAMPERED", "REVOKED", "EXPIRED"}:
        sev = Severity.CRITICAL if state_name in {"TAMPERED", "REVOKED"} else Severity.HIGH
        reg.record(
            title=f"Authenticode signature: {state_name}",
            description=(
                "The running binary's Authenticode signature is not in a trusted "
                f"state ({state_name}). On production builds this indicates "
                "tampering, revocation, or an unsigned drop-in replacement."
            ),
            severity=sev,
            cvss_base=7.8 if sev == Severity.HIGH else 9.1,
            cvss_vector="CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            attack_technique="T1553.002",  # Subvert Trust Controls: Code Signing
            evidence={"state": state_name},
            remediation=(
                "Rebuild and re-sign the binary from a clean source tree, or "
                "reinstall from the vendor-signed release artifact."
            ),
        )
    else:
        reg.record(
            title=f"Authenticode signature: {state_name}",
            description="WinVerifyTrust returned a non-standard state; see evidence.",
            severity=Severity.LOW,
            evidence={"state": state_name, "raw": repr(result)},
        )


def _check_dll_search_order(reg: FindingRegistry) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        # There is no direct "query default dirs" API — but calling
        # SetDefaultDllDirectories with the same flags is idempotent,
        # and we can sniff whether it SUCCEEDS with LOAD_LIBRARY_SEARCH_*
        # (it will only succeed with those flags if KB2533623 is installed
        # and the process hasn't already been locked down in an incompatible
        # way). We record the state we *would* apply.
        from app.core.self_integrity import harden_dll_search_path, DllHardeningResult
        state = harden_dll_search_path()
        if state == DllHardeningResult.APPLIED:
            reg.record(
                title="DLL search order hardened",
                description=(
                    "Process successfully called SetDefaultDllDirectories with "
                    "LOAD_LIBRARY_SEARCH_APPLICATION_DIR | SYSTEM32 | USER_DIRS."
                ),
                severity=Severity.INFO,
                evidence={"result": state.name},
            )
        else:
            reg.record(
                title="DLL search order NOT hardened",
                description=(
                    "Could not apply SetDefaultDllDirectories. The process is "
                    "exposed to DLL sideloading via CWD or PATH."
                ),
                severity=Severity.HIGH,
                cvss_base=7.8,
                cvss_vector="CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H",
                attack_technique="T1574.001",  # DLL Search Order Hijacking
                evidence={"result": state.name if hasattr(state, "name") else str(state)},
                remediation=(
                    "Call app.core.self_integrity.apply_startup_hardening() "
                    "as the first line of main() before any DLL imports."
                ),
            )
    except Exception as e:
        reg.record(
            title="DLL search order check failed",
            description="Exception during DLL search order probe.",
            severity=Severity.LOW,
            evidence={"error": repr(e)},
        )


def _check_writable_path_dirs(reg: FindingRegistry) -> None:
    path_env = os.environ.get("PATH", "")
    sep = os.pathsep
    writable: List[str] = []
    for entry in path_env.split(sep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        p = Path(entry)
        if _path_is_user_writable(p):
            # On POSIX, user-owned dirs under $HOME are expected and low-risk.
            home = Path.home()
            try:
                p.resolve().relative_to(home.resolve())
                continue  # under home — noise
            except ValueError:
                pass
            writable.append(str(p))
    if writable:
        reg.record(
            title=f"{len(writable)} writable directories on PATH",
            description=(
                "One or more PATH entries are writable by the current user. "
                "If any of these appear earlier on PATH than a system binary "
                "DupeZ invokes (netsh, arp, ipconfig, route), an attacker who "
                "controls the user account can drop a trojan binary and "
                "hijack execution."
            ),
            severity=Severity.MEDIUM,
            cvss_base=6.7,
            cvss_vector="CVSS:3.1/AV:L/AC:H/PR:L/UI:N/S:U/C:H/I:H/A:H",
            attack_technique="T1574.007",  # Path Interception by PATH Environment Variable
            evidence={"entries": writable[:32], "total": len(writable)},
            remediation=(
                "Audit PATH entries outside of $HOME. Remove any that are "
                "writable by the user. DupeZ itself resolves system binaries "
                "to %SystemRoot%\\System32 via safe_subprocess.resolve_system_binary, "
                "so DupeZ's own calls are safe — but third-party tools the user "
                "runs may not be."
            ),
        )
    else:
        reg.record(
            title="PATH is clean of user-writable entries",
            description="No user-writable directories found on PATH outside $HOME.",
            severity=Severity.INFO,
            evidence={"path_entries_scanned": len(path_env.split(sep))},
        )


def _check_suspicious_env(reg: FindingRegistry) -> None:
    hits: List[str] = []
    for name in os.environ:
        if name in _SECRET_NAME_ALLOWLIST:
            continue
        if _SECRET_NAME_RE.search(name):
            hits.append(name)
    if hits:
        # Names only — never log values.
        reg.record(
            title=f"{len(hits)} credential-shaped env vars present",
            description=(
                "The process environment contains variables whose names suggest "
                "credentials. Any child process inherits these by default, which "
                "makes them available to every binary DupeZ spawns."
            ),
            severity=Severity.MEDIUM,
            cvss_base=5.5,
            cvss_vector="CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N",
            attack_technique="T1552.001",  # Unsecured Credentials: Credentials In Files
            evidence={"names": sorted(hits)},
            remediation=(
                "Scrub the environment before spawning subprocesses that don't "
                "need these credentials. safe_subprocess.run accepts an explicit "
                "env= dict — pass a minimal environment instead of inheriting."
            ),
        )


def _check_loaded_modules(reg: FindingRegistry) -> None:
    """Flag any loaded native module outside expected trust anchors."""
    roots = _expected_module_roots()
    suspicious: List[dict] = []

    # Walk sys.modules for modules that have __file__ pointing to .dll/.so/.pyd
    for name, mod in list(sys.modules.items()):
        fn = getattr(mod, "__file__", None)
        if not fn:
            continue
        lower = fn.lower()
        if not lower.endswith((".dll", ".pyd", ".so")):
            continue
        p = Path(fn)
        if not _is_under_any(p, roots):
            suspicious.append({"module": name, "path": str(p)})

    if suspicious:
        reg.record(
            title=f"{len(suspicious)} native modules loaded from unexpected paths",
            description=(
                "One or more native modules are loaded from a directory outside "
                "the expected trust anchors (system dir, Python install, "
                "site-packages, DupeZ install dir). This may indicate DLL "
                "injection or a misconfigured search path."
            ),
            severity=Severity.HIGH,
            cvss_base=7.2,
            cvss_vector="CVSS:3.1/AV:L/AC:H/PR:L/UI:N/S:U/C:H/I:H/A:H",
            attack_technique="T1055.001",  # Process Injection: DLL
            evidence={"modules": suspicious[:32], "total": len(suspicious)},
            remediation=(
                "Investigate the listed paths. If any are in user-writable "
                "locations, treat the host as potentially compromised and run "
                "a full endpoint scan."
            ),
        )


# ── Public entrypoint ───────────────────────────────────────────

def run_recon(reg: FindingRegistry) -> None:
    """Run every recon check, recording findings into *reg*.

    The caller must have already asserted consent; this function
    re-asserts defensively.
    """
    require_consent()
    _check_host_profile(reg)
    _check_authenticode(reg)
    _check_dll_search_order(reg)
    _check_writable_path_dirs(reg)
    _check_suspicious_env(reg)
    _check_loaded_modules(reg)
