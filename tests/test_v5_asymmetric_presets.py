#!/usr/bin/env python3
"""Tests for v5 Phase 4: Asymmetric Direction Engine."""

import unittest

from app.firewall.asymmetric_presets import (
    AsymmetricPreset,
    AsymmetricConfigBuilder,
    ALL_PRESETS,
    get_preset,
    list_presets,
    get_preset_names,
    GODMODE_STANDARD,
    GHOST_MODE,
    DESYNC_STANDARD,
    PHANTOM_MODE,
)


class TestAsymmetricPreset(unittest.TestCase):
    def test_to_engine_config(self):
        config = GODMODE_STANDARD.to_engine_config()
        self.assertIn("methods", config)
        self.assertIn("params", config)
        self.assertIn("godmode", config["methods"])

    def test_config_is_deep_copy(self):
        """Modifying returned config shouldn't affect preset."""
        config = GODMODE_STANDARD.to_engine_config()
        config["params"]["godmode_lag_ms"] = 9999
        # Original should be unchanged
        fresh = GODMODE_STANDARD.to_engine_config()
        self.assertEqual(fresh["params"]["godmode_lag_ms"], 2000)


class TestPresetRegistry(unittest.TestCase):
    def test_all_presets_populated(self):
        self.assertGreater(len(ALL_PRESETS), 10)

    def test_get_preset_case_insensitive(self):
        preset = get_preset("GODMODE")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.name, "God Mode")

    def test_get_preset_unknown(self):
        self.assertIsNone(get_preset("nonexistent_preset"))

    def test_list_presets_all(self):
        presets = list_presets()
        self.assertGreater(len(presets), 10)

    def test_list_presets_by_category(self):
        stealth = list_presets("stealth")
        for p in stealth:
            self.assertEqual(p.category, "stealth")

    def test_get_preset_names(self):
        names = get_preset_names()
        self.assertIn("godmode", names)
        self.assertIn("ghost", names)
        self.assertIn("phantom", names)

    def test_all_presets_have_methods(self):
        for name, preset in ALL_PRESETS.items():
            self.assertGreater(len(preset.methods), 0,
                               f"Preset '{name}' has no methods")

    def test_all_presets_have_params(self):
        for name, preset in ALL_PRESETS.items():
            self.assertIsInstance(preset.params, dict,
                                 f"Preset '{name}' params not dict")

    def test_effectiveness_range(self):
        for name, preset in ALL_PRESETS.items():
            self.assertGreaterEqual(preset.effectiveness, 0.0)
            self.assertLessEqual(preset.effectiveness, 1.0)

    def test_detectability_range(self):
        for name, preset in ALL_PRESETS.items():
            self.assertGreaterEqual(preset.detectability, 0.0)
            self.assertLessEqual(preset.detectability, 1.0)


class TestPresetContent(unittest.TestCase):
    """Verify specific presets have correct structure."""

    def test_godmode_standard(self):
        self.assertIn("godmode", GODMODE_STANDARD.methods)
        self.assertEqual(GODMODE_STANDARD.params["godmode_lag_ms"], 2000)

    def test_ghost_mode(self):
        self.assertIn("drop", GHOST_MODE.methods)
        self.assertEqual(GHOST_MODE.params["drop_direction"], "outbound")

    def test_desync_standard(self):
        self.assertIn("lag", DESYNC_STANDARD.methods)
        self.assertIn("duplicate", DESYNC_STANDARD.methods)
        self.assertEqual(DESYNC_STANDARD.params["lag_direction"], "inbound")
        self.assertEqual(DESYNC_STANDARD.params["duplicate_direction"], "outbound")

    def test_phantom_mode(self):
        self.assertIn("pulse", PHANTOM_MODE.methods)
        self.assertEqual(PHANTOM_MODE.params["pulse_burst_ticks"], 3)
        self.assertEqual(PHANTOM_MODE.params["pulse_rest_ticks"], 5)


class TestAsymmetricConfigBuilder(unittest.TestCase):
    def test_add_inbound(self):
        config = (AsymmetricConfigBuilder()
                  .add_inbound("lag", lag_delay=500)
                  .build())
        self.assertIn("lag", config["methods"])
        self.assertEqual(config["params"]["lag_direction"], "inbound")
        self.assertEqual(config["params"]["lag_delay"], 500)

    def test_add_outbound(self):
        config = (AsymmetricConfigBuilder()
                  .add_outbound("drop", drop_chance=80)
                  .build())
        self.assertEqual(config["params"]["drop_direction"], "outbound")

    def test_add_both(self):
        config = (AsymmetricConfigBuilder()
                  .add_both("corrupt", tamper_chance=10)
                  .build())
        self.assertEqual(config["params"]["corrupt_direction"], "both")

    def test_from_preset(self):
        config = (AsymmetricConfigBuilder()
                  .from_preset("godmode")
                  .set_param("godmode_lag_ms", 3000)
                  .build())
        self.assertIn("godmode", config["methods"])
        self.assertEqual(config["params"]["godmode_lag_ms"], 3000)

    def test_multi_module(self):
        config = (AsymmetricConfigBuilder()
                  .add_inbound("lag", lag_delay=200)
                  .add_outbound("drop", drop_chance=50)
                  .add_both("corrupt", tamper_chance=5)
                  .build())
        self.assertEqual(len(config["methods"]), 3)
        self.assertEqual(config["params"]["lag_direction"], "inbound")
        self.assertEqual(config["params"]["drop_direction"], "outbound")
        self.assertEqual(config["params"]["corrupt_direction"], "both")


if __name__ == "__main__":
    unittest.main()
