#!/usr/bin/env python3
"""Tests for v5: DayZ Patch Monitor & Auto-Config Updater."""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
from dataclasses import asdict

from app.core.patch_monitor import (
    PatchInfo,
    PatchImpact,
    PatchMonitor,
    MonitorState,
    _IMPACT_RULES,
)


# ── Fake Steam API response ─────────────────────────────────────────

def _fake_steam_response(patches=None):
    """Build a fake Steam News API JSON response."""
    if patches is None:
        patches = [_make_fake_patch()]
    items = []
    for p in patches:
        items.append({
            "gid": p.gid,
            "title": p.title,
            "url": p.url,
            "contents": p.contents,
            "date": p.date_unix,
            "feedlabel": "Community Announcements",
        })
    return json.dumps({
        "appnews": {"newsitems": items}
    }).encode("utf-8")


def _make_fake_patch(
    gid="111111",
    title="DayZ Update 1.29 - Stable",
    contents="Fixed networking desync issues. Updated tick rate.",
    date_unix=None,
):
    return PatchInfo(
        gid=gid,
        title=title,
        contents=contents,
        date_unix=date_unix or int(time.time()),
        date_str="2026-04-09 00:00 UTC",
        url="https://store.steampowered.com/news/app/221100",
        version_tag="1.29",
        is_stable=True,
        is_experimental=False,
    )


class _TempProfileDir:
    """Context manager that sets up a temp game profile for testing."""

    def __init__(self):
        self._tmpdir = None
        self._patches = []

    def __enter__(self):
        self._tmpdir = tempfile.mkdtemp()
        profile_dir = os.path.join(self._tmpdir, "config", "game_profiles")
        os.makedirs(profile_dir, exist_ok=True)
        state_dir = os.path.join(self._tmpdir, "config")
        # Write a minimal dayz.json
        profile = {
            "game": "dayz",
            "version_notes": "initial",
            "tick_model": {
                "expected_range_hz": [20, 120],
                "notes": "default"
            },
            "anti_cheat": {
                "detection_vectors": ["BattlEye kernel driver"]
            },
            "packet_classification": {
                "auto_calibrate": False
            },
            "game_state_detection": {},
            "nat_keepalive": {},
        }
        profile_path = os.path.join(profile_dir, "dayz.json")
        with open(profile_path, "w") as f:
            json.dump(profile, f, indent=2)
        return self._tmpdir, profile_path, state_dir

    def __exit__(self, *args):
        import shutil
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestPatchInfo(unittest.TestCase):
    def test_defaults(self):
        p = PatchInfo()
        self.assertEqual(p.title, "")
        self.assertEqual(p.gid, "")
        self.assertFalse(p.is_stable)

    def test_fields(self):
        p = _make_fake_patch()
        self.assertEqual(p.gid, "111111")
        self.assertTrue(p.is_stable)
        self.assertEqual(p.version_tag, "1.29")


class TestPatchImpact(unittest.TestCase):
    def test_defaults(self):
        impact = PatchImpact()
        self.assertEqual(impact.severity, "low")
        self.assertFalse(impact.needs_recalibration)
        self.assertEqual(impact.affected_sections, [])

    def test_fields(self):
        impact = PatchImpact(
            severity="critical",
            needs_recalibration=True,
            affected_sections=["network"],
        )
        self.assertEqual(impact.severity, "critical")
        self.assertTrue(impact.needs_recalibration)


class TestMonitorState(unittest.TestCase):
    def test_defaults(self):
        state = MonitorState()
        self.assertEqual(state.last_seen_gid, "")
        self.assertEqual(state.check_count, 0)

    def test_roundtrip(self):
        state = MonitorState(
            last_check_unix=1000.0,
            last_seen_gid="abc",
            check_count=5,
        )
        d = asdict(state)
        restored = MonitorState(**d)
        self.assertEqual(restored.last_seen_gid, "abc")
        self.assertEqual(restored.check_count, 5)


class TestImpactRules(unittest.TestCase):
    """Verify impact rules match expected keywords."""

    def test_network_rule_matches(self):
        text = "Fixed UDP packet replication issues"
        matched = False
        for pattern, sections, severity in _IMPACT_RULES:
            import re
            if re.findall(pattern, text):
                if "network" in sections:
                    matched = True
                    break
        self.assertTrue(matched)

    def test_anticheat_rule_matches(self):
        text = "BattlEye anti-cheat driver scan improvements"
        matched_sections = set()
        for pattern, sections, severity in _IMPACT_RULES:
            import re
            if re.findall(pattern, text):
                matched_sections.update(sections)
        self.assertIn("anti_cheat", matched_sections)

    def test_tick_rate_rule(self):
        text = "Improved server FPS and tick rate stability"
        matched_sections = set()
        for pattern, sections, severity in _IMPACT_RULES:
            import re
            if re.findall(pattern, text):
                matched_sections.update(sections)
        self.assertIn("tick_model", matched_sections)

    def test_platform_rule(self):
        text = "Xbox Series X native performance patch"
        matched_sections = set()
        for pattern, sections, severity in _IMPACT_RULES:
            import re
            if re.findall(pattern, text):
                matched_sections.update(sections)
        self.assertIn("platform_support", matched_sections)

    def test_no_match_on_unrelated(self):
        text = "Happy holidays from the Bohemia team"
        matched = False
        for pattern, sections, severity in _IMPACT_RULES:
            import re
            if re.findall(pattern, text):
                matched = True
                break
        self.assertFalse(matched)


