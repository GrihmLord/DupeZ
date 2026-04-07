#!/usr/bin/env python3
"""
DupeZ v3.5.0 Regression Tests
Tests all new code from this release plus regressions on core modules.
Run: python -m pytest tests/test_regression_v350.py -v
"""

import sys
import os
import json
import time
import tempfile

# Ensure project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest


# ======================================================================
# 1. Profile System
# ======================================================================
class TestProfileManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from app.core.profiles import ProfileManager
        self.pm = ProfileManager(profiles_dir=self.tmpdir)

    def test_save_and_load(self):
        profile = self.pm.save("test1", methods=["lag", "drop"], params={"lag_delay": 1500})
        assert profile.name == "test1"
        loaded = self.pm.load("test1")
        assert loaded is not None
        assert loaded.methods == ["lag", "drop"]
        assert loaded.params["lag_delay"] == 1500
        assert loaded.use_count == 1

    def test_list_profiles(self):
        self.pm.save("a", methods=["lag"], params={})
        self.pm.save("b", methods=["drop"], params={})
        profiles = self.pm.list_profiles()
        names = [p.name for p in profiles]
        assert "a" in names
        assert "b" in names

    def test_delete_profile(self):
        self.pm.save("del_me", methods=[], params={})
        assert self.pm.delete("del_me")
        assert self.pm.load("del_me") is None

    def test_export_import(self):
        self.pm.save("exportable", methods=["godmode"], params={"godmode_lag_ms": 2000})
        export_path = os.path.join(self.tmpdir, "exported.json")
        assert self.pm.export_profile("exportable", export_path)
        assert os.path.exists(export_path)

        # Import into fresh manager
        from app.core.profiles import ProfileManager
        pm2 = ProfileManager(profiles_dir=tempfile.mkdtemp())
        imported = pm2.import_profile(export_path)
        assert imported is not None
        assert imported.name == "exportable"
        assert imported.params["godmode_lag_ms"] == 2000

    def test_profile_dataclass_roundtrip(self):
        from app.core.profiles import DisruptionProfile
        p = DisruptionProfile(name="rt", methods=["lag"], params={"x": 1})
        d = p.to_dict()
        p2 = DisruptionProfile.from_dict(d)
        assert p2.name == "rt"
        assert p2.methods == ["lag"]


# ======================================================================
# 2. GPC Parser
# ======================================================================
class TestGPCParser:
    def test_parse_basic(self):
        from app.gpc.gpc_parser import parse_gpc
        source = """
int my_var = 10;
main {
    set_val(TRACE_1, 100);
    wait(200);
}
combo AutoDupe {
    set_val(TRACE_2, 50);
    wait(100);
}
"""
        script = parse_gpc(source)
        assert script is not None
        assert len(script.variables) >= 1
        assert script.variables[0].name == "my_var"
        assert script.variables[0].initial_value == "10"
        assert script.main_body is not None
        assert len(script.combos) >= 1
        assert script.combos[0].name == "AutoDupe"

    def test_combo_steps(self):
        from app.gpc.gpc_parser import parse_gpc
        source = """
combo TestCombo {
    wait(100);
    wait(200);
    set_val(TRACE_1, 50);
}
"""
        script = parse_gpc(source)
        assert len(script.combos) == 1
        assert len(script.combos[0].steps) == 3
        # Verify wait steps parsed correctly
        wait_steps = [s for s in script.combos[0].steps if s.function == "wait"]
        assert len(wait_steps) == 2


# ======================================================================
# 3. GPC Generator
# ======================================================================
class TestGPCGenerator:
    def test_list_templates(self):
        from app.gpc.gpc_generator import list_templates
        templates = list_templates()
        assert len(templates) >= 4
        names = [t["name"] for t in templates]
        assert "DayZ Auto Dupe" in names

    def test_generate_from_template(self):
        from app.gpc.gpc_generator import GPCGenerator, get_template
        gen = GPCGenerator()
        tmpl = get_template("DayZ Auto Dupe")
        assert tmpl is not None
        source = gen.generate(tmpl)
        assert source is not None
        assert len(source) > 50
        assert "main" in source

    def test_generate_null_template(self):
        from app.gpc.gpc_generator import GPCGenerator
        gen = GPCGenerator()
        source = gen.generate(None)
        assert "ERROR" in source

    def test_export_to_file(self):
        from app.gpc.gpc_generator import GPCGenerator
        gen = GPCGenerator()
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "test.gpc")
        result = gen.export_to_file("// test script", path)
        assert result is True
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "// test script"


# ======================================================================
# 4. LLM Advisor — keyword routing
# ======================================================================
class TestLLMAdvisor:
    def test_stop_keyword_priority(self):
        from app.ai.llm_advisor import LLMAdvisor
        advisor = LLMAdvisor()
        result = advisor.ask("stop everything")
        assert result["goal"] == "stop"

    def test_start_keyword(self):
        from app.ai.llm_advisor import LLMAdvisor
        advisor = LLMAdvisor()
        result = advisor.ask("start")
        assert result["goal"] == "start"

    def test_chaos_keyword(self):
        from app.ai.llm_advisor import LLMAdvisor
        advisor = LLMAdvisor()
        result = advisor.ask("nuke them with everything")
        assert result["goal"] == "chaos"

    def test_godmode_keyword(self):
        from app.ai.llm_advisor import LLMAdvisor
        advisor = LLMAdvisor()
        result = advisor.ask("god mode on my hotspot")
        assert result["goal"] == "godmode"


