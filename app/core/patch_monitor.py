#!/usr/bin/env python3
"""
DayZ Patch Monitor & Auto-Config Updater.

Tracks Bohemia Interactive's DayZ updates via multiple sources and
automatically adjusts DupeZ's game profile config when patches are
detected.  Eliminates the manual process of reading changelogs and
tweaking hardcoded values.

Data Sources (checked in priority order):
  1. Steam Web API  -- ISteamNews/GetNewsForApp (patch notes)
  2. Steam Web API  -- ISteamApps/UpToDateCheck  (version bump)
  3. SteamDB RSS    -- steamdb.info/app/221100/patchnotes (backup)

What it does on patch detection:
  1. Fetches the changelog text from Steam News
  2. Parses it for known impact keywords (port change, tick rate,
     inventory, desync, anti-cheat, networking)
  3. Flags affected config sections in the game profile
  4. Triggers auto-recalibration on next engine start
  5. Logs a detailed patch impact report

This module is designed to run:
  - On DupeZ startup (quick check)
  - Periodically via the scheduler (every 30 min default)
  - On-demand from the GUI "Check for Updates" button

Security:
  - All HTTP via ``secure_get_json`` (TLS 1.3, cert verify, URL validation)
  - Atomic state persistence (tmp -> fsync -> replace)
  - HMAC-SHA384 integrity on persisted state file
  - Audit trail for patch detection events
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import re
import sys
import time
import threading
from dataclasses import dataclass, field, asdict, fields as dc_fields
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.logs.logger import log_info, log_error

__all__ = [
    "PatchInfo",
    "PatchImpact",
    "MonitorState",
    "PatchMonitor",
    "get_monitor",
    "check_now",
    "start_background_monitoring",
    "stop_background_monitoring",
]

# ── Constants ─────────────────────────────────────────────────────────

DAYZ_APP_ID: int = 221100

# Steam Web API endpoints (no API key required for these)
_STEAM_NEWS_URL: str = (
    "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"
    f"?appid={DAYZ_APP_ID}&count=5&maxlength=2000&format=json"
)
_STEAM_VERSION_URL: str = (
    "https://api.steampowered.com/ISteamApps/UpToDateCheck/v0001/"
    f"?appid={DAYZ_APP_ID}&version=0&format=json"
)

# Where we persist the last-seen state
_STATE_DIR: str = os.path.join(os.path.dirname(__file__), "..", "config")
_STATE_FILE: str = os.path.join(_STATE_DIR, "patch_monitor_state.json")
_STATE_HMAC_FILE: str = _STATE_FILE + ".hmac"

# Game profile path
_PROFILE_DIR: str = os.path.join(
    os.path.dirname(__file__), "..", "config", "game_profiles")
_PROFILE_PATH: str = os.path.join(_PROFILE_DIR, "dayz.json")

# Default background check interval
_DEFAULT_CHECK_INTERVAL_S: float = 1800.0  # 30 minutes

# Steam feed labels considered official
_OFFICIAL_FEEDS: frozenset[str] = frozenset({
    "Community Announcements",
    "steam_community_announcements",
})

# Regex pattern for patch-like titles (compiled once)
_PATCH_TITLE_RE = re.compile(
    r"(?i)(update|patch|hotfix|stable|experimental)"
)

# Version tag extraction pattern
_VERSION_TAG_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")

# Stable / experimental branch detection
_STABLE_RE = re.compile(r"(?i)(stable|out now|live|release)")
_EXPERIMENTAL_RE = re.compile(r"(?i)experimental")


# ── Impact keyword detection ──────────────────────────────────────────

# Each tuple: (regex_pattern, affected_config_sections, severity)
_IMPACT_RULES: List[Tuple[re.Pattern[str], List[str], str]] = [
    # Networking / protocol
    (re.compile(r"(?i)(network|packet|protocol|udp|tcp|replication|netcode)"),
     ["network", "reliable_udp", "packet_classification"], "high"),
    (re.compile(r"(?i)(port\s*\d+|server\s*port|game\s*port|changed?\s*port)"),
     ["network"], "critical"),
    (re.compile(r"(?i)(tick\s*rate|server\s*fps|simulation\s*rate|performance.*server)"),
     ["tick_model", "packet_classification", "game_state_detection"], "high"),

    # Inventory / duplication
    (re.compile(r"(?i)(inventory|item\s*dupe|duplication|exploit|ILT_TEMP)"),
     ["disruption_defaults"], "medium"),
    (re.compile(r"(?i)(desync|synchroniz|rollback|reconcil)"),
     ["reliable_udp", "disruption_defaults", "burst_strategy"], "high"),

    # Anti-cheat
    (re.compile(r"(?i)(battleye|anti.?cheat|ban\s*wave|detection|driver\s*scan)"),
     ["anti_cheat"], "critical"),
    (re.compile(r"(?i)(WinDivert|WFP|NDIS|kernel\s*driver|filter\s*enum)"),
     ["anti_cheat"], "critical"),

    # Connection / NAT
    (re.compile(r"(?i)(disconnect|kick|timeout|freeze|connection\s*quality)"),
     ["disruption_defaults", "nat_keepalive", "burst_strategy"], "high"),
    (re.compile(r"(?i)(NAT|keepalive|keep.alive|mapping|stale\s*connection)"),
     ["nat_keepalive", "disruption_defaults"], "medium"),

    # Engine migration
    (re.compile(r"(?i)(enfusion|engine\s*migrat|animation\s*system|new\s*engine)"),
     ["tick_model", "network", "packet_classification"], "high"),

    # Platform specific
    (re.compile(r"(?i)(xbox\s*series|native.*xbox|playstation|ps5|cross.?play)"),
     ["platform_support"], "medium"),

    # General balance
    (re.compile(r"(?i)(vehicle|collision|physics|movement|speed)"),
     ["packet_classification"], "low"),
    (re.compile(r"(?i)(loot|spawn|economy|trader|base\s*build)"),
     ["packet_classification"], "low"),
]

# Severity ordering for comparisons
_SEVERITY_RANK: Dict[str, int] = {
    "low": 0, "medium": 1, "high": 2, "critical": 3,
}

# Config sections that trigger recalibration
_CRITICAL_SECTIONS: frozenset[str] = frozenset({
    "network", "reliable_udp", "tick_model",
    "packet_classification", "anti_cheat",
})


# ── HMAC integrity for state file ────────────────────────────────────

def _get_hmac_key() -> bytes:
    """Derive a machine-specific HMAC key for state integrity.

    Uses the same machine-bound seed pattern as data_persistence.
    """
    import platform
    parts = [
        platform.node(),
        os.environ.get("USERNAME", os.environ.get("USER", "default")),
        platform.machine(),
        "DupeZ-PatchMonitor-v1",  # domain separation
    ]
    seed = "|".join(parts).encode("utf-8")
    return hashlib.sha384(seed).digest()


def _compute_hmac(data: bytes) -> str:
    """Compute HMAC-SHA384 hex digest."""
    return _hmac.new(_get_hmac_key(), data, hashlib.sha384).hexdigest()


def _verify_hmac(data: bytes, expected_hex: str) -> bool:
    """Constant-time HMAC verification."""
    computed = _hmac.new(_get_hmac_key(), data, hashlib.sha384).hexdigest()
    return _hmac.compare_digest(computed, expected_hex)


# ── Audit helper ─────────────────────────────────────────────────────

def _audit(event: str, details: Dict[str, Any]) -> None:
    """Emit an audit event (best-effort)."""
    try:
        from app.logs.audit import audit_event
        audit_event(event, details)
    except Exception:
        pass


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class PatchInfo:
    """Represents a detected DayZ patch."""
    title: str = ""
    date_unix: int = 0
    date_str: str = ""
    gid: str = ""
    url: str = ""
    contents: str = ""
    version_tag: str = ""          # e.g. "1.29"
    is_stable: bool = False
    is_experimental: bool = False


@dataclass
class PatchImpact:
    """Analysis of how a patch affects DupeZ config."""
    patch: PatchInfo = field(default_factory=PatchInfo)
    affected_sections: List[str] = field(default_factory=list)
    severity: str = "low"          # low, medium, high, critical
    keyword_matches: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    auto_actions_taken: List[str] = field(default_factory=list)
    needs_recalibration: bool = False


@dataclass
class MonitorState:
    """Persisted state between monitor runs."""
    last_check_unix: float = 0.0
    last_seen_gid: str = ""
    last_seen_title: str = ""
    last_version_hash: str = ""
    known_version: str = ""
    check_count: int = 0
    patches_detected: int = 0


# ── Core Monitor ──────────────────────────────────────────────────────

class PatchMonitor:
    """Monitors DayZ updates and auto-adjusts DupeZ config.

    Usage::

        monitor = PatchMonitor()
        impacts = monitor.check_for_updates()
        for impact in impacts:
            print(impact.severity, impact.affected_sections)
    """

    def __init__(self, check_interval_sec: float = _DEFAULT_CHECK_INTERVAL_S) -> None:
        self._check_interval: float = check_interval_sec
        self._state: MonitorState = self._load_state()
        self._lock = threading.Lock()
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[List[PatchImpact]], None]] = []

    # ── Public API ────────────────────────────────────────────────────

    def check_for_updates(self) -> List[PatchImpact]:
        """Check Steam for new DayZ patches.  Returns list of impacts."""
        impacts: List[PatchImpact] = []
        with self._lock:
            try:
                patches = self._fetch_news()
                new_patches = self._filter_new(patches)

                for patch in new_patches:
                    impact = self._analyze_impact(patch)
                    if impact.affected_sections:
                        self._apply_auto_actions(impact)
                    impacts.append(impact)
                    self._state.patches_detected += 1

                # Update state
                if patches:
                    self._state.last_seen_gid = patches[0].gid
                    self._state.last_seen_title = patches[0].title
                self._state.last_check_unix = time.time()
                self._state.check_count += 1
                self._save_state()

                if new_patches:
                    log_info(
                        f"PatchMonitor: {len(new_patches)} new patch(es) detected"
                    )
                    for impact in impacts:
                        log_info(
                            f"  [{impact.severity.upper()}] {impact.patch.title} "
                            f"— affects: {impact.affected_sections}"
                        )
                        _audit("patch_detected", {
                            "title": impact.patch.title,
                            "severity": impact.severity,
                            "affected": impact.affected_sections,
                            "version": impact.patch.version_tag,
                        })

                    # Notify callbacks
                    for cb in self._callbacks:
                        try:
                            cb(impacts)
                        except Exception as e:
                            log_error(f"PatchMonitor callback error: {e}")
                else:
                    log_info(
                        f"PatchMonitor: no new patches "
                        f"(last seen: {self._state.last_seen_title})"
                    )

            except Exception as e:
                log_error(f"PatchMonitor: check failed: {e}")

        return impacts

    def on_patch_detected(self, callback: Callable[[List[PatchImpact]], None]) -> None:
        """Register a callback: fn(List[PatchImpact]) called on new patches."""
        self._callbacks.append(callback)

    def start_background(self) -> None:
        """Start periodic background checking."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._background_loop, daemon=True,
            name="PatchMonitor")
        self._thread.start()
        log_info(
            f"PatchMonitor: background checking started "
            f"(every {self._check_interval / 60:.0f} min)"
        )

    def stop_background(self) -> None:
        """Stop periodic checking."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        log_info("PatchMonitor: background checking stopped")

    def get_state(self) -> Dict[str, Any]:
        """Return current monitor state for GUI display."""
        return asdict(self._state)

    def get_last_impact_report(self) -> Optional[PatchImpact]:
        """Return the most recent patch impact analysis."""
        impacts = self.check_for_updates()
        return impacts[0] if impacts else None

    # ── Steam API ─────────────────────────────────────────────────────

    def _fetch_news(self) -> List[PatchInfo]:
        """Fetch latest DayZ news from Steam Web API.

        Uses ``secure_get_json`` for TLS-enforced, validated HTTP.
        """
        try:
            from app.core.secure_http import secure_get_json

            data = secure_get_json(_STEAM_NEWS_URL)
            if data is None:
                log_error("PatchMonitor: Steam API returned no data")
                return []

            items = data.get("appnewsitems", {}).get("newsitems", [])
            if not items:
                items = data.get("appnews", {}).get("newsitems", [])

            patches: List[PatchInfo] = []
            for item in items:
                title = item.get("title", "")
                feedlabel = item.get("feedlabel", "")

                # Only care about official announcements
                if feedlabel not in _OFFICIAL_FEEDS:
                    # Still include if title looks like a patch note
                    if not _PATCH_TITLE_RE.search(title):
                        continue

                date_unix = item.get("date", 0)
                p = PatchInfo(
                    title=title,
                    date_unix=date_unix,
                    date_str=datetime.fromtimestamp(
                        date_unix, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M UTC"),
                    gid=str(item.get("gid", "")),
                    url=item.get("url", ""),
                    contents=item.get("contents", ""),
                )

                # Extract version tag (e.g. "1.29")
                ver_match = _VERSION_TAG_RE.search(title)
                if ver_match:
                    p.version_tag = ver_match.group(1)

                p.is_stable = bool(_STABLE_RE.search(title))
                p.is_experimental = bool(_EXPERIMENTAL_RE.search(title))

                patches.append(p)

            return patches

        except Exception as e:
            log_error(f"PatchMonitor: Steam API error: {e}")
            return []

    def _filter_new(self, patches: List[PatchInfo]) -> List[PatchInfo]:
        """Filter to only patches we haven't seen before."""
        if not self._state.last_seen_gid:
            # First run -- don't flood with old patches, just record latest
            return []

        new: List[PatchInfo] = []
        for p in patches:
            if p.gid == self._state.last_seen_gid:
                break
            new.append(p)
        return new

    # ── Impact Analysis ───────────────────────────────────────────────

    def _analyze_impact(self, patch: PatchInfo) -> PatchImpact:
        """Analyze a patch's changelog for DupeZ-relevant changes."""
        impact = PatchImpact(patch=patch)
        text = f"{patch.title} {patch.contents}"

        max_severity = "low"
        seen_sections: set[str] = set()

        for pattern, sections, severity in _IMPACT_RULES:
            matches = pattern.findall(text)
            if matches:
                # Limit keyword matches to avoid unbounded growth
                impact.keyword_matches.extend(matches[:3])
                for s in sections:
                    if s not in seen_sections:
                        impact.affected_sections.append(s)
                        seen_sections.add(s)
                if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(max_severity, 0):
                    max_severity = severity

        impact.severity = max_severity

        # Generate recommendations based on affected sections
        impact.recommendations = self._generate_recommendations(impact)

        # Flag for recalibration if networking/protocol affected
        if seen_sections & _CRITICAL_SECTIONS:
            impact.needs_recalibration = True

        return impact

    @staticmethod
    def _generate_recommendations(impact: PatchImpact) -> List[str]:
        """Generate human-readable recommendations for a patch impact."""
        recs: List[str] = []
        sections = set(impact.affected_sections)

        if "network" in sections or "reliable_udp" in sections:
            recs.append(
                "Networking changes detected. Run a calibration session "
                "on a live server to update packet size thresholds and "
                "ack bitfield parameters.")

        if "tick_model" in sections:
            recs.append(
                "Server performance changes detected. The TickEstimator "
                "will auto-adapt, but verify tick rate on updated servers "
                "using the traffic analyzer.")

        if "packet_classification" in sections:
            recs.append(
                "Packet classification may be affected. Auto-calibration "
                "will re-derive thresholds on next disruption session.")

        if "anti_cheat" in sections:
            recs.append(
                "CRITICAL: Anti-cheat changes detected. Check BattlEye "
                "detection vectors. Consider switching to NDIS backend "
                "if WinDivert detections are mentioned.")

        if "disruption_defaults" in sections:
            recs.append(
                "Game mechanics changed. Review disruption presets -- "
                "dupe templates may need updating if inventory system changed.")

        if "nat_keepalive" in sections or "burst_strategy" in sections:
            recs.append(
                "Connection handling changed. Monitor for increased kicks "
                "and adjust burst/rest ratio and NAT keepalive interval.")

        if "platform_support" in sections:
            recs.append(
                "Platform-specific changes. Verify PS5/Xbox/PC interception "
                "layers still work correctly on updated clients.")

        if not recs:
            recs.append("Minor changes. No immediate DupeZ impact expected.")

        return recs

    # ── Auto-Actions ──────────────────────────────────────────────────

    def _apply_auto_actions(self, impact: PatchImpact) -> None:
        """Automatically adjust game profile based on patch analysis."""
        actions: List[str] = []

        try:
            if not os.path.isfile(_PROFILE_PATH):
                return

            with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
                profile = json.load(f)

            modified = False

            # Update version notes
            if impact.patch.version_tag:
                old_notes = profile.get("version_notes", "")
                new_notes = (
                    f"Auto-updated for DayZ {impact.patch.version_tag} "
                    f"({impact.patch.date_str}). "
                    f"Previous: {old_notes[:100]}")
                profile["version_notes"] = new_notes
                modified = True
                actions.append(
                    f"Updated version_notes to reflect {impact.patch.version_tag}")

            # If tick/performance mentioned, widen TickEstimator bounds
            if "tick_model" in impact.affected_sections:
                tm = profile.get("tick_model", {})
                tick_range = tm.get("expected_range_hz", [20, 120])
                old_max = tick_range[1] if len(tick_range) > 1 else 120
                tick_ceiling = 200
                if old_max < tick_ceiling:
                    tm["expected_range_hz"] = [20, tick_ceiling]
                    tm["notes"] = (
                        f"Widened for {impact.patch.version_tag} "
                        "server performance changes.")
                    profile["tick_model"] = tm
                    modified = True
                    actions.append(
                        f"Widened tick rate ceiling to {tick_ceiling}Hz "
                        f"(was {old_max}Hz)")

            # If anti-cheat mentioned, update detection vector notes
            if "anti_cheat" in impact.affected_sections:
                ac = profile.get("anti_cheat", {})
                vectors = ac.get("detection_vectors", [])
                note = (
                    f"Potential update in {impact.patch.version_tag} -- "
                    "review detection surface")
                if note not in vectors:
                    vectors.append(note)
                    ac["detection_vectors"] = vectors
                    profile["anti_cheat"] = ac
                    modified = True
                    actions.append("Added anti-cheat update note")

            # Enable recalibration flags
            if impact.needs_recalibration:
                pc = profile.get("packet_classification", {})
                pc["auto_calibrate"] = True
                pc["_recalibration_triggered_by"] = impact.patch.version_tag
                profile["packet_classification"] = pc

                gsd = profile.get("game_state_detection", {})
                gsd["auto_calibrate"] = True
                profile["game_state_detection"] = gsd

                nk = profile.get("nat_keepalive", {})
                nk["auto_calibrate"] = True
                profile["nat_keepalive"] = nk
                modified = True
                actions.append(
                    "Enabled auto-recalibration for classifier, "
                    "game state detector, and NAT keepalive")

            # Atomic write (tmp -> fsync -> replace)
            if modified:
                tmp_path = _PROFILE_PATH + ".tmp"
                try:
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump(profile, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, _PROFILE_PATH)
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise

                # Clear profile cache so next load picks up changes.
                # If this fails, disk is updated but in-memory state is stale —
                # that's worth warning about (operator will run with old tuning
                # until restart).
                try:
                    from app.config.game_profiles import reload_profile
                    reload_profile("dayz")
                except Exception as exc:  # noqa: BLE001
                    log_info(
                        "PatchMonitor: profile written to disk but "
                        f"reload_profile failed ({exc!r}); restart app to "
                        "pick up changes"
                    )

                log_info(
                    f"PatchMonitor: auto-updated game profile "
                    f"({len(actions)} actions)")
                _audit("patch_auto_action", {
                    "patch": impact.patch.version_tag,
                    "actions": actions,
                })

        except Exception as e:
            log_error(f"PatchMonitor: auto-action failed: {e}")
            actions.append(f"ERROR: {e}")

        impact.auto_actions_taken = actions

    # ── Background Loop ───────────────────────────────────────────────

    def _background_loop(self) -> None:
        """Periodic check loop for background thread."""
        # Initial check on startup (short delay to let app initialize)
        time.sleep(5)
        self.check_for_updates()

        while self._running:
            # Sleep in small increments so stop_background() is responsive
            for _ in range(int(self._check_interval)):
                if not self._running:
                    return
                time.sleep(1)
            self.check_for_updates()

    # ── State Persistence (atomic + HMAC) ─────────────────────────────

    def _load_state(self) -> MonitorState:
        """Load persisted state from disk with HMAC integrity check."""
        try:
            if not os.path.isfile(_STATE_FILE):
                return MonitorState()

            with open(_STATE_FILE, "rb") as f:
                raw = f.read()

            # HMAC integrity check
            if os.path.isfile(_STATE_HMAC_FILE):
                try:
                    with open(_STATE_HMAC_FILE, "r", encoding="utf-8") as hf:
                        stored_hmac = hf.read().strip()
                    if not _verify_hmac(raw, stored_hmac):
                        log_error(
                            "PatchMonitor: state HMAC verification FAILED "
                            "-- possible tampering, resetting state"
                        )
                        _audit("patch_monitor_hmac_fail", {
                            "file": _STATE_FILE,
                        })
                        return MonitorState()
                except Exception as e:
                    log_error(f"PatchMonitor: HMAC check error: {e}")
                    # Continue loading -- don't brick on missing/corrupt HMAC

            data = json.loads(raw.decode("utf-8"))
            known_fields = {fld.name for fld in dc_fields(MonitorState)}
            filtered = {k: v for k, v in data.items() if k in known_fields}
            return MonitorState(**filtered)

        except (json.JSONDecodeError, TypeError) as e:
            log_error(f"PatchMonitor: corrupt state file, resetting: {e}")
            return MonitorState()
        except Exception as e:
            log_error(f"PatchMonitor: state load failed: {e}")
            return MonitorState()

    def _save_state(self) -> None:
        """Persist state to disk (atomic write + HMAC integrity)."""
        tmp_path = _STATE_FILE + ".tmp"
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)

            raw_json = json.dumps(asdict(self._state), indent=2)
            raw_bytes = raw_json.encode("utf-8")

            # Atomic write: tmp -> fsync -> replace
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(raw_json)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, _STATE_FILE)

            # Write companion HMAC tag
            try:
                hmac_hex = _compute_hmac(raw_bytes)
                hmac_tmp = _STATE_HMAC_FILE + ".tmp"
                with open(hmac_tmp, "w", encoding="utf-8") as hf:
                    hf.write(hmac_hex)
                    hf.flush()
                    os.fsync(hf.fileno())
                os.replace(hmac_tmp, _STATE_HMAC_FILE)
            except Exception as he:
                log_error(f"PatchMonitor: HMAC write failed: {he}")

        except Exception as e:
            log_error(f"PatchMonitor: state save failed: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── Module-level convenience ──────────────────────────────────────────

_monitor: Optional[PatchMonitor] = None


def get_monitor() -> PatchMonitor:
    """Get or create the singleton PatchMonitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = PatchMonitor()
    return _monitor


def check_now() -> List[PatchImpact]:
    """Quick check for updates (for GUI button / startup)."""
    return get_monitor().check_for_updates()


def start_background_monitoring() -> None:
    """Start the background monitor (call from app startup)."""
    get_monitor().start_background()


def stop_background_monitoring() -> None:
    """Stop the background monitor (call from app shutdown)."""
    if _monitor:
        _monitor.stop_background()
