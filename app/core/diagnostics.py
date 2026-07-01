"""Diagnostic wizard backend (v5.7.0 feature #8).

Wraps every self-check DupeZ already does — admin status, WinDivert
driver, Npcap, clumsy.exe, signed-update pubkey, data directory
writability, Windows Firewall posture — into a single callable list
with per-check remediation hints. The UI consumes the list and
renders pass/fail badges plus "Fix this" buttons.

Each check returns a :class:`CheckResult` with:

    name        : human title
    status      : PASS / WARN / FAIL
    message     : one-line outcome
    fix_hint    : actionable remediation (empty for PASS)
    fix_command : optional shell/PowerShell snippet — see SECURITY below

Call :func:`run_all_checks` to get the full list, or
:func:`run_check(name)` to re-run a single check after a fix attempt.

SECURITY CONTRACT — fix_command (v5.7.3)
----------------------------------------
``fix_command`` is a HUMAN-FACING SUGGESTION ONLY. The UI may display
it and offer a "copy to clipboard" affordance. The UI MUST NOT execute
it — not via ``subprocess``, not via ``os.system``, not via the
safe-subprocess wrapper, not on a button click, not automatically.

Rationale: every fix_command string in this module is a compile-time
constant, so today there is no injection vector. But a future check
could compute a fix_command from a path or environment value; if the
UI auto-ran it, that would become a command-injection sink. Keeping
the "display only, never execute" rule absolute means no future check
author can accidentally open that hole. Remediation is the operator's
deliberate action, performed in their own shell.
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
            "Re-install from the latest signed GitHub release, verify the "
            "published hashes, and investigate the quarantine event. Do not "
            "create a broad antivirus exclusion."
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


def _check_secret_store() -> CheckResult:
    """Secret-store directory must be reachable for durable HMAC keys."""
    from app.core.secret_store import check_store_health

    health = check_store_health()
    if health.healthy:
        return CheckResult(
            name="Secret store",
            status=CheckStatus.PASS,
            message=f"writable: {health.path}",
        )
    location = health.safe_path or "%LOCALAPPDATA%\\DupeZ\\secrets"
    error = health.safe_error or health.error or "unknown error"
    return CheckResult(
        name="Secret store",
        status=CheckStatus.FAIL,
        message=f"secret store unavailable at {location}: {error}",
        fix_hint=(
            "DupeZ cannot reliably persist audit and data-integrity keys. "
            f"{health.remediation_hint}"
        ),
    )


def _check_persistence_key() -> CheckResult:
    """Persistence HMAC should use the durable secret-store key."""
    try:
        from app.core.data_persistence import persistence_key_degraded
        if persistence_key_degraded():
            return CheckResult(
                name="Persistence integrity key",
                status=CheckStatus.WARN,
                message="using legacy machine-derived fallback key",
                fix_hint=(
                    "Persistence integrity still works, but it is weaker "
                    "than the secret-store-backed design. Repair the secret "
                    "store and restart DupeZ so data files are re-signed "
                    "under the durable per-install key."
                ),
            )
        return CheckResult(
            name="Persistence integrity key",
            status=CheckStatus.PASS,
            message="secret-store-backed HMAC key active",
        )
    except Exception as exc:
        return CheckResult(
            name="Persistence integrity key",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
            fix_hint=(
                "Run the Secret store diagnostic first; persistence key "
                "health depends on that storage layer."
            ),
        )


def _check_audit_chain() -> CheckResult:
    """Audit log should be unsealed, non-degraded, and verifiable."""
    try:
        from app.logs.audit import get_audit_logger
        audit = get_audit_logger()
        valid, count, error = audit.verify_chain()
        if audit.is_sealed():
            return CheckResult(
                name="Audit chain",
                status=CheckStatus.FAIL,
                message="audit logger is sealed after a tamper signal",
                fix_hint=(
                    "Investigate the audit files first. Then run "
                    "`python -m app.cli recovery audit-status` and, only "
                    "after preserving evidence, reset with "
                    "`python -m app.cli recovery reset-audit --apply`."
                ),
            )
        if not valid:
            return CheckResult(
                name="Audit chain",
                status=CheckStatus.FAIL,
                message=f"audit chain failed after {count} entries: {error}",
                fix_hint=(
                    "Treat this as a possible tamper or key-loss event. "
                    "Preserve the audit directory before resetting the chain "
                    "through the recovery CLI."
                ),
            )
        if audit.degraded:
            return CheckResult(
                name="Audit chain",
                status=CheckStatus.WARN,
                message=f"chain verifies, but audit key is degraded ({count} entries)",
                fix_hint=(
                    "The audit logger is using an ephemeral key because the "
                    "secret store was unavailable. Repair the secret store "
                    "and restart DupeZ to restore cross-run verification."
                ),
            )
        return CheckResult(
            name="Audit chain",
            status=CheckStatus.PASS,
            message=f"verified {count} audit entr{'y' if count == 1 else 'ies'}",
        )
    except Exception as exc:
        return CheckResult(
            name="Audit chain",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
            fix_hint=(
                "Run `python -m app.cli recovery audit-status` for a focused "
                "audit report."
            ),
        )


def _check_firewall_exclusion() -> CheckResult:
    """Report safe endpoint-protection guidance without weakening Defender."""
    if not sys.platform.startswith("win"):
        return CheckResult(
            name="Windows Defender posture",
            status=CheckStatus.WARN,
            message="non-Windows host — skipped",
        )
    try:
        from app.core.defender_posture import query_defender_posture
        posture = query_defender_posture()
    except Exception as exc:
        return CheckResult(
            name="Windows Defender posture",
            status=CheckStatus.WARN,
            message=f"Defender posture check failed: {exc}",
            fix_hint=(
                "Do not add broad Defender exclusions. Rebuild from a clean "
                "tree, verify bundled-binary hashes, and inspect the local "
                "Protection History entry for the exact detection name."
            ),
        )

    if not posture.available:
        return CheckResult(
            name="Windows Defender posture",
            status=CheckStatus.WARN,
            message=posture.message,
            fix_hint=(
                "Defender status could not be queried. Keep endpoint "
                "protection enabled, then verify release hashes, bundled "
                "binary provenance, and Authenticode signatures manually."
            ),
        )

    details: list[str] = [posture.message]
    if posture.latest_threat_name:
        details.append(f"latest threat: {posture.latest_threat_name}")
    if posture.latest_detection_time:
        details.append(f"at {posture.latest_detection_time}")
    status = CheckStatus.WARN if posture.status == "warn" else CheckStatus.PASS
    return CheckResult(
        name="Windows Defender posture",
        status=status,
        message="; ".join(details),
        fix_hint=(
            "If Defender is blocking DupeZ, treat it as evidence first: "
            "confirm the detection name in Protection History, verify "
            "packaging/binary-provenance.json, run release preflight, and "
            "ship a signed non-UPX build. Avoid broad exclusions."
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


def _check_operation_journal() -> CheckResult:
    """Report whether a prior run left network state requiring recovery."""
    try:
        from app.core.operation_journal import OperationJournal
        journal = OperationJournal()
        if journal.is_pending():
            return CheckResult(
                name="Network recovery journal",
                status=CheckStatus.FAIL,
                message="pending network-state restoration detected",
                fix_hint=(
                    "Restart DupeZ with the required privileges. Startup will "
                    "stop packet operations and remove DupeZ firewall rules "
                    "before enabling background services."
                ),
            )
        return CheckResult(
            name="Network recovery journal",
            status=CheckStatus.PASS,
            message="no pending crash-recovery marker",
        )
    except Exception as exc:
        return CheckResult(
            name="Network recovery journal",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
        )


def _check_runtime_storage() -> CheckResult:
    """Verify installed builds separate mutable state from binaries."""
    try:
        from app.core.app_paths import (
            config_dir,
            data_dir,
            ensure_runtime_migration,
            is_installed_runtime,
            legacy_runtime_root,
        )

        if not is_installed_runtime():
            return CheckResult(
                name="Runtime storage separation",
                status=CheckStatus.PASS,
                message="source checkout uses explicit development paths",
            )
        results = ensure_runtime_migration() or ()
        errors = [
            error
            for result in results
            for error in result.errors
        ]
        conflicts = [
            conflict
            for result in results
            for conflict in result.conflicts
        ]
        binary_root = legacy_runtime_root().resolve()
        mutable_roots = [data_dir().resolve(), config_dir().resolve()]
        if any(root == binary_root or binary_root in root.parents for root in mutable_roots):
            return CheckResult(
                name="Runtime storage separation",
                status=CheckStatus.FAIL,
                message="mutable state still resolves beneath the binary directory",
                fix_hint=(
                    "Set a writable per-user LOCALAPPDATA location and restart "
                    "DupeZ before running active operations."
                ),
            )
        if errors:
            return CheckResult(
                name="Runtime storage separation",
                status=CheckStatus.FAIL,
                message=f"legacy migration has {len(errors)} copy error(s)",
                fix_hint=(
                    "Preserve the legacy app/data and app/config folders, "
                    "repair per-user storage permissions, then restart to retry."
                ),
            )
        if conflicts:
            return CheckResult(
                name="Runtime storage separation",
                status=CheckStatus.WARN,
                message=(
                    f"per-user storage active; {len(conflicts)} legacy "
                    "conflict(s) preserved"
                ),
                fix_hint=(
                    "The per-user destination won. Review legacy files before "
                    "deleting them; DupeZ does not delete migration sources."
                ),
            )
        return CheckResult(
            name="Runtime storage separation",
            status=CheckStatus.PASS,
            message="mutable data and config use per-user storage",
        )
    except Exception as exc:
        return CheckResult(
            name="Runtime storage separation",
            status=CheckStatus.FAIL,
            message=f"storage-path check failed: {exc}",
            fix_hint="Preserve existing data and inspect per-user storage permissions.",
        )


# ── Registry + public API ────────────────────────────────────────────

def _check_wifi_adapter() -> CheckResult:
    """Passive WiFi-route detection for user troubleshooting."""
    try:
        from app.network.wifi_probe import get_wifi_route_info
        route = get_wifi_route_info()
        adapter = route.adapter_name or "unknown adapter"
        masked_ip = route.masked_local_ip or "unknown local IP"
        if route.is_wifi:
            return CheckResult(
                name="WiFi adapter path",
                status=CheckStatus.PASS,
                message=(
                    f"default route uses WiFi adapter '{adapter}' "
                    f"({masked_ip})"
                ),
            )
        return CheckResult(
            name="WiFi adapter path",
            status=CheckStatus.WARN,
            message=(
                f"default route is not detected as WiFi via '{adapter}' "
                f"({masked_ip}): {route.reason or 'unknown reason'}"
            ),
            fix_hint=(
                "If you expected WiFi, confirm Windows is routing traffic "
                "through the wireless adapter. Adapter names containing "
                "Wi-Fi, Wireless, WLAN, or 802.11 are recognized. This is "
                "a passive diagnostic and does not change network state."
            ),
        )
    except Exception as exc:
        return CheckResult(
            name="WiFi adapter path",
            status=CheckStatus.WARN,
            message=f"check failed: {exc}",
        )


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
        name="wifi_adapter",
        description="Passively report whether the default route appears to be WiFi",
        runner=_check_wifi_adapter,
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
        name="secret_store",
        description="Verify the OS-backed secret store is writable",
        runner=_check_secret_store,
    ),
    DiagnosticCheck(
        name="persistence_key",
        description="Verify persistence integrity uses durable keying",
        runner=_check_persistence_key,
    ),
    DiagnosticCheck(
        name="audit_chain",
        description="Verify audit log integrity and degraded state",
        runner=_check_audit_chain,
    ),
    DiagnosticCheck(
        name="operation_journal",
        description="Check for network state left pending after a crash",
        runner=_check_operation_journal,
    ),
    DiagnosticCheck(
        name="runtime_storage",
        description="Verify mutable state is separated from installed binaries",
        runner=_check_runtime_storage,
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
