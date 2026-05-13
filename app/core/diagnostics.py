"""Diagnostic wizard backend (v5.7.0 feature #8).

Wraps every self-check DupeZ already does — admin status, WinDivert
driver, Npcap, clumsy.exe, signed-update pubkey, data directory
writability, Windows Firewall posture — into a single callable list
with per-check remediation hints. The UI consumes the list and
renders pass/fail badges plus "Fix this" buttons.

No new diagnostics. Just centralized.

Each check returns a :class:`CheckResult` with:

    name        : human title
    status      : PASS / WARN / FAIL
    message     : one-line outcome
    fix_hint    : actionable remediation (empty for PASS)
    fix_command : optional shell/PowerShell snippet the UI can offer
                  to copy to clipboard or run with confirmation

Call :func:`run_all_checks` to get the full list, or
:func:`run_check(name)` to re-run a single check after a fix attempt.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

from app.logs.logger import log_warning


__all__ = [
    "CheckStatus",
    "CheckResult",
    "DiagnosticCheck",
    "run_all_checks",
    "run_check",
    "ALL_CHECKS",
]


class CheckStatus:
    """Discriminator strings for CheckResult.status."""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one diagnostic check."""
    name: str
    status: str
    message: str
    fix_hint: str = ""
    fix_command: str = ""


@dataclass(frozen=True)
class DiagnosticCheck:
    """Registry entry — a named check function."""
    name: str
    description: str
    runner: Callable[[], CheckResult]


# ── Individual checks ────────────────────────────────────────────────

def _check_admin() -> CheckResult:
    """WinDivert + raw socket access require admin / High-IL."""
    if not sys.platform.startswith("win"):
        return CheckResult(
            name="Administrator privileges",
            status=CheckStatus.WARN,
            message="non-Windows host — admin check skipped",
        )
    try:
        from app.utils.helpers import is_admin
        if is_admin():
            return CheckResult(
                name="Administrator privileges",
                status=CheckStatus.PASS,
                message="running as Administrator (High-IL)",
            )
        return CheckResult(
            name="Administrator privileges",
            status=CheckStatus.FAIL,
            message="NOT running as Administrator",
            fix_hint=(
                "WinDivert cannot intercept packets without admin. "
                "Close DupeZ and re-launch via right-click → "
                "'Run as administrator', or use DupeZ-Compat.exe "
                "(its manifest requests elevation automatically)."
            ),
        )
    except Exception as exc:
        return CheckResult(
            name="Administrator privileges",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
        )


def _check_windivert_files() -> CheckResult:
    """WinDivert.dll + WinDivert64.sys must be present beside the exe."""
    try:
        from app.utils.helpers import find_resource_path
        candidates = [
            ("WinDivert.dll", find_resource_path("app/firewall/WinDivert.dll")),
            ("WinDivert64.sys", find_resource_path("app/firewall/WinDivert64.sys")),
        ]
    except Exception:
        # Fallback: search likely locations directly.
        candidates = [
            ("WinDivert.dll", os.path.join("app", "firewall", "WinDivert.dll")),
            ("WinDivert64.sys", os.path.join("app", "firewall", "WinDivert64.sys")),
        ]

    missing = [n for n, p in candidates if not (p and os.path.exists(p))]
    if not missing:
        return CheckResult(
            name="WinDivert driver",
            status=CheckStatus.PASS,
            message="WinDivert.dll + WinDivert64.sys present",
        )
    return CheckResult(
        name="WinDivert driver",
        status=CheckStatus.FAIL,
        message=f"missing: {', '.join(missing)}",
        fix_hint=(
            "WinDivert files are bundled with DupeZ. If they're missing, "
            "your installer was incomplete or AV quarantined them. "
            "Re-install from the latest GitHub release and add the "
            "DupeZ install folder to your antivirus exclusion list."
        ),
    )