# ======================================================================
# 5. Smart Engine
# ======================================================================
class TestSmartEngine:
    def test_recommend_basic(self):
        from app.ai.smart_engine import SmartDisruptionEngine
        from app.ai.network_profiler import NetworkProfile
        engine = SmartDisruptionEngine()
        profile = NetworkProfile(
            target_ip="192.168.1.100",
            avg_rtt_ms=50.0,
            jitter_ms=10.0,
            packet_loss_pct=0.0,
            estimated_bandwidth_kbps=10.0,
        )
        rec = engine.recommend(profile, goal="disconnect", intensity=0.8)
        assert rec is not None
        assert hasattr(rec, 'methods')
        assert hasattr(rec, 'params')
        assert len(rec.methods) > 0

    def test_intensity_clamping(self):
        from app.ai.smart_engine import SmartDisruptionEngine
        from app.ai.network_profiler import NetworkProfile
        engine = SmartDisruptionEngine()
        profile = NetworkProfile(target_ip="10.0.0.1")
        # Should not crash with out-of-range intensity
        rec = engine.recommend(profile, goal="lag", intensity=5.0)
        assert rec is not None
        rec2 = engine.recommend(profile, goal="lag", intensity=-1.0)
        assert rec2 is not None


# ======================================================================
# 6. NativeDisruptEngine — stats API
# ======================================================================
class TestNativeEngineStats:
    def test_get_stats_returns_dict(self):
        """Test that get_stats returns the expected structure (no WinDivert needed)."""
        # We can't actually start the engine without WinDivert, but we can
        # test the stats method on an un-started engine.
        try:
            from app.firewall.native_divert_engine import NativeDisruptEngine
            engine = NativeDisruptEngine(
                target_ip="192.168.1.1",
                filter_str="ip.DstAddr == 192.168.1.1",
                methods=["lag"],
                params={"lag_delay": 500},
            )
            stats = engine.get_stats()
            assert isinstance(stats, dict)
            assert "packets_processed" in stats
            assert "packets_dropped" in stats
            assert "packets_inbound" in stats
            assert "packets_outbound" in stats
            assert "packets_passed" in stats
            assert "alive" in stats
            assert stats["alive"] is False  # not started
            assert stats["target_ip"] == "192.168.1.1"
            assert "lag" in stats["methods"]
        except ImportError:
            pytest.skip("WinDivert not available on this platform")
        except OSError:
            pytest.skip("WinDivert DLL not loadable on this platform")

    def test_format_count_helper(self):
        """Test the _format_count static method on ClumsyControlView."""
        # Import directly — just test the static method
        sys.modules.pop('app.gui.clumsy_control', None)
        try:
            from app.gui.clumsy_control import ClumsyControlView
            assert ClumsyControlView._format_count(0) == "0"
            assert ClumsyControlView._format_count(999) == "999"
            assert ClumsyControlView._format_count(1000) == "1.0K"
            assert ClumsyControlView._format_count(1500) == "1.5K"
            assert ClumsyControlView._format_count(1_000_000) == "1.0M"
            assert ClumsyControlView._format_count(2_500_000) == "2.5M"
        except ImportError:
            pytest.skip("PyQt6 not available")


# ======================================================================
# 7. Device Bridge
# ======================================================================
class TestDeviceBridge:
    def test_scan_devices_returns_list(self):
        from app.gpc.device_bridge import scan_devices
        result = scan_devices()
        assert isinstance(result, list)

    def test_is_device_connected(self):
        from app.gpc.device_bridge import is_device_connected
        # No device attached in test env — should return False
        assert is_device_connected() is False


# ======================================================================
# 8. Data Persistence — basics
# ======================================================================
class TestDataPersistence:
    def test_nickname_manager_get_set(self):
        from app.core.data_persistence import nickname_manager
        # Should not crash
        nick = nickname_manager.get_nickname(mac="00:00:00:00:00:00", ip="1.2.3.4")
        # May or may not have a nickname — just verify it returns str or None
        assert nick is None or isinstance(nick, str)

    def test_settings_manager(self):
        from app.core.data_persistence import settings_manager
        # settings_manager stores settings as a dict attribute
        settings = settings_manager.settings
        assert isinstance(settings, dict)


# ======================================================================
# 9. Version consistency
# ======================================================================
class TestVersion:
    def test_main_version(self):
        with open(os.path.join(ROOT, "app", "main.py")) as f:
            content = f.read()
        assert "3.5.0" in content

    def test_changelog_has_v350(self):
        with open(os.path.join(ROOT, "CHANGELOG.md")) as f:
            content = f.read()
        assert "v3.5.0" in content

    def test_roadmap_has_v350(self):
        with open(os.path.join(ROOT, "ROADMAP.md")) as f:
            content = f.read()
        assert "v3.5.0" in content

    def test_readme_has_v350(self):
        with open(os.path.join(ROOT, "README.md")) as f:
            content = f.read()
        assert "v3.5.0" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