class TestPatchMonitorAnalysis(unittest.TestCase):
    """Test the analysis pipeline without network calls."""

    def setUp(self):
        self.monitor = PatchMonitor.__new__(PatchMonitor)
        self.monitor._state = MonitorState()
        self.monitor._lock = __import__("threading").Lock()
        self.monitor._running = False
        self.monitor._thread = None
        self.monitor._callbacks = []
        self.monitor._check_interval = 1800

    def test_analyze_network_patch(self):
        patch = _make_fake_patch(
            contents="Fixed networking desync in UDP replication layer"
        )
        impact = self.monitor._analyze_impact(patch)
        self.assertIn("network", impact.affected_sections)
        self.assertIn("reliable_udp", impact.affected_sections)
        self.assertTrue(impact.needs_recalibration)
        self.assertIn("high", [impact.severity])

    def test_analyze_anticheat_patch(self):
        patch = _make_fake_patch(
            title="DayZ 1.30 Hotfix",
            contents="Updated BattlEye anti-cheat with new WinDivert detection"
        )
        impact = self.monitor._analyze_impact(patch)
        self.assertIn("anti_cheat", impact.affected_sections)
        self.assertEqual(impact.severity, "critical")
        self.assertTrue(impact.needs_recalibration)

    def test_analyze_minor_patch(self):
        patch = _make_fake_patch(
            contents="Fixed loot spawn rates for coastal towns"
        )
        impact = self.monitor._analyze_impact(patch)
        self.assertEqual(impact.severity, "low")

    def test_analyze_empty_patch(self):
        patch = _make_fake_patch(
            title="Community Event",
            contents="Join us for the winter event!"
        )
        impact = self.monitor._analyze_impact(patch)
        self.assertEqual(len(impact.affected_sections), 0)
        self.assertFalse(impact.needs_recalibration)

    def test_recommendations_generated(self):
        patch = _make_fake_patch(
            contents="Major tick rate changes and anti-cheat update with BattlEye"
        )
        impact = self.monitor._analyze_impact(patch)
        self.assertTrue(len(impact.recommendations) > 0)


class TestPatchMonitorAutoActions(unittest.TestCase):
    """Test auto-action profile modifications."""

    def setUp(self):
        self.monitor = PatchMonitor.__new__(PatchMonitor)
        self.monitor._state = MonitorState()
        self.monitor._lock = __import__("threading").Lock()
        self.monitor._running = False
        self.monitor._thread = None
        self.monitor._callbacks = []
        self.monitor._check_interval = 1800

    def test_auto_update_version_notes(self):
        with _TempProfileDir() as (tmpdir, profile_path, state_dir):
            with patch("app.core.patch_monitor._PROFILE_PATH", profile_path):
                impact = PatchImpact(
                    patch=_make_fake_patch(),
                    affected_sections=["network"],
                    severity="high",
                    needs_recalibration=True,
                )
                self.monitor._apply_auto_actions(impact)

                with open(profile_path) as f:
                    profile = json.load(f)
                self.assertIn("1.29", profile["version_notes"])
                self.assertTrue(len(impact.auto_actions_taken) > 0)

    def test_auto_widen_tick_bounds(self):
        with _TempProfileDir() as (tmpdir, profile_path, state_dir):
            with patch("app.core.patch_monitor._PROFILE_PATH", profile_path):
                impact = PatchImpact(
                    patch=_make_fake_patch(),
                    affected_sections=["tick_model"],
                    severity="high",
                    needs_recalibration=True,
                )
                self.monitor._apply_auto_actions(impact)

                with open(profile_path) as f:
                    profile = json.load(f)
                self.assertEqual(
                    profile["tick_model"]["expected_range_hz"][1], 200)

    def test_auto_enable_recalibration(self):
        with _TempProfileDir() as (tmpdir, profile_path, state_dir):
            with patch("app.core.patch_monitor._PROFILE_PATH", profile_path):
                impact = PatchImpact(
                    patch=_make_fake_patch(),
                    affected_sections=["network", "packet_classification"],
                    severity="high",
                    needs_recalibration=True,
                )
                self.monitor._apply_auto_actions(impact)

                with open(profile_path) as f:
                    profile = json.load(f)
                self.assertTrue(
                    profile["packet_classification"]["auto_calibrate"])

    def test_auto_add_anticheat_note(self):
        with _TempProfileDir() as (tmpdir, profile_path, state_dir):
            with patch("app.core.patch_monitor._PROFILE_PATH", profile_path):
                impact = PatchImpact(
                    patch=_make_fake_patch(),
                    affected_sections=["anti_cheat"],
                    severity="critical",
                    needs_recalibration=False,
                )
                self.monitor._apply_auto_actions(impact)

                with open(profile_path) as f:
                    profile = json.load(f)
                vectors = profile["anti_cheat"]["detection_vectors"]
                self.assertTrue(
                    any("1.29" in v for v in vectors))