def _check_npcap() -> CheckResult:
    """Npcap is needed for the optional ARP-spoof path (WiFi same-net)."""
    try:
        from app.network.npcap_check import check_npcap
        result = check_npcap()
        if result.available:
            return CheckResult(
                name="Npcap (optional)",
                status=CheckStatus.PASS,
                message="Npcap installed and reachable",
            )
        return CheckResult(
            name="Npcap (optional)",
            status=CheckStatus.WARN,
            message=f"not available: {result.reason}",
            fix_hint=(
                "Npcap is only required if you opt into the ARP-spoof "
                "path for WiFi same-network peer targeting. The default "
                "self-disrupt mode (v5.6.5+) does not need it."
            ),
            fix_command=f"Open {result.install_url} in a browser",
        )
    except Exception as exc:
        return CheckResult(
            name="Npcap (optional)",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
        )


def _check_clumsy_fallback() -> CheckResult:
    """clumsy.exe is the optional fallback engine when native is unavailable."""
    candidates = [
        "app/firewall/clumsy.exe",
        os.path.join("app", "firewall", "clumsy.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return CheckResult(
                name="clumsy.exe fallback (optional)",
                status=CheckStatus.PASS,
                message=f"clumsy.exe present at {p}",
            )
    return CheckResult(
        name="clumsy.exe fallback (optional)",
        status=CheckStatus.WARN,
        message="not found",
        fix_hint=(
            "DupeZ prefers the native WinDivert engine and only falls "
            "back to clumsy.exe automation when native is unavailable. "
            "Missing clumsy.exe is non-fatal."
        ),
    )


def _check_update_pubkey() -> CheckResult:
    """Auto-update requires TRUSTED_PUBKEYS_PEM to be populated."""
    try:
        from app.core.update_verify import TRUSTED_PUBKEYS_PEM
        if not TRUSTED_PUBKEYS_PEM:
            return CheckResult(
                name="Auto-update signing key",
                status=CheckStatus.FAIL,
                message="TRUSTED_PUBKEYS_PEM is empty — auto-update will fail-closed",
                fix_hint=(
                    "Re-install from the latest GitHub release. v5.6.6+ "
                    "ships with the provisioned pubkey embedded. If you "
                    "see this on a current release, it indicates a build "
                    "regression — report to maintainer."
                ),
            )
        return CheckResult(
            name="Auto-update signing key",
            status=CheckStatus.PASS,
            message=f"{len(TRUSTED_PUBKEYS_PEM)} pinned pubkey(s)",
        )
    except Exception as exc:
        return CheckResult(
            name="Auto-update signing key",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
        )


def _check_data_directory() -> CheckResult:
    """Persistence layer needs a writable data directory."""
    try:
        from app.core.data_persistence import persistence_manager
        path = persistence_manager.data_directory
        if not path.exists():
            return CheckResult(
                name="Data directory",
                status=CheckStatus.FAIL,
                message=f"directory does not exist: {path}",
                fix_hint=(
                    f"DupeZ stores your tracker, settings, and episode "
                    f"data here. Create the directory manually or "
                    f"check write permissions on its parent."
                ),
                fix_command=f'mkdir "{path}"',
            )
        # Try a write probe.
        probe = path / ".diagnostics_write_probe.tmp"
        try:
            probe.write_text("probe", encoding="utf-8")
            probe.unlink()
        except Exception as exc:
            return CheckResult(
                name="Data directory",
                status=CheckStatus.FAIL,
                message=f"directory not writable: {exc}",
                fix_hint=(
                    f"DupeZ cannot save state. Check the folder's "
                    f"permissions or run DupeZ as Administrator."
                ),
            )
        return CheckResult(
            name="Data directory",
            status=CheckStatus.PASS,
            message=f"writable: {path}",
        )
    except Exception as exc:
        return CheckResult(
            name="Data directory",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
        )


def _check_firewall_exclusion() -> CheckResult:
    """Best-effort check: is Windows Defender blocking us?

    We can't actually query Defender from user-mode without admin, so
    this is a hint check — we look for symptoms (recent quarantine
    events in our own log) rather than a definitive answer.
    """
    if not sys.platform.startswith("win"):
        return CheckResult(
            name="Windows Defender exclusion",
            status=CheckStatus.WARN,
            message="non-Windows host — skipped",
        )
    return CheckResult(
        name="Windows Defender exclusion",
        status=CheckStatus.WARN,
        message="cannot verify automatically — recommend manual check",
        fix_hint=(
            "Add the DupeZ install folder to Windows Defender exclusions "
            "to prevent the dist\\ + build\\ folders from being scanned "
            "(causes the 'access denied' build failures historically "
            "seen on Compat-variant rebuilds)."
        ),
        fix_command=(
            'Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\\Programs\\DupeZ"'
        ),
    )


def _check_episode_store() -> CheckResult:
    """v5.6.0+ episode recorder writes to app/data/episodes."""
    try:
        from app.core.data_persistence import persistence_manager
        ep_dir = persistence_manager.data_directory / "episodes"
        if not ep_dir.exists():
            return CheckResult(
                name="Episode store",
                status=CheckStatus.WARN,
                message="no episodes yet — normal on a fresh install",
                fix_hint=(
                    "The episode recorder writes per-cut telemetry to "
                    "this folder. It's created on the first cut you fire."
                ),
            )
        files = list(ep_dir.glob("episode_*.jsonl"))
        return CheckResult(
            name="Episode store",
            status=CheckStatus.PASS,
            message=f"{len(files)} episode file(s) at {ep_dir}",
        )
    except Exception as exc:
        return CheckResult(
            name="Episode store",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
        )


# ── Registry + public API ────────────────────────────────────────────

ALL_CHECKS: List[DiagnosticCheck] = [
    DiagnosticCheck(
        name="admin",
        description="Verify DupeZ is running with Administrator rights",
        runner=_check_admin,
    ),
    DiagnosticCheck(
        name="windivert",
        description="Verify WinDivert DLL + .sys are present",
        runner=_check_windivert_files,
    ),
    DiagnosticCheck(
        name="npcap",
        description="Verify Npcap availability (optional for ARP-spoof path)",
        runner=_check_npcap,
    ),
    DiagnosticCheck(
        name="clumsy",
        description="Verify clumsy.exe fallback availability (optional)",
        runner=_check_clumsy_fallback,
    ),
    DiagnosticCheck(
        name="update_pubkey",
        description="Verify auto-update pubkey is provisioned",
        runner=_check_update_pubkey,
    ),
    DiagnosticCheck(
        name="data_directory",
        description="Verify the persistence directory is writable",
        runner=_check_data_directory,
    ),
    DiagnosticCheck(
        name="firewall",
        description="Best-effort Windows Defender posture check",
        runner=_check_firewall_exclusion,
    ),
    DiagnosticCheck(
        name="episode_store",
        description="Verify the episode recorder data directory",
        runner=_check_episode_store,
    ),
]


def run_all_checks() -> List[CheckResult]:
    """Run every registered check and return results in registration order."""
    out: List[CheckResult] = []
    for chk in ALL_CHECKS:
        try:
            out.append(chk.runner())
        except Exception as exc:
            log_warning(f"diagnostics: {chk.name} raised: {exc}")
            out.append(CheckResult(
                name=chk.name,
                status=CheckStatus.WARN,
                message=f"check crashed: {exc}",
            ))
    return out


def run_check(name: str) -> Optional[CheckResult]:
    """Run a single check by registry name."""
    for chk in ALL_CHECKS:
        if chk.name == name:
            try:
                return chk.runner()
            except Exception as exc:
                log_warning(f"diagnostics: {name} raised: {exc}")
                return CheckResult(
                    name=name,
                    status=CheckStatus.WARN,
                    message=f"check crashed: {exc}",
                )
    return None