class TestPatchMonitorStatePersistence(unittest.TestCase):
    """Test state save/load cycle."""

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")
            with patch("app.core.patch_monitor._STATE_FILE", state_file):
                monitor = PatchMonitor.__new__(PatchMonitor)
                monitor._state = MonitorState(
                    last_check_unix=12345.0,
                    last_seen_gid="test_gid",
                    check_count=3,
                    patches_detected=1,
                )
                monitor._save_state()

                self.assertTrue(os.path.isfile(state_file))

                loaded = monitor._load_state()
                self.assertEqual(loaded.last_seen_gid, "test_gid")
                self.assertEqual(loaded.check_count, 3)

    def test_load_missing_file(self):
        with patch("app.core.patch_monitor._STATE_FILE", "/nonexistent/path.json"):
            monitor = PatchMonitor.__new__(PatchMonitor)
            state = monitor._load_state()
            self.assertEqual(state.last_seen_gid, "")
            self.assertEqual(state.check_count, 0)


class TestPatchMonitorFilterNew(unittest.TestCase):
    """Test filtering logic for new patches."""

    def setUp(self):
        self.monitor = PatchMonitor.__new__(PatchMonitor)
        self.monitor._state = MonitorState()
        self.monitor._lock = __import__("threading").Lock()
        self.monitor._running = False
        self.monitor._thread = None
        self.monitor._callbacks = []

    def test_first_run_returns_empty(self):
        """First run (no last_seen_gid) should return empty to avoid flood."""
        patches = [_make_fake_patch(gid="aaa"), _make_fake_patch(gid="bbb")]
        result = self.monitor._filter_new(patches)
        self.assertEqual(result, [])

    def test_returns_new_patches_only(self):
        self.monitor._state.last_seen_gid = "bbb"
        patches = [
            _make_fake_patch(gid="ddd"),
            _make_fake_patch(gid="ccc"),
            _make_fake_patch(gid="bbb"),  # seen this one
            _make_fake_patch(gid="aaa"),  # older
        ]
        result = self.monitor._filter_new(patches)
        gids = [p.gid for p in result]
        self.assertEqual(gids, ["ddd", "ccc"])

    def test_no_new_patches(self):
        self.monitor._state.last_seen_gid = "aaa"
        patches = [_make_fake_patch(gid="aaa")]
        result = self.monitor._filter_new(patches)
        self.assertEqual(result, [])


class TestPatchMonitorCallbacks(unittest.TestCase):
    """Test callback registration and invocation."""

    def test_callback_registered(self):
        monitor = PatchMonitor.__new__(PatchMonitor)
        monitor._callbacks = []
        cb = MagicMock()
        monitor.on_patch_detected(cb)
        self.assertEqual(len(monitor._callbacks), 1)


class TestPatchMonitorBackgroundLifecycle(unittest.TestCase):
    """Test start/stop lifecycle (without actual network calls)."""

    @patch("app.core.patch_monitor.PatchMonitor._fetch_news", return_value=[])
    @patch("app.core.patch_monitor._STATE_FILE", "/tmp/test_pm_state.json")
    def test_start_and_stop(self, mock_fetch):
        monitor = PatchMonitor(check_interval_sec=1)
        monitor.start_background()
        self.assertTrue(monitor._running)
        time.sleep(0.2)
        monitor.stop_background()
        self.assertFalse(monitor._running)

    def test_double_start_idempotent(self):
        monitor = PatchMonitor.__new__(PatchMonitor)
        monitor._state = MonitorState()
        monitor._lock = __import__("threading").Lock()
        monitor._running = True
        monitor._thread = None
        monitor._callbacks = []
        monitor._check_interval = 999
        # Calling start when already running should be no-op
        monitor.start_background()
        # Should still be running, no crash
        self.assertTrue(monitor._running)


class TestPatchMonitorGetState(unittest.TestCase):
    def test_get_state_returns_dict(self):
        monitor = PatchMonitor.__new__(PatchMonitor)
        monitor._state = MonitorState(
            last_seen_gid="xyz", check_count=7)
        state = monitor.get_state()
        self.assertIsInstance(state, dict)
        self.assertEqual(state["last_seen_gid"], "xyz")
        self.assertEqual(state["check_count"], 7)


if __name__ == "__main__":
    unittest.main()
